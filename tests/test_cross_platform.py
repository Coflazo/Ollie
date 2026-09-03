"""Invariants that only break on one operating system, asserted on all of them.

Every failure in this file was a real bug that a green suite on the author's machine said
nothing about, because the code path that breaks on Windows is never taken on macOS and the
code path that breaks on macOS is never compiled on Windows.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

import pytest

from ollie.store import Store

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT / "native"))
import loader  # noqa: E402


# ------------------------------------------------------------- the native library


def test_the_library_suffix_matches_this_platform() -> None:
    """A wrong suffix is invisible: the file is simply never found.

    Windows spent the whole project looking for libollie_native.so, which cannot exist, so
    `available()` was False on every Windows machine and the C++ hot paths (the copyright
    overlap guard, retrieval fusion, memory scoring) always ran as Python.
    """
    expected = {"Windows": ".dll", "Darwin": ".dylib"}.get(platform.system(), ".so")
    assert loader._SUFFIX == expected
    assert loader._library_path().name == f"libollie_native{expected}"


def test_a_built_library_actually_loads() -> None:
    """Building it and loading it are different claims.

    ctypes falls back silently on an architecture mismatch or a missing dependency, so a
    library sitting on disk next to a Python fallback proves nothing on its own.
    """
    if not loader._library_path().exists():
        pytest.skip("native library not built on this machine")
    assert loader.available(), loader.status()


# ------------------------------------------------------------------ file handles


def test_a_closed_store_releases_its_database_file(tmp_path: Path) -> None:
    """Windows will not delete a file that is still open. POSIX will.

    That difference is why an unclosed Store is a leak on macOS and a hard failure on
    Windows: pytest deletes old tmp_path trees, the delete fails on a locked ollie.db, and
    the debris eventually makes the whole temp root unusable. Tests then error during
    fixture setup, nowhere near the connection that caused it.
    """
    database = tmp_path / "closes.db"
    with Store(database, key=b"0" * 32) as store:
        store.create_profile({"content_mode": "general"}, {"big_five": {}}, "Rose")
    assert database.exists()

    # The assertion is the unlink itself: on Windows this raises PermissionError if any
    # handle is still open, including the -wal and -shm sidecars SQLite opens in WAL mode.
    for sidecar in ("", "-wal", "-shm"):
        candidate = database.with_name(database.name + sidecar)
        if candidate.exists():
            candidate.unlink()


# ------------------------------------------------------------------ line endings


def test_shell_scripts_have_unix_line_endings() -> None:
    """A CR in a shebang is a broken launcher, and Git for Windows adds one by default.

    With core.autocrlf=true a clone on Windows rewrites text files to CRLF. For Python that
    is harmless. For a shell script it is fatal the moment the tree reaches macOS or Linux:
    the kernel reads `#!/usr/bin/env bash\\r` and looks for an interpreter named "bash\\r".
    `.gitattributes` pins eol=lf on these files, and this is what proves it took effect.
    """
    scripts = [ROOT / "START.command", ROOT / "scripts" / "ollie",
               ROOT / "native" / "build.sh"]
    offenders = [
        str(path.relative_to(ROOT)) for path in scripts
        if path.exists() and b"\r\n" in path.read_bytes()
    ]
    assert not offenders, (
        f"CRLF in a shell script: {offenders}. Check .gitattributes is present, then "
        "re-checkout: git rm --cached -r . && git reset --hard"
    )


def test_windows_batch_files_have_windows_line_endings() -> None:
    """The mirror image. cmd.exe reads a batch file a line at a time and mis-parses LF."""
    batch = [ROOT / "native" / "build.cmd", ROOT / "START.bat"]
    offenders = [
        str(path.relative_to(ROOT)) for path in batch
        if path.exists() and b"\r\n" not in path.read_bytes()
    ]
    assert not offenders, f"LF in a batch file, which cmd.exe mis-parses: {offenders}"


# --------------------------------------------------------------------- launchers


def test_every_platform_has_a_launcher() -> None:
    """One double-clickable entry point per platform, all onto the same Python."""
    for launcher in ("START.command", "START.bat", "scripts/launch.py"):
        assert (ROOT / launcher).exists(), f"missing launcher: {launcher}"
