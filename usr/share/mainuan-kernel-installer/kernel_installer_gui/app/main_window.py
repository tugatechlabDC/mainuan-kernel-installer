"""
Main application window for Mainuan Kernel Installer.
"""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gio

from ..widgets.profile_selector import ProfileSelector
from ..widgets.version_picker import VersionPicker
from ..widgets.build_progress import BuildProgress
from ..widgets.history_view import HistoryView
from ..widgets.packaged_view import PackagedKernelsView
from ..widgets.recommend_dialog import RecommendDialog
from ..core.packaged import PackagedKernelManager
from ..core.recommend import CAT_COMPILE
from .. import APP_NAME
from ..widgets.window_utils import (MessageDialog, apply_titlebar, fit_default_size,
                                    enable_auto_fit, DECORATION_LAYOUT)
from ..widgets.profile_selector import load_asset_icon
from ..core.kernel import KernelManager
from ..core.distro import DistroDetector
from ..core.profiles import KernelProfile
from ..core.notifications import get_notification_manager
from ..locale.i18n import _

import threading


class KernelInstallerWindow(Gtk.ApplicationWindow):
    """Main window for the Mainuan Kernel Installer application."""
    
    def __init__(self, application: Gtk.Application):
        super().__init__(application=application)
        
        self.set_title(APP_NAME)
        fit_default_size(self, 780, 760)   # never larger than the usable screen area
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("org.mainuan.kernel-installer")
        
        # Initialize managers
        self._kernel_manager = KernelManager()
        self._distro = DistroDetector()
        self._packaged = PackagedKernelManager(self._distro)
        self._building = False
        
        # Header bar
        self._create_header_bar()
        
        # Main content
        self._create_content()
        
        # Load initial data
        GLib.idle_add(self._load_initial_data)
    
    def _create_header_bar(self) -> None:
        """Create the header bar with title and actions."""
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_decoration_layout(DECORATION_LAYOUT)  # minimize, maximize, close
        header.set_title(APP_NAME)
        header.set_subtitle(_("by David Caixinha"))
        
        # App icon managed by window icon setting
        
        # Menu button
        menu_btn = Gtk.MenuButton()
        menu_icon = Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON)
        menu_btn.set_image(menu_icon)
        
        # Create menu
        menu = Gio.Menu()
        menu.append(_("Recommended kernel for this PC"), "app.recommend")
        menu.append(_("Refresh versions (F5)"), "app.refresh")
        menu.append(_("Clean build files"), "app.cleanup")
        menu.append(_("About"), "app.about")
        menu.append(_("Quit (Ctrl+Q)"), "app.quit")
        menu_btn.set_menu_model(menu)
        
        header.pack_end(menu_btn)
        
        self.set_titlebar(header)
    
    def _create_content(self) -> None:
        """Create the main content area."""
        # Main vertical box with margins
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        main_box.set_margin_top(16)
        main_box.set_margin_bottom(16)
        main_box.set_margin_start(24)
        main_box.set_margin_end(24)
        
        # Stack for switching between config and build views
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        
        # === Config page (banner + tabs) ===
        config_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        config_page.pack_start(self._create_recommend_banner(), False, False, 0)
        self._notebook = Gtk.Notebook()
        self._notebook.set_show_border(False)
        self._notebook.get_style_context().add_class("main-tabs")
        config_page.pack_start(self._notebook, True, True, 0)
        
        # --- Tab 1: compile from kernel.org (original content)
        config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        config_box.set_margin_top(12)
        config_box.set_margin_bottom(12)
        config_box.set_margin_start(12)
        config_box.set_margin_end(12)
        
        # Profile selector
        self._profile_selector = ProfileSelector()
        self._profile_selector.connect('profile-changed', self._on_profile_changed)
        config_box.pack_start(self._profile_selector, False, False, 0)
        
        # Separator
        config_box.pack_start(Gtk.Separator(), False, False, 0)
        
        # Version picker
        self._version_picker = VersionPicker(self._kernel_manager)
        config_box.pack_start(self._version_picker, False, False, 0)
        
        # Kernel name entry
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        name_label = Gtk.Label(label=_("Kernel name (suffix)"))
        name_label.set_halign(Gtk.Align.START)
        name_label.get_style_context().add_class('section-header')
        name_box.pack_start(name_label, False, False, 0)
        
        name_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._kernel_name_entry = Gtk.Entry()
        self._kernel_name_entry.set_text("custom")
        self._kernel_name_entry.set_placeholder_text(_("E.g.: gaming, server, my-kernel"))
        self._kernel_name_entry.set_tooltip_text(_("This name will be added to the kernel, e.g.: 6.18.7-custom-gaming"))
        self._kernel_name_entry.set_hexpand(True)
        name_row.pack_start(self._kernel_name_entry, True, True, 0)
        name_box.pack_start(name_row, False, False, 0)
        
        name_hint = Gtk.Label(label=_("Result: 6.x.x-custom-gaming (combined with profile)"))
        name_hint.set_halign(Gtk.Align.START)
        name_hint.get_style_context().add_class('dim-label')
        self._name_hint_label = name_hint
        name_box.pack_start(name_hint, False, False, 0)
        
        # Update hint when name changes
        self._kernel_name_entry.connect('changed', self._on_kernel_name_changed)
        
        config_box.pack_start(name_box, False, False, 0)
        
        # Cleanup option
        self._cleanup_check = Gtk.CheckButton(label=_("Clean build directory after installation (Save disk space)"))
        self._cleanup_check.set_active(True)
        config_box.pack_start(self._cleanup_check, False, False, 0)
        
        # Separator
        config_box.pack_start(Gtk.Separator(), False, False, 0)
        
        # System info - Row 1
        info_box1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        
        # Distro info
        distro_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        distro_label = Gtk.Label(label=_("Distribution:"))
        distro_label.set_halign(Gtk.Align.START)
        distro_label.get_style_context().add_class('dim-label')
        distro_box.pack_start(distro_label, False, False, 0)
        
        self._distro_value = Gtk.Label(label=_("Detecting..."))
        self._distro_value.set_halign(Gtk.Align.START)
        distro_box.pack_start(self._distro_value, False, False, 0)
        info_box1.pack_start(distro_box, True, True, 0)
        
        # Current kernel
        kernel_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        kernel_label = Gtk.Label(label=_("Current kernel:"))
        kernel_label.set_halign(Gtk.Align.START)
        kernel_label.get_style_context().add_class('dim-label')
        kernel_box.pack_start(kernel_label, False, False, 0)
        
        self._kernel_value = Gtk.Label(label="...")
        self._kernel_value.set_halign(Gtk.Align.START)
        kernel_box.pack_start(self._kernel_value, False, False, 0)
        info_box1.pack_start(kernel_box, True, True, 0)
        
        config_box.pack_start(info_box1, False, False, 0)
        
        # System info - Row 2 (Bootloader and Initramfs)
        info_box2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        
        # Bootloader info
        bootloader_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        bootloader_label = Gtk.Label(label=_("Bootloader:"))
        bootloader_label.set_halign(Gtk.Align.START)
        bootloader_label.get_style_context().add_class('dim-label')
        bootloader_box.pack_start(bootloader_label, False, False, 0)
        
        self._bootloader_value = Gtk.Label(label="...")
        self._bootloader_value.set_halign(Gtk.Align.START)
        bootloader_box.pack_start(self._bootloader_value, False, False, 0)
        info_box2.pack_start(bootloader_box, True, True, 0)
        
        # Initramfs info
        initramfs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        initramfs_label = Gtk.Label(label=_("Initramfs:"))
        initramfs_label.set_halign(Gtk.Align.START)
        initramfs_label.get_style_context().add_class('dim-label')
        initramfs_box.pack_start(initramfs_label, False, False, 0)
        
        self._initramfs_value = Gtk.Label(label="...")
        self._initramfs_value.set_halign(Gtk.Align.START)
        initramfs_box.pack_start(self._initramfs_value, False, False, 0)
        info_box2.pack_start(initramfs_box, True, True, 0)
        
        
        config_box.pack_start(info_box2, False, False, 0)
        
        # Dependency progress area (Initially hidden)
        dep_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._dep_label = Gtk.Label(label="")
        self._dep_label.set_halign(Gtk.Align.START)
        self._dep_label.get_style_context().add_class('dim-label')
        dep_box.pack_start(self._dep_label, False, False, 0)
        
        self._dep_progress = Gtk.ProgressBar()
        self._dep_progress.set_show_text(True)
        dep_box.pack_start(self._dep_progress, False, False, 0)
        
        self._dep_box = dep_box # Keep ref to hide/show
        config_box.pack_start(self._dep_box, False, False, 0)
        
        # Install button
        self._install_btn = Gtk.Button(label=_("📥 Download and install kernel"))
        self._install_btn.get_style_context().add_class('suggested-action')
        self._install_btn.get_style_context().add_class('install-button')
        self._install_btn.connect('clicked', self._on_install_clicked)
        config_box.pack_start(self._install_btn, False, False, 8)
        
        compile_scroll = Gtk.ScrolledWindow()
        compile_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        compile_scroll.add(config_box)
        self._add_tab(compile_scroll, "tab-compile", _("Compile"))
        
        # --- Tab 2: pre-built RT / LTS / XanMod kernels
        self._packaged_view = PackagedKernelsView()
        self._packaged_view.set_border_width(12)
        self._packaged_view.connect('install-requested', self._on_pkg_install)
        self._packaged_view.connect('remove-requested', self._on_pkg_remove)
        self._packaged_view.connect('update-lists-requested', self._on_pkg_update_lists)
        self._packaged_view.connect('reload-requested', lambda w: self._load_packaged())
        self._add_tab(self._packaged_view, "tab-packages", "RT / LTS / XanMod")
        
        # --- Tab 3: installed kernels history
        self._history_view = HistoryView(self._kernel_manager)
        self._history_view.set_border_width(12)
        self._history_view.connect('remove-kernels', self._on_remove_kernels)
        self._add_tab(self._history_view, "tab-installed", _("Installed kernels"))
        
        self._stack.add_named(config_page, "config")
        
        # === Build page ===
        build_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        
        self._build_progress = BuildProgress()
        build_box.pack_start(self._build_progress, True, True, 0)
        
        # Cancel button
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_halign(Gtk.Align.END)
        
        self._cancel_btn = Gtk.Button(label=_("Cancel"))
        self._cancel_btn.get_style_context().add_class('destructive-action')
        self._cancel_btn.connect('clicked', self._on_cancel_clicked)
        self._cancel_btn.set_sensitive(False)
        button_box.pack_start(self._cancel_btn, False, False, 0)
        
        self._done_btn = Gtk.Button(label=_("Done"))
        self._done_btn.connect('clicked', self._on_done_clicked)
        self._done_btn.set_no_show_all(True)
        button_box.pack_start(self._done_btn, False, False, 8)
        
        build_box.pack_start(button_box, False, False, 0)
        
        self._stack.add_named(build_box, "build")
        
        main_box.pack_start(self._stack, True, True, 0)
        self.add(main_box)
        
        # Initially hide dependency box
        self._dep_box.hide()
        
        self.show_all()
        # Ensure hidden after show_all
        self._dep_box.hide()
        
        # Always open on the first tab (Compile) and keep the window on screen
        self._notebook.set_current_page(0)
        enable_auto_fit(self)
        self.connect('map', self._on_first_map)
        
        # Pulse timer
        self._pulse_timer_id = None
    
    def _on_first_map(self, widget) -> None:
        """The first time the window is shown, make sure the Compile tab is selected."""
        if not getattr(self, '_tab_reset', False):
            self._tab_reset = True
            self._notebook.set_current_page(0)
    
    def _add_tab(self, page: Gtk.Widget, icon_name: str, text: str) -> None:
        """Add a notebook tab with an icon and a label; tabs share the width evenly."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        box.pack_start(load_asset_icon(icon_name, 24), False, False, 0)
        label = Gtk.Label(label=text)
        label.get_style_context().add_class('tab-title')
        box.pack_start(label, False, False, 0)
        box.show_all()
        self._notebook.append_page(page, box)
        self._notebook.child_set_property(page, 'tab-expand', True)
        self._notebook.child_set_property(page, 'tab-fill', True)
    
    def _pulse_progress(self) -> bool:
        """Pulse the progress bar."""
        if self._dep_box.get_visible():
            self._dep_progress.pulse()
            return True
        return False
    
    def show_dependency_check_ui(self) -> None:
        """Switch to progress view for dependency checking."""
        # Show local progress bar, stay on config page
        self._dep_box.show()
        self._install_btn.set_sensitive(False)
        self._dep_progress.set_fraction(0.0)
        self._dep_label.set_text(_("Checking system dependencies..."))
        
        # Start pulsing
        if self._pulse_timer_id is None:
            self._pulse_timer_id = GLib.timeout_add(100, self._pulse_progress)
    
    def update_dependency_progress(self, message: str) -> None:
        """Update progress bar during dependency check."""
        # Pulse handled by timer
        self._dep_progress.set_text(_("Working..."))
        self._dep_label.set_text(message)
    
    def hide_dependency_check_ui(self, success: bool) -> None:
        """Return to config view after check."""
        self._dep_box.hide()
        self._install_btn.set_sensitive(True)
        
        # Stop pulsing
        if self._pulse_timer_id is not None:
            GLib.source_remove(self._pulse_timer_id)
            self._pulse_timer_id = None
        
        if success:
            # Maybe show a small checkmark or nothing
            pass
        else:
            self._show_error(_("CRITICAL: Failed to install dependencies. Check terminal output."))
    
    def _load_initial_data(self) -> None:
        """Load initial data when window opens."""
        # Detect distro
        distro_info = self._distro.detect()
        self._distro_value.set_text(distro_info.pretty_name)
        
        # Check if supported
        if not self._distro.is_supported():
            self._show_unsupported_dialog(distro_info.pretty_name)
        
        # Get current kernel
        current = self._kernel_manager.get_current_kernel()
        self._kernel_value.set_text(current)
        
        # Detect bootloader and initramfs
        self._bootloader_value.set_text(self._distro.get_bootloader_name())
        self._initramfs_value.set_text(self._distro.get_initramfs_name())
        
        # Fetch available versions
        self._version_picker.refresh_versions()
        
        # Load history and pre-built kernels
        self._history_view.refresh()
        self._load_packaged()
    
    def _show_unsupported_dialog(self, distro_name: str) -> None:
        """Show dialog for unsupported distributions."""
        dialog = MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text=_("Unsupported distribution")
        )
        dialog.format_secondary_text(
            _("%(distro)s is not officially supported. "
            "The program might not work correctly.") % {'distro': distro_name}
        )
        dialog.run()
        dialog.destroy()
    
    def _on_install_clicked(self, button: Gtk.Button) -> None:
        """Handle install button click."""
        version = self._version_picker.get_selected_version()
        profile = self._profile_selector.get_selected_profile()
        
        if not version:
            self._show_error(_("Please select a kernel version."))
            return
        
        # Check dependencies first
        missing = self._kernel_manager.check_build_dependencies()
        if missing:
            pkg_list = ", ".join(missing)
            self._show_error(_("Missing required build tools: %(tools)s\n\nPlease install them and try again.") % {'tools': pkg_list})
            return
        
        # Confirm
        if not self._confirm_install(version, profile):
            return
        
        # Switch to build view
        self._stack.set_visible_child_name("build")
        self._build_progress.start_build()
        self._cancel_btn.set_sensitive(True)
        self._building = True
        
        # Set progress callback
        self._kernel_manager.set_progress_callback(self._on_build_progress)
        
        # Start build in thread
        custom_name = self.get_kernel_name()
        cleanup = self._cleanup_check.get_active()
        def build_thread():
            try:
                success = self._kernel_manager.full_install(version, profile, custom_name, cleanup)
                GLib.idle_add(self._on_build_complete, success)
            except Exception as e:
                GLib.idle_add(self._on_build_error, str(e))
        
        thread = threading.Thread(target=build_thread, daemon=True)
        thread.start()
    
    def _confirm_install(self, version: str, profile: KernelProfile) -> bool:
        """Show confirmation dialog."""
        dialog = MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Install kernel?")
        )
        dialog.format_secondary_text(
            _("You are about to download, compile and install:\n\n"
            "• Version: Linux %(version)s\n"
            "• Profile: %(profile)s\n\n"
            "This process may take several hours.") % {'version': version, 'profile': profile.name}
        )
        
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES
    
    def _on_build_progress(self, message: str, percent: int) -> None:
        """Handle build progress updates."""
        self._build_progress.update_progress(message, percent)
        if message:
            self._build_progress.append_log(message)
    
    def _on_build_complete(self, success: bool) -> None:
        """Handle build completion."""
        is_cancelled = self._kernel_manager._cancel_requested
        self._building = False
        self._cancel_btn.set_sensitive(False)
        self._done_btn.show()
        self._build_progress.set_complete(success, cancelled=is_cancelled)
        
        # Refresh history
        self._history_view.refresh()
        
        # Send notification
        version = self._version_picker.get_selected_version()
        notifier = get_notification_manager()
        notifier.notify_build_complete(version, success, cancelled=is_cancelled)
        
        if success:
            self._ask_reboot()
    
    def _on_build_error(self, error: str) -> None:
        """Handle build error."""
        self._building = False
        self._cancel_btn.set_sensitive(False)
        self._done_btn.show()
        self._build_progress.set_complete(False)
        self._build_progress.append_log(f"ERROR: {error}")
    
    def _on_cancel_clicked(self, button: Gtk.Button) -> None:
        """Handle cancel button click."""
        if self._building:
            self._cancel_btn.set_sensitive(False)
            self._build_progress.update_progress(_("Stopping build process..."), -1)
            self._build_progress.append_log(_("Cancellation requested by user..."))
            
            # This sets the flag that run_command_with_callback checks
            self._kernel_manager.cancel_operation()

    def _on_remove_kernels(self, widget, versions) -> None:
        """Handle kernel removal request(s) from the installed kernels tab."""
        if not self._confirm_remove(", ".join(versions)):
            return
        self._run_task(lambda: self._kernel_manager.remove_kernels(list(versions)))
    
    # ------------------------------------------------------------------
    # Generic background task (install / remove / update) on the progress page
    # ------------------------------------------------------------------
    def _run_task(self, func, ask_reboot: bool = False) -> None:
        """Run ``func`` (returns bool) in a thread, showing the progress page."""
        self._stack.set_visible_child_name("build")
        self._build_progress.start_build()
        self._build_progress.update_progress(_("Starting..."), 0)
        self._cancel_btn.set_sensitive(False)
        self._building = True
        
        self._kernel_manager.set_progress_callback(self._on_build_progress)
        self._packaged.set_progress_callback(self._on_build_progress)
        
        def worker():
            try:
                success = bool(func())
                GLib.idle_add(self._on_task_complete, success, ask_reboot)
            except Exception as e:
                GLib.idle_add(self._on_build_error, str(e))
        
        threading.Thread(target=worker, daemon=True).start()
    
    def _on_task_complete(self, success: bool, ask_reboot: bool = False) -> None:
        """Common completion handler for install / remove / update tasks."""
        self._building = False
        self._done_btn.show()
        self._build_progress.set_complete(success)
        self._history_view.refresh()
        self._load_packaged()
        self._kernel_value.set_text(self._kernel_manager.get_current_kernel())
        if success:
            get_notification_manager().notify(_("Operation completed successfully"))
            if ask_reboot:
                self._ask_reboot()
    
    # ------------------------------------------------------------------
    # Pre-built kernels (RT / LTS / XanMod)
    # ------------------------------------------------------------------
    def _load_packaged(self) -> None:
        """Load the list of pre-built kernels in the background."""
        if not self._packaged.is_supported():
            self._packaged_view.set_unsupported(
                _("Pre-built kernels need an APT based system (Debian, Ubuntu and derivatives)."))
            return
        self._packaged_view.set_loading()
        
        def worker():
            try:
                kernels = self._packaged.list_kernels()
            except Exception as e:
                print(f"Error listing pre-built kernels: {e}")
                kernels = {}
            GLib.idle_add(self._packaged_view.set_kernels, kernels)
        
        threading.Thread(target=worker, daemon=True).start()
    
    def _ask(self, title: str, text: str) -> bool:
        dialog = MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO, text=title)
        dialog.format_secondary_text(text)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES
    
    def _on_pkg_install(self, widget, kernel) -> None:
        text = _("The package %(pkg)s will be installed and the bootloader updated.") % {'pkg': kernel.package}
        if kernel.source == "xanmod" and kernel.needs_repo:
            text += "\n\n" + _("This will also add the official XanMod repository (deb.xanmod.org) "
                              "and its signing key to your system.")
        text += "\n\n" + _("Do you want to continue?")
        if not self._ask(_("Install %(name)s?") % {'name': kernel.title}, text):
            return
        self._run_task(lambda: self._packaged.install(kernel), ask_reboot=True)
    
    def _on_pkg_remove(self, widget, kernel) -> None:
        packages, error = self._packaged.plan_removal(kernel)
        if error:
            self._show_error(error)
            return
        text = _("These packages will be removed:") + "\n\n" + "\n".join("• " + p for p in packages)
        if not self._ask(_("Remove %(name)s?") % {'name': kernel.title}, text):
            return
        self._run_task(lambda: self._packaged.remove(packages))
    
    def _on_pkg_update_lists(self, widget) -> None:
        self._run_task(lambda: self._packaged.refresh_package_lists())
    
    # ------------------------------------------------------------------
    # Recommended kernel
    # ------------------------------------------------------------------
    def _create_recommend_banner(self) -> Gtk.Widget:
        banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        banner.get_style_context().add_class('recommend-banner')
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=_("Which kernel is best for this PC?"))
        title.set_halign(Gtk.Align.START)
        title.get_style_context().add_class('recommend-title')
        text.pack_start(title, False, False, 0)
        sub = Gtk.Label(label=_("Run a hardware test and get the recommended, compatible kernel."))
        sub.set_halign(Gtk.Align.START)
        sub.get_style_context().add_class('dim-label')
        text.pack_start(sub, False, False, 0)
        banner.pack_start(text, True, True, 0)
        btn = Gtk.Button(label=_("🎯 Recommended kernel"))
        btn.get_style_context().add_class('suggested-action')
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect('clicked', lambda b: self.show_recommendation())
        banner.pack_start(btn, False, False, 0)
        return banner
    
    def show_recommendation(self) -> None:
        """Run the hardware test and show the recommended kernel."""
        dialog = RecommendDialog(self, self._kernel_manager, self._distro,
                                 apt_based=self._packaged.is_supported())
        response = dialog.run()
        chosen = dialog.chosen
        dialog.destroy()
        if response == Gtk.ResponseType.ACCEPT and chosen is not None:
            self._apply_suggestion(chosen)
    
    def _apply_suggestion(self, s) -> None:
        """Select the suggested kernel in the matching tab."""
        if s.category == CAT_COMPILE:
            self._notebook.set_current_page(0)
            if s.version:
                self._version_picker.select_version(s.version)
            if s.profile is not None:
                self._profile_selector.set_selected_profile(s.profile)
        else:
            self._notebook.set_current_page(1)
            self._packaged_view.focus_package(s.category, s.package)

    def _confirm_remove(self, version: str) -> bool:
        """Show removal confirmation dialog."""
        dialog = MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Remove kernel?")
        )
        dialog.format_secondary_text(
            _("Are you sure you want to completely remove Linux %(version)s?\n\n"
              "This will delete the kernel image, modules, and update the bootloader.") % {'version': version}
        )
        
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def _on_remove_complete(self, success: bool) -> None:
        """Handle removal completion."""
        self._on_task_complete(success)
    
    def _on_done_clicked(self, button: Gtk.Button) -> None:
        """Handle done button click - return to config view."""
        self._stack.set_visible_child_name("config")
        self._done_btn.hide()
    
    def _ask_reboot(self) -> None:
        """Ask user if they want to reboot."""
        dialog = MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=_("Installation complete!")
        )
        dialog.format_secondary_text(
            _("The kernel has been installed successfully.\n\n"
            "Do you want to reboot now to use the new kernel?")
        )
        
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.YES:
            from ..utils.system import reboot_system
            reboot_system()
    
    def _show_error(self, message: str) -> None:
        """Show error dialog."""
        dialog = MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=_("Error")
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()
    
    def refresh_versions(self) -> None:
        """Public method to refresh kernel versions from kernel.org."""
        self._version_picker.refresh_versions()
    
    def _on_kernel_name_changed(self, entry: Gtk.Entry) -> None:
        """Handle kernel name entry change."""
        self._update_name_hint()
    
    def _update_name_hint(self) -> None:
        """Update the kernel name preview hint."""
        name = self.get_kernel_name()
        version = self._version_picker.get_selected_version() or "6.x.x"
        profile = self._profile_selector.get_selected_profile()
        profile_suffix = profile.suffix if profile else "gaming"
        
        if name:
            preview = f"{version}-{name}-{profile_suffix}"
        else:
            preview = f"{version}-{profile_suffix}"
        
        self._name_hint_label.set_text(_("Result: %s") % preview)
    
    def get_kernel_name(self) -> str:
        """Get the custom kernel name from entry field."""
        name = self._kernel_name_entry.get_text().strip()
        # Sanitize: only allow alphanumeric, dash, underscore
        import re
        name = re.sub(r'[^a-zA-Z0-9_-]', '', name)
        return name
    
    def _on_profile_changed(self, widget, profile) -> None:
        """Handle profile selection change."""
        self._update_name_hint()
