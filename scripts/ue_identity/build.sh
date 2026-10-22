#!/usr/bin/env bash
set -euo pipefail
FLEXRIC_DIR=${FLEXRIC_DIR:-/home/nyu/flexric}
FLEXRIC_BUILD=${FLEXRIC_BUILD:-$FLEXRIC_DIR/build-ocudu}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
OUTPUT=${1:-/tmp/falcon-xapp-ue-identity}
LIBRARY=$FLEXRIC_BUILD/src/xApp/libe42_xapp.a
TIME_OBJECT=$FLEXRIC_BUILD/src/util/CMakeFiles/e2_time_obj.dir/time_now_us.c.o
PLUGIN_DIR=${FALCON_IDENTITY_SM_DIR:-/tmp/falcon-ue-identity-sm}
[[ -f "$LIBRARY" && -f "$TIME_OBJECT" ]] || {
  printf 'Missing pinned FlexRIC artifacts under %s\n' "$FLEXRIC_BUILD" >&2
  exit 1
}
python3 "$SCRIPT_DIR/build_plugin.py" --source "$FLEXRIC_DIR" --build "$FLEXRIC_BUILD" --output "$PLUGIN_DIR"
gcc -g -std=gnu11 -fPIE -Wall -Wextra -Wno-unused-result \
  -fstack-protector-strong -fstack-clash-protection \
  -DASN -DE2AP_V3 -DKPM_V3_00 -DNONE_XAPP -DSERVICE_MODEL_DIR_PATH='"/"' \
  -I "$FLEXRIC_DIR/src" "$SCRIPT_DIR/e2_collector.c" \
  "$FLEXRIC_DIR/src/util/alg_ds/alg/defer.c" "$TIME_OBJECT" "$LIBRARY" \
  -pthread -lsctp -ldl -lconfig -lm -o "$OUTPUT"
printf 'Built: %s\n' "$OUTPUT"
