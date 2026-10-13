# Development Handoff

Updated: 2026-10-12. Continue from **3660-MHz single-UE/DU1 uplink functionality and actual five-metric KPM reception verified; RF stability pending**, plus completed two-SIM provisioning and modem UICC preparation. Read [Progress and Configuration](project_progress_and_configuration.md), the [Full Reproduction Runbook](full_reproduction_runbook.md), the [FlexRIC record](troubleshooting/2026-10-07_flexric_bringup.md), and [SIM Provisioning and Dual-UE Preparation](sim_provisioning_and_dual_ue.md). Daily commands are summarized separately for [Spark](spark_quick_commands.md) and the [UE laptop](ue_laptop_quick_commands.md).

## Achieved and pending

The **2026-10-12 Plan 3 checkpoint** migrated DU1 from 3750 to 3660 MHz within n78, preserving PCI 1 and radio serial `3271233`. Actual startup gave carrier `644000`, SSB `643680`, 20 MHz, 30 kHz SCS, and USB 3. The complete new configuration uses TX 70 / RX 35 and includes E2/KPM; its maintained and deployed copies have the same SHA-256. UE `10.45.0.2 / wwan0` passed ping with 5/5 replies and 0% loss, and a 30-second TCP uplink with receiver **17.0 Mbit/s** and sender Retr **0**. The xApp received **12 complete five-metric rows for UE F1AP ID 5**, report age 508–820 µs, and completed subscription/deletion with its success marker. [Daily log](../dev_logs/2026-10-12_ruibin.md) and [evidence](evidence/2026-10-12_du1_3660mhz/manifest.json) retain the details.

This checkpoint is **uplink only**. RF stability remains pending: 117 underflows were observed by 11:39:44 EDT. The actual IMSI, SIM card, and bearer ID were not retained in these acceptance excerpts; do not infer registration of either new subscriber from UE F1AP ID 5. Dual-DU operation and full Plan 3 acceptance remain pending.

The historical 2026-10-05 experiment established private n78 detection, PRACH/PUSCH CRC OK, SA registration/authentication, packet attachment, IPv4 PDU setup, a connected static bearer, manually configured WWAN, and laptop-to-Spark application traffic. The first 10-second TCP uplink was sender 6.29 Mbit/s / receiver 5.09 Mbit/s, sender Retr 0. Sustained throughput, downlink, UDP and live video are not yet validated.

The 2026-10-07 session added FlexRIC, verified DU E2 Setup, and completed the C KPM xApp subscription and deletion. A later run received all five actual DU metrics for UE F1AP ID `14`: selected UL throughput samples were 14.163–14.675 Mbit/s at the RLC measurement layer, with UL PRB usage 86%. Next acceptance work is synchronized KPM/application traffic correlation, cold-start/new-laptop reproducibility and traffic characterization. Dual FR1/FR3 operation, AI prediction and MPTCP steering remain future work; preserve and document the single-link baseline while preparing the second path.

Phase 5 preparation has advanced: Open Cells `OC011830` is personalized as IMSI `001010000000101` / ICCID `89860061100000000830` / `OpenCells101` / MSISDN `00000101`; `OC011831` is `001010000000102` / `89860061100000000831` / `OpenCells102` / `00000102`. Both use PLMN `00101`, passed Milenage at SQN **64** with HSS reference **96**, and showed ready USIM applications through Quectel. SIM2 was checked first in the original modem, then in the second physical RM500QGL_VH, IMEI `863305041980706`; the original unit's previously observed IMEI is `863305041978437`.

This completes SIM/modem preparation, not new-subscriber registration. Matching Open5GS records, SQN representation checks, DU2/radio deployment and simultaneous end-to-end links remain pending. The intended SIM1 → modem #1 → DU1 and SIM2 → modem #2 → DU2 paths share CU/Open5GS, then expose two laptop WWAN/IP paths for MPTCP. Shared PLMN `00101` does not automatically enforce those SIM-to-DU associations; verify cell selection and the actual serving cell.

## Stable infrastructure facts

- Spark `spark-7c40`: Ubuntu 24.04.5, aarch64, 20 cores, 121 GiB, NVIDIA GB10; kernel `7.0.0-1019-nvidia`, PREEMPT_DYNAMIC.
- OCUDU `/home/nyu/ocudu`, `release_26_04` / `050a2bb`, Clang 18.1.3. CU executable `build/apps/cu/ocu`, DU `build/apps/du_split_8/odu`.
- FlexRIC `/home/nyu/flexric`, pinned `736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8`, GCC 13.3 Debug, `build-ocudu`, `E2AP_V3` / `KPM_V3_00`, `NONE_XAPP`, multilanguage OFF. Installed binaries/configs use `/usr/local/bin/flexric`, `/usr/local/etc/flexric`, `/usr/local/lib/flexric`.
- Configuration paths: `/home/nyu/ocudu/configs/cu.yml` and current `du1_b210_n78_3660mhz.yml`; `du1_b210_n78_20mhz.yml` is preserved history; Open5GS `/etc/open5gs/{nrf,amf,smf,upf}.yaml`.
- Current `configs/du1_b210_n78_3660mhz.yml` includes DU E2, KPM, RLC/scheduler metrics and a 1000 ms DU report period in one file. `configs/du1_flexric.yml` remains a historical reference. FlexRIC SCTP ports are E2 `36421`, xApp E42 `36422`, both `127.0.0.1`.
- Open5GS `2.8.0~noble5`; MongoDB 7 Docker container `open5gs-mongo`, image `mongo:7.0-jammy`, volume `open5gs-mongo-data`; native MongoDB 8 disabled.
- B210 `3271233` / UHD 4.6.0.0 / USB 3; n78, carrier ARFCN 644000 / 3660 MHz, SSB ARFCN 643680, 20 MHz, 30 kHz, PCI 1, SISO.
- The current 2026-10-12 DU1 file uses **TX 70 / RX 35**. Historical 2026-10-05 traffic used TX 80 / RX 40; the 2026-10-07 file used TX 70 / RX 40. Preserve the actual gain and record it per test. Sample rate 23.04 MS/s, internal clock, clock_ppm 0, freq_offset 0; CU/DU INFO logs.
- Private identity PLMN `00101`, TAC 7, SST 1, DNN `internet`, test IMSI `001010000000001`, subscriber session type 1 / IPv4 only.
- UE RMU500EK / RM500QGL_VH, firmware `RM500QGLABR13A03M4G`. NR5G-only and disable-mode 2 (NSA disabled on this firmware), current lock PCI 1 / SSB 643680 / SCS 30 / n78; open the current laptop AT port with `sudo minicom -D /dev/ttyUSB2 -b 115200`.
- Addresses: CU N2/N3 `127.0.0.1`; AMF `127.0.0.5`; CU F1 `127.0.10.1`; DU F1 `127.0.10.2`; UPF `127.0.0.7`; SMF `127.0.0.4`; Spark local private gateway `10.45.0.1` on ogstun.

The current CU has an explicit `ngu` bind; it was not proven necessary as a root-cause repair. The latest DU has no explicit old `otw_format: sc12` entry. Preserve the actual configuration and inspect runtime sockets before changing either.

## Resolved failures and their evidence

| Failure | Resolved cause |
|---|---|
| Reject 95 / NRF discovery 500 / AMF HTTP 400 | NRF serving PLMN `999/70` corrected to `001/01` |
| Reject 7 / UDR 404 / missing SUPI/IMSI | Exact SIM subscriber absent and then provisioned |
| Public-network drift / lock state errors | NR/SA selection followed by private SSB lock; settings rechecked after reboot |
| Connected registration but CallFailed / CU rejects IPv4v6 | Subscriber type 3 → type 1; IPv4 simple-connect |
| Historical RF underflow/late | Previously mitigated by the performance script and privileged RAN launch; underflows recurred on 2026-10-12 and remain unresolved |
| Static bearer connected but no WWAN IP | Actual bearer IP/prefix/MTU applied to laptop interface |
| KPM Format 4 subscription fails, RIC asserts, xApp times out | `1a3903a7` modified ASN.1 codec replaced by standard codec in `73650812`; subscription/deletion then passed |
| SIM setup APT HTTP timeouts | HTTPS Ubuntu archive/security sources worked; this was separate from reader/PC/SC operation |
| `program_uicc_pcsc` cannot load `libccid.so` | Command-local `LD_LIBRARY_PATH=/lib/pcsc/drivers/ifd-ccid.bundle/Contents/Linux` supplied the existing driver library |

Private QSCAN and PUSCH CRC OK at 20–33 dB SINR established usable downlink acquisition and uplink with RX gain 40. The unsupported IMS request was not the `internet` failure. Do not reopen these diagnoses without contradictory new evidence.

## Working procedures

1. Check current processes/services; historical verification does not imply live components are running.
2. During interactive bring-up, give one next step with exact host label, expected evidence and success/failure layer. Use real command output before advancing.
3. Use the canonical runbook service set/order: NRF, SCP, UDR, UDM, AUSF, PCF, NSSF, UPF, SMF, AMF. BSF/SEPP are optional, EPC services are legacy, WebUI is administration.
    Run CU and FlexRIC before DU. DU E2 Setup depends on F1 Setup component data; reconnecting after a RIC restart requires a DU restart. Start the xApp after RIC has registered the DU.
4. Preserve the NVIDIA kernel, compiler defaults, boot parameters and current working RAN configuration. No PREEMPT_RT, CPU isolation, IRQ or hugepage changes without a specific evidenced need.
5. The recorded performance script already sets 20 performance governors, disables KMS polling and configures four network-buffer values at 33554432. Check after reboot. CU/DU launch with sudo; recurring RF failures remain a monitoring issue.
6. Check band, carrier/SSB, gain, serial and authorized lab conditions before RF startup. Never probe/benchmark B210 while DU owns it. Gain values are not calibrated dBm.
7. Never infer authentication secrets (Ki/K, OP or OPc) from IMSI or ICCID; keep credentials, authentication vectors and derived RAN keys out of Git. The new cards' independent pairs are in `~/sim_du1_credentials.txt` and `~/sim_du2_credentials.txt`, permission 600; never cross-copy them between subscriber `...101` and `...102`. Preserve the files because the secrets cannot normally be read back from the USIM. Avoid unnecessary repeat Milenage tests, which advance SQN. Sanitize INFO logs.
8. Dynamically discover modem, SIM, bearer, QMI/AT port, WWAN interface and allocated UE address. With two modems, verify equipment ID and actual SIM IMSI instead of selecting the first `mmcli -L` result. QMI uses proxy. Query the active bearer rather than EPS initial-bearer display. For SIM swaps, disable the selected modem and power it off before changing the card, then rediscover it after reconnection.
9. Keep laptop Wi-Fi for management. Local Spark application traffic requires neither Internet NAT nor a laptop default-route change.
10. Record tests by direction, duration, rate, retransmission/jitter/loss and concurrent RF-error growth. Do not present first TCP success as sustained performance.
11. Stop traffic and let the xApp delete its subscription, then release PDU/laptop configuration, stop DU, FlexRIC, CU and core. Keep MongoDB data; optional/legacy services need explicit cleanup for full shutdown.
12. Documentation maintenance does not authorize starting services, RF, benchmarking, committing or pushing. The operator requested no automatic push/merge for this update.
13. Write all documentation in US English, including comments and operator prompts in documented commands.

## Next session

First diagnose the current RF underflows and repeat **uplink-only** traffic with retained KPM timing and error counts. Capture the actual IMSI/bearer/serving-cell ledger and verify cold-start repeatability. Preserve the working 3660-MHz carrier and SSB lock.

Prepare the two new subscribers using [SIM Provisioning and Dual-UE Preparation](sim_provisioning_and_dual_ue.md). Add/verify `001010000000101` with the pair from `~/sim_du1_credentials.txt` and `001010000000102` with the pair from `~/sim_du2_credentials.txt`; use SST 1, DNN `internet` and IPv4 session type 1. Check the installed Open5GS SQN representation before applying the programmer's reference **96**, and preserve the verified single-link subscriber `001010000000001`.

Then prepare distinct DU/cell/radio identities and CU + DU1 + DU2, confirm each modem registers through its intended cell, establish two independent PDU sessions and laptop WWAN/IP paths, and test MPTCP. Extend the already verified DU1 FlexRIC/KPM collection to both DU/UE identities after dual-link reception works; AI prediction, active steering and blockage/QoE comparison follow later.

The 30-second TCP uplink and five-metric reception are already functionally verified at 3660 MHz. Next acceptance work is sustained uplink stability, precise traffic/KPM timing correlation, and cold-start reproducibility; downlink is not required for the current scope. Extend to DU2 only with its own radio/configuration and independently evidenced UE path.

The original example's huge negative `KPM ... ind_msg latency` is invalid. The [timestamp repair](troubleshooting/2026-10-07_flexric_latency_fix.md) is applied to local FlexRIC source, rebuilt, tested and installed; do not discard these local source changes when switching commits. It normalizes v3 ASN timestamps to Unix microseconds and prints signed `report_age_us`. Installed KPM library and `xapp_oran_moni` match the repaired build. Following the initial preview without UE indications, an actual UE ID `2` run produced 12 report-age values of **499–717 microseconds** and completed subscription deletion/exit normally. Live time display is verified; precise delay accuracy and synchronized application performance remain open. Follow [Spark step 7a](spark_quick_commands.md#7a-verify-reports-after-the-timestamp-repair) for repeat runs. Selected UE `2` DL RLC delay samples 13.80–14.40 in 0.1 ms units mean **1.380–1.440 ms**; UE IDs are not fixed.

Use the [Full Reproduction Runbook](full_reproduction_runbook.md) for operating commands and [Software Installation, Drivers, and OCUDU Environment](software_installation_and_drivers.md) for dependencies, driver inspection, compiler/build settings, and installation issues.
