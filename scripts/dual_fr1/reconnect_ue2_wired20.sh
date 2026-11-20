#!/usr/bin/env bash
# UE2 / direct n78 wired 20 MHz: PCI 2, SSB ARFCN 639648.
# Verify/restore the owned UE2 cell lock at startup, then register and connect PDU.
# Manual command (Spark wired baseline TX 70 / RX 35):
# sudo bash ~/falcon-ue2-wired20/reconnect_ue2_wired20.sh \
#   --auto-cell-lock --interval 3 --verbose 3 --registration-timeout 30
# The Python entry supplies these defaults; explicit options override them.
set -euo pipefail
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 -B "$SCRIPT_DIR/reconnect_ue2_wired20.py" "$@"
