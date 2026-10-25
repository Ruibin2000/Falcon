# First DU KPM expansion: 100 ms UE profile

Developer: Ruibin. Updated: October 25, 2026.

This stage adds 14 scheduler measurements and six sample-count/age fields
to the accepted seven: **27 raw E2 measurements**. DU source/subscription
periods remain **100 ms**, CU identity **1000 ms**, Core polling **1 s** and
freshness **3 s**. Offline verification does not establish live expanded
delivery; a new operator-run dual-UE capture remains required.

## Profiles and deployment

| Selection | Configuration | DU period |
| --- | --- | --- |
| Explicit `--du-metrics 27` | [Expanded](../../configs/flexric/xapp_ue_identity_expanded.conf) | 100 ms |
| Default / `--du-metrics 7` | [Accepted seven](../../configs/flexric/xapp_ue_identity.conf) | 100 ms |
| `--du-metrics 5` | [Legacy five](../../configs/flexric/xapp_ue_identity_five.conf) | 1000 ms |

The [Spark quick commands, section 7](../dual_ue_spark_quick_commands.md#7-start-the-dual-ue-identityrf-xapp-and-save-txt-results)
target the expanded capture and retain current IP checks. Older DUs cannot
serve the new names; rejected metrics must not be silently omitted.
Rebuild/restart both DUs and the xApp. Healthy CU, RIC and Core can remain
running. No CU identity or FlexRIC source/SDK ABI change is required.
The collector is rebuilt to format unsigned measurement integers correctly.

## Raw measurement contract

The seven existing names and units are retained: `DRB.RlcSduDelayDl`,
`DRB.UEThpDl`, `DRB.UEThpUl`, `RRU.PrbTotDl`, `RRU.PrbTotUl`,
`PUSCH.RSRP.dBFS`, `PUSCH.SNR.dB`.

Added names are local UE-scoped metrics supporting one unfiltered
`NO_LABEL` and preserving requested UE order. Node/cell aggregation is
rejected. They carry the existing node/DU/F1 identity and current-IP binding.
Values come from typed scheduler snapshots, not console text.

| Added wire name | Source | Unit / E2 type | Semantics |
| --- | --- | --- | --- |
| `CQI` | `cqi_stats` | index / INTEGER | Window mean rounded to nearest integer, matching console; noValue without samples |
| `CQI.Samples` | CQI observations | samples / INTEGER | Zero is valid |
| `DL.MCS`, `UL.MCS` | `dl_mcs`, `ul_mcs` | index / INTEGER | Rounded source window means; noValue without grants |
| `DL.MCS.Samples`, `UL.MCS.Samples` | DL codewords / PUSCH grants | samples / INTEGER | Window observation counts |
| `UL.PHR.dB` | `last_phr` | dB / REAL | Signed source representative of last PH interval; not a window mean |
| `UL.PHR.AgeMs` | Last PHR indication time | ms / REAL | Age at scheduler snapshot creation |
| `UL.BSR.Bytes` | `bsr` | bytes / INTEGER | Sum of reported LCG bytes in the last received BSR indication |
| `UL.BSR.AgeMs` | Last BSR indication time | ms / REAL | Age at snapshot creation |
| `DL.Buffer.Bytes` | `dl_bs` | bytes / INTEGER | Sum of last stored DL logical-channel buffer states |
| `DL.Buffer.AgeMs` | Newest DL buffer indication time | ms / REAL | Age of newest channel update, not of every channel |
| `DL.MAC.Throughput`, `UL.MAC.Throughput` | `dl_brate_kbps`, `ul_brate_kbps` | kbit/s / REAL | Positive-ACK DL bytes / CRC-success UL bytes normalized by source period |
| `DL.HARQ.Ok`, `DL.HARQ.Nok` | `dl_nof_ok/nok` | count / INTEGER | Window ACK / NACK-or-misdetection outcomes |
| `UL.CRC.Ok`, `UL.CRC.Nok` | `ul_nof_ok/nok` | count / INTEGER | Window CRC-success / failure indications |
| `PRB.UsageDl.Percent`, `PRB.UsageUl.Percent` | PDSCH/PUSCH PRB-slot count, directional slot count and cell PRB capacity | % / REAL | Unrounded percentage for the requested UE, including values below 1% |

PHR, BSR and DL buffer remain unavailable until an indication arrives.
Their last-known values persist across windows with increasing age; context
removal/recreation clears them. Ages use a monotonic clock, are measured
at source snapshot creation, exclude delivery time and are not refreshed by
a repeated KPM read.

BSR partial-LCG/format interpretation is unchanged: the last indication's
sum is not proof of a complete, continuously updated modem queue. DL buffer
combines last-known per-channel values with potentially different ages.

Buffer sums use 64-bit accumulation and are withheld when they exceed the
unsigned 32-bit wire domain. Valid zero, negative PHR and missing data remain
distinct. Nonfinite/out-of-range REAL values are withheld. Current OCUDU
REAL storage has float precision, so fractional throughput is retained to
that precision rather than promising exact source-double equality.

## Getter fixes and xApp-derived values

CQI is advertised at UE scope and resolves the actual requested UE.
PRB-used/percentage getters also find the actual `ue_index`, rather than
using it as a dense vector offset. Both representations use the full PRB-slot
count: `100 * used / (directional_slots * cell_prbs)`. The existing
`RRU.PrbTotDl/Ul` still return INTEGER percentages. The additional local
`PRB.UsageDl.Percent` and `PRB.UsageUl.Percent` return REAL percentages directly
from the DU, separately from xApp-derived values. For example, 19 used PRB-slots
out of 520 produce approximately 3.653846% as REAL and 3% as INTEGER. One out
of 520 produces approximately 0.192308% as REAL and 0% as INTEGER. Valid zero
remains REAL zero; a missing UE or zero slot/capacity denominator produces
noValue. The REAL metrics are UE-only; no node/cell aggregate is advertised.

Raw E2 values remain in `row.metrics`. The xApp separately emits
`DL.HARQ.FailureRatio` and `UL.CRC.FailureRatio` in `derived_metrics`,
with source names and unit percent: `100 * NOK / (OK + NOK)`.
Missing counts or a zero denominator produce noValue. These are observed
outcome ratios, not first-transmission BLER or IP packet loss. TXT labels
them as xApp-derived. Seven/five-measurement rows retain their behavior.

## Verification and remaining scope

Native tests cover sparse/reordered UEs, missing data, valid zero, signed
PHR, fractional rates and PRB percentages, window reset, persistent ages, context recreation,
buffer bounds, capability admission, advertisement and actual APER encoding.
The [synthetic fixture](../../tests/ue_identity/fixtures/du_expanded_codec.json)
is decoded independently by the pinned FlexRIC plugin and collector,
including 4294967295 bytes without signed JSON corruption. Python checks
also preserve both IP bindings and separate derived values from raw KPM.
These fixtures are not radio measurements. Records are retained in
[verification.json](../evidence/2026-10-25_kpm_expansion_stage1/verification.json).

A synthetic payload size does not establish live full E2AP PDU size or
runtime capacity. The new dual-uplink capture must inspect all 27 names,
actual 100 ms arrivals, missing samples, input drops and current bindings.
The implementation's 9100-byte full SCTP PDU limit remains relevant.

RI, OLLA, TA, further RLC and separate cell/RU-health metrics remain later
stages. The snapshot-concurrency deferral is preserved: no provider locks,
collection guards, executor changes or cleanup relocation are included.
Shared lifecycle-generation proof also remains separate.
