# DU PUSCH RF Measurement Semantics

Plan 1, Step 2 source trace, recorded on October 19, 2026 (America/New_York).
Developer: Hao Ding.

## Scope, revisions, and evidence

| Repository | Branch and inspected revision | Role in this step |
| --- | --- | --- |
| Falcon | `E2SM-KPM`, starting at `7ef01c1555f4c4811a6f08eca1fcdf06982aee18` | Added this implementation note. |
| OCUDU | `E2SM-KPM`, `4cffc0479f9620f668a7ac79aeb314b2e31525e4` | Read production sources and the existing deployment configuration. No source changes. |
| FlexRIC | `falcon-xapp`, `10b8ec79d0f011902d329b2ed37f33f8b101b591` | Remained read-only; the timestamp repair is already committed. No edits or builds. |

The approved OCUDU baseline includes the plan's `69801c7` revision, the
3660 MHz DU1 configuration, and `AGENTS.md`. Step 1 established that the five
RF production patch targets are identical across `050a2bb`, `69801c7`, and
`4cffc04`; both cumulative RF patches passed `git apply --check` without being
applied. The approved branch and revision deviations are retained in
`/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step1-r_5tm1a2/approved-baselines.json`.

Step 2 command transcripts, numbered source snapshots, hashes, and static
validation results are retained under
`/home/nyu/verification/e2sm-kpm/run-TQcKveEB/step2-source-trace/`.
Every `OCUDU:path:line` citation below is relative to `/home/nyu/ocudu` at
the recorded revision. The notes destination follows the user's explicit
Step 2 path instruction. Existing plans and explanatory documents were preserved.

Context: [authoritative Plan 1](../../plans/e2sm-kpm-du-rf-metrics.md),
[Plan 2 ordering and shared files](../../plans/xapp-kpm-app-subscription.md),
[historical RF package record](../troubleshooting/2026-10-07_flexric_bringup.md),
and [timestamp semantics](../troubleshooting/2026-10-07_flexric_latency_fix.md).

## Measurement contract to implement

| Exported name | Scheduler source | Wire type and unit | Validity |
| --- | --- | --- | --- |
| `FALCON.PUSCH.RSRP.dBFS` | The requested UE's `pusch_rsrp_db` | KPM `REAL`, software dBFS | A matching current UE snapshot and a finite value. |
| `FALCON.PUSCH.SNR.dB` | The requested UE's `pusch_snr_db` | KPM `REAL`, dB | A matching current UE snapshot, a finite value, and `nof_pusch_snr_reports > 0`. |

Both metrics require UE scope and exactly one unfiltered `NO_LABEL` entry.
Return one record per requested UE in request order. A missing mapping,
incompatible UE type, absent snapshot, absent sample, or non-finite selected
scheduler value must yield `noValue`. A finite measured zero is valid.
Reject node/cell aggregation and expanded labels. These requirements describe
the pending RF implementation, not behavior already present in this baseline.

RSRP describes uplink PUSCH DM-RS received power on the software full-scale
reference. It is not calibrated dBm or a UE-reported downlink measurement.
The SNR wire name preserves the scheduler's existing field name for the
selected PHY SINR estimate; no additional independent SINR metric is implied.
RSRQ remains a local unavailable-capability notice, with no RSRQ subscription.

## Estimator selection and PHY measurements

The application default is `post_equalization`. Its documented alternatives
are `channel_estimator` and `evm`
(`OCUDU:apps/units/flexible_o_du/o_du_low/du_low_config.h:28`).
The configuration parser binds the setting to that application field
(`OCUDU:apps/units/flexible_o_du/o_du_low/du_low_config_cli11_schema.cpp:205`).
The DU-low translator converts the string to the PHY SINR enum
(`OCUDU:apps/units/flexible_o_du/o_du_low/du_low_config_translator.cpp:35`).
The upper-PHY factory enables the selected calculation and passes the selection
to the PUSCH processor factory
(`OCUDU:lib/phy/upper/upper_phy_factories.cpp:784`,
`OCUDU:lib/phy/upper/upper_phy_factories.cpp:817`). The processor factory copies
that value into each processor configuration
(`OCUDU:lib/phy/upper/channel_processors/pusch/processor_factories.cpp:168`).
The processor constructs CSI with that explicit selection
(`OCUDU:lib/phy/upper/channel_processors/pusch/pusch_processor_impl.cpp:211`).

The standalone `channel_state_information` default constructor selects
`channel_estimator`; it does not override the application's explicit
`post_equalization` selection. `get_sinr_dB()` returns the optional value for
the selected enum. There is no automatic fallback to another estimate when
the selected estimate is absent
(`OCUDU:include/ocudu/phy/upper/channel_state_information.h:36`,
`OCUDU:include/ocudu/phy/upper/channel_state_information.h:67`).

The DM-RS estimator retrieves per-port RSRP for transmit layer 0 and passes it
to `set_rsrp_lin()`
(`OCUDU:lib/phy/upper/signal_processors/pusch/dmrs_pusch_estimator_impl.cpp:209`,
`OCUDU:lib/phy/upper/signal_processors/pusch/dmrs_pusch_estimator_impl.cpp:296`).
CSI excludes non-normal per-port values, averages the retained linear powers
across ports, and then converts that mean to normalized dB
(`OCUDU:include/ocudu/phy/upper/channel_state_information.h:208`). This per-port
linear averaging precedes the scheduler's separate averaging of reported dB
samples. The estimator also populates the channel-estimator SINR field
(`OCUDU:lib/phy/upper/signal_processors/pusch/dmrs_pusch_estimator_impl.cpp:313`).

For post-equalization SINR, the demodulator computes the negative dB value of
the mean equalized noise variance; its degenerate branch produces positive
infinity
(`OCUDU:lib/phy/upper/channel_processors/pusch/pusch_demodulator_impl.cpp:428`).
The notifier stores post-equalization statistics and, when calculated, the
EVM-derived estimate `-20 * log10(EVM) - 3.7`
(`OCUDU:lib/phy/upper/channel_processors/pusch/pusch_processor_notifier_adaptor.h:128`).
The CSI setter ignores NaN, but does not reject infinity
(`OCUDU:include/ocudu/phy/upper/channel_state_information.h:86`).
The data-result callback carries both decoder status and CSI onward without
discarding CSI on a failed TB CRC
(`OCUDU:lib/phy/upper/channel_processors/pusch/pusch_processor_notifier_adaptor.h:226`).

## PHY/FAPI/MAC conversion and limits

The CRC-indication path reads `result.csi.get_sinr_dB()` and
`result.csi.get_rsrp_dB()`. It converts normalized power to software dBFS by
subtracting `20 * log10(full_scale_reference)`, clamps the values, and invokes
the CRC builder with `rsrp_use_dBm = false`
(`OCUDU:lib/fapi_adaptor/phy/p7/phy_to_fapi_results_event_fastpath_translator.cpp:47`,
`OCUDU:lib/fapi_adaptor/phy/p7/phy_to_fapi_results_event_fastpath_translator.cpp:231`).

The inspected split-8 factory omits an explicit calibration member, retaining
the `1.F` default in the common RU configuration. That value is passed to the
P7 translator
(`OCUDU:apps/units/flexible_o_du/split_8/split_8_o_du_factory.cpp:10`,
`OCUDU:apps/units/flexible_o_du/split_helpers/flexible_o_du_configs.h:25`,
`OCUDU:apps/units/flexible_o_du/split_helpers/flexible_o_du_factory.cpp:64`,
`OCUDU:apps/units/flexible_o_du/split_helpers/flexible_o_du_factory.cpp:239`).
This source-level software reference does not establish physical power
calibration or the behavior of the existing deployed binary.

| Quantity | Clamp before builder | Builder encoding for a present value | MAC decoding | Missing sentinel |
| --- | --- | --- | --- | --- |
| RSRP | `[-128, 0] dBFS` | `unsigned((rsrp_dBFS + 128.F) * 10.F)` | `(float(q) - 1280.F) * 0.1F` | `UINT16_MAX` (`65535`) |
| Selected SINR | `[-65.534, 65.534] dB` | `int(sinr_dB * 500.F)`, then `int16_t` | `float(q) * 0.002F` | `INT16_MIN` (`-32768`) |

Clamp constants and optional-value handling are at
`OCUDU:lib/fapi_adaptor/phy/p7/phy_to_fapi_results_event_fastpath_translator.cpp:238`.
Encoding, integer casts, sentinels, and range assertions are at
`OCUDU:include/ocudu/fapi/p7/builders/crc_indication_builder.h:32`.
Decoding converts the sentinels to `std::nullopt`
(`OCUDU:lib/fapi_adaptor/mac/p7/fapi_to_mac_indications_fastpath_translator.cpp:54`).

The nominal quantization steps are 0.1 dB for RSRP and 0.002 dB for SINR.
The builder uses truncating casts, not rounding to nearest. Floating-point
arithmetic can affect boundary results; native conversion tests must exercise
the production implementation. Zero encodes as RSRP `1280` or SINR `0`, both
distinct from the missing sentinels. RSRP `-128 dBFS` is also a valid encoded
boundary, distinct from missing data.

An absent CSI optional remains absent through the builder and MAC adapter.
Infinities reaching the clamp can instead become finite saturation values;
for example, positive-infinite selected SINR is clamped before encoding.
KPM cannot recover the pre-clamp value or infer original validity from a finite
boundary value. The RF task preserves this existing behavior; its non-finite
check applies to the selected scheduler snapshot value.

The FAPI-to-MAC CRC callback transfers CRC status and the decoded RF optionals
without a CRC-success filter
(`OCUDU:lib/fapi_adaptor/mac/p7/fapi_to_mac_indications_fastpath_translator.cpp:127`).
The MAC scheduler adapter resolves C-RNTI through its UE manager and copies
`ul_sinr_dB` and `ul_rsrp_dBFS` to the scheduler indication
(`OCUDU:lib/mac/mac_sched/ocudu_scheduler_adapter.cpp:365`).

## Scheduler averaging, sample counts, and reset

For an existing scheduler UE, each CRC indication increments the CRC counter.
Each present RF optional independently increments its RF sample count and
adds its decoded dB value to the corresponding sum. Only the UL byte counter
is gated by TB CRC success. RF samples associated with failed CRCs therefore
participate in the RF means
(`OCUDU:lib/scheduler/logging/scheduler_metrics_handler.cpp:144`). The sums are
`double` and the RF counts start at zero
(`OCUDU:lib/scheduler/logging/scheduler_metrics_handler.h:49`,
`OCUDU:lib/scheduler/logging/scheduler_metrics_handler.h:64`).

For each report window:

```text
pusch_rsrp_db = sum_pusch_rsrp / nof_pusch_rsrp_reports, when count > 0
               -infinity, otherwise
pusch_snr_db  = sum_pusch_snrs / nof_pusch_snr_reports, when count > 0
               0, otherwise
```

These are arithmetic means of the available, quantized dB reports, not a
linear-power mean across time, a success-only mean, or a throughput-weighted
mean. The output fields are `float`
(`OCUDU:lib/scheduler/logging/scheduler_metrics_handler.cpp:582`,
`OCUDU:lib/scheduler/logging/scheduler_metrics_handler.cpp:607`,
`OCUDU:include/ocudu/scheduler/scheduler_metrics.h:41`). Averaging can produce
fractions finer than one input quantization step. KPM `REAL` must preserve the
selected scheduler float promoted to double, without an integer cast.

Report construction includes UE identity, PCI, the starting slot and window
slot count
(`OCUDU:lib/scheduler/logging/scheduler_metrics_handler.cpp:370`). Each UE's
`compute_report()` resets its nonpersistent data before returning; the sums and
counts do not accumulate across windows
(`OCUDU:lib/scheduler/logging/scheduler_metrics_handler.cpp:658`).

The baseline snapshot does not expose the SNR count, although the accumulator
already maintains it
(`OCUDU:include/ocudu/scheduler/scheduler_metrics.h:23`,
`OCUDU:lib/scheduler/logging/scheduler_metrics_handler.h:64`). The reviewed RF
patch must copy that count into `nof_pusch_snr_reports` without changing the
mean or reset behavior. RSRP already uses negative infinity for an absent
window; SNR's default zero cannot distinguish absence from a valid measurement.

## KPM consumption, mapping, and advertisement

The provider replaces `last_ue_metrics` from each scheduler report and clears
disconnected RLC history
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:133`).
Its header exposes scheduler and RLC notification entry points
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h:31`).
Snapshot synchronization and generation consistency remain the explicit Step 3
design review gate; this trace does not establish safe concurrent access.

The existing generic `RSRP` and `RSRQ` getters both take the first UE snapshot
and return an integer cast of `pusch_snr_db`
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:337`).
Their constructor registrations use `UNKNOWN_LEVEL`
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:14`).
That enum has a separate bit from UE/node scope, so registration alone does
not demonstrate advertisement in those scopes
(`OCUDU:include/ocudu/e2/e2sm/e2sm_kpm.h:12`). The RF patch must replace the
registrations with the exact vendor names at UE scope and remove the incorrect
RSRQ getter; it has not been applied in this step.

The existing F1AP translator resolves a gNB-CU UE F1AP ID to its DU `ue_index`
and returns `INVALID_DU_UE_INDEX` when no context exists
(`OCUDU:lib/f1ap/du/f1ap_du_impl.cpp:619`). The RF getter must then search
the scheduler snapshot by the stored `ue_index`. That index must never be used
as a vector offset. Style 4 consumes the returned record vector in the exact
requested UE order, which requires stable cardinality even for missing UEs
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.cpp:428`).

Current Style 4 UE discovery reads RLC snapshots and translates internal IDs
to F1AP IDs; it does not enforce the matching condition as a slice filter
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:253`).
Both scheduler and RLC metrics must remain enabled.

Capability names are filtered by the provider's supported-level flags
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp:180`).
The production `pack_ran_function_description()` obtains the node and UE lists
and includes the UE list in the Style 4 description, with Format 4 action and
Format 3 indication
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_asn1_packer.cpp:64`,
`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_asn1_packer.cpp:137`).
Style 4 admission delegates to the Format 1 subscription checker at UE level
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_impl.cpp:177`). The existing label loop
does not enforce exactly one label entry
(`OCUDU:lib/e2/e2sm/e2sm_kpm/e2sm_kpm_impl.cpp:56`); the RF patch must enforce
the contract during both admission and collection. This is pending Step 3.

## Current deployment configuration

The approved operating file is `configs/du1_b210_n78_3660mhz.yml`, not the
plan's historical two-file combination. It specifies DU ID 1, carrier ARFCN
644000, n78, 20 MHz, 30 kHz SCS, 23.04 MS/s, TX gain 70, and RX gain 35
(`OCUDU:configs/du1_b210_n78_3660mhz.yml:8`,
`OCUDU:configs/du1_b210_n78_3660mhz.yml:18`). Its E2/KPM block is enabled and
its metrics block explicitly sets scheduler and RLC reporting to enabled,
with `du_report_period: 1000`
(`OCUDU:configs/du1_b210_n78_3660mhz.yml:49`). The parser maps these metric
keys to the application fields and describes the period in milliseconds
(`OCUDU:apps/units/flexible_o_du/o_du_high/du_high/du_high_config_cli11_schema.cpp:2484`).
The translator transfers the flags and period to DU-high configuration
(`OCUDU:apps/units/flexible_o_du/o_du_high/du_high/du_high_config_translators.cpp:1207`).

The file contains no `pusch_sinr_calc_method` override. With the inspected
source defaults and this file alone, the configured selection is therefore
`post_equalization`. This is a source/configuration inference: no DU was
launched, no runtime configuration dump or binary dry run was performed, and
the existing binary's effective method was not independently verified.
Keep all three historical/current config hashes in Step 1 evidence for the
eventual Steps 8-9 command review. No configuration or gain changes are needed
to expose the existing scheduler measurements.

## Validation, use, and remaining gates

Static validation retained numbered source snapshots, source hashes,
configuration checks, citation checks, and the unchanged OCUDU RF-target
comparison against HEAD. This step added documentation only. No production
source, RF patch, runner, configuration, or existing explanatory document was
changed; no build, RF probe, network traffic, or service operation was performed.

Use this note when reviewing the five-file RF candidate in Step 3 and
designing production conversion/scheduler coverage in Step 5. In particular,
the existing synthetic codec values are injected after PHY/FAPI conversion;
they cannot establish quantization, calibration, or the correctness of one
physical RF sample. Step 6 must retain the original synthetic expectations
independently of the later native conversion tests.

Step 3 still requires an approved executor/snapshot design before any candidate
implementation changes. Step 5 requires separately proposed explicit runner
baseline adaptations for OCUDU `4cffc04` and FlexRIC `10b8ec79`, preserving
all other guards. Step 7, deployment builds, and live acceptance remain blocked.

No live estimator behavior, physical dBm calibration, RF sample age, sustained
cadence, source-to-binary correspondence, or multi-UE hardware behavior was
validated by this source trace.

## Known limitations

The project lead's reviewer decision, communicated on 2026-10-21, deferred
snapshot safety, snapshot generation, and source-generation trace correlation
for this iteration. Metrics-strand writes and E2 reads remain unsynchronized;
data races and inconsistent snapshots are accepted known limitations. No
provider mutex, executor confinement, cleanup relocation, or `du.cpp`
receive-executor prerequisite will be implemented. This decision supersedes
the Step 3 design-approval gate recorded above; see the
[design decision](../e2sm-kpm/2026-10-19_du_rf_metrics_patch_review_and_snapshot_design.md#decision).
Sequential offline checks do not establish concurrent safety or same-window
RSRP/SNR consistency. The measurement, mapping, label, and REAL/noValue
contract remains required. RSRQ remains a local `n/a` notice only.
