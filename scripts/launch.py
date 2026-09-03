#!/usr/bin/env python3
"""Get the latest code, build what needs building, check nothing is broken, start Ollie.

There is one implementation and three doors into it: START.command for a double-click on
macOS and Linux, START.bat for a double-click on Windows, and running this file directly.
Both wrappers are four lines. That is deliberate: the previous arrangement had the whole
procedure written twice in shell, and the Windows half did not exist at all, so a Windows
user's only route in was a sequence of commands out of the README.

Everything here is standard library, because it has to run before the virtual environment
it creates exists.

Safe to run repeatedly. It never discards your work: uncommitted changes are set aside, the
pull happens, and they are handed straight back. If your branch has local commits it leaves
them alone and says so rather than guessing what you wanted.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = sys.platform == "win32"
DEFAULT_PORT = 8765
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


# --------------------------------------------------------------------------- output


def _enable_ansi() -> bool:
    """Colour on every terminal that can take it, and none that cannot.

    Windows consoles ignore ANSI escapes until a process asks for them, so without this the
    output is legible but littered with things like ESC[1m. Windows Terminal enables the
    flag itself; conhost, which is still what a double-click opens on many machines, does
    not.
    """
    if not sys.stdout.isatty():
        return False
    if not WINDOWS:
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        return bool(kernel32.SetConsoleMode(
            handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING))
    except (ImportError, AttributeError, OSError):
        return False


# A tick redirected into a file on Windows meets cp1252 and raises UnicodeEncodeError,
# which turns a cosmetic character into a crashed launcher. Ask for UTF-8 and accept a
# replacement character if even that is refused.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

_COLOUR = _enable_ansi()


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOUR else text


# Flushed on every line. Redirected into a log, Python block-buffers stdout, and a build
# that takes two minutes then shows nothing at all until it is already over.
def step(text: str) -> None:
    print(f"\n{_paint('1', text)}", flush=True)


def note(text: str) -> None:
    print(f"  {_paint('2', text)}", flush=True)


def ok(text: str) -> None:
    print(f"  {_paint('38;5;209', 'v')} {text}", flush=True)


def bad(text: str) -> None:
    print(f"  {_paint('31', 'x ' + text)}", flush=True)


def die(text: str) -> None:
    bad(text)
    # A double-clicked window closes the instant the process exits, taking the error with
    # it. Hold it open long enough to be read.
    if sys.stdin and sys.stdin.isatty():
        input(f"\n  {_paint('2', 'Press return to close.')} ")
    raise SystemExit(1)


# ------------------------------------------------------------------------ processes


def which(name: str) -> str | None:
    """Resolve a command to a full path before anything tries to run it.

    Not decoration. On Windows, subprocess spawns through CreateProcess, whose bare-name
    PATH search only considers .exe: `subprocess.run(["npm", ...])` raises FileNotFoundError
    because npm is npm.cmd, and PATHEXT resolution is a shell feature rather than a kernel
    one. shutil.which does apply PATHEXT, so resolving first is what makes npm, ollama and
    git callable identically on all three platforms.
    """
    return shutil.which(name)


def run(argv: list[str], *, check: bool = False, quiet: bool = True,
        cwd: Path | None = None, timeout: int | None = None) -> subprocess.CompletedProcess:
    resolved = which(argv[0]) or argv[0]
    return subprocess.run(
        [resolved, *argv[1:]], cwd=cwd or ROOT, check=check, timeout=timeout,
        capture_output=quiet, text=True,
    )


def spawn_detached(argv: list[str]) -> None:
    """Start something that must outlive this process, on either process model."""
    resolved = which(argv[0])
    if not resolved:
        return
    creation = 0
    keywords: dict[str, object] = {}
    if WINDOWS:
        # Without a new process group, Ctrl-C in this window also kills the child.
        creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) \
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        keywords["creationflags"] = creation
    else:
        keywords["start_new_session"] = True
    try:
        subprocess.Popen([resolved, *argv[1:]], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, **keywords)
    except OSError:
        pass


# ---------------------------------------------------------------- 1. latest code


def update_from_git() -> None:
    step("1. Getting the latest code")

    if not which("git"):
        note("git is not installed, so this is whatever code is already here")
        return
    if not (ROOT / ".git").exists():
        note("not a git checkout, using the code as it is")
        return

    # A half-finished merge or rebase leaves files conflicted, and every git command after
    # that refuses with "needs merge" until it is cleared. Backing out is safe for the same
    # reason the pull is: nothing committed lives only on a branch.
    if (ROOT / ".git" / "rebase-merge").exists() or (ROOT / ".git" / "rebase-apply").exists():
        note("a rebase was in progress, backing out of it")
        run(["git", "rebase", "--abort"])
    if (ROOT / ".git" / "MERGE_HEAD").exists():
        note("a merge was in progress with conflicts, backing out of it")
        if run(["git", "merge", "--abort"]).returncode != 0:
            run(["git", "reset", "-q", "--merge"])
    if run(["git", "diff", "--name-only", "--diff-filter=U"]).stdout.strip():
        note("clearing files left in a conflicted state")
        run(["git", "checkout", "-f", "--", "."])

    stashed = False
    if run(["git", "status", "--porcelain"]).stdout.strip():
        # The launcher wrappers are excluded on purpose: a shell reads a script
        # incrementally, so stashing the file currently executing can pull it out from
        # under itself mid-run.
        stashed = run([
            "git", "stash", "push", "-u", "-m", f"ollie-start-{int(time.time())}", "--",
            ".", ":(exclude)START.command", ":(exclude)START.bat",
        ]).returncode == 0
        if stashed:
            note("your uncommitted changes are set aside for a moment")

    if run(["git", "fetch", "-q", "origin"], timeout=120).returncode != 0:
        note("could not reach GitHub, using what is already here")

    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    if branch != "main":
        note(f"switching from {branch} to main")
        if run(["git", "checkout", "-q", "main"]).returncode != 0:
            die("could not switch to main. Commit your work first.")

    ahead = run(["git", "rev-list", "--count", "origin/main..main"]).stdout.strip() or "0"
    if ahead != "0":
        note(f"you have {ahead} local commit(s) main does not. Not touching them.")
        note("push them yourself when ready: git push origin main")
    # Only fast-forward. A merge or rebase decision belongs to you, not to a launcher.
    elif run(["git", "merge", "-q", "--ff-only", "origin/main"]).returncode == 0:
        ok("up to date with main")
    else:
        note("could not fast-forward; continuing with the current code")

    head = run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    ok(f"on {run(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).stdout.strip()} at {head}")

    if stashed:
        if run(["git", "stash", "pop"]).returncode == 0:
            ok("your uncommitted changes are back")
        else:
            bad("your changes conflict with what was pulled, so they are still stashed")
            note("get them with: git stash pop     (or inspect: git stash show -p)")


# --------------------------------------------------------------- 2. dependencies


def venv_python() -> Path:
    """Windows puts the interpreter in Scripts and names it python.exe. Everything else
    puts it in bin and names it python. Guessing wrong is the single most common way a
    cross-platform script fails on first run."""
    return ROOT / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")


def ensure_environment() -> Path:
    step("2. Checking dependencies")

    python = venv_python()
    if not python.exists():
        note("first run, creating the virtual environment (a minute or two)")
        if subprocess.run([sys.executable, "-m", "venv", str(ROOT / ".venv")],
                          cwd=ROOT).returncode != 0:
            die("could not create .venv")
        install(python, "installing dependencies")
    elif subprocess.run([str(python), "-c",
                         "import fastapi, pydantic, cryptography, pdfplumber"],
                        capture_output=True).returncode != 0:
        # Cheap check that also catches a pull which added a dependency.
        install(python, "installing new dependencies")
    ok("python ready")
    return python


def install(python: Path, message: str) -> None:
    note(message)
    subprocess.run([str(python), "-m", "pip", "install", "-q", "--upgrade", "pip"],
                   cwd=ROOT, capture_output=True)
    done = subprocess.run([str(python), "-m", "pip", "install", "-q", "-e", ".[dev]"],
                          cwd=ROOT, capture_output=True, text=True)
    if done.returncode != 0:
        print(done.stderr[-2000:], file=sys.stderr)
        die("could not install dependencies")


def build_native(python: Path) -> None:
    """Always rebuild, and say plainly which path the user ends up on.

    The C++ carries the checks that run on every single reply: the copyright overlap guard,
    retrieval fusion, and memory scoring. The Python twins are correct and slower, so
    dropping to them is a performance decision the user should be told about rather than
    discover. The loader treats a library missing a symbol as absent, so a stale one after a
    pull silently costs speed with no other sign.
    """
    done = subprocess.run([str(python), str(ROOT / "native" / "build.py")],
                          cwd=ROOT, capture_output=True, text=True)
    if done.returncode == 0:
        ok(done.stdout.strip().splitlines()[-1] if done.stdout.strip()
           else "native library built")
        return
    # Say what actually went wrong. Reporting every failure as a missing compiler sent
    # people off to install one they already had, when the real cause was a DLL still
    # mapped by a copy of Ollie that was never shut down.
    note("the native library did not build, so the hot paths run in Python "
         "(correct, just slower)")
    for line in (done.stderr or done.stdout or "").strip().splitlines()[:4]:
        note(f"  {line}")


def build_web() -> None:
    # A built dist is everything serving needs; node_modules is only an input to building
    # it. Requiring both would make someone who pruned node_modules to reclaim disk sit
    # through a full npm install on every launch for no change in what gets served.
    dist = ROOT / "web" / "dist"
    lock = ROOT / "web" / "package-lock.json"
    fresh = (dist / "index.html").exists() and (
        not lock.exists() or lock.stat().st_mtime <= dist.stat().st_mtime)
    if fresh:
        ok("interface ready")
        return
    if not which("npm"):
        if dist.exists():
            note("npm not found, using the interface that is already built")
            return
        die("the interface is not built and npm is not installed. Install Node 20 or "
            "later from nodejs.org, then run this again.")

    note("building the interface (first run, or it changed)")
    web = ROOT / "web"
    if run(["npm", "install", "--silent"], cwd=web, timeout=1800).returncode != 0:
        die("npm install failed. Check that Node 20 or later is installed: node --version")
    if run(["npm", "run", "build", "--silent"], cwd=web, timeout=1800).returncode != 0:
        die("the interface failed to build.")
    ok("interface ready")


# ---------------------------------------------------------------------- 3. verify


def run_tests(python: Path) -> None:
    step("3. Checking nothing is broken")
    log = ROOT / ".ollie-tests.log"
    done = subprocess.run([str(python), "-m", "pytest", "-q"], cwd=ROOT,
                          capture_output=True, text=True)
    output = (done.stdout or "") + (done.stderr or "")
    log.write_text(output, encoding="utf-8", errors="replace")
    if done.returncode == 0:
        ok(next((line for line in reversed(output.strip().splitlines()) if line.strip()),
                "tests passed"))
        return
    bad(f"tests failed. Full output: {log}")
    for line in output.strip().splitlines()[-15:]:
        print(f"    {line}")
    if not (sys.stdin and sys.stdin.isatty()):
        die("stopped")
    if input(f"\n  {_paint('2', 'Start anyway? [y/N]')} ").strip().lower() not in ("y", "yes"):
        die("stopped")


# ----------------------------------------------------------------------- 4. start


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        # Without this, a socket left in TIME_WAIT reads as free on Linux and busy on
        # Windows, so the two platforms would disagree about the same machine state.
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) != 0


def ollie_is_serving(port: int) -> bool:
    """Is the thing holding this port one of ours, or somebody else's server?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/health", timeout=2) as r:
            return bool(json.loads(r.read().decode("utf-8", "replace")).get("ok"))
    except (urllib.error.URLError, OSError, ValueError):
        return False


def pids_on_port(port: int) -> list[int]:
    """Whoever is listening, asked the way each platform answers."""
    pids: set[int] = set()
    if WINDOWS:
        out = run(["netstat", "-ano", "-p", "tcp"]).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0].upper() == "TCP" \
                    and parts[1].endswith(f":{port}") and parts[3].upper() == "LISTENING":
                if parts[4].isdigit():
                    pids.add(int(parts[4]))
    elif which("lsof"):
        for line in run(["lsof", "-ti", f":{port}"]).stdout.split():
            if line.strip().isdigit():
                pids.add(int(line.strip()))
    return sorted(pids)


def free_the_port(port: int) -> int:
    """Double-clicking twice is the normal way to use this, so an older copy of Ollie has to
    be replaced rather than reported as a crash. Anything that is not Ollie is left strictly
    alone and we move to the next port instead: a launcher that kills unidentified processes
    to claim a number is not a trade anyone agreed to."""
    if port_is_free(port):
        return port

    if not ollie_is_serving(port):
        for candidate in range(port + 1, port + 20):
            if port_is_free(candidate):
                note(f"port {port} is used by something else, using {candidate} instead")
                return candidate
        die(f"port {port} is busy and so are the next 20.")

    note("an older copy is already running, replacing it")
    for pid in pids_on_port(port):
        if WINDOWS:
            # /T takes the children too. A venv's python.exe on Windows is a stub that
            # launches the real interpreter, so the process holding the port is a child and
            # killing it alone can leave the wrapper behind still holding the library open.
            run(["taskkill", "/F", "/T", "/PID", str(pid)])
        else:
            run(["kill", str(pid)])
    for _ in range(20):
        if port_is_free(port):
            return port
        time.sleep(0.25)

    for candidate in range(port + 1, port + 20):
        if port_is_free(candidate):
            note(f"the old copy would not close, using port {candidate} instead")
            return candidate
    die(f"port {port} is busy and would not free up.")
    return port  # unreachable; keeps the type honest


def ollama_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/version", timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def ensure_ollama() -> bool:
    """Start a locally installed Ollama rather than telling the user to open another
    terminal, but never install it for them and never touch a remote OLLAMA_HOST."""
    if ollama_alive():
        return True
    if os.environ.get("OLLAMA_HOST") or not which("ollama"):
        return False
    note("starting Ollama")
    spawn_detached(["ollama", "serve"])
    for _ in range(20):
        if ollama_alive():
            return True
        time.sleep(0.5)
    return False


def serve(python: Path, port: int, demo: bool, extra: list[str]) -> int:
    step("4. Starting Ollie")
    argv = [str(python), "-m", "ollie", "serve", "--port", str(port), *extra]
    if demo:
        note("demo mode: scripted replies, everything else real")
        argv.append("--demo")
    elif not ensure_ollama():
        note("Ollama is not reachable, so starting in demo mode instead")
        note("for real replies: install Ollama from ollama.com, then run this again")
        argv.append("--demo")
    # Not exec: Windows has no execve that replaces the process in a way a console window
    # survives, so the launcher stays as the parent on every platform and forwards the code.
    try:
        return subprocess.run(argv, cwd=ROOT).returncode
    except KeyboardInterrupt:
        return 0


# ------------------------------------------------------------------------- driver


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="launch", description="Update, build, check and start Ollie.")
    parser.add_argument("--demo", action="store_true",
                        help="scripted replies instead of a model; everything else real")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--quick", action="store_true",
                        help="skip the git pull and the test run")
    parser.add_argument("--no-pull", action="store_true")
    parser.add_argument("--no-tests", action="store_true")
    parser.add_argument("--model", help="override the model tag")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    print(_paint("38;5;209", "\n  Ollie"))

    if not (args.quick or args.no_pull):
        update_from_git()

    python = ensure_environment()
    build_native(python)
    build_web()

    if not (args.quick or args.no_tests):
        run_tests(python)

    extra: list[str] = []
    if args.model:
        extra += ["--model", args.model]
    if args.no_browser:
        extra.append("--no-browser")
    return serve(python, free_the_port(args.port), args.demo, extra)


if __name__ == "__main__":
    raise SystemExit(main())
