#!/usr/bin/env bash
set -euo pipefail

# Minimal Meson build helper: reconfigure (if present) and build.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure local user bin (for pip-installed meson/ninja) is on PATH
export PATH="$HOME/.local/bin:$PATH"

BUILD_DIR="builddir"

meson setup --reconfigure "$BUILD_DIR" -Dbuildtype=debugoptimized -Db_lto=false -Dcpp_args='-fno-omit-frame-pointer'
meson compile -C "$BUILD_DIR"