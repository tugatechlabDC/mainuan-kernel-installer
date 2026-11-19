"""Core subpackage for Mainuan Kernel Installer - business logic."""

from .distro import DistroDetector
from .kernel import KernelManager
from .profiles import KernelProfile, KERNEL_PROFILES
from .notifications import NotificationManager

__all__ = ['DistroDetector', 'KernelManager', 'KernelProfile', 'KERNEL_PROFILES', 'NotificationManager']
