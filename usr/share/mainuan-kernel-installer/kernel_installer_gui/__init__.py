"""
Mainuan Mainuan Kernel Installer Package.
Copyright (C) 2026 David Caixinha

A GTK3 frontend for downloading, compiling and installing
the latest Linux kernel with optimized profiles.
"""

__version__ = "1.1.1"
__author__ = "David Caixinha"

# Brand / application name shown in window title, About dialog and notifications
APP_NAME = "Mainuan Kernel Installer"
APP_ID = "org.mainuan.kernel-installer"

# Initialize internationalization
from .locale.i18n import init_i18n, _
init_i18n()
