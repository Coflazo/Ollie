"""Hardware discovery must provide a usable model tier on every supported OS.

These run on whatever machine happens to be executing them, which is the point: CI runs the
file on Ubuntu, macOS and Windows, so a branch that only works on the machine it was written
on fails somewhere visible rather than silently reporting zero and dropping the user into
the smallest model tier.
"""

from __future__ import annotations

import platform

from ollie import config, hardware


def test_probe_reports_plausible_resources() -> None:
    result = hardware.probe()
    assert result.ram_gb > 1, "no RAM reading; this OS has no working branch in probe()"
    assert result.ram_available_gb > 0
    assert result.disk_free_gb > 0
    assert result.cores_logical >= 1
    assert result.model_budget_gb > 0
    assert config.tier_for(result.ram_gb).candidates


def test_probe_identifies_the_machine() -> None:
    """Empty strings here are what a missing platform branch looks like in the UI."""
    result = hardware.probe()
    assert result.os.strip(), "operating system not identified"
    assert result.arch.strip(), "architecture not identified"
    assert result.cpu.strip(), "CPU not identified"


def test_physical_cores_never_exceed_logical_cores() -> None:
    """The bug this catches is reporting os.cpu_count() as the physical count.

    os.cpu_count() is logical. On a hyper-threaded machine that is twice the truth, and
    every branch of probe() used to return it for both, so an 8-core laptop claimed 16.
    """
    result = hardware.probe()
    assert result.cores_physical >= 1
    assert result.cores_physical <= result.cores_logical


def test_posix_memory_probe_never_raises() -> None:
    """The last-resort path. It is allowed to answer 0, never to raise.

    It runs on Windows too, where sysconf does not exist, because probe() calls it whenever
    a platform's preferred interface came back empty.
    """
    total, available = hardware._posix_memory_gb()
    assert total >= 0 and available >= 0
    if platform.system() in ("Linux", "Darwin"):
        assert total > 0, "sysconf should report physical memory on any POSIX system"


def test_tier_boundaries_are_stable() -> None:
    assert config.tier_for(64).name == "xl"
    assert config.tier_for(32).name == "l"
    assert config.tier_for(16).name == "m"
    assert config.tier_for(7).name == "s"
    assert config.tier_for(6.99).name == "xs"
