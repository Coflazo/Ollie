#!/usr/bin/env sh
# Shim. The build itself lives in build.py, which is the one that knows about MSVC, MinGW,
# Clang, GCC and the three different shared-library extensions. Keeping this file means the
# POSIX habit and every existing instruction still work; keeping it this short means there
# is only ever one implementation to fix.
#
# `sh` rather than `bash` on purpose: Alpine and the smaller container images ship without
# bash, and there is nothing here that needs it.
set -eu
cd "$(dirname "$0")"

for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" build.py "$@"
  fi
done

echo "no python found; install Python 3.12 or later" >&2
exit 1
