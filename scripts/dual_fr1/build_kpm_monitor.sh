#!/usr/bin/env bash
set -euo pipefail

# Reuse the pinned local FlexRIC API/library without modifying or installing it.
FLEXRIC_DIR=${FLEXRIC_DIR:-/home/nyu/flexric}
FLEXRIC_BUILD=${FLEXRIC_BUILD:-$FLEXRIC_DIR/build-ocudu}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
OUTPUT=${1:-/tmp/falcon-xapp-oran-moni-dual}
LIBRARY=$FLEXRIC_BUILD/src/xApp/libe42_xapp.a
TIME_OBJECT=$FLEXRIC_BUILD/src/util/CMakeFiles/e2_time_obj.dir/time_now_us.c.o
[[ -f "$LIBRARY" && -f "$TIME_OBJECT" ]] || {
  printf 'Missing pinned FlexRIC build artifacts under %s\n' "$FLEXRIC_BUILD" >&2
  exit 1
}

gcc -g -std=gnu11 -fPIE -W -Wall -Wextra -Wno-unused-result \
  -fstack-protector-strong -fstack-clash-protection \
  -DASN -DE2AP_V3 -DKPM_V3_00 -DNONE_XAPP -DSERVICE_MODEL_DIR_PATH='"/"' \
  -I "$FLEXRIC_DIR/src" \
  "$SCRIPT_DIR/xapp_oran_moni_dual.c" \
  "$FLEXRIC_DIR/src/util/alg_ds/alg/defer.c" "$TIME_OBJECT" "$LIBRARY" \
  -pthread -lsctp -ldl -lconfig -o "$OUTPUT"
printf 'Built: %s\n' "$OUTPUT"
