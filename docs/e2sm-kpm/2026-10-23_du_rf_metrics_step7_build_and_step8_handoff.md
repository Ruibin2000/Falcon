# DU RF Metrics Step 7 Build and Step 8 Operator Handoff

Preparation snapshot: October 23, 2026, **14:59 EDT** (`America/New_York`),
before the operator launches. Step 7 applied-source build and
native/staged-monitor checks passed. Step 8 configuration parsing passed;
live Setup, subscription, value, and lifecycle acceptance remain **Not run**.
No service, radio, or traffic test was started by the agent.
The subsequent operator results are recorded separately in the
[Step 8 log review](2026-10-23_du_rf_metrics_step8_operator_log_review.md).

Context: [Plan 1](../../plans/e2sm-kpm-du-rf-metrics.md),
[Step 6 acceptance](2026-10-23_du_rf_metrics_offline_acceptance.md),
[measurement semantics](../notes/e2sm_kpm_du_rf_metrics_semantics.md), and
[reviewer design decision](2026-10-19_du_rf_metrics_patch_review_and_snapshot_design.md#decision).
The reviewer-authorized October 23 scope supersedes the historical deployment
blockers in earlier records. It does not establish that Plan 2 Stage A passed.

## Repository state and applied changes

| Repository | Branch / HEAD | Result |
| --- | --- | --- |
| Falcon | `E2SM-KPM` / `c0a199002b47ccb6374ab14ffd291bd0b86620ba` during validation | Approved deployment-scope plan committed, not pushed during Step 7. This record describes validation at that HEAD; subsequent reporting commits are separate. Existing unrelated UE-identity bytecode preserved. |
| OCUDU | `E2SM-KPM` / `4cffc0479f9620f668a7ac79aeb314b2e31525e4` | RF and native patches applied to ten files, unstaged and uncommitted; full required build completed. |
| FlexRIC | `falcon-xapp` / `10b8ec79d0f011902d329b2ed37f33f8b101b591` | Source, index, existing build and timestamp repair preserved. Existing untracked `build-ocudu/` and `compile_commands.json` retained. |

The OCUDU RF patch changes the scheduler snapshot header/producer and three KPM
provider/admission files. The separate native patch changes provider, scheduler,
CRC-builder and adapter test sources plus the adapter test CMake file. Exact
paths and before/after copies are retained in the application evidence. No
mutex, generation, cleanup relocation, `du.cpp` change, DU diagnostics, sidecar,
or header/NTP correlation hook was added.

| Reviewed patch | SHA-256 |
| --- | --- |
| `patches/ocudu/050a2bb-du-rf-metrics.patch` | `eb5527d1aec0e88853bc15c966d7a663506256def77eb811c34c59367753f992` |
| `patches/ocudu/69801c7-du-rf-metrics-native-tests.patch` | `8693c879141cd23a447d107efe1d6b4127e024888f870fb76cc321577b08a4a6` |
| `patches/flexric/73650812-du-rf-metrics.patch` | `6f1a994b7c6c8d9b89440b26832223a9d25526973ab4ec435155b0e59fe3d721` |

The FlexRIC patch was applied only to evidence-local scratch source. The ledger
distinguishes `ocudu-rf`, `ocudu-native-tests`, and `flexric-staged-monitor`.
The timestamp repair was neither reapplied nor installed.

## Evidence and executed validation

Persistent root: `/home/nyu/verification/e2sm-kpm/run-TQcKveEB`.

| Evidence under that root | Result |
| --- | --- |
| `step7-deploy-20261023-chi6rf4p/application-summary.json` | Both OCUDU applications passed. Preflight reverified 50 Step 6 build inputs, ten Step 6 artifacts, reviewed patch hashes and frozen gate. All five applied RF outputs equal the accepted staged candidate. |
| `applied-components.txt` | Successful applications and patch hashes recorded immediately; no automatic rollback. |
| `step7-deploy-20261023-chi6rf4p/build-native-20261023-rurw2gh0/build-native-summary.json` | Full DU and four native targets built; all tests and gates passed. |
| `monitor-live/monitor-summary.json` and `monitor-live/build-inputs.json` | External monitor compile/link and copied legacy codec/model tests passed; exact commands, flags, source/input hashes and binary identity retained. |
| `flexric-existing-checks/binary-provenance.json` | Both copied test binaries match their existing shared-build originals. Tests ran from evidence with an evidence-local `TMPDIR`; no `ctest` or FlexRIC rebuild. |
| `step7-deploy-20261023-chi6rf4p/step8-prep-20261023-n1187csn/dryrun-summary.json` | Rebuilt DU `--dryrun` exited 0 without sudo. Parsing/autoderivation only; no semantic, radio or live acceptance implied. |
| `live/operator-helper-validation.json` | Capture helper syntax, normal capture and synthetic SIGINT cleanup capture passed. This is not actual xApp deletion/lifecycle acceptance. |

Before the full build, each monitor compiler/link invocation, the native/legacy
test runs and dry-run, the recorded `pgrep -a odu`, `pgrep -a nearRT-RIC`, and
`pgrep -a xapp` checks returned 1 with no matches. Process-check errors were not
treated as absence. Git reads used optional-lock suppression in the evidence
drivers to avoid incidental index refreshes in FlexRIC.

The approved build ran from **14:46:52 to 14:49:05 EDT**:

```bash
nice -n 19 cmake --build /home/nyu/ocudu/build \
  --target odu_split_8 e2sm_kpm_meas_provider_metrics_test \
           scheduler_metrics_handler_test crc_indication_builder_test \
           fapi_to_mac_indications_fastpath_translator_test -j 4
```

All five targets completed. The native patch's adapter dependency was handled
by normal OCUDU CMake regeneration. Build and logger exits were 0; there were
no compiler or linker warnings in the DU/native build.

| Frozen native group | Executed / required | Skips / failures / errors |
| --- | ---: | --- |
| `native-provider` | 11 / 11 | 0 / 0 / 0 |
| `native-scheduler` | 11 / 11 | 0 / 0 / 0 |
| `native-crc` | 4 / 4 | 0 / 0 / 0 |
| `native-adapter` | 10 / 10 | 0 / 0 / 0 |

The four fresh XML files are `native/provider.xml`, `scheduler.xml`, `crc.xml`
and `adapter.xml`. All names exactly match their frozen groups, all cases are
`run/completed`, and all four unmodified `check-gtest.py` gates exited 0. The
provider command retained the planned `FALCON_KPM_ACTION_INPUT`; the native
provider does not consume it. The actual external-action round trip remains
the separately established Step 6 standalone result.

The 53-name manifest remains 17 offline plus 36 native names, with SHA-256
`3b1636a4b76e81833fe31ef1b46221ebc5a6cf2d11452c767db4fcacdfc8bf0b`.
The frozen checker remains
`754cf7bd434bf4c84933559a0a73abd42f9b20c5b5a72dea81a664345b88f007`.
Both were checked before/after acceptance; requirements were not refrozen.

The staged monitor uses the exact Step 6 GCC compile flags, two existing
utility objects, `libe42_xapp.a`, and `-pthread -lsctp -ldl -lconfig -lm`.
KPM loads dynamically from the unchanged configured `SM_DIR`; the monitor
does not use the harness-only static KPM link. It was built but not launched.
Compilation emitted no warnings; linking retained one known
`requires executable stack` warning, matching the Step 6 baseline limitation.
The existing codec test completed 16 iterations; the existing model test
reported success. These are existing-binary checks, not a fresh FlexRIC build.

## Binary and configuration identities

| Artifact | SHA-256 |
| --- | --- |
| `/home/nyu/ocudu/build/apps/du_split_8/odu` | `39762d8bb8401550519677bc924b50db708d552a3d7b52a584c2f613624b3d13` |
| Evidence `monitor-live/xapp_oran_moni` | `80968c102a483d03181485ecf24c99e32475e7ae6b138b0153adf5fb07d2a286` |
| `/usr/local/lib/flexric/libkpm_sm.so` | `f7e62d2a135e587d67a39cddcc1270ec9ba0ec97df03a3f8dbf63124c46ed53d` |
| `/home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml` | `c40667a31206aa4ca7b8f08d826f7d87320df5280b59ef388dbab34e9f9b326d` |
| Evidence `live/operator_helpers.sh` | `904239f75a5db3bd461b84323dbde550bfc38f45ceadd10f5eef63349cd08d51` |

The previous DU binary hash was
`f5eb2a9235a8822675227e43d09272dd4d90e34a7d05e708265f52b745defe17`.
The new DU contains uncommitted RF changes despite its unchanged source HEAD;
record the executable hash rather than interpreting the startup commit banner
as proof of pristine source. `deployment-binaries.sha256` identifies the new
DU, staged monitor and existing plugin.

## Operator-only Step 8 commands

The agent has not executed these launches. Use separate Bash terminals in the
order below. If core/CU are already healthy, preserve their working state.
In **each terminal**, first run:

```bash
export E2_RF_EVIDENCE=/home/nyu/verification/e2sm-kpm/run-TQcKveEB
source "$E2_RF_EVIDENCE/live/operator_helpers.sh"
```

Sourcing only defines functions. `falcon_capture` records the exact command,
helper hash, timestamps, combined log and command/logger exits in a unique
directory. Its `tee` ignores Ctrl+C so application cleanup output can finish;
statuses are written when the command exits. A still-running service therefore
does not yet have final exit statuses. The helper was tested with a synthetic
process only. It does not establish real SDK shutdown.

**Terminal 1, existing MongoDB and SA core:**

```bash
FALCON_RUN=$(mktemp -d "$E2_RF_EVIDENCE/live/core-XXXXXXXX")
falcon_capture "$FALCON_RUN" falcon_start_core
```

The function preserves the existing `open5gs-mongo` container/data, starts the
ten SA units in the runbook order, and individually checks all ten. It stops
on failure; it does not recreate data, stop other services or change networking.

**Terminal 2, CU; wait for N2 completion and `==== CU started ===`:**

```bash
FALCON_RUN=$(mktemp -d "$E2_RF_EVIDENCE/live/cu-XXXXXXXX")
falcon_capture "$FALCON_RUN" sudo stdbuf -oL -eL \
  /home/nyu/ocudu/build/apps/cu/ocu -c /home/nyu/ocudu/configs/cu.yml \
  log --filename "$FALCON_RUN/cu-application.log"
```

**Terminal 3, RIC before DU:**

```bash
FALCON_RUN=$(mktemp -d "$E2_RF_EVIDENCE/live/ric-XXXXXXXX")
falcon_capture "$FALCON_RUN" stdbuf -oL -eL \
  /usr/local/bin/flexric/ric/nearRT-RIC -c /usr/local/etc/flexric/ric.conf
```

**Terminal 4, rebuilt DU, single 3660-MHz configuration:**

```bash
FALCON_RUN=$(mktemp -d "$E2_RF_EVIDENCE/live/du-XXXXXXXX")
falcon_capture "$FALCON_RUN" sudo stdbuf -oL -eL \
  /home/nyu/ocudu/build/apps/du_split_8/odu \
  -c /home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml \
  log --filename "$FALCON_RUN/du-application.log"
```

Verify ARFCN 644000, n78, 3660 MHz, DU1, and F1/E2 completion. The documented
`log --filename` CLI only redirects application logs; configuration files,
carrier, gains, estimator and metrics settings remain unchanged.

**Terminal 5, new external monitor after DU Setup:**

```bash
FALCON_RUN=$(mktemp -d "$E2_RF_EVIDENCE/live/xapp-XXXXXXXX")
falcon_capture "$FALCON_RUN" env FALCON_KPM_RF_TRACE=1 stdbuf -oL -eL \
  "$E2_RF_EVIDENCE/monitor-live/xapp_oran_moni" \
  -c /home/nyu/Desktop/Falcon_repo/Falcon/configs/flexric/xapp_du_rf_metrics.conf
```

Retain the printed capture directories and send the startup/subscription logs
for review. Do not replace the staged monitor with either installed or shared
build monitor. The agent will wait for operator logs before any live acceptance.

## Pending gates and known limitations

- Step 8 needs actual E2 Setup evidence advertising both
  `FALCON.PUSCH.RSRP.dBFS` and `FALCON.PUSCH.SNR.dB`, plus acceptance of the
  function-ID-2 subscription requesting the original five and these two metrics.
  The ordinary RIC function-ID-2 acceptance line does not print the advertised
  measurement list. Configuration names, a successful subscription response,
  native advertisement tests or later RF rows alone are not an independent
  capture of the live Setup definition. Retain actual decoded advertisement
  evidence; leave this subgate unverified if ordinary logs omit it.
- Step 9 retains two-decimal agreement using existing DU window output, same
  UE and nearest report time, explicitly weaker and non-generation-matched.
  Existing console/scheduler logs have only one decimal; no qualifying active
  higher-precision output has been found. The JSON consumer is not enabled and
  has zero/clamping limitations. No output was enabled or added. This gate
  cannot pass on the currently available evidence.
- Metrics-strand writes and E2 reads remain unsynchronized by reviewer decision.
  No same-window guarantee, exact live REAL preservation, generation match or
  PHY sample-age claim is established. RSRQ remains a local `n/a` notice.
- Step 10 actual Ctrl+C/SIGTERM deletion, reconnect/restart, missing live data,
  and physical multi-UE/multi-DU checks remain **Not run**. No traffic, hardware,
  service, install, OCUDU commit or push was performed by this execution.
