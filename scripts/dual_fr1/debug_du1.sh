#!/usr/bin/env bash
# Fixed DU1 entry point for the temporary GDB crash-capture launcher.
set -euo pipefail
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  printf 'Usage: bash %s [--prepare-only]\n' "$0"
  exit 0
fi
DU1_DEBUG_SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec bash "$DU1_DEBUG_SCRIPT_DIR/debug_du.sh" 1 "$@"
