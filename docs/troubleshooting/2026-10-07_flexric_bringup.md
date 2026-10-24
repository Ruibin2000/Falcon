# FlexRIC integration on Spark

Date: **2026-10-07**. OCUDU DU1 connected to FlexRIC over E2, and the C KPM xApp completed subscription, deletion and normal exit. **A subsequent run received all five actual UE KPM measurements for gNB-DU UE F1AP ID `14`.** The 2026-10-05 UE traffic result remains the application-data baseline; no new synchronized application benchmark accompanied the KPM excerpt.

## Working configuration

| Component | Value |
|---|---|
| Host | `spark-7c40`, DGX Spark, arm64, Ubuntu 24.04.5 |
| OCUDU | `050a2bb`, existing CU/DU binaries, B210/UHD |
| FlexRIC | `br-flexric`, `736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8` |
| Compiler and build | GCC 13.3, Debug, `build-ocudu` |
| Options | `E2AP_V3`, `KPM_V3_00`, `NONE_XAPP`, `XAPP_MULTILANGUAGE=OFF` |
| E2 / E42 listeners | `127.0.0.1:36421` / `127.0.0.1:36422`, SCTP |
| DU configs | `du1_b210_n78_20mhz.yml` followed by `du1_flexric.yml` |
| KPM | Function ID 2, Format 4, 1000 ms, five DU measurements |
| Radio | B210 `3271233`, USB 3, 23.04 MS/s, n78, 20 MHz, PCI 1, carrier 650000 / SSB 649632 |
| Current gain | Inspected TX 70 / RX 40; earlier 2026-10-05 UE traffic used TX 80 / RX 40 |

Use the [installation guide](../setup/software_installation_and_drivers.md#8-flexric-installation-on-spark), [canonical runtime steps](../runbooks/full_reproduction_runbook.md#9-confirm-rf-and-start-the-du), and [Spark](../single_ue/spark_quick_commands.md) / [UE laptop](../single_ue/ue_laptop_quick_commands.md) quick commands to reproduce.

## Initial installation and E2 Setup

The missing packages were `cmake-curses-gui`, `libconfig-dev` and `libconfig++-dev`; existing build tools, SCTP, SWIG and Python development files were present. FlexRIC was initially pinned to `1a3903a7`, configured with `E2AP_V3`, `KPM_V3`, `NONE_XAPP` and Python OFF, then built and installed. Both localhost SCTP ports listened successfully.

The DU overlay enabled `enable_du_e2`, KPM, RLC/scheduler metrics and a 1000 ms DU report period. The two-config `--dryrun` returned 0. This checks parsing only and does not start the radio. No OCUDU rebuild or ZeroMQ radio change was required.

MongoDB returned `{ ok: 1 }`; all ten required Open5GS services were active. CU connected to AMF and listened for F1. DU initialized B210 over USB 3, completed F1 and E2 connections and started. RIC registered PLMN `001/01`, node ID 411, `ngran_gNB_DU`, DU ID 1 and KPM RAN function ID 2. SCTP N2, F1 and E2 associations were established.

## Subscription failure and codec diagnosis

The first C xApp connected to RIC and discovered one DU, but its Format 4 subscription failed. The observed sequence was:

1. DU received the KPM subscription and failed Action Definition decoding, including `Invalid choice id=38 for choice type meas_type_c`.
2. DU returned Subscription Failure.
3. FlexRIC asserted in `e2ap_handle_subscription_failure_ric` with `Not implemented` and aborted.
4. The xApp then timed out waiting for its subscription response and aborted.

The old compiled KPM codec used modified ASN.1 extension boundaries. Source inspection found these differences from OCUDU's standard encoding:

| Field | Old FlexRIC `1a3903a7` | Standard codec in `73650812` |
|---|---|---|
| Action Definition Formats 4/5 | Root CHOICE alternatives | Extension alternatives |
| Test condition S-NSSAI | Root CHOICE alternative | Extension alternative |
| Format 1 distribution range | Root optional field | Extension optional field |
| Indication Message Format 3 | Root CHOICE alternative | Extension alternative |

The Format 4 selection was therefore decoded as the wrong format and corrupted later field interpretation. Disabling the RIC assertion would not correct this encoding mismatch. Absence of a UE did not cause the subscription rejection; an eligible UE is needed later to produce Format 4 reports.

## Version correction and offline verification

FlexRIC was changed to `736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8`. Its generated codec uses standard KPM ASN.1. A separate `build-ocudu` directory used the new `KPM_V3_00` option, GCC 13.3 Debug and multilanguage OFF. The complete build and install succeeded. The built and installed KPM libraries had identical SHA-256 values:

```text
74f62b45b8ac37b770b20e53a39e0fa19eac5944ebb0b4a977e5a906b40f2711
```

This is the session's artifact hash; reproduction checks equality between its own built and installed files.

Offline cross-codec tests used synthetic messages:

| Test | Old `1a3903a7` | New `73650812` |
|---|---|---|
| Format 4 subscription encoded by FlexRIC, decoded by existing OCUDU | Fails; incorrectly selects Format 2 | Passes: Format 4, SST condition 1, 1000 ms, all five metric names and no-label labels |
| Format 1 subscription decoded by OCUDU | Passes | Passes |
| Event trigger decoded by OCUDU | Passes, 1000 ms | Passes, 1000 ms |
| OCUDU Format 3 indication decoded by FlexRIC | Not tested | Passes: synthetic gNB-DU UE ID 7, five measurement names and integer values 101–105 |

These checks validate encoding/decoding for the test messages. The synthetic UE and values are not radio measurements.

## Successful live subscription

After stopping DU, starting the new FlexRIC and restarting DU, E2 Setup again completed and RIC accepted KPM function ID 2. The new C xApp output included:

```text
[xApp]: Registered E2 Nodes = 1
Connected E2 nodes = 1
xApp subscribes RAN Func ID 2 in E2 node idx 0, nb_id 411
[xApp]: SUBSCRIPTION RESPONSE rx
[xApp]: Successfully subscribed to RAN_FUNC_ID 2
[xApp]: E42 SUBSCRIPTION DELETE RESPONSE rx
Test xApp run SUCCESSFULLY
```

RIC remained running and handled subscription deletion. The monitor's approximately 10-second observation window and subsequent exit are expected for this revision.

## Actual UE KPM reception

The operator then captured repeated reports from E2 node `411`, type `ngran_gNB_DU`, with `UE ID type = gNB-DU, gnb_cu_ue_f1ap = 14`. Selected consecutive reports contained:

| Metric | First sample | Second sample | Unit and interpretation |
|---|---|---|---|
| `DRB.RlcSduDelayDl` | 17.30 | 15.80 | 0.1 ms; **1.730 / 1.580 ms** RLC SDU delay |
| `DRB.UEThpDl` | 253.00 | 242.00 | kbps; **253 / 242 kbps** RLC-derived throughput |
| `DRB.UEThpUl` | 14163.00 | 14675.00 | kbps; **14.163 / 14.675 Mbit/s** RLC-derived throughput |
| `RRU.PrbTotDl` | 0 | 0 | Integer percentage; **0%** reported |
| `RRU.PrbTotUl` | 86 | 86 | Integer percentage; **86%** reported |

This establishes live UE metric reception through DU → E2 → RIC → xApp. The captured xApp log also ended with `Test xApp run SUCCESSFULLY`. UE ID `14` is an observation, not a fixed identifier for later runs. The configured period is 1000 ms; the pasted excerpt has no receive timestamps to verify precise cadence. It also lacks synchronized iperf direction, duration and sender/receiver results.

Units were checked against the existing OCUDU source in `lib/e2/e2sm/e2sm_kpm/e2sm_kpm_metric_defs.h` and provider formulas in `e2sm_kpm_du_meas_provider_impl.cpp`. Throughput uses RLC PDU byte counters, so it does not establish application goodput. The delay is an RLC SDU measurement, not RTT. DL PRB usage can round down to zero while small DL throughput remains: the per-UE PRB formula uses integer division, and scheduler/RLC samples come from separate reports. These samples do not isolate which effect produced the zero.

The same excerpt printed huge negative `KPM-v3 ind_msg latency` values, including `-938098313332490154 μs`. This is an invalid timestamp display. OCUDU's `e2sm_kpm_report_service_impl.cpp` sends a 64-bit NTP fixed-point collection timestamp. FlexRIC's original KPM decoder uses `ntohll` with incorrect 32-bit half ordering on this little-endian host; `examples/xApp/c/monitor/xapp_oran_moni.c` then subtracts the result from Unix microseconds. A subsequent [timestamp repair](2026-10-07_flexric_latency_fix.md) normalizes NTP bytes to Unix microseconds and labels the signed display `report_age_us`. Source, build and offline tests passed; an initial preview passed without UE indications. After installation verification, a later UE ID `2` run received 12 report-age values of **499–717 microseconds**, all five metrics and normal subscription deletion/exit. Live timestamp display is now verified. The quick metric summary omits the old invalid display.

## Next acceptance and diagnostics

Repeat the RM500Q private traffic test and Spark xApp together, recording current UE ID, application direction, duration, rate, report timing and DU RF-error growth. Initial actual UE KPM reception is now verified; synchronized traffic correlation, precise cadence and sustained stability remain acceptance work.

Keep these runtime details in mind:

- CU and RIC must be available before DU. E2 Setup waits for F1 component data; restarting RIC requires restarting DU for a fresh E2 association.
- RLC metrics must be enabled for the UE reports used here. Without an eligible UE, subscription can succeed without periodic indications.
- `log.all_level` does not override the separate E2AP logger default. Set only `log.e2ap_level: debug` when more E2 evidence is needed, then restart DU after RIC.
- Install the tested timestamp repair before interpreting the new `report_age_us` display. It includes processing and queuing, and is not pure transport latency; see the repair record.
- The current provider accepts the example's S-NSSAI condition without enforcing a slice filter. Do not treat its output as validated per-slice isolation.

Use narrow E2/KPM excerpts when diagnosing failures; keep authentication material and complete RAN INFO logs outside Git. Stop traffic/xApp and the laptop PDU first, then DU, RIC, CU and core; preserve MongoDB data.

## DU RF metrics extension: offline package, 2026-10-09

The cumulative [OCUDU patch](../../patches/ocudu/050a2bb-du-rf-metrics.patch), [FlexRIC monitor patch](../../patches/flexric/73650812-du-rf-metrics.patch), and [dedicated xApp configuration](../../configs/flexric/xapp_du_rf_metrics.conf) add DU PUSCH RSRP and SNR reporting. The exported name follows the DU's existing `pusch_snr_db` naming. **The SNR-named package passed offline verification; the live source checkouts, deployed binaries and services have not been updated, and live RF acceptance remains pending.** The earlier five-metric results above remain the deployed baseline. This package operates on the DU measurement path; it does not add CU measurements.

These are replacements for the earlier [OCUDU RSRP patch](../../patches/ocudu/050a2bb-pusch-rsrp.patch) and [FlexRIC RSRP patch](../../patches/flexric/73650812-pusch-rsrp.patch), which are retained as historical artifacts. Apply the cumulative patches instead of the earlier RSRP patches; do not stack both versions. The current host checkouts have not received either RF package. If another checkout already has the earlier RSRP package, reverse those two patches first, preserving the existing FlexRIC timestamp repair, then check and apply the cumulative package.

| Output | Source and meaning | Unit |
|---|---|---|
| `FALCON.PUSCH.RSRP.dBFS` | Latest scheduler-window mean of available PUSCH DM-RS received-power reports | Software dBFS |
| `FALCON.PUSCH.SNR.dB` | Latest scheduler-window value of the DU's existing `pusch_snr_db` field | dB |
| `RSRQ = n/a` | Local xApp capability notice: `source=xapp-capability-status reason=unavailable_in_du` | No measured value |

The old provider's `RSRP` and `RSRQ` getters both returned an integer derived from the first UE's `pusch_snr_db`. The cumulative patch replaces the dummy `RSRP` registration with the vendor RSRP metric and removes the incorrect `RSRQ` registration/getter. SNR reporting reads the existing `pusch_snr_db` field without changing its calculation. Internally this field aggregates the PHY-selected `ul_sinr_dB`; the public metric uses the requested legacy SNR name. The xApp subscribes to this measured value and displays `n/a` only when a sample is missing or invalid.

Both RF metrics advertise UE-level `NO_LABEL` support and reject undefined node/cell aggregation or label expansion. The provider translates each requested UE's gNB-CU UE F1AP ID into its internal DU index, then searches the matching scheduler snapshot; internal indices are not vector offsets. Finite measurements use `REAL`, preserving fractions, negative values and a measured zero. The scheduler snapshot gains `nof_pusch_snr_reports`, allowing the provider to distinguish measured `0 dB` from the legacy zero produced when no SNR samples are available. Missing, disconnected, incompatible or unmeasured UEs receive one `noValue` record per requested metric, maintaining request order and cardinality.

RSRP remains software dBFS, not calibrated dBm, UE-reported downlink RSRP, or standard `L1M.UL-SRS-RSRP`. Both window means follow the existing scheduler's averaging of the reported dB values. The package does not change RU normalization or recover values already clamped by PHY/FAPI; `ovl` readings require separate investigation.

The `t` console table's UL `rsrp` column and the new xApp metric read the same `pusch_rsrp_db` field. For the same UE and scheduler window, their underlying value is identical. The console formats negative values to one decimal and clamps them to at least `-99.9`; it displays `ovl` for any finite value greater than or equal to zero. The xApp reports the finite value using `REAL` and prints two decimal places without that console clamp or `ovl` substitution. For example, a raw `-12.94` appears as `-12.9` in the console and `-12.94 dBFS` in the xApp; raw `0.0` appears as `ovl` and `0.00 dBFS` respectively. Missing measurements appear as `n/a` in both. Align the UE and window when comparing: the console uses C-RNTI, while the xApp uses UE F1AP ID and reads the most recent snapshot on a separate E2 timer.

The xApp subscribes to the original five DU measurements plus the two RF metrics: seven names in one Format 4 subscription at 1000 ms. Both RF values require `REAL`; `noValue`, non-finite values and incorrect integer encodings display `n/a`. Each received UE/report row also prints the local RSRQ capability notice above. This notice carries an explicit source and is not an E2 measurement, subscription or advertised RAN capability. The monitor runs until Ctrl+C or SIGTERM and then requests normal subscription deletion.

Each measurement line includes PLMN, node type, gNB node ID, CU/DU ID when present, UE F1AP ID, `header_time_us` and `sample_idx`. Use the complete node/DU identity plus UE F1AP ID for multi-DU correlation: a shared CU can give several DUs the same gNB ID. F1AP UE IDs are context identifiers; they are not console C-RNTIs or subscriber IMSIs and may change or be reused after reconnection. `sample_idx` is a row index within one report, not a global sample sequence. Nodes are discovered at startup, so relaunch the xApp after adding a DU. UE discovery still depends on the existing RLC metrics path; keep both `enable_sched` and `enable_rlc` enabled. The template's S-NSSAI condition is not enforced as a slice filter by this OCUDU provider.

The 1000 ms xApp setting populates the E2 event-trigger period and action granularity; the scheduler source period is configured separately through `du_report_period`. E2 collects the most recent source snapshot and the timers are not guaranteed to align. A faster subscription can repeat an older source window. `header_time_us` is the KPM header time, not a PHY sample timestamp: current OCUDU clears the message and updates the header before packing that header. `report_age_us` therefore cannot establish the RF sample's age or the full source-to-xApp delay. See the [timestamp record](2026-10-07_flexric_latency_fix.md#meaning-of-report_age_us).

### Offline verification

Run these checks before applying the cumulative package to the source checkouts. They reuse existing OCUDU and FlexRIC build dependencies, stage the changed sources under `/tmp`, and do not launch a network or radio service. FlexRIC must already contain the [timestamp repair](2026-10-07_flexric_latency_fix.md).

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
python3 scripts/ocudu/test_du_rf_metrics.py
python3 scripts/flexric/test_du_rf_metrics.py \
  --wire-fixture /tmp/falcon-du-rf-check/du-rf-indication.bin
```

All 13 OCUDU tests passed for the SNR-named version after supplying the new FlexRIC action fixture. They cover distinct RSRP/SNR values, sparse and reordered UE identifiers, fractions, a measured zero versus an absent SNR sample, missing/non-finite values, replaced snapshots, label/scope admission, and actual Style 4 collection and Format 3 APER encoding. The real scheduler CRC-to-report test covers an absent sample, measured zero, the expected two-sample mean, and an empty next window that resets the count and returns `noValue`.

The FlexRIC check compiled and linked the monitor, exercised its callback through the real KPM decoder, encoded the actual seven-metric subscription and passed OCUDU admission. The callback cases also passed for incorrect RF integer encoding, unavailable name/value mapping, incomplete reports, different DU identities, explicit local capability notices and the stop flag. The first command alone passes 12 tests and skips the external subscription case until the second command supplies its fixture. Live SDK subscription deletion is separate acceptance work.

The synthetic cross-codec fixture has three UE F1AP IDs and two RF columns:

| UE F1AP ID | RSRP record | SNR record |
|---|---|---|
| `1007` | `REAL -13.125` | `REAL 21.75` |
| `2091` | `REAL 0.0` | `REAL 0.0` with an available sample |
| `3199` | `noValue` | `noValue` |

The DU indication fixture is 223 bytes. It verifies serialization and UE association; its values are synthetic and do not establish live cadence. Artifacts and logs are under `/tmp/falcon-du-rf-check/` (`provider.log`) and `/tmp/falcon-du-rf-flexric-check/` (`callback.log`, `subscription.log`). The offline harness links KPM's ASN runtime before the SDK's E2AP runtime to avoid collisions between their same-named static functions. The production monitor follows its normal SDK-only link and loads service-model plugins dynamically; no new plugin installation is required.

### Apply and rebuild in the operator terminal

The OCUDU base is `050a2bb72e1d794cd60570d809987c1fcda3e54b`. The FlexRIC base is `736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8` with the timestamp repair already applied. If the earlier RSRP-only patches are present, use `git apply --reverse --check` and then `git apply --reverse` with those earlier paths before proceeding. Do not reverse the timestamp repair or force a patch over unrelated changes. On the current host, that RF-patch reversal is unnecessary because the RF patches have not been applied.

Check the cumulative patches against both source checkouts:

```bash
git -C /home/nyu/ocudu apply --check \
  /home/nyu/Desktop/Falcon_repo/Falcon/patches/ocudu/050a2bb-du-rf-metrics.patch
git -C /home/nyu/flexric apply --check \
  /home/nyu/Desktop/Falcon_repo/Falcon/patches/flexric/73650812-du-rf-metrics.patch
```

Stop current traffic and xApp, then DU and RIC through their existing terminals before applying and rebuilding. Keep the working CU/core configuration. If a check fails, inspect the local changes and base revision before proceeding.

```bash
git -C /home/nyu/ocudu apply \
  /home/nyu/Desktop/Falcon_repo/Falcon/patches/ocudu/050a2bb-du-rf-metrics.patch
git -C /home/nyu/flexric apply \
  /home/nyu/Desktop/Falcon_repo/Falcon/patches/flexric/73650812-du-rf-metrics.patch

cmake --build /home/nyu/ocudu/build --target odu_split_8 -j 8
cmake --build /home/nyu/flexric/build-ocudu --target xapp_oran_moni -j 8
```

Build the complete `odu_split_8` target and its dependencies after adding the scheduler snapshot field. The changed struct is shared by metric producers and consumers; replacing only one provider object or hot-swapping a library is insufficient. This build command lets CMake rebuild all affected dependencies. The new xApp can use the already working timestamp-repaired KPM plugin; it requires no `/usr/local` binary or plugin replacement.

The DU E2 overlay already enables scheduler/RLC metrics and a 1000 ms source period. Check the rebuilt DU's configuration parsing without starting RF:

```bash
/home/nyu/ocudu/build/apps/du_split_8/odu \
  -c /home/nyu/ocudu/configs/du1_b210_n78_20mhz.yml \
  -c /home/nyu/ocudu/configs/du1_flexric.yml --dryrun
```

Restart RIC before DU using [runbook stage 9](../runbooks/full_reproduction_runbook.md#9-confirm-rf-and-start-the-du), allowing fresh E2 Setup to advertise both custom measurements. Reconnect the UE and overlap monitoring with uplink traffic. Run the rebuilt xApp directly:

```bash
/home/nyu/flexric/build-ocudu/examples/xApp/c/monitor/xapp_oran_moni \
  -c /home/nyu/Desktop/Falcon_repo/Falcon/configs/flexric/xapp_du_rf_metrics.conf
```

Expect a successful function-ID-2 subscription, correctly associated RSRP lines in `dBFS` and SNR lines in `dB`, or explicit `n/a` for missing values. RSRQ should remain a local unavailable-capability notice. Validate measured values against the DU's corresponding scheduler window, multi-UE mapping, missing-measurement behavior, intervals and normal Ctrl+C deletion. Console formatting/clamping need not reproduce every raw decimal. Keep 1000 ms until live acceptance passes; shorter reporting requires coordinated source/xApp changes plus load and freshness checks. Neither header time nor report-age output substitutes for a PHY measurement timestamp.

To revert, stop traffic/xApp/DU/RIC, check and reverse these cumulative patches, rebuild both complete targets, and return to the prior five-metric configuration. This preserves the timestamp repair and unrelated local changes. The earlier RSRP-only package remains available as a historical alternative; it is not automatically reapplied by reverting this package.
