# DU RF Metrics Validation Harness — October 21, 2026

This document records Plan 1 Step 5 on Falcon branch `E2SM-KPM`, starting at
`c5e02f634bcde5e6992bec5ba5b54e1076d17440`. It supplements the existing
[plan](../../plans/e2sm-kpm-du-rf-metrics.md),
[OCUDU contract review](2026-10-21_du_rf_metrics_contract_review.md), and
[FlexRIC monitor review](2026-10-21_flexric_du_rf_monitor_review.md).
Existing explanatory documents, plan checkboxes, and development logs are
unchanged in this step. The statuses below distinguish test design and runner
validation from execution of the RF acceptance tests.

## Scope and baseline decisions

Only Falcon contains repository edits. OCUDU remains on `E2SM-KPM` at
`4cffc0479f9620f668a7ac79aeb314b2e31525e4`; its five RF production targets
remain unmodified in the index and working tree. FlexRIC remains read-only on
`falcon-xapp` at `10b8ec79d0f011902d329b2ed37f33f8b101b591`. No branch,
worktree, deployment build directory, installation, service, traffic, radio,
or push operation is part of this work.

The user approved these runner proposals before implementation:

- OCUDU explicitly accepts full revisions
  `050a2bb72e1d794cd60570d809987c1fcda3e54b`,
  `69801c7e9a3a72e4f29d98f14f626f156444c3ca`, and
  `4cffc0479f9620f668a7ac79aeb314b2e31525e4`.
  Before changing the revision guard, all five production targets were compared
  across those revisions. Each target has the same Git blob at all three bases.
  The allowlist does not accept arbitrary descendants.
- FlexRIC explicitly accepts only
  `10b8ec79d0f011902d329b2ed37f33f8b101b591`. The timestamp repair is committed
  at that baseline. All six repair inputs must be clean and byte-identical to
  that commit; neither the repair nor the historical RSRP-only patch is applied
  by the RF runner. The old `73650812` baseline is deliberately not accepted.

The OCUDU effective baseline differs from `69801c7` by the 3660-MHz DU1
configuration and `AGENTS.md`, as recorded in Step 1. Supporting that baseline
does not resolve the later deployment-configuration discrepancy.

## Affected Falcon paths

| Path | Purpose |
| --- | --- |
| `scripts/ocudu/test_du_rf_metrics.py` | Explicit reviewed revisions, exact five-file/blob guards, read-only preflight mode, output protection, and sequential nice-19 compile/link commands. |
| `scripts/flexric/test_du_rf_metrics.py` | Committed timestamp baseline, read-only preflight mode, output/input guards, nice-19 compile/link commands, complete decoded fixture checks, and named action XML validation. |
| `tests/test_du_rf_runner_guards.py` | Python rejection-path tests using temporary ordinary files and mocks; no Git mutation, compiler, or service invocation. |
| `tests/ocudu_du_rf_metrics_test.cpp` | Retained all 13 original standalone cases and added four required coverage cases. |
| `patches/ocudu/69801c7-du-rf-metrics-native-tests.patch` | Separate native provider/scheduler/CRC/adapter regressions; applied only to scratch during Step 5. |
| `tests/e2sm_kpm_du_rf_required_tests.json` | Exact mandatory GTest names, retained in evidence and frozen before Step 6. |
| `docs/e2sm-kpm/2026-10-21_du_rf_metrics_validation_harness.md` | This implementation, validation, and acceptance handoff. |

The reviewed five-file OCUDU RF patch and one-file FlexRIC RF patch are unchanged.
Native test changes are never mixed into the production RF patch.

## Runner safeguards and usage

Both runners reject unknown revisions, dirty RF inputs, patches outside their
reviewed target sets, failed applicability checks, and output paths overlapping
source/build/repository/install directories. They reject symlink components
and nonempty output directories instead of deleting or reusing artifacts.
The OCUDU runner additionally checks the index and the five expected Git blob
IDs, including an index-only modification whose working bytes match HEAD.
Its existing build must identify the supplied source in `CMakeCache.txt`.
FlexRIC validates both staged and working timestamp inputs, including
`kpm_timestamp.h`, rather than accepting a timestamp substring.

Read-only guard checks use explicit paths:

```bash
python3 -B scripts/ocudu/test_du_rf_metrics.py \
  --ocudu-source /home/nyu/ocudu --ocudu-build /home/nyu/ocudu/build \
  --output-dir /tmp/falcon-step5-ocudu-check-only-final-vhst0vi4 --check-only
python3 -B scripts/flexric/test_du_rf_metrics.py \
  --flexric-source /home/nyu/flexric --flexric-build /home/nyu/flexric/build-ocudu \
  --output-dir /tmp/falcon-step5-flexric-check-only-final-vhst0vi4 --check-only
```

`--check-only` returns before creating output or staging files. FlexRIC does
not require the future indication fixture/provider executable in this mode;
normal execution still requires them. Normal execution checks `pgrep -a odu`,
`pgrep -a nearRT-RIC`, and `pgrep -a xapp` before each compiler/link invocation,
stops if a process is found or the check fails, and uses `nice -n 19` with
sequential commands. Compiler `TMPDIR` is inside the selected output directory.

Existing compiler flags and library inputs are retained. The FlexRIC monitor
is linked but never executed by the runner. The callback harness links the
KPM ASN runtime before the SDK's E2AP runtime inside the existing linker group.
`build-inputs.json` identifies recipes, source/test/patch inputs, and reused
compiler/object/archive hashes. Those hashes identify inputs; they do not
prove a fresh deployment build.

FlexRIC requires all six harness PASS markers and six complete fixture trace
rows, preserving UE identity, header time, metric, units, record type, and
exact value. UE `1007` must have `-13.125`/`21.75`, UE `2091` measured zero for
both metrics, and UE `3199` two `noValue` records. Human-readable diagnostics
and local RSRQ status remain required. The external seven-metric action test
must appear exactly once under its expected name in XML and execute without
failure/error/skip. Successful full execution produces `offline-results.json`;
no such full-run result is claimed in Step 5.

## Test design and mandatory coverage

The original fixture in `baseline/provider-tests.cpp` contains exactly 13
unique cases, SHA-256
`61bce3024c77103af0f9b0e1ef365c38540abdc39ad54520b1761819778bde77`.
Their names and function bodies are retained. The four new standalone cases
cover:

1. Decoding the production `pack_ran_function_description()`: both vendor names
   at UE styles only, no dummy RSRP/RSRQ, and the original five metrics retained.
2. Real Style 3 action admission for both RF names: one true unexpanded
   `NO_LABEL`, with or without supported UE-selection conditions; rejection of
   test-only, absent/duplicate/mixed/expanded labels and cell scope.
3. Removing a translator mapping while keeping an old scheduler snapshot:
   no stale value reuse, preserved request order/cardinality, and two `noValue`
   positions for the removed UE.
4. Failed-CRC RF samples: independent RF means/counts, missing optional data,
   valid measured zero, and reset to a missing next window.

ASN.1 `noLabel` has no FALSE enumerator. A present but unset `nulltype` value
and an empty matching list cannot be encoded as valid actions; those two
defensive cases use an explicitly decoded handler. Other Style 3 cases use
actual APER encoding and public action admission.

The separate native patch adds 14 cases across four test executables:

| Manifest group | Native target | Required cases including retained cases |
| --- | --- | --- |
| `offline-provider` | Staged `ocudu_du_rf_metrics_test` | 17 (13 original + 4 new). |
| `native-provider` | `e2sm_kpm_meas_provider_metrics_test` | 11 (6 retained + 5 new). |
| `native-scheduler` | `scheduler_metrics_handler_test` | 11 (8 retained + 3 new). |
| `native-crc` | `crc_indication_builder_test` | 4 (2 retained + 2 new). |
| `native-adapter` | `fapi_to_mac_indications_fastpath_translator_test` | 10 (6 retained, including 5 parameter instances, + 4 new). |

The adapter tests call both production translators, capture wire and MAC
results, and assert literal expected sentinels, valid zero, 0.1-dB RSRP and
0.002-dB SINR quantization, and positive/negative saturation. The test does not
copy the production clamp. Its test-only CMake change adds the PHY translator
include path and library to the existing MAC adapter test target.

Static boundary observation: the PHY clamp uses float endpoints `+/-65.534`
(`lib/fapi_adaptor/phy/p7/phy_to_fapi_results_event_fastpath_translator.cpp:239`).
The builder multiplies by `500.F` and truncates to `int16_t`
(`include/ocudu/fapi/p7/builders/crc_indication_builder.h:66`); the MAC translator
multiplies by `0.002F`
(`lib/fapi_adaptor/mac/p7/fapi_to_mac_indications_fastpath_translator.cpp:55`).
IEEE float arithmetic predicts saturated wire values `+/-32766` and decoded
`+/-65.532` dB. These are native test expectations, not executed native results.

The snapshot-concurrency/generation matrix row remains **Deferred by reviewer
decision 2026-10-21**, as explained in the existing
[design decision](2026-10-19_du_rf_metrics_patch_review_and_snapshot_design.md#decision).
No mutex, generation, cleanup relocation, `du.cpp` prerequisite, source-window
correlation, or concurrency pass is introduced.

## Validation and frozen acceptance handoff

Evidence directory:
`/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step5-harness-20261021-vhst0vi4/`.

| Validation | Command or retained record | Result |
| --- | --- | --- |
| Three-revision/five-target comparison, captured before changing the revision guard | `baseline-target-blobs.json` and `blob-*.command.txt` | Passed: five identical blobs across all three full revisions. |
| Runner rejection and acceptance paths | `python3 -B tests/test_du_rf_runner_guards.py -v`; `python-runner-guards.{command,stdout,stderr,status}.*` | Passed: 35 Python tests, zero skips/failures/errors. Subprocess/compiler behavior is mocked; no RF acceptance executable is run. |
| Actual OCUDU baseline/build preflight | `ocudu-read-only-preflight.command.txt` | Passed, exit 0; output directory not created. |
| Actual FlexRIC baseline/timestamp/build preflight | `flexric-read-only-preflight.command.txt` | Passed, exit 0; output directory not created. |
| Both RF patches and independent native patch | `*-apply-check.command.txt`, each using `git apply --check --whitespace=error-all` against the actual checkout | Passed, exit 0 for all three; no checkout application. |
| Independent scratch RF-then-native application | `scratch-{rf,native}-{check,apply}.*`; `scratch-rf-then-native/` | Passed: five native outputs equal the reviewed candidate; native application does not change the five RF outputs. |
| Original standalone case preservation | `validation-summary.json`; retained baseline and current source | Passed: all 13 original names and function bodies unchanged; 17 total. |
| Manifest/source agreement | `validation-summary.json`, `frozen/required-tests.json`, `native-design-scratch/native-test-names.json` | Passed: 53 unique mandatory names across the five nonempty groups; inherited adapter parameter instances included. |
| Frozen gate hash verification | `sha256sum -c /home/nyu/verification/e2sm-kpm/run-TQcKveEB/acceptance-gate.sha256` | Passed for both files. |
| Whitespace and source preservation | `final-whitespace.*`, `existing-documents-unchanged.*`, `ocudu-targets-{clean,index-clean}.*`, before/after Git state records | Passed: existing documents/plan/logs, OCUDU inputs, FlexRIC state, and all three HEADs unchanged during validation. |

The first Python guard run had two positive-test subcase errors: an invented
`/never-run-gcc` fixture path was correctly rejected by the new compiler
existence check (`RuntimeError: Monitor compiler is unavailable`). The test
fixture now uses a temporary ordinary file and mocks compiler lookup; the
production guard was retained. The initial command/output transcription and
diagnosis are retained in `guard-fixture-initial-failure-transcript.txt`;
the final raw 35-test output is in `python-runner-guards.stderr.txt`.
An earlier native artifact wrapper also explicitly records that no-index diff
status 1 with no diagnostics means file differences; strict patch checks and
the ordinary Falcon whitespace check both passed.

| Frozen artifact | SHA-256 |
| --- | --- |
| `tests/e2sm_kpm_du_rf_required_tests.json`, byte-identical to evidence `required-tests.json` | `3b1636a4b76e81833fe31ef1b46221ebc5a6cf2d11452c767db4fcacdfc8bf0b` |
| Evidence `check-gtest.py`, copied exactly from the plan's inline script | `754cf7bd434bf4c84933559a0a73abd42f9b20c5b5a72dea81a664345b88f007` |
| Independent native-test patch | `8693c879141cd23a447d107efe1d6b4127e024888f870fb76cc321577b08a4a6` |
| Unchanged cumulative OCUDU RF patch | `eb5527d1aec0e88853bc15c966d7a663506256def77eb811c34c59367753f992` |
| Unchanged cumulative FlexRIC RF patch | `6f1a994b7c6c8d9b89440b26832223a9d25526973ab4ec435155b0e59fe3d721` |

The persistent run root contains `baseline/required-provider.json`,
`required-tests.json`, `check-gtest.py`, and `acceptance-gate.sha256`.
Step 5's `frozen/` directory retains copies. Native base/candidate/reapplication
copies and their command/result records are retained in `native-design-scratch/`.

The six Step 5 implementation items are eligible to record complete for
baseline comparison, deliberate guarded revision support, compatibility
evidence, staging separation, separate native test design, and the populated
frozen manifest. This document records those results without editing the
existing plan. It does not mark the future RF acceptance tests as passed.

Full RF object compilation, linking, provider/callback/codec/action acceptance,
and native test execution are **Not run** in Step 5. Native source application
and execution remain Step 7 work after explicit deployment authorization.
Actual signal delivery, subscription deletion, and SDK shutdown still require
the later authorized runtime validation. Physical calibration and live RF
accuracy are not established by these synthetic offline fixtures.

After Step 5 approval, verify the frozen acceptance files before the exact
Step 6 provider-stage, flexric-stage, provider-final, and XML-gate commands:

```bash
sha256sum -c /home/nyu/verification/e2sm-kpm/run-TQcKveEB/acceptance-gate.sha256
```

The initial provider stage may retain its one planned missing-external-action
skip. The final provider XML must execute all 17 mandatory cases with zero
skips/failures/errors. Native groups are frozen now for the later Step 7 gate;
they must not be reduced to match passing results. Use the same XML gate for
the additional `native-adapter` executable. Stop before Step 7 until Plan 2
Stage A acceptance and an agreed hardware slot are explicitly authorized.
