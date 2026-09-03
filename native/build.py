#!/usr/bin/env python3
"""Build libollie_native for whatever compiler this machine actually has.

One translation unit, one output, no CMake. The complexity that remains is not build-system
ceremony, it is the genuine differences between three toolchains:

  - the output is a .dylib, a .so or a .dll depending on the OS, and ctypes will not find
    the wrong one;
  - MSVC spells every flag differently from Clang and GCC, and needs an environment that
    only exists inside a developer command prompt;
  - a MinGW build links against libstdc++ and libgcc by default, and a DLL whose
    dependencies are not on the search path fails to load with an error message that names
    the DLL we asked for rather than the one that is missing, so we link them statically.

Failing here is not fatal to Ollie. Every native function has a Python twin, so a machine
with no compiler runs the same code more slowly. This script says so plainly rather than
presenting a missing compiler as a broken install.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "ollie_native.cpp"

WINDOWS = platform.system() == "Windows"
SUFFIX = ".dll" if WINDOWS else (".dylib" if platform.system() == "Darwin" else ".so")
OUTPUT = HERE / f"libollie_native{SUFFIX}"

# MSVC leaves these next to the DLL. They are build intermediates, not artefacts.
LEFTOVERS = ("ollie_native.obj", "libollie_native.exp", "libollie_native.lib",
             "vc140.pdb", "libollie_native.pdb")

# One toolchain to try: a label for the log, the argv, and the environment it needs.
Toolchain = tuple[str, list[str], "dict[str, str] | None"]


def unix_command(compiler: str) -> list[str]:
    """Clang and GCC share a flag vocabulary, so they share a command."""
    # -march=native is skipped deliberately: the machine that builds and the machine that
    # runs are often different, and a library that segfaults on someone else's CPU is worse
    # than one that is marginally slower.
    argv = [compiler, "-std=c++20", "-O3", "-shared",
            "-Wall", "-Wextra", "-Wno-unused-parameter"]
    if WINDOWS:
        # Otherwise the DLL needs libstdc++-6.dll and libgcc_s_seh-1.dll beside it.
        argv += ["-static-libstdc++", "-static-libgcc"]
    else:
        # Meaningless on Windows, where all code is position independent, and MinGW warns
        # about it on every build.
        argv.append("-fPIC")
    return argv + ["-o", str(OUTPUT), str(SOURCE)]


def msvc_command(compiler: str) -> list[str]:
    return [compiler, "/nologo", "/std:c++20", "/O2", "/EHsc", "/W3", "/LD",
            str(SOURCE), f"/Fe:{OUTPUT}", f"/Fo:{HERE / 'ollie_native.obj'}"]


def vcvars_toolchain() -> tuple[str, dict[str, str]] | None:
    """Locate MSVC without asking anyone to open a developer command prompt.

    vswhere.exe ships at a fixed path with every Visual Studio 2017 and later, which is the
    only reason finding the toolchain from an ordinary shell is possible at all. Returns the
    absolute path to cl.exe and the environment it needs, or None.
    """
    if not WINDOWS:
        return None
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        return None
    try:
        dumped_roots = subprocess.run(
            [str(vswhere), "-latest", "-products", "*", "-property", "installationPath",
             "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    roots = [line.strip() for line in dumped_roots.splitlines() if line.strip()]
    if not roots:
        return None
    vcvars = Path(roots[0]) / "VC" / "Auxiliary" / "Build" / "vcvarsall.bat"
    if not vcvars.exists():
        return None

    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    try:
        # Running `set` after the batch file is the only supported way to read what it
        # changed: the variables live in a cmd.exe that exits immediately afterwards.
        #
        # A pre-quoted string, not a list. Windows has no argv at the OS level, so
        # subprocess re-quotes list elements with MSVC's rules, which escape an embedded
        # quote with a backslash. cmd.exe does not read those rules, and reports the whole
        # path as an unrecognised command. A string reaches CreateProcess untouched.
        dumped = subprocess.run(
            f'"{vcvars}" {arch} >nul 2>&1 && set',
            shell=True, capture_output=True, text=True, timeout=180,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    env = dict(os.environ)
    for line in dumped.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            env[key] = value

    # An absolute path, not the bare name. CreateProcess resolves argv[0] against the PATH
    # of the *calling* process, so handing subprocess an `env` whose PATH contains cl.exe is
    # not enough: it still fails with "the system cannot find the file specified". The env
    # is what supplies INCLUDE and LIB; the absolute path is what lets it launch at all.
    compiler = shutil.which("cl", path=env.get("PATH", ""))
    return (compiler, env) if compiler else None


def candidates() -> list[Toolchain]:
    """Every toolchain worth trying, best first."""
    found: list[Toolchain] = []

    # An explicit CXX always wins. Someone who sets it means it.
    override = os.environ.get("CXX")
    if override and (resolved := shutil.which(override)):
        found.append((override, unix_command(resolved), None))

    if WINDOWS and (on_path := shutil.which("cl")):
        found.append(("cl (MSVC)", msvc_command(on_path), None))
    for name in ("clang++", "g++", "c++"):
        if resolved := shutil.which(name):
            found.append((name, unix_command(resolved), None))
    if WINDOWS and not any(label.startswith("cl") for label, _, _ in found):
        if toolchain := vcvars_toolchain():
            compiler, env = toolchain
            found.append(("cl (MSVC, found via vswhere)", msvc_command(compiler), env))
    return found


def clear_previous_output() -> str | None:
    """Get the old library out of the way, even while something has it open.

    A failed build must not leave the previous library in place: the loader only rejects a
    library that is missing a symbol, so a stale but complete one is picked up silently and
    the run quietly exercises the wrong code.

    Deleting it is not always allowed. POSIX unlink removes the directory entry and lets a
    process that already mapped the file keep its mapping, so rebuilding a .so while Ollie
    runs is fine. Windows locks a mapped DLL outright and refuses the delete with
    PermissionError, which used to end this script in a traceback whenever the app, a test
    run, or a process still shutting down had the library open. Windows does permit renaming
    a mapped file, so move it aside instead and sweep the leftovers on a later run, once
    nothing holds them.
    """
    for stale in HERE.glob(f"libollie_native{SUFFIX}.old-*"):
        try:
            stale.unlink()
        except OSError:
            pass  # still mapped somewhere; the next run will get it

    if not OUTPUT.exists():
        return None
    try:
        OUTPUT.unlink()
        return None
    except OSError:
        pass
    try:
        OUTPUT.rename(HERE / f"{OUTPUT.name}.old-{os.getpid()}-{int(time.time())}")
        return None
    except OSError as exc:
        return str(exc)


def main() -> int:
    if not SOURCE.exists():
        print(f"no source at {SOURCE}", file=sys.stderr)
        return 1

    if blocked := clear_previous_output():
        print(f"cannot replace {OUTPUT.name}: {blocked}\n"
              "  Something still has it open. Stop Ollie and run this again.",
              file=sys.stderr)
        return 1

    toolchains = candidates()
    if not toolchains:
        print("no C++ compiler found, so Ollie will use the Python fallbacks.\n"
              "  macOS    xcode-select --install\n"
              "  Debian   sudo apt install g++\n"
              "  Windows  winget install Microsoft.VisualStudio.2022.BuildTools\n"
              "           (with the C++ workload), or winget install LLVM.LLVM",
              file=sys.stderr)
        return 1

    failures: list[str] = []
    for label, argv, env in toolchains:
        try:
            done = subprocess.run(argv, cwd=HERE, env=env, capture_output=True, text=True,
                                  timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            failures.append(f"{label}: {exc}")
            continue
        if done.returncode == 0 and OUTPUT.exists():
            for name in LEFTOVERS:
                (HERE / name).unlink(missing_ok=True)
            print(f"built {OUTPUT.parent.name}/{OUTPUT.name} with {label}")
            return 0
        failures.append(f"{label}: exit {done.returncode}\n"
                        f"{(done.stderr or done.stdout).strip()[:2000]}")
        OUTPUT.unlink(missing_ok=True)

    print("every available compiler failed; Ollie will use the Python fallbacks:",
          file=sys.stderr)
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
