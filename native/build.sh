#!/usr/bin/env bash
# One compiler invocation. No CMake, no build system, no generated files to check in.
#
# CMake is a reasonable choice for a project with many targets. This has one translation
# unit and one output, so a build system here would be pure ceremony.
set -euo pipefail

cd "$(dirname "$0")"

case "$(uname -s)" in
  Darwin) EXT=dylib ;;
  *)      EXT=so ;;
esac

# -march=native is skipped deliberately: the build machine and the demo machine are
# different architectures, and a library that segfaults on someone else's CPU is worse
# than one that is marginally slower.
clang++ -std=c++20 -O3 -fPIC -shared \
        -Wall -Wextra -Wno-unused-parameter \
        -o "libollie_native.${EXT}" ollie_native.cpp

echo "built native/libollie_native.${EXT}"
