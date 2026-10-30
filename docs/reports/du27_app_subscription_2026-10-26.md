# Bound 27 KPM application subscription implementation

> Historical scope: this record retains its dated implementation, test
> configuration and results. The [current two-link design](../dual_link_radio_design.md)
> defines DU1 3660 MHz / 20 MHz, DU2 3600-MHz n78 interface / 40 MHz, and
> the designed Pi-Radio 9250-MHz OTA path. Those later radio changes are
> outside this record's validation.

The existing 27-metric identity xApp now serves application registrations and
pushes each new currently matched DU/UE report, including its full CU/Core/session
and current IP binding. The independent dummy saves the received report to TXT
and measures receipt before disk work. Source-driven publication retains the
100 ms DU configuration and 1-second CU/Core refresh.

Offline verification passes **107 mandatory cases, zero skipped**, including
23 subscription cases and the 84 existing identity/profile/codec regressions.
The normal and ASan/UBSan collector runs both use Python debug allocation checks.
A separate 60-second paced archived-input experiment compares every eligible
source report against independent socket receipts and all 27 TXT values.

The subsequent [October 26 live test](du27_app_subscription_live_2026-10-26.md)
receives and writes all 2,400 dual-DU reports through one dummy over 120 seconds,
with push p99 2.314 ms and normal unregister. **The planned 30-minute live
stability and live fault scenarios remain pending.** The offline verification
below was authorized while equipment was stopped and started no RIC, Core,
DU or radio service.

## Code and behavior

The integration uses `run.handle()`'s existing mapper output boundary, factored
into `BoundReportFeed` in subscription mode. The existing matcher resolves the
association; the publisher copies the completed record and never substitutes a
newer session/IP at socket-write time.

| Files | Responsibility |
| --- | --- |
| [Coordinator](../../scripts/ue_identity/xapp_ue_identity.py) | Subscription-mode CLI, existing collector/Core integration, paced replay and graceful shutdown |
| [Feed adapter](../../scripts/ue_identity/subscription_feed.py) | Mapper output, current binding eligibility, expiry and immutable snapshot handoff |
| [Service](../../scripts/ue_identity/subscription.py) | Listener, registry, exact filters, cutoff, bounded queues, partial I/O, heartbeat and cleanup |
| [Protocol](../../scripts/ue_identity/subscription_protocol.py) | Version 2, full keys, registry-derived 27-name/type/unit validation and strict JSON |
| [Collector](../../scripts/ue_identity/e2_collector.c) | Callback-entry CLOCK_MONOTONIC/instance/sequence metadata, continuous operation and restored normal signal handlers |
| [Dummy](../../scripts/ue_identity/dummy_subscriber.py) | Independent socket consumer, validation, asynchronous TXT, receipt evidence and timing summaries |
| [Source evidence](../../scripts/ue_identity/subscription_evidence.py) | Opt-in bounded trace with independent REAL bit strings before transport serialization |
| [Settings](../../configs/ue_identity/subscriptions.json) | Loopback endpoint, queue and lifecycle bounds |
| [Tests](../../tests/ue_identity/test_subscriptions.py) | Actual production mapper/socket/dummy/TXT integration and deterministic failures |
| [Verification runner](../../scripts/ue_identity/verify_subscriptions.py) | Required manifest, all identity regressions, native inputs, result/log/hash retention |
| [Paced runner](../../scripts/ue_identity/benchmark_subscriptions.py) | Actual coordinator plus all/exact dummy processes at original captured timing |

The native collector is rebuilt separately against the retained FlexRIC SDK and
isolated KPM plugin. No new RAN source metric or FlexRIC SDK implementation is
needed for this path. The earlier base5 prototype remains separate scaffolding.
Existing diagnostic invocations without `--publish-config` retain their output
behavior; subscription mode defaults to 27 metrics, enforces current matching,
and replaces routine TXT/per-report stdout with TCP pushes.

A subscription's cutoff uses actual collector callback-entry time, on the same
CLOCK_MONOTONIC origin as registry commit. Native/Python clock comparison is a
mandatory case. Delayed older callbacks are excluded, including when normalization
finishes after admission. Admission precedes data; unregister drains intact frames
and is the final acknowledgment before closure.

Equal F1AP ID 1 on two DUs, multiple UEs on one DU, Core IP changes and scoped
identity release retain correct attribution. Source/identity invalidation updates
data state without inventing reports. Source EOF does not erase the final fresh
queued report: reports precede the corresponding binding-state notice. A dedicated
barrier test reproduces that ordering race.

## Offline cases

The suite exercises real sockets and real dummy processes, rather than a Python
mock implementation of the service. It covers full 27-value/type/unit/bit-pattern
preservation, full association snapshots, exact filters, source-entry registration
cutoffs, noValue/zero and numeric limits, source expiry without new DU rows,
unsupported/malformed/duplicate/oversized frames, partial and coalesced I/O,
normal unregister, twenty app reconnects, idle/registration/incomplete deadlines,
bounded ingress, slow/non-reading clients, slow/failing TXT writers, serialization
limits, source EOF ordering, source-period validation and ambiguous internal JSON.

The retained normal/sanitizer manifests show every case and outcome. ASan/UBSan
instruments the changed collector code and its native codec/serialization paths;
the existing SDK archive and KPM plugin are reused without instrumentation.
Python's debug allocator and threaded socket/writer tests cover the new Python
ownership paths. This is not a full sanitizer or live-lifecycle audit of the SDK.
The reused SDK keeps its existing executable-stack linker warning.

## Sixty second paced forwarding

The runner takes a 60-second prefix of the existing October 25 CU/DU/Core input
capture and preserves its original event spacing. It starts the actual coordinator
with `data_source: replay` and two actual dummy processes: one receives all matched
links and one an exact full radio key. Both remain connected for 63 seconds,
including a quiet tail after input EOF, before clean unregister and TXT drain.

The passing run has 1,140 currently matched source reports after normal startup
association. The all-link dummy receives and writes all 1,140; the exact-link dummy
receives and writes its 570. Independent source bit strings, complete record
comparison and per-metric TXT checks find no omissions, duplicates, type/value
changes, cross-link leakage or incorrect IP association. The service finishes with
zero active registrations and empty ingress, with no ingress/client overflow,
serialization failure or expired report in this workload.

Measured latency and per-link cadence are retained in the
[paced result](../evidence/2026-10-26_du27_app_subscriptions/paced-summary.json).
Report-ready-to-receive p99 is 3.380 ms for all links and 3.595 ms for the exact
link; maxima are 4.034/4.662 ms. Per-link receipt-interval p99 is at most
102.444 ms, with a maximum of 103.855 ms. Coordinator RSS samples range from
23,792 to 24,980 KiB; the largest reconstructed wire frame is 3,478 bytes.
These measurements use real coordinator/publisher/client processing, with captured
callback age projected onto the replay clock. They do not characterize a new RF,
E2 transport or PHY sample-time run. The result meets the plan's same-host added
push delay and receipt-cadence budgets for this offline workload.

Resource samples retain coordinator RSS and process CPU ticks; frame sizing is
reconstructed from received wire objects after removing dummy-added timing fields.
This short run does not establish the planned 30-minute memory/connection result.

The first paced run found that an immediate EOF could suppress the final queued
report. Its failed receipts are preserved separately. The final publisher drains
fresh snapshots before source-state notices, and the complete paced comparison
passes after the fix. The explicit EOF barrier regression prevents a return of
that failure.

## Retained artifacts and reproduction

Working evidence and separate native binaries are under
`/tmp/falcon-du27-subscriptions-olzjy5l1`. Original deployed collector/plugin hashes
are preserved. The repository retains:

| Artifact | Evidence |
| --- | --- |
| [Normal summary](../evidence/2026-10-26_du27_app_subscriptions/normal-summary.json) | 107/107 mandatory cases and all per-case results |
| [ASan and UBSan summary](../evidence/2026-10-26_du27_app_subscriptions/sanitizer-summary.json) | Same cases against the instrumented collector, leak detection enabled |
| [Paced summary](../evidence/2026-10-26_du27_app_subscriptions/paced-summary.json) | Counts, independent equality, timing and cadence for both actual consumers |
| [Protocol examples](../evidence/2026-10-26_du27_app_subscriptions/protocol-examples.json) | Actual fixture registration, full bound report and final acknowledgment |
| [Manifest](../evidence/2026-10-26_du27_app_subscriptions/manifest.json) | Source/configuration/binary and archive hashes, build commands and scope |
| [Evidence archive](../evidence/2026-10-26_du27_app_subscriptions/offline-evidence.tar.gz) | Commands, manifests, logs, source traces/REAL bits, received JSONL/TXT and resource samples |

The [interface guide](../kpm_app_interface.md) provides isolated build, service,
dummy, full offline verification and paced reproduction commands.

## Remaining live acceptance

The linked 120-second live report verifies the real E2/socket/TXT path under
stable dual-UE bindings. Run the planned 30-minute workload, app churn and
slow-consumer scenarios,
retaining source/receipt/TXT equality, latency/cadence outliers, source freshness,
CPU/RSS/queue trends and normal E2 subscription deletion. Historical acquisition
success and this replay result remain separate from those live gates.
