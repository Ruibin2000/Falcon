#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
UE_AT_PORT=/dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.2-port0
exec python3 -B "$SCRIPT_DIR/reconnect_ue.py" \
  --auto-cell-lock --at-port "$UE_AT_PORT" "$@" --ue 1
