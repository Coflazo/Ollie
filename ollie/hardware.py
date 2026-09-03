"""What machine are we on, and what can it actually run.

Total RAM is the wrong number on its own. A 16 GB machine with 800 MB free cannot load a
9 GB model no matter what the spec sheet says, so the budget below takes the smaller of a
fraction of physical memory and a larger fraction of what is genuinely free right now.

Each operating system exposes those numbers through its own interface and none of them are
portable, so there is a branch per platform and a POSIX `sysconf` path underneath for
everything else. The last one matters more than it looks: without it a FreeBSD or Solaris
machine reports 0 GB, lands in the smallest tier, and is told to run a 0.5b model on
hardware that could comfortably run a 32b one.
"""

from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

from . import config


@dataclass
class Probe:
    os: str
    arch: str
    cpu: str
    cores_physical: int
    cores_logical: int
    ram_gb: float
    ram_available_gb: float
    disk_free_gb: float
    apple_silicon: bool
    native: bool = False

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def model_budget_gb(self) -> float:
        return min(self.ram_gb * 0.70, self.ram_available_gb * 0.85)


# ------------------------------------------------------------------ generic POSIX


def _posix_memory_gb() -> tuple[float, float]:
    """Total and available RAM through sysconf, the interface every POSIX shares.

    Used directly on the systems without a branch of their own, and as the fallback when a
    platform's preferred interface is unavailable, which is the ordinary case inside a
    container with a restricted /proc.
    """
    try:
        page = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):
        return 0.0, 0.0

    def gigabytes(name: str) -> float:
        try:
            pages = os.sysconf(name)
        except (AttributeError, ValueError, OSError):
            return 0.0
        # sysconf answers -1 for a name it knows but cannot measure.
        return pages * page / 1e9 if pages and pages > 0 else 0.0

    return gigabytes("SC_PHYS_PAGES"), gigabytes("SC_AVPHYS_PAGES")


# ------------------------------------------------------------------------- macOS


def _sysctl(key: str) -> str:
    try:
        return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _macos_available_ram_gb() -> float:
    """vm_stat pages that can be reclaimed without swapping something out."""
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return 0.0
    page = 4096
    if m := re.search(r"page size of (\d+) bytes", out):
        page = int(m.group(1))
    counts = {k: int(v) for k, v in re.findall(r"^(.+?):\s+(\d+)\.", out, re.M)}
    free = counts.get("Pages free", 0) + counts.get("Pages inactive", 0) \
        + counts.get("Pages speculative", 0)
    return round(free * page / 1e9, 2)


# ------------------------------------------------------------------------- Linux


def _linux_meminfo() -> tuple[float, float]:
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0.0, 0.0

    def kb(key: str) -> float:
        m = re.search(rf"^{key}:\s+(\d+) kB", text, re.M)
        return int(m.group(1)) / 1e6 if m else 0.0

    return kb("MemTotal"), kb("MemAvailable")


def _linux_cpu() -> tuple[str, int]:
    """Model name and *physical* core count from /proc/cpuinfo.

    os.cpu_count() is the logical count. On anything with hyper-threading that is twice the
    physical count, and reporting it as physical makes an 8-core laptop claim 16 cores.

    A physical core is a unique (physical id, core id) pair: core ids restart at 0 in every
    socket, so neither half identifies a core on its own. Arm parts including the Raspberry
    Pi publish neither field, so this returns 0 there and the caller falls back.
    """
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", 0

    model = ""
    for key in ("model name", "Model", "Hardware", "cpu model"):
        if m := re.search(rf"^{key}\s*:\s*(.+)$", text, re.M):
            model = m.group(1).strip()
            break

    cores: set[tuple[str, str]] = set()
    for block in re.split(r"\n\s*\n", text):
        package = re.search(r"^physical id\s*:\s*(\S+)", block, re.M)
        core = re.search(r"^core id\s*:\s*(\S+)", block, re.M)
        if package and core:
            cores.add((package.group(1), core.group(1)))
    return model, len(cores)


# ----------------------------------------------------------------------- Windows


def _windows_memory_gb() -> tuple[float, float]:
    """Physical and currently available RAM from the Windows kernel."""

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError):
        return 0.0, 0.0
    if not ok:
        return 0.0, 0.0
    scale = 1e9
    return status.ullTotalPhys / scale, status.ullAvailPhys / scale


def _windows_physical_cores() -> int:
    """Physical cores via GetLogicalProcessorInformationEx.

    The older non-Ex call describes only the caller's processor group, so it undercounts on
    any machine with more than 64 logical processors. This one returns a variable-length
    record per physical core across every group, which is why walking the buffer means
    reading each record's own Size field rather than striding by a fixed width.
    """
    RELATION_PROCESSOR_CORE = 0
    try:
        kernel32 = ctypes.windll.kernel32
    except (AttributeError, OSError):
        return 0

    length = ctypes.c_ulong(0)
    # The first call is expected to fail; it is how the required buffer size is asked for.
    kernel32.GetLogicalProcessorInformationEx(RELATION_PROCESSOR_CORE, None,
                                              ctypes.byref(length))
    if not length.value:
        return 0

    buffer = ctypes.create_string_buffer(length.value)
    if not kernel32.GetLogicalProcessorInformationEx(RELATION_PROCESSOR_CORE, buffer,
                                                     ctypes.byref(length)):
        return 0

    # Each record is { DWORD Relationship; DWORD Size; ... }, so Size lives at offset 4.
    count = offset = 0
    while offset + 8 <= length.value:
        size = int.from_bytes(buffer[offset + 4:offset + 8], "little")
        if size <= 0:
            break
        count += 1
        offset += size
    return count


def _windows_cpu_name() -> str:
    """The marketing name, the way macOS reports machdep.cpu.brand_string.

    platform.processor() returns PROCESSOR_IDENTIFIER, which reads "Intel64 Family 6 Model
    186 Stepping 2, GenuineIntel" and tells a person nothing. The registry has the string
    the chip is actually sold under.
    """
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except (ImportError, OSError, ValueError):
        return ""


# --------------------------------------------------------------------------- probe


def probe() -> Probe:
    system = platform.system()
    arch = platform.machine()
    logical = os.cpu_count() or 1
    physical = logical
    apple = False

    try:
        disk_free = round(shutil.disk_usage(config.ROOT).free / 1e9, 1)
    except OSError:
        disk_free = 0.0

    if system == "Darwin":
        total = float(_sysctl("hw.memsize") or 0) / 1e9
        avail = _macos_available_ram_gb()
        cpu = _sysctl("machdep.cpu.brand_string") or arch
        physical = int(_sysctl("hw.physicalcpu") or 0) or logical
        logical = int(_sysctl("hw.ncpu") or 0) or logical
        apple = arch == "arm64"
    elif system == "Linux":
        total, avail = _linux_meminfo()
        model, cores = _linux_cpu()
        cpu = model or platform.processor() or arch
        physical = cores or logical
    elif system == "Windows":
        total, avail = _windows_memory_gb()
        cpu = (_windows_cpu_name() or platform.processor()
               or os.environ.get("PROCESSOR_IDENTIFIER", "") or arch)
        physical = _windows_physical_cores() or logical
    else:
        # FreeBSD, OpenBSD, NetBSD, Solaris, AIX and anything else with a libc. Reporting
        # zero here would put a capable machine in the smallest model tier.
        total, avail = _posix_memory_gb()
        cpu = platform.processor() or arch

    # Every branch above can come back empty inside a container or a sandbox. sysconf is
    # the last thing to try before admitting we do not know.
    if total <= 0 or avail <= 0:
        fallback_total, fallback_avail = _posix_memory_gb()
        total = total if total > 0 else fallback_total
        avail = avail if avail > 0 else fallback_avail

    # A machine that reports total but not available is better served by a conservative
    # guess than by a zero, which would make model_budget_gb zero and reject every model.
    if total > 0 and avail <= 0:
        avail = total * 0.5

    return Probe(
        os=f"{system} {platform.release()}".strip(), arch=arch, cpu=cpu,
        cores_physical=max(1, physical), cores_logical=max(1, logical),
        ram_gb=round(total, 1), ram_available_gb=round(avail, 2),
        disk_free_gb=disk_free, apple_silicon=apple,
    )


def describe(p: Probe, tier: config.Tier) -> str:
    return (f"{p.cpu.strip()} · {p.cores_physical} cores · {p.ram_gb:g} GB RAM "
            f"({p.ram_available_gb:g} GB free) → tier {tier.name}, "
            f"{tier.context_cap} token context")
