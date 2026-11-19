"""
Recommended-kernel dialog: runs the hardware test in the background and
shows the checks plus the kernel recommended for this computer.
"""

import threading

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib

from ..core.recommend import (run_hardware_test, TestResult, Suggestion,
                              CAT_COMPILE, CAT_LTS, CAT_RT, CAT_XANMOD)
from ..locale.i18n import _
from .profile_selector import load_asset_icon
from .window_utils import apply_titlebar, fit_default_size

_STATUS_ICON = {"ok": ("✔", "check-ok"), "warn": ("⚠", "check-warn"),
                "fail": ("✖", "check-fail"), "info": ("ℹ", "check-info")}


class RecommendDialog(Gtk.Dialog):
    """Modal dialog. After RESPONSE_ACCEPT, read ``chosen`` for the suggestion to apply."""
    
    def __init__(self, parent: Gtk.Window, kernel_manager, distro, apt_based: bool):
        super().__init__(title=_("Recommended kernel for this computer"), transient_for=parent, modal=True,
                         use_header_bar=0)
        apply_titlebar(self, _("Recommended kernel for this computer"))
        fit_default_size(self, 620, 640)
        self.chosen = None
        self.result = None
        self._km = kernel_manager
        self._distro_name = distro.detect().pretty_name
        self._apt_based = apt_based
        
        self.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        self._apply_btn = self.add_button(_("Apply recommendation"), Gtk.ResponseType.ACCEPT)
        self._apply_btn.get_style_context().add_class('suggested-action')
        self._apply_btn.set_sensitive(False)
        
        self._body = self.get_content_area()
        self._body.set_spacing(10)
        self._body.set_border_width(16)
        
        # Progress page
        self._progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._progress_box.set_valign(Gtk.Align.CENTER)
        self._progress_box.set_vexpand(True)
        spinner = Gtk.Spinner()
        spinner.set_size_request(48, 48)
        spinner.start()
        self._progress_box.pack_start(spinner, False, False, 0)
        self._progress_label = Gtk.Label(label=_("Testing your hardware..."))
        self._progress_box.pack_start(self._progress_label, False, False, 0)
        self._body.pack_start(self._progress_box, True, True, 0)
        self.show_all()
        
        threading.Thread(target=self._worker, daemon=True).start()
    
    # --------------------------------------------------------------- worker
    def _worker(self) -> None:
        try:
            versions = self._km.fetch_available_versions()
            GLib.idle_add(self._set_progress, _("Testing your hardware..."))
            result = run_hardware_test(
                versions, self._distro_name, self._apt_based,
                progress=lambda m: GLib.idle_add(self._set_progress, m))
            GLib.idle_add(self._show_result, result)
        except Exception as e:  # never leave the dialog spinning forever
            GLib.idle_add(self._show_error, str(e))
    
    def _set_progress(self, text: str) -> bool:
        self._progress_label.set_text(text)
        return False
    
    def _show_error(self, message: str) -> bool:
        self._progress_label.set_text(_("The hardware test failed: %(e)s") % {'e': message})
        return False
    
    # --------------------------------------------------------------- result
    def _show_result(self, result: TestResult) -> bool:
        self.result = result
        self._body.remove(self._progress_box)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.set_margin_end(8)
        scroll.add(content)
        
        rec = result.recommendation
        
        # --- Recommended card
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.get_style_context().add_class('recommend-banner')
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top.pack_start(load_asset_icon('recommend', 48), False, False, 0)
        tb = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        small = Gtk.Label(label=_("RECOMMENDED FOR YOUR PC"))
        small.set_halign(Gtk.Align.START)
        small.get_style_context().add_class('dim-label')
        tb.pack_start(small, False, False, 0)
        title = Gtk.Label(label=rec.primary.title)
        title.set_halign(Gtk.Align.START)
        title.get_style_context().add_class('recommend-title')
        tb.pack_start(title, False, False, 0)
        top.pack_start(tb, True, True, 0)
        card.pack_start(top, False, False, 0)
        card.pack_start(self._wrapped(rec.primary.detail), False, False, 0)
        for reason in rec.reasons:
            card.pack_start(self._wrapped("• " + reason), False, False, 0)
        content.pack_start(card, False, False, 0)
        
        # --- Test results
        hdr = Gtk.Label(label=_("Hardware test results"))
        hdr.set_halign(Gtk.Align.START)
        hdr.get_style_context().add_class('section-header')
        content.pack_start(hdr, False, False, 0)
        grid = Gtk.Grid(column_spacing=10, row_spacing=5)
        for i, c in enumerate(result.checks):
            symbol, css = _STATUS_ICON.get(c.status, _STATUS_ICON["info"])
            s = Gtk.Label(label=symbol)
            s.get_style_context().add_class(css)
            grid.attach(s, 0, i, 1, 1)
            name = Gtk.Label(label=c.label)
            name.set_halign(Gtk.Align.START)
            name.set_valign(Gtk.Align.START)
            name.get_style_context().add_class('dim-label')
            grid.attach(name, 1, i, 1, 1)
            val = self._wrapped(c.value)
            val.set_hexpand(True)
            grid.attach(val, 2, i, 1, 1)
        content.pack_start(grid, False, False, 0)
        
        # --- Alternatives
        if rec.alternatives:
            ah = Gtk.Label(label=_("Other compatible options"))
            ah.set_halign(Gtk.Align.START)
            ah.get_style_context().add_class('section-header')
            content.pack_start(ah, False, False, 0)
            for alt in rec.alternatives:
                content.pack_start(self._alt_row(alt), False, False, 0)
        
        note = self._wrapped(_("This test is a guide based on the detected hardware and installed software. "
                               "LTS kernels are always the safest choice."))
        note.get_style_context().add_class('dim-label')
        content.pack_start(note, False, False, 0)
        
        self._body.pack_start(scroll, True, True, 0)
        self.chosen = rec.primary
        self._apply_btn.set_sensitive(True)
        self._body.show_all()
        return False
    
    def _alt_row(self, alt: Suggestion) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        t = Gtk.Label(label=alt.title)
        t.set_halign(Gtk.Align.START)
        t.get_style_context().add_class('kernel-row-title')
        info.pack_start(t, False, False, 0)
        info.pack_start(self._wrapped(alt.detail), False, False, 0)
        row.pack_start(info, True, True, 0)
        btn = Gtk.Button(label=_("Use this"))
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect('clicked', self._on_alt_clicked, alt)
        row.pack_start(btn, False, False, 0)
        return row
    
    def _on_alt_clicked(self, button: Gtk.Button, alt: Suggestion) -> None:
        self.chosen = alt
        self.response(Gtk.ResponseType.ACCEPT)
    
    @staticmethod
    def _wrapped(text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.set_halign(Gtk.Align.START)
        lbl.set_xalign(0)
        lbl.set_line_wrap(True)
        lbl.set_max_width_chars(70)
        return lbl
