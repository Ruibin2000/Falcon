# DU RF Metrics Offline Acceptance — October 23, 2026

Plan 1 Step 6 passed the staged provider, codec, callback, and action round trip.
The final provider XML executed all 17 frozen offline cases with zero skips,
failures, or errors. This closes the offline exit criterion only. Stop before
Step 7; source application, native suites, deployment builds, and hardware/live
acceptance remain unauthorized and **Not run**.

Context: [Plan 1](../../plans/e2sm-kpm-du-rf-metrics.md),
[measurement semantics](../notes/e2sm_kpm_du_rf_metrics_semantics.md),
[reviewer decision](2026-10-19_du_rf_metrics_patch_review_and_snapshot_design.md#decision),
[contract review](2026-10-21_du_rf_metrics_contract_review.md),
[monitor review](2026-10-21_flexric_du_rf_monitor_review.md),
[Step 5 handoff](2026-10-21_du_rf_metrics_validation_harness.md), and
[October 21 development log](../../dev_logs/2026-10-21_haoding.md).
Existing explanatory documents, plans, indexes, and logs were preserved.

## Repositories and affected paths

| Repository | Branch and starting HEAD | Scope |
| --- | --- | --- |
| Falcon, `/home/nyu/Desktop/Falcon_repo/Falcon` | `E2SM-KPM`, `9d3b30b5b7bd42d0ea95d03f14ab7201ca0f9379` | Corrected three test/runner files and added this acceptance record. |
| OCUDU, `/home/nyu/ocudu` | `E2SM-KPM`, `4cffc0479f9620f668a7ac79aeb314b2e31525e4` | Read-only source/build inputs. All five RF targets and their index entries remain unmodified at HEAD. |
| FlexRIC, `/home/nyu/flexric` | `falcon-xapp`, `10b8ec79d0f011902d329b2ed37f33f8b101b591` | Strictly read-only checkout and `build-ocudu`; committed timestamp repair retained. |

Falcon changes:

- `tests/flexric_du_rf_metrics_test.c`: added two standalone fixture-boundary
  lines around the original decoded fixture replay.
- `scripts/flexric/test_du_rf_metrics.py`: required exactly one ordered fixture
  frame and restricted the six-row fixture validator to that frame.
- `tests/test_du_rf_runner_guards.py`: retained the original 35 cases and added
  four regressions covering complete replay, framing failures, strict fields,
  and outside-frame values that must not hide missing/incorrect fixture rows.
- `docs/e2sm-kpm/2026-10-23_du_rf_metrics_offline_acceptance.md`: this record.

The cumulative OCUDU/FlexRIC RF patches, separate native-test patch, C++ fixture,
runtime configuration, and frozen GTest names were unchanged. No branch or
worktree was created/switched. The nine unrelated UE-identity `.pyc` files were
preserved byte for byte; FlexRIC retained its existing untracked build entries.

## Fixture trace integration correction

The existing C harness printed six original fixture traces, then 16 verified
diagnostic traces for precision, negative zero, non-finite REAL, INTEGER, and
unsupported record types. The Python validator scanned every `RF_TRACE` row as
an original fixture row, incorrectly rejecting the first reused UE/metric key.

The original fixture replay is now delimited by exact standalone lines
`FALCON_RF_FIXTURE_BEGIN` and `FALCON_RF_FIXTURE_END`. The runner requires each
once, in order, and exactly six trace rows inside. Existing per-UE values,
REAL/noValue types, units, identity, header consistency, field structure, and
duplicate/missing/unknown-row checks remain strict inside that frame. Values
outside cannot compensate for an incorrect or absent fixture row.

All 16 diagnostic traces remain in `callback.log`, with their existing C
assertions. The six global PASS markers, readable output, local RSRQ notice,
obsolete-name rejection, revision guards, clean-source guards, patch checks,
output guards, and KPM-before-SDK link order remain required. Production trace
format and measurement semantics did not change.

## Frozen requirements and exact execution

Persistent run root:
`/home/nyu/verification/e2sm-kpm/run-TQcKveEB/`.

This invocation's preflight, input snapshots, regression results, preservation
checks, and final summary are in:
`step6-offline-20261023-1ied7v8n/` under that root. The four plan commands retain
their original run-root `.command.txt`, `.log`, and `.status` paths.

The existing frozen gate was verified before acceptance and between stages;
it was not regenerated or refrozen. The manifest remains 17 offline plus
36 later native names, with no removed or renamed requirement:

| Frozen file | SHA-256 |
| --- | --- |
| `required-tests.json`, identical to `tests/e2sm_kpm_du_rf_required_tests.json` | `3b1636a4b76e81833fe31ef1b46221ebc5a6cf2d11452c767db4fcacdfc8bf0b` |
| `check-gtest.py` | `754cf7bd434bf4c84933559a0a73abd42f9b20c5b5a72dea81a664345b88f007` |

The plan's `record_check` function and these commands are retained in the
invocation's `offline-driver.sh`:

```bash
FALCON_REPO=/home/nyu/Desktop/Falcon_repo/Falcon
OCUDU_SOURCE=/home/nyu/ocudu
FLEXRIC_SOURCE=/home/nyu/flexric
E2_RF_EVIDENCE=/home/nyu/verification/e2sm-kpm/run-TQcKveEB

sha256sum -c "$E2_RF_EVIDENCE/acceptance-gate.sha256"
record_check provider-stage python3 "$FALCON_REPO/scripts/ocudu/test_du_rf_metrics.py" \
  --ocudu-source "$OCUDU_SOURCE" --ocudu-build "$OCUDU_SOURCE/build" \
  --output-dir "$E2_RF_EVIDENCE/ocudu"
record_check flexric-stage python3 "$FALCON_REPO/scripts/flexric/test_du_rf_metrics.py" \
  --flexric-source "$FLEXRIC_SOURCE" --flexric-build "$FLEXRIC_SOURCE/build-ocudu" \
  --wire-fixture "$E2_RF_EVIDENCE/ocudu/du-rf-indication.bin" \
  --ocudu-test "$E2_RF_EVIDENCE/ocudu/ocudu_du_rf_metrics_test" \
  --output-dir "$E2_RF_EVIDENCE/flexric"
record_check provider-final env \
  FALCON_KPM_ACTION_INPUT="$E2_RF_EVIDENCE/flexric/flexric-action.bin" \
  FALCON_KPM_WIRE_OUTPUT="$E2_RF_EVIDENCE/ocudu/du-rf-indication-final.bin" \
  "$E2_RF_EVIDENCE/ocudu/ocudu_du_rf_metrics_test" \
  --gtest_output="xml:$E2_RF_EVIDENCE/ocudu/provider-final.xml"
record_check provider-xml-gate python3 "$E2_RF_EVIDENCE/check-gtest.py" \
  "$E2_RF_EVIDENCE/ocudu/provider-final.xml" "$E2_RF_EVIDENCE" offline-provider
```

Each pre-build `pgrep -a odu`, `pgrep -a nearRT-RIC`, and `pgrep -a xapp`
returned 1 without output. Runner process checks remained active before each
compiler/link invocation. The build commands were sequential and used
`nice -n 19`: four C++ translation units, two C translation units, and three
links. Compilers/flags/libraries came from existing build records; no CMake
rerun or full `odu` build occurred. All generated outputs and compiler temporary
files were inside evidence. The actual monitor was linked but never executed.

## Results and decoded values

| Check | Result and retained evidence |
| --- | --- |
| Python runner regressions | Passed: 39 tests, zero skips/failures/errors; `framing-review/guards.{stdout,stderr}.txt` and `guards.status.json`. No compiler was invoked by these mock-based guards. |
| `provider-stage` | Command/log exits 0/0; 16 passed and one planned skip because the external FlexRIC action did not exist yet. |
| `flexric-stage` | Command/log exits 0/0; real monitor/harness compilation and linking, actual KPM decoding, six harness PASS markers, and one successful external-action admission test. |
| `provider-final` | Command/log exits 0/0; all 17 frozen standalone cases run/completed, zero skips/failures/errors/disabled; `ocudu/provider-final.xml`. All 13 original cases were included. |
| `provider-xml-gate` | Command/log exits 0/0; `PASS offline-provider: 17 executed; all 17 required cases passed`. |
| Fixture trace replay | Exactly six rows inside one frame and 16 diagnostic rows outside, 22 total; `flexric/callback.log`. |
| Source/build input preservation | Passed: 50 recorded source/compiler/object/archive hashes reverified; source HEADs/statuses and nine unrelated `.pyc` hashes preserved. |
| Frozen gate and existing documents | Passed: frozen bytes/hashes unchanged; existing explanatory documents, plans, and logs unchanged. |

The real FlexRIC decoder/callback produced:

| UE F1AP ID | RSRP | SNR |
| --- | --- | --- |
| `1007` | REAL `-13.125` dBFS | REAL `21.75` dB |
| `2091` | REAL `0` dBFS | REAL `0` dB |
| `3199` | `noValue`, rendered `n/a` dBFS | `noValue`, rendered `n/a` dB |

All six fixture traces carried PLMN `001-01`, MNC width 2, node type 7, node
ID 411/unused bits 0, CU/DU ID 1, row index 0, `incomplete=false`, and header
time `1792778757394439` microseconds. This is the synthetic fixture's KPM
header time, not a PHY sample timestamp or a snapshot-generation correlation.

| Wire artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `ocudu/du-rf-indication.bin` | 223 | `383c396ef89ac7640c4975b991f02c982f7cd9ef3eee24d9072d3c1c227b3882` |
| `ocudu/du-rf-indication-final.bin` | 223 | `383c396ef89ac7640c4975b991f02c982f7cd9ef3eee24d9072d3c1c227b3882` |
| `flexric/flexric-action.bin` | 168 | `a1ced278f2dd14dd9204e71a479ca2c2ec323742f7de2327d11a1cf8b333657e` |

The indication files were freshly generated in separate runs; identical
payload hashes are expected for the same synthetic values. Build-input hashes
identify reused archives and do not establish a fresh deployment build.

## Warnings and remaining limitations

There were zero compiler warnings and two GNU linker warnings:

```text
xapp_oran_moni.o: requires executable stack (because the .note.GNU-stack section is executable)
flexric_du_rf_metrics_test.o: requires executable stack (because the .note.GNU-stack section is executable)
```

Read-only `readelf` checks found the existing shared monitor object already
had an executable `.note.GNU-stack` section, and the existing shared monitor
binary had `GNU_STACK RWE`, matching both staged executables. This is consistent
with the inherited GCC nested-function implementation of FlexRIC's `defer`
macro. The warning and executable-stack requirement remain open; no linker
option was changed to suppress them. Full command/output records and a copy of
the existing `defer.h` are in the invocation's readelf/reference evidence.

The reviewer-deferred concurrency limitation remains: metrics-strand writes
and E2 reads are unsynchronized. No provider mutex, generation, cleanup
relocation, receive-executor change, or concurrent-consistency pass was added.
The decoded trace does not prove same-window RF pairs or source correlation.

Native provider/scheduler/CRC/adapter suites, production source application,
deployment builds, signal/subscription lifecycle in a connected xApp, live UE
traffic, B210 access, and RF calibration are **Not run**. The 36 native test
names remain frozen for later authorized Step 7 execution. No install, service
control, network traffic test, or push was performed.

Step 7 remains blocked until explicit Plan 2 Stage A acceptance, an agreed
hardware slot, and source-ownership coordination. FlexRIC source application
ownership and generation-dependent requirements in Steps 7–11 still require
review. This Step 6 result does not grant that authorization.
