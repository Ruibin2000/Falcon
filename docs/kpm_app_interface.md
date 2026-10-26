# Bound KPM application subscription interface

The existing 27-metric identity xApp now accepts application subscriptions and
pushes its newly matched reports over TCP. Each report retains its full link,
DU/UE, CU/Core/session and current IP association. The independent dummy receives
machine-readable pushes, timestamps them and saves TXT. The service follows the
actual 100 ms DU report stream; CU identity and Core polling remain at 1 second.

This implements the revised [Plan 2](../plans/xapp-kpm-app-subscription.md).
Offline mapper/codec/socket/TXT checks and a 60-second paced archived-input run
pass. A subsequent [120-second live E2 test](reports/du27_app_subscription_live_2026-10-26.md)
receives and writes all 2,400 dual-DU reports through one dummy, with normal
unregister and push p99 2.314 ms. The planned 30-minute live stability run and
live reconnect/slow-client scenarios remain pending. See the
[implementation and verification record](reports/du27_app_subscription_2026-10-26.md).

## Start the service

Build a separate collector and isolated plugin, preserving the earlier binary:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
SUB_RUN=$(mktemp -d /tmp/falcon-bound-kpm-XXXXXXXX)
FALCON_IDENTITY_SM_DIR="$SUB_RUN/sm" \
  bash scripts/ue_identity/build.sh "$SUB_RUN/collector"
sed "s#^SM_DIR = .*#SM_DIR = \"$SUB_RUN/sm/\"#" \
  configs/flexric/xapp_ue_identity_expanded.conf > "$SUB_RUN/xapp.conf"
printf 'Run directory: %s\n' "$SUB_RUN"
```

With the existing RIC/CU/DUs/Core already running, start the subscription-mode
coordinator and leave it running:

```bash
python3 -B scripts/ue_identity/xapp_ue_identity.py \
  --collector "$SUB_RUN/collector" --e2-config "$SUB_RUN/xapp.conf" \
  --config configs/ue_identity/local.json \
  --publish-config configs/ue_identity/subscriptions.json \
  --duration 0 --publisher-summary "$SUB_RUN/service-summary.json"
```

`SUBSCRIPTION_READY` identifies the bound listener at `127.0.0.1:8765`, the
instance, source kind and profile `du27_bound_v1`. It means application admission
is available; registration may wait for source initialization or a valid match.
The existing collector's subscription log remains a separate source-readiness
check. All intended RIC/DU membership must be present at acquisition startup.

Application lifecycle events are printed immediately to stderr, and appear in
the xApp terminal/log when stderr is captured:

| Event | Meaning |
| --- | --- |
| `APP_REGISTER_RECEIVED` | A decoded registration request arrived; validation is next |
| `APP_REGISTERED` | Registry admission succeeded and the success response was queued |
| `APP_REGISTER_REJECTED` | Admission failed; `reason` gives the error code |
| `APP_UNREGISTER_RECEIVED`, `APP_UNREGISTERED` | A valid unregister was received, publication stopped for this client, and its final response was queued |
| `APP_DISCONNECTED` | The connection and registry entry were cleaned up; `reason` distinguishes normal drain, EOF, timeout, overflow or shutdown |
| `APP_REQUEST_REJECTED` | A malformed or invalid non-registration request was rejected |

Each line contains a UTC timestamp, broker/source identity, peer, app/subscription
IDs when known, and event details. Reconnecting creates a new registration and
subscription ID in these same logs. `acknowledgement: queued` describes server
admission; the dummy's received `registration_status` confirms the acknowledgment
reached the client. KPM pushes and routine heartbeat do not generate console
lines. Log-write errors are counted as `lifecycle_log_errors`.

Subscription mode selects 27 metrics by default and forces fresh-only matching.
It checks DU Style 4/100 ms and CU identity/1000 ms configuration, with 1-second
Core polling. It does not start a new E2 subscription per app. Acquisition and
matching continue with no registered apps. The same admitted CU allocation and
existing ambiguity/reuse guards apply.

`--duration 0` runs until SIGINT/SIGTERM. A finite duration up to 3600 seconds
is also supported. On shutdown the listener stops admission, the collector
removes its shared handles and stops SDK dispatch, then the publisher drains
clients within its bound. Source membership changes and SDK/E2 reconnect remain
outside the app reconnect mechanism.

Production subscription mode writes no routine report TXT or per-report stdout.
`--text-output` and `--last-known` are rejected in this mode. Existing diagnostic
commands without `--publish-config` retain their previous behavior. Optional
`--capture-events NEW_FILE` captures raw inputs; `--report-evidence NEW_FILE`
enables a bounded asynchronous source trace with independent REAL bit strings.
Both are explicit verification tools, not required delivery paths.

## Run the independent dummy

In another terminal on Spark:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
DUMMY_RUN=$(mktemp -d /tmp/falcon-kpm-dummy-XXXXXXXX)
python3 -B scripts/ue_identity/dummy_subscriber.py \
  --host 127.0.0.1 --port 8765 --app-id dummy-all --all-links \
  --expected-profile du27_bound_v1 --reports 100 --timeout 60 \
  --text-output "$DUMMY_RUN/kpm.txt" \
  --receipts-output "$DUMMY_RUN/receipts.jsonl" \
  --summary "$DUMMY_RUN/summary.json" --check-timing
```

The dummy receives only from the app socket. It never reads xApp TXT, shared
report files, E2 or Core. It validates the full 27-name set, values/types/units,
complete identities, subscription/instance and report timing. It timestamps when
the complete frame becomes available, before validation/formatting. TXT writing
runs in a separate bounded worker. Each TXT block includes subscription/report/
delivery/link IDs, binding revision, receipt time, full association and all KPM.

Use `--duration SECONDS` instead of `--reports` for a timed connection run. Ping
runs every 10 seconds. Normal completion unregisters, verifies the final
acknowledgment and EOF, drains TXT and checks that written/received counts agree.
Failures, overflow, truncated frames or TXT errors return nonzero. Output files
must be new. `--check-timing` enforces the plan's added-delay budgets; summaries
always retain the measured distributions. A planned long run uses `--duration
1800`, complete source/receipt evidence and separate cadence/count analysis.

For exact filtering, replace `--all-links` with `--links-file FILE`. The file is
an array of complete node/UE keys, for example:

```json
[
  {
    "node": {
      "mcc": "001", "mnc": "01", "node_type": "ngran_gNB_DU",
      "gnb_id": "411", "gnb_id_bits": 22, "du_id": "1"
    },
    "ue": {"id_type": "gnb_du", "gnb_cu_ue_f1ap_id": "1"}
  }
]
```

Use current context identifiers. Equal F1AP numbers on different DUs are distinct
keys. Exact subscriptions remain registered but waiting if a UE reconnects with a
new F1AP ID; register a new key explicitly. All-links consumers such as an MPTCP
server can inspect the current association in every newly matched report.

## Protocol version 2

Each frame is a UTF-8 JSON object plus newline. TCP splitting/coalescing and
partial writes are supported. JSON duplicate keys, invalid UTF-8, unsupported
versions/profiles and oversized frames are rejected. App/request IDs contain
1–64 ASCII `[A-Za-z0-9_.-]` characters.

Register all current matched links:

```json
{"version":2,"type":"register","request_id":"reg-1","app_id":"mptcp-server","expected_profile":"du27_bound_v1","filter":{"mode":"all_matched_links"}}
```

Or use `filter: {"mode":"links","links":[KEY,...]}` with 1–32 distinct full
keys as above. Registration does not alter E2 acquisition or source settings.
Success has `type: registration_status`, `status: registered`, echoed request/app
IDs, subscription and broker instance IDs, source, profile, the ordered 27 metric
names, filter, `report_period_ms: 100`, `cu_period_ms: 1000`, `core_period_ms: 1000`,
`cutoff_at_mono_us`, data state and `delivery: best_effort_no_replay`.

Status precedes data. Only reports whose **collector callback entered after the
registry commit** can reach that registration, including when a pre-registration
callback finishes normalization later. The native and Python entry/commit clocks
both use CLOCK_MONOTONIC; the regression suite checks their shared process origin.

A `kpm_report` push includes:

| Field | Meaning |
| --- | --- |
| `version`, `metric_profile` | `2`, `du27_bound_v1` |
| `broker_instance_id`, `subscription_id` | Fresh service process and connection registration |
| `data_source` | `e2`, `replay` or `fixture` |
| `report_seq`, `delivery_seq` | Existing mapper report sequence as a wire string; per-registration consecutive push sequence from 1 |
| `link_id` | Canonical full radio key; no F1AP-only attribution |
| `binding_revision` | Local association revision, not a DU/CU lifecycle-generation proof |
| `callback_at_mono_us`, `report_ready_at_mono_us` | Callback entry and complete matched snapshot generation |
| `published_at_mono_us`, `valid_until_mono_us` | Serialization/enqueue time and source-freshness bound |
| `ingress_dropped_total` | Cumulative publisher ingress loss |
| `report` | Complete existing matched record, including `node`, `row.ue`, `row.metrics`, `binding`, `ue_ipv4` and provenance |

The inner report retains its mapper `app_instance`, numeric `sequence`, source
instance/indication IDs, header/receive/callback wall times, sample index,
granularity, incomplete flag and binding reason/method/assurance. Its binding
includes serving DU/CU context where available, GUAMI, SUPI, AMF/RAN NGAP IDs,
PDU session ID, DNN and current IPv4. Wire IDs/timestamps/counters use decimal
strings; the inner historical mapper sequence remains numeric explicitly.

Raw metric names/types/units come from
[metrics.EXPANDED](../scripts/ue_identity/metrics.py) and the
[27-metric reference](du_kpm_metrics_reference.md). Finite REALs, signed values,
valid zero, unsigned 32-bit INTEGER and `no_value`/null are retained. The two
failure ratios stay in `derived_metrics`. A missing/wrongly typed raw metric or
wrong granularity rejects the full profile with a counted diagnostic; it does
not fabricate a measurement or silently downgrade. Incomplete, cached, stale,
unresolved or ambiguous bindings are not published as currently matched KPM.

Immutable report snapshots preserve the association at generation. Later source
state or a new IP cannot relabel an older report. Fresh queued reports precede
source-state notifications, including the last report at EOF; expired snapshots
are counted and suppressed. No timer retransmits old KPM.

`binding_state` notifications carry link/revision, data state and reason. Separate
data states are `waiting_for_match`, `receiving`, `binding_invalid` and
`source_unavailable`. Core/CU withdrawal/error and freshness expiry update state
without requiring a new DU report. They do not fabricate measurements.

Ping and unregister requests are:

```json
{"version":2,"type":"ping","request_id":"p-1"}
{"version":2,"type":"unregister","request_id":"u-1","subscription_id":"sub-1"}
```

Pong echoes the request with data state and last matching report age. Unregister
stops adding frames, drains complete/partial queued frames, acknowledges
`unregistration_status`/`unregistered`, then closes. No frame follows that
acknowledgment. Reconnect needs a fresh registration; active duplicate app IDs
are rejected and no history is replayed.

Stable rejection codes include `invalid_request`, `unsupported_version`,
`unsupported_profile`, `duplicate_app_id`, `already_registered`,
`too_many_clients`, `frame_too_large` and `shutting_down`. Malformed frames without
a safe request ID receive an error and close when possible.

## Bounds and measurements

[Subscription settings](../configs/ue_identity/subscriptions.json) constrain:
16 connections, 32 exact links, 8 KiB requests, 64 KiB outgoing frames, 256 owned
reports/4 MiB ingress and 64 frames/1 MiB per-client output. Python object sizes
are accounted conservatively, beyond encoded payload alone. Full ingress drops
the new arrival with a counter; full/slow client queues disconnect only that app.

Registration and incomplete-frame deadlines are 5 seconds, valid-request idle
expiry 30 seconds, pending writes without progress 5 seconds, and unregister/
shutdown drain at most 2 seconds. TCP_NODELAY is enabled on both app endpoints.
`write_chunk`/`test_stall_app` are deterministic fixture I/O adapters; live E2
mode rejects them. Dummy writer bounds can be lowered with
`--writer-queue-reports`/`--writer-queue-bytes`; its test delay is forbidden for
live sources.

Source evidence is opt-in, bounded to 100,000 records with 256 queued items/4 MiB,
and reports writer/capacity failures. A 30-minute two-DU run can produce about
36,000 source rows; size all receipt/measurement storage accordingly. Dummy
timing arrays have a 200,000-report limit and fail visibly when exceeded.

Time measurements distinguish callback → ready, ready → publish, publish →
receipt, and receipt → TXT written. `published` means enqueued, not successfully
received. Replayed callback time is projected from captured arrival/age onto the
shared monotonic clock and labelled by `data_source: replay`; it is not a new
radio measurement. Header age is not PHY sample age or pure transport latency.

## Reproduce offline validation

With a rebuilt collector and isolated plugin, run the full mandatory suite:

```bash
PYTHONMALLOC=debug python3 -B scripts/ue_identity/verify_subscriptions.py \
  --collector "$SUB_RUN/collector" --plugin "$SUB_RUN/sm/libkpm_sm.so" \
  --output-dir "$SUB_RUN/verification"
```

The runner requires native inputs, disallows skipped required gates, and retains
case manifests/results, source hashes, two actual dummy TXT/JSONL files and source
snapshots. It includes the previous identity/profile/codec regressions.

For the existing archived input at its original 100 ms pace:

```bash
python3 -B scripts/ue_identity/benchmark_subscriptions.py \
  --seconds 60 --output-dir "$SUB_RUN/paced-replay"
```

This starts the real coordinator and all/exact dummy processes, captures
independent source bit strings, compares every eligible record and all TXT
values, checks timing/cadence budgets, and records RSS/CPU samples. It requires
local sockets but no RIC/Core/DU services. It establishes offline forwarding;
real E2 functional delivery and the 30-minute live stability run remain separate.

The earlier standalone base5/version-1 prototype and its reproduction commands
are preserved in the [historical reference](evidence/2026-10-26_kpm_app_subscription/base5_interface_reference.txt).
They are not a dependency of this bound-report service.
