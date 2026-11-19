"""
Hardware test and kernel recommendation for Mainuan Kernel Installer.

The test inspects the CPU, GPU, memory, firmware (UEFI / Secure Boot), storage
and the software installed on the machine, and then recommends the kernel
branch (LTS, RT, XanMod or a custom build from kernel.org) that best matches
that hardware.

The decision logic (build_recommendation) is separated from the detection
code (detect_hardware) so it can be tested without real hardware.
"""

import glob
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set, Tuple

from .profiles import ProfileType
from ..locale.i18n import _

# Recommendation categories (match the tabs of the "pre-built kernels" section)
CAT_LTS = "lts"
CAT_RT = "rt"
CAT_XANMOD = "xanmod"
CAT_COMPILE = "compile"

# x86-64 micro-architecture levels (psABI) and the /proc/cpuinfo flags they need
_V2 = {"cx16", "lahf_lm", "popcnt", "sse4_1", "sse4_2", "ssse3"}
_V3 = _V2 | {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "abm", "movbe", "xsave"}
_V4 = _V3 | {"avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"}

_GAMING_PKGS = ("steam", "lutris", "gamemode", "heroic", "mangohud", "goverlay", "bottles")
_AUDIO_PKGS = ("ardour", "jackd", "qjackctl", "reaper", "bitwig", "carla", "lmms",
               "rosegarden", "hydrogen", "mixbus", "zynaddsubfx", "yoshimi", "cadence")

Version = Tuple[int, int]


# --------------------------------------------------------------------------- data
@dataclass
class Check:
    """One line of the hardware test report."""
    label: str
    value: str
    status: str = "info"  # ok | warn | fail | info


@dataclass
class HardwareInfo:
    cpu_model: str = ""
    cpu_vendor: str = ""          # intel | amd | other
    cpu_family: int = 0
    cpu_model_id: int = 0
    cpu_threads: int = 1
    x86_level: int = 1
    ram_mb: int = 0
    is_vm: bool = False
    hypervisor: str = ""
    is_laptop: bool = False
    gpus: List[str] = field(default_factory=list)
    nvidia_proprietary: bool = False
    uefi: bool = False
    secure_boot: Optional[bool] = None
    nvme: bool = False
    boot_free_mb: Optional[int] = None
    build_free_gb: Optional[float] = None
    current_kernel: str = ""
    distro: str = ""
    apt_based: bool = True
    hints: Set[str] = field(default_factory=set)       # {"gaming", "audio"}
    hint_details: List[str] = field(default_factory=list)
    min_kernel: Version = (5, 10)
    min_kernel_reasons: List[str] = field(default_factory=list)


@dataclass
class Suggestion:
    """A concrete kernel suggestion."""
    category: str                       # lts | rt | xanmod | compile
    title: str
    detail: str = ""
    package: Optional[str] = None       # package name in the pre-built section
    version: Optional[str] = None       # kernel.org version (compile)
    profile: Optional[ProfileType] = None


@dataclass
class Recommendation:
    primary: Suggestion
    reasons: List[str] = field(default_factory=list)
    alternatives: List[Suggestion] = field(default_factory=list)


@dataclass
class TestResult:
    hardware: HardwareInfo
    checks: List[Check]
    recommendation: Recommendation


# ----------------------------------------------------------------------- helpers
def parse_version(text: str) -> Version:
    """'6.12.9-xanmod1' -> (6, 12). Returns (0, 0) if it cannot be parsed."""
    m = re.match(r"\s*(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def fmt_version(v: Version) -> str:
    return f"{v[0]}.{v[1]}"


def compute_x86_level(flags: Set[str]) -> int:
    """Return the x86-64 psABI level (1-4) supported by the given CPU flags."""
    if _V4 <= flags:
        return 4
    if _V3 <= flags:
        return 3
    if _V2 <= flags:
        return 2
    return 1


def parse_cpuinfo(text: str) -> Dict[str, object]:
    """Extract model name, vendor, family, model and flags from /proc/cpuinfo."""
    info: Dict[str, object] = {"model_name": "", "vendor": "", "family": 0, "model": 0,
                               "flags": set(), "threads": 0}
    first_done = False
    for line in text.splitlines():
        if not line.strip():
            if info["threads"]:
                first_done = True
            continue
        if ":" not in line:
            continue
        key, _sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "processor":
            info["threads"] = int(info["threads"]) + 1
        if first_done:
            continue
        if key == "model name":
            info["model_name"] = value
        elif key == "vendor_id":
            info["vendor"] = value
        elif key == "cpu family":
            info["family"] = int(value) if value.isdigit() else 0
        elif key == "model" and value.isdigit():
            info["model"] = int(value)
        elif key in ("flags", "Features"):
            info["flags"] = set(value.split())
    return info


def min_kernel_for_cpu(vendor: str, family: int, model: int, name: str = "") -> Optional[Tuple[Version, str]]:
    """
    Approximate minimum kernel series with good support for a CPU generation.
    Returns (version, human readable generation) or None when unknown.
    """
    if vendor == "intel" and family == 6:
        table = {
            (0xCC,): ((6, 17), "Panther Lake"),
            (0xC5, 0xC6): ((6, 11), "Arrow Lake"),
            (0xBD,): ((6, 12), "Lunar Lake"),
            (0xAA, 0xAC): ((6, 8), "Meteor Lake"),
            (0xB7, 0xBA, 0xBF): ((6, 1), "Raptor Lake"),
            (0x97, 0x9A): ((5, 19), "Alder Lake"),
            (0x8C, 0x8D): ((5, 15), "Tiger Lake"),
        }
        for models, result in table.items():
            if model in models:
                return result
        return None
    if vendor == "amd":
        if family == 0x1A:
            return (6, 11), "Zen 5"
        if family == 0x19:
            if 0x10 <= model <= 0x1F or 0x60 <= model <= 0x7F or 0xA0 <= model <= 0xAF:
                return (6, 2), "Zen 4"
            return (5, 15), "Zen 3"
        if family == 0x17:
            return (5, 10), "Zen / Zen 2"
    return None


def min_kernel_for_gpu(gpu_line: str) -> Optional[Tuple[Version, str]]:
    """Approximate minimum kernel series for recent GPU generations."""
    g = gpu_line.lower()
    if re.search(r"navi\s*4\d|rx\s*9[0-9]{3}|radeon\s*9[0-9]{3}", g):
        return (6, 13), "AMD RDNA 4"
    if re.search(r"navi\s*3\d|rx\s*7[0-9]{3}", g):
        return (6, 2), "AMD RDNA 3"
    if "battlemage" in g or re.search(r"arc\s*b[0-9]{3}", g):
        return (6, 12), "Intel Arc Battlemage"
    if "dg2" in g or "alchemist" in g or re.search(r"arc\s*a[0-9]{3}", g):
        return (6, 2), "Intel Arc Alchemist"
    return None


# --------------------------------------------------------------------- detection
def _read(path: str) -> str:
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def _run(cmd: str) -> str:
    try:
        from ..utils.system import run_command
        res = run_command(cmd)
        return res.stdout if res.returncode == 0 else ""
    except Exception:
        return ""


def _detect_secure_boot() -> Tuple[bool, Optional[bool]]:
    """Return (uefi, secure_boot). secure_boot is None when it cannot be determined."""
    if not os.path.isdir("/sys/firmware/efi"):
        return False, False
    for path in glob.glob("/sys/firmware/efi/efivars/SecureBoot-*"):
        try:
            with open(path, "rb") as f:
                data = f.read()
            if data:
                return True, data[-1] == 1
        except Exception:
            pass
    out = _run("mokutil --sb-state 2>/dev/null").lower()
    if "secureboot enabled" in out:
        return True, True
    if "secureboot disabled" in out:
        return True, False
    return True, None


def _installed_packages() -> Set[str]:
    out = _run("dpkg-query -W -f='${Package}\\n' 2>/dev/null")
    return {line.strip() for line in out.splitlines() if line.strip()}


def detect_hardware(distro_name: str = "", apt_based: bool = True,
                    progress: Optional[Callable[[str], None]] = None) -> HardwareInfo:
    """Inspect the running machine. Every probe is optional and failure-safe."""
    hw = HardwareInfo(distro=distro_name, apt_based=apt_based)

    def step(msg: str) -> None:
        if progress:
            progress(msg)

    # CPU
    step(_("Testing processor..."))
    cpu = parse_cpuinfo(_read("/proc/cpuinfo"))
    hw.cpu_model = str(cpu["model_name"]) or _("Unknown processor")
    vendor = str(cpu["vendor"]).lower()
    hw.cpu_vendor = "intel" if "intel" in vendor else "amd" if "amd" in vendor else "other"
    hw.cpu_family = int(cpu["family"])
    hw.cpu_model_id = int(cpu["model"])
    hw.cpu_threads = int(cpu["threads"]) or (os.cpu_count() or 1)
    hw.x86_level = compute_x86_level(set(cpu["flags"]))
    hypervisor_flag = "hypervisor" in cpu["flags"]

    # Memory
    step(_("Testing memory..."))
    m = re.search(r"MemTotal:\s+(\d+)\s*kB", _read("/proc/meminfo"))
    hw.ram_mb = int(m.group(1)) // 1024 if m else 0

    # Virtualisation / chassis
    step(_("Detecting machine type..."))
    virt = _run("systemd-detect-virt --vm 2>/dev/null").strip()
    if virt and virt != "none":
        hw.is_vm, hw.hypervisor = True, virt
    elif hypervisor_flag:
        hw.is_vm, hw.hypervisor = True, "hypervisor"
    chassis = _read("/sys/class/dmi/id/chassis_type").strip()
    hw.is_laptop = (chassis.isdigit() and int(chassis) in (8, 9, 10, 11, 14, 30, 31, 32)) \
        or bool(glob.glob("/sys/class/power_supply/BAT*"))

    # GPU
    step(_("Testing graphics cards..."))
    for line in _run("lspci -mm 2>/dev/null").splitlines():
        low = line.lower()
        if "vga compatible controller" in low or "3d controller" in low or "display controller" in low:
            parts = re.findall(r'"([^"]*)"', line)
            hw.gpus.append(" ".join(parts[1:3]).strip() if len(parts) >= 3 else line.strip())
    hw.nvidia_proprietary = os.path.exists("/proc/driver/nvidia") or \
        any(l.startswith("nvidia ") for l in _read("/proc/modules").splitlines())

    # Firmware
    step(_("Checking firmware (UEFI / Secure Boot)..."))
    hw.uefi, hw.secure_boot = _detect_secure_boot()

    # Storage
    step(_("Checking storage..."))
    hw.nvme = bool(glob.glob("/sys/class/nvme/nvme*"))
    try:
        hw.boot_free_mb = shutil.disk_usage("/boot").free // (1024 * 1024)
    except Exception:
        pass
    try:
        hw.build_free_gb = shutil.disk_usage(os.path.expanduser("~")).free / (1024 ** 3)
    except Exception:
        pass

    # Current kernel
    hw.current_kernel = _run("uname -r").strip()

    # Usage hints (installed software)
    step(_("Analysing installed software..."))
    pkgs = _installed_packages()
    home = os.path.expanduser("~")
    gaming = sorted(p for p in pkgs if p.startswith(_GAMING_PKGS))
    if os.path.isdir(os.path.join(home, ".steam")) or os.path.isdir(os.path.join(home, ".local/share/Steam")):
        gaming.append("steam")
    audio = sorted(p for p in pkgs if p.startswith(_AUDIO_PKGS))
    if gaming:
        hw.hints.add("gaming")
        hw.hint_details.append(_("Gaming software detected: %(names)s") % {"names": ", ".join(sorted(set(gaming))[:4])})
    if audio:
        hw.hints.add("audio")
        hw.hint_details.append(_("Audio production software detected: %(names)s") % {"names": ", ".join(audio[:4])})

    # Minimum kernel for this generation of hardware
    cpu_req = min_kernel_for_cpu(hw.cpu_vendor, hw.cpu_family, hw.cpu_model_id, hw.cpu_model)
    if cpu_req:
        _apply_min_kernel(hw, cpu_req[0], _("%(what)s processor") % {"what": cpu_req[1]})
    for gpu in hw.gpus:
        gpu_req = min_kernel_for_gpu(gpu)
        if gpu_req:
            _apply_min_kernel(hw, gpu_req[0], _("%(what)s graphics") % {"what": gpu_req[1]})
    return hw


def _apply_min_kernel(hw: HardwareInfo, version: Version, reason: str) -> None:
    hw.min_kernel_reasons.append(f"{reason}: Linux {fmt_version(version)}+")
    if version > hw.min_kernel:
        hw.min_kernel = version


# ---------------------------------------------------------------- recommendation
def _xanmod_package(branch: str, level: int) -> Optional[str]:
    """XanMod meta-package for a branch and CPU level (v2/v3 only for most branches)."""
    if level < 1:
        return None
    if branch == "lts":
        lvl = min(level, 3)
        return f"linux-xanmod-lts-x64v{lvl}"
    if level < 2:
        return None  # MAIN / EDGE / RT builds need at least x86-64-v2
    lvl = min(level, 3)
    prefix = {"main": "linux-xanmod", "edge": "linux-xanmod-edge", "rt": "linux-xanmod-rt"}[branch]
    return f"{prefix}-x64v{lvl}"


def pick_kernel_org_version(versions: list, min_kernel: Version):
    """
    Choose a kernel.org version: the newest long-term series that satisfies
    ``min_kernel``; otherwise the latest stable. Returns (version, is_lts) or (None, False).
    """
    lts = sorted((v for v in versions if getattr(v, "is_longterm", False)),
                 key=lambda v: parse_version(v.version), reverse=True)
    for v in lts:
        if parse_version(v.version) >= min_kernel:
            return v.version, True
    for v in versions:
        if getattr(v, "is_latest", False):
            return v.version, False
    stable = [v for v in versions if not getattr(v, "is_mainline", False)]
    if stable:
        return stable[0].version, bool(getattr(stable[0], "is_longterm", False))
    return None, False


def _profile_for(hw: HardwareInfo) -> ProfileType:
    if "audio" in hw.hints:
        return ProfileType.AUDIO_VIDEO
    if "gaming" in hw.hints:
        return ProfileType.GAMING
    if hw.is_vm or (hw.ram_mb and hw.ram_mb <= 3072):
        return ProfileType.MINIMAL
    return ProfileType.HARDWARE_OPTIMIZED


def build_recommendation(hw: HardwareInfo, versions: list) -> Recommendation:
    """Decide which kernel suits ``hw``. ``versions`` are kernel.org KernelVersion objects."""
    reasons: List[str] = []
    cur = parse_version(hw.current_kernel)
    sb_on = hw.secure_boot is True
    can_unsigned = not sb_on
    outdated = cur != (0, 0) and cur < hw.min_kernel
    profile = _profile_for(hw)
    org_version, org_is_lts = pick_kernel_org_version(versions, hw.min_kernel)

    lts_s = Suggestion(
        CAT_LTS, _("LTS kernel (distribution)"),
        _("Long-term support kernel from your distribution's repositories: signed, stable and the most compatible."),
    )
    xan_lts = _xanmod_package("lts", hw.x86_level)
    xan_main = _xanmod_package("main", hw.x86_level)
    xan_rt = _xanmod_package("rt", hw.x86_level)

    def xanmod_s(pkg: str, label: str) -> Suggestion:
        return Suggestion(CAT_XANMOD, label,
                          _("Pre-built kernel tuned for desktop responsiveness and performance (package %(pkg)s).") % {"pkg": pkg},
                          package=pkg)

    compile_s = None
    if org_version:
        compile_s = Suggestion(
            CAT_COMPILE,
            _("Compile Linux %(version)s") % {"version": org_version},
            _("Kernel.org %(kind)s release compiled with the \"%(profile)s\" profile.") % {
                "kind": _("long-term") if org_is_lts else _("stable"),
                "profile": _(_profile_name(profile))},
            version=org_version, profile=profile)

    # ---- choose the primary suggestion -----------------------------------
    primary: Suggestion
    if hw.is_vm:
        primary = lts_s
        reasons.append(_("You are running inside a virtual machine (%(hv)s): a stable LTS kernel is the safest choice.") % {"hv": hw.hypervisor})
    elif outdated and sb_on:
        primary = Suggestion(CAT_LTS, _("Newest LTS / HWE kernel (distribution)"),
                             _("Choose the newest signed kernel in the list (HWE / backports)."))
        reasons.append(_("Your kernel %(cur)s is older than the %(min)s+ recommended for your hardware, and Secure Boot requires a signed kernel.") % {
            "cur": fmt_version(cur), "min": fmt_version(hw.min_kernel)})
    elif outdated and xan_main:
        primary = xanmod_s(xan_main, _("XanMod (latest)"))
        reasons.append(_("Your kernel %(cur)s is older than the %(min)s+ recommended for your hardware: XanMod ships a recent kernel as a ready-to-install package.") % {
            "cur": fmt_version(cur), "min": fmt_version(hw.min_kernel)})
    elif outdated and compile_s:
        primary = compile_s
        reasons.append(_("Your kernel %(cur)s is older than the %(min)s+ recommended for your hardware.") % {
            "cur": fmt_version(cur), "min": fmt_version(hw.min_kernel)})
    elif "audio" in hw.hints and can_unsigned and xan_rt:
        primary = Suggestion(CAT_RT, _("XanMod Real-Time (RT)"),
                             _("Real-time kernel for low-latency audio (package %(pkg)s).") % {"pkg": xan_rt}, package=xan_rt)
        reasons.append(_("Audio production software was found: a real-time kernel reduces audio latency and dropouts."))
    elif "audio" in hw.hints:
        primary = Suggestion(CAT_RT, _("Real-time (RT) kernel"), _("Choose an RT kernel from the list."))
        reasons.append(_("Audio production software was found: a real-time kernel reduces audio latency and dropouts."))
        if sb_on:
            reasons.append(_("Secure Boot is enabled: prefer a signed RT kernel from your distribution."))
    elif sb_on:
        primary = lts_s
        reasons.append(_("Secure Boot is enabled: signed distribution kernels boot without extra steps, while compiled or XanMod kernels are unsigned."))
    elif "gaming" in hw.hints and hw.x86_level >= 3 and not hw.nvidia_proprietary and xan_main:
        primary = xanmod_s(xan_main, _("XanMod (gaming / desktop)"))
        reasons.append(_("Gaming software was found and your CPU supports x86-64-v3: XanMod improves responsiveness and frame pacing."))
    elif "gaming" in hw.hints and xan_lts:
        primary = xanmod_s(xan_lts, _("XanMod LTS"))
        reasons.append(_("Gaming software was found: XanMod LTS adds desktop/gaming tuning on a long-term base."))
    else:
        primary = lts_s
        reasons.append(_("No special workload detected: an LTS kernel gives the best stability and compatibility."))

    # ---- extra reasons -----------------------------------------------------
    if hw.nvidia_proprietary:
        reasons.append(_("The NVIDIA proprietary driver is in use: prefer LTS kernels (the driver supports them first) and keep the kernel headers installed."))
    if hw.x86_level == 1 and primary.category == CAT_XANMOD:
        reasons.append(_("Your CPU only supports baseline x86-64: only XanMod LTS (x64v1) is compatible."))
    if hw.ram_mb and hw.ram_mb <= 3072:
        reasons.append(_("Low memory (%(gb).1f GB): if you compile, the Minimal profile keeps the kernel small.") % {"gb": hw.ram_mb / 1024})

    # ---- alternatives --------------------------------------------------------
    alts: List[Suggestion] = []

    def add_alt(s: Optional[Suggestion]) -> None:
        if s is None or s is primary:
            return
        if any(a.category == s.category and a.package == s.package and a.version == s.version for a in alts):
            return
        if primary.category == s.category and primary.package == s.package and primary.version == s.version:
            return
        alts.append(s)

    add_alt(lts_s)
    if can_unsigned:
        if xan_lts:
            add_alt(xanmod_s(xan_lts, _("XanMod LTS")))
        if xan_main and hw.x86_level >= 2:
            add_alt(xanmod_s(xan_main, _("XanMod (latest)")))
        if xan_rt:
            add_alt(Suggestion(CAT_RT, _("XanMod Real-Time (RT)"),
                               _("Real-time kernel for low-latency audio (package %(pkg)s).") % {"pkg": xan_rt}, package=xan_rt))
    add_alt(compile_s)
    return Recommendation(primary=primary, reasons=reasons, alternatives=alts[:4])


def _profile_name(profile: ProfileType) -> str:
    from .profiles import get_profile
    p = get_profile(profile)
    return p.name if p else "Custom"


def build_checks(hw: HardwareInfo, versions: list) -> List[Check]:
    """Turn the detected hardware into the list shown in the test report."""
    checks: List[Check] = []
    checks.append(Check(_("Processor"), f"{hw.cpu_model} ({hw.cpu_threads} {_('threads')})", "ok"))

    level_txt = f"x86-64-v{hw.x86_level}"
    if hw.x86_level >= 3:
        checks.append(Check(_("CPU instruction level"), _("%(lvl)s - compatible with all optimised kernels") % {"lvl": level_txt}, "ok"))
    elif hw.x86_level == 2:
        checks.append(Check(_("CPU instruction level"), _("%(lvl)s - compatible with XanMod x64v2 builds") % {"lvl": level_txt}, "ok"))
    else:
        checks.append(Check(_("CPU instruction level"), _("%(lvl)s - only baseline kernels (XanMod LTS x64v1)") % {"lvl": level_txt}, "warn"))

    if hw.ram_mb:
        status = "ok" if hw.ram_mb >= 4096 else "warn"
        checks.append(Check(_("Memory"), f"{hw.ram_mb / 1024:.1f} GB", status))

    if hw.gpus:
        for gpu in hw.gpus:
            checks.append(Check(_("Graphics"), gpu, "ok"))
    else:
        checks.append(Check(_("Graphics"), _("Not detected (lspci unavailable)"), "info"))
    if hw.nvidia_proprietary:
        checks.append(Check(_("NVIDIA driver"), _("Proprietary driver in use - LTS kernels recommended"), "warn"))

    machine = _("Virtual machine (%(hv)s)") % {"hv": hw.hypervisor} if hw.is_vm else \
        (_("Laptop") if hw.is_laptop else _("Desktop / workstation"))
    checks.append(Check(_("Machine type"), machine, "info"))

    if not hw.uefi:
        checks.append(Check(_("Firmware"), _("Legacy BIOS - no Secure Boot restrictions"), "ok"))
    elif hw.secure_boot is True:
        checks.append(Check(_("Secure Boot"), _("Enabled - compiled and XanMod kernels are unsigned"), "warn"))
    elif hw.secure_boot is False:
        checks.append(Check(_("Secure Boot"), _("Disabled - any kernel can boot"), "ok"))
    else:
        checks.append(Check(_("Secure Boot"), _("UEFI detected, state unknown (install mokutil to check)"), "info"))

    if hw.nvme:
        checks.append(Check(_("Storage"), _("NVMe drive detected"), "ok"))
    if hw.boot_free_mb is not None:
        checks.append(Check(_("Free space in /boot"), f"{hw.boot_free_mb} MB",
                            "ok" if hw.boot_free_mb >= 300 else "warn"))
    if hw.build_free_gb is not None:
        checks.append(Check(_("Free space for compiling"), f"{hw.build_free_gb:.0f} GB",
                            "ok" if hw.build_free_gb >= 30 else "warn"))

    cur = parse_version(hw.current_kernel)
    if cur != (0, 0):
        if cur >= hw.min_kernel:
            checks.append(Check(_("Current kernel"), _("%(cur)s - sufficient for this hardware") % {"cur": hw.current_kernel}, "ok"))
        else:
            checks.append(Check(_("Current kernel"), _("%(cur)s - older than the recommended %(min)s+") % {
                "cur": hw.current_kernel, "min": fmt_version(hw.min_kernel)}, "warn"))
    for reason in hw.min_kernel_reasons:
        checks.append(Check(_("Hardware requirement"), reason, "info"))

    for detail in hw.hint_details:
        checks.append(Check(_("Usage profile"), detail, "info"))

    if hw.apt_based:
        checks.append(Check(_("Package system"), _("APT - pre-built RT / LTS / XanMod kernels are available"), "ok"))
    else:
        checks.append(Check(_("Package system"), _("Not APT-based - the pre-built kernels section is unavailable"), "warn"))
    if versions:
        checks.append(Check(_("kernel.org"), _("Reachable (%(n)d versions found)") % {"n": len(versions)}, "ok"))
    else:
        checks.append(Check(_("kernel.org"), _("Could not fetch the version list (offline?)"), "warn"))
    return checks


def run_hardware_test(versions: list, distro_name: str = "", apt_based: bool = True,
                      progress: Optional[Callable[[str], None]] = None) -> TestResult:
    """Run the complete test (blocking - call it from a worker thread)."""
    hw = detect_hardware(distro_name, apt_based, progress)
    if progress:
        progress(_("Choosing the best kernel..."))
    return TestResult(hw, build_checks(hw, versions), build_recommendation(hw, versions))
