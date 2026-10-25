# DU RF Candidate Review and Snapshot Synchronization Proposal

Plan 1, Step 3 review, October 19, 2026 (America/New_York).
Status: design approval requested; implementation and Step 3 acceptance pending.

## Inputs and scope

| Repository | Branch and revision | Authorized work |
| --- | --- | --- |
| Falcon | `E2SM-KPM`, review starting at `add1952cea010ad23f2ee67ba3e270fed19ae326` | Add this review; after design approval, correct candidate artifacts and tests here. |
| OCUDU | `E2SM-KPM`, `4cffc0479f9620f668a7ac79aeb314b2e31525e4` | Read only during this review; preserve the five RF targets at HEAD until Step 7. |
| FlexRIC | `falcon-xapp`, `10b8ec79d0f011902d329b2ed37f33f8b101b591` | Read-only access; no edits, branch changes, or builds. |

Candidate: `patches/ocudu/050a2bb-du-rf-metrics.patch`.
Reviewed input SHA-256:
`8ce25f800d9f1b875d3610aa77bb37b686139a5e0b845d20a7d2bfe9db281f44`.
This identifies the uncorrected candidate, not an accepted final package.

Context: [Plan 1](../../plans/e2sm-kpm-du-rf-metrics.md),
[Step 2 measurement semantics](../notes/e2sm_kpm_du_rf_metrics_semantics.md),
and [Plan 2 coordination](../../plans/xapp-kpm-app-subscription.md).
Evidence: `/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step3-design-review/`.
`OCUDU:path:line` citations refer to the inspected OCUDU revision;
`FALCON:path:line` citations refer to the review starting revision.

## Candidate checklist review

| Step 3 requirement | Static review result | Remaining acceptance |
| --- | --- | --- |
| Translate each CU UE F1AP ID and search by `ue_index` | Present: the RF helper calls the translator and uses `std::find_if` on the snapshot's `ue_index`; it does not use a vector offset. | Safe concurrent access, native translator assumptions, and fresh multi-UE regression evidence. |
| Preserve request order and one record per requested UE | Present: each loop iteration starts with `noValue` and appends exactly one item, including missing/wrong-type UEs. Invalid scope/labels also append placeholders before returning false. | Fresh collection and Style 4 regression results. |
| Preserve negative fractions and valid zero; require SNR samples | Present: finite floats are promoted to `REAL`; SNR requires `nof_pusch_snr_reports > 0`, copied from the scheduler accumulator. | Fresh scheduler/conversion/provider cases, including failed CRC samples. |
| Reject labels and node/cell scopes at admission and collection | Present for the two named RF metrics: UE level, no cell scope, exactly one label, true `NO_LABEL`, no other known fields or extensions. | Expanded-label and production admission regressions. |
| Replace dummy registrations and advertise exact UE-level vendor names | Present in the provider registration. The existing production packer consumes the supported-level lists. | Decode `pack_ran_function_description()` from the production provider; a name-list-only assertion is insufficient. |
| Safe replacement and reads across affected readers | Missing: the candidate retains unsynchronized mutable caches and iterator reads. | Approved design, implementation, concurrent regression, and later native/applied checks. |
| Snapshot generation and opt-in correlation trace design | Missing in the candidate. Proposed below. | Approve the design, implement generation support, and retain Step 7 report/trace hooks separately. |

The `has_only_no_label()` check covers the current ASN.1 label presence fields,
extension flag, and extension pointers
(`OCUDU:include/ocudu/asn1/e2sm/e2sm_kpm_ies.h:216`). Current static findings
do not close any Step 3 checkbox or substitute for Step 6 acceptance.

The capability path is the provider's supported-level filtering and the
production RAN-function packer
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:180`,
`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_asn1_packer.cpp:137`).
The existing generic dummy registrations use `UNKNOWN_LEVEL`; their mere
registration does not prove advertisement at UE scope.

## Actual executor model

### Metrics updates use a distinct metrics strand

The worker manager creates the metrics strand on `non_rt_medium_prio_exec`
(`OCUDU:apps/services/worker_manager/worker_manager.cpp:375`). The DU application
passes that executor to its metrics manager
(`OCUDU:apps/du/du.cpp:376`). DU and RLC metric callbacks capture owned metric
objects and defer consumer execution to that executor
(`OCUDU:apps/units/flexible_o_du/o_du_high/du_high/metrics/du_metrics.h:43`,
`OCUDU:apps/units/flexible_o_du/o_du_high/du_high/metrics/du_high_rlc_metrics.h:39`).

The DU E2 consumer forwards scheduler reports to its scheduler consumer, which
calls the E2 notifier once per cell. The RLC E2 consumer also calls the notifier
directly
(`OCUDU:apps/units/flexible_o_du/o_du_high/du_high/metrics/du_metrics_consumers.cpp:54`,
`OCUDU:apps/units/flexible_o_du/o_du_high/du_high/metrics/consumers/scheduler_metrics_consumers.cpp:391`,
`OCUDU:apps/units/flexible_o_du/o_du_high/du_high/metrics/du_high_rlc_metrics_consumers.cpp:38`).
The connector forwards both report types directly into the provider; it does
not dispatch them to E2
(`OCUDU:lib/e2/common/e2_du_metrics_connector.cpp:11`).

### DU control, F1AP, and E2 timers share a control strand

`du_ctrl_exec` and `du_e2_exec` decorate the same `ctrl_executor_mapper::strand`.
The mapper returns those decorated executors from the corresponding accessors
(`OCUDU:lib/du/du_high/du_high_executor_mapper.cpp:394`,
`OCUDU:lib/du/du_high/du_high_executor_mapper.cpp:439`). This is serialization by
strand, not permanent affinity to one operating-system thread.

DU-high supplies its control executor to F1AP; received F1AP messages are
explicitly dispatched to that executor
(`OCUDU:lib/du/du_high/du_high_impl.cpp:69`,
`OCUDU:lib/f1ap/du/f1ap_du_impl.cpp:366`). The E2 factory receives a timer factory
bound to `du_e2_executor()`
(`OCUDU:lib/du/du_high/o_du_high_factory.cpp:156`). Indication timeout collection
therefore runs through that control strand
(`OCUDU:lib/e2/procedures/e2_indication_procedure.cpp:31`). The metrics strand is
different; sharing an underlying worker pool does not serialize the two strands.

### E2 receive processing is not confined to that control strand

The DU application supplies `e2_rx_executor()` to the SCTP gateway. That mapper
accessor returns the raw high-priority pool executor, rather than the control
strand
(`OCUDU:apps/du/du.cpp:338`,
`OCUDU:lib/du/du_high/du_high_executor_mapper.cpp:442`). The SCTP client registers
its receive callback with the supplied executor
(`OCUDU:lib/gateways/sctp_network_client_impl.cpp:332`). Packed E2 data is decoded
and forwarded directly to the E2 receive channel, then to
`e2_impl::handle_message()`; that method does not switch execution contexts
(`OCUDU:lib/e2/gateways/e2_network_client_factory.cpp:28`,
`OCUDU:lib/e2/common/e2_connection_handler.cpp:32`,
`OCUDU:lib/e2/common/e2_impl.cpp:174`).

Subscription deletion sets its transaction event directly
(`OCUDU:lib/e2/common/e2_subscription_manager_impl.cpp:114`). The event source
sets a manual event, whose awaiter flush resumes suspended coroutines inline
(`OCUDU:include/ocudu/support/async/async_event_source.h:33`,
`OCUDU:include/ocudu/support/async/manual_event.h:34`,
`OCUDU:include/ocudu/support/async/detail/event_impl.h:11`). In the existing
indication loop, setting `running = false` does not skip the following action
loop: it can still call `collect_measurements()` during that final iteration
(`OCUDU:lib/e2/procedures/e2_indication_procedure.cpp:35`). Consequently, assuming
that every getter necessarily runs on the control strand is insufficient.
This is a static concurrency finding; no runtime failure was reproduced.

## Why protecting only the RF getter is insufficient

Scheduler updates clear and refill `last_ue_metrics` while replacing the cell
PRB/slot/preamble fields; multiple existing getters read the same state
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:133`,
`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h:107`). RLC callbacks
append/trim the RLC map while discovery and throughput/delay getters iterate it.
The scheduler callback also invokes `clear_rlc_metrics()`.

That cleanup calls the F1AP translator from the metrics strand
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:156`). Translator
lookups return/read live UE-context pointers
(`OCUDU:lib/f1ap/du/f1ap_du_impl.cpp:590`,
`OCUDU:lib/f1ap/du/f1ap_du_impl.cpp:619`). The UE manager has a mutex for its
ID map and some lookups, but UE slot insertion/removal and a returned pointer's
lifetime are not all protected by that same lookup lock
(`OCUDU:lib/f1ap/du/ue_context/f1ap_du_ue_manager.h:30`,
`OCUDU:lib/f1ap/du/ue_context/f1ap_du_ue_manager.h:53`,
`OCUDU:lib/f1ap/du/ue_context/f1ap_du_ue_manager.h:84`). A new provider mutex
cannot serialize independent F1AP context mutation. Confining translator use
to the existing control strand is part of the proposed solution.

## Recommended design A: protected provider state and DU receive confinement

Approval is requested for the complete design below before implementation.

1. Add one nonrecursive `std::mutex` to the DU provider. Both `report_metrics()`
   overloads acquire it for publication/update. `get_meas_data()` acquires it
   once around the getter dispatch and the complete requested-UE batch. Both
   UE-discovery overloads and explicit cleanup also acquire it. Immutable
   capability registrations need no additional state lock.
2. Protect the scheduler UE vector, associated cell counters, RLC map/history,
   cleanup timestamp, and snapshot metadata with that same mutex. Existing
   CQI/PRB/delay/throughput getters remain behind the shared dispatch lock;
   their calculations and existing mapping limitations remain unchanged.
   No pointers or iterators into mutable caches may escape the lock.
3. Use a private cleanup helper for callers that already hold the lock. Remove
   F1AP-dependent cleanup from the metrics-thread scheduler callback; invoke
   cleanup before UE discovery and measurement collection on the control strand.
   Preserve the existing one-second check and disconnected-context predicate.
   This intentionally moves cleanup timing from metric arrival to the next E2
   read and requires baseline five-metric regression coverage. With no E2
   reads, cleanup is deferred; review the retained-cache bound as well as
   numerical output. An explicit public cleanup call retains the control-strand
   caller requirement.
4. Add a monotonically increasing `uint64_t` scheduler generation, initially
   zero for no accepted report. Publish the generation, complete UE snapshot,
   counts, PCI, source slot, and window length together under the lock. Increment
   on every accepted scheduler report, including empty/replacement windows.
5. Route the DU application's E2 receive callback through its existing
   `du_e2_executor()` instead of its raw `e2_rx_executor()`. This is a separate
   prerequisite artifact targeting `apps/du/du.cpp`, outside the five-file RF
   patch. It confines receive-driven protocol continuations and translator
   reads to the same strand as F1AP. It adds no new queue implementation,
   provider task ownership, worker thread, or ASN.1 schema. It does move E2
   socket/decode work onto the control strand; test queue delay and ordering
   offline and retain actual runtime load/stability as a later acceptance gate.
6. New trace formatting and file output happen after copying owned results
   out of the protected lookup. The lock is on the metrics/E2 consumer side;
   it is not added to PHY or scheduler slot-processing callbacks.

The complete design has two required parts. Applying a provider-only patch
without the receive-confinement prerequisite does not establish the proposed
translator/concurrency guarantee for the running DU. No OCUDU file, including
the prerequisite target, will be edited in its checkout before Step 7.

Alternative B is full executor confinement: dispatch owned scheduler/RLC reports
onto E2 before invoking the provider, and also confine E2 receive handling.
That approach preserves cleanup at report consumption, but requires additional
connector/factory changes, copied queued reports, overflow behavior, and a
reviewed shutdown/drain lifetime. It needs a separately approved artifact and
staging strategy. Design A avoids adding that asynchronous provider lifetime.

## Proposed generation and trace contract

The private RF selection result should capture snapshot generation, requested
F1AP ID, resolved `ue_index`, metric, selected float promoted to double, record
type/missing reason, the window's SNR sample count, PCI, source slot, and window
length in one protected lookup. Every UE in a single RF getter call observes
one generation. Separate RSRP and SNR calls may legitimately observe different
generations; do not claim a same-window pair unless those generations agree.

The baseline exposes no RSRP sample count in the public snapshot. Do not infer
that count from a finite RSRP value. If an actual RSRP count is required in the
diagnostics, copy the existing scheduler RSRP accumulator count into the
snapshot in the separate Step 7 diagnostic patch. It does not change RSRP
validity, which follows the recorded finite-value/sentinel contract.

Keep tracing off by default, with an opt-in `FALCON_KPM_RF_TRACE=1` switch.
The separate Step 7 diagnostic patch must use a default trace-aware interface
path instead of RTTI, retain owned row/metric metadata, and correlate it with
the header actually packed. Message packing currently clears the collection
and updates the header before header packing
(`OCUDU:lib/e2/procedures/e2_indication_procedure.cpp:55`,
`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:78`,
`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:360`).
Retain local report counter, row index, generation, exact NTP header word and
its repaired Unix-microsecond conversion. Emit finite values with 17 significant
digits and explicit `noValue`; retain complete node/DU identity at the report
side. Trace must not reconstruct source data through a second lookup.

## Artifact boundary and proposed validation

Keep the cumulative RF patch restricted to its existing five production files.
Corrections, once approved, are made only in scratch copies and regenerated
into Falcon. Keep the DU E2 receive prerequisite, native tests, and Step 7
diagnostics in separate patches. The proposed prerequisite artifact is
`patches/ocudu/4cffc04-du-e2-rx-confinement.patch`; it has not been created.
The staging runner currently compiles every
`.cpp` named by its RF patch, so adding unrelated executor/application or test
sources to that patch would violate its compilation assumptions
(`FALCON:scripts/ocudu/test_du_rf_metrics.py:47`,
`FALCON:scripts/ocudu/test_du_rf_metrics.py:73`). Do not weaken those guards.

Step 5 test design must retain all 13 original cases and add deterministic
overlap checks for scheduler replacement, all requested UE records, SNR
count/value consistency, RLC updates/discovery/cleanup, and empty windows.
Also require original five-metric numerical regressions, production capability
decoding, and label/UE mapping cases. Executor tests must exercise receive
events, timeout and delete continuations, F1AP mutation, and shutdown ordering
through the selected strand; a provider-only mutex stress test cannot close
that integration gate. Use explicit synchronization rather than fixed sleeps.
Add an exact test-name manifest entry/XML gate for any extra native executable.
Generation/trace/header association also needs the separate Step 7 diagnostics
tests. A focused sanitizer run, if used, must be isolated and separately approved
under the existing build/process rules.

This review performs no build or test execution. Scratch implementation,
runner changes, additional patches, and final candidate hashing remain pending
approval. Step 7 remains blocked by Plan 2 Stage A and the hardware-slot gate.
No Step 3 checkbox is marked complete by this review.

## Decision

The project lead's reviewer decision, communicated by Hao Ding on 2026-10-21,
is to retain the existing cumulative RF implementation and defer concurrency
hardening for this iteration. Neither recommended design A nor alternative B
is selected. Do not implement a provider mutex, snapshot generation, cleanup
relocation, or the `apps/du/du.cpp` E2-receive prerequisite. The preceding
analysis and proposals are retained as historical design context, not active
implementation instructions.

Snapshot safety and generation/source-trace correlation are deferred known
limitations: metrics-strand writes and E2 reads remain unsynchronized. This
includes possible data races, invalidated reads, and mixed snapshot/count/value
observations. Sequential offline passes do not establish thread safety,
same-window RF pairs, or generation-based source correlation. The snapshot
concurrency acceptance row is deferred, not passed.

Continue Steps 3-6 with the exact two vendor metrics and the remaining
measurement contract. Correct genuine contract gaps only in scratch copies,
regenerate Falcon patch artifacts, and keep the five OCUDU targets unchanged
at HEAD until Step 7. Keep RSRQ as a local `n/a` notice; add no RSRQ metric.
The Step 4 decoded monitor trace remains in scope, but cannot establish a
source-generation correlation. See the
[2026-10-21 contract review](2026-10-21_du_rf_metrics_contract_review.md).

This decision supersedes the approval/implementation gates for designs A/B
and the related concurrent/generation tests in this October 19 review. It does
not waive any other offline acceptance case or weaken a runner guard. Plan
Steps 7-11 are unchanged and outside the authorized execution scope; their
generation-dependent requirements will need review before those steps are
authorized. Plan 2 Stage A acceptance and an agreed hardware slot still gate
deployment and live work. This decision does not authorize applying patches to
the host source checkouts, deployment builds, or service actions.
