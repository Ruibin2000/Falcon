# UE1 live CU/DU/Core association: October 21, 2026

> Publication: This report and its selected figures are versioned. Detailed
> captures, logs and per-sample data remain in the local evidence archive.
> References marked `local archive` and captured-data reanalysis commands
> require that archive separately. See the [publication policy](../README.md#local-archive-policy).

> Historical scope: this record retains its dated implementation, test
> configuration and results. The [current two-link design](../../project_design_and_progress.md)
> defines DU1 3660 MHz / 20 MHz, DU2 3600-MHz n78 interface / 40 MHz, and
> the designed Pi-Radio 9250-MHz OTA path. Those later radio changes are
> outside this record's validation.

Developer: Ruibin Chen. Branch: Dual-UE in Falcon and OCUDU.

The real single-UE observational association passed: 57 consecutive DU1 rows
were associated with UE1 IPv4 `10.45.0.2` using actual CU E2 identities and
actual AMF/SMF snapshots. One initial DU row remained unresolved because it
arrived before the first CU identity. Both subscriptions were deleted normally
and the operator reported process exit 0. This result covers the explicitly
experimental `observed_unique_current_context` capability. Strict serving-DU
transport, dual UE and transitions remain open. The subsequent sustained-UL
trial below also demonstrates real throughput/PRB response; repeated
performance/regression acceptance remains pending.

## Setup and independent UE path

Spark ran the existing ten SA Core services, candidate RIC plugin/config,
candidate CU with the identity overlay, and the accepted DU1 binary. RIC
registered CU gNB 411 and gNB-DU 411/DU ID 1. DU1 used B210 serial 3271233 over
USB 3, PCI 1, carrier ARFCN 644000 and SSB ARFCN 643680. UE2/DU2 were not
included in the trial's admitted source scope.

The operator's Laptop output independently records bearer 1 connected and
not suspended, APN internet, IPv4 `10.45.0.2/30`, gateway `10.45.0.1`, wwan0 and
MTU 1400. Its source-bound route selects table 151/wwan0; ping receives 5/5
replies. See the Laptop path record (local archive: `../evidence/2026-10-21_ue_identity_live/06_laptop_ue1_path.json`).
This check demonstrates the single-UE host path; it is not a throughput test.

## Actual capture

Source directory: `/tmp/falcon-identity-ue1.bTQEUzlq`.
App instance: `81a6fb38-1880-48ef-b9f0-de2939cb63de`.
DU header window: 20:46:52.644656–20:47:49.644165 UTC, October 21, 2026.

```bash
python3 scripts/ue_identity/xapp_ue_identity.py \
  --config configs/ue_identity/single_ue1.json \
  --capture-events "$IDENTITY_XAPP_RUN/inputs.ndjson" \
  --observed-unique --duration 60 \
  > "$IDENTITY_XAPP_RUN/rows.ndjson" \
  2> "$IDENTITY_XAPP_RUN/xapp.log"
```

The retained files are decoded live inputs/output, not replay fixtures or a
packet capture. Their hashes/config snapshots are in the
capture summary (local archive: `../evidence/2026-10-21_ue_identity_live/07_single_ue1_xapp/summary.json`).

| Observation | Actual result |
| --- | --- |
| Registered E2 nodes | 2: CU and DU1 |
| Successful KPM subscriptions | 2 |
| Core snapshots | 60 |
| CU Format 3 indications | 57, with standard gNB UEID and real RRC state 1 |
| DU1 indications/output rows | 58 / 58 |
| Matched output rows | 57 consecutive |
| Unresolved output rows | 1 initial row: CU identity missing |
| Ambiguous/stale rows | 0 / 0 |
| Reported C ingress drops | 0 |
| Core-error/ingress-loss events | 0 |
| Subscription deletion responses | 2 |
| Operator-reported exit | 0 |

Different CU/DU counts are retained rather than paired by list order. Their
phases and shutdown boundaries differ. The first DU report arrives before the
first CU report and remains unresolved; later rows use the cached identity.

## Identity chain observed during this run

| Source | Actual relation |
| --- | --- |
| Laptop bearer/route | UE1 host IPv4 10.45.0.2, wwan0/table 151 |
| SMF | SUPI imsi-001010000000101, active PDU Session 1, DNN internet, IPv4 10.45.0.2 |
| AMF | Same SUPI, connected/registered, gNB 411, AMF UE NGAP ID 14, RAN UE NGAP ID 13, NCI 6733824 |
| CU E2 | AMF UE NGAP ID 14, GUAMI 001/01 + region 2/set 1/pointer 0, F1 list [14], RRC state 1 |
| DU1 E2 | PLMN 001/01, gNB 411, DU ID 1, gNB-CU UE F1AP ID 14 |
| Output | IP 10.45.0.2, method core_infoapi_cu_e2, assurance observed_unique_current_context |

Earlier Core/CU probes in this session contained AMF/RAN/F1 IDs 6/5/5. The
new IDs above come from the actual capture after context changes. IP and SUPI
persisted; those earlier radio IDs were not hard-coded into the matcher. Equal
numeric AMF and F1 IDs in this capture are separate typed fields joined through
CU reporting, not an assumption that the identifier namespaces are identical.

An independent inspection of the retained decoded inputs checks each matched
row against the preceding CU identity and Core snapshot, the admitted DU,
freshness, the SMF session and Laptop IP. It finds no inconsistencies. All 58
output metric payloads retain their corresponding DU type/value unchanged;
known units are added separately. No claim is made about completeness of the
filtered CU UE inventory or attribution across unobserved identifier reuse.

## Metrics and remaining load check

Every DU row contains the five requested metrics. Actual values include:

| Metric | Last captured value | Unit |
| --- | --- | --- |
| DRB.RlcSduDelayDl | 22.200000762939453 | 0.1 ms |
| DRB.UEThpDl | 0 | kbit/s |
| DRB.UEThpUl | 0 | kbit/s |
| RRU.PrbTotDl | 0 | % |
| RRU.PrbTotUl | 0 | % |

Delay is nonzero in all 58 rows; throughput and PRB are zero throughout this
capture. The operator's earlier five-packet ping proves connectivity, but a
sustained bulk-UL interval overlapping this capture is not established. These
zeros therefore leave traffic-metric response and performance validation open.
The subsequent trial below performs the sustained-load check.

## Follow-up: real UE1 TCP uplink and KPM response

Source directory: `/tmp/falcon-identity-ue1-ul.wmlsSfno`.
App instance: `2975a93a-3690-4155-b6d8-f685abb43580`.
The same single-UE experimental configuration ran for 120 seconds while the
Laptop ran a source-bound 60-second TCP UL to 10.45.0.1:5201.

The actual Spark server accepted peer 10.45.0.2 and reports **99.2 MiB over
60.29 seconds, receiver goodput 13.8 Mbit/s**. The operator reports iperf exit
0. Sender retransmissions were not supplied and are not assumed to be zero.

| Observation | Actual result |
| --- | --- |
| Core snapshots | 120: initial AMF idle, then 119 connected snapshots |
| CU / DU1 indications | 117 / 118 |
| Output rows | 118 |
| Matched rows | 117 consecutive, all IP 10.45.0.2 |
| Initial unresolved | 1, CU identity missing |
| Consecutive matched rows with positive UL throughput | 60 |
| Nonzero UL throughput / UL PRB rows | 61 / 61, including the initial unresolved row |
| UL throughput positive-row arithmetic mean | 14696.836 kbit/s, approximately 14.70 Mbit/s |
| UL throughput maximum | 20970 kbit/s, 20.97 Mbit/s |
| UL PRB positive-row mean / maximum | 82.44% / 86% |
| Core errors / ingress-loss events / reported drops | 0 / 0 / 0 |
| Deletion responses / operator-reported xApp exit | 2 / 0 |

The independently checked live chain uses AMF UE NGAP ID 15, RAN UE NGAP ID
14, standard CU F1 list [15] and DU1 F1 ID 15. The IP remains 10.45.0.2.
Context IDs changed between app instances; this does not establish handling
of identifier reuse or handover within one running instance.

UL throughput and UL PRB are nonzero from header time 20:53:16.228852 through
20:54:16.229488 UTC; later rows return zero. DL throughput also responds
(maximum 338 kbit/s); DL PRB reaches 5%. Delay has 61 numeric rows and 57 later
no-value rows. Original DU type/value/no-value states are preserved in every
output row. RLC throughput and TCP receiver goodput have different measurement
definitions/windows and are reported separately.

The first Core snapshot has cm_state idle and no current NGAP IDs, while SMF
retains the inactive PDU/IP. It does not become a claimed current radio mapping.
Later connected snapshots and actual CU identities enable the observed
association. A standalone analysis initially tried reading a RAN ID from every
snapshot; the analysis was corrected to respect idle/missing contexts. The
running xApp already handled this state and did not fail.

Timing is evaluated in the Spark clock domain. DU header coverage is
20:53:16.228852–20:55:13.229214 UTC. The single completed server log's last write
is 20:54:14.998629 UTC; subtracting its 60.29-second duration gives an
approximate stream start of 20:53:14.708629 UTC. This filesystem marker is an
approximation, not packet-level timing. The operator's Laptop end is recorded
as 20:50:55 UTC, so direct cross-host timestamp alignment is not established.
Initial subscription warmup is retained; exact per-second correlation or
independent clock synchronization is not claimed.

- Actual iperf server log (local archive: `../evidence/2026-10-21_ue_identity_live/08_single_ue1_ul/iperf_server.log`)
- Decoded live inputs (local archive: `../evidence/2026-10-21_ue_identity_live/08_single_ue1_ul/inputs.ndjson`)
- Associated DU rows (local archive: `../evidence/2026-10-21_ue_identity_live/08_single_ue1_ul/rows.ndjson`)
- Subscription/deletion log (local archive: `../evidence/2026-10-21_ue_identity_live/08_single_ue1_ul/xapp.log`)
- Counts, metric statistics, timing and independent audit (local archive: `../evidence/2026-10-21_ue_identity_live/08_single_ue1_ul/summary.json`)

## Retained evidence

### Readable xApp output

The xApp now supports `--text-output PATH`, a separate TXT containing only
the application's correlated records. Each record lists scoped gNB/DU/F1
identity, SUPI, actual AMF/RAN UE NGAP IDs, GUAMI, PDU session, DNN and IPv4,
followed by the original KPM types, values and units. Binding status, reason
and experimental assurance remain explicit. SDK logs and raw Core/CU/DU
events do not enter this file. The JSON binding also now retains SUPI and
the actual AMF-reported RAN ID; it never derives these from F1 ID equality.
Changing the RAN context resets the independently observed Core boundary.

The readable UE1 UL report (local archive: `../evidence/2026-10-21_ue_identity_live/09_xapp_text_output/ue1_ul_from_capture.txt`)
was regenerated from this trial's retained actual input events, not from
synthetic fixtures. All 118 rows retain their original status, DU identity,
collection/ingress timestamps and KPM type/value/unit. The 117 matches show
SUPI imsi-001010000000101 and actual RAN UE NGAP ID 14; the initial unresolved
record retains unknown Core/IP fields. Its header explicitly labels it as a
captured-input replay; this is a readable rendering of existing evidence,
not a new live radio acceptance run. A new app UUID/output time is expected.
See the output validation record (local archive: `../evidence/2026-10-21_ue_identity_live/09_xapp_text_output/validation.json`).

A separate 20-second real TXT attempt in
`/tmp/falcon-identity-txt.LMhzyxzK` completed with process exit 0 and normal
deletion of two subscriptions. AMF remained idle, no CU/DU UE records arrived,
and Spark's ten downlink pings received no reply. No binding was fabricated;
this attempt does not validate live TXT rows. The subsequent Laptop-driven
iperf run below supplies the missing live TXT evidence.
The Python/codec/output suite passes 34 checks, including missing/zero values,
withholding Core fields on uncertain records, actual typed NGAP IDs, RAN
context changes and exclusive output-file creation.

### Follow-up: actual live TXT during UE1 iperf uplink

The operator ran the new xApp with `--text-output`, `--observed-unique` and
120-second duration while generating a 60-second source-bound TCP uplink.
This run wrote the application's readable results directly; it was not a
replay. Stdout was discarded as requested; SDK logs stayed in `xapp.log`.
Source: `/tmp/falcon-identity-iperf.dbpfozm0`. App instance:
`5d0487ed-f256-4bb2-b810-5d91ef18aa69`. The DU header window was
21:12:42.745822–21:14:39.746048 UTC (17:12:42–17:14:39 America/New_York).

| Observation | Actual result |
| --- | --- |
| TXT records | 118 |
| Matched | 117 consecutive, sequences 2–118 |
| Initial unresolved | Sequence 1: CU identity missing; Core/IP fields unknown |
| Ambiguous / stale | 0 / 0 |
| Identity on every matched record | gNB 411/22 bits, DU1, F1 UE ID 22, SUPI imsi-001010000000101, AMF UE NGAP ID 22, RAN UE NGAP ID 21 |
| Session on every matched record | PDU 1, DNN internet, IPv4 10.45.0.2 |
| Nonzero UL KPM records | 62, all matched |
| Positive-row UL mean / peak | 21147.484 / 24240 kbit/s |
| Peak UL PRB | 88% |
| iperf server | Peer 10.45.0.2, 149 MBytes over 60.21 seconds, receiver 20.7 Mbit/s |
| Registered nodes / successful subscriptions / deletion responses | 2 / 2 / 2 |

The file contains all five KPM metrics with their expected units on every
record, and no SDK log or raw Core snapshots. `no_value` remains explicit.
The startup record was not retrospectively labelled. The SDK reports normal
stop after deleting both subscriptions; the Python process exit code was not
included in the operator's pasted result. TCP receiver goodput and RLC KPM
throughput retain their separate definitions/windows. No sender retransmission
result was supplied.

This run validates real single-UE TXT generation, observed identity binding
and uplink metric response. No raw ingress or JSON output was requested for
this run, so the audit checks the rendered bindings and metrics rather than
independently reconstructing its Core/CU inputs. Earlier captured-input trials
above provide that separate evidence. Strict serving-DU transport, dual UE,
transitions and recovery remain open; the assurance remains
`observed_unique_current_context`.

- Actual live xApp TXT (local archive: `../evidence/2026-10-21_ue_identity_live/10_single_ue1_txt_iperf/bindings.txt`)
- SDK subscription/deletion log (local archive: `../evidence/2026-10-21_ue_identity_live/10_single_ue1_txt_iperf/xapp.log`)
- Corresponding iperf server trial (local archive: `../evidence/2026-10-21_ue_identity_live/10_single_ue1_txt_iperf/iperf_server_trial2.log`)
- Counts, identity checks, statistics and hashes (local archive: `../evidence/2026-10-21_ue_identity_live/10_single_ue1_txt_iperf/summary.json`)

- Decoded live inputs (local archive: `../evidence/2026-10-21_ue_identity_live/07_single_ue1_xapp/inputs.ndjson`)
- Associated DU rows (local archive: `../evidence/2026-10-21_ue_identity_live/07_single_ue1_xapp/rows.ndjson`)
- SDK subscription/deletion log (local archive: `../evidence/2026-10-21_ue_identity_live/07_single_ue1_xapp/xapp.log`)
- Counts, hashes and independent audit summary (local archive: `../evidence/2026-10-21_ue_identity_live/07_single_ue1_xapp/summary.json`)
- [Plan 4](../../../plans/cu-ue-ip-e2-binding.md) and [standalone runbook](../../reference/ue_identity_xapp.md)

These single-UE trials supply real association and UL metric-response evidence.
They do not close the strict DU/lifecycle wire gap or replace dual-UE, recovery and
performance acceptance. Plan 2/MPX integration remains deferred.
