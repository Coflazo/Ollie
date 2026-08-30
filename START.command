#!/usr/bin/env bash
#
# Double-click this file. It pulls the latest main, rebuilds whatever needs rebuilding,
# and starts Ollie.
#
# Safe to run repeatedly. It never discards your work: uncommitted changes are set aside,
# the pull happens, and they are handed straight back. If your branch has local commits it
# leaves them alone and says so rather than guessing what you wanted.

cd "$(dirname "$0")" || exit 1

BOLD=$'\033[1m'; DIM=$'\033[2m'; WARM=$'\033[38;5;209m'; RED=$'\033[31m'; OFF=$'\033[0m'
step() { printf "\n%s%s%s\n" "$BOLD" "$1" "$OFF"; }
note() { printf "  %s%s%s\n" "$DIM" "$1" "$OFF"; }
ok()   { printf "  %s✓%s %s\n" "$WARM" "$OFF" "$1"; }
bad()  { printf "  %s✗ %s%s\n" "$RED" "$1" "$OFF"; }

die() {
  bad "$1"
  printf "\n%sPress return to close.%s " "$DIM" "$OFF"
  read -r _
  exit 1
}

printf "%s\n  Ollie\n%s" "$WARM" "$OFF"

# ----------------------------------------------------------------- pull the latest

step "1. Getting the latest code"

if ! command -v git >/dev/null 2>&1; then
  die "git is not installed. Install the Xcode command line tools: xcode-select --install"
fi

# A half-finished merge or rebase leaves files in a conflicted state, and every git
# command after that refuses with "needs merge" until it is cleared. Backing out is safe
# here for the same reason the pull below is: nothing committed lives only on a branch.
if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
  note "a rebase was in progress, backing out of it"
  git rebase --abort >/dev/null 2>&1 || true
fi
if [ -f .git/MERGE_HEAD ]; then
  note "a merge was in progress with conflicts, backing out of it"
  git merge --abort >/dev/null 2>&1 || git reset -q --merge >/dev/null 2>&1 || true
fi
if [ -n "$(git diff --name-only --diff-filter=U 2>/dev/null)" ]; then
  note "clearing files left in a conflicted state"
  git checkout -f -- . >/dev/null 2>&1 || true
fi

STASH=""
if [ -n "$(git status --porcelain)" ]; then
  STASH="ollie-start-$(date +%s)"
  # This script is excluded from the stash on purpose. `-u` takes untracked files, and
  # bash reads a script incrementally rather than all at once, so stashing the file
  # currently executing can pull it out from under itself mid-run.
  git stash push -u -m "$STASH" -- . ':(exclude)START.command' >/dev/null 2>&1 \
    && note "your uncommitted changes are set aside for a moment"
fi

git fetch -q origin 2>/dev/null || note "could not reach GitHub, using what is already here"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  note "switching from $BRANCH to main"
  git checkout -q main 2>/dev/null || die "could not switch to main. Commit your work first."
fi

# Only fast-forward. A merge or rebase decision belongs to you, not to a launcher.
AHEAD="$(git rev-list --count origin/main..main 2>/dev/null || echo 0)"
if [ "$AHEAD" != "0" ]; then
  note "you have $AHEAD local commit(s) main does not. Not touching them."
  note "push them yourself when ready: git push origin main"
else
  git merge -q --ff-only origin/main 2>/dev/null && ok "up to date with main" \
    || note "could not fast-forward; continuing with the current code"
fi
ok "on $(git rev-parse --abbrev-ref HEAD) at $(git rev-parse --short HEAD)"

# Hand the work back now, while there is still a shell to report a problem. Doing this at
# the end is not possible: the script finishes with exec, which replaces the process, so
# anything scheduled for exit never runs.
if [ -n "$STASH" ]; then
  if git stash pop >/dev/null 2>&1; then
    ok "your uncommitted changes are back"
  else
    bad "your changes conflict with what was pulled, so they are still stashed"
    note "get them with: git stash pop     (or inspect: git stash show -p)"
  fi
fi

# ------------------------------------------------------------------- dependencies

step "2. Checking dependencies"

PY=""
for candidate in ./.venv/bin/python python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then PY="$candidate"; break; fi
done
[ -n "$PY" ] || die "no Python found. Install it: brew install python@3.12"

if [ ! -x ./.venv/bin/python ]; then
  note "first run, creating the virtual environment (a minute or two)"
  "$PY" -m venv .venv || die "could not create .venv"
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -e ".[dev]" || die "could not install dependencies"
fi
PY=./.venv/bin/python

# Cheap check that also catches a pull which added a dependency.
if ! $PY -c "import fastapi, pydantic, cryptography, pdfplumber" 2>/dev/null; then
  note "installing new dependencies"
  ./.venv/bin/pip install -q -e ".[dev]" || die "could not install dependencies"
fi
ok "python ready"

# Always rebuild. The loader treats a library missing a symbol as absent, so a stale
# .dylib after a pull silently drops you onto the Python path.
if command -v clang++ >/dev/null 2>&1; then
  ./native/build.sh >/dev/null 2>&1 && ok "native library built" \
    || note "native build failed, the Python fallback covers it"
else
  note "no compiler, using the Python fallback (run: xcode-select --install)"
fi

if [ ! -d web/dist ] || [ ! -d web/node_modules ] || [ web/package-lock.json -nt web/dist ]; then
  note "building the interface (first run, or it changed)"
  ( cd web && npm install --silent && npm run build --silent ) \
    || die "the interface failed to build. Check that Node 20+ is installed: node --version"
fi
ok "interface ready"

# ------------------------------------------------------------------------- verify

step "3. Checking nothing is broken"
if $PY -m pytest -q >/tmp/ollie-tests.log 2>&1; then
  ok "$(tail -1 /tmp/ollie-tests.log)"
else
  bad "tests failed. Full output: /tmp/ollie-tests.log"
  tail -15 /tmp/ollie-tests.log
  printf "\n  %sStart anyway? [y/N]%s " "$DIM" "$OFF"
  read -r answer
  case "$answer" in [yY]*) ;; *) die "stopped" ;; esac
fi

# --------------------------------------------------------------------------- start

step "4. Starting Ollie"

# Double-clicking twice is the normal way to use this, so a copy already holding the port
# has to be replaced rather than reported as a crash. Without this the second run dies on
# "address already in use" while the browser still shows the older build, which looks like
# the pull did nothing.
if lsof -ti :8765 >/dev/null 2>&1; then
  note "an older copy is already running, replacing it"
  pkill -f "ollie serve" >/dev/null 2>&1 || true
  for _ in $(seq 1 10); do
    lsof -ti :8765 >/dev/null 2>&1 || break
    sleep 0.5
  done
  if lsof -ti :8765 >/dev/null 2>&1; then
    die "something else is using port 8765. Close it, or run: $PY -m ollie serve --port 8766"
  fi
fi

# Demo mode uses scripted replies so the product is walkable on hardware that cannot run
# inference quickly. Pass --demo to this script to force it. Otherwise a real model is
# used when Ollama has one.
if [ "${1:-}" = "--demo" ]; then
  note "demo mode: scripted replies, everything else real"
  exec $PY -m ollie serve --demo
fi

if ! curl -sf --max-time 3 "${OLLAMA_HOST:-http://localhost:11434}/api/version" >/dev/null 2>&1; then
  if command -v ollama >/dev/null 2>&1 && [ -z "${OLLAMA_HOST:-}" ]; then
    note "starting Ollama"
    nohup ollama serve >/dev/null 2>&1 &
    for _ in $(seq 1 20); do
      curl -sf --max-time 2 http://localhost:11434/api/version >/dev/null 2>&1 && break
      sleep 0.5
    done
  fi
fi

if curl -sf --max-time 3 "${OLLAMA_HOST:-http://localhost:11434}/api/version" >/dev/null 2>&1; then
  exec $PY -m ollie serve
fi

note "Ollama is not reachable, so starting in demo mode instead"
note "for real replies: install Ollama from ollama.com, then run this again"
exec $PY -m ollie serve --demo
