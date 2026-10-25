# DU Metric Expansion and Reporting Periods

## Decision and sequence

On October 24, 2026, the operator requested broader DU DL/UL telemetry before
increasing its reporting frequency. Extend the metric coverage at 1000 ms,
validate the values and delivery, then evaluate 200 ms and finally 100 ms.
The revised execution checklists are in [Plan 1](../../plans/e2sm-kpm-du-rf-metrics.md)
and [Plan 2](../../plans/xapp-kpm-app-subscription.md).

The coverage target is every usable metric in the DU's published scheduler,
RLC, MAC, PHY and RU metric reports. First cover every measurement displayed
by the DU `t` command. Then cover the remaining published fields, recording
each as included, conditionally available, derived, or unavailable, with a
reason. A field existing in a header does not establish that its producer is
enabled, that it has a valid sample, or that a KPM getter already exists.
This is a planning inventory; the added getters and faster profiles are pending.

## Current repository baselines

| Repository | Branch and commit | State relevant to this extension |
| --- | --- | --- |
| Falcon | `E2SM-KPM`, `b957048` before this plan revision | Contains the RF patches, configuration, tests and October 23 verification records. |
| OCUDU | `E2SM-KPM`, `b587084d0e` | Includes the RF implementation and native-test commits; both remain local and unpushed at inspection. |
| FlexRIC | `E2SM-KPM`, `3597413f` | Contains the timestamp repair and repository maintenance; the RF monitor remains an external staged candidate. |

The Falcon and OCUDU branches do not yet include the recently merged Dual-UE
mainline changes. Review the integration before claiming dual-DU live coverage;
do not reset either branch or discard the existing RF commits. The separate
Dual-UE functional acceptance decision remains unchanged.

## DU console coverage

The source is OCUDU `include/ocudu/scheduler/scheduler_metrics.h`, with display
formatting in
`apps/units/flexible_o_du/o_du_high/du_high/metrics/consumers/scheduler_metrics_consumers.cpp`.
PCI and C-RNTI are identity/context fields. They must be retained alongside the
complete node/DU and F1AP UE identity, rather than used as globally unique keys.

| Console measurement | DU source | Export semantics to define and validate |
| --- | --- | --- |
| DL CQI | `cqi_stats` | Mean and sample count; noValue with no observations. Repair the existing first-UE/UNKNOWN_LEVEL CQI path before reuse. |
| DL RI | `dl_ri_stats` | Mean and sample count; preserve fractional means. |
| DL MCS | `dl_mcs` | Existing rounded grant-average index; distinguish no DL grants from a measured index zero. |
| DL bitrate | `dl_brate_kbps` | MAC throughput in kbit/s over the actual window; separate from RLC throughput. |
| DL OK / NOK | `dl_nof_ok`, `dl_nof_nok` | Two window counters for HARQ feedback outcomes. |
| DL error percentage | DL OK / NOK | Derived `100 * NOK / (OK + NOK)`; noValue for a zero denominator. |
| DL buffer | `dl_bs` | Last-known buffer occupancy in bytes, not a period mean. |
| UL PUSCH SNR | `pusch_snr_db`, `nof_pusch_snr_reports` | Existing `FALCON.PUSCH.SNR.dB`; dB sample mean, valid measured zero, noValue without samples. |
| UL PUSCH RSRP | `pusch_rsrp_db` | Existing `FALCON.PUSCH.RSRP.dBFS`; software dBFS sample mean, finite-value validity. |
| UL RI | `ul_ri_stats` | Mean and sample count; the console's fallback `1` is not evidence of a measured RI. |
| UL MCS | `ul_mcs` | Existing rounded grant-average index; define a sample-validity rule. |
| UL bitrate | `ul_brate_kbps` | MAC CRC-success throughput in kbit/s over the actual window. |
| UL OK / NOK | `ul_nof_ok`, `ul_nof_nok` | Two window counters for CRC outcomes, not IP packet counts. |
| UL error percentage | UL OK / NOK | Derived CRC failure percentage; noValue for a zero denominator. |
| UL BSR | `bsr` | Last-known aggregate buffer status in bytes; disclose persistence. |
| Timing advance | PUSCH/PUCCH/SRS `*_ta_stats` | Preserve the source and observation count. Use a declared unit; record the console's SRS, PUSCH, PUCCH selection order if reproducing its combined TA. |
| Power headroom | `last_phr` | Optional last-known PHR in dB; disclose persistence and absence. |

Do not scrape console strings. The console rounds, clamps, renders valid zero
SNR as `n/a`, and substitutes defaults for some absent values. Export from the
typed source snapshots and reproduce display formatting only for human output.
PUSCH RF means remain arithmetic means of valid dB samples, including samples
associated with failed CRCs. Other metrics keep their own counter, mean,
maximum, rate or last-known-value semantics.

## Additional published metric families

| Family | Candidate coverage | Source and integration requirement |
| --- | --- | --- |
| Remaining per-UE scheduler fields | PUCCH SNR, SR count, PDSCH/PUSCH PRBs, invalid HARQ/CSI counts, CE/CRC/HARQ/SR delay mean/max, OLLA offsets, grant-distance maxima, TA statistics and sample counts | `scheduler_metrics.h`; preserve optional validity and trace the actual producer/reset rules. Add a validity/sample counter where the published snapshot currently conflates missing data with zero. |
| Cell scheduler | Slot/window context, PRB capacity, DL/UL slots and grants, PRACH/MSG3, allocation failures, late HARQs, PUCCH usage, scheduler latency, error indications | `scheduler_cell_metrics`; requires cell-keyed snapshots and a cell/node subscription path, not duplicated UE rows. |
| RLC DL and UL | Existing delay/throughput/volume/drop metrics, SDU/PDU counts and bytes, losses, malformed PDUs, retransmissions, control PDUs and applicable AM/UM latency counters | `include/ocudu/rlc/rlc_metrics.h`, `rlc_tx_metrics.h`, `rlc_rx_metrics.h`; specify bearer aggregation, mode support, units and actual report period. |
| MAC processing | Slot processing/dequeue/scheduler/FAPI latency statistics and context-switch counts | `include/ocudu/mac/mac_metrics.h`; these reports are not currently inputs to the KPM provider. Add explicit bounded ownership/notifier integration. |
| PHY / DU-low processing | Available upper-PHY processing and timing statistics | `include/ocudu/du/du_low/du_low_metrics.h`, `include/ocudu/phy/upper/upper_phy_metrics.h`; inventory producer-specific fields and sampling periods before defining KPM names. |
| SDR RU health | Late, underflow and overflow counts; per-sector TX/RX power, peaks, PAPR and clipping indicators | `include/ocudu/ru/sdr/ru_sdr_metrics.h`; separate radio/sector scope from UE scope, verify units and producer availability, and retain its actual cadence. |

Reuse standard KPM names only when the existing definition, unit, scope and
aggregation agree. Introduce reviewed `FALCON.*` names otherwise. The provider's
currently registered names are candidates for audit, not a verified complete
catalog. In particular, repair sparse UE-index/vector mapping and arithmetic
issues in the CQI/PRB paths before expanding their advertised support.

Measured downlink UE RSRP/RSRQ/SINR, calibrated dBm and CU-owned PDCP/RRC data
are not supplied by these DU scheduler/RLC reports. Record them as unavailable
unless a real additional source is integrated. Raw IQ, per-slot packet traces
and unbounded event streams require separate interfaces; do not label them as
periodic scalar KPM measurements. Histograms and vectors need a bounded,
explicit mapping before inclusion.

## Registry and profile contract

For every candidate, record its source member and producer, wire name, scope,
unit, INTEGER/REAL type, aggregation/reset rule, validity/sample-count rule,
source period, enabled producer, expected cost, tests and inclusion decision.
Keep complete DU/cell/UE attribution. Include the actual window duration and
sample availability where available; last-known values must not be described
as new window averages.

Respect the actual ASN.1/SDK numeric ranges. Signed PHR/OLLA and other negative
measurements need a signed-capable representation such as REAL where the KPM
INTEGER path is unsigned. Check counter/identifier bounds explicitly and retain
numeric overflow tests; do not wrap or silently narrow a wider source value.

Preserve the seven-metric RF profile as a regression profile. Add versioned
expanded UE and separate cell/DU-health profiles from an explicit registry.
Every requested supported metric must be advertised, admitted and decoded.
Unsupported metrics must be reported explicitly; never substitute fabricated
values or silently remove metrics to make a performance run pass.

## Frequency and capacity acceptance

The first expanded-profile acceptance remains at 1000 ms. Only after its
source correctness, codec, identity, live values and lifecycle checks pass,
test the same declared coverage at 200 ms, then 100 ms. Change the DU producer
period and the KPM reporting/granularity periods together. Source producers
with a slower independent cadence must stay in a declared slower profile or
be updated explicitly; faster polling does not create new samples.

The inspection found that the current DU configuration parser accepts both
200 and 100 ms, and the KPM reporting timer uses milliseconds. This establishes
configuration feasibility, not runtime timing or end-to-end acceptance.

At each rate, retain actual encoded E2AP PDU sizes, report counts, monotonic
arrival intervals, processing times, queue depths/drops, CPU use, and changes
in radio late/underflow/overflow counters under comparable traffic. The
current OCUDU SCTP sender rejects a PDU above 9100 bytes
(`lib/gateways/sctp_network_gateway_common_impl.h` and
`lib/gateways/sctp_network_client_impl.cpp`). Check the complete encoded PDU,
not only its KPM payload. If needed, partition the declared metric set into
bounded groups with one shared subscription per DU/scope/group; retain coverage.

Keep slow terminal/file/socket work outside callbacks. Plan 2's bounded
queues, overflow counters and slow-client isolation remain required for the
application-forwarding implementation. They are not protections already
provided by the current text monitor. Monitor-only rate acceptance cannot
close the separate broker-to-client forwarding gate.

The existing snapshot synchronization deferral remains a known limitation.
Review ownership and cross-executor reads for added sources and document the
chosen consistency policy. Do not claim that a shared report row guarantees
one source window, that identical numbers prove replay, or that a 100/200 ms
period guarantees the same upper bound on end-to-end latency.

## Completion records

Retain separate results for the original RF baseline, expanded coverage at
1000 ms, expanded coverage at 200 ms, expanded coverage at 100 ms, and
application forwarding at each tested rate. Preserve the previously accepted
17 offline and 36 native case names and the 39 runner regressions; add new
tests without replacing those results. Keep actual single-link and multi-link
coverage explicit, and preserve all existing historical verification reports.
