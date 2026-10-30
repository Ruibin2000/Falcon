# DU KPM metric reference

Updated: October 29, 2026.

The [current two-link deployment](dual_link_radio_design.md) uses DU1 at
3660 MHz / 20 MHz (51 PRBs) and DU2 at a 3600-MHz n78 interface / 40 MHz
(106 PRBs), both at 30-kHz SCS and 100-ms DU reporting. Link 2 is designed
for Pi-Radio conversion to 9250-MHz OTA; the current direct test has no
converters. This does not change the measurement names or units. Normalize
PRB usage using each cell's reported capacity; do not assume 51 PRBs for both
links or interpret the `FR3` label as an E2 physical-frequency measurement.

The following table defines the **27 raw DU KPM measurements** in the
expanded UE profile. Scheduler fields refer to `scheduler_ue_metrics`; RLC fields refer
to the retained `rlc_metrics` reports for the requested UE. The `t` column
identifies the corresponding DU console label, when one is printed. An em
dash means that this measurement has no separate column in the console table.
`INTEGER` and `REAL` describe the E2 record type, before plot unit conversions.

| Reported KPM | Meaning and wire unit / type | DU source field | DU console `t` column | Statistic |
| --- | --- | --- | --- | --- |
| `DRB.RlcSduDelayDl` | DL RLC SDU delay; 0.1 ms / REAL | RLC `tx.tx_low.sum_sdu_latency_us`, `tx.tx_high.num_sdus` | — | Retained UE RLC latency sum divided by SDU count; scaled and rounded by the getter |
| `DRB.UEThpDl` | DL RLC throughput; kbit/s / REAL | RLC `tx.tx_low.num_pdu_bytes_no_segmentation` plus UM/AM `num_pdu_bytes_with_segmentation` | — | Mean byte counters over retained RLC reports, normalized by the RLC metrics period |
| `DRB.UEThpUl` | UL RLC throughput; kbit/s / REAL | RLC `rx.num_pdu_bytes` | — | Mean byte counter over retained RLC reports, normalized by the RLC metrics period |
| `RRU.PrbTotDl` | DL PRB utilization; % / INTEGER | `tot_pdsch_prbs_used` plus DL slot count and cell capacity | — | DL utilization formula below, truncated to an integer |
| `RRU.PrbTotUl` | UL PRB utilization; % / INTEGER | `tot_pusch_prbs_used` plus UL slot count and cell capacity | — | UL utilization formula below, truncated to an integer |
| `PUSCH.RSRP.dBFS` | UL PUSCH DM-RS power; dBFS / REAL | `pusch_rsrp_db` | UL `rsrp` | Window arithmetic mean of available dBFS samples, after PHY conversion and range limiting |
| `PUSCH.SNR.dB` | UL selected PHY SINR estimate; dB / REAL | `pusch_snr_db`, guarded by `nof_pusch_snr_reports` | UL `pusch` | Window arithmetic mean of available selected PHY estimates |
| `CQI` | DL channel quality index; index / INTEGER | `cqi_stats.get_mean()` | DL `cqi` | Window mean rounded to nearest integer; unavailable without observations |
| `CQI.Samples` | CQI observation count; samples / INTEGER | `cqi_stats.get_nof_observations()` | — | Number of CQI observations in the window; zero is valid |
| `DL.MCS` | DL modulation and coding index; index / INTEGER | `dl_mcs` | DL `mcs` | Rounded window mean over scheduled DL codewords |
| `UL.MCS` | UL modulation and coding index; index / INTEGER | `ul_mcs` | UL `mcs` | Rounded window mean over scheduled PUSCH grants |
| `DL.MCS.Samples` | DL MCS observation count; samples / INTEGER | `nof_dl_mcs_reports` | — | Number of scheduled DL codewords in the window |
| `UL.MCS.Samples` | UL MCS observation count; samples / INTEGER | `nof_ul_mcs_reports` | — | Number of scheduled PUSCH grants in the window |
| `UL.PHR.dB` | UL power headroom; dB / REAL | `last_phr` | UL `phr` | Latest reported PH interval midpoint; signed value, not a window mean |
| `UL.PHR.AgeMs` | Age of latest PHR; ms / REAL | `phr_age_ms` | — | Time since the latest PHR indication, evaluated at snapshot creation |
| `UL.BSR.Bytes` | Reported UL buffer occupancy; bytes / INTEGER | `bsr` | UL `bsr` | Sum of logical-channel-group bytes in the latest received BSR indication |
| `UL.BSR.AgeMs` | Age of latest BSR; ms / REAL | `bsr_age_ms` | — | Time since the latest BSR indication, evaluated at snapshot creation |
| `DL.Buffer.Bytes` | Reported DL buffer occupancy; bytes / INTEGER | `dl_bs` | DL `dl_bs` | Sum of last stored DL logical-channel buffer values |
| `DL.Buffer.AgeMs` | Age of newest DL buffer update; ms / REAL | `dl_buffer_age_ms` | — | Time since the newest channel update; other channel values may be older |
| `DL.MAC.Throughput` | DL MAC acknowledged rate; kbit/s / REAL | `dl_brate_kbps` | DL `brate` | Positive-ACK transport-block bytes normalized by the source period |
| `UL.MAC.Throughput` | UL MAC CRC-success rate; kbit/s / REAL | `ul_brate_kbps` | UL `brate` | CRC-success transport-block bytes normalized by the source period |
| `DL.HARQ.Ok` | DL positive HARQ outcomes; count / INTEGER | `dl_nof_ok` | DL `ok` | Positive HARQ-ACK count in the window |
| `DL.HARQ.Nok` | DL negative HARQ outcomes; count / INTEGER | `dl_nof_nok` | DL `nok` | NACK or HARQ-ACK misdetection count in the window |
| `UL.CRC.Ok` | UL successful CRC outcomes; count / INTEGER | `ul_nof_ok` | UL `ok` | CRC-success indication count in the window |
| `UL.CRC.Nok` | UL failed CRC outcomes; count / INTEGER | `ul_nof_nok` | UL `nok` | CRC-failure indication count in the window |
| `PRB.UsageDl.Percent` | DL PRB utilization with fractional precision; % / REAL | `tot_pdsch_prbs_used` plus DL slot count and cell capacity | — | DL utilization formula below, retaining its fractional result |
| `PRB.UsageUl.Percent` | UL PRB utilization with fractional precision; % / REAL | `tot_pusch_prbs_used` plus UL slot count and cell capacity | — | UL utilization formula below, retaining its fractional result |

For PRB utilization, the provider computes
`100 × used_PRB_slots / (directional_slots × cell_PRBs)`. The directional
counts come from `scheduler_cell_metrics.nof_dl_slots` and `nof_ul_slots`,
and cell capacity from `nof_prbs`. The current UL denominator counts full UL
slots. INTEGER and REAL representations use separate getter calls. Consumers
can use the REAL fields directly for fractional precision; this does not
guarantee that different getters read the same snapshot version.

Scheduler means, rates and outcome counts describe the configured 100 ms
source window. PHR, BSR and DL buffer are latest-indication values that may
persist across windows; their age fields preserve that distinction. RLC
getters aggregate the retained RLC reports, so their values are not necessarily
restricted to the exact same window as a scheduler field in the same E2 row.
Missing measurements remain `no_value`, while valid zero remains numeric.

The console is a formatted view: its `brate` fields use MAC statistics and
engineering-scaled bit/s, while the KPM rate fields above use kbit/s. The
`DRB.UEThpDl/Ul` RLC measurements therefore have no direct `brate` mapping.
Plots convert rates to Mbit/s and RLC delay to ms. The xApp additionally derives
`DL.HARQ.FailureRatio` and `UL.CRC.FailureRatio` as
`100 × NOK / (OK + NOK)`; these two values are outside the 27 raw measurements.
CU identity reports and the joined Core IPv4/session fields are also separate
from this DU measurement list.

Implementation details and deployment profiles are described in the
[first DU KPM expansion](e2sm-kpm/du_kpm_expansion_stage1.md). Live observations are
recorded in the [six-minute dual UE stability report](reports/dual_ue_27kpm_stability_report_2026-10-25.md).
