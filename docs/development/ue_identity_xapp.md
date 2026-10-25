# Standalone CU/DU identity xApp

Developer: Ruibin Chen. Implementation started on October 21, 2026 on both
repositories' `Dual-UE` branches. This is the first implementation milestone of
[Plan 4](../../plans/cu-ue-ip-e2-binding.md). Real single/dual-UE observational
association and uplink passed. Explicit CU serving-DU scope is implemented for
the admitted local profile; shared lifecycle-generation and recovery gates remain open.

The application combines CU-CP identity-bearing KPM, DU KPM with seven
measurements by default, and read-only Open5GS AMF/SMF queries. It emits
diagnostic NDJSON on stdout; SDK and error messages go to stderr. It has no
Plan 2 broker or MPX dependency.

## Implemented path and current boundary

```text
SMF SUPI/PDU/IP ---------+
AMF SUPI/NGAP/gNB -------+--> Python coordinator --> diagnostic NDJSON
CU NGAP/GUAMI/F1 --> E2 -+
DU1/DU2 base5+RF -> E2 -+
```

CU reads its local NGAP/F1 contexts on the CU-CP executor. Owned snapshots retain
AMF/RAN NGAP IDs, GUAMI, CU/DU F1AP UE IDs and actual serving DU ID. Missing,
releasing, unconnected or reconfiguring contexts are withheld. Enabling
`metrics.layers.enable_ue_identity` opts into this collection; it defaults off.
The existing periodic metrics path transfers the copy to E2.

CU KPM advertises the vendor measurement `FALCON.UE.RRCState`, a real RRC state
gauge (0 idle, 1 connected, 2 inactive). Format 4 enumerates connected UEs with
complete identities and applies an SST equality filter using admitted DRBs.
AMF UE NGAP ID, GUAMI and F1 ID travel in standard `UEID-GNB`, separately from
the measurement. A disappeared subscribed UE produces `no_value`. The provider
expires its identity snapshot after three seconds. A filtered list is not a
complete lifecycle snapshot.

The October 25 capture exposed two simultaneous F1 ID 1 contexts on different
DUs. CU at 1 s was current; the original wire identity lacked their serving-DU
distinction. Increasing the CU rate cannot remove that collision.

The updated CU allocates the existing optional eight-octet `ran-UEID` in
`UEID-GNB` as **`du36-cuue28-v1`**: big-endian unsigned
`(serving_du_id << 28) | cu_ue_index`. All 36 DU bits are preserved; CU indices
outside `[0, 2^28)` are withheld rather than truncated. This is a local opaque
RAN UE identity allocation, not a new ASN.1 field or measurement. The collector
retains the original octets as `ue.ran_ue_id_hex`. Only a CU explicitly admitted
with `ran_ue_id_format: du36-cuue28-v1` is interpreted this way; arbitrary
third-party RAN UE IDs remain opaque.

The mapper joins `(PLMN, gNB, DU ID, F1AP ID)` to CU AMF/GUAMI, then to Core.
Equal F1 numbers on different DUs are independent, and explicit scope does not
require the other DU to be reporting. Existing AMF/GUAMI/F1 fields, RRC state,
source freshness, measurement values and legacy profiles are preserved.

| Mode | IP publication |
| --- | --- |
| Admitted explicit CU scope, either CLI mode | Unique current bindings use `assurance: cu_reported_du_scope`, with `serving_du_id` and `cu_ue_index` |
| Legacy CU, default `strict` | Keeps `ue_ipv4: null`; generic UEID alone does not establish serving DU |
| Legacy CU, explicit `--observed-unique` | Retains experimental `observed_unique_current_context` matching and conservative conflict handling |

The October 21 user preference adds a separate binding policy:
`binding_policy: last_known` in `local.json`, or explicit `--last-known`.
After a link has a verified association, missing inputs for that UE can reuse its
history with `binding_status: cached`, `assurance: last_known_observed_context`,
the last verification time and its monotonic age. A cached IP is historical,
not a new claim of current verification. `--fresh-only` restores the original
withhold-on-missing-input behavior. Historical fallback cannot establish an
initial binding or bypass scope/conflict checks.

The dual local config also enables `independent_links: true`. Once the DU/F1
association is established, each UE's current CU/Core relation is checked
independently. Other-DU silence alone does not trigger `cached`. Fresh own
inputs remain `matched` with `assurance: established_du_scope_current_context`
when the established DU scope is needed. This applies with `--fresh-only` too:
radio association retention is separate from historical IP fallback.

The CU index is **not a shared CU/DU context-generation token**. Reuse of the
same DU/F1 key with a different CU identity/index remains quarantined. New F1
contexts can establish their own relations while the peer continues; release
withdraws the corresponding relation, and older headers cannot inherit a later
relation. Exact unobserved full-key reuse and source-restart generation proof
remain under Plan 4. Timers alone do not clear uncertainty. Ingress loss remains
latched. Cross-DU equality no longer permanently taints the peer's bare F1 ID.

## DU measurement profiles

The default `configs/flexric/xapp_ue_identity.conf` subscribes to seven DU
measurements: `DRB.RlcSduDelayDl`, `DRB.UEThpDl`, `DRB.UEThpUl`, `RRU.PrbTotDl`,
`RRU.PrbTotUl`, `PUSCH.RSRP.dBFS`, and `PUSCH.SNR.dB`. The RF names have no
project prefix. RSRP uses software dBFS rather than calibrated dBm; SNR uses
dB. Both retain REAL values or `no_value`, and their DU statistics use the
reporting-period average rather than an instantaneous console reading.

The current seven-metric profile uses **100 ms** DU source windows and
subscription reporting/granularity. Both DU configs must use
`metrics.periodicity.du_report_period: 100`; changing the subscription alone
does not produce new source samples. CU identity source/subscriptions stay
at **1000 ms**, Core polls at **1 second**, and source freshness remains
**3 seconds**. Fresh CU/Core context can serve multiple fast DU reports.
New registration/IP association still waits for those independently timed
identity sources; 100 ms reports do not imply 100 ms end-to-end recovery.

The E2 SCTP connector now enables `SCTP_NODELAY`. In the captured deployment it
was unset, allowing Nagle buffering to interact with the 200 ms delayed-SACK
timer. An isolated 100 ms loopback sender reproduced gaps up to 208.09 ms with
NODELAY off, versus 99.85–100.19 ms with it on. This verifies that buffering
mechanism, not the repaired live pipeline. Recheck actual receive spacing and
ordering after restarting CU/DUs and xApp. RIC already enables NODELAY; its
source/plugin ABI is unchanged.

DU snapshot synchronization remains deferred by operator request. The 100 ms
change preserves existing cache publication, E2 receive execution and cleanup
behavior. No concurrent-snapshot guarantee or same-window RF pair is claimed;
the PHY estimator and RF averaging algorithm are unchanged.

The default requires DUs that advertise both RF measurements. For legacy DUs,
`configs/flexric/xapp_ue_identity_five.conf` preserves the original complete
five-DU-measurement **1000 ms** configuration. Select it explicitly with `--du-metrics 5`:

```bash
python3 scripts/ue_identity/xapp_ue_identity.py \
  --du-metrics 5 --observed-unique --duration 60
```

Omitting `--du-metrics`, or passing `--du-metrics 7`, selects the seven-metric
default. There is no automatic downgrade. Both profiles keep the same CU
identity subscriptions, including the existing protocol name
`FALCON.UE.RRCState`, and use the same CU/DU/Core association logic described
above. A mixed deployment with a legacy DU can use the five-metric profile
for a common supported subscription. Custom `--e2-config PATH` remains
supported and cannot be combined explicitly with `--du-metrics`.

The [October 25 100 ms capture](../reports/du_100ms_mixed_rate_experiment_report_2026-10-25.md)
verified approximately 10 reports/s per DU, but exposed burst delivery,
cross-DU identity collisions and a separate PRB-index defect after context
replacement. Original outputs are retained unchanged. Validate the NODELAY
and explicit-scope fixes in a new capture using
[the Spark procedure](../dual_ue_spark_quick_commands.md#7-start-the-dual-ue-identityrf-xapp-and-save-txt-results).
A live legacy-DU subscription remains separate from this new-rate verification.

## Build and offline verification

The October 25 scope/NODELAY correction passes 76 Python and 29 native checks,
including independent APER decoding with duplicate per-DU F1 IDs. Retained
[verification metadata](../evidence/2026-10-25_cu_du_scope_fix/verification.json)
and [SCTP comparison](../evidence/2026-10-25_cu_du_scope_fix/sctp_cadence.json)
are offline evidence; the repaired live capture remains pending.

From Falcon:

```bash
bash scripts/ue_identity/build.sh
python3 -m unittest discover -s tests/ue_identity -v
python3 scripts/ue_identity/xapp_ue_identity.py \
  --replay tests/ue_identity/fixtures/dual_replay.ndjson
python3 scripts/ue_identity/xapp_ue_identity.py \
  --replay tests/ue_identity/fixtures/dual_replay.ndjson --observed-unique
```

The replay is synthetic. Its final experimental rows associate DU1/F1 1007 with
`10.45.0.10` and DU2/F1 2007 with `10.46.0.10`; these are fixture addresses.
Strict replay emits null IPs. Replay starts neither E2 nor HTTP.

The build uses Python 3.10+ standard library, GCC, `patch`, and the existing
FlexRIC headers/static SDK and system libraries (SCTP, libconfig, pthread, dl,
math). Defaults are `/home/nyu/flexric` and its `build-ocudu` tree. Override with
`FLEXRIC_DIR`/`FLEXRIC_BUILD` when using the same pinned layout. The executable is
`/tmp/falcon-xapp-ue-identity`; the optional first build argument changes it.

The pinned KPM plugin rejects valid AMF UE IDs at or above `2^39`: asn1c stores
these positive 40-bit integers with an extra zero sign octet. The retained
[minimal decoder patch](../../patches/flexric/ue_identity_amf_40bit.patch) fixes the
size check and verifies conversion. `build_plugin.py` compiles that one source
and relinks an isolated plugin using the original CMake objects. It preserves
the existing timestamp conversion objects and never writes the FlexRIC tree or
installed plugin. Output is `/tmp/falcon-ue-identity-sm/libkpm_sm.so` plus the
adjacent manifest `/tmp/falcon-ue-identity-sm.manifest.json`. Metadata stays
outside `SM_DIR` because the SDK attempts to load regular files as plugins.
`FALCON_IDENTITY_SM_DIR` changes this directory; update `SM_DIR` in a
copied xApp config to match. Building only a different directory does not change
the config automatically. Existing SDK objects produce executable-stack linker
warnings; this milestone does not rebuild those dependencies.

The codec test decodes synthetic bytes produced by OCUDU's independent ASN.1
encoder through the candidate FlexRIC plugin. It checks large AMF IDs, GUAMI,
F1 IDs, actual state and NTP-to-Unix header conversion, then exercises the Core
join. It skips if the collector/plugin have not been built; require **zero
skips** when recording this validation. Override their paths using
`FALCON_IDENTITY_COLLECTOR` and `FALCON_IDENTITY_PLUGIN`.

Verify the actual SDK parser and plugin-directory loader without sockets:

```bash
/tmp/falcon-xapp-ue-identity --check-config configs/flexric/xapp_ue_identity.conf
/tmp/falcon-xapp-ue-identity --check-config configs/flexric/xapp_ue_identity_five.conf
/tmp/falcon-xapp-ue-identity --check-config configs/flexric/ric_ue_identity.conf
```

From OCUDU:

```bash
cmake --build build --target ocu e2sm_kpm_meas_provider_test \
  cu_cp_metrics_handler_test ngap_test f1ap_cu_test -j4
build/tests/unittests/e2/e2sm_kpm_meas_provider_test
build/tests/unittests/cu_cp/metrics_handler/cu_cp_metrics_handler_test
build/tests/unittests/ngap/ngap_test
build/tests/unittests/f1ap/cu_cp/f1ap_cu_test
build/apps/cu/ocu -c configs/cu.yml \
  -c /home/nyu/Desktop/Falcon_repo/Falcon/configs/ocudu/cu_identity_e2.yml --dryrun
```

`--dryrun` checks parsing/autoderivation and exits before application startup;
it does not establish E2 connectivity or validate a live identity chain.

To regenerate the codec fixture, create a temporary directory and set
`FALCON_IDENTITY_FIXTURE_DIR` to it while running the native `cu_identity.*`
tests. They write `cu_header.asn`/`cu_message.asn`; the retained JSON fixture
stores their bytes as hex. Decode without RIC using:

```bash
/tmp/falcon-xapp-ue-identity --decode-fixture \
  /tmp/falcon-ue-identity-codec/cu_header.asn \
  /tmp/falcon-ue-identity-codec/cu_message.asn \
  /tmp/falcon-ue-identity-sm/libkpm_sm.so
```

The decoder-only mode supplies a synthetic node identity; it proves codec
compatibility, not E2 node registration or a real UE.

## Live setup and run

First verify the existing Core during normal operation:

```bash
python3 scripts/ue_identity/xapp_ue_identity.py --probe-core
```

The current adapter expects paginated `items` plus
`pager: {page, page_size, count}` with count meaning total rows, page starting at
zero and page size 100. AMF items require `supi`, `cm_state: connected` and
`gnb.{gnb_id,amf_ue_ngap_id,ran_ue_ngap_id}`. SMF items require `supi`, `pdu` and
session `psi`, `dnn`, `ipv4`, `pdu_state` (`active` or `inactive`). Other/missing
session states fail validation. Actual deployed schema and pagination semantics
must be verified before using this adapter. Raw API strings in an installed
binary are insufficient evidence.

`configs/ue_identity/local.json` admits PLMN 001/01, gNB 411 with 22 bits and DU
IDs 1/2, DNNs internet/internet2, and AMF GUAMI region 2/set 1/pointer 0. Confirm
these values against the active config. GUAMI scope is an explicit endpoint
configuration, not guessed from a bare AMF UE number. Loopback endpoints require
the same host/network namespace as Core. No Core source or allocation changes
are part of this implementation.

For a candidate deployment, use `configs/flexric/ric_ue_identity.conf` when
starting the existing RIC binary. RIC itself decodes indications before
forwarding, so **RIC and the new xApp must both load the compatible candidate
plugin**. These candidate configs are for a KPM-only testbed; CU and both DUs
must have other service models disabled. A later RC-enabled deployment needs
the matching plugins too. An RIC restart requires controlled CU/DU E2 recovery
under the existing testbed workflow.

```bash
/usr/local/bin/flexric/ric/nearRT-RIC \
  -c /home/nyu/Desktop/Falcon_repo/Falcon/configs/flexric/ric_ue_identity.conf
```

Startup order: existing Core and candidate RIC ready, CU, DU1/DU2, then the new xApp. On the
CU launch, layer `configs/ocudu/cu_identity_e2.yml` after the normal CU config;
it enables CU-CP E2 and identity collection, with CU-UP E2 disabled. The new
metric requires the candidate CU binary. Use the existing DU configurations.
Run the new application only after all intended E2 nodes have registered:

```bash
python3 scripts/ue_identity/xapp_ue_identity.py --duration 60 \
  > /tmp/ue_identity.ndjson 2> /tmp/ue_identity.stderr.log
```

For an explicitly experimental run, add `--observed-unique`. The app enumerates
nodes at startup and logs subscription count. Establishing a new association
requires all admitted DU sources to be current. With `--last-known`, a missing
input for that UE can use labelled historical IP. With `independent_links`,
another DU becoming silent does not interrupt fresh matching on an established
link whose own inputs remain current. It does not dynamically
discover later nodes or automatically recover from RIC restart. Verify the
actual CU and two DU registrations/subscriptions independently. Normal shutdown
deletes successful subscriptions; the coordinator reports a cleanup timeout as
failure. Restarting RAN services is an operator deployment step, separate from
building and running offline checks.

For the staged single-UE1 trial, select
`--config configs/ue_identity/single_ue1.json`: it admits DU1 only and DNN
internet. The dual configuration requires both admitted DUs to be current to
establish a new observed association; historical reuse does not create a
binding that has never been verified.

Add `--capture-events /path/to/new/ingress.ndjson` to retain decoded CU/DU
reports and actual Core poll snapshots before correlation, including ingress
loss notifications. This is decoded input evidence, not a packet capture or
the original ASN.1 wire bytes. The file must not already exist. Recording runs
on the coordinator outside E2 callbacks. Validate the actual CU identities,
DU identifiers and Core session independently against Laptop truth; a matched
output row alone is insufficient live acceptance evidence.

For a readable file containing only the xApp's correlated output, add
`--text-output /path/to/new/bindings.txt`. Each DU record shows the scoped
gNB/DU/F1 UE identity, SUPI, actual AMF and RAN UE NGAP IDs, GUAMI, PDU Session
ID, DNN and IPv4, followed by its KPM metrics and units. It also shows binding
status, reason and assurance. Cached records retain their own previously
verified Core/IP fields, with an explicit history line. Unresolved, ambiguous
and stale records without reusable history retain DU/KPM and show unknown
Core/IP fields; they do not borrow another link's binding.
The UE identifier is explicitly labelled **gNB-CU UE F1AP ID**. The gNB
identifies the CU/gNB scope; no separate numeric CU ID is invented.

```bash
IDENTITY_TXT_RUN=$(mktemp -d /tmp/falcon-identity-txt.XXXXXXXX)
python3 scripts/ue_identity/xapp_ue_identity.py \
  --config configs/ue_identity/single_ue1.json \
  --observed-unique --duration 60 \
  --text-output "$IDENTITY_TXT_RUN/bindings.txt" \
  > "$IDENTITY_TXT_RUN/rows.ndjson" \
  2> "$IDENTITY_TXT_RUN/xapp.log"
```

TXT contains only the xApp's formatted results. SDK startup/subscription logs
stay on stderr; raw Core/CU/DU input snapshots are included only in a separate
`--capture-events` file if requested. NDJSON on stdout remains available with
the same results. The TXT file is created exclusively (existing files cause
an error) and flushed after each record. All writes run on the coordinator,
outside E2 callbacks. Missing KPM values remain `no_value`, measured zero
remains `0`, and incomplete-flag absence is distinct from false. Collection
time is the KPM report header, not a reconstructed per-sample timestamp.

The [actual live TXT trial](../evidence/2026-10-21_ue_identity_live/10_single_ue1_txt_iperf/bindings.txt)
contains 118 records, with 117 consecutive observed matches during a UE1
iperf test. Its first record remains unresolved while waiting for CU identity.
To inspect a completed run using standard Ubuntu tools:

```bash
grep -c '^record=' "$IDENTITY_TXT_RUN/bindings.txt"
grep -c '^record=.*status=matched ' "$IDENTITY_TXT_RUN/bindings.txt"
grep -B 11 -A 2 -m 3 'DRB\.UEThpUl = [1-9]' "$IDENTITY_TXT_RUN/bindings.txt"
```

The final command displays the first three records with UL throughput at
least 1 kbit/s, including their identity fields. For sustained-load validation,
start the existing Spark iperf server, run the xApp for 120 seconds, and
within that window run `iperf3 -c 10.45.0.1 -p 5201 -B 10.45.0.2 -t 60 -i 1`
on the Laptop after confirming its current UE1 IP. Inspect load-period records;
later idle records can legitimately show zero throughput.

## Association and output contract

Core poll results join by normalized IMSI-form SUPI, retaining session/DNN
candidates. The E2 join uses endpoint-scoped GUAMI + gNB + AMF UE NGAP ID and
standard F1 IDs. DU keys include PLMN, gNB, configured bit length, node type,
actual DU ID and F1 ID. Internal UE indices, RNTIs, list order, traffic and DNN
subnets are never used as substitutes for these identities.

Each output DU sample has:

| Field | Meaning |
| --- | --- |
| `schema` | `falcon.ue_identity.experimental.v1`; local diagnostic contract |
| `app_instance`, `sequence` | New UUID per app, increasing output row sequence |
| `node`, `row.ue` | Original DU identity; explicit configured gNB bit length added |
| `row.sample_idx`, `granularity_ms`, `incomplete` | Original measurement metadata; no reconstructed sampling times |
| `row.metrics` | Type/value/no-value preserved; known units added |
| `header_time_us`, `callback_at_us`, `received_at_us`, `emitted_at_us` | Report collection header, C callback, Python ingress and output wall times in Unix microseconds, as decimal strings |
| `binding_status`, `reason`, `ue_ipv4` | matched/cached/unresolved/ambiguous/stale, explanation, nullable IP |
| `binding` when matched or cached | method, experimental assurance, SUPI, canonical AMF and actual RAN UE NGAP IDs, GUAMI tuple `[MCC,MNC,region,set,pointer]`, PDU Session ID and DNN |
| `binding_status: cached` | Historical binding for the same full DU/F1 key; `last_verified_at_us`, monotonic `age_ms`, and `last_verified_assurance` explain its provenance |

Base5 units are delay **0.1 ms**, throughput **kbit/s**, PRB utilization **%**.
Values are never rescaled or replaced by zero. A UE measurement is not a
per-PDU-session or MPTCP-subflow traffic measurement. More than one eligible
Core IP/session remains ambiguous and does not duplicate measurements.

CU/Core relations are cached across different report phases/rates. No pending
DU buffer is implemented in this milestone: early samples are emitted
unresolved immediately and are never retroactively labelled. A sample must
postdate independently observed CU and Core relations. Missing filtered CU
rows do not imply release. Missing/stale sources expire after three seconds;
local expiry uses monotonic time, while header checks require synchronized
wall clocks and the timestamp-compatible plugin. The initial implementation
assumes the same lab clock domain.

HTTP runs outside E2 callbacks: 0.5-second I/O timeout, two-second checked cycle
budget, maximum 2 MiB/response, 16 pages, 256 UE rows and eight sessions per UE.
Sequential pages/queries share a deadline; it is checked before requests and
after reads, rather than being a real-time thread cancellation guarantee.
Both Core halves must validate before replacing cache state. Their reads are
not an atomic cross-NF transaction; the poller retains query timing in its
internal event. Core errors immediately prevent fresh verification; the
last-known policy may continue publishing an explicitly historical binding.

### Real-time output with historical binding

The operator selected real-time output and labelled history reuse. Cache keys
include admitted PLMN/gNB/node type/DU and F1 ID. They are memory-only and are
never filled from an IP subnet, a different UE, or a previous process. A
previously verified link matches independently while its own CU/Core inputs
are fresh. Stale own CU/Core inputs or a Core request error can use labelled
IP history. Raw KPM values and metadata remain unchanged.

A successful complete Core snapshot removes a historical entry if its current
connected NGAP context or unique SUPI/session/IP relation no longer agrees.
RRC idle retires that radio binding; an inactive SMF PDU alone retains its IP.
The radio association and historical IP are separate: a current IP/session
update invalidates the old cached IP but can use the unchanged radio scope to
match the new current IP when that UE's CU/Core inputs are fresh.
Explicit CU unavailability, a changed F1 list, known F1 reuse/conflict, or ingress
loss also prevent reuse. A late measurement older than the confirmed binding
does not borrow a later relation. History is not aged out solely because
another DU stops reporting. During an unobserved outage a cached relation can
have changed; consumers must read its status and age rather than treat it as
fresh. Lifecycle proof and automatic source restart recovery remain open.

Run manually using the same RAN/Core processes:

```bash
IDENTITY_HISTORY_RUN=$(mktemp -d /tmp/falcon-identity-history.XXXXXXXX)
python3 scripts/ue_identity/xapp_ue_identity.py \
  --config configs/ue_identity/local.json \
  --observed-unique --last-known --duration 360 \
  --text-output "$IDENTITY_HISTORY_RUN/bindings.txt" \
  --capture-events "$IDENTITY_HISTORY_RUN/inputs.ndjson" \
  > "$IDENTITY_HISTORY_RUN/rows.ndjson" \
  2> "$IDENTITY_HISTORY_RUN/xapp.log"
```

Repeat the operator's UE1 300-second and UE2 20-second / quiet 150-second /
30-second clients while this foreground capture runs. After completion:

```bash
grep -c '^record=.*status=matched ' "$IDENTITY_HISTORY_RUN/bindings.txt"
grep -c '^record=.*status=cached ' "$IDENTITY_HISTORY_RUN/bindings.txt"
grep -B 7 -A 8 -m 1 'validity=last_known_unverified' "$IDENTITY_HISTORY_RUN/bindings.txt"
```

Acceptance: previously associated UE1 rows during UE2 silence retain the same
DU/F1/NGAP/SUPI/IP with `matched` status while UE1's own CU/Core inputs remain
fresh. `cached` is reserved for missing verification inputs of that UE. A new
or retired context must not inherit an old binding. Cold-start/new-context rows
without any verified history can still have unknown IP: real-time output cannot
recover identity information that has not arrived. Using `--fresh-only`
disables history, including when the local JSON enables it.

The [independent-link regression](../evidence/2026-10-21_ue_identity_live/15_independent_links_replay/comparison.json)
checks the previous real 637-row trace: 581 original bindings remain unchanged,
29 UE1 rows now match using fresh own CU/Core inputs and their established
DU/F1 scope, and 27 rows lack an initial established scope or CU identity.
Both fresh-only and last-known give 610 matched, 0 cached, 27 unresolved for
this trace. Raw-source checks on the additional 29 matches confirm CU age at
most 999,105 us and Core age at most 966,709 us. This is a file-only check,
not a new live acceptance. The
[earlier history-only regression](../evidence/2026-10-21_ue_identity_live/14_last_known_policy_replay/comparison.json)
retains its archived configuration without independent-link matching; its 29
cached rows describe the superseded intermediate policy.

Initial scope establishment still uses all admitted DU observations because
the CU standard UEID lacks explicit per-UE serving-DU/generation transport.
The change decouples established links; it does not manufacture a first radio
association or close the strict lifecycle gate. Sources that share an actual
identity conflict or ingress loss may still invalidate multiple links.

The C ingress queue is bounded to 16 serialized reports/4 MiB. The coordinator
queue holds at most 256 serialized events/4 MiB. Decoding/serialization also
has explicit per-report bounds. Identity/history caches are bounded to 256
keys and four observed identities per F1 ID. Overflow/loss invalidates mapping
confidence instead of evicting history and reusing an uncertain key. Long runs
with many context changes may therefore need a controlled restart.

## Six-minute bidirectional idle/resume test

Developer: Ruibin Chen. This operator-run procedure checks both
UE1 idle / UE2 active and UE2 idle / UE1 active in
one 360-second xApp instance. Existing Core, RIC, CU, DUs, and PDU sessions stay
running. Only the test traffic pauses. CU's current default inactivity timer
is 120 seconds (`cu_cp_unit_config.h`); the CU base/identity overlay do not
override it. Each role therefore gets 150 seconds without generated traffic.
Core must actually report idle; stopping iperf alone does not prove idle.

The first [real bidirectional run](../reports/ue_identity_dual_ue_live_2026-10-21.md#live-six-minute-bidirectional-idleresume-validation)
passes independent current matching: 645 matched / 648 total, three own
startup/resume boundary records, and zero cached. Each UE's observed Core idle
interval lasts about 30 seconds while its peer has 30 consecutive matched
positive-UL records. This is one live round per UE, not closure of all Plan 4
strict lifecycle/recovery gates. The steps below remain reusable for repetition.

The inline Laptop command below reuses `~/falcon-dual-ul.py` from the Laptop Quick Start to rediscover the
current IMEI/SIM/bearer/IP/interface/routes. It never hardcodes the old bearer
index or `.2` address. The parent waits for all four owned iperf clients and
cleans them up on failure or interruption. No assistant-launched processes
are required. The operator pastes the command explicitly; no new script file or transfer is used.

Times below are relative to the Laptop launcher's traffic start, not Spark's
clock. Quiet periods begin after each first client actually exits; final
transfer/connection overhead can shift boundaries slightly.

| Nominal seconds | UE1 | UE2 | What to verify |
| --- | --- | --- | --- |
| 0–15 | UL | UL | Both initial identity chains are established. |
| 15–165 | Quiet 150 s | Same uninterrupted UL connection | UE1 reaches Core idle; UE2 stays currently matched. |
| 165–175 | Resumed UL | Same UL connection | UE1 matches its actual resumed context. |
| 175–325 | Same uninterrupted UL connection | Quiet 150 s | UE2 reaches Core idle; UE1 stays currently matched. |
| 325–335 | Same UL connection | Resumed UL | UE2 matches its actual resumed context. |

UE1 clients run for 15 and 170 seconds; UE2 clients for 175 and 10 seconds.
Each UE's quiet interval is 150 seconds measured on Laptop's monotonic clock.
The nominal traffic schedule is 335 seconds, leaving about 25 seconds within
the 360-second Spark capture for switching terminals and process overhead.
Start the prepared Laptop launcher within ten seconds of starting xApp.
The command aborts if a client exceeds its requested duration by five seconds
or the complete traffic run exceeds 345 seconds. An overrun or a capture
missing the last resume phase is not accepted as a complete six-minute test.

1. Keep both Spark iperf servers in separate foreground terminals. Reuse them
   if already listening; otherwise start each manually:

   ```bash
   iperf3 -s -B 10.45.0.1 -p 5201
   ```

   ```bash
   iperf3 -s -B 10.46.0.1 -p 5202
   ```

2. Close other iperf clients, periodic ping, modem test traffic and applications
   using the WWAN paths. Keep management traffic on the management network.
   Do not disconnect bearers or toggle modem power. The existing
   `~/falcon-dual-ul.py` Quick Start helper is reused as installed previously.

3. Paste this command directly into the Laptop terminal. It creates test logs,
   not a script file. Leave it at `READY` while starting the Spark capture:

   ```bash
   python3 - <<'PY'
   import importlib.util, json, signal, subprocess, tempfile, threading, time
   from concurrent.futures import ThreadPoolExecutor, as_completed
   from datetime import datetime
   from pathlib import Path
   from zoneinfo import ZoneInfo
   
   spec = importlib.util.spec_from_file_location('ue_helper', Path.home() / 'falcon-dual-ul.py')
   helper = importlib.util.module_from_spec(spec)
   spec.loader.exec_module(helper)
   roles = helper.discover_roles()
   helper.verify_routes(roles)
   assert len(roles) == 2 and {r['ue'] for r in roles} == {1, 2}
   for r in roles:
       print(f"UE{r['ue']}: IMSI={r['imsi']} IP={r['source']} dev={r['interface']} -> {r['server']}:{r['port']}", flush=True)
   print('READY: 启动 Spark 的360秒xApp，然后在10秒内回这里输入 START 并回车。', flush=True)
   with open('/dev/tty') as tty:
       while True:
           line = tty.readline()
           if not line:
               raise SystemExit('终端已关闭')
           if line.strip() == 'START':
               break
   assert helper.discover_roles() == roles, 'Bearer已变化，请重新检查'
   helper.verify_routes(roles)
   
   out = Path(tempfile.mkdtemp(prefix='falcon-dual-idle-'))
   (out / 'truth.json').write_text(json.dumps(roles, indent=2) + '\n')
   started = time.monotonic()
   lock, stop, jobs = threading.Lock(), threading.Event(), []
   stamp = lambda: datetime.now(ZoneInfo('America/New_York')).isoformat()
   events = (out / 'events.ndjson').open('w')
   print('Evidence:', out, 'START:', stamp(), flush=True)
   
   def event(kind, **fields):
       with lock:
           item = dict(event=kind, time_edt=stamp(), elapsed_s=round(time.monotonic()-started, 3), **fields)
           events.write(json.dumps(item) + '\n'); events.flush()
           print(item, flush=True)
   
   def flow(r, before, after):
       for phase, seconds in (('before', before), ('after', after)):
           if phase == 'after':
               event('quiet_started', ue=r['ue'], seconds=150)
               quiet_start = time.monotonic()
               if stop.wait(150):
                   return
               event('quiet_finished', ue=r['ue'], actual_seconds=round(time.monotonic()-quiet_start, 3))
           log = out / f"ue{r['ue']}_{phase}.log"
           with lock:
               if stop.is_set():
                   return
               stream = log.open('w')
               try:
                   proc = subprocess.Popen(['iperf3', '-c', r['server'], '-p', str(r['port']),
                       '-B', r['source'], '-t', str(seconds), '-i', '1', '--get-server-output'],
                       stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
               except BaseException:
                   stream.close()
                   raise
               job = dict(ue=r['ue'], phase=phase, seconds=seconds, log=str(log), started_at=stamp())
               jobs.append((proc, stream, job))
           event('iperf_started', ue=r['ue'], phase=phase, seconds=seconds)
           try:
               rc = proc.wait(timeout=seconds+5)
           finally:
               stream.close()
           job.update(exit_code=rc, ended_at=stamp())
           event('iperf_finished', ue=r['ue'], phase=phase, exit_code=rc)
           if rc:
               raise RuntimeError(f"UE{r['ue']} {phase} exit={rc}; log={log}")
   
   def halt(*_):
       raise KeyboardInterrupt
   signal.signal(signal.SIGTERM, halt)
   pool = ThreadPoolExecutor(max_workers=2)
   status, error = 'completed', None
   try:
       futures = [pool.submit(flow, r, *( (15, 170) if r['ue'] == 1 else (175, 10) )) for r in roles]
       for future in as_completed(futures, timeout=345):
           future.result()
   except (Exception, KeyboardInterrupt) as exc:
       status, error = 'failed', str(exc) or type(exc).__name__
   finally:
       stop.set()
       with lock:
           owned = list(jobs)
       for proc, _, _ in owned:
           if proc.poll() is None:
               proc.terminate()
       for proc, _, job in owned:
           try:
               proc.wait(timeout=3)
           except subprocess.TimeoutExpired:
               proc.kill(); proc.wait()
           job.update(exit_code=proc.returncode)
       pool.shutdown(wait=True)
       summary = dict(status=status, error=error, elapsed_seconds=round(time.monotonic()-started, 3),
                      links=roles, jobs=[job for _, _, job in jobs], ended_at=stamp())
       (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
       events.close()
       for _, _, job in jobs:
           print(f"UE{job['ue']} {job['phase']} exit={job['exit_code']}")
           for line in Path(job['log']).read_text(errors='replace').splitlines():
               if any(word in line for word in ('sender', 'receiver', 'iperf Done', 'error')):
                   print(line)
       print('STATUS:', status, 'ERROR:', error, 'Evidence:', out, flush=True)
   raise SystemExit(0 if status == 'completed' else 1)
   PY
   ```

   `/dev/tty` receives the start instruction because Python's standard input
   contains the pasted heredoc. No iperf starts until `START` is entered.

4. On Spark, manually start a new xApp capture. The local config enables
   independent established-link matching. This test explicitly uses
   `--fresh-only` to verify current association, with no historical IP fallback
   in this process; the configured normal last-known policy is unchanged.

   ```bash
   cd /home/nyu/Desktop/Falcon_repo/Falcon
   IDENTITY_BIDIR_RUN=$(mktemp -d /tmp/falcon-identity-bidir.XXXXXXXX)
   printf 'Spark采集目录：%s\n' "$IDENTITY_BIDIR_RUN"
   cp configs/ue_identity/local.json "$IDENTITY_BIDIR_RUN/local.json"
   sha256sum scripts/ue_identity/mapping.py scripts/ue_identity/xapp_ue_identity.py \
     configs/ue_identity/local.json > "$IDENTITY_BIDIR_RUN/source-sha256.txt"
   python3 scripts/ue_identity/xapp_ue_identity.py \
     --config configs/ue_identity/local.json \
     --observed-unique --fresh-only --duration 360 \
     --text-output "$IDENTITY_BIDIR_RUN/bindings.txt" \
     --capture-events "$IDENTITY_BIDIR_RUN/inputs.ndjson" \
     > "$IDENTITY_BIDIR_RUN/rows.ndjson" \
     2> "$IDENTITY_BIDIR_RUN/xapp.log"
   IDENTITY_BIDIR_RC=$?
   printf 'xApp exit=%s\n' "$IDENTITY_BIDIR_RC"
   ```

5. Within ten seconds, return to Laptop, type `START` and press Enter. Do not manually
   change traffic phases. The launcher prints each start/stop/quiet transition
   and every client exit. Let the whole six-minute Spark capture finish.

6. On Spark, inspect the completed capture:

   ```bash
   grep -E 'Registered E2 Nodes|identity collector:|Sucessfully stopped' "$IDENTITY_BIDIR_RUN/xapp.log"
   python3 - "$IDENTITY_BIDIR_RUN" <<'PY'
   from collections import Counter
   from datetime import datetime, timezone
   import json
   from pathlib import Path
   import sys
   from zoneinfo import ZoneInfo

   root = Path(sys.argv[1])
   rows = [json.loads(line) for line in (root / 'rows.ndjson').open()]
   for du in ('1', '2'):
       selected = [row for row in rows if row['node']['du_id'] == du]
       print('DU' + du, dict(Counter(row['binding_status'] for row in selected)))
       print('matched identities:', sorted({
           (row['row']['ue']['gnb_cu_ue_f1ap_id'], row['binding']['amf_ue_ngap_id'],
            row['binding']['ran_ue_ngap_id'], row['ue_ipv4'])
           for row in selected if row['binding_status'] == 'matched'}))
   previous = {}
   for line in (root / 'inputs.ndjson').open():
       event = json.loads(line)
       if event['kind'] != 'core_snapshot':
           continue
       for ue in event['amf']:
           state = (ue['cm_state'], ue['gnb'].get('amf_ue_ngap_id'), ue['gnb'].get('ran_ue_ngap_id'))
           if previous.get(ue['supi']) != state:
               stamp = datetime.fromtimestamp(int(event['received_at_us']) / 1e6, timezone.utc).astimezone(ZoneInfo('America/New_York'))
               print(stamp.isoformat(), ue['supi'], state)
               previous[ue['supi']] = state
   PY
   ```

### Acceptance for this run

- Capture one app instance for 360 seconds, three intended E2 nodes and
  subscriptions, all deletion responses, xApp exit 0, and no reported ingress
  loss/Core errors. Retain every original KPM row.
- Both UE identity chains must be established before their tested idle
  transitions. Require at least five consecutive matched samples per UE in
  initial connected operation.
- Core must show each UE moving connected -> idle -> connected within the
  capture, with its PDU/session/IP retained during ordinary idle. Target at
  least one ten-second observed idle interval per UE. If only UE2 reaches
  idle, the UE1 gate is not tested; no test result may infer idle from sleep.
- For each idle interval, examine the other UE's records after the idle DU
  stops being current. Require at least ten consecutive peer rows with fresh
  own CU/Core inputs, correct IP/DU/F1/NGAP/SUPI and `matched` status. Any peer
  rejection caused solely by the silent DU fails independence acceptance.
  Count and explain all other unresolved/stale/ambiguous windows too.
- On each resume, use actual Core/CU identities, not expected numeric IDs or
  the old F1 context. Require at least five consecutive current matches and
  zero observed cross-UE assignment. Measure convergence from the later fresh
  matching CU/Core prerequisite; initial target is three reporting periods
  under healthy complete inputs. Short initial unbound rows of the resuming
  UE may occur before that information arrives; the active peer must remain
  unaffected. An IP change is investigated rather than filled from history.
- All four Laptop clients must exit 0 and report receiver results. The
  launcher summary is `completed`. Report any zero-throughput intervals on
  the continuing connection; exit 0 alone does not prove stall-free traffic.

Keep Spark `inputs.ndjson`, `rows.ndjson`, `bindings.txt`, `xapp.log`, and the
effective config/source revision. Laptop retains `truth.json`, `events.ndjson`, four client logs and `summary.json` under the printed
`/tmp/falcon-dual-idle-*` path. Paste the Spark capture directory/xApp exit and
Laptop's four client results, final `STATUS` and evidence directory for audit.
Spark's Core/CU/DU timestamps determine idle and matching boundaries. Laptop
phase times are in its own clock domain; cross-host wall-clock alignment is
still unverified and must not be assumed from matching printed times.

## Evidence and remaining validation

See the [implementation record](../reports/ue_identity_implementation_2026-10-21.md)
for commands and baselines, and the
[single-UE live report](../reports/ue_identity_single_ue1_live_2026-10-21.md)
for real Core schema, CU/DU E2, Laptop path and sustained-UL evidence. The
single-UE experimental association passed with 57/58 then 117/118 matched
rows; each initial row remained unresolved during subscription warmup.
The subsequent [dual-UE live report](../reports/ue_identity_dual_ue_live_2026-10-21.md)
records three subscriptions, 223 DU samples, 221 correct observed matches and
two initial unresolved samples. Both concurrent iperf clients exit 0, receiver
13.2/11.9 Mbit/s. An independent raw-input audit checks all matched Core/CU/DU
chains and lab NCIs, all original metric payloads and the live TXT.
Corrective live serving-DU verification, shared lifecycle transport, transitions/recovery, clock alignment
and repeated comparative performance acceptance remain pending.

Rollback for a later deployed trial: stop the independent app, restore the
previous CU binary/config and remove the candidate overlay, then run the
accepted DU-only monitor. The installed FlexRIC plugin and Core policies were
not replaced by this build. Preserve the accepted timestamp and RF fixes.
