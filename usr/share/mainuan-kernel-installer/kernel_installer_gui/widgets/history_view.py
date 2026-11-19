"""
History view widget - lists every kernel installed on the system and lets
the user remove the ones that are no longer needed.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from ..core.kernel import KernelManager, InstalledKernel
from ..locale.i18n import _
from typing import Dict, List


class HistoryView(Gtk.Box):
    """
    Widget showing all installed kernels (distribution, LTS, RT, XanMod and
    custom builds) with the option to remove the unwanted ones.
    """
    
    __gsignals__ = {
        # Emitted with a list of kernel version strings to remove
        'remove-kernels': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }
    
    def __init__(self, kernel_manager: KernelManager = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        
        self._kernel_manager = kernel_manager or KernelManager()
        self._checks: Dict[str, Gtk.CheckButton] = {}
        
        # --- Header: title + actions -------------------------------------
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        
        self._title = Gtk.Label(label=_("📜 Installed kernels history"))
        self._title.get_style_context().add_class('section-header')
        self._title.set_halign(Gtk.Align.START)
        header.pack_start(self._title, True, True, 0)
        
        refresh_btn = Gtk.Button()
        refresh_btn.set_image(Gtk.Image.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON))
        refresh_btn.set_tooltip_text(_("Refresh list"))
        refresh_btn.connect('clicked', lambda b: self.refresh())
        header.pack_end(refresh_btn, False, False, 0)
        
        self._remove_selected_btn = Gtk.Button(label=_("🗑 Remove selected"))
        self._remove_selected_btn.get_style_context().add_class('destructive-action')
        self._remove_selected_btn.set_sensitive(False)
        self._remove_selected_btn.connect('clicked', self._on_remove_selected)
        header.pack_end(self._remove_selected_btn, False, False, 0)
        
        self.pack_start(header, False, False, 0)
        
        hint = Gtk.Label(label=_("Tick the kernels you no longer need and press \"Remove selected\", "
                                 "or use the bin icon on a row. The running kernel cannot be removed."))
        hint.set_halign(Gtk.Align.START)
        hint.set_line_wrap(True)
        hint.set_xalign(0)
        hint.get_style_context().add_class('dim-label')
        self.pack_start(hint, False, False, 0)
        
        # --- List -----------------------------------------------------------
        self._list_box = Gtk.ListBox()
        self._list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list_box.get_style_context().add_class('history-list')
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(120)
        scroll.set_vexpand(True)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.add(self._list_box)
        self.pack_start(scroll, True, True, 0)
        
        self.show_all()
    
    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        """Refresh the list from the system."""
        self.set_history(self._kernel_manager.get_installation_history())
    
    def set_history(self, history: List[InstalledKernel]) -> None:
        """Fill the list with the given kernels."""
        for child in self._list_box.get_children():
            self._list_box.remove(child)
        self._checks = {}
        
        if not history:
            empty_label = Gtk.Label(label=_("No kernels installed yet"))
            empty_label.get_style_context().add_class('dim-label')
            empty_label.set_margin_top(12)
            empty_label.set_margin_bottom(12)
            self._list_box.add(empty_label)
            self._title.set_text(_("📜 Installed kernels history"))
        else:
            only_one = len(history) <= 1
            for kernel in history:
                self._list_box.add(self._create_history_row(kernel, only_one))
            self._title.set_text(_("📜 Installed kernels history") + f" ({len(history)})")
        
        self._update_remove_button()
        self._list_box.show_all()
    
    def _create_history_row(self, kernel: InstalledKernel, only_one: bool) -> Gtk.ListBoxRow:
        """Create a row for an installed kernel."""
        row = Gtk.ListBoxRow()
        removable = not kernel.is_current and not only_one
        
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        
        # Selection checkbox
        check = Gtk.CheckButton()
        check.set_sensitive(removable)
        if removable:
            check.set_tooltip_text(_("Select for removal"))
            check.connect('toggled', lambda c: self._update_remove_button())
            self._checks[kernel.version] = check
        box.pack_start(check, False, False, 0)
        
        # Version + date
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        version_label = Gtk.Label(label=kernel.version)
        version_label.set_halign(Gtk.Align.START)
        version_label.set_selectable(False)
        if kernel.is_current:
            version_label.get_style_context().add_class('current-kernel')
        info.pack_start(version_label, False, False, 0)
        
        try:
            from datetime import datetime
            date_str = datetime.fromisoformat(kernel.installed_date).strftime("%Y-%m-%d")
        except Exception:
            date_str = (kernel.installed_date or "")[:10]
        date_label = Gtk.Label(label=_("Installed: %(date)s") % {'date': date_str})
        date_label.set_halign(Gtk.Align.START)
        date_label.get_style_context().add_class('dim-label')
        info.pack_start(date_label, False, False, 0)
        box.pack_start(info, True, True, 0)
        
        # Running indicator
        if kernel.is_current:
            running = Gtk.Label(label=_("Running"))
            running.get_style_context().add_class('status-running')
            box.pack_start(running, False, False, 0)
        
        # Type / profile badge
        profile_label = Gtk.Label(label=_(kernel.profile))
        profile_label.get_style_context().add_class('profile-badge')
        box.pack_start(profile_label, False, False, 0)
        
        # Remove button
        remove_btn = Gtk.Button()
        remove_btn.set_image(Gtk.Image.new_from_icon_name('edit-delete-symbolic', Gtk.IconSize.BUTTON))
        remove_btn.get_style_context().add_class('flat')
        if kernel.is_current:
            remove_btn.set_sensitive(False)
            remove_btn.set_tooltip_text(_("Cannot remove the currently running kernel"))
        elif only_one:
            remove_btn.set_sensitive(False)
            remove_btn.set_tooltip_text(_("Cannot remove the only installed kernel"))
        else:
            remove_btn.set_tooltip_text(_("Remove this kernel"))
            remove_btn.connect('clicked', self._on_remove_clicked, kernel.version)
        box.pack_start(remove_btn, False, False, 0)
        
        row.add(box)
        return row
    
    # --------------------------------------------------------------- actions
    def _selected_versions(self) -> List[str]:
        return [v for v, c in self._checks.items() if c.get_active()]
    
    def _update_remove_button(self) -> None:
        n = len(self._selected_versions())
        self._remove_selected_btn.set_sensitive(n > 0)
        label = _("🗑 Remove selected")
        self._remove_selected_btn.set_label(f"{label} ({n})" if n else label)
    
    def _on_remove_selected(self, button: Gtk.Button) -> None:
        versions = self._selected_versions()
        if versions:
            self.emit('remove-kernels', versions)
    
    def _on_remove_clicked(self, button: Gtk.Button, version: str) -> None:
        """Handle the bin button of a single row."""
        self.emit('remove-kernels', [version])
