"""
Pre-built kernels (RT, LTS and XanMod) for Debian/Ubuntu based systems.

Lists the kernel packages available through APT, and installs or removes them.
XanMod kernels come from the official XanMod repository (deb.xanmod.org), which
is added on demand together with its signing key.
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .distro import DistroDetector, DistroFamily
from .recommend import CAT_LTS, CAT_RT, CAT_XANMOD, compute_x86_level, parse_cpuinfo
from ..utils.system import run_command
from ..locale.i18n import _

CATEGORIES = (CAT_RT, CAT_LTS, CAT_XANMOD)

XANMOD_KEY_URL = "https://dl.xanmod.org/archive.key"
XANMOD_KEYRING = "/etc/apt/keyrings/xanmod-archive-keyring.gpg"
XANMOD_LIST = "/etc/apt/sources.list.d/xanmod-release.list"
XANMOD_HOST = "deb.xanmod.org"

# Package-name prefixes that belong to a kernel "family" (never touch anything else)
_KERNEL_PREFIXES = (
    "linux-image-", "linux-headers-", "linux-modules-", "linux-modules-extra-",
    "linux-tools-", "linux-cloud-tools-", "linux-buildinfo-",
    "linux-xanmod", "linux-generic", "linux-lowlatency", "linux-rt", "linux-realtime",
)
_COMPANIONS = ("linux-image-", "linux-image-unsigned-", "linux-headers-", "linux-modules-",
               "linux-modules-extra-", "linux-tools-", "linux-cloud-tools-", "linux-buildinfo-")
_VERSIONED_RE = re.compile(
    r"^linux-(?:image|image-unsigned|headers|modules|modules-extra|tools|cloud-tools|buildinfo)-(\d+\.\d+\.\d+.*)$")
_VERSIONED_IMAGE_RE = re.compile(r"^linux-image-(?:unsigned-)?\d")


@dataclass
class PackagedKernel:
    """A kernel package shown in the pre-built kernels section."""
    package: str
    category: str                  # rt | lts | xanmod
    title: str
    description: str = ""
    candidate: str = ""            # version that APT would install ("" = none)
    installed_version: str = ""    # "" = not installed
    source: str = "distro"         # distro | xanmod
    needs_repo: bool = False       # XanMod repo not configured yet
    is_running: bool = False       # the running kernel belongs to this package

    @property
    def installed(self) -> bool:
        return bool(self.installed_version)

    @property
    def available(self) -> bool:
        return bool(self.candidate) or self.needs_repo or self.installed


def _version_key(text: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text))


class PackagedKernelManager:
    """Lists, installs and removes pre-built kernels using APT."""

    def __init__(self, distro: Optional[DistroDetector] = None):
        self._distro = distro or DistroDetector()
        self._progress_callback: Optional[Callable[[str, int], None]] = None
        self._running = ""
        self._cpu_level = 0

    # ------------------------------------------------------------------ basics
    def set_progress_callback(self, callback: Callable[[str, int], None]) -> None:
        self._progress_callback = callback

    def _report(self, message: str, percent: int = -1) -> None:
        if self._progress_callback:
            self._progress_callback(message, percent)

    def is_supported(self) -> bool:
        """Pre-built kernels need APT (Debian / Ubuntu families)."""
        try:
            return self._distro.detect().family in (DistroFamily.DEBIAN, DistroFamily.UBUNTU) \
                and shutil.which("apt-get") is not None
        except Exception:
            return False

    def running_kernel(self) -> str:
        if not self._running:
            self._running = run_command("uname -r").stdout.strip()
        return self._running

    def cpu_level(self) -> int:
        if not self._cpu_level:
            try:
                with open("/proc/cpuinfo", errors="ignore") as f:
                    self._cpu_level = compute_x86_level(set(parse_cpuinfo(f.read())["flags"]))
            except Exception:
                self._cpu_level = 1
        return self._cpu_level

    def xanmod_repo_configured(self) -> bool:
        paths = ["/etc/apt/sources.list"]
        try:
            paths += [os.path.join("/etc/apt/sources.list.d", f) for f in os.listdir("/etc/apt/sources.list.d")]
        except Exception:
            pass
        for p in paths:
            try:
                with open(p, errors="ignore") as f:
                    if XANMOD_HOST in f.read():
                        return True
            except Exception:
                continue
        return False

    # ----------------------------------------------------------- apt queries
    def _installed_packages(self) -> Dict[str, str]:
        """name -> version for every installed package."""
        out = run_command("dpkg-query -W -f='${Package}\\t${Version}\\t${db:Status-Abbrev}\\n' 2>/dev/null").stdout
        result: Dict[str, str] = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[2].strip().startswith("ii"):
                result[parts[0]] = parts[1]
        return result

    def _policy(self, packages: List[str]) -> Dict[str, Dict[str, str]]:
        """Run apt-cache policy in batches. Returns name -> {installed, candidate}."""
        result: Dict[str, Dict[str, str]] = {}
        for i in range(0, len(packages), 50):
            batch = packages[i:i + 50]
            cmd = "apt-cache policy " + " ".join(shlex.quote(p) for p in batch) + " 2>/dev/null"
            current = None
            for line in run_command(cmd).stdout.splitlines():
                m = re.match(r"^(\S+):\s*$", line)
                if m:
                    current = m.group(1)
                    result[current] = {"installed": "", "candidate": ""}
                    continue
                if current:
                    s = line.strip()
                    if s.startswith("Installed:"):
                        v = s.split(":", 1)[1].strip()
                        result[current]["installed"] = "" if v.startswith("(none)") else v
                    elif s.startswith("Candidate:"):
                        v = s.split(":", 1)[1].strip()
                        result[current]["candidate"] = "" if v.startswith("(none)") else v
        return result

    def _pkgnames(self, prefix: str) -> List[str]:
        out = run_command(f"apt-cache pkgnames {shlex.quote(prefix)} 2>/dev/null").stdout
        return [l.strip() for l in out.splitlines() if l.strip()]

    # ---------------------------------------------------------------- listing
    def list_kernels(self) -> Dict[str, List[PackagedKernel]]:
        """Return the available kernels grouped by category (rt, lts, xanmod)."""
        result: Dict[str, List[PackagedKernel]] = {c: [] for c in CATEGORIES}
        if not self.is_supported():
            return result

        names = self._pkgnames("linux-image-")
        installed = self._installed_packages()
        running = self.running_kernel()

        lts_meta, lts_ver, rt_meta, rt_ver, xan_ver = [], [], [], [], []
        for n in names:
            if re.fullmatch(r"linux-image-(generic|amd64)", n) or re.fullmatch(r"linux-image-generic-hwe-\d+\.\d+", n):
                lts_meta.append(n)
            elif re.fullmatch(r"linux-image-\d+\.\d+\.\d+-\d+-(generic|amd64)", n):
                lts_ver.append(n)
            elif n in ("linux-image-rt-amd64", "linux-image-realtime") or \
                    re.fullmatch(r"linux-image-lowlatency(-hwe-\d+\.\d+)?", n):
                rt_meta.append(n)
            elif re.fullmatch(r"linux-image-\d+\.\d+\.\d+-\d+-(rt-amd64|realtime|lowlatency)", n):
                rt_ver.append(n)
            elif re.fullmatch(r"linux-image-\d+\.\d+\.\d+-x64v\d-xanmod\d+", n):
                xan_ver.append(n)

        def newest(items: List[str], n: int) -> List[str]:
            return sorted(items, key=_version_key, reverse=True)[:n]

        distro_pkgs = lts_meta + newest(lts_ver, 6) + rt_meta + newest(rt_ver, 4)
        level = self.cpu_level()
        xan_versioned = [n for n in newest(xan_ver, 12)
                         if int(re.search(r"x64v(\d)", n).group(1)) <= min(level, 3)][:6]
        policy = self._policy(distro_pkgs + xan_versioned)

        def build(name: str, category: str, title: str, desc: str, source: str = "distro") -> PackagedKernel:
            info = policy.get(name, {})
            inst = installed.get(name, "") or info.get("installed", "")
            suffix = name.replace("linux-image-", "", 1)
            return PackagedKernel(
                package=name, category=category, title=title, description=desc,
                candidate=info.get("candidate", ""), installed_version=inst, source=source,
                is_running=bool(inst) and suffix == running)

        for n in lts_meta:
            title, desc = self._lts_meta_text(n)
            result[CAT_LTS].append(build(n, CAT_LTS, title, desc))
        for n in newest(lts_ver, 6):
            result[CAT_LTS].append(build(
                n, CAT_LTS, _("Linux %(v)s") % {"v": n.replace("linux-image-", "")},
                _("Specific kernel build from your distribution")))
        # LTS branch of XanMod also belongs to the LTS tab
        result[CAT_LTS].extend(self._xanmod_entries("lts", CAT_LTS, installed))

        for n in rt_meta:
            title, desc = self._rt_meta_text(n)
            result[CAT_RT].append(build(n, CAT_RT, title, desc))
        for n in newest(rt_ver, 4):
            result[CAT_RT].append(build(
                n, CAT_RT, _("Linux %(v)s") % {"v": n.replace("linux-image-", "")},
                _("Specific real-time / low-latency build from your distribution")))
        result[CAT_RT].extend(self._xanmod_entries("rt", CAT_RT, installed))

        result[CAT_XANMOD].extend(self._xanmod_entries("main", CAT_XANMOD, installed))
        result[CAT_XANMOD].extend(self._xanmod_entries("edge", CAT_XANMOD, installed))
        for n in xan_versioned:
            lvl = re.search(r"(x64v\d)", n).group(1)
            ver = re.search(r"linux-image-(\d+\.\d+\.\d+)", n).group(1)
            result[CAT_XANMOD].append(build(
                n, CAT_XANMOD, _("XanMod %(v)s (%(lvl)s)") % {"v": ver, "lvl": lvl},
                _("Specific XanMod build"), source="xanmod"))

        # XanMod meta-package state (policy lookups for static entries)
        self._fill_xanmod_state(result, installed)
        # Hide distro entries APT cannot provide (no candidate and not installed)
        for cat in result:
            result[cat] = [e for e in result[cat] if e.available]
        return result

    @staticmethod
    def _lts_meta_text(name: str) -> Tuple[str, str]:
        m = re.fullmatch(r"linux-image-generic-hwe-(\d+\.\d+)", name)
        if m:
            return (_("HWE kernel (Ubuntu %(v)s)") % {"v": m.group(1)},
                    _("Newer LTS kernel for recent hardware, updated automatically"))
        if name == "linux-image-amd64":
            return (_("Debian stable kernel"), _("Official long-term kernel of your Debian release, updated automatically"))
        return (_("Ubuntu LTS kernel (generic)"), _("Default long-term kernel of your Ubuntu release, updated automatically"))

    @staticmethod
    def _rt_meta_text(name: str) -> Tuple[str, str]:
        if name == "linux-image-rt-amd64":
            return (_("Debian real-time kernel (RT)"), _("PREEMPT_RT kernel for ultra-low latency, updated automatically"))
        if name == "linux-image-realtime":
            return (_("Ubuntu real-time kernel (RT)"), _("PREEMPT_RT kernel (may require Ubuntu Pro)"))
        return (_("Ubuntu low-latency kernel"), _("Low-latency preemption for audio / video (not full real-time)"))

    # -------------------------------------------------------------- xanmod
    _XANMOD_BRANCHES = {
        # branch: (package prefix, levels offered)
        "main": ("linux-xanmod", (2, 3)),
        "lts": ("linux-xanmod-lts", (1, 2, 3)),
        "edge": ("linux-xanmod-edge", (2, 3)),
        "rt": ("linux-xanmod-rt", (2, 3)),
    }

    def _xanmod_entries(self, branch: str, category: str, installed: Dict[str, str]) -> List[PackagedKernel]:
        prefix, levels = self._XANMOD_BRANCHES[branch]
        texts = {
            "main": (_("XanMod MAIN"), _("Latest stable kernel with XanMod performance and desktop patches")),
            "lts": (_("XanMod LTS"), _("Long-term kernel with XanMod patches - the most stable XanMod branch")),
            "edge": (_("XanMod EDGE"), _("Newest upstream features, less tested")),
            "rt": (_("XanMod RT"), _("Real-time preemption (PREEMPT_RT) for ultra-low latency")),
        }
        title, desc = texts[branch]
        level = min(self.cpu_level(), 3)
        entries = []
        for lvl in sorted(levels, reverse=True):
            if lvl > level:
                continue
            name = f"{prefix}-x64v{lvl}"
            entries.append(PackagedKernel(
                package=name, category=category,
                title=f"{title} (x64v{lvl})", description=desc, source="xanmod",
                installed_version=installed.get(name, "")))
        return entries

    def _fill_xanmod_state(self, result: Dict[str, List[PackagedKernel]], installed: Dict[str, str]) -> None:
        entries = [e for lst in result.values() for e in lst
                   if e.source == "xanmod" and e.package.startswith("linux-xanmod")]
        if not entries:
            return
        configured = self.xanmod_repo_configured()
        policy = self._policy([e.package for e in entries]) if configured else {}
        for e in entries:
            info = policy.get(e.package, {})
            e.candidate = info.get("candidate", "")
            if not e.installed_version:
                e.installed_version = installed.get(e.package, "") or info.get("installed", "")
            e.needs_repo = not configured
        if configured:
            # Hide branches that the repository does not offer for this release
            for cat in list(result):
                result[cat] = [e for e in result[cat]
                               if not (e.source == "xanmod" and e.package.startswith("linux-xanmod")
                                       and not e.candidate and not e.installed)]

    # ---------------------------------------------------------- privileged runs
    def _run_script(self, script: str) -> int:
        """Run a shell script as root (pkexec/sudo), streaming every line to the progress callback."""
        header = ("set -e\nexport DEBIAN_FRONTEND=noninteractive\n"
                  "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n")
        runner = ["pkexec"] if shutil.which("pkexec") else ["sudo"]
        argv = runner + ["sh", "-c", header + script]
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
            if line:
                print(f"PRIVILEGED: {line}", file=sys.stderr, flush=True)
                self._report(line, -1)
        proc.wait()
        if proc.returncode in (126, 127) and runner[0] == "pkexec":
            self._report(_("Authentication was cancelled or denied."), -1)
        return proc.returncode

    def _bootloader_cmd(self) -> str:
        try:
            return self._distro.get_bootloader_update_command()
        except Exception:
            return "update-grub"

    def refresh_package_lists(self) -> bool:
        """apt-get update (needs root)."""
        self._report(_("Updating package lists..."), 5)
        ok = self._run_script("apt-get update") == 0
        self._report(_("Package lists updated.") if ok else _("Could not update the package lists."), 100 if ok else -1)
        return ok

    def _xanmod_codename(self) -> str:
        info: Dict[str, str] = {}
        try:
            with open("/etc/os-release", errors="ignore") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        info[k] = v.strip('"')
        except Exception:
            pass
        return info.get("UBUNTU_CODENAME") or info.get("VERSION_CODENAME") or "releases"

    def install(self, kernel: PackagedKernel) -> bool:
        """Install a pre-built kernel (adding the XanMod repository if needed)."""
        pkg = shlex.quote(kernel.package)
        self._report(_("Installing %(name)s...") % {"name": kernel.title}, 2)
        lines = []
        if kernel.source == "xanmod" and kernel.needs_repo:
            codename = shlex.quote(self._xanmod_codename())
            lines += [
                'echo "Adding the official XanMod repository (%s)..."' % XANMOD_HOST,
                "install -m 0755 -d /etc/apt/keyrings",
                f"wget -qO- {XANMOD_KEY_URL} | gpg --batch --yes --dearmor -o {XANMOD_KEYRING}",
                f"chmod 0644 {XANMOD_KEYRING}",
                "add_repo() {",
                f"  echo \"deb [signed-by={XANMOD_KEYRING}] http://{XANMOD_HOST} $1 main\" > {XANMOD_LIST}",
                "  apt-get update || true",
                "}",
                f"add_repo {codename}",
                f"if ! apt-cache policy {pkg} | grep -q 'Candidate: [0-9]'; then add_repo releases; fi",
                f"if ! apt-cache policy {pkg} | grep -q 'Candidate: [0-9]'; then",
                f"  echo 'ERROR: {kernel.package} is not available in the XanMod repository for this system.'",
                "  exit 3",
                "fi",
            ]
        lines += [f"apt-get install -y {pkg}", self._bootloader_cmd()]
        ok = self._run_script("\n".join(lines)) == 0
        self._report(_("Kernel installed successfully.") if ok else _("Installation failed."), 100 if ok else -1)
        return ok

    # ------------------------------------------------------------- removal
    def _kernel_depends(self, package: str, installed: Dict[str, str]) -> List[str]:
        out = run_command(f"apt-cache depends --installed {shlex.quote(package)} 2>/dev/null").stdout
        deps = []
        for line in out.splitlines():
            m = re.match(r"^\s*\|?Depends:\s*(\S+)", line)
            if m:
                name = m.group(1).strip("<>")
                if name.startswith(_KERNEL_PREFIXES) and name in installed and name != package:
                    deps.append(name)
        return deps

    def plan_removal(self, kernel: PackagedKernel) -> Tuple[List[str], str]:
        """
        Work out which packages must be purged to remove ``kernel``.

        Returns (packages, error). ``error`` is non-empty when removal must not proceed.
        """
        installed = self._installed_packages()
        running = self.running_kernel()
        pkgs = set()
        if kernel.package in installed:
            pkgs.add(kernel.package)
        for dep in self._kernel_depends(kernel.package, installed):
            pkgs.add(dep)

        # Companion packages (headers, modules...) of every versioned image
        for name in list(pkgs):
            m = _VERSIONED_RE.match(name)
            if m and name.startswith("linux-image"):
                for pref in _COMPANIONS:
                    cand = pref + m.group(1)
                    if cand in installed:
                        pkgs.add(cand)
        # Meta companions: linux-image-generic -> linux-generic / linux-headers-generic
        if kernel.package.startswith("linux-image-") and not _VERSIONED_IMAGE_RE.match(kernel.package):
            tail = kernel.package[len("linux-image-"):]
            for cand in (f"linux-{tail}", f"linux-headers-{tail}"):
                if cand in installed:
                    pkgs.add(cand)

        if not pkgs:
            return [], _("This kernel is not installed.")
        for name in pkgs:
            m = _VERSIONED_RE.match(name)
            if m and m.group(1) == running:
                return [], _("The kernel %(k)s is currently running. Boot into another kernel first, then remove it.") % {"k": running}

        remaining = [n for n in installed
                     if _VERSIONED_IMAGE_RE.match(n) and n not in pkgs]
        if not remaining:
            return [], _("Removing this would leave the system without any kernel installed.")
        return sorted(pkgs), ""

    def remove(self, packages: List[str]) -> bool:
        """Purge the given packages and update the bootloader."""
        names = " ".join(shlex.quote(p) for p in packages)
        self._report(_("Removing kernel packages..."), 5)
        ok = self._run_script(f"apt-get purge -y {names}\n{self._bootloader_cmd()}") == 0
        self._report(_("Kernel removed successfully.") if ok else _("Could not remove the kernel packages."),
                     100 if ok else -1)
        return ok
