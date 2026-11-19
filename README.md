<div align="center">

![Mainuan kernel installer Icon](usr/share/icons/hicolor/128x128/apps/org.mainuan.kernel-installer.png)

# Mainuan Kernel Installer

[![License: GPL-3.0+](https://img.shields.io/badge/License-GPL--3.0%2B-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Version](https://img.shields.io/badge/version-1.0.1-green.svg)]()

A graphical interface for downloading, compiling, and installing the Linux kernel with optimized profiles.

**Mainuan Kernel installer** is an elegant, lightweight Site Specific Browser (SSB) engine tailored for Mainuan Linux. It effortlessly turns any website into a standalone, desktop-integrated application utilizing isolated browser profiles for maximum privacy and separation from your primary web session.

</div>

## Preview

![Kernel Installer Screenshot 01](kernel_installer_gui/assets/screenshots/screenshot01.png)
![Kernel Installer Screenshot 02](kernel_installer_gui/assets/screenshots/screenshot02.png)
![Kernel Installer Screenshot 03](kernel_installer_gui/assets/screenshots/screenshot03.png)
![Kernel Installer Screenshot 04](kernel_installer_gui/assets/screenshots/screenshot04.png)

## Features

- Download kernels directly from kernel.org (RT, LTS, XanMod)
- Optimized profiles: Gaming, Audio/Video, Minimal, Hardware Optimized
- Auto-detection of Hardware features (CPU, GPU, NVMe) for performance
- Virtualization support detection (QEMU, VMware, VirtualBox)
- Single sudo prompt for the entire installation process
- Fluent reboot without extra password prompts (integrated with systemd)
- Optional automatic cleanup of build directory
- Real-time system load monitoring with descriptive labels and tooltips
- Auto-detection of bootloader (GRUB, systemd-boot, rEFInd)
- Auto-detection of initramfs tool (dracut, initramfs-tools, mkinitcpio)
- Custom kernel naming
- Desktop notifications (transient via libnotify, auto-hide after 5s)
- **Universal localization**: 100% translation coverage for 9 languages (PT, BR, EN, ES, FR, DE, IT, RO, RU)
- **Compact UI**: Redesigned and optimized interface for various screen sizes
- **Major build optimization**: Automatically disables `CONFIG_DEBUG_INFO` to speed up compilation by ~50%
- Intelligent automated system dependency verification and installation
- Improved build cancellation: smart detection and user-friendly notifications
- Kernel removal support for Debian, Ubuntu.

## Requirements

- Python 3.10+
- GTK 3.0
- PyGObject

### Debian/Ubuntu

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-notify-0.7
```

## 📦 Installation

### Option 1: Native Packages (Recommended)

- **Mainuan**: [Download .deb](https://github.com/mainuan/mainuan-kernel-installer/releases)
  ```bash
  sudo dpkg -i kernel-installer_1.0.2_all.deb
  sudo apt install -f
  ```

### Option 2: From Source

1. Clone the repository:
   ```bash
   git clone https://github.com/mainuan/mainuan-kernel-installer.git
   ```
2. Install dependencies (see Requirements)
3. Run the program:
   ```bash
   python3 main.py
   ```

## Keyboard Shortcuts

| Shortcut | Action           |
| -------- | ---------------- |
| Ctrl+Q   | Quit             |
| F5       | Refresh versions |

## License

GPL-3.0 - See [LICENSE](LICENSE)

## 🆕 New in version 1.1.1 (November 18, 2026)

## Contributing

Report issues in [Issues](https://github.com/mainuan/mainuan-kernel-installer/issues)
and submit changes via pull request to the `main` branch. Every PR must pass the
[CI](https://github.com/mainuan/mainuan-kernel-installer/actions/workflows/ci.yml)
checks, which must all be green (passing). Document any visible changes in
[CHANGELOG.md](CHANGELOG.md) and `debian/changelog`.


- [GitHub Repository](https://github.com/SoplosLinux/kernel-installer)

