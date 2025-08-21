#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
	echo "Usage: $0 /path/to/binary [args...]" >&2
	exit 1
fi

BIN="$1"
shift || true

if [ ! -x "$BIN" ]; then
	echo "error: not an executable: $BIN" >&2
	exit 1
fi

# Deterministic XRay log prefix so analyze.sh can find logs.
# Override with XRAY_BASE to change directory/prefix.
PREFIX="${XRAY_BASE:-$(pwd)/outputs/xray-log.$(basename "$BIN").}"

# Default XRAY_OPTIONS; users can override by exporting XRAY_OPTIONS beforehand.
: "${XRAY_OPTIONS:=verbosity=1:xray_mode=xray-basic:patch_premain=true}"

# Ensure logs go to the known prefix (append even if XRAY_OPTIONS already set).
export XRAY_OPTIONS="${XRAY_OPTIONS}:xray_logfile_base=${PREFIX}"

exec "$BIN" "$@"


