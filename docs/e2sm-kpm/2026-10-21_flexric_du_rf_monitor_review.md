# FlexRIC DU RF Monitor Review — October 21, 2026

Plan 1, Step 4 candidate review and corrections. Source review, artifact
applicability checks, and two syntax-only compilation checks are complete.
The eight Step 4 implementation checkboxes record static review completion;
offline acceptance remains pending Steps 5-6. Linking, callback execution,
cross-codec acceptance, and actual signal/SDK lifecycle validation are
**Not run** in this step.

## Scope and revisions

| Repository | Branch and inspected HEAD | Work |
| --- | --- | --- |
| Falcon | `E2SM-KPM`, starting at `5fa562b39a6434b88872b43ae9c4ea44888d2275` | Regenerated the monitor RF patch, extended the callback harness, clarified configuration comments, and added this review. |
| OCUDU | `E2SM-KPM`, `4cffc0479f9620f668a7ac79aeb314b2e31525e4` | Remained unchanged; the five RF targets stay unmodified at HEAD. |
| FlexRIC | `falcon-xapp`, `10b8ec79d0f011902d329b2ed37f33f8b101b591` | Read-only review and `git apply --check`; no edits, branch operations, or builds. Timestamp repair is already committed. |

Context: [Plan 1](../../plans/e2sm-kpm-du-rf-metrics.md#step-4-review-and-complete-flexric-subscription-and-output),
[measurement semantics](../notes/e2sm_kpm_du_rf_metrics_semantics.md),
[reviewer decision](2026-10-19_du_rf_metrics_patch_review_and_snapshot_design.md#decision),
and [Plan 2](../../plans/xapp-kpm-app-subscription.md).

## Changed artifacts and compatibility

| Falcon path | Change |
| --- | --- |
| `patches/flexric/73650812-du-rf-metrics.patch` | Cumulative scratch-reviewed monitor changes described below. |
| `tests/flexric_du_rf_metrics_test.c` | Retained original fixture/configuration checks and added captured-output, precision, malformed-input, and capacity checks. Syntax-only compilation passed; execution is not run. |
| `configs/flexric/xapp_du_rf_metrics.conf` | Comments clarify the committed timestamp repair and optional decoded trace. All noncomment configuration content is unchanged. |
| `docs/e2sm-kpm/2026-10-21_flexric_du_rf_monitor_review.md` | This review and evidence references. |
| `plans/e2sm-kpm-du-rf-metrics.md` | Marked the eight Step 4 implementation items as statically reviewed, explicitly retaining the pending offline acceptance gate. Steps 7-11 are unchanged. |

The cumulative FlexRIC patch touches exactly one FlexRIC source file:
`examples/xApp/c/monitor/xapp_oran_moni.c`. No CMake, SDK, codec, or ASN.1 schema
file is included. The historical RSRP-only patch must not be stacked with it.

| Candidate | SHA-256 |
| --- | --- |
| Input RF patch | `e98d4ba96131bb2614e6287e0c126c1b86f01b2cafc4dd451f4dd5b6c8c50372` |
| Reviewed RF patch | `6f1a994b7c6c8d9b89440b26832223a9d25526973ab4ec435155b0e59fe3d721` |

The timestamp-repaired age calculation/print block remains byte-identical to
the inspected FlexRIC baseline, and the timestamp helper matches the Step 1
backup. The patch/configuration instructions now require preserving that repair
instead of reapplying it.

No change is required to `examples/xApp/c/monitor/CMakeLists.txt`. Plan 2 adds
separate broker/test targets there and retains the monitor; this patch leaves
that shared build file untouched. The offline harness's existing KPM ASN
runtime-before-E2AP runtime link order is unchanged. Both runner scripts remain
unchanged pending the separately proposed Step 5 baseline adaptations.

## Subscription and callback review

The configuration still requests exactly these names, in one DU-only Style 4
subscription with event/granularity periods of 1000 ms:

1. `DRB.RlcSduDelayDl`
2. `DRB.UEThpDl`
3. `DRB.UEThpUl`
4. `RRU.PrbTotDl`
5. `RRU.PrbTotUl`
6. `FALCON.PUSCH.RSRP.dBFS`
7. `FALCON.PUSCH.SNR.dB`

The existing builder supplies one true `NO_LABEL` per named metric. E2AP v3,
KPM v3.00, and the current S-NSSAI/SST=1 selection are retained. The DU's matching
implementation does not establish slice filtering. No RSRQ or separately named
SINR metric is subscribed. RSRQ remains the local capability notice
`RSRQ = n/a source=xapp-capability-status reason=unavailable_in_du`.

The existing candidate already associated Format 3 records with measurement
names, preserved REAL/noValue, rejected RF INTEGER/non-finite values, printed
units, and retained incomplete-row status. Review corrected these gaps:

- Added missing opt-in full-precision decoded RF tracing.
- Rejected embedded-NUL measurement names before classification and rendering,
  preventing an INTEGER with a disguised RF name from appearing as a valid RF
  measurement.
- Added pointer/count checks to the generic Format 1 path and bounded Format 3
  UE, data, name, and record lists before traversal. Missing name mappings still
  produce an explicit name/value-count diagnostic. Generic Format 1 retains its
  raw-value behavior and permits omitted optional names.
- Used explicit monitor limits of 65,535 list items and 150 name bytes. Longer
  ASN.1 name extensions are unsupported by this monitor; this does not change
  the schema or assert that every longer extension is ASN.1-invalid.
- Validated PLMN width/value and optional gNB F1AP-list structure. Included MNC
  digit count and `node_id_unused` in identity output; absent CU/DU ID is explicit
  `cu_du_id=n/a`. This avoids silently collapsing known identity distinctions.

These checks cannot establish the allocated extent of an arbitrary non-null C
pointer. Normal processing relies on the existing decoder's owned structures.
No decoder/schema changes were introduced.

## Decoded trace contract

`FALCON_KPM_RF_TRACE=1` enables additional `RF_TRACE` rows for the two exact RF
names. Unset or any other value leaves the trace disabled. Normal value output
retains two decimal places. Each trace row includes PLMN/MNC width, node type,
node number/unused bits, CU/DU ID or explicit absence, UE key/ID, header time,
row index, metric, unit, record type, value, and incomplete flag.

Finite REAL uses `%.17g`, preserving round-trip double precision and signed zero.
Missing data uses `record_type=noValue value=n/a`. Rejected INTEGER/non-finite
REAL/unsupported records preserve their actual type and an explicit reason;
they do not become measured zero or REAL. A stdio stream lock keeps each trace
row intact alongside other SDK output; it does not synchronize DU snapshots.

`header_time_us` is the repaired KPM header time, not a PHY sample timestamp.
`sample_idx` is a report-row index, not a global sequence. No DU generation,
same-window RSRP/SNR pair, RF sample age, or exact source-to-wire correlation
is established. The reviewer's deferred synchronization/generation decision
remains unchanged.

## Subscription lifetime and shutdown

The input candidate stored compact successful handles in arrays sized only by
node count, which could overflow with multiple configurations per node. The
reviewed candidate sizes separate KPM/RC arrays by node count times the number
of corresponding configurations, checks count/allocation-byte overflow, and
records only successful answers. Allocation/subscription failures and stopped
or zero-node startup follow main-thread SDK cleanup. Subscription loops honor
the stop flag; recorded handles are deleted before SDK shutdown.

SIGINT/SIGTERM handlers only set `volatile sig_atomic_t stop_requested`. The
handlers remain installed after SDK initialization, which installs its own
handler. Original loop-local deferred builder cleanup is retained because
`report_sm_xapp_api()` synchronously encodes those inputs before returning
(`FLEXRIC:src/xApp/e42_xapp.c:361`, `FLEXRIC:src/xApp/e42_xapp.c:417`). No response
reason-pointer ownership was invented. `try_stop_xapp_api()` is polled only
until its first successful stop (`FLEXRIC:src/xApp/e42_xapp_api.c:84`). Actual
subscription deletion, signal handling, and SDK shutdown still require later
authorized runtime validation. Existing builder-allocation assertions remain
inherited behavior.

## Validation and remaining gates

Evidence:
`/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step4-review-20261021-7738r6e1/`.
It retains original/candidate/verification source copies, input/reviewed patches,
configuration/build-file references, command outputs/statuses, and hashes.

- Passed: `git -C /home/nyu/flexric apply --check /home/nyu/Desktop/Falcon_repo/Falcon/patches/flexric/73650812-du-rf-metrics.patch`.
- Passed: strict scratch `git apply --check --whitespace=error-all`, independent
  scratch application, and byte comparison against the corrected candidate.
- Passed: `git diff --check`, unchanged source/CMake targets and checkout states,
  timestamp-block/helper preservation, and unchanged configuration content.
- Passed: both syntax-only checks described below, each with exit status 0,
  zero warnings, and zero errors.
- Object compilation, linking, full builds, callback tests, codec/action
  fixtures, and signal/SDK lifecycle execution: **Not run** in Step 4.

### Syntax-only compilation

Evidence:
`/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step4-review-20261021-7738r6e1/syntax-check-0qdfmi9v/`.

Immediately before compilation, `pgrep -a odu`, `pgrep -a nearRT-RIC`, and
`pgrep -a xapp` each returned 1 with no output. The monitor command was
reconstructed from the existing `build-ocudu` target's `build.make` recipe and
`flags.make` definitions. Its compiler/define/include/flag argument vector
matched the existing runner's `compile_flags()` result exactly; the latter was
used for the harness command without invoking the runner's staging/build entry
point. Macro quoting was parsed once, preserving literal string quotes.

Both commands used `nice -n 19 /usr/bin/gcc`, retained the existing warning
flags, removed object/dependency output arguments (`-o`, `-MD`, `-MT`, `-MF`),
and added `-fsyntax-only`. The monitor source path points to a private evidence
copy of the reviewed candidate. The harness uses its normal
`FALCON_XAPP_SOURCE` definition to include that same copy. Relative SDK headers
are read through the private source tree's `src` symlink to the read-only
FlexRIC sources. `TMPDIR` points inside this syntax evidence directory.

| Translation unit | Exact command and output records | Result |
| --- | --- | --- |
| Scratch-patched `examples/xApp/c/monitor/xapp_oran_moni.c` | `monitor-syntax.command.txt`, `monitor-syntax.stdout.txt`, `monitor-syntax.stderr.txt`, `monitor-syntax.status.json` | Exit 0; empty stdout/stderr; 0 warnings, 0 errors. |
| Falcon `tests/flexric_du_rf_metrics_test.c`, including the scratch monitor | `harness-syntax.command.txt`, `harness-syntax.stdout.txt`, `harness-syntax.stderr.txt`, `harness-syntax.status.json` | Exit 0; empty stdout/stderr; 0 warnings, 0 errors. |

`summary.json` records command-input hashes and unchanged before/after Git
states for all three repositories. The monitor source SHA-256 is
`b1d39a26c230bc0f99e4463e87fac2fde0fbd7e6a5ef0db255da72f015b952aa`;
the harness SHA-256 is
`71ee7050c665b45c3a66bc6eb56bea88abfa4821d994d46569451ff10562c581`.
No source correction or patch regeneration was needed after these checks, so
the reviewed patch hash above is unchanged. No CMake rerun, object/dependency
output, FlexRIC checkout/build-directory write, or SDK execution was performed.

The extended C harness includes four groups: subscription-capacity arithmetic;
trace opt-in/identity/precision/value types; malformed Format 3 callbacks; and
generic Format 1 compatibility/structure guards. It preserves the original
cross-codec fixture and configuration/action checks. Captured trace assertions
also replay representative verified rows for the later callback log. No test
pass is claimed until the harness is compiled and executed in Steps 5-6.

Step 4 implementation static review is complete; fresh offline acceptance
remains pending Steps 5-6. The plan records that distinction alongside its
checked Step 4 implementation items; Steps 7-11 remain unchanged. Next, propose both runner
baseline updates before implementing them, retain all 13 original provider
cases plus additions, complete/freeze the test manifest, and run Step 6 with
explicit paths. Preserve the process/nice/build limits and stop before Step 7.
