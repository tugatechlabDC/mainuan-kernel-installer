"""
Pre-built kernels section: lists RT, LTS and XanMod kernels available for
installation and lets the user install or remove them.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from typing import Dict, List, Optional

from ..core.packaged import PackagedKernel, CATEGORIES
from ..core.recommend import CAT_LTS, CAT_RT, CAT_XANMOD
from ..locale.i18n import _
from .profile_selector import load_asset_icon


class PackagedKernelsView(Gtk.Box):
    """Tabs (RT / LTS / XanMod) with the list of kernels available to install."""
    
    __gsignals__ = {
        'install-requested': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'remove-requested': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        'update-lists-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'reload-requested': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        
        self._lists: Dict[str, Gtk.ListBox] = {}
        self._rows: Dict[str, Dict[str, Gtk.ListBoxRow]] = {c: {} for c in CATEGORIES}
        
        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=_("📦 Pre-built kernels (RT, LTS, XanMod)"))
        title.get_style_context().add_class('section-header')
        title.set_halign(Gtk.Align.START)
        header.pack_start(title, True, True, 0)
        
        reload_btn = Gtk.Button()
        reload_btn.set_image(Gtk.Image.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON))
        reload_btn.set_tooltip_text(_("Refresh list"))
        reload_btn.connect('clicked', lambda b: self.emit('reload-requested'))
        header.pack_end(reload_btn, False, False, 0)
        
        update_btn = Gtk.Button(label=_("Update package lists"))
        update_btn.set_tooltip_text(_("Runs apt update (requires password)"))
        update_btn.connect('clicked', lambda b: self.emit('update-lists-requested'))
        header.pack_end(update_btn, False, False, 0)
        self.pack_start(header, False, False, 0)
        
        # Category switcher
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self._stack)
        switcher.set_halign(Gtk.Align.CENTER)
        self.pack_start(switcher, False, False, 0)
        
        pages = (
            (CAT_RT, "RT", _("Real-time and low-latency kernels for audio, video and industrial use.")),
            (CAT_LTS, "LTS", _("Long-term support kernels: the most stable and compatible choice.")),
            (CAT_XANMOD, "XanMod", _("XanMod kernels: tuned for desktop responsiveness, gaming and performance. "
                                    "Installing one adds the official XanMod repository.")),
        )
        for cat, label, desc in pages:
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            d = Gtk.Label(label=desc)
            d.set_halign(Gtk.Align.START)
            d.set_xalign(0)
            d.set_line_wrap(True)
            d.get_style_context().add_class('dim-label')
            page.pack_start(d, False, False, 0)
            
            lb = Gtk.ListBox()
            lb.set_selection_mode(Gtk.SelectionMode.SINGLE)
            lb.get_style_context().add_class('history-list')
            self._lists[cat] = lb
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_min_content_height(120)
            scroll.set_vexpand(True)
            scroll.set_shadow_type(Gtk.ShadowType.IN)
            scroll.add(lb)
            page.pack_start(scroll, True, True, 0)
            self._stack.add_titled(page, cat, label)
        self.pack_start(self._stack, True, True, 0)
        
        self._status = Gtk.Label(label="")
        self._status.set_halign(Gtk.Align.START)
        self._status.get_style_context().add_class('dim-label')
        self.pack_start(self._status, False, False, 0)
        
        self.show_all()
    
    # ------------------------------------------------------------------ data
    def _clear(self) -> None:
        for cat, lb in self._lists.items():
            for child in lb.get_children():
                lb.remove(child)
            self._rows[cat] = {}
    
    def _placeholder(self, cat: str, text: str) -> None:
        lbl = Gtk.Label(label=text)
        lbl.get_style_context().add_class('dim-label')
        lbl.set_margin_top(16)
        lbl.set_margin_bottom(16)
        lbl.set_line_wrap(True)
        self._lists[cat].add(lbl)
        self._lists[cat].show_all()
    
    def set_loading(self) -> None:
        self._clear()
        for cat in CATEGORIES:
            self._placeholder(cat, _("Loading available kernels..."))
        self._status.set_text("")
    
    def set_unsupported(self, message: str) -> None:
        self._clear()
        for cat in CATEGORIES:
            self._placeholder(cat, message)
    
    def set_kernels(self, kernels: Dict[str, List[PackagedKernel]]) -> None:
        self._clear()
        for cat in CATEGORIES:
            items = kernels.get(cat, [])
            if not items:
                self._placeholder(cat, _("No kernels of this type are available in your repositories. "
                                         "Try \"Update package lists\"."))
                continue
            for k in items:
                row = self._create_row(k)
                self._rows[cat][k.package] = row
                self._lists[cat].add(row)
            self._lists[cat].show_all()
        total = sum(len(v) for v in kernels.values())
        self._status.set_text(_("%(n)d kernels listed") % {'n': total})
    
    def _create_row(self, k: PackagedKernel) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        for m in ('top', 'bottom'):
            getattr(box, f'set_margin_{m}')(6)
        box.set_margin_start(8)
        box.set_margin_end(8)
        
        icon_name = {CAT_RT: 'category-rt', CAT_LTS: 'category-lts', CAT_XANMOD: 'category-xanmod'}[k.category]
        box.pack_start(load_asset_icon(icon_name, 36), False, False, 0)
        
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=k.title)
        title.set_halign(Gtk.Align.START)
        title.get_style_context().add_class('kernel-row-title')
        info.pack_start(title, False, False, 0)
        
        parts = [k.package]
        if k.installed:
            parts.append(_("installed %(v)s") % {'v': k.installed_version})
        if k.candidate and k.candidate != k.installed_version:
            parts.append(_("available %(v)s") % {'v': k.candidate})
        sub = Gtk.Label(label=" · ".join(parts))
        sub.set_halign(Gtk.Align.START)
        sub.set_ellipsize(3)  # Pango.EllipsizeMode.END
        sub.get_style_context().add_class('dim-label')
        info.pack_start(sub, False, False, 0)
        if k.description:
            desc = Gtk.Label(label=k.description)
            desc.set_halign(Gtk.Align.START)
            desc.set_xalign(0)
            desc.set_line_wrap(True)
            desc.get_style_context().add_class('dim-label')
            info.pack_start(desc, False, False, 0)
        box.pack_start(info, True, True, 0)
        
        if k.is_running:
            badge = Gtk.Label(label=_("Running"))
            badge.get_style_context().add_class('status-running')
            box.pack_start(badge, False, False, 0)
        elif k.installed:
            badge = Gtk.Label(label=_("Installed"))
            badge.get_style_context().add_class('status-installed')
            box.pack_start(badge, False, False, 0)
        
        if k.installed:
            btn = Gtk.Button(label=_("Remove"))
            btn.get_style_context().add_class('destructive-action')
            if k.is_running:
                btn.set_sensitive(False)
                btn.set_tooltip_text(_("Cannot remove the currently running kernel"))
            btn.connect('clicked', lambda b, kk=k: self.emit('remove-requested', kk))
        else:
            btn = Gtk.Button(label=_("Install"))
            btn.get_style_context().add_class('suggested-action')
            btn.connect('clicked', lambda b, kk=k: self.emit('install-requested', kk))
        box.pack_start(btn, False, False, 0)
        
        row.add(box)
        return row
    
    # ------------------------------------------------------------ navigation
    def focus_package(self, category: str, package: Optional[str] = None) -> None:
        """Show a category tab and highlight a package (used by the recommendation)."""
        if category not in self._lists:
            return
        self._stack.set_visible_child_name(category)
        row = self._rows.get(category, {}).get(package) if package else None
        if row is not None:
            self._lists[category].select_row(row)
            row.grab_focus()
