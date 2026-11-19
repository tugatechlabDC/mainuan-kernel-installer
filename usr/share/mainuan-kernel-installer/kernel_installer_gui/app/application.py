"""
GTK Application class for Mainuan Kernel Installer.
Handles application lifecycle, theme detection, and CSS loading.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, Gio, GLib

import os
from pathlib import Path

from .main_window import KernelInstallerWindow
from ..core.notifications import get_notification_manager
from ..core.kernel import KernelManager
from ..locale.i18n import _
from .. import __version__, APP_NAME, APP_ID
from ..widgets.window_utils import MessageDialog, AboutDialog


class KernelInstallerApp(Gtk.Application):
    """Main GTK Application for Mainuan Kernel Installer."""
    
    APP_ID = APP_ID
    
    def __init__(self, force_new=False):
        flags = Gio.ApplicationFlags.FLAGS_NONE
        if force_new:
            flags |= Gio.ApplicationFlags.NON_UNIQUE
            
        super().__init__(
            application_id=self.APP_ID,
            flags=flags
        )
        
        self._window = None
        self._kernel_manager = KernelManager()
    
    def do_activate(self) -> None:
        """Called when application is activated (e.g. at startup)."""
        if not self._window:
            self._window = KernelInstallerWindow(self)
            # Connect key press event for shortcuts
            self._window.connect('key-press-event', self._on_key_press)
        
        self._window.present()
        
        # Schedule dependency check only on first activation if needed
        # We use a flag to avoid re-triggering on multiple activations
        if not hasattr(self, '_dep_checked'):
            self._dep_checked = True
            GLib.idle_add(self._check_dependencies_threaded)
    
    def do_startup(self) -> None:
        """Called when application starts."""
        Gtk.Application.do_startup(self)
        
        # Load CSS
        self._load_css()
        
        # Setup actions first
        self._setup_actions()
        
        # Setup keyboard shortcuts after actions
        self._setup_accelerators()
        
        # Setup notification manager
        notifier = get_notification_manager()
        notifier.set_application(self)

    def _check_dependencies_threaded(self) -> bool:
        """Interact with main window to run check in thread."""
        # Switch UI to progress mode
        self._window.show_dependency_check_ui()
        
        import threading
        
        def run_check():
            try:
                from ..core.distro import DistroDetector
                distro = DistroDetector()
                
                # We can't get granular progress from apt easily without complex parsing,
                # but at least the UI won't freeze.
                GLib.idle_add(self._window.update_dependency_progress, 
                             _("Verifying environment (requires password)..."))
                
                # This blocks this thread, but UI stays alive
                success = distro.install_dependencies()
                
                if success:
                    GLib.idle_add(self._window.update_dependency_progress, 
                                 _("Dependencies installed/verified."))
                    # Small delay to let user see "Done"
                    import time
                    time.sleep(1.0)
                    GLib.idle_add(self._window.hide_dependency_check_ui, True)
                else:
                    GLib.idle_add(self._window.update_dependency_progress, 
                                 _("Error installing dependencies."))
                    GLib.idle_add(self._window.hide_dependency_check_ui, False)
                    
            except Exception as e:
                print(f"Dependency thread error: {e}")
                GLib.idle_add(self._window.update_dependency_progress, f"Error: {e}")
                
        thread = threading.Thread(target=run_check, daemon=True)
        thread.start()
            
        return False  # Don't call again
    
    def _on_key_press(self, widget, event) -> bool:
        """Handle key press events for shortcuts."""
        keyval = event.keyval
        state = event.state & Gtk.accelerator_get_default_mod_mask()
        
        # Ctrl+Q or Ctrl+W to quit
        if state == Gdk.ModifierType.CONTROL_MASK:
            if keyval in (Gdk.KEY_q, Gdk.KEY_Q, Gdk.KEY_w, Gdk.KEY_W):
                self.quit()
                return True
        
        # F5 to refresh
        if keyval == Gdk.KEY_F5:
            if self._window:
                self._window.refresh_versions()
            return True
        
        # Escape to close dialogs or go back
        if keyval == Gdk.KEY_Escape:
            # Could be used for canceling
            pass
        
        return False
    
    def _setup_accelerators(self) -> None:
        """Setup keyboard shortcuts."""
        # These are for menu display, actual handling is in _on_key_press
        self.set_accels_for_action("app.quit", ["<Control>q", "<Control>w"])
        self.set_accels_for_action("app.refresh", ["F5"])
    
    def _load_css(self) -> None:
        """Load and apply CSS styles."""
        css_provider = Gtk.CssProvider()
        
        # Try to load from package data directory
        css_paths = [
            Path(__file__).parent.parent / "data" / "style.css",
            Path("/usr/share/mainuan-kernel-installer/style.css"),
            Path.home() / ".config" / "mainuan-kernel-installer" / "style.css",
        ]
        
        css_content = self._get_default_css()
        
        for path in css_paths:
            if path.exists():
                try:
                    css_provider.load_from_path(str(path))
                    css_content = None
                    break
                except Exception:
                    continue
        
        if css_content:
            css_provider.load_from_data(css_content.encode())
        
        # Apply to screen
        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    
    def _get_default_css(self) -> str:
        """Get default CSS styles that adapt to light/dark themes."""
        return '''
/* Mainuan Mainuan Kernel Installer Styles */
/* Uses GTK3 theme variables for automatic light/dark adaptation */

/* Profile Cards */
.profile-card {
    padding: 12px;
    border-radius: 12px;
    border: 2px solid alpha(@theme_fg_color, 0.1);
    background: alpha(@theme_bg_color, 0.5);
    transition: all 200ms ease;
    min-width: 160px;
}

.profile-card:hover {
    border-color: alpha(@theme_selected_bg_color, 0.5);
    background: alpha(@theme_selected_bg_color, 0.1);
}

.profile-card:checked {
    border-color: @theme_selected_bg_color;
    background: alpha(@theme_selected_bg_color, 0.15);
    box-shadow: 0 0 0 3px alpha(@theme_selected_bg_color, 0.2);
}

.profile-name {
    font-weight: bold;
    font-size: 1.1em;
}

.profile-description {
    font-size: 0.9em;
    opacity: 0.8;
}

/* Section Headers */
.section-header {
    font-weight: bold;
    font-size: 1.05em;
    opacity: 0.9;
}

/* Install Button */
.install-button {
    padding: 12px 24px;
    font-size: 1.1em;
    font-weight: bold;
    border-radius: 8px;
}

/* History List */
.history-list {
    background: transparent;
}

.history-list row {
    border-radius: 6px;
    margin: 2px 0;
}

.history-list row:hover {
    background: alpha(@theme_fg_color, 0.05);
}

.current-kernel {
    font-weight: bold;
}

.profile-badge {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.85em;
    background: alpha(@theme_selected_bg_color, 0.2);
}

/* Load Indicator */
.load-percentage {
    font-size: 1.5em;
    font-weight: bold;
}

/* Level Bar Colors */
levelbar block.low {
    background-color: #4caf50;
}

levelbar block.high {
    background-color: #ff9800;
}

levelbar block.full {
    background-color: #f44336;
}

/* Dim Labels */
.dim-label {
    opacity: 0.7;
    font-size: 0.9em;
}

/* Error Text */
.error {
    color: #f44336;
}

/* Progress Bar */
progressbar progress {
    border-radius: 4px;
}

progressbar trough {
    border-radius: 4px;
}

/* ===== Mainuan brand colours (from the Mainuan logo) ===== */
@define-color mainuan_teal #0cd0db;
@define-color mainuan_teal_mid #06adb7;
@define-color mainuan_teal_dark #018993;

.profile-card:hover {
  border-color: alpha(@mainuan_teal_mid, 0.7);
  background: alpha(@mainuan_teal, 0.10);
}

.profile-card:checked {
  border-color: @mainuan_teal_dark;
  background: alpha(@mainuan_teal, 0.18);
  box-shadow: 0 0 0 3px alpha(@mainuan_teal, 0.28);
}

.section-header {
  color: @mainuan_teal_dark;
}

.profile-badge {
  background: alpha(@mainuan_teal, 0.22);
  color: @mainuan_teal_dark;
}

button.suggested-action,
button.install-button {
  background-image: linear-gradient(to bottom, @mainuan_teal, @mainuan_teal_dark);
  color: #ffffff;
  border-color: @mainuan_teal_dark;
  text-shadow: none;
}

button.suggested-action:hover,
button.install-button:hover {
  background-image: linear-gradient(to bottom, #3fe0e9, @mainuan_teal_mid);
}

button.suggested-action:disabled,
button.install-button:disabled {
  background-image: none;
  background-color: alpha(@mainuan_teal_dark, 0.35);
  color: alpha(#ffffff, 0.8);
}

/* Recommended-kernel banner */
.recommend-banner {
  padding: 10px 14px;
  border-radius: 12px;
  background-image: linear-gradient(to right, alpha(@mainuan_teal, 0.22), alpha(@mainuan_teal_dark, 0.10));
  border: 1px solid alpha(@mainuan_teal_dark, 0.45);
}

.recommend-title {
  font-weight: bold;
  font-size: 1.1em;
}

/* Pre-built kernel rows (RT / LTS / XanMod) */
.kernel-row-title {
  font-weight: bold;
}

.status-installed {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.85em;
  background: alpha(@mainuan_teal, 0.25);
  color: @mainuan_teal_dark;
  font-weight: bold;
}

.status-running {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.85em;
  background: @mainuan_teal_dark;
  color: #ffffff;
  font-weight: bold;
}

.check-ok { color: #2e9e5b; }
.check-warn { color: #d98a00; }
.check-fail { color: #d93a3a; }
.check-info { color: @mainuan_teal_dark; }

/* ===== Main tabs (Compile / RT-LTS-XanMod / Installed kernels) ===== */
notebook.main-tabs > header {
  padding: 6px 6px 0 6px;
  background: alpha(@mainuan_teal, 0.06);
  border-bottom: 2px solid alpha(@mainuan_teal_dark, 0.45);
}

notebook.main-tabs > header > tabs > tab {
  padding: 8px 18px;
  margin: 0 4px;
  min-height: 30px;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 12px 12px 0 0;
  background: transparent;
  outline: none;
}

notebook.main-tabs > header > tabs > tab:hover {
  background: alpha(@mainuan_teal, 0.14);
  border-color: alpha(@mainuan_teal_mid, 0.4);
}

notebook.main-tabs > header > tabs > tab:checked {
  background-image: linear-gradient(to bottom, alpha(@mainuan_teal, 0.38), alpha(@mainuan_teal, 0.12));
  border-color: alpha(@mainuan_teal_dark, 0.6);
  box-shadow: inset 0 -3px 0 @mainuan_teal_dark;
}

notebook.main-tabs > header > tabs > tab label.tab-title {
  font-weight: bold;
}

notebook.main-tabs > header > tabs > tab:checked label.tab-title {
  color: @mainuan_teal_dark;
}
'''
    
    def _setup_actions(self) -> None:
        """Setup application actions for menu."""
        # Quit action
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self._on_quit)
        self.add_action(quit_action)
        
        # Refresh action
        refresh_action = Gio.SimpleAction.new("refresh", None)
        refresh_action.connect("activate", self._on_refresh)
        self.add_action(refresh_action)
        
        # About action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)
        
        # Recommended-kernel action
        recommend_action = Gio.SimpleAction.new("recommend", None)
        recommend_action.connect("activate", self._on_recommend)
        self.add_action(recommend_action)
        
        # Cleanup action
        cleanup_action = Gio.SimpleAction.new("cleanup", None)
        cleanup_action.connect("activate", self._on_cleanup)
        self.add_action(cleanup_action)
    
    def _on_quit(self, action: Gio.SimpleAction, param) -> None:
        """Quit the application."""
        self.quit()
    
    def _on_refresh(self, action: Gio.SimpleAction, param) -> None:
        """Refresh kernel versions."""
        if self._window:
            self._window.refresh_versions()
    
    def _on_recommend(self, action: Gio.SimpleAction, param) -> None:
        """Run the hardware test and show the recommended kernel."""
        if self._window:
            self._window.show_recommendation()
    
    def _on_about(self, action: Gio.SimpleAction, param) -> None:
        """Show about dialog."""
        about = AboutDialog(transient_for=self._window, modal=True)
        about.set_program_name(APP_NAME)
        about.set_version(__version__)
        about.set_comments(
            _("A graphical interface for downloading, compiling and installing the Linux kernel with optimized profiles.")
        )
        about.set_authors(["David Caixinha"])
        about.set_copyright("© 2026 David Caixinha")
        about.set_license_type(Gtk.License.GPL_3_0)
        about.set_logo_icon_name("org.mainuan.kernel-installer")
        
        about.run()
        about.destroy()
    
    def _on_cleanup(self, action: Gio.SimpleAction, param) -> None:
        """Clean up build files."""
        dialog = MessageDialog(
            transient_for=self._window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Clean build files?")
        )
        dialog.format_secondary_text(
            _("All temporary files in ~/kernel_build will be deleted.\n"
            "This will free up disk space.")
        )
        
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.YES:
            if self._kernel_manager.cleanup_build_files():
                self._show_info(_("Build files deleted."))
            else:
                self._show_error(_("Error cleaning files."))
    
    def _show_info(self, message: str) -> None:
        """Show info dialog."""
        dialog = MessageDialog(
            transient_for=self._window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.run()
        dialog.destroy()
    
    def _show_error(self, message: str) -> None:
        """Show error dialog."""
        dialog = MessageDialog(
            transient_for=self._window,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=message
        )
        dialog.run()
        dialog.destroy()
