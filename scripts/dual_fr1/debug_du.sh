#!/usr/bin/env bash
# Start one selected DU under GDB without changing system core settings.
set -euo pipefail

usage() {
  printf 'Usage: bash %s {1|2} [--prepare-only]\n' "$0"
}

case "${1:-}" in
  1|2) DU_DEBUG_ROLE=$1; shift ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
DU_DEBUG_PREPARE_ONLY=0
case "${1:-}" in
  --prepare-only) DU_DEBUG_PREPARE_ONLY=1; shift ;;
  -h|--help) usage; exit 0 ;;
esac
if (( $# != 0 )); then
  usage >&2
  exit 2
fi

DU_DEBUG_SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DU_DEBUG_SOURCE=/home/nyu/ocudu
DU_DEBUG_BINARY=$DU_DEBUG_SOURCE/build-integrated/apps/du_split_8/odu
DU_DEBUG_GDB=$(command -v gdb) || { printf 'Missing gdb\n' >&2; exit 1; }
case "$DU_DEBUG_ROLE" in
  1) DU_DEBUG_CONFIGS=(configs/du1_b210_n78_3660mhz.yml) ;;
  2) DU_DEBUG_CONFIGS=(configs/du2_b210_n78_20mhz.yml configs/du2_flexric.yml) ;;
esac
for DU_DEBUG_REQUIRED in "$DU_DEBUG_BINARY" "$DU_DEBUG_SCRIPT_DIR/capture_du_crash.gdb" \
  "$DU_DEBUG_SCRIPT_DIR/run_du_console.sh"; do
  [[ -r "$DU_DEBUG_REQUIRED" ]] || { printf 'Missing file: %s\n' "$DU_DEBUG_REQUIRED" >&2; exit 1; }
done
for DU_DEBUG_CONFIG in "${DU_DEBUG_CONFIGS[@]}"; do
  [[ -r "$DU_DEBUG_SOURCE/$DU_DEBUG_CONFIG" ]] || {
    printf 'Missing file: %s\n' "$DU_DEBUG_SOURCE/$DU_DEBUG_CONFIG" >&2
    exit 1
  }
done
if (( ! DU_DEBUG_PREPARE_ONLY )) && [[ ! -t 0 || ! -t 1 || ! -t 2 ]]; then
  printf 'Run directly in the DU%s interactive terminal.\n' "$DU_DEBUG_ROLE" >&2
  exit 2
fi

DU_DEBUG_RUN=$(mktemp -d "/tmp/falcon-du${DU_DEBUG_ROLE}-crash.XXXXXXXX")
cp "$DU_DEBUG_SCRIPT_DIR/capture_du_crash.gdb" "$DU_DEBUG_RUN/capture.gdb"
DU_DEBUG_BASE="$DU_DEBUG_RUN/du${DU_DEBUG_ROLE}.yml"
cp "$DU_DEBUG_SOURCE/${DU_DEBUG_CONFIGS[0]}" "$DU_DEBUG_BASE"
DU_DEBUG_ARGS=(-c "$DU_DEBUG_BASE")
if (( ${#DU_DEBUG_CONFIGS[@]} == 2 )); then
  cp "$DU_DEBUG_SOURCE/${DU_DEBUG_CONFIGS[1]}" "$DU_DEBUG_RUN/e2.yml"
  DU_DEBUG_ARGS+=(-c "$DU_DEBUG_RUN/e2.yml")
fi
sha256sum "$DU_DEBUG_BINARY" > "$DU_DEBUG_RUN/binary.sha256"
printf 'DU%s debug directory: %s\n' "$DU_DEBUG_ROLE" "$DU_DEBUG_RUN"
if (( DU_DEBUG_PREPARE_ONLY )); then
  printf 'Prepared only; no DU, radio, sudo or debugger process started.\n'
  exit 0
fi

cd "$DU_DEBUG_SOURCE"
exec bash "$DU_DEBUG_SCRIPT_DIR/run_du_console.sh" "$DU_DEBUG_RUN/startup.log" \
  sudo env "FALCON_DU_CRASH_DIR=$DU_DEBUG_RUN" "FALCON_DU_CRASH_ROLE=DU$DU_DEBUG_ROLE" \
  "$DU_DEBUG_GDB" -nx -q --batch -x "$DU_DEBUG_RUN/capture.gdb" \
  --args "$DU_DEBUG_BINARY" "${DU_DEBUG_ARGS[@]}" \
  log --filename "$DU_DEBUG_RUN/du.log"
