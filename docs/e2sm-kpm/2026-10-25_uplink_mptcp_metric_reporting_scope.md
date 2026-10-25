# E2SM Metrics for Uplink MPTCP Video

The video data direction is Laptop to Spark. Use per-UE uplink radio quality,
reliability, power margin, backlog, and delivered service as the main radio
inputs to MPTCP decisions on the Laptop. Retain selected downlink measurements
because acknowledgments and uplink scheduling depend on downlink delivery.
DL CQI describes downlink data-channel quality; it does not directly measure
PDCCH reliability or uplink capacity.

This October 25, 2026 inventory separates the existing subscription, proposed
extensions, and information to obtain outside E2SM-KPM. It narrows the initial
application profile from the broader
[DU metric inventory](2026-10-24_du_metric_expansion_and_reporting_periods.md).
The existing implementation plans and compatibility profile are unchanged.

## Existing subscription and its validation status

Falcon's [seven-metric configuration](../../configs/flexric/xapp_du_rf_metrics.conf)
requests the following measurements at 1000 ms. These are implemented and
configured measurements, not a claim that seven populated measurements are
currently arriving. The retained
[October 23 live review](2026-10-23_du_rf_metrics_step8_operator_log_review.md)
confirmed subscription admission but contained no decoded measurement rows.
The RF source, encoding, and decoder have offline validation; continuous live
values, accuracy, and application forwarding remain separate work.

| Measurement | Source and actual meaning | Use for uplink video |
| --- | --- | --- |
| `FALCON.PUSCH.SNR.dB` | Scheduler `pusch_snr_db`, with `nof_pusch_snr_reports` for validity. Arithmetic mean of available PHY-selected `ul_sinr_dB` samples in the source window. | Primary UL quality input. |
| `FALCON.PUSCH.RSRP.dBFS` | Scheduler `pusch_rsrp_db`. Arithmetic mean of available PUSCH DM-RS power observations in software dBFS. | Supporting UL received-power input; not calibrated dBm or UE-measured DL RSRP. |
| `DRB.UEThpUl` | DU RLC RX PDU-byte statistics divided by their source period, expressed in kbit/s by the getter. | Actual UL service observation, not IP/video goodput or a direct estimate of unused capacity. |
| `DRB.UEThpDl` | DU RLC TX PDU-byte statistics, expressed in kbit/s by the getter. | DL service context; small ACK traffic can legitimately produce a small value. |
| `RRU.PrbTotUl` | Current getter calculates an integer UL PRB-use percentage from scheduler PRBs and UL slots. | Existing resource-use context; audit before using it as a control input. |
| `RRU.PrbTotDl` | Current getter calculates an integer DL PRB-use percentage from scheduler PRBs and DL slots. | Auxiliary DL resource-use context; same audit requirement. |
| `DRB.RlcSduDelayDl` | DU RLC TX SDU latency statistics; the getter's output unit is 0.1 ms. | Lower-priority DL delay diagnostic for this application. It is not RTT. |

The PRB UE getters currently use an internal UE index as a vector position.
Sparse or reordered UE indices can therefore select the wrong entry or return
noValue. Audit that mapping, integer truncation, denominators, and source
periods. The existing throughput getters also use integer intermediate values;
their declared REAL output does not guarantee retained fractional precision.
These qualifications apply to existing metrics, not just future extensions.

## Extensions for the initial application profile

The sources below already exist in OCUDU's typed scheduler reports. Read those
reports directly; do not scrape the DU console or continuously poll AT ports
for measurements that the DU already has.

| Priority | Measurement | How to obtain it | Export and interpretation requirements |
| --- | --- | --- | --- |
| First | UL power headroom | Decoded UE PHR MAC CE reaches `handle_ul_phr_indication`; the report exposes `last_phr`. | Last-known optional dB value. The current producer maps a reported PH interval to an integer midpoint. Preserve signed values and distinguish absence from zero. Add update age/validity; it is not a period average or spare bandwidth. |
| First | UL CRC OK and NOK | `scheduler_ue_metrics.ul_nof_ok` and `ul_nof_nok`, updated from CRC indications. | Two source-window counters. Derive `NOK / (OK + NOK)` at the xApp/controller; noValue when the denominator is zero. This is a CRC-outcome failure fraction, not IP loss or a proven first-transmission BLER. |
| First | UL buffer status | Decoded BSR indications reach `handle_ul_bsr_indication`; the report exposes aggregate `bsr`. | Last-known queued bytes reported by the UE, with update age/validity to be added. Do not present it as a fresh window average or an exact continuous queue measurement. |
| First | UL MCS | `scheduler_ue_metrics.ul_mcs`, produced from scheduled PUSCH grant MCS values. | Existing producer rounds the grant-average index. Export its meaning explicitly and add sample/grant validity so a window without grants is not a measured index zero. |
| First | DL CQI | UE CSI reaches scheduler `cqi_stats`; obtain its mean and observation count. | A `CQI` getter is already registered, but it reads the first UE and is registered at UNKNOWN_LEVEL. Repair UE scope, mapping, no-sample handling, and precision before subscribing to it. |
| First | DL HARQ OK and NOK | `dl_nof_ok` and `dl_nof_nok`, derived from received HARQ feedback. | Two window counters; derive the failure fraction with its denominator. They describe radio delivery, not specifically TCP ACK packets or direct PDCCH decoding success. |
| Optional next | MAC UL service rate | `ul_brate_kbps`, computed from CRC-success MAC transport-block bytes and the source window. | Distinct from existing RLC UL throughput. Add only if this layer distinction helps the controller or validation; label the layer and unit. |
| Optional next | UL scheduling delay | `avg_sr_to_pusch_delay_ms` and `max_sr_to_pusch_delay_ms`. | Optional delay statistics for handled SR observations. Not an end-to-end delay measurement or a complete measure of all UL waiting. |
| Optional next | UL and DL RI | `ul_ri_stats` and `dl_ri_stats`, including observation counts. | Conditional layer/rank context. Preserve fractional means and missing observations; do not copy the console's default UL RI of one. |

UL PRB context already belongs to the seven-metric profile and needs repair,
not a second duplicate metric. A separate cell-load profile can be added if
multi-UE contention becomes an input; a cell-level measurement must not be
represented as an independent per-UE observation.

All new getters must map the requested F1AP UE identity to `ue_index`, then
find the matching report entry, as the repaired RF getters do. Add supported
measurement definitions, admission, codec/decoder handling, and subscription
entries together. Registered names alone do not make measurements usable.
Choose standard names only when scope, unit, and aggregation agree; new vendor
names require an explicit contract rather than an assumed standard definition.

## Information to obtain outside E2SM

The following observations remain important. They do not need to travel from
the DU through E2SM to reach an application that can obtain them directly.

| Information | Appropriate source | Why it stays outside the initial KPM profile |
| --- | --- | --- |
| Per-subflow RTT, RTT variance, congestion window, retransmissions, acknowledged bytes, and delivery-rate estimates | Laptop sender's kernel socket diagnostics. Where supported, `MPTCP_TCPINFO` provides per-subflow `tcp_info`; `MPTCP_SUBFLOW_ADDRS` or `MPTCP_FULL_INFO` provides addressing. Check the installed kernel API and fields before implementation. | These are transport measurements, not DU radio measurements. Application goodput must still be measured at the application. |
| MPTCP connection/subflow state, endpoints, reinjections, and aggregate byte counters | MPTCP socket information and path-manager events; availability varies by counter/API/kernel version. | The transport/controller owns this state. Do not claim a generic MPTCP retransmission counter identifies every reinjection or per-path event. |
| UE IP, WWAN interface, routes, modem registration, PDU/bearer state, and recovery status | Laptop Netlink/IP state and ModemManager, with the modem selected by identity. | Host connectivity and recovery state should be joined with radio identities outside KPM; it does not require continuous E2 measurement polling. |
| Video bitrate, encoding/sending backlog, frame delivery, end-to-end latency, receiver buffer, and stalls | Video sender/receiver instrumentation on Laptop and Spark, as applicable to the actual pipeline. | These are application outcomes and workload indicators. |
| Fraction of traffic assigned to FR1/FR3 and the controller's decisions | Sender/controller accounting, kernel counters, and receiver measurements. | These are actions and transport/application results, not independent DU measurements. |
| Derived UL/DL error percentages | xApp/controller arithmetic from the exported OK/NOK window counters. | Avoid a redundant wire value; retain the counters and denominator. |

Linux documents the MPTCP packet scheduler as selecting available subflows for
outgoing data and describes the socket diagnostics above in its
[MPTCP documentation](https://docs.kernel.org/networking/mptcp.html).
This does not establish that the current project already collects those fields
or provides an arbitrary per-subflow weighting API. The xApp-to-application
broker and cross-host delivery are still implementation work.

PHY/MAC processing latency histograms, scheduler execution timings, RU
underflow/overflow/late counters, PAPR/clipping, detailed RLC internals, and TA
are useful diagnostics. Keep them in local or lower-frequency operational
monitoring for the initial uplink controller. They can justify a separate E2
health profile later if the control experiment demonstrates a need. They do
not all need to accompany every fast per-UE radio report.

UE-measured DL RSRP/RSRQ/SINR and calibrated UL dBm are a separate availability
question: the present DU sources do not supply them. Do not synthesize them
from PUSCH dBFS or CQI. A future modem/UE measurement feed or explicit RRC
measurement integration needs its own source, units, and identity contract.

## Required context and implementation order

Associate measurements with the complete node/DU identity and the F1AP UE
identity, plus available cell context. The host/controller must maintain the
separate binding to modem, current UE IP, interface, and MPTCP subflow. C-RNTI,
PCI, or an old IP alone is not a stable global identity.

Retain metric validity, observation counts where applicable, source-window
duration, and timestamps. Add update age for persistent PHR/BSR and an explicit
UE lifecycle policy. The KPM header timestamp is not a PHY sample timestamp;
current snapshots do not yet provide all this context or a synchronized
source-window guarantee. Missing samples must remain distinct from a measured
zero and from a disconnected path.

Implement and validate the first-priority additions and existing CQI/PRB
repairs at 1000 ms before evaluating 200 ms, then 100 ms. Change source and
reporting periods together. Validate controller delivery separately from
monitor reception. The broader diagnostic inventory remains available for
later work; this document does not implement or enable the narrowed profile.

## Repository scope and source references

The inspected baselines are Falcon `E2SM-KPM` at `b957048`, OCUDU `E2SM-KPM`
at `b587084d0e`, and FlexRIC `E2SM-KPM` at `3597413f`. OCUDU's two RF/test
commits remain ahead of its fork tracking branch. The Falcon and OCUDU E2SM
branches still require integration with the Dual-UE mainline changes before
claiming combined dual-DU deployment coverage.

OCUDU sources:

- `include/ocudu/scheduler/scheduler_metrics.h`: per-UE and cell metric types.
- `lib/scheduler/logging/scheduler_metrics_handler.cpp`: CRC, CSI, BSR and PHR
  input handling, source-window aggregation, and report construction.
- `lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp`: supported names,
  CQI/PRB/RF getters, and RLC throughput/delay conversion.
- `include/ocudu/rlc/rlc_metrics.h`: RLC bearer identity and source period.
- `include/ocudu/ru/sdr/ru_sdr_metrics.h`: radio/sector diagnostic metrics.

This change adds only this classification document. It does not change source,
runtime configuration, subscriptions, services, or existing plans. Validation
consists of checking the listed configuration, source members, getter behavior,
relative links, and document whitespace; it is not a new live measurement run.
