# Spark Wired DU2 Quick Start

Updated: 2026-11-19. Use with the
[Laptop wired UE2 guide](laptop_wired_ue2_quick_start.md).

This profile runs **CU + DU2 + UE2** over a direct 3.6-GHz cable connection,
without DU1 or Pi-Radio. The recommended
[single-terminal automatic entry point](#single-terminal-automatic-startup-recommended)
reuses `spark_auto.py`, the same controller as the dual-DU and DU1 profiles.
The operator enters the startup command manually; the script then manages the
processes in order: **MongoDB -> Core -> RIC -> CU -> DU2 -> xApp**.
Connect UE2 on the Laptop after `[RUNNING]`. The Spark controller does not start
or stop the Laptop watcher.

Sections 2-7 retain an alternative manual procedure using separate terminals.
Choose one mode. Manual mode may reuse healthy Core/RIC/CU services. Automatic
mode requires the old RAN/xApp to stop normally first and does not adopt existing
manual RIC/CU/DU processes. The controllers share a lock and run one at a time.

## 1. Fixed Profile and Wiring

| Parameter | Current setting |
| --- | --- |
| B210 | Serial `328B021`; USB 3; logical RF port `0` is RF A |
| DU2 | n78 / 3600 MHz / 20 MHz / 23.04 MS/s / 1T1R |
| Carrier / SSB ARFCN | `640000` / **`639648`** |
| PLMN / TAC / PCI / NCI | `00101` / `7` / `2` / `66C001` |
| TX / RX gain | **70 / 35 dB**; digital TX backoff 12 dB |
| Accepted DL snapshot | RSRP **-99 dBm** / RSRQ **-11 dB** / SINR **24 dB**, 2026-11-19 |
| PUSCH power control | Native defaults; no additional closed-loop enable or SINR target |
| TDD | `DDDSUUUUUU`; 30-kHz SCS; 10 slots / 5 ms |
| DU statistics / DU KPM | **100 ms / 100 ms**, 27 DU measurements |
| CU identity / Core polling | 1000 ms / 1 s |
| UE2 DNN / IPv4 pool | `internet2` / `10.46.0.0/16` |
| Spark UE2 endpoint | `ogstun_2`, `10.46.0.1/16`, MTU 1400 |

The attenuators are external hardware; their losses are not configured by YAML:

```text
Quectel ANT3 -- ZFRSC-42-S+ common port 3 (no common attenuator)
                    +-- 50 dB (20+20+10) -- B210 RF A TX/RX
                    +-- 60 dB ------------ B210 RF A RX2
```

Other Quectel ports retain antennas and may still receive external OTA signals.
The accepted DL baseline fixes **TX 70, digital backoff 12 dB, the 50-dB DL
branch, no common attenuator**, and the frequency, bandwidth and TDD settings
above. The recorded QENG cell was PCI `2` / NCI `66C001`; `C5GREG: 0,1` confirmed
registration. Signal readings are measured snapshots, not configured targets.

On 2026-11-19, access and approximately -98 dBm / 24 dB DL measurements were
restored without the common attenuator. UL comparisons used RX gains 20, 30, 40
and 35. The selected **TX 70 / RX 35** 60-second run measured median UL SINR
**23.6 dB**, mean MAC throughput **39.41 Mbps**, CRC NOK **10.59%**, and iperf
receiver throughput **37.4 Mbps** with sender TCP Retr **0**. This is a repeat-run
baseline from one measurement, not an optimal-gain or long-term stability claim.

Only DU2 and the Laptop entry point need dedicated wired profiles. Reuse the
existing CU, RIC and xApp configurations:

| Component | Configuration |
| --- | --- |
| DU2 | [`du2_b210_n78_20mhz_wired.yml`](../configs/ocudu/dual_fr1/du2_b210_n78_20mhz_wired.yml) |
| CU | `/home/nyu/ocudu/configs/cu.yml` + [`cu_identity_e2.yml`](../configs/ocudu/cu_identity_e2.yml) |
| RIC | [`ric_ue_identity.conf`](../configs/flexric/ric_ue_identity.conf) |
| xApp | [`xapp_ue_identity_expanded.conf`](../configs/flexric/xapp_ue_identity_expanded.conf) |
| Identity mapping / publisher | [`local.json`](../configs/ue_identity/local.json) / [`subscriptions.json`](../configs/ue_identity/subscriptions.json) |

The dedicated DU2 YAML includes E2 and metrics settings. Load that DU file alone;
the 40-MHz OTA DU2 configuration/overlay belongs to the separate profile.
CU/RIC use the existing ports; reuse compatible listeners or stop them normally
before starting replacements.

## Single-Terminal Automatic Startup (Recommended)

### Prepare, Check and Start

Reuse the existing OCUDU/FlexRIC builds and Open5GS/MongoDB installation.
Require the UE2 subscriber `001010000000102`, SST 1, DNN `internet2`, IPv4, and
`ogstun_2` configured UP with `10.46.0.1/16`, MTU 1400 and its subnet route.
For an existing TUN with incorrect link state/MTU, manually run
`sudo ip link set dev ogstun_2 mtu 1400 up`. If the TUN is not configured, complete
section 3 first. Section 2 covers performance preparation after reboot.

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
python3 -B scripts/spark_wired_du2_auto.py --check
sudo python3 -B scripts/spark_wired_du2_auto.py
```

`--check` performs offline file/configuration checks without operating host
services or radios. Require `PASS: offline configs/artifacts; DU2 70/35` and the
path to this repository's wired20 YAML before running the startup command.

[`spark_wired_du2_auto.py`](../scripts/spark_wired_du2_auto.py) selects the wired
profile. Startup, PTYs, protocol readiness, health checks, command routing and
failure cleanup remain in the shared controller. The selected roles/configs are:

- CU + DU2 only; no DU1 YAML, B210 or UE1 subscriber is required.
- DU2 uses this repository's wired20 YAML, independently of deployed OTA DU2 files.
- The same ten Core services are managed; TUN/route checks select only `ogstun_2`
  and `10.46.0.0/16`.
- CU/RIC/xApp sources are snapshotted, with an isolated collector/plugin per run.
  The identity snapshot selects DU2 / `internet2` without rewriting shared `local.json`.
- DU statistics/KPM remain 100 ms, CU identity 1000 ms and Core polling 1 s.

Retain the printed `/tmp/falcon-spark-wired-du2-auto-XXXXXXXX` directory.
The controller requires CU E2, DU2 F1/E2, xApp E42/broker and both KPM subscriptions
before `[RUNNING]`. Then follow
[Laptop section 3](laptop_wired_ue2_quick_start.md#3-start-the-wired-ue2-watcher).
Update the Laptop wired files first. Startup verifies/restores PCI `2`, SSB
`639648`, SCS `30`, n78, and requires matching lock readback before registration
and PDU setup. After first installation or a modem reset, also verify the Laptop
USB AT port and NR SA / n78 settings.

### Status, Gains and Shutdown

Enter one command at a time in the Spark controller terminal:

```text
status
tx_gain 0 70
rx_gain 0 35
```

Expect **E2 nodes registered=2/2**, **DUs registered=1/1**,
**E2 nodes subscribed=2**, two KPM subscriptions and the current application count.
Gain commands control DU2 only. YAML already loads TX 70 / RX 35; the commands
above confirm or restore the baseline. Wait for each `Tx/Rx gain set to ...`
acknowledgement before entering another command. The controller accepts `status`,
gain commands and `stop`; native DU `t` is used only in manual mode.

Section 8 gives the recorded UL commands and log export procedure. The formal
MPTCP application uses `127.0.0.1:8765`, protocol 2 / profile `du27_bound_v1`.
Missing UE samples or application registration alone is not a component failure.

After traffic, stop the Laptop watcher and wait for successful cleanup, then
enter `stop` or Ctrl+C in Spark. Cleanup order is **xApp -> DU2 -> CU -> RIC ->
5GC**. Require both xApp E2 subscription deletions. Component failures use the
same cleanup. The ten Core services stop; Docker/MongoDB and external MPTCP
processes remain running.

From another Spark terminal, use the actual directory printed for this run.
The second command requests a normal shutdown:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
read -r -p 'Current automatic run directory: ' WIRED_AUTO_RUN
sudo python3 -B scripts/spark_wired_du2_auto.py --status "$WIRED_AUTO_RUN"
sudo python3 -B scripts/spark_wired_du2_auto.py --stop "$WIRED_AUTO_RUN"
```

The directory contains `status.json`, `manifest.json`, configuration snapshots,
`supervisor.log`, `ric.console.log`, `cu.console.log`, `du2.console.log`,
`xapp.console.log` and the final `publisher.json`. Run the manual startup commands
below only after the automatic controller has stopped.

For an explicit parameter comparison, select the same complete wired20 DU YAML
in both check and start commands:

```bash
python3 -B scripts/spark_wired_du2_auto.py --du2-config /path/to/du2-wired-candidate.yml --check
sudo python3 -B scripts/spark_wired_du2_auto.py --du2-config /path/to/du2-wired-candidate.yml
```

The selected file is copied to `du2.yml`; the manifest records its source path
and hash. The default profile remains TX 70 / RX 35 with no additional closed-loop
PUSCH enable or SINR target. Scheduler logs expose UL SINR, relative RSRP, CRC and
PHR. Offline checks and simulated tests are separate from hardware acceptance.

## 2. Manual Cold-Start Preparation

Stop old experiment watchers, xApp and RAN processes normally. Check the binaries
and build the compatible KPM plugin used by RIC/xApp. This block does not start
radios or services. Skip rebuilding while a healthy experiment uses the plugin.

```bash
(
  set -euo pipefail
  cd /home/nyu/Desktop/Falcon_repo/Falcon
  test -x /home/nyu/ocudu/build-integrated/apps/cu/ocu
  test -x /home/nyu/ocudu/build-integrated/apps/du_split_8/odu
  test -x /usr/local/bin/flexric/ric/nearRT-RIC
  bash scripts/ue_identity/build.sh
  /tmp/falcon-xapp-ue-identity --check-config configs/flexric/ric_ue_identity.conf
  /tmp/falcon-xapp-ue-identity --check-config configs/flexric/xapp_ue_identity_expanded.conf
  /home/nyu/ocudu/build-integrated/apps/cu/ocu \
    -c /home/nyu/ocudu/configs/cu.yml -c configs/ocudu/cu_identity_e2.yml --dryrun
  /home/nyu/ocudu/build-integrated/apps/du_split_8/odu \
    -c configs/ocudu/dual_fr1/du2_b210_n78_20mhz_wired.yml --dryrun
)
```

Require success for every command, DU `Time: 100` and CU `Time: 1000` in the
subscription configuration. `--dryrun` checks parsing/derived parameters only.
If binaries are missing, complete the
[build preparation](spark_quick_commands.md#1a-prepare-the-cu-identity-binary-and-isolated-flexric-plugin).
Rebuild the collector/plugin after `/tmp` has been cleared or after reboot.

After rebooting Spark, restore the existing performance settings in a separate
terminal and answer `Y` when prompted:

```bash
cd /home/nyu/ocudu
sudo ./scripts/ocudu_performance
```

## 3. Manual Core and ogstun_2 Preparation

Reuse Open5GS, MongoDB and the UE2 subscriber: IMSI `001010000000102`, SST 1,
DNN `internet2`, IPv4. If the subscriber is missing, follow the
[existing provisioning procedure](operations/setup/sim_provisioning_and_dual_ue.md#prepare-open5gs-subscribers).

```bash
sudo docker start open5gs-mongo
CORE_UNITS=(
  open5gs-nrfd open5gs-scpd open5gs-udrd open5gs-udmd
  open5gs-ausfd open5gs-pcfd open5gs-nssfd
  open5gs-upfd open5gs-smfd open5gs-amfd
)
sudo systemctl start "${CORE_UNITS[@]}"
systemctl is-active "${CORE_UNITS[@]}"
sudo ip link set dev ogstun_2 mtu 1400 up
ip -br -4 addr show dev ogstun_2
ip link show dev ogstun_2
ip -4 route show 10.46.0.0/16
```

Require ten `active` services, TUN UP / MTU 1400 / `10.46.0.1/16`, and route
`10.46.0.0/16 dev ogstun_2`. Correct the existing Core configuration if its address
differs before proceeding.

The xApp also uses the two existing read-only infoAPIs:

```bash
curl --noproxy '*' --fail --show-error --max-time 3 \
  'http://127.0.0.5:9090/ue-info?page=0&page_size=100'
curl --noproxy '*' --fail --show-error --max-time 3 \
  'http://127.0.0.4:9090/pdu-info?page=0&page_size=100'
```

Require valid JSON. Empty `items` is normal before the UE connects.

## 4. Manual RIC Terminal

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
RIC_RUN=$(mktemp -d /tmp/falcon-du2-wired20-ric.XXXXXXXX)
printf 'RIC logs: %s\n' "$RIC_RUN"
cp configs/flexric/ric_ue_identity.conf "$RIC_RUN/ric.conf"
set -o pipefail
stdbuf -oL -eL /usr/local/bin/flexric/ric/nearRT-RIC \
  -c "$RIC_RUN/ric.conf" 2>&1 | tee "$RIC_RUN/ric.log"
```

Require KPM SM ID 2 loaded from `/tmp/falcon-ue-identity-sm/`, E2 port `36421` and
E42 port `36422`. Leave the terminal open. Reuse an existing compatible RIC
instead of starting another listener.

## 5. Manual CU Terminal

```bash
cd /home/nyu/ocudu
CU_RUN=$(mktemp -d /tmp/falcon-du2-wired20-cu.XXXXXXXX)
printf 'CU logs: %s\n' "$CU_RUN"
cp configs/cu.yml "$CU_RUN/cu.yml"
cp /home/nyu/Desktop/Falcon_repo/Falcon/configs/ocudu/cu_identity_e2.yml "$CU_RUN/cu_identity_e2.yml"
set -o pipefail
sudo stdbuf -oL -eL build-integrated/apps/cu/ocu \
  -c "$CU_RUN/cu.yml" -c "$CU_RUN/cu_identity_e2.yml" \
  log --filename "$CU_RUN/cu.log" 2>&1 | tee "$CU_RUN/console.log"
```

Require N2 connection to AMF `127.0.0.5:38412`, E2 connection and
`==== CU started ===`. F1-C is `127.0.10.1:38472`; CU identity reports every
1000 ms. Keep the terminal open. A reused CU must include the identity/E2 overlay.

## 6. Manual DU2 Terminal

Create a new directory for each run. Execute the block directly in an interactive
terminal. `run_du_console.sh` records output/timing itself; use it without an
additional pipe or redirection.

```bash
cd /home/nyu/ocudu
DU2_RUN=$(mktemp -d /tmp/falcon-du2-wired20.XXXXXXXX)
printf 'DU2 logs: %s\n' "$DU2_RUN"
cp /home/nyu/Desktop/Falcon_repo/Falcon/configs/ocudu/dual_fr1/du2_b210_n78_20mhz_wired.yml "$DU2_RUN/du.yml"
bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/run_du_console.sh \
  "$DU2_RUN/startup.log" \
  sudo stdbuf -oL -eL build-integrated/apps/du_split_8/odu \
  -c "$DU2_RUN/du.yml" log --filename "$DU2_RUN/du.log"
```

Require USB 3, B210 serial `328B021`, and:

```text
Cell pci=2, bw=20 MHz, 1T1R, dl_arfcn=640000 (n78), dl_freq=3600 MHz, dl_ssb_arfcn=639648, ul_freq=3600 MHz
F1-C: Connection to CU-CP on 127.0.10.1:38472 completed
E2AP: Connection to Near-RT-RIC completed
==== DU started ===
```

The configuration already loads TX 70 / RX 35. Keep the terminal open and start
UE2 using the [Laptop guide](laptop_wired_ue2_quick_start.md). Require all nine
checks and `UE2 / n78-wired20 attempt N: SUCCESS`.

## 7. Manual xApp Terminal: 100 ms and 27 Metrics

CU + DU2 provides **two E2 nodes** and requires **two KPM subscriptions**.
The collector discovers nodes at startup, so wait for DU2 E2 Setup first.
Shared `local.json` admits DU1 and DU2; this run starts only DU2 and its bound
reports should identify DU2.

Prepare a fresh snapshot in the xApp terminal, then choose A or B below:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
WIRED_XAPP_RUN=$(mktemp -d /tmp/falcon-du2-wired20-xapp.XXXXXXXX)
printf 'xApp logs: %s\n' "$WIRED_XAPP_RUN"
cp configs/ue_identity/local.json "$WIRED_XAPP_RUN/local.json"
cp configs/ue_identity/subscriptions.json "$WIRED_XAPP_RUN/subscriptions.json"
cp configs/flexric/xapp_ue_identity_expanded.conf "$WIRED_XAPP_RUN/xapp.conf"
/tmp/falcon-xapp-ue-identity --check-config "$WIRED_XAPP_RUN/xapp.conf"
```

### A. Continuous Service for MPTCP Registration

```bash
set -o pipefail
python3 -B scripts/ue_identity/xapp_ue_identity.py \
  --collector /tmp/falcon-xapp-ue-identity \
  --config "$WIRED_XAPP_RUN/local.json" --e2-config "$WIRED_XAPP_RUN/xapp.conf" \
  --publish-config "$WIRED_XAPP_RUN/subscriptions.json" \
  --fresh-only --duration 0 --publisher-summary "$WIRED_XAPP_RUN/publisher.json" \
  2>&1 | tee -i "$WIRED_XAPP_RUN/xapp.log"
WIRED_XAPP_RC=${PIPESTATUS[0]}
printf 'xApp exit=%s\n' "$WIRED_XAPP_RC" | tee "$WIRED_XAPP_RUN/exit.txt"
```

Require `SUBSCRIPTION_READY host=127.0.0.1 port=8765`, profile `du27_bound_v1`,
and `identity collector: 2 KPM subscriptions, duration=0`. Leave this terminal
open and connect the formal MPTCP application using the
[application interface guide](interface/README.md#10-service-operation-and-offline-verification).
This starts only the xApp service. The application must verify `DU_ID=2`, DNN
`internet2` and the Laptop's current UE2 address.

### B. Optional 120-Second TXT/NDJSON Capture

Run separately from A. When switching modes, stop the original xApp and repeat
the preparation block to create a new directory.

```bash
python3 -B scripts/ue_identity/xapp_ue_identity.py \
  --collector /tmp/falcon-xapp-ue-identity \
  --config "$WIRED_XAPP_RUN/local.json" --e2-config "$WIRED_XAPP_RUN/xapp.conf" \
  --fresh-only --duration 120 \
  --text-output "$WIRED_XAPP_RUN/bindings.txt" \
  --capture-events "$WIRED_XAPP_RUN/inputs.ndjson" \
  > "$WIRED_XAPP_RUN/rows.ndjson" 2> "$WIRED_XAPP_RUN/xapp.log"
WIRED_XAPP_RC=$?
printf 'xApp exit=%s\n' "$WIRED_XAPP_RC" | tee "$WIRED_XAPP_RUN/exit.txt"
```

Require bound records with `DU_ID=2`, SUPI `imsi-001010000000102`, DNN `internet2`
and the current IPv4. DU `granularity_ms=100` corresponds to about ten reports
per second; verify actual cadence from retained logs. RF fields may be `no_value`
when no valid PUSCH sample exists. Normal exit is 0 with both subscription delete
responses received.

## 8. Recorded UL Experiment and Log Export

The fixed profile is TX 70 / RX 35 with the existing attenuators and native PUSCH
power-control defaults. Preserve TX 70, digital backoff 12 dB, the 50-dB DL branch,
no common attenuator, UL branch 60 dB and the frequency/bandwidth/TDD profile.
For a new gain comparison, vary only USRP RX gain while keeping traffic and the
RF path the same. Source-YAML changes take effect at the next startup; running
snapshots are separate files.

Start a UE2 listener in another Spark terminal and leave it open:

```bash
iperf3 -s -B 10.46.0.1 -p 5202
```

Run source-bound UL traffic as described in the Laptop guide. Manual mode accepts
`t` in the **native DU2 terminal** to show metrics. In automatic mode, read
`du2.console.log` or KPM reports. The controller does not accept `t`.
`PUSCH.SNR.dB` reports selected PHY **UL SINR**, separately from Quectel's DL
measurement. `PUSCH.RSRP.dBFS` is software-relative power and is not calibrated dBm.

Scheduler logging is enabled. Follow the actual automatic run directory:

```bash
read -r -p 'Current automatic run directory: ' WIRED_AUTO_RUN
sudo tail -n 0 -F "$WIRED_AUTO_RUN/du2.console.log" |
  grep --line-buffered 'Scheduler UE'
```

During 60 seconds of sustained UL, compare `pusch_snr_db`, `ul_nof_ok`,
`ul_nof_nok`, `ul_brate` and `last_phr`. Exclude idle windows without valid PUSCH
from reception-quality summaries. Corresponding xApp metrics include
`PUSCH.SNR.dB`, `UL.CRC.Ok/Nok`, `UL.MAC.Throughput` and `UL.PHR.dB`.

### Recorded Traffic and Export Commands

Keep the Spark listener and Laptop watcher running. The successful Laptop run
used:

```bash
iperf3 -c 10.46.0.1 -p 5202 -B 10.46.0.5 -t 60 -i 1
```

`10.46.0.5` was that run's address. After reconnecting, verify the current address
using [Laptop section 4](laptop_wired_ue2_quick_start.md#4-current-ip-routes-and-ping)
and update `-B` if needed. Retain sender/receiver summaries and traffic timestamps.

After traffic, export logs from another Spark terminal using the directory
printed for the actual run:

```bash
read -r -p 'Current automatic run directory: ' WIRED_AUTO_RUN
UL_EXPORT=$(mktemp /tmp/falcon-ue2-ul-rx35.XXXXXXXX.log)
sudo grep -aE 'Scheduler UE|gain set|Real-time failure' \
  "$WIRED_AUTO_RUN/du2.console.log" > "$UL_EXPORT"
printf 'Export file: %s\n' "$UL_EXPORT"
```

`sudo grep` reads the private directory; the export is created by the current
user and can be inspected directly. It contains history. Select the actual
traffic window and matching gain acknowledgement before computing statistics.
Exclude startup/other-gain errors and idle samples.

### Recorded Comparison on 2026-11-19

Each column summarizes its own final approximately 60-second sustained UL window:

| Measurement | RX 30 | RX 35: selected baseline | RX 40 |
| --- | --- | --- | --- |
| Median UL SINR | 20.8 dB | 23.6 dB | 24.0 dB |
| Median UL RSRP | -30.8 dBFS | -25.6 dBFS | -21.2 dBFS |
| Median UL MCS | 16 | 22 | 22 |
| CRC NOK / (OK + NOK) | 2.67% | 10.59% | 11.44% |
| Mean MAC throughput | 31.61 Mbps | 39.41 Mbps | 40.04 Mbps |
| RF underflow / RF-late messages | 2 / 0 | 2 / 0 | 1 / 0 |

The RX-35 window was 16:07:25-16:08:25 America/New_York
(21:07:25-21:08:25 UTC), with RNTI `0x460e`. The original export was
`/tmp/falcon-ue2-ul-rx35.mY9XEzYF.log`. Its byte-identical retained copy,
`du2-rx35-export.log`, and final comparison/capacity summaries are in the local
archive `docs/experiments/evidence/2026-11-19_ue2_wired20_baseline/`.
`manifest.json` records hashes and verifies that the earlier RX20/RX30/RX40
exports were exact prefixes of this final export. They were removed as redundant
intermediate copies; their samples remain in the retained final log.

The iperf sender reported 37.8 Mbps / TCP Retr 0; the receiver reported 37.4 Mbps.
MAC and application throughput are distinct, as are CRC errors and TCP packet
loss. RNTI changed before the RX-35 traffic window. These sequential single runs
do not completely isolate the effect of gain.

### Optional Gain Comparison

Keep the other parameters and UL workload unchanged. Enter one setting per run,
in the automatic controller or the manual native DU2 terminal:

| RX gain | Command |
| --- | --- |
| 30 | `rx_gain 0 30` |
| 35: current baseline | `rx_gain 0 35` |
| 40 | `rx_gain 0 40` |

Use the same 60-second workload for each comparison. Compare SINR, CRC, throughput
and PHR, and retain each result. Restore the baseline with `rx_gain 0 35`.
Runtime gains do not rewrite YAML; the next default startup reloads TX 70 / RX 35.

Increasing RX gain does not guarantee the same increase in SINR. If reported
power rises without SINR improvement, investigate before increasing gain again.
For insufficient PHR, inspect UE power control, resource allocation and the RF
path. USRP RX gain affects UL reception; measure DL separately at the Quectel UE.

## 9. Troubleshooting and Shutdown

In automatic mode, enter the actual run directory in another Spark terminal:

```bash
read -r -p 'Current automatic run directory: ' WIRED_AUTO_RUN
sudo tail -n 60 "$WIRED_AUTO_RUN/du2.console.log"
sudo grep -aEni 'underflow|overflow|Real-time failure|Late:|gain set|fatal|error' \
  "$WIRED_AUTO_RUN/du2.console.log" | tail -n 40
sudo python3 -B /home/nyu/Desktop/Falcon_repo/Falcon/scripts/spark_wired_du2_auto.py \
  --status "$WIRED_AUTO_RUN"
```

In manual mode, use the actual DU2 directory. Select the intended run explicitly
rather than assuming the newest directory belongs to it:

```bash
read -r -p 'Current DU2 log directory: ' DU2_LOG_DIR
sudo tail -n 50 "$DU2_LOG_DIR/startup.log"
sudo grep -aEni 'underflow|overflow|Real-time failure|Late:|gain set|fatal|error' \
  "$DU2_LOG_DIR/startup.log" "$DU2_LOG_DIR/du.log" | tail -n 40
sudo grep -a 'PUSCH:' "$DU2_LOG_DIR/du.log" | tail -n 20
```

| Symptom | Next check |
| --- | --- |
| UE `SEARCH` or registration failure | Verify DU startup, ANT3 wiring, NR SA / n78 and SSB `639648`; inspect the DL path first |
| 40-MHz output or SSB `638976` | Select the dedicated wired files instead of the older OTA config/entry point |
| RF underflow | Check real-time host processing, CPU/performance and USB 3; gain changes do not supply missing samples |
| Connected UE with missing identity/IP binding | Verify the CU identity overlay, both infoAPIs and current UE2 address |

Automatic mode uses `du2.console.log` and the controller's status/stop procedure
above. For **manual mode**, stop in this order: application/iperf traffic ->
xApp Ctrl+C and both E2 deletions -> Laptop watcher Ctrl+C and
`UE2 shutdown: SUCCESS` -> iperf listener, if started -> DU2 Ctrl+C -> CU Ctrl+C ->
RIC Ctrl+C. Preserve shared Core/CU/RIC services still used by another experiment.

If no other UE uses Core and shutdown is intended, run this in the terminal
that still defines `CORE_UNITS`:

```bash
sudo systemctl stop "${CORE_UNITS[@]}"
```

Retain the run's RIC/CU/DU2/xApp directories and Laptop watcher/iperf directories.
Copy required `/tmp` evidence to persistent storage before rebooting, using the
[local archive policy](experiments/README.md#local-archive-policy). Preserve DU
`startup.log.timing`, configuration snapshots and gain-change timing.
