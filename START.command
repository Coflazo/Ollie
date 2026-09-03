#!/usr/bin/env bash
#
# Double-click this file on macOS or Linux. It pulls the latest main, rebuilds whatever
# needs rebuilding, checks nothing is broken, and starts Ollie.
#
# The procedure itself lives in scripts/launch.py, and START.bat is the same four lines for
# Windows. Writing it once in Python rather than twice in two shells is the only reason the
# Windows path behaves identically to this one instead of approximately like it.

cd "$(dirname "$0")" || exit 1

for candidate in ./.venv/bin/python python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 || [ -x "$candidate" ]; then
    exec "$candidate" scripts/launch.py "$@"
  fi
done

printf '\n  No Python found.\n'
printf '  macOS:  brew install python@3.12   (or install the Xcode command line tools)\n'
printf '  Linux:  sudo apt install python3.12 python3.12-venv\n\n'
printf '  Press return to close. '
read -r _
exit 1
