#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 /path/to/binary [trace_format]" >&2
  echo "  trace_format: trace_event (default), yaml, json" >&2
  exit 1
fi

BIN="$1"
FORMAT="${2:-trace_event}"

if [ ! -f "$BIN" ]; then
  echo "error: binary not found: $BIN" >&2
  exit 1
fi

NAME="$(basename "$BIN")"

# Directory to search for logs and to write outputs
SEARCH_DIR="${XRAY_DIR:-./outputs}"
mkdir -p "$SEARCH_DIR"

# Prefix used for matching; override with XRAY_BASE_PREFIX if you want a custom base
PREFIX="${XRAY_BASE_PREFIX:-xray-log.${NAME}}"

# --- Find newest matching XRay log in ./outputs ---
# Uses simple 'ls -t | head -1' method
LOG="$(ls -t "${SEARCH_DIR}/${PREFIX}"* 2>/dev/null | head -1 || true)"
if [ -z "${LOG}" ]; then
  echo "error: no XRay logs found in '${SEARCH_DIR}' matching prefix '${PREFIX}'" >&2
  echo "Hint: ensure your run step writes logs into '${SEARCH_DIR}', or set XRAY_DIR/XRAY_BASE_PREFIX." >&2
  exit 1
fi

echo "Using log: ${LOG}" >&2

# Pick output file path inside ./outputs
case "$FORMAT" in
  trace_event)
    OUT="${SEARCH_DIR}/trace.json"
    llvm-xray convert -symbolize -instr_map="$BIN" -f trace_event "$LOG" > "$OUT"
    echo "Wrote: $OUT"
    ;;
  yaml)
    OUT="${SEARCH_DIR}/trace.yaml"
    llvm-xray convert -symbolize -instr_map="$BIN" -f yaml "$LOG" > "$OUT"
    echo "Wrote: $OUT"
    ;;
  json)
    OUT="${SEARCH_DIR}/trace.json"
    llvm-xray convert -symbolize -instr_map="$BIN" -f json "$LOG" > "$OUT"
    echo "Wrote: $OUT"
    ;;
  *)
    echo "error: unknown format '$FORMAT' (use trace_event|yaml|json)" >&2
    exit 2
    ;;
esac
