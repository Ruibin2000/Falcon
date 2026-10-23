# E2SM-KPM DU RF Metrics Implementation Plan

Enable FlexRIC to receive the correct per-UE uplink PUSCH RSRP and SNR values
already produced by the OCUDU DU. Implement the measurement getters, advertise
their capabilities through E2SM-KPM, preserve their values through the codec,
and verify them in the FlexRIC xApp during actual uplink traffic.

| Field | Value |
| --- | --- |
| Plan | 1 |
| Task | `e2sm-kpm-du-rf-metrics` |
| Status | Planned; implementation and acceptance pending |
| Created at | 13 : 23: 41 Oct 11, 2026 EDT |
| Last updated at | 14 : 41: 36 Oct 11, 2026 EDT |
| Time zone | `America/New_York` |
| Developer | To be assigned |
| Reviewer | To be assigned |
| Falcon inspection baseline | `3f12f627d80cdad14bc9a5ab267f8f65452a2da9` |
| OCUDU inspection baseline | `69801c7e9a3a72e4f29d98f14f626f156444c3ca` |
| FlexRIC inspection baseline | `736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8`, with the existing local timestamp repair |
| Prerequisites | Accepted Plan 2 Stage A (Steps 1–8), including live five-metric E2-to-dummy delivery; preserve FlexRIC's local timestamp repair |
| Execution order | [Plan 2](xapp-kpm-app-subscription.md) Steps 1–8 (Stage A); then remaining Plan 1 RF work and acceptance; then Plan 2 Steps 9–11 (Stage B) |
| Initial deployment | Existing OCUDU DU and FlexRIC RIC/xApp test environment |

Maintain this file as the single plan for this task. Mark steps complete only
after their exit criteria pass and their evidence has been retained.

## Current State and Scope

The current DU scheduler exports `pusch_rsrp_db` and `pusch_snr_db`. The existing
KPM `get_rsrp` and `get_rsrq` functions both return an integer cast of the first
UE snapshot's `pusch_snr_db`. They neither return the named measurement nor map
each requested UE correctly. There is no independent SNR getter in that provider.
The existing E2 connection and five-metric xApp reception provide a working
transport baseline; successful transport does not establish RF measurement correctness.

Falcon already contains cumulative OCUDU and FlexRIC RF patches, regression
sources, and a seven-metric xApp configuration. Both cumulative patches passed
applicability checks against the inspected host checkouts on October 11.
The RF changes have not been applied to those checkouts. The historical
verification document reports offline passes, but its `/tmp` result directories
are unavailable. Repeat acceptance with fresh retained evidence.

OCUDU now includes a local configuration commit on top of the original
`050a2bb72e1d794cd60570d809987c1fcda3e54b` patch base. Its five RF source files
are unchanged between that base and `69801c7`. However, the current offline
runner rejects the newer HEAD. Resolve this deliberately in Step 5.

This task covers DU PUSCH telemetry, the KPM provider, capability advertisement,
subscription, encoding/decoding, and xApp output. Keep the existing PHY estimator,
RF configuration, averaging algorithm, timestamp repair, and original five
metrics. Separate work is required for measured RSRQ, downlink UE measurements,
calibrated dBm, CU RF telemetry, faster sampling, and unrelated CQI/PRB getter defects.

## Measurement Contract

| Exported name | Source | Unit and representation | Missing data |
| --- | --- | --- | --- |
| `FALCON.PUSCH.RSRP.dBFS` | Requested UE's scheduler-window `pusch_rsrp_db` | Software dBFS; KPM `REAL` | `noValue` if the UE/sample is unavailable or the value is non-finite |
| `FALCON.PUSCH.SNR.dB` | Requested UE's scheduler-window `pusch_snr_db` | dB; KPM `REAL`; legacy SNR label for the selected PHY SINR estimate | `noValue` unless a finite value and at least one SNR sample exist |
| RSRQ capability notice | Local xApp message | `RSRQ = n/a source=xapp-capability-status reason=unavailable_in_du` | No RSRQ subscription or measured value |

Both measured metrics support UE-level collection with exactly one unfiltered
`NO_LABEL` entry. Reject node/cell aggregation and expanded labels. Preserve
request order and one record per requested UE, including unavailable UEs.
A measured zero is valid; missing data must not become zero.

The application default for `pusch_sinr_calc_method` is `post_equalization`.
Record the actual configured method; the PHY also supports `channel_estimator`
and `evm`. The current PHY/FAPI path quantizes RSRP in 0.1 dB increments and SINR
in 0.002 dB increments, with saturation before the scheduler receives them.
The scheduler averages the available reported dB values, including RF samples
associated with failed transport-block CRCs. Preserve these semantics.

```mermaid
flowchart LR
    PHY[PUSCH PHY measurements] --> FAPI[FAPI conversion and quantization]
    FAPI --> MAC[MAC CRC indication]
    MAC --> SCH[Per UE scheduler window]
    SCH --> KPM[UE mapped KPM getters]
    KPM --> WIRE[Format 3 APER indication over E2]
    WIRE --> RIC[FlexRIC KPM decoder]
    RIC --> APP[xApp values and identity]
```

## Step 1 Capture the Baseline

- [ ] Record source revisions, local changes, configuration hashes, build settings,
  compiler versions, and the binaries currently used by the operator.
- [ ] Preserve FlexRIC's local timestamp encoder/decoder repair and its untracked
  `kpm_timestamp.h`. Save the diff and helper file before RF work.
- [ ] Establish implementation branches from the recorded baselines. Preserve
  the OCUDU configuration commit and all unrelated local changes.
- [ ] Create a unique persistent evidence directory outside both source/build trees.

Use Bash in the engineering terminal. Keep these variables and the logging
function available for subsequent build and offline steps:

```bash
set -euo pipefail
FALCON_REPO=/home/nyu/Desktop/Falcon_repo/Falcon
OCUDU_SOURCE=/home/nyu/ocudu
FLEXRIC_SOURCE=/home/nyu/flexric
E2_RF_EVIDENCE_ROOT=/home/nyu/verification/e2sm-kpm
mkdir -p "$E2_RF_EVIDENCE_ROOT"
E2_RF_EVIDENCE=$(mktemp -d "$E2_RF_EVIDENCE_ROOT/run-XXXXXXXX")
mkdir -p "$E2_RF_EVIDENCE"/{baseline,ocudu,flexric,native,live}
printf 'Evidence directory: %s\n' "$E2_RF_EVIDENCE"

record_check() {
  local label="$1"
  shift
  printf '%q ' "$@" > "$E2_RF_EVIDENCE/$label.command.txt"
  printf '\n' >> "$E2_RF_EVIDENCE/$label.command.txt"
  set +e
  "$@" 2>&1 | tee "$E2_RF_EVIDENCE/$label.log"
  local results=("${PIPESTATUS[@]}")
  set -e
  printf 'command_exit=%s\nlog_exit=%s\n' "${results[0]}" "${results[1]}" \
    > "$E2_RF_EVIDENCE/$label.status"
  test "${results[0]}" -eq 0 && test "${results[1]}" -eq 0
}

git -C "$FALCON_REPO" rev-parse HEAD > "$E2_RF_EVIDENCE/baseline/falcon-head.txt"
git -C "$OCUDU_SOURCE" rev-parse HEAD > "$E2_RF_EVIDENCE/baseline/ocudu-head.txt"
git -C "$FLEXRIC_SOURCE" rev-parse HEAD > "$E2_RF_EVIDENCE/baseline/flexric-head.txt"
git -C "$OCUDU_SOURCE" status --short > "$E2_RF_EVIDENCE/baseline/ocudu-status.txt"
git -C "$FLEXRIC_SOURCE" status --short > "$E2_RF_EVIDENCE/baseline/flexric-status.txt"
git -C "$FLEXRIC_SOURCE" diff --binary > "$E2_RF_EVIDENCE/baseline/flexric-local.patch"
cp "$FLEXRIC_SOURCE/src/sm/kpm_sm/kpm_sm_v03.00/ie/kpm_data_ie/kpm_ric_info/kpm_timestamp.h" \
  "$E2_RF_EVIDENCE/baseline/kpm_timestamp.h"
sha256sum "$OCUDU_SOURCE"/configs/{cu,du1_b210_n78_20mhz,du1_flexric}.yml \
  > "$E2_RF_EVIDENCE/baseline/config-sha256.txt"
sha256sum "$OCUDU_SOURCE/build/apps/du_split_8/odu" \
  "$FLEXRIC_SOURCE/build-ocudu/examples/xApp/c/monitor/xapp_oran_moni" \
  /usr/local/bin/flexric/xApp/c/xapp_oran_moni \
  "$FLEXRIC_SOURCE/build-ocudu/src/sm/kpm_sm/kpm_sm_v03.00/libkpm_sm.so" \
  /usr/local/lib/flexric/libkpm_sm.so \
  > "$E2_RF_EVIDENCE/baseline/binary-sha256.txt"
git -C "$FALCON_REPO" show 3f12f62:tests/ocudu_du_rf_metrics_test.cpp \
  > "$E2_RF_EVIDENCE/baseline/provider-tests.cpp"
record_check ocudu-compiler /usr/bin/clang++-18 --version
record_check flexric-compiler /usr/bin/gcc --version
record_check ocudu-build-settings cmake -LA -N "$OCUDU_SOURCE/build"
record_check flexric-build-settings cmake -LA -N "$FLEXRIC_SOURCE/build-ocudu"
```

**Exit criteria:** the recorded state matches the approved implementation base,
timestamp changes are recoverable, and baseline configuration/binary identities
are retained. Stop and review any new source changes before proceeding. Do not
reset the source checkout to the older patch base.

## Step 2 Trace and Confirm the Source Measurements

- [ ] Trace RSRP and selected SINR through the production source paths below.
- [ ] Record the estimator selection, units, saturation, quantization, averaging,
  and sample-validity rules in the implementation notes.
- [ ] Confirm the active DU configuration enables both scheduler and RLC metrics,
  with `du_report_period: 1000`.

Paths below are relative to the OCUDU source root:

| Area | Files to inspect |
| --- | --- |
| PHY measurement and estimator selection | `lib/phy/upper/signal_processors/pusch/dmrs_pusch_estimator_impl.cpp`, `include/ocudu/phy/upper/channel_state_information.h`, `apps/units/flexible_o_du/o_du_low/du_low_config.h` |
| PHY and MAC conversion | Locate `phy_to_fapi_results_event_fastpath_translator.cpp`, `fapi_to_mac_indications_fastpath_translator.cpp`, and `ocudu_scheduler_adapter.cpp` under `lib/`; inspect `include/ocudu/fapi/p7/builders/crc_indication_builder.h` |
| Scheduler values and validity | `lib/scheduler/logging/scheduler_metrics_handler.cpp`, `include/ocudu/scheduler/scheduler_metrics.h` |
| KPM consumption and advertisement | `lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp`, its header, `e2sm_kpm_impl.cpp`, and `e2sm_kpm_asn1_packer.cpp` |

RSRP is uplink DM-RS power in software dBFS. It is neither calibrated dBm nor
UE-reported downlink RSRP. `FALCON.PUSCH.SNR.dB` preserves the scheduler's legacy
name for its selected SINR value; do not create an independent SINR claim from
the same field.

**Exit criteria:** source-to-metric semantics are understood and recorded.
No PHY estimator or radio-gain change is required to expose these values over E2.

## Step 3 Review and Complete the OCUDU Candidate Patch

Use the [cumulative OCUDU patch](../patches/ocudu/050a2bb-du-rf-metrics.patch)
as the implementation candidate. Make necessary corrections in a scratch copy
and regenerate the reviewed patch; keep the host's five patch targets unchanged
until Step 7 so the staging runner can test the candidate.

| File | Required implementation |
| --- | --- |
| `include/ocudu/scheduler/scheduler_metrics.h` | Expose `nof_pusch_snr_reports` in the snapshot and document the actual RF units. |
| `lib/scheduler/logging/scheduler_metrics_handler.cpp` | Copy the window's SNR sample count into the snapshot; retain the existing means and reset behavior. |
| `lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h` | Declare `get_snr` and the shared RF getter; remove the incorrect RSRQ getter. |
| `lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp` | Register both vendor names at UE level; select the correct UE snapshot; return `REAL` or `noValue`. |
| `lib/e2/e2sm/e2sm_kpm/e2sm_kpm_impl.cpp` | Enforce one `NO_LABEL` entry for these RF metrics during action admission. |

- [x] Map each requested gNB-CU UE F1AP ID through the existing translator to the
  internal DU UE index. Search the snapshot by `ue_index`; never use that index
  as a vector offset or take the first UE for all requests.
- [x] Return one record for every requested UE, in request order. Missing,
  disconnected, incompatible, or non-finite entries become `noValue`.
- [x] Preserve negative/fractional values and finite zero. For SNR, require a
  positive sample count so the missing default zero cannot become a measurement.
- [x] Reject unsupported labels and node/cell scopes consistently at admission
  and collection. Do not fabricate aggregate RF values.
- [x] Remove generic dummy RSRP/RSRQ registrations; advertise the exact two vendor
  names through the production RAN-function description.
- [ ] **Deferred by reviewer decision 2026-10-21 (known limitation: unsynchronized
  metrics-strand writes vs E2 reads; see [design doc](../docs/e2sm-kpm/2026-10-19_du_rf_metrics_patch_review_and_snapshot_design.md#decision)).**
  Establish safe scheduler snapshot replacement and reads. Metrics and E2
  can run on different executor strands; the existing vector replacement does
  not by itself establish safe concurrent access. Use reviewed executor
  confinement or consistent immutable/locked snapshots across affected readers.
- [ ] **Deferred by reviewer decision 2026-10-21 (known limitation: unsynchronized
  metrics-strand writes vs E2 reads; see [design doc](../docs/e2sm-kpm/2026-10-19_du_rf_metrics_patch_review_and_snapshot_design.md#decision)).**
  Design an opt-in RF trace with a monotonically increasing scheduler
  snapshot generation, requested UE, internal UE index, selected float-to-double
  values, and counts. Capture generation and values in the same safe getter
  lookup. Add the report-correlation hooks as a separate diagnostic patch in
  Step 7, after staging verification, to preserve the five-file runner contract.

Step 3 static candidate review completed on 2026-10-21 under the reviewer-deferred
scope above. The five checked implementation items record source/patch review;
offline acceptance remains pending Steps 5-6. The RF-only Style 3 admission fix,
reviewed patch hash, commands, and limitations are recorded in the
[contract review](../docs/e2sm-kpm/2026-10-21_du_rf_metrics_contract_review.md).
Evidence: `/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step3-review-20261021-6e3yqixn/`.

**Exit criteria:** the reviewed candidate implements the contract without
changing unrelated measurement behavior. Record its hash. The historical
RSRP-only patch remains an alternative artifact and must not be stacked with
the cumulative RF patch.

## Step 4 Review and Complete FlexRIC Subscription and Output

Use the [cumulative FlexRIC patch](../patches/flexric/73650812-du-rf-metrics.patch)
and [seven-metric configuration](../configs/flexric/xapp_du_rf_metrics.conf).
Preserve the already applied timestamp repair; do not apply it again.

- [x] Request the existing five DU metrics plus the two exact vendor names in
  one Style 4 subscription at 1000 ms. Keep E2AP v3 and KPM v3.00.
- [x] Decode the resulting Format 3 UE reports and associate values with their
  measurement names. Validate name/value counts and unsupported formats.
- [x] Accept RF `REAL` values; render `noValue` as `n/a`. Reject integer RF
  encodings and non-finite values with a clear diagnostic.
- [x] Print units and full context: PLMN, node type, gNB ID, CU/DU ID when present,
  UE F1AP ID, KPM header time, and row index. UE F1AP ID alone is insufficient
  across several DUs; it is also not a C-RNTI or subscriber IMSI.
- [x] Add an opt-in decoded RF trace, for example enabled by a new
  `FALCON_KPM_RF_TRACE=1` switch. Emit `REAL` values with round-trip double
  precision (`%.17g`), together with complete node/DU identity,
  `header_time_us`, UE F1AP ID, row index, metric name, and record type.
  Preserve the readable two-decimal normal output. Extend the callback harness
  to verify both forms and the explicit missing-value trace.
- [x] Keep RSRQ as an explicitly local capability notice. Do not subscribe to an
  unavailable RSRQ or separately named SINR metric.
- [x] On Ctrl+C/SIGTERM, set a stop flag and perform subscription deletion and SDK
  cleanup in the main thread. Do not perform SDK cleanup inside a signal handler.
- [x] Retain the timestamp-repaired service-model plugin and existing decoder.
  This RF task changes measurement exposure and monitor handling, not ASN.1 schemas.

Step 4 implementation static review completed on 2026-10-21. The eight checked
items record completed implementation review. Staged callback/codec/action
acceptance passed on 2026-10-23 in Step 6; see the
[offline acceptance record](../docs/e2sm-kpm/2026-10-23_du_rf_metrics_offline_acceptance.md).
The scratch monitor and callback harness also passed syntax-only compilation
with zero warnings/errors. Actual SIGINT/SIGTERM delivery, connected
subscription deletion, and SDK shutdown remain **Not run**. The reviewed patch
hash, commands, and implementation limitations are recorded in the
[monitor review](../docs/e2sm-kpm/2026-10-21_flexric_du_rf_monitor_review.md).
Evidence: `/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step4-review-20261021-7738r6e1/syntax-check-0qdfmi9v/`.

**Exit criteria:** subscription names/types match the DU contract, the callback
handles missing/malformed data without crashing, and the original five metrics
remain present. Preserve the intentional offline link order: KPM ASN runtime
before the SDK's E2AP ASN runtime.

## Step 5 Adapt the Validation Harness and Close Test Gaps

- [x] Compare all five RF production files between `050a2bb` and `69801c7` and
  record that comparison before updating revision checks.
- [x] Update `scripts/ocudu/test_du_rf_metrics.py` to explicitly accept the reviewed
  `69801c7e9a3a72e4f29d98f14f626f156444c3ca` baseline. An explicit allowlist may
  also retain the original base. Preserve rejection of unknown revisions,
  modified patch targets, unsafe output paths, and failed patch checks.
- [x] Record the patch's original base and its reviewed compatibility with the
  configuration-only commit. Rebase the patch if any production target differs;
  do not remove the guard simply to make the test run.
- [x] Keep staging-only tests separate from tests of the applied source. The
  existing runner copies originals and applies the RF patch itself; it must run
  before applying that patch to its input source checkout.
- [x] Design native regression additions for the existing OCUDU provider,
  scheduler, and FAPI builder test targets. Apply those test edits in Step 7.
  Keep native test changes in a separate reviewed patch from the five-file RF
  patch: the current staging runner compiles every `.cpp` named by its RF patch.
- [x] Create and review a mandatory test-name manifest before running acceptance.
  Retain all 13 original standalone cases, append required new cases, and list
  the required native provider/scheduler/conversion cases by exact
  `classname.name`. Include every case covering the matrix below. Freeze its
  hash before the run; do not reduce the manifest to fit passing results.

Step 5 implementation and test-design work completed on 2026-10-21. The six
checked items record baseline compatibility, guarded runner support, staging
separation, separate native-test design, and the frozen mandatory manifest.
The runners deliberately accept OCUDU `4cffc04` and FlexRIC `10b8ec79` under
the reviewed baseline deviations. The 53 required names comprise 17 offline
and 36 native cases; native application and execution remain **Not run**.
The original 13 standalone cases were retained, with four additions. Commands,
hashes, coverage, and limitations are recorded in the
[harness handoff](../docs/e2sm-kpm/2026-10-21_du_rf_metrics_validation_harness.md).
Evidence: `/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step5-harness-20261021-vhst0vi4/`.
The later trace-framing correction and successful offline execution are
recorded in Step 6; no native execution pass is implied by these checkboxes.

Initialize the manifest from the retained original fixture, then populate the
native lists and append the additional standalone cases:

```bash
python3 - "$E2_RF_EVIDENCE" <<'PY'
import json
import pathlib
import re
import sys
evidence = pathlib.Path(sys.argv[1])
source = (evidence / 'baseline/provider-tests.cpp').read_text()
original = [f'{suite}.{name}' for suite, name in
            re.findall(r'TEST_F\(\s*(\w+)\s*,\s*(\w+)\s*\)', source)]
if len(original) != 13 or len(set(original)) != 13:
    raise SystemExit('Unexpected original fixture; review the baseline')
(evidence / 'baseline/required-provider.json').write_text(json.dumps(original, indent=2))
manifest = {'offline-provider': original,
            'native-provider': [], 'native-scheduler': [], 'native-crc': []}
destination = evidence / 'required-tests.json'
if destination.exists():
    raise SystemExit('Manifest already exists; review it rather than overwrite it')
destination.write_text(json.dumps(manifest, indent=2))
PY
```

The empty native lists are placeholders to complete during test design, not
permission to skip native coverage. Add a manifest entry and the same XML gate
for any additional GTest executable used for adapter acceptance.

Required coverage:

| Area | Required cases and expected behavior |
| --- | --- |
| Metric advertisement | Decode `pack_ran_function_description()` from the production provider; both vendor names appear at UE scope, with no dummy RSRP/RSRQ capability. |
| Value semantics | Distinct RSRP/SNR values, negative fractions, measured zero, absent samples, NaN/infinity, empty/replaced windows. |
| UE mapping | Sparse/reordered identifiers, removed/missing UEs, wrong UE type, stable order and cardinality. |
| Admission | Correct `NO_LABEL`; reject missing/duplicate/expanded labels and unsupported cell/node scope. |
| Scheduler path | Count reset, absent sample, measured zero, two-sample mean, and RF samples on failed TB CRCs. |
| Snapshot consistency | Deferred by reviewer decision 2026-10-21 (known limitation: unsynchronized metrics-strand writes vs E2 reads; see [design doc](../docs/e2sm-kpm/2026-10-19_du_rf_metrics_patch_review_and_snapshot_design.md#decision)). No concurrent-snapshot or generation-consistency pass is claimed. |
| Adapter boundaries | Production missing-value sentinels, RSRP 0.1 dB and SINR 0.002 dB quantization, saturation, and valid zero through conversion. |
| Codec integration | Actual Style 4 admission, Format 3 APER encoding, FlexRIC decoding, seven-metric action encoding, and OCUDU admission of that action. |
| Monitor robustness | Incorrect RF integers, invalid REAL values, missing mappings, incomplete reports, DU identity, local RSRQ notice, and stop handling. |

The existing fixture injects values after PHY/FAPI conversion; it does not prove
physical calibration or conversion correctness. Existing mock-based E2 Setup
tests may still contain dummy RSRQ lists. Add production-provider coverage rather
than editing a mock assertion solely to match the new names.

**Exit criteria:** the runner supports the approved current base without weakening
its safeguards, and the test matrix covers both the existing 13 cases and the
identified conversion/advertisement gaps.

## Step 6 Run Offline Verification Before Applying Source Changes

- [x] Verify the frozen mandatory manifest and XML-gate hashes before acceptance
  and retain all original provider test names plus the required additions.
- [x] Complete provider-stage, flexric-stage, provider-final, and the mandatory
  XML gate with zero command/log exit statuses and retained evidence.
- [x] Execute all 17 required offline-provider cases, including the original 13,
  in the final run with zero skips, failures, or errors.
- [x] Verify the three UE fixture value/type pairs, fresh nonempty indication
  and action artifacts, complete callback context, and readable/precise output.
- [x] Verify unchanged source checkouts, the five OCUDU RF targets, frozen
  requirements, and the reused build inputs after staged acceptance.

Step 6 offline acceptance passed on 2026-10-23. The trace-framing correction
and acceptance record are committed in Falcon as `269d063` and `e87d527`.
The five checked items record executed offline acceptance, superseding the
earlier pending-offline notices. The final provider XML passed all 17 required
cases; the external seven-metric action test also passed. The 39 Python guard
tests passed, and callback output retained six fixture plus 16 diagnostic
trace rows. There were zero compiler warnings and two inherited
executable-stack linker warnings; their baseline comparison is documented.
Native suites, deployment builds, connected signal/SDK lifecycle checks,
and hardware/live acceptance remain **Not run**. See the
[offline acceptance record](../docs/e2sm-kpm/2026-10-23_du_rf_metrics_offline_acceptance.md).
Evidence: `/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step6-offline-20261023-1ied7v8n/verification-summary.json`;
the four command/log/status records and generated artifacts are retained in
its parent run directory. Frozen manifest and XML-gate hashes were preserved.

Run these commands only after Step 5 is implemented. All candidate outputs go
to the new evidence directory; the source checkouts remain unchanged.

```bash
cat > "$E2_RF_EVIDENCE/check-gtest.py" <<'PY'
import json
import pathlib
import sys
import xml.etree.ElementTree as ET
xml_path, evidence_path, suite = sys.argv[1:]
evidence = pathlib.Path(evidence_path)
required = json.loads((evidence / 'required-tests.json').read_text()).get(suite)
if (not isinstance(required, list) or not required or
        any(not isinstance(name, str) or not name for name in required) or
        len(set(required)) != len(required)):
    raise SystemExit(f'Missing or invalid mandatory test list: {suite}')
if suite == 'offline-provider':
    original = json.loads((evidence / 'baseline/required-provider.json').read_text())
    if not set(original).issubset(required):
        raise SystemExit('The manifest dropped original provider cases')
root = ET.parse(xml_path).getroot()
cases = list(root.iter('testcase'))
names = [f"{case.get('classname')}.{case.get('name')}" for case in cases]
missing = sorted(set(required) - set(names))
bad = [name for name, case in zip(names, cases)
       if case.get('status') != 'run' or case.get('result') != 'completed'
       or any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped'))]
suite_errors = [node.tag for node in root.iter()
                if node.tag in ('testsuite', 'testsuites') and
                any(int(node.get(attr, '0')) for attr in ('failures', 'errors'))]
if not cases or missing or bad or suite_errors or len(set(names)) != len(names):
    raise SystemExit(f'FAIL {suite}: missing={missing}, not_passed={bad}, '
                     f'suite_errors={suite_errors}, duplicate_names={len(set(names)) != len(names)}')
print(f'PASS {suite}: {len(cases)} executed; all {len(required)} required cases passed')
PY
sha256sum "$E2_RF_EVIDENCE/required-tests.json" "$E2_RF_EVIDENCE/check-gtest.py" \
  > "$E2_RF_EVIDENCE/acceptance-gate.sha256"

record_check provider-stage python3 "$FALCON_REPO/scripts/ocudu/test_du_rf_metrics.py" \
  --ocudu-source "$OCUDU_SOURCE" \
  --ocudu-build "$OCUDU_SOURCE/build" \
  --output-dir "$E2_RF_EVIDENCE/ocudu"

record_check flexric-stage python3 "$FALCON_REPO/scripts/flexric/test_du_rf_metrics.py" \
  --flexric-source "$FLEXRIC_SOURCE" \
  --flexric-build "$FLEXRIC_SOURCE/build-ocudu" \
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

The accepted 17-case OCUDU staging run reported 16 passes and one planned
external-subscription skip. FlexRIC supplied the missing action fixture, and
the final run executed all 17 cases with zero skips/failures/errors. Future
acceptance runs must retain all 13 original cases plus the required additions,
with zero skips/failures/errors and exit code 0 in the final complete run.

Inspect the decoded fixture for UE F1AP IDs `1007`, `2091`, and `3199`: expect
RSRP/SNR `REAL` pairs `(-13.125, 21.75)`, `(0.0, 0.0)`, and `(noValue, noValue)`.
These are synthetic codec values, not live RF measurements. Require nonempty
fresh indication/action fixtures and retain callback/subscription logs. The
OCUDU runner does not create `provider.log`; the logging wrapper captures its output.

**Exit criteria:** the full provider/codec/action round trip passes with retained
commands and exit statuses. Staged linking against existing archives is an
offline check; it does not replace the full rebuild in Step 7.

## Step 7 Apply the Reviewed Package and Build the Actual Targets

- [ ] Stop test traffic and let the current xApp delete its subscription. Stop DU
  before RIC in their existing terminals. Keep the working CU/core configuration.
- [ ] Recheck the reviewed source base and patch hashes. If they changed since
  Step 6, resolve the difference and repeat affected offline checks.
- [ ] Apply only the cumulative RF package, then port the reviewed native tests
  into the existing test fixtures. Retain their native CMake/GTest setup.
  Record each successful application immediately in
  `$E2_RF_EVIDENCE/applied-components.txt`; include later test/diagnostic changes
  and their exact patch paths. Use this ledger if deployment stops partway through.

```bash
record_check ocudu-apply-check git -C "$OCUDU_SOURCE" apply --check \
  "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch"
record_check flexric-apply-check git -C "$FLEXRIC_SOURCE" apply --check \
  "$FALCON_REPO/patches/flexric/73650812-du-rf-metrics.patch"

git -C "$OCUDU_SOURCE" apply "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch"
printf 'ocudu-rf %s\n' "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch" \
  >> "$E2_RF_EVIDENCE/applied-components.txt"
git -C "$FLEXRIC_SOURCE" apply "$FALCON_REPO/patches/flexric/73650812-du-rf-metrics.patch"
printf 'flexric-rf %s\n' "$FALCON_REPO/patches/flexric/73650812-du-rf-metrics.patch" \
  >> "$E2_RF_EVIDENCE/applied-components.txt"
```

After the native test edits, retain their separate diff as
`patches/ocudu/69801c7-du-rf-metrics-native-tests.patch`. Include every changed
test/CMake file and verify that reversing it restores the baseline test sources.
Record the completed native test changes and patch path in the application ledger.
Before the full build, implement the live correlation trace as a separate
`patches/ocudu/69801c7-du-rf-metrics-diagnostics.patch`:

- Capture a generation number when the DU provider accepts a scheduler window.
  Return each getter's generation and selected value as same-call optional
  trace metadata, using the safe snapshot access established in Step 3.
  Retain PCI, scheduler start slot, and window length where present in the source
  snapshot. Log the promoted source values with 17 significant digits.
  In `include/ocudu/e2/e2sm/e2sm_kpm.h`, add a default trace-aware interface path
  that delegates to the existing getter for providers without trace metadata.
  Override it in the DU provider header/source; do not use `dynamic_cast`
  because this build disables RTTI.
- In `e2sm_kpm_report_service_style4::collect_measurements()`, retain sidecar
  metadata for each actual UE/row/metric: local report counter, source window
  generation, selected value/type, and count.
- In `e2sm_kpm_report_service_base::get_indication_message()`, preserve that
  sidecar before collection is cleared. In `get_indication_header()`, attach
  the header actually packed and flush the trace only for successful packing.
  The current procedure packs the message first; its clear operation updates
  the header. A header logged before that operation identifies a different
  instant. Record the exact NTP word and its Unix-microsecond conversion using
  the same conversion as the repaired FlexRIC decoder.
- Keep instrumentation disabled by default, outside the ASN.1 payload, and
  narrow enough to avoid logging unrelated traffic. Test generation/row
  association, repeated windows, and message/header clear ordering. Retain its
  separate patch, including diagnostic test edits, hash, and application-ledger
  entry. Use and document the opt-in switch for both DU and monitor launches.

Then build and run the actual implementation:

```bash
record_check ocudu-build cmake --build "$OCUDU_SOURCE/build" \
  --target odu_split_8 e2sm_kpm_meas_provider_metrics_test \
           scheduler_metrics_handler_test crc_indication_builder_test -j 8

record_check native-provider env \
  FALCON_KPM_ACTION_INPUT="$E2_RF_EVIDENCE/flexric/flexric-action.bin" \
  "$OCUDU_SOURCE/build/tests/unittests/e2/e2sm_kpm_meas_provider_metrics_test" \
  --gtest_output="xml:$E2_RF_EVIDENCE/native/provider.xml"
record_check native-scheduler \
  "$OCUDU_SOURCE/build/tests/unittests/scheduler/scheduler_metrics_handler_test" \
  --gtest_output="xml:$E2_RF_EVIDENCE/native/scheduler.xml"
record_check native-crc \
  "$OCUDU_SOURCE/build/tests/unittests/fapi/p7/builders/crc_indication_builder_test" \
  --gtest_output="xml:$E2_RF_EVIDENCE/native/crc.xml"
record_check native-provider-xml-gate python3 "$E2_RF_EVIDENCE/check-gtest.py" \
  "$E2_RF_EVIDENCE/native/provider.xml" "$E2_RF_EVIDENCE" native-provider
record_check native-scheduler-xml-gate python3 "$E2_RF_EVIDENCE/check-gtest.py" \
  "$E2_RF_EVIDENCE/native/scheduler.xml" "$E2_RF_EVIDENCE" native-scheduler
record_check native-crc-xml-gate python3 "$E2_RF_EVIDENCE/check-gtest.py" \
  "$E2_RF_EVIDENCE/native/crc.xml" "$E2_RF_EVIDENCE" native-crc

record_check flexric-build cmake --build "$FLEXRIC_SOURCE/build-ocudu" \
  --target xapp_oran_moni test_enc_dec_kpm_sm test_kpm_sm -j 8
record_check flexric-codec \
  "$FLEXRIC_SOURCE/build-ocudu/test/encode_decode/sm/kpm/kpm_sm_v03.00/test_enc_dec_kpm_sm"
record_check flexric-service-model \
  "$FLEXRIC_SOURCE/build-ocudu/test/sm/kpm_sm/kpm_sm_v03.00/test_kpm_sm"

sha256sum "$OCUDU_SOURCE/build/apps/du_split_8/odu" \
  "$FLEXRIC_SOURCE/build-ocudu/examples/xApp/c/monitor/xapp_oran_moni" \
  > "$E2_RF_EVIDENCE/deployment-binaries.sha256"
```

Require the new native cases to execute, not merely the pre-existing tests.
Run additional native translator tests used for the adapter coverage
and retain their commands/results.

**Exit criteria:** complete targets and relevant native regressions pass against
the applied source, with no skipped required cases. The new scheduler snapshot
field is shared by producers and consumers: rebuilding only the provider object
or replacing one library is insufficient. Do not rerun the unchanged staging
script against the now-patched checkout; its refusal is intentional.

## Step 8 Validate Configuration and Fresh E2 Capabilities

```bash
record_check du-config "$OCUDU_SOURCE/build/apps/du_split_8/odu" \
  -c "$OCUDU_SOURCE/configs/du1_b210_n78_20mhz.yml" \
  -c "$OCUDU_SOURCE/configs/du1_flexric.yml" --dryrun
```

- [ ] Confirm scheduler/RLC metrics remain enabled and the source period is
  1000 ms. UE discovery for this Style 4 path depends on RLC snapshots.
- [ ] Confirm the xApp requests the seven intended names at 1000 ms and uses
  `/usr/local/lib/flexric/` with the existing timestamp-repaired KPM plugin.
- [ ] Start CU/core as required by the [runbook](../docs/full_reproduction_runbook.md),
  then RIC before DU. Use the rebuilt DU path and existing radio configuration.
  A RIC restart requires a DU restart for fresh E2 Setup.

In separate Spark terminals, use the existing operator launch sequence:

```bash
/usr/local/bin/flexric/ric/nearRT-RIC -c /usr/local/etc/flexric/ric.conf
```

```bash
sudo /home/nyu/ocudu/build/apps/du_split_8/odu \
  -c /home/nyu/ocudu/configs/du1_b210_n78_20mhz.yml \
  -c /home/nyu/ocudu/configs/du1_flexric.yml
```

```bash
/home/nyu/flexric/build-ocudu/examples/xApp/c/monitor/xapp_oran_moni \
  -c /home/nyu/Desktop/Falcon_repo/Falcon/configs/flexric/xapp_du_rf_metrics.conf
```

Verify the complete node/DU identity and advertised custom names, then a successful
function-ID-2 seven-metric subscription. Launch the rebuilt monitor directly,
rather than the older installed monitor. Use approved lab operating conditions
and the existing runbook; do not probe the B210 while DU owns it.

**Exit criteria:** configuration parsing passes, E2 Setup advertises both RF
metrics, and the intended subscription is accepted by the actual DU/RIC.
If this fails, resolve capability/version/admission issues before judging values.

## Step 9 Verify Correct Values During Live Uplink Traffic

- [ ] Establish the existing single-UE private IPv4 session using the
  [UE command booklet](../docs/ue_laptop_quick_commands.md).
- [ ] Run a controlled 30–60 second uplink test using the current private
  endpoints and [traffic procedure](../docs/full_reproduction_runbook.md).
  Record actual UE identity, direction, duration, application results, and RF errors.
- [ ] Capture narrow getter diagnostics and xApp RF output. Map the same UE between
  console C-RNTI, internal DU index, and UE F1AP ID. Enable the new opt-in trace
  for both processes and use one RF subscription per DU during this controlled run.
- [ ] Join the source sidecar and decoded trace by full node/DU identity,
  transmitted `header_time_us`, UE F1AP ID, row index, and metric name. Verify
  header keys are unique within each DU/process session; exclude ambiguous
  or duplicate matches. Carry the source snapshot generation into the comparison
  evidence, including repeated generations across reports.
- [ ] Obtain at least ten confidently correlated RF value pairs. Raw decoded
  `REAL` values parsed from the `%.17g` trace must equal the scheduler float
  promoted to double for each matched row. Check RSRP and SNR independently;
  record any difference in their source generations. Count a pair as a
  same-window pair only when both generations agree. Normal terminal output
  must match its documented two-decimal formatting.
- [ ] Confirm the original five metrics continue to report and the custom RSRP
  and SNR values are independently sourced, rather than copied from one field.
- [ ] Collect at least 30 consecutive populated reports during sustained traffic.
  Record arrival intervals, gaps, incomplete rows, and repeated source windows.
  Investigate unexplained gaps/crashes before accepting stable reception.

The DU console RSRP display rounds to one decimal, clamps negative values at
`-99.9`, and prints `ovl` for finite values at or above zero. The xApp exports the
finite scheduler value, including zero. Account for these presentation differences;
do not require literal console/xApp text equality. If the source window cannot
be matched confidently, record the comparison as inconclusive and improve the
narrow diagnostic correlation before claiming value accuracy.
Two-decimal logs alone establish display agreement; combine them with offline
codec evidence without claiming exact live `REAL` preservation. The exact live
gate remains incomplete until the full-precision, unambiguous comparison passes.

`header_time_us` is a KPM header time, not a PHY sample timestamp. `sample_idx`
is a row index, not a global sequence. `report_age_us` does not establish RF
sample age or pure transport latency. Record arrival cadence separately and
retain the 1000 ms source/subscription periods throughout initial acceptance.

**Exit criteria:** real UE values satisfy the source/identity/unit contract,
the correlation evidence supports accuracy, and sustained reception preserves
the baseline metrics without crashes or unexplained RF regression.

## Step 10 Verify Missing Data and Session Lifecycle

- [ ] Pause uplink traffic and disconnect/reconnect the UE using the established
  procedure. Check sample-count resets, newly allocated identifiers, and absence
  of stale measurements attributed to the new UE context.
- [ ] Where an active UE report has no valid RF sample, verify `noValue`/`n/a`.
  An inactive UE may cease to produce rows entirely; that alone is not an error
  and does not prove a missing-value record was emitted.
- [ ] Verify actual Ctrl+C and SIGTERM handling in separate xApp runs: the RIC
  receives subscription deletion, the SDK closes, and the process exits normally.
  An offline stop-flag test alone does not establish this behavior.
- [ ] Restart RIC followed by DU and the xApp; require fresh Setup, subscription,
  and correctly associated values. Do not assume automatic reconnection.
- [ ] Retain synthetic zero/missing/multi-UE tests as deterministic acceptance.
  If two live UEs or DUs are available, repeat association checks with distinct
  node/DU/UE identities; relaunch the xApp after a DU is added.

**Exit criteria:** no stale or cross-UE values, normal deletion/exit, and repeatable
restart. Report physical multi-UE/multi-DU coverage separately; a single-UE run
does not establish it. The current Style 4 S-NSSAI condition is not an enforced
slice filter, so this task does not validate slice isolation.

## Step 11 Review Deliverables and Close the Task

- [ ] Retain the reviewed RF patches, separate native test patch, validation
  runner base update, separate diagnostic patch, xApp configuration, and exact
  source/build identities. Keep diagnostic tracing disabled for normal operation.
- [ ] Hash the patches, scripts, tests, configuration, binaries, and fresh fixtures.
  Keep raw run artifacts outside source repositories; commit only selected
  sanitized evidence summaries and reviewed source artifacts.
- [ ] Update the [RF verification record](../docs/troubleshooting/2026-10-07_flexric_bringup.md#du-rf-metrics-extension-offline-package-2026-10-09)
  with current revisions, commands, results, estimator semantics, and remaining limits.
- [ ] Check that final commits separate the existing FlexRIC timestamp repair
  from RF work and contain no unrelated configuration changes or secrets.
- [ ] Have the reviewer verify the checklist against retained results and record
  completion or the specific incomplete gate in this plan.

| Acceptance gate | Required evidence |
| --- | --- |
| Measurement semantics | Correct source, unit, selected estimator, validity/count rules, and supported scope documented. |
| Offline integration | All required provider/cross-codec/action cases executed with zero failures/errors/skips. |
| Applied implementation | Full DU/xApp builds and native production-provider/scheduler/conversion checks pass. |
| E2 capabilities | Actual Setup and subscription contain the two custom RF names plus the baseline metrics. |
| Live values | At least ten matched source-window comparisons and 30 consecutive populated traffic reports. |
| Lifecycle | UE reconnect, RIC/DU restart, Ctrl+C/SIGTERM deletion, and normal process exit recorded. |
| Handoff | Reviewed patches/commits, sanitized evidence, exact launch paths, limits, and rollback retained. |

Close the initial DU1 implementation only when these gates pass. List physical
multi-UE/multi-DU acceptance as a follow-up when that hardware path is unavailable.

## Rollback

If deployment acceptance fails, stop traffic, let the xApp delete its subscription,
then stop DU before RIC. Consult the application ledger and reverse only changes
that were actually applied. Reverse diagnostic changes first, separate native
test changes next, and cumulative RF changes last. Check each reversal before
applying it. The following sequence assumes both RF patches and the native test
and diagnostic patches were applied; omit unapplied components, including a
patch that was never created. Record successful reversals in the ledger:

```bash
git -C "$OCUDU_SOURCE" apply --reverse --check \
  "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-diagnostics.patch"
git -C "$OCUDU_SOURCE" apply --reverse \
  "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-diagnostics.patch"
git -C "$OCUDU_SOURCE" apply --reverse --check \
  "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-native-tests.patch"
git -C "$OCUDU_SOURCE" apply --reverse \
  "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-native-tests.patch"
git -C "$OCUDU_SOURCE" apply --reverse --check \
  "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch"
git -C "$OCUDU_SOURCE" apply --reverse \
  "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch"
git -C "$FLEXRIC_SOURCE" apply --reverse --check \
  "$FALCON_REPO/patches/flexric/73650812-du-rf-metrics.patch"
git -C "$FLEXRIC_SOURCE" apply --reverse \
  "$FALCON_REPO/patches/flexric/73650812-du-rf-metrics.patch"

cmake --build "$OCUDU_SOURCE/build" --target odu_split_8 -j 8
cmake --build "$FLEXRIC_SOURCE/build-ocudu" --target xapp_oran_moni -j 8
```

Use the exact final reviewed patches if their filenames changed during review.
If a reversal check fails or later work depends on these changes, stop and resolve
the diff rather than forcing it. Preserve the `69801c7` configuration commit,
timestamp repair, and unrelated work. Restart RIC before DU and use the prior
five-metric monitor configuration from the runbook. Reverting the cumulative
package does not automatically apply the historical RSRP-only patches.

## Repository References

- [OCUDU cumulative RF patch](../patches/ocudu/050a2bb-du-rf-metrics.patch)
  and [FlexRIC cumulative RF patch](../patches/flexric/73650812-du-rf-metrics.patch).
- [OCUDU staging runner](../scripts/ocudu/test_du_rf_metrics.py)
  and [FlexRIC staging runner](../scripts/flexric/test_du_rf_metrics.py).
- [OCUDU regression cases](../tests/ocudu_du_rf_metrics_test.cpp)
  and [FlexRIC regression cases](../tests/flexric_du_rf_metrics_test.c).
- [Seven-metric configuration](../configs/flexric/xapp_du_rf_metrics.conf).
- [Existing RF package record](../docs/troubleshooting/2026-10-07_flexric_bringup.md#du-rf-metrics-extension-offline-package-2026-10-09).
- [Timestamp repair](../docs/troubleshooting/2026-10-07_flexric_latency_fix.md),
  [full runbook](../docs/full_reproduction_runbook.md), and
  [Spark command booklet](../docs/spark_quick_commands.md).
