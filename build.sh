#!/usr/bin/env bash
set -euo pipefail

# Minimal Meson build helper: reconfigure (if present) and build.
# Usage: ./build.sh [xray]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure local user bin (for pip-installed meson/ninja) is on PATH
export PATH="$HOME/.local/bin:$PATH"

BUILD_DIR="builddir"
XRAY_FLAG=""

# Check if XRay is requested
if [ "${1:-}" = "xray" ]; then
    XRAY_FLAG="-Dxray=true"
    echo "Building with LLVM XRay instrumentation..."
fi

meson setup --reconfigure "$BUILD_DIR" $XRAY_FLAG
meson compile -C "$BUILD_DIR"


