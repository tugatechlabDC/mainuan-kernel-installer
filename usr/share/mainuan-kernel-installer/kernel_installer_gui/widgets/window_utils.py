"""
Window helpers: title bar with minimize / maximize / close for every window
and dialog, and sizing that always fits the usable screen area (excluding
panels and docks).
"""

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib

from .. import APP_NAME

# Window buttons on the right: minimize, maximize, close
DECORATION_LAYOUT = ":minimize,maximize,close"


def apply_titlebar(window: Gtk.Window, title: str = None, subtitle: str = None) -> Gtk.HeaderBar:
    """
    Give ``window`` a title bar with minimize, maximize and close buttons.
    Must be called before the window is shown.
    """
    header = Gtk.HeaderBar()
    header.set_show_close_button(True)
    header.set_decoration_layout(DECORATION_LAYOUT)
    header.set_title(title or window.get_title() or APP_NAME)
    if subtitle:
        header.set_subtitle(subtitle)
    window.set_titlebar(header)
    window.set_resizable(True)
    window.set_deletable(True)
    # NORMAL hint: window managers keep minimize / maximize available
    window.set_type_hint(Gdk.WindowTypeHint.NORMAL)
    header.show()
    return header


class MessageDialog(Gtk.MessageDialog):
    """Gtk.MessageDialog that always has a full title bar."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('use_header_bar', 0)
        super().__init__(*args, **kwargs)
        apply_titlebar(self, APP_NAME)


class AboutDialog(Gtk.AboutDialog):
    """Gtk.AboutDialog that always has a full title bar."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('use_header_bar', 0)
        super().__init__(*args, **kwargs)
        apply_titlebar(self, APP_NAME)


# ----------------------------------------------------------------- screen fit
def get_workarea(window: Gtk.Window = None) -> Gdk.Rectangle:
    """Usable area (monitor minus panels) of the monitor showing ``window``."""
    display = Gdk.Display.get_default()
    monitor = None
    try:
        if window is not None and window.get_window() is not None:
            monitor = display.get_monitor_at_window(window.get_window())
        if monitor is None:
            monitor = display.get_primary_monitor() or display.get_monitor(0)
        return monitor.get_workarea()
    except Exception:
        return None


def fit_default_size(window: Gtk.Window, pref_w: int, pref_h: int,
                     w_ratio: float = 0.92, h_ratio: float = 0.88) -> None:
    """Set a default size no larger than a share of the usable screen area."""
    wa = get_workarea()
    if wa is None:
        window.set_default_size(pref_w, pref_h)
        return
    window.set_default_size(min(pref_w, int(wa.width * w_ratio)),
                            min(pref_h, int(wa.height * h_ratio)))


def keep_inside_workarea(window: Gtk.Window) -> bool:
    """
    Shrink / move the window so it never hides behind a panel or leaves the
    screen. Safe to call repeatedly (e.g. on map and when the monitor changes).
    """
    try:
        if window.is_maximized() or window.get_window() is None:
            return False
        wa = get_workarea(window)
        if wa is None:
            return False
        w, h = window.get_size()
        nw, nh = min(w, wa.width), min(h, int(wa.height * 0.96))
        if (nw, nh) != (w, h):
            window.resize(nw, nh)
        x, y = window.get_position()
        nx = max(wa.x, min(x, wa.x + wa.width - nw))
        ny = max(wa.y, min(y, wa.y + wa.height - nh))
        if (nx, ny) != (x, y):
            window.move(nx, ny)
    except Exception:
        pass
    return False  # for GLib.idle_add / timeout_add (run once)


def enable_auto_fit(window: Gtk.Window) -> None:
    """Re-check the window position/size when it is shown or the screen changes."""
    def schedule(*args):
        GLib.timeout_add(200, keep_inside_workarea, window)
        return False

    window.connect('map-event', schedule)
    screen = window.get_screen()
    if screen is not None:
        screen.connect('monitors-changed', schedule)
        screen.connect('size-changed', schedule)
