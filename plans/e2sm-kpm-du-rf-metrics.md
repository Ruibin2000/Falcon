# E2SM-KPM DU RF Metrics Implementation Plan

The current seven-metric PUSCH RF baseline now targets 100 ms DU production
and reporting, with 1000 ms CU identity and 1-second Core polling. The operator's
October 25 request supersedes the earlier expansion-before-frequency order.
Expanded DL/UL coverage remains planned work: inventory measurements shown by
the DU `t` command and the remaining published DU metric families. Preserve
source semantics and complete UE/cell/DU attribution throughout the provider,
capability advertisement, codec and xApp.

| Field | Value |
| --- | --- |
| Plan | 1 |
| Task | `e2sm-kpm-du-rf-metrics` |
| Status | Current seven-metric 100 ms DU / 1 s CU stage complete and accepted by the operator on October 25; snapshot synchronization, the context-replacement PRB-index defect and expanded coverage remain follow-up work outside current acceptance |
| Created at | 13 : 23: 41 Oct 11, 2026 EDT |
| Last updated at | Oct 25, 2026 EDT |
| Time zone | `America/New_York` |
| Developer | To be assigned |
| Reviewer | Ruibin, project lead; decisions communicated by the developer |
| Falcon inspection baseline | `3f12f627d80cdad14bc9a5ab267f8f65452a2da9` |
| OCUDU inspection baseline | `69801c7e9a3a72e4f29d98f14f626f156444c3ca` |
| FlexRIC inspection baseline | `736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8`, with the existing local timestamp repair |
| Prerequisites | Plan 2 Stage A gate for Plan 1 Steps 7–11 waived by reviewer Ruibin on 2026-10-23; hardware slot confirmed by the developer; preserve the committed FlexRIC timestamp repair |
| Execution order | October 25 operator request advances the current seven-metric DU baseline directly to 100 ms. CU identity remains 1000 ms and Core polling 1 second. Expanded coverage and application forwarding retain separate acceptance. |
| Initial deployment | Existing OCUDU DU and FlexRIC RIC/xApp test environment |

Maintain this file as the single plan for this task. Mark steps complete only
after their exit criteria pass and their evidence has been retained.

## October 24 Metric Coverage and Frequency Decision

**October 25 update:** the operator subsequently requested a 100 ms period for
the current seven-metric dual-UE profile. That request supersedes the earlier
requirement to finish expanded coverage and 200 ms first. Both maintained and
deployed DU scheduler/RLC configs now use 100 ms, and only the default profile's
DU subscription changes to 100 ms. CU source/subscriptions remain 1000 ms,
Core polling 1 second, and the explicit legacy five-metric backup 1000 ms.
The operator explicitly retains the earlier snapshot-concurrency deferral.
Do not include provider locks, collection guards, E2 receive confinement or
cleanup relocation in this rate change. Native 100 ms APER, throughput
normalization, and mixed-rate IP mapping checks pass; no concurrent-snapshot
guarantee is claimed.
The [October 25 live report](../docs/reports/dual_ue_100ms_validation_report_2026-10-25.md)
verifies 1,179 reports per DU with receive-interval medians of 99.988 / 99.999 ms,
no reversed headers and no reported collector ingress loss. RF and PRB values
are available in every UL sample above 1 Mbit/s. The run keeps steady F1
contexts; it does not validate the separate PRB-index defect after replacement,
full radio health or source-snapshot synchronization. Source-generation
trace/header correlation remains unimplemented.
Use [the default Spark startup and 100 ms inspection commands](../docs/dual_ue_spark_quick_commands.md#7-start-the-dual-ue-identityrf-xapp-and-save-txt-results).

The operator requested more DL/UL measurements before any frequency increase.
This decision extends the original two-RF-metric scope and supersedes its
fixed seven-metric coverage limit. The earlier source reviews, passed tests
and outstanding RF live checks remain valid records of the narrower baseline.
Steps 1–11 retain that baseline; Steps 12–17 define the expanded completion
scope and order. No new implementation or timing result is implied by this revision.

| Phase | Required outcome | Period |
| --- | --- | --- |
| Inventory | Account for every DU console measurement and every published scheduler/RLC/MAC/PHY/RU metric field; record source, scope, validity and inclusion decision | 1000 ms baseline |
| Expand | Implement reviewed getters, capabilities, profiles and typed xApp handling; repair existing getter defects affecting the selected metrics | 1000 ms |
| Accept expanded coverage | Offline/native and real source-to-xApp validation of the declared metric set, identities and missing data | 1000 ms |
| Increase frequency | Verify the same accepted coverage and actual producer periods under controlled load | 200 ms first, then 100 ms |
| Application forwarding | Plan 2 preserves the expanded typed values and tests its bounded queues at each claimed rate | Separate gate; monitor reception does not establish forwarding |

The [coverage inventory and reporting contract](../docs/e2sm-kpm/2026-10-24_du_metric_expansion_and_reporting_periods.md)
defines the candidate families and source paths. "All DU metrics" means all
usable fields in published DU metric reports, with explicit disposition of
conditional/unavailable fields. It does not mean subscribing to every name
already registered without reviewing its implementation. Keep UE, cell and
DU/radio scopes separate; introduce bounded profile groups when necessary.

Maintain the 1000 ms source/subscription baseline while expanding coverage.
Do not change running periods as part of a getter patch. The original
1000 ms instructions in Steps 1–11 apply to baseline acceptance; faster
operation begins only in Steps 15–16. The previous concurrency deferral is
not evidence of synchronized snapshots and is not silently marked resolved.

## RF Baseline and Current Implementation State

At the original inspection baseline, KPM `get_rsrp` and `get_rsrq` both returned
an integer cast of the first UE snapshot's `pusch_snr_db`, without correct
measurement or UE mapping. The current OCUDU `E2SM-KPM` branch includes the
corrected RF implementation in `f8964521e8` and native tests in `b587084d0e`.
They are committed locally and remain unpushed at this revision. The 17-case
offline and 36-case native/build acceptance passed. Live seven-name
subscription passed, but the reviewed live snapshot had no RF value rows;
the advertised Setup names, RF numeric and lifecycle gates remain incomplete.

Falcon contains the cumulative RF/native patches, regressions, seven-metric
configuration and retained October 23 acceptance records. The FlexRIC RF
monitor was built outside its checkout; it is not yet integrated into the
new FlexRIC `E2SM-KPM` branch. Preserve the committed timestamp repair and
distinguish the staged executable from the unchanged shared monitor.

The original RF targets were identical across the reviewed unmodified bases.
Step 5 resolved runner compatibility before acceptance. Its staging-only
runner intentionally refuses already-patched targets; use applied-source
validation for the current branch rather than weakening those guards.

Keep the existing PHY estimator, RF configuration, PUSCH averaging algorithm,
timestamp repair and baseline profile semantics. The expanded scope now
includes DL/UL scheduler/RLC metrics, applicable cell and DU-health reports,
their required getter corrections, and later reporting-period evaluation.
Measured downlink UE RSRP/RSRQ/SINR, calibrated dBm and CU-owned telemetry
require real additional sources; do not fabricate them from the DU RF values.

## Measurement Contract

| Exported name | Source | Unit and representation | Missing data |
| --- | --- | --- | --- |
| `PUSCH.RSRP.dBFS` | Requested UE's scheduler-window `pusch_rsrp_db` | Software dBFS; KPM `REAL` | `noValue` if the UE/sample is unavailable or the value is non-finite |
| `PUSCH.SNR.dB` | Requested UE's scheduler-window `pusch_snr_db` | dB; KPM `REAL`; legacy SNR label for the selected PHY SINR estimate | `noValue` unless a finite value and at least one SNR sample exist |
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
UE-reported downlink RSRP. `PUSCH.SNR.dB` preserves the scheduler's legacy
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

**Reviewer decision, 2026-10-23:** project lead Ruibin waived the Plan 2 Stage A
prerequisite for Plan 1; the developer confirmed the hardware slot. This is a
waiver, not evidence that Plan 2 Stage A passed. The reviewer retained the
2026-10-21 concurrency deferral and removed DU diagnostics from this iteration:
no provider mutex, snapshot generation, cleanup relocation, `du.cpp`
E2-receive change, sidecar, or message/header/NTP correlation hooks. The earlier
Step 3 diagnostic proposal is not a Step 7 prerequisite. Unsynchronized
metrics-strand writes versus E2 reads remain a known limitation.

Only OCUDU receives checkout changes. FlexRIC remains read-only at `10b8ec79`,
including its existing `build-ocudu/` and `compile_commands.json`; its timestamp
repair is already committed. Use a newly staged monitor outside that checkout
with the existing installed timestamp-repaired KPM plugin. Do not install or
write under `/usr/local`.

- [ ] Have the operator stop test traffic, let the current xApp delete its
  subscription, and stop DU before RIC in their existing terminals. Keep the
  working CU/core configuration. The agent does not control services or RF.
- [x] Record `pgrep -a odu`, `pgrep -a nearRT-RIC`, and `pgrep -a xapp` before
  patch application and before each compiler/build invocation. If any process
  is running, stop and request approval before proceeding. Treat process-check
  errors separately from exit 1 meaning no match.
- [x] Recheck source revisions, checkout changes, frozen acceptance-gate hashes,
  and patch hashes against Step 6. The effective bases are OCUDU `4cffc0479f`
  and FlexRIC `10b8ec79`. If an input changed, resolve the difference and repeat
  affected offline checks; do not weaken the guards or refreeze requirements.
- [x] Apply the cumulative OCUDU RF patch and the separate reviewed native-test
  patch only. Retain the native fixtures and CMake/GTest setup. Record each
  successful application immediately, with its exact patch path and hash, in
  `$E2_RF_EVIDENCE/applied-components.txt`. Do not commit OCUDU without approval.

```bash
sha256sum -c "$E2_RF_EVIDENCE/acceptance-gate.sha256"
record_check ocudu-apply-check git -C "$OCUDU_SOURCE" apply --check \
  "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch"
record_check native-apply-check git -C "$OCUDU_SOURCE" apply --check \
  "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-native-tests.patch"

git -C "$OCUDU_SOURCE" apply "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch"
printf 'ocudu-rf %s\n' "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch" \
  >> "$E2_RF_EVIDENCE/applied-components.txt"
sha256sum "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch" \
  >> "$E2_RF_EVIDENCE/applied-components.txt"
record_check native-after-rf-apply-check git -C "$OCUDU_SOURCE" apply --check \
  "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-native-tests.patch"
git -C "$OCUDU_SOURCE" apply \
  "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-native-tests.patch"
printf 'ocudu-native-tests %s\n' \
  "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-native-tests.patch" \
  >> "$E2_RF_EVIDENCE/applied-components.txt"
sha256sum "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-native-tests.patch" \
  >> "$E2_RF_EVIDENCE/applied-components.txt"
```

Stop for explicit approval before the full DU build. After approval and the
process checks, build only the needed targets with `nice -n 19` and at most
`-j 4`. The frozen manifest also requires ten adapter cases; make the original
additional-translator requirement explicit rather than omitting that group.
Run all four native suites and their unchanged frozen XML gates:

```bash
record_check ocudu-build nice -n 19 cmake --build "$OCUDU_SOURCE/build" \
  --target odu_split_8 e2sm_kpm_meas_provider_metrics_test \
           scheduler_metrics_handler_test crc_indication_builder_test \
           fapi_to_mac_indications_fastpath_translator_test -j 4

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
record_check native-adapter \
  "$OCUDU_SOURCE/build/tests/unittests/fapi_adaptor/mac/p7/fapi_to_mac_indications_fastpath_translator_test" \
  --gtest_output="xml:$E2_RF_EVIDENCE/native/adapter.xml"
record_check native-provider-xml-gate python3 "$E2_RF_EVIDENCE/check-gtest.py" \
  "$E2_RF_EVIDENCE/native/provider.xml" "$E2_RF_EVIDENCE" native-provider
record_check native-scheduler-xml-gate python3 "$E2_RF_EVIDENCE/check-gtest.py" \
  "$E2_RF_EVIDENCE/native/scheduler.xml" "$E2_RF_EVIDENCE" native-scheduler
record_check native-crc-xml-gate python3 "$E2_RF_EVIDENCE/check-gtest.py" \
  "$E2_RF_EVIDENCE/native/crc.xml" "$E2_RF_EVIDENCE" native-crc
record_check native-adapter-xml-gate python3 "$E2_RF_EVIDENCE/check-gtest.py" \
  "$E2_RF_EVIDENCE/native/adapter.xml" "$E2_RF_EVIDENCE" native-adapter
sha256sum "$OCUDU_SOURCE/build/apps/du_split_8/odu" \
  > "$E2_RF_EVIDENCE/deployment-binaries.sha256"
```

Require all 36 frozen native names to execute without skips, failures, or
errors. If a patch, build, or test fails, retain its command/output and stop;
request approval before any rollback. Recheck the frozen gate after execution.

Build the patched monitor in a new `$E2_RF_EVIDENCE/monitor-live/` directory,
refusing to overwrite an existing output directory. Reconstruct its compile
and link commands from the same FlexRIC build records and Step 6
`flexric/build-inputs.json` / `flexric-stage.log` inputs. Preserve the staged
`examples/xApp/c/monitor/` hierarchy and read-only `src` include link used by
the runner. Copy the monitor source and apply the reviewed cumulative FlexRIC
RF patch only to that scratch copy. Record the staged application separately;
it is not an application to the FlexRIC checkout.

Use the existing GCC flags selecting `ASN`, `E2AP_V3`, `KPM_V3_00`, and
`NONE_XAPP`, with the recorded warning/hardening flags. Link the monitor with
the existing `defer.c.o`, `time_now_us.c.o`, `libe42_xapp.a`, and system
libraries `-pthread -lsctp -ldl -lconfig -lm`, as in Step 6. The monitor loads
KPM dynamically; do not add the harness-only static KPM link. Check processes
before each compile/link, use `nice -n 19`, and keep `TMPDIR`, objects, binary,
commands, logs, and status files inside the new evidence directory. Record the
source revision and source/patch/compiler/flags/reused-object/archive hashes,
then the new executable SHA-256. Preserve `SM_DIR=/usr/local/lib/flexric/` in
the runtime configuration and record the existing plugin's hash without
changing it. Record the absolute staged executable path for Steps 8–10.

Retain the existing FlexRIC codec and service-model checks without rebuilding
or writing to `build-ocudu`. Copy the two existing test executables into a new
evidence directory and verify each copy against its source. Run the copies
from that directory with an evidence-local `TMPDIR`, retaining commands,
outputs, exit statuses, and binary provenance. These in-memory tests do not
launch RIC/xApp services. Do not use `ctest`, which could write under the shared
build. Record these as checks of existing binaries, not a fresh FlexRIC build.

```bash
FLEXRIC_CHECKS="$E2_RF_EVIDENCE/flexric-existing-checks"
test ! -e "$FLEXRIC_CHECKS"
mkdir "$FLEXRIC_CHECKS"
mkdir "$FLEXRIC_CHECKS/tmp"
cp "$FLEXRIC_SOURCE/build-ocudu/test/encode_decode/sm/kpm/kpm_sm_v03.00/test_enc_dec_kpm_sm" \
  "$FLEXRIC_CHECKS/test_enc_dec_kpm_sm"
cp "$FLEXRIC_SOURCE/build-ocudu/test/sm/kpm_sm/kpm_sm_v03.00/test_kpm_sm" \
  "$FLEXRIC_CHECKS/test_kpm_sm"
cmp "$FLEXRIC_SOURCE/build-ocudu/test/encode_decode/sm/kpm/kpm_sm_v03.00/test_enc_dec_kpm_sm" \
  "$FLEXRIC_CHECKS/test_enc_dec_kpm_sm"
cmp "$FLEXRIC_SOURCE/build-ocudu/test/sm/kpm_sm/kpm_sm_v03.00/test_kpm_sm" \
  "$FLEXRIC_CHECKS/test_kpm_sm"
(
  cd "$FLEXRIC_CHECKS"
  ulimit -c 0
  export TMPDIR="$FLEXRIC_CHECKS/tmp"
  record_check flexric-codec "$FLEXRIC_CHECKS/test_enc_dec_kpm_sm"
  record_check flexric-service-model "$FLEXRIC_CHECKS/test_kpm_sm"
)
STAGED_MONITOR="$E2_RF_EVIDENCE/monitor-live/xapp_oran_moni"
sha256sum "$STAGED_MONITOR" /usr/local/lib/flexric/libkpm_sm.so \
  >> "$E2_RF_EVIDENCE/deployment-binaries.sha256"
```

**Exit criteria:** the full DU target, all required native cases, staged monitor
build, and existing FlexRIC codec/model checks pass with retained provenance.
The new scheduler snapshot field is shared by producers and consumers:
rebuilding only the provider object or replacing one library is insufficient.
The staged monitor replaces the original FlexRIC in-checkout monitor-build
requirement for this iteration. The FlexRIC checkout/build/plugin remain
unchanged. Do not rerun the staging runner against the now-patched OCUDU
checkout; its refusal is intentional.

Step 7 build acceptance passed on 2026-10-23: the full DU target, all 36
frozen native cases and four XML gates, the external staged monitor, and copied
existing FlexRIC codec/model checks passed. The three checked items above have
retained command/hash/source evidence. Initial and subsequent process checks
were idle; no operator stop/deletion event was recorded or inferred from that
absence, so the operator-stop checkbox remains unexecuted for this invocation.
OCUDU source changes remain uncommitted; FlexRIC source/build and the installed
plugin remain unchanged. The DU/native build emitted no warnings; the monitor
link retained the known executable-stack warning. Exact paths, binary hashes,
commands, results, limits, and operator commands are recorded in the
[Step 7 build and Step 8 handoff](../docs/e2sm-kpm/2026-10-23_du_rf_metrics_step7_build_and_step8_handoff.md).
Evidence: `/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step7-deploy-20261023-chi6rf4p/`
and its `build-native-20261023-rurw2gh0/` child, plus the run root's
`monitor-live/monitor-summary.json`.

## Step 8 Validate Configuration and Fresh E2 Capabilities

Use the deployed single-file DU1 configuration
`/home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml`; do not combine the older
20-MHz file and FlexRIC overlay. The reviewed file enables DU E2 and KPM at
`127.0.0.1:36421`, enables scheduler/RLC metrics, and sets `du_report_period`
to 1000 ms. Its carrier is ARFCN 644000 / 3660 MHz. Record its hash and stop if
those required settings are absent or changed; do not guess replacements.

Source inspection at OCUDU `4cffc0479f`, `apps/du/du.cpp:184–186`, shows
`--dryrun` returns after configuration parsing/autoderivation, before logging,
semantic validation, or radio/service creation. This is a parsing check only.
Run it without `sudo`; stop if it requests privileges or attempts RF access.
Do not turn it into a normal DU launch to make the check pass.

```bash
record_check du-config "$OCUDU_SOURCE/build/apps/du_split_8/odu" \
  -c "$OCUDU_SOURCE/configs/du1_b210_n78_3660mhz.yml" --dryrun
```

The rebuilt DU passed this parsing-only check on 2026-10-23 without sudo or
radio/service creation. Evidence:
`/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step7-deploy-20261023-chi6rf4p/step8-prep-20261023-n1187csn/dryrun-summary.json`.
Operator logs were reviewed on 2026-10-23. The three operational/configuration
items below are now verified: core/CU/DU startup, the actual 3660-MHz carrier,
1000-ms scheduler/RLC settings, the configured plugin path, and admission of all
seven exact names with `NO_LABEL`, followed by xApp subscription success.
Step 8 remains **Partial** until the actual Setup definition's advertised RF
names are captured and decoded. The xApp snapshot contains zero RF trace rows;
the operator confirmed that the UE is not attached or lacks an established
data session. The DU snapshot has 52 complete underflow and 18 complete late
warnings; this is not a stability pass or a causal diagnosis. See the
[operator log review](../docs/e2sm-kpm/2026-10-23_du_rf_metrics_step8_operator_log_review.md).
Evidence: `/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step8-live-review-20261023-ltlwu4i6/`.
No service control, packet capture, build, radio action or traffic generation
was performed by the agent during the review.

- [x] Confirm scheduler/RLC metrics remain enabled and the source period is
  1000 ms. UE discovery for this Style 4 path depends on RLC snapshots.
- [x] Confirm the xApp requests the seven intended names at 1000 ms and uses
  `/usr/local/lib/flexric/` with the existing timestamp-repaired KPM plugin.
- [x] Give the operator the exact launch commands and evidence paths. The
  operator starts CU/core as required by the
  [runbook](../docs/runbooks/full_reproduction_runbook.md), then RIC before DU, then the
  staged monitor. A RIC restart requires a DU restart for fresh E2 Setup.
  The agent does not run `sudo`, start/stop services, touch the B210, or generate
  traffic. Retain operator logs before judging the live gates.
- [ ] Retain and decode the actual E2 Setup function-ID-2 definition, showing
  both vendor RF names in the advertised measurement list. The admitted-name
  subscription log does not complete this separate exit criterion.

The following are operator-only commands for separate Spark terminals, after
CU/core preparation. Set `E2_RF_EVIDENCE` in every terminal to the retained
absolute run directory, `/home/nyu/verification/e2sm-kpm/run-TQcKveEB`, and
create its `live/` directory. Use the recorded staged monitor path and hash.
Retain the exact launch commands. Each pipeline below creates a fresh log and
immediately records both process and log exit statuses after it returns. If a
terminal interruption prevents that capture, record the status as **Not recorded**
instead of inferring success. Wait for operator logs before marking any live
checkbox complete.

```bash
set -o pipefail
FALCON_RIC_LOG=$(mktemp "$E2_RF_EVIDENCE/live/ric-XXXXXXXX.log") || exit
set +e
/usr/local/bin/flexric/ric/nearRT-RIC -c /usr/local/etc/flexric/ric.conf \
  2>&1 | tee "$FALCON_RIC_LOG"
FALCON_RIC_STATUS=("${PIPESTATUS[@]}")
printf 'command_exit=%s\nlog_exit=%s\n' "${FALCON_RIC_STATUS[0]}" "${FALCON_RIC_STATUS[1]}" \
  > "$FALCON_RIC_LOG.status"
```

```bash
set -o pipefail
FALCON_DU_LOG=$(mktemp "$E2_RF_EVIDENCE/live/du-console-XXXXXXXX.log") || exit
set +e
sudo /home/nyu/ocudu/build/apps/du_split_8/odu \
  -c /home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml \
  2>&1 | tee "$FALCON_DU_LOG"
FALCON_DU_STATUS=("${PIPESTATUS[@]}")
printf 'command_exit=%s\nlog_exit=%s\n' "${FALCON_DU_STATUS[0]}" "${FALCON_DU_STATUS[1]}" \
  > "$FALCON_DU_LOG.status"
```

```bash
set -o pipefail
FALCON_XAPP_LOG=$(mktemp "$E2_RF_EVIDENCE/live/xapp-XXXXXXXX.log") || exit
set +e
FALCON_KPM_RF_TRACE=1 "$E2_RF_EVIDENCE/monitor-live/xapp_oran_moni" \
  -c /home/nyu/Desktop/Falcon_repo/Falcon/configs/flexric/xapp_du_rf_metrics.conf \
  2>&1 | tee "$FALCON_XAPP_LOG"
FALCON_XAPP_STATUS=("${PIPESTATUS[@]}")
printf 'command_exit=%s\nlog_exit=%s\n' "${FALCON_XAPP_STATUS[0]}" "${FALCON_XAPP_STATUS[1]}" \
  > "$FALCON_XAPP_LOG.status"
```

The DU configuration also writes its existing application log to
`/tmp/du1_3660.log`. Retain the relevant session separately under `live/`,
with its source path, timestamps, and hash; console capture is not that file.
Verify the complete node/DU identity and advertised custom names, then a
successful function-ID-2 seven-metric subscription. Use the staged monitor,
its configuration, and the existing plugin; the checkout and installed
monitor executables remain unchanged. Use approved lab operating conditions
and the existing runbook; do not probe the B210 while DU owns it.

**Exit criteria:** configuration parsing passes, E2 Setup advertises both RF
metrics, and the intended subscription is accepted by the actual DU/RIC.
If this fails, resolve capability/version/admission issues before judging values.

## Step 9 Verify Correct Values During Live Uplink Traffic

**Reviewer decision, 2026-10-23:** use existing DU per-UE RF metrics output and
the staged monitor's `FALCON_KPM_RF_TRACE=1` output. Match by UE and nearest
report time. This is a weaker, non-generation-matched comparison; no DU
instrumentation, sidecar, header/NTP join, or same-window proof is required.
The developer explicitly retained the two-decimal comparison requirement:
identify an existing higher-precision DU output first; otherwise this value
check does not pass. Do not relax it to one decimal or enable/add an output
without further approval.

- [ ] Have the operator establish the existing single-UE private IPv4 session
  using the [UE command booklet](../docs/single_ue/ue_laptop_quick_commands.md).
- [ ] Have the operator run a controlled 30–60 second uplink test using the
  current private endpoints and
  [traffic procedure](../docs/runbooks/full_reproduction_runbook.md). Record actual UE
  identity, direction, duration, application results, and RF errors.
- [ ] Identify and retain existing DU output containing both per-UE
  scheduler-window RSRP/SNR with at least two decimal places or sufficient raw
  numeric precision. Record its source, units, precision, timestamps, and
  validity/presentation rules. An available output implementation is not proof
  that output was enabled or captured. Individual PHY/CRC samples do not
  substitute for the scheduler-window means.
- [ ] Capture that existing DU output and the staged xApp RF output. Map the same
  UE between console C-RNTI, internal DU index, and UE F1AP ID; retain full
  node/DU/session identity. Use one RF subscription per DU during the controlled
  run. Keep xApp `FALCON_KPM_RF_TRACE=1`; there is no new DU trace switch.
- [ ] Select the nearest DU report time for each xApp report of the same UE.
  Document the time basis, chosen timestamps and their difference, matching
  tolerance, and exclusions before judging agreement. Exclude ambiguous UE,
  session, or timing matches. Retain raw source lines and decoded trace rows.
  Header time may aid approximate ordering; it is not a source-window key.
- [ ] Obtain at least ten usable per-UE RSRP/SNR comparison pairs. Compare each
  metric independently at two-decimal display precision, retain the xApp
  `%.17g` decoded trace as supplementary evidence, and account for documented
  rounding/clamping. Do not count `ovl`, `n/a`, saturated displays, or
  insufficient-precision DU values as successful two-decimal numeric matches.
- [ ] Confirm the original five metrics continue to report and the custom RSRP
  and SNR values are independently sourced, rather than copied from one field.
- [ ] Collect at least 30 consecutive populated reports during sustained traffic.
  Record arrival intervals, gaps, incomplete rows, and repeated displayed
  values. Without generation metadata, repeated values do not establish
  repeated source windows. Investigate unexplained gaps/crashes before
  accepting stable reception.

At OCUDU `4cffc0479f`, the existing console and scheduler log format both RF
values to one decimal (`apps/units/flexible_o_du/o_du_high/du_high/metrics/consumers/scheduler_metrics_consumers.cpp:89–99,314–325`).
SNR is clamped to `[-99.9, 99.9]` and zero renders as `n/a`; negative RSRP is
clamped at `-99.9`, and finite RSRP at or above zero renders as `ovl`.
The xApp exports finite scheduler values, including valid zero, with two-decimal
normal output and full-precision optional decoded trace. These existing DU
console/log lines alone cannot pass the two-decimal value check. Do not pad a
one-decimal value with zero or infer precision from a filename or a consumer
that was not active. The existing scheduler JSON generator serializes float
window means without a fixed one-decimal format
(`apps/helpers/metrics/json_generators/du_high/scheduler.cpp:38–60,146–148`),
but the deployed configuration does not enable JSON metrics or the remote
metrics subscription. Those options default to false. The JSON consumer also
omits zero and clamps values, so its existence alone does not establish
validity or adequate live evidence. The read-only review of eleven existing
`/tmp/falcon-du1-3660.*/du.log` files found no scheduler-window RF fields or JSON
RF rows; a qualifying active high-precision DU output has not been found.
If no qualifying existing DU output is available, retain that limitation and
leave the Step 9 value gate incomplete. Any proposal to enable an existing
consumer requires a separate decision before implementation.

Even a successful two-decimal nearest-time comparison establishes display
agreement only. Combine it with offline codec evidence without claiming exact
live `REAL` preservation, same-source-window pairs, or synchronized snapshots.
Unsynchronized metrics/E2 access remains a known limitation.
`header_time_us` is a KPM header time, not a PHY sample timestamp. `sample_idx`
is a row index, not a global sequence. `report_age_us` does not establish RF
sample age or pure transport latency. Record arrival cadence separately and
retain the 1000 ms source/subscription periods throughout initial acceptance.

**Exit criteria:** real UE values satisfy the source/identity/unit contract,
at least ten two-decimal comparisons pass under the explicitly weaker
non-generation-matched method, and sustained reception preserves the baseline
metrics without crashes or unexplained RF regression. Missing precision or
ambiguous correlation leaves the value gate incomplete.

## Step 10 Verify Missing Data and Session Lifecycle

- [ ] Have the operator pause uplink traffic and disconnect/reconnect the UE
  using the established procedure. Retain native/offline sample-count reset
  coverage and check observable missing-value behavior, newly allocated
  identifiers, and absence of stale measurements attributed to the new UE
  context. Do not claim direct observation of live sample counters without an
  existing output that actually contains them.
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
  runner base update, xApp configuration, staged-monitor build command and
  source/patch/binary hashes, existing plugin identity, and exact source/build
  identities. No DU diagnostics patch is a deliverable. Keep the existing
  xApp RF trace disabled for normal operation.
- [ ] Hash the patches, scripts, tests, configuration, binaries, and fresh fixtures.
  Keep raw run artifacts outside source repositories; commit only selected
  sanitized evidence summaries and reviewed source artifacts.
- [ ] Create a new dated RF verification/handoff document under `docs/e2sm-kpm/`
  with current revisions, commands, results, estimator semantics, and remaining
  limits. Link the historical
  [RF verification record](../docs/troubleshooting/2026-10-07_flexric_bringup.md#du-rf-metrics-extension-offline-package-2026-10-09)
  as context; preserve that existing document under the root repository rules.
- [ ] Check that final commits separate the existing FlexRIC timestamp repair
  from RF work and contain no unrelated configuration changes or secrets.
- [ ] Have the reviewer verify the checklist against retained results and record
  completion or the specific incomplete gate in this plan.

| Acceptance gate | Required evidence |
| --- | --- |
| Measurement semantics | Correct source, unit, selected estimator, validity/count rules, and supported scope documented. |
| Offline integration | All required provider/cross-codec/action cases executed with zero failures/errors/skips. |
| Applied implementation | Full DU build, external staged-monitor build, all 36 required native provider/scheduler/conversion cases, and existing FlexRIC codec/model checks pass; shared FlexRIC remains read-only. |
| E2 capabilities | Actual Setup and subscription contain the two custom RF names plus the baseline metrics. |
| Live values | At least ten same-UE nearest-report-time comparisons at two-decimal precision using qualifying existing DU output, plus the xApp RF trace and 30 consecutive populated traffic reports; explicitly weaker and non-generation-matched. If no sufficiently precise existing DU output is captured, this gate remains incomplete. |
| Lifecycle | UE reconnect, RIC/DU restart, Ctrl+C/SIGTERM deletion, and normal process exit recorded. |
| Handoff | Reviewed patches/commits, sanitized evidence, exact launch paths, limits, and rollback retained. |

These gates close the original RF baseline, not the expanded October 24 scope.
List physical multi-UE/multi-DU acceptance as a follow-up when that hardware
path is unavailable, without changing the separate Dual-UE functional acceptance.

## Step 12 Freeze the Expanded DU Metric Registry

- [ ] Inventory all measurements in the DU console and all fields in published
  scheduler, RLC, MAC, PHY and RU reports using the linked coverage inventory.
  Record included, derived, conditional or unavailable status for every field.
- [ ] For every selected metric, freeze source/producer, name, unit, wire type,
  UE/cell/DU scope, window/reset/last-value behavior, validity and source period.
  Keep PCI/C-RNTI context distinct from the complete F1AP UE identity.
- [ ] Include the existing seven metrics as a regression profile. Define explicit
  expanded UE and separate cell/DU-health profiles, without inventing standard
  KPM names or treating a registered name as a verified getter.
- [ ] Audit CQI, PRB, throughput, volume, loss and delay getters. Account for
  sparse/reordered UE indices, bearer aggregation, units, integer truncation,
  missing samples and zero denominators before advertising expanded support.

**Exit criteria:** every published field has a disposition and every included
measurement has a reviewable source contract; unavailable data has no fake value.

## Step 13 Implement Expanded Coverage at 1000 ms

- [ ] Implement typed snapshot/getter paths for all included console metrics:
  CQI, DL/UL RI and MCS, MAC bitrate, OK/NOK counts, derived error percentages,
  DL buffer, PUSCH RSRP/SNR, BSR, sourced TA statistics and PHR.
- [ ] Add the remaining included scheduler/RLC metrics and separate cell-level
  reports. Integrate available MAC/PHY/RU health producers explicitly; preserve
  their actual producer cadence and optional availability.
- [ ] Preserve valid zero, negative/fractional REAL values, counters and optional
  absence. Add validity/sample information when an existing zero/default cannot
  distinguish absence. Do not apply period-mean semantics to last-known values.
- [ ] Add capability/admission and xApp decoding/output for each declared profile.
  Use typed measurements, not parsed terminal strings. Review ownership across
  producer and E2 executors and retain any deferred consistency limitation.
- [ ] Keep producers, KPM reporting and granularity at 1000 ms for this phase.
  Retain source/patch/binary identities and the seven-metric regression profile.

**Exit criteria:** implemented sources, actual advertised/admitted names and
decoded fields agree with the registry; no unsupported metric is silently omitted.

## Step 14 Accept Expanded Metrics Before Changing Frequency

- [ ] Retain all existing offline/native/runner regressions and add tests for
  every new getter, derived quantity, scope, validity rule and advertised name.
  Cover sparse UE indices, two DUs sharing UE numbers, empty windows, counter
  resets, signed/fractional/zero values and malformed requests.
- [ ] Verify complete APER encode/decode and xApp preservation for expanded UE
  and cell/health profiles. Check complete encoded E2AP PDU sizes against the
  current 9100-byte sender limit and partition into declared bounded groups
  if needed, without losing metric coverage.
- [ ] At 1000 ms, retain actual Setup capabilities, subscription admission and
  populated DL/UL traffic results for the included profiles. Compare source
  values to xApp values with the registry's units and precision; keep the
  unresolved original RF comparison gate explicit until it passes.
- [ ] Verify absent data and normal subscription cleanup/restart. Keep physical
  coverage explicit. Source scope and identity tests do not reopen the accepted
  Dual-UE feature's separate supplemental experiment requirements.
- [ ] Preserve a named accepted 1000 ms metric list and baseline measurements
  before rate tests. Record broker receipt validation separately under Plan 2;
  monitor output alone does not prove application forwarding.

**Exit criteria:** expanded source correctness, live delivery and lifecycle at
1000 ms pass for the declared coverage before any acceleration test begins.

## Step 15 Evaluate 200 ms Reporting

- [ ] Set DU statistics and KPM reporting/granularity to 200 ms together in new
  candidate configurations. Update independent producers explicitly or retain
  them in declared slower profiles; do not relabel repeated 1000 ms data.
- [ ] Freeze the test duration, warm-up, metric list, traffic, identity checks
  and tolerances for cadence, gaps and processing/queue delay before the run.
- [ ] Measure full PDU sizes, arrival intervals, processing time, CPU use,
  queue growth/drops and radio late/underflow/overflow changes relative to the
  comparable 1000 ms run. Bound trace output and avoid slow callback I/O.
- [ ] Verify missing-data and lifecycle behavior with the expanded coverage.
  Preserve known snapshot-consistency limits; identical values alone do not
  establish replay, and header time is not a PHY/window correlation key.
- [ ] If forwarding is implemented, run Plan 2's matching client equality,
  slow-client and queue tests. Otherwise label this monitor-path acceptance
  only, with forwarding pending.

**Exit criteria:** the declared 200 ms path passes the frozen correctness and
load checks without sustained queue growth or unexplained loss. A parse-only
check or a bandwidth estimate does not establish this result.

## Step 16 Evaluate 100 ms Reporting After 200 ms

- [ ] Preserve the accepted 200 ms configurations and evidence before changing
  both applicable producer and subscription periods to 100 ms.
- [ ] Repeat Step 15 with the same expanded metric coverage and declared slower
  producers, measuring the actual higher report rate rather than assuming it.
- [ ] Test low-traffic/no-sample windows as well as sustained DL/UL traffic.
  Separate expected noValue from delayed, dropped or stale reports.
- [ ] Record monitor and application-forwarding results independently. If the
  100 ms checks fail, keep 200 ms as the supported profile and retain the reason;
  do not silently reduce metric coverage or weaken checks to claim 100 ms.

**Exit criteria:** 100 ms is supported only for the explicitly tested coverage,
workload and delivery path; it is not a hard end-to-end latency guarantee.

## Step 17 Close the Expanded Scope

- [ ] Retain the metric registry, source mappings, reviewed code/patches, profile
  versions, configurations, regression results and complete source/binary IDs.
- [ ] Record expanded 1000 ms, 200 ms, 100 ms and broker forwarding as separate
  completion items, with conditional/unavailable source fields disclosed.
- [ ] Preserve the original RF evidence and the 1000 ms fallback. Record exact
  supported rates, report size limits, queue behavior, scope and remaining limits.

The expanded task closes only when its declared metric coverage and claimed
rates have passed; the earlier RF-only completion table is not sufficient.

## Rollback

Stop on any deployment failure and request approval before rollback. The
operator stops traffic, lets the xApp delete its subscription, and stops DU
before RIC; the agent does not control services or RF. Consult the application
ledger and reverse only OCUDU changes that were actually applied: separate
native-test changes first, cumulative RF changes last. Check each reversal
before applying it. There is no DU diagnostics patch to reverse, and no patch
was applied to the read-only FlexRIC checkout. The following assumes both
OCUDU patches were applied; omit unapplied components and record successful
reversals in the ledger:

```bash
git -C "$OCUDU_SOURCE" apply --reverse --check \
  "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-native-tests.patch"
git -C "$OCUDU_SOURCE" apply --reverse \
  "$FALCON_REPO/patches/ocudu/69801c7-du-rf-metrics-native-tests.patch"
git -C "$OCUDU_SOURCE" apply --reverse --check \
  "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch"
git -C "$OCUDU_SOURCE" apply --reverse \
  "$FALCON_REPO/patches/ocudu/050a2bb-du-rf-metrics.patch"
```

After the process checks and explicit full-build approval:

```bash
record_check ocudu-rollback-build nice -n 19 cmake --build "$OCUDU_SOURCE/build" \
  --target odu_split_8 -j 4
```

Use the exact final reviewed patches if their filenames changed during review.
If a reversal check fails or later work depends on these changes, stop and
resolve the diff rather than forcing it. Preserve the effective OCUDU
`4cffc0479f` baseline, including the 3660-MHz configuration and `AGENTS.md`,
FlexRIC's committed timestamp repair, and unrelated work. Retain staged
monitor artifacts as evidence; monitor rollback selects the prior unchanged
monitor binary and five-metric configuration from the runbook. Do not reverse
patches or rebuild/install inside FlexRIC or change the installed plugin.
Have the operator restart RIC before DU using the recorded prior binaries and
configuration. Reverting the cumulative package does not automatically apply
the historical RSRP-only patches.

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
  [full runbook](../docs/runbooks/full_reproduction_runbook.md), and
  [Spark command booklet](../docs/single_ue/spark_quick_commands.md).
