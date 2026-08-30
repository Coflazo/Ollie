"""What machine are we on, and what can it actually run.

Total RAM is the wrong number on its own. A 16 GB machine with 800 MB free cannot load a
9 GB model no matter what the spec sheet says, so the budget below takes the smaller of a
fraction of physical memory and a larger fraction of what is genuinely free right now.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict

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


def _linux_meminfo() -> tuple[float, float]:
    try:
        text = open("/proc/meminfo").read()
    except OSError:
        return 0.0, 0.0
    def kb(key: str) -> float:
        m = re.search(rf"^{key}:\s+(\d+) kB", text, re.M)
        return int(m.group(1)) / 1e6 if m else 0.0
    return kb("MemTotal"), kb("MemAvailable")


def probe() -> Probe:
    system = platform.system()
    arch = platform.machine()
    disk_free = round(shutil.disk_usage(config.ROOT).free / 1e9, 1)

    if system == "Darwin":
        total = float(_sysctl("hw.memsize") or 0) / 1e9
        avail = _macos_available_ram_gb()
        cpu = _sysctl("machdep.cpu.brand_string") or arch
        phys = int(_sysctl("hw.physicalcpu") or 0) or os.cpu_count() or 1
        logical = int(_sysctl("hw.ncpu") or 0) or os.cpu_count() or 1
        apple = arch == "arm64"
    elif system == "Linux":
        total, avail = _linux_meminfo()
        cpu = arch
        phys = os.cpu_count() or 1
        logical = phys
        apple = False
    else:
        total = avail = 0.0
        cpu = arch
        phys = logical = os.cpu_count() or 1
        apple = False

    return Probe(
        os=f"{system} {platform.release()}", arch=arch, cpu=cpu,
        cores_physical=phys, cores_logical=logical,
        ram_gb=round(total, 1), ram_available_gb=round(avail, 2),
        disk_free_gb=disk_free, apple_silicon=apple,
    )


def describe(p: Probe, tier: config.Tier) -> str:
    return (f"{p.cpu.strip()} · {p.cores_physical} cores · {p.ram_gb:g} GB RAM "
            f"({p.ram_available_gb:g} GB free) → tier {tier.name}, "
            f"{tier.context_cap} token context")
