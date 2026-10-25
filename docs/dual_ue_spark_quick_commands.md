# Dual UE Spark Quick Commands — 100 ms DU / 1 s CU

Updated: 2026-10-25. Developer: Ruibin Chen.

This is the complete Spark startup and experiment procedure for two UEs,
using the first expanded **27-measurement** DU profile at **100 ms** and CU identity
reports at **1 second**. Follow sections 1–6 to prepare/start the testbed,
then section 7 for a 120-second xApp capture overlapping a 60-second dual
uplink. Inspect the actual report cadence and both UE/IP bindings.

| Source | Default period |
| --- | --- |
| DU1 and DU2 scheduler/RLC statistics | **100 ms** |
| DU1 and DU2 KPM reporting and granularity | **100 ms** |
| CU identity statistics and KPM reporting | **1000 ms** |
| Core AMF/SMF polling | **1 second** |
| Identity source freshness limit | **3 seconds** |

These defaults apply throughout configuration, build checks, startup and
result inspection below. Actual expanded 100 ms operation must be verified from the new
capture; configuration values alone do not establish live timing. See the
[first-expansion contract](e2sm-kpm/du_kpm_expansion_stage1.md) for units,
sample counts, latest-value ages and missing-data rules. The accepted seven
and legacy five profiles remain available; the launcher's default stays seven.
For this expansion rebuild/restart both DUs and the xApp. Healthy CU, RIC
and Core may keep running.

The accepted E2 binaries already enable `SCTP_NODELAY` to avoid holding small
KPM messages behind delayed acknowledgments. This behavior is retained.
Verify actual receive spacing and ordering again with the expanded capture.

The standalone xApp combines DU KPM, CU identity-bearing E2 reports and existing
read-only AMF/SMF infoAPIs. Its `bindings.txt` contains only xApp records:
gNB/DU/F1 UE ID, SUPI, NGAP IDs/GUAMI, PDU session/DNN/IP, then KPM. The commands
below retain `--observed-unique` for legacy CU compatibility. The updated CU
carries serving-DU scope in its optional RAN UE identity; the captured
`local.json` admits `du36-cuue28-v1`. Updated records should show
`assurance=cu_reported_du_scope` and a `CU scope:` line. Equal F1 IDs on the two
DUs are supported. Shared context-generation and remaining restart/reuse/
performance gates are still open in
[Plan 4](../plans/cu-ue-ip-e2-binding.md). Core source/IP allocation and Plan 2
broker/MPX integration are outside this change. The
[October 13 DU-only UL/KPM results](evidence/2026-10-13_dual_kpm_reports/manifest.json)
remain historical [Plan 3](../plans/dual-ue-du-fr1-channels.md) evidence.

Run all commands in this file on Spark. Use Bash and separate foreground
terminals for CU, RIC, each DU, each iperf server and xApp. Use the
[Laptop reconnect Quick Start](dual_ue_laptop_reconnect_quick_start.md) for
automatic UE connection/recovery and the section 7 concurrent iperf test;
manual modem/AT/routing/client commands remain in
[Dual UE Laptop Quick Commands](dual_ue_laptop_quick_commands.md).
Startup order: prepare artifacts → Core → identity-configured RIC
→ identity-enabled CU → both DUs → both servers → complete Laptop UE1 sequence
→ complete Laptop UE2 sequence → section 7 dual UE identity/RF capture.
Every service/client is started manually in the foreground. Reuse healthy infrastructure during
modem recovery; steps 1–5 cover a stopped testbed.
After a modem power cycle, repeat the affected role's complete laptop sequence
([UE1](dual_ue_laptop_quick_commands.md#ue1-start) / [UE2](dual_ue_laptop_quick_commands.md#ue2-start)) before traffic. The operator reported
lock query `0`; its lock must be restored and the actual serving cell verified.
The October 21 Laptop truth identified IMSI `001010000000101` / `internet` /
`10.45.0.2` and IMSI `001010000000102` / `internet2` / `10.46.0.2`.
Those IPs, modem/bearer indices and RAN IDs may change after restart or idle.
Keep the Spark `.1` endpoints and rediscover current Laptop bearer allocations
and host routes with the launcher; compare them independently with CU/Core
inputs and the xApp output. The launcher records the bearer default gateway
while actual routes determine the server path.
The explicit table-151/table-152 inspection, complete per-role host IPv4 reset
without old-session parameters, guarded rebuilding and both private-path checks are in
[UE1 recovery](dual_ue_laptop_quick_commands.md#ue1-clean-old-path) and
[UE2 recovery](dual_ue_laptop_quick_commands.md#ue2-clean-old-path).
These tables belong to the laptop. Spark keeps service addresses `10.45.0.1`
and `10.46.0.1`, and its two iperf listeners continue to use the same bindings.
The laptop's [guarded reset](dual_ue_laptop_quick_commands.md#block-wifi-fallback)
installs destination blocks that survive reset/shutdown: ordinary ping and
TCP/UDP to these service IPs cannot fall back to Wi-Fi. Rebuilding installs both
source and destination lookups; verify both routes before traffic. Management
Wi-Fi and its default route remain available for other destinations.
The October 23 [TUN split](networking/dual_ue_tun_split.md) is applied: UE1 uses `ogstun_1`
and UE2 uses `ogstun_2`, both with MTU 1400. Spark configuration checks passed;
post-split traffic and UE2 PDU/ping recovery passed in the October 23/24
reports. Cold-start, full repeatability and bidirectional disturbance/survivor
tests are [supplemental experiments](development/dual_ue_supplemental_experiments.md),
not current Dual UE acceptance criteria or merge prerequisites.

## 0. Role assignments and core preparation

| Parameter | UE1 / DU1 | UE2 / DU2 |
| --- | --- | --- |
| B210 serial | `3271233` | `328B021` |
| Carrier / ARFCN | 3660 MHz / `644000` | 3600 MHz / `640000` |
| PCI / SSB / SCS / band | `1` / `643680` / 30 kHz / n78 | `2` / `639648` / 30 kHz / n78 |
| DU ID / sector / expected NCI | `1` / `0` / `6733824` | `2` / `1` / `6733825` |
| DU F1 bind | `127.0.10.2` | `127.0.10.3` |
| Intended modem IMEI | `863305041978437` | `863305041980706` |
| Intended SIM IMSI | `001010000000101` | `001010000000102` |
| DNN / APN | `internet` | `internet2` |
| Expected UE IPv4 pool | `10.45.0.0/16` | `10.46.0.0/16` |
| Spark service IP | `10.45.0.1` | `10.46.0.1` |
| Spark TUN interface | `ogstun_1` | `ogstun_2` |
| Spark iperf3 port | `5201` | `5202` |
| Proposed policy table / lookup / guard priority | `151` / `10151` / `10152` | `152` / `10161` / `10162` |
| WWAN / UE IP / modem / bearer / AT port | Discover each run | Discover each run |

The reviewed dual-subnet migration is complete. Preserve bundle
`/tmp/falcon-dual-subnets.Ir8TjqjO`; do not reapply the first-migration script to
the migrated core. The old two-address `ogstun` was subsequently split;
use the [current layout, archived scripts and rollback](networking/dual_ue_tun_split.md).
See [Dual UE Subnets](networking/dual_ue_subnets.md) for the historical DNN migration. Both cells use
PLMN `00101`, TAC 7, SST 1 and n78 / 20 MHz / SCS 30 kHz. Keep K/OPc private
and preserve the baseline subscriber; do not blindly reset SQN.

## 1. Check radios and deploy configuration before a cold start

For a cold start, check hardware while both DUs are stopped. Keep the verified
separate USB controller arrangement. On October 21 the observed paths were
DU1 `6-1.3` / `NVDA8000:02` and DU2 `2-1.3` / `NVDA8000:00`;
rediscover after reconnection.

```bash
if pgrep -x odu >/dev/null; then
  printf 'SKIP: DU is running; do not discover/probe its radio.\n'
else
  lsusb -t
  sudo uhd_find_devices --args type=b200
fi
```

Require both actual serials and USB 3 / `5000M`. After reconnecting, the boards
may first appear as Cypress WestBridge at 480 Mb/s with a temporary serial.
If DU2 is missing, with its DU stopped, let UHD load firmware and rediscover it:

```bash
sudo uhd_find_devices --args 'type=b200,serial=328B021'
lsusb -t
```

Require serial `328B021` and `5000M` before starting DU2. Probe only the stopped
radio; a broad discovery/probe must not disturb a running DU.

Deploy and check the maintained configs before the cold-start launch:

```bash
FALCON_REPO=/home/nyu/Desktop/Falcon_repo/Falcon
cp "$FALCON_REPO/configs/ocudu/dual_fr1/du1_b210_n78_3660mhz.yml" /home/nyu/ocudu/configs/
cp "$FALCON_REPO/configs/ocudu/dual_fr1/du2_b210_n78_20mhz.yml" /home/nyu/ocudu/configs/
cp "$FALCON_REPO/configs/ocudu/dual_fr1/du2_flexric.yml" /home/nyu/ocudu/configs/
python3 "$FALCON_REPO/scripts/dual_fr1/check_config.py" \
  --du1 /home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml \
  --du2 /home/nyu/ocudu/configs/du2_b210_n78_20mhz.yml \
  --du2-e2 /home/nyu/ocudu/configs/du2_flexric.yml
```

Require `PASS`: both deployed DU configs must enable scheduler/RLC metrics
with `metrics.periodicity.du_report_period: 100`. Keep the actual recorded RF
conditions from Plan 3. The current
configs use TX 70 / RX 35 and 23.04 MS/s; these gains are not calibrated dBm.
Host performance restoration, when needed after reboot, is in
[step 2](#2-restore-performance-settings-after-reboot).

### 1a. Prepare the CU identity binary and isolated FlexRIC plugin

Run before starting CU/RIC/xApp. Use Falcon `main` and the integrated OCUDU
`falcon-dev`, which now contains both CU identity and DU RF reporting. Build
CU and DU from that same source revision in `build-integrated`; the original
`build` executables remain available as the previous baseline. The commands
below prepare the RAN binaries and isolated xApp/plugin, then check CU and
both DU configurations. They start no services or radios:

```bash
git -C /home/nyu/Desktop/Falcon_repo/Falcon branch --show-current
git -C /home/nyu/ocudu branch --show-current
cd /home/nyu/Desktop/Falcon_repo/Falcon
cmake -S /home/nyu/ocudu -B /home/nyu/ocudu/build-integrated \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER=/usr/bin/clang-18 \
  -DCMAKE_CXX_COMPILER=/usr/bin/clang++-18 \
  -DENABLE_UHD=ON -DBUILD_TESTING=ON &&
cmake --build /home/nyu/ocudu/build-integrated --target ocu odu_split_8 -j4 &&
bash scripts/ue_identity/build.sh &&
/tmp/falcon-xapp-ue-identity --check-config configs/flexric/ric_ue_identity.conf &&
/tmp/falcon-xapp-ue-identity --check-config configs/flexric/xapp_ue_identity.conf &&
/tmp/falcon-xapp-ue-identity --check-config configs/flexric/xapp_ue_identity_expanded.conf &&
/home/nyu/ocudu/build-integrated/apps/cu/ocu \
  -c /home/nyu/ocudu/configs/cu.yml \
  -c configs/ocudu/cu_identity_e2.yml --dryrun &&
/home/nyu/ocudu/build-integrated/apps/du_split_8/odu \
  -c /home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml --dryrun &&
/home/nyu/ocudu/build-integrated/apps/du_split_8/odu \
  -c /home/nyu/ocudu/configs/du2_b210_n78_20mhz.yml \
  -c /home/nyu/ocudu/configs/du2_flexric.yml --dryrun
```

Expected subscription parsing: DU `Time: 100`; CU `Time: 1000`. The CU overlay
keeps `cu_cp_report_period: 1000`; the two deployed DU configs use
`du_report_period: 100`. Keep these producer and subscription settings together.

DU snapshot concurrency work remains deferred by operator request. This
procedure tests the stated reporting rates, current identity/IP matching and
delivery; it does not claim synchronized source snapshots.

Stop on any build/config error. Require `/tmp/falcon-xapp-ue-identity` and
`/tmp/falcon-ue-identity-sm/libkpm_sm.so`. Rebuild after `/tmp` is cleared/rebooted.
The isolated KPM plugin includes the 40-bit AMF ID decoder fix; both RIC and
xApp configs select it. Installed FlexRIC files and its source tree are left
unchanged. Sections 4–5 launch the integrated executables; retain the accepted
DU configs. Require CU and DU startup banners to identify the intended merged
revision. The dry run checks configuration support; live CU identity delivery
and both DU RF subscriptions are verified in section 7. Both DUs must
advertise `PUSCH.RSRP.dBFS` and `PUSCH.SNR.dB`; a five-metric fallback does not
validate the RF extension.
See the [identity implementation guide](development/ue_identity_xapp.md#build-and-offline-verification)
for dependency/build troubleshooting. A successful build is preparation, not
live binding acceptance.

## 2. Restore performance settings after reboot

```bash
cd /home/nyu/ocudu
sudo ./scripts/ocudu_performance
```

Answer `Y` to each of the three prompts, then check the short summaries:

```bash
awk '$0 != "performance" {bad++} END {printf "CPU governor: %s (%d CPUs)\n", NR && !bad ? "OK" : "FAIL", NR}' /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
if [ "$(sudo cat /sys/module/drm_kms_helper/parameters/poll)" = N ]; then
  printf 'DRM polling: OK\n'
else
  printf 'DRM polling: FAIL\n'
fi
sysctl -n net.core.rmem_max net.core.wmem_max net.core.rmem_default net.core.wmem_default |
  awk '$0 != 33554432 {bad++} END {print "Network buffers: " (NR == 4 && !bad ? "OK" : "FAIL")}'
```

## 3. MongoDB, subscribers and ten SA core services

```bash
sudo docker start open5gs-mongo &&
sudo docker exec open5gs-mongo mongosh --quiet --eval 'db.adminCommand({ping: 1})'
```

Require `{ ok: 1 }`. Check the two intended subscriber profiles without printing
authentication fields:

```bash
sudo docker exec open5gs-mongo mongosh --quiet --eval '
const subscribers = db.getSiblingDB("open5gs").subscribers;
let failed = false;
for (const [imsi, dnn] of [["001010000000101", "internet"], ["001010000000102", "internet2"]]) {
  const rows = subscribers.find({imsi}, {_id:0,imsi:1,slice:1}).toArray();
  const sessions = rows.length === 1 ? (rows[0].slice || [])
    .filter(s => s.sst === 1).flatMap(s => s.session || [])
    .filter(s => s.name === dnn && s.type === 1) : [];
  const ok = rows.length === 1 && sessions.length === 1;
  print(imsi + ": " + (ok ? "OK (SST 1, " + dnn + ", IPv4)" : "FAIL (record/session)"));
  failed = failed || !ok;
}
if (failed) quit(1);
'
```

Stop if either profile fails. Prepare it using its own protected credentials via
the [subscriber procedure](setup/sim_provisioning_and_dual_ue.md#prepare-open5gs-subscribers).
This projection does not verify K/OPc or SQN. Preserve the historical subscriber
`001010000000001`; do not reset SQN to 96 without checking its current state.

On the dedicated Spark cold start, use the existing SA service selection:

```bash
sudo systemctl stop open5gs-mmed open5gs-hssd open5gs-pcrfd open5gs-sgwcd open5gs-sgwud
sudo systemctl stop open5gs-bsfd open5gs-seppd
CORE_UNITS=(
  open5gs-nrfd open5gs-scpd open5gs-udrd open5gs-udmd
  open5gs-ausfd open5gs-pcfd open5gs-nssfd
  open5gs-upfd open5gs-smfd open5gs-amfd
)
for unit in "${CORE_UNITS[@]}"; do
  if ! sudo systemctl start "$unit"; then
    printf 'FAIL: Cannot start %s\n' "$unit"
    break
  fi
done
CORE_ACTIVE_COUNT=0
for unit in "${CORE_UNITS[@]}"; do
  if systemctl is-active --quiet "$unit"; then
    CORE_ACTIVE_COUNT=$((CORE_ACTIVE_COUNT + 1))
  else
    printf 'FAIL: %s\n' "$unit"
  fi
done
printf '5GC active: %d/10\n' "$CORE_ACTIVE_COUNT"
for tun in ogstun_1 ogstun_2; do
  ip -o link show dev "$tun"
  ip -o -4 addr show dev "$tun"
done
ip -4 route show 10.45.0.0/16
ip -4 route show 10.46.0.0/16
```

Require `10/10`; `ogstun_1` must be UP, MTU 1400, with `10.45.0.1/16`, and
`ogstun_2` must be UP, MTU 1400, with `10.46.0.1/16`. The private routes must
use their corresponding TUNs. The old name `ogstun` is absent. Current setup,
archived scripts and rollback are in the [TUN split guide](networking/dual_ue_tun_split.md);
the two-DNN subscriber history is in the [subnet migration guide](networking/dual_ue_subnets.md).
Original single-subnet repair is in the
[full runbook](runbooks/full_reproduction_runbook.md#7-start-only-the-required-5gc-functions).

Check the existing read-only identity APIs from Spark before starting RAN:

```bash
curl --noproxy '*' --fail --show-error --max-time 3 -i \
  'http://127.0.0.5:9090/ue-info?page=0&page_size=100'
curl --noproxy '*' --fail --show-error --max-time 3 -i \
  'http://127.0.0.4:9090/pdu-info?page=0&page_size=100'
```

Require HTTP 200 and JSON `items`/`pager`. Empty `items` before UE registration
is normal. These addresses are the existing AMF/SMF infoAPIs on this testbed;
if unavailable, resolve the API/service configuration before the binding test.
The xApp requires them even though the CU reports AMF-side NGAP identifiers.

## 4. Start identity RIC, then identity-enabled CU in separate terminals

**RIC terminal first:**

```bash
IDENTITY_RIC_RUN=$(mktemp -d /tmp/falcon-identity-ric.XXXXXXXX)
printf 'RIC log directory: %s\n' "$IDENTITY_RIC_RUN"
set -o pipefail
stdbuf -oL -eL /usr/local/bin/flexric/ric/nearRT-RIC \
  -c /home/nyu/Desktop/Falcon_repo/Falcon/configs/flexric/ric_ue_identity.conf \
  2>&1 | tee "$IDENTITY_RIC_RUN/ric.log"
```

Require `SM_DIR: /tmp/falcon-ue-identity-sm/`, E2 port `36421`, E42 port `36422`
and KPM SM ID `2` loaded. Keep RIC running. Use this config throughout both
binding tests; it is a KPM-only candidate setup.

**CU terminal:**

```bash
cd /home/nyu/ocudu
IDENTITY_CU_RUN=$(mktemp -d /tmp/falcon-identity-cu.XXXXXXXX)
printf 'CU log directory: %s\n' "$IDENTITY_CU_RUN"
set -o pipefail
sudo stdbuf -oL -eL build-integrated/apps/cu/ocu \
  -c configs/cu.yml \
  -c /home/nyu/Desktop/Falcon_repo/Falcon/configs/ocudu/cu_identity_e2.yml \
  log --filename "$IDENTITY_CU_RUN/cu.log" \
  2>&1 | tee "$IDENTITY_CU_RUN/console.log"
```

Require N2 connection to `127.0.0.5:38412`, E2 connection to RIC, F1 listener
`127.0.10.1:38472`, and `==== CU started ===`. RIC must accept the CU/gNB 411
node and KPM function 2. The overlay enables CU-CP E2/identity metrics; using
only `configs/cu.yml` will omit the identity source required by this test.
The identity overlay produces CU snapshots every **1000 ms**; section 7 uses
the matching 1000 ms CU subscription.
The base CU file and the versioned identity overlay set
`cu_cp.request_pdu_session_timeout: 10` seconds. This allows the laptop to finish
its registration/cell checks before requesting a PDU; the earlier 3-second
window caused one measured startup to release and reconnect its RRC context.
The change applies when CU starts with these files. A running CU keeps its
previous setting until restarted using the normal CU/DU shutdown/start sequence.
Keep this terminal running. If RIC restarts, stop the test and restart CU and
both DUs in order before launching a new xApp; automatic E2 recovery is not
assumed.

## 5. Start DU1 and DU2 in separate terminals and keep both running

Complete the shared MongoDB/core/CU/RIC startup first. Start each DU in its own
foreground terminal before beginning either laptop UE sequence. Both DUs stay
running while UE1 and UE2 are prepared and measured. Each DU produces
scheduler/RLC statistics every **100 ms** using the section 1 configs; the
section 7 xApp subscribes at the same 100 ms period.

The [console launcher](../scripts/dual_fr1/run_du_console.sh) uses util-linux
`script` to give sudo and the DU terminal-backed stdin/stdout/stderr while
recording `startup.log`. Run it directly in an interactive terminal. It
replaces the old `sudo ... | tee` pipeline, which left the DU behind sudo's
pseudo-terminal foreground group and prevented console input. The launcher
flushes output and propagates the child exit status. It also records
`startup.log.timing` and prints a precise UTC clock marker before launching the
DU, so gain replies can be correlated with DU/CU events; see
[script(1)](https://man7.org/linux/man-pages/man1/script.1.html).

### 5a. Spark DU1 terminal

```bash
cd /home/nyu/ocudu
DU1_RUN=$(mktemp -d /tmp/falcon-du1-3660.XXXXXXXX)
printf 'DU1 run directory: %s\n' "$DU1_RUN"
bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/run_du_console.sh \
  "$DU1_RUN/startup.log" \
  sudo stdbuf -oL -eL build-integrated/apps/du_split_8/odu \
  -c configs/du1_b210_n78_3660mhz.yml \
  log --filename "$DU1_RUN/du.log"
```

Require radio `3271233` / USB 3, PCI 1 / carrier `644000` / SSB `643680`,
F1/E2 completed, `==== DU started ===`, and RIC accepted gNB 411 / DU ID 1.
Leave this terminal running.

### 5b. Spark DU2 terminal

```bash
cd /home/nyu/ocudu
DU2_RUN=$(mktemp -d /tmp/falcon-du2-3600.XXXXXXXX)
printf 'DU2 run directory: %s\n' "$DU2_RUN"
bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/run_du_console.sh \
  "$DU2_RUN/startup.log" \
  sudo stdbuf -oL -eL build-integrated/apps/du_split_8/odu \
  -c configs/du2_b210_n78_20mhz.yml -c configs/du2_flexric.yml \
  log --filename "$DU2_RUN/du.log"
```

Require radio `328B021` / USB 3, PCI 2 / carrier `640000` / SSB `639648`,
F1/E2 completed, `==== DU started ===`, and RIC accepted gNB 411 / DU ID 2.
Leave this terminal running.

### 5c. Confirm the two-DU startup before UE setup

In a Spark diagnostics terminal:

```bash
pgrep -a -x odu
```

Require two actual DU processes with the two distinct configuration paths.
RIC must show both DU IDs and accept KPM function 2 for each; retain actual
CU NR CGI/F1AP and startup evidence. Starting the two foreground terminals
separately results in concurrent operation; it does not establish synchronized
RF timing. Keep the recorded clock/RF settings and the remaining Plan 3 gates.
If both DUs are already running correctly, reuse them for modem recovery.

### 5d. Console input and temporary RX gain

After `==== DU started ===`, enter this line in each corresponding DU terminal
and press Enter. Require an `Available commands` response:

```text
;h;
```

The current OCUDU console splits commands on semicolons and removes newlines.
Send one command at a time with surrounding semicolons so queued lines do not
merge. In the selected DU's terminal, temporarily reduce its RX gain to 30 dB:

```text
;rx_gain 0 30;
```

Require `Rx gain set to 30 dB for port 0.` (numeric formatting may differ).
Port `0` is local to that DU process and is not its DU ID. This changes its
radio's uplink reception gain. Restore the configured 35 dB with a separate
command:

```text
;rx_gain 0 35;
```

Runtime gain changes do not rewrite YAML; restart reads the configuration
again. The new launcher is stored in the repository and is used on each
startup, replacing the temporary per-PID foreground repair. The launcher was
tested with real PTYs and a fake DU, including foreground ownership, command
input, live output logging, literal arguments, child exit codes and `Ctrl+C`:
`python3 -B /home/nyu/Desktop/Falcon_repo/Falcon/tests/du_console_test.py`.

### 5e. Record gain change times

Start each DU using the existing launcher command above. The updated launcher
automatically records `startup.log` and `startup.log.timing` in that DU's run
directory. Continue entering gain commands normally in the DU terminal:

```text
;tx_gain 0 40;
```

Restore it with a separate command:

```text
;tx_gain 0 70;
```

In another **Spark** terminal, display the gain acknowledgement times for the
latest DU2 run:

```bash
python3 /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/extract_du_gain_times.py --du 2
```

Use `--du 1` for DU1, or pass an explicit `startup.log` path instead of `--du`.
The tool reads a snapshot and exits; rerun after another gain command. Use
`--json` to emit JSON lines for archival/analysis. It works while the DU is
running and records successful TX and RX gain replies. It does not send commands
to the DU or change its foreground terminal.

The timestamp is the reconstructed UTC time at which `script` observed the
successful `Tx/Rx gain set to ...` output, anchored to the launcher's precise
clock marker. It is an experiment alignment marker, not a hardware measurement
of when RF power settled. A command's hardware call completes before its reply;
output delivery/scheduling can add delay. Spark's DU/CU logs use the same host's
UTC clock; Laptop events still need the independently measured clock offset.

Retain **both** `startup.log` and `startup.log.timing` along with `du.log`.
No input stream is logged, so hidden sudo password input stays unrecorded. The
gain extraction code rejects input timing records and refuses to invent times
for old logs without the new clock marker/timing file. This recording starts on
the next DU launch with the updated script; an already-running old console
cannot acquire historical timestamps retroactively. No DU rebuild is required.

PTY tests verify foreground input, Ctrl+C, exit codes, timing extraction and
hidden-input exclusion. Byte/timing tests cover split replies and incomplete
live records; hardware timing accuracy still needs measurement on the testbed.
These tests do not start radios; verify
F1/E2, console help, both UE paths and traffic after the next actual launch.

## 6. Start both iperf servers before the laptop sequences

In the Spark UE1 server terminal:

```bash
iperf3 -s -B 10.45.0.1 -p 5201
```

In the Spark UE2 server terminal:

```bash
iperf3 -s -B 10.46.0.1 -p 5202
```

Require `Server listening` on both ports. Reuse existing listeners rather than
starting duplicate servers. Keep both listeners, both DUs, CU and RIC running.
For the automatic workflow, follow the
[Laptop reconnect Quick Start](dual_ue_laptop_reconnect_quick_start.md): start
one watcher per UE, wait for both connection `SUCCESS` markers and pass the
dual-upload helper's `--check-only` preflight. Leave both watchers running,
then continue with section 7 below.

For manual operation, the laptop follows the [complete UE1 sequence](dual_ue_laptop_quick_commands.md#ue1-start)
in its own terminal, followed by the [complete UE2 sequence](dual_ue_laptop_quick_commands.md#ue2-start)
in another terminal. Each sequence includes identity/cell/PDU, complete role reset,
its own table/rules, private ping and individual UL with the other UE's test
traffic idle. Keep both PDU paths active for the concurrent test in step 7.

## 7. Start the dual UE identity/RF xApp and save TXT results

Use this section for the merged RIC/xApp/E2SM integration test. Finish steps
1–6 and connect both Laptop UEs first. Keep Core, the identity-configured RIC,
the identity-enabled CU, both DUs and both iperf listeners running. Finish any
other xApp before starting this capture.

Require the RIC to have accepted the three intended E2 nodes: CU/gNB 411,
gNB 411 / DU ID 1, and gNB 411 / DU ID 2. The xApp discovers nodes at startup;
if one is missing, fix its E2 connection before launching the xApp.

This command uses the maintained identity coordinator, the **dual UE**
`local.json`, and the explicit **27-measurement expanded** subscription. The two RF names
are `PUSCH.RSRP.dBFS` and `PUSCH.SNR.dB`. CU identity subscriptions, including
`FALCON.UE.RRCState`, remain enabled. `--observed-unique` allows the existing
experimental CU/DU/Core association; `--fresh-only` disables historical IP
fallback for this test, so an old cached IP cannot hide a missing current join.
Both DU subscriptions use **100 ms** reporting/granularity and require the
100 ms source configs. CU identity remains at 1000 ms. Expect roughly ten
reports per second per active DU, twenty DU rows per second across the two
single-UE paths. An idle 100 ms window may have no usable PUSCH sample.

### 7a. Start the xApp and write a 120-second TXT capture

<a id="7a-first-verify-both-ip-bindings-during-a-60-second-dual-upload"></a>

In a dedicated **Spark xApp terminal**:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
IDENTITY_DUAL_RUN=$(mktemp -d /tmp/falcon-identity-dual.XXXXXXXX)
printf 'Spark capture directory: %s\n' "$IDENTITY_DUAL_RUN"
cp configs/ue_identity/local.json "$IDENTITY_DUAL_RUN/local.json"
cp configs/flexric/xapp_ue_identity_expanded.conf "$IDENTITY_DUAL_RUN/xapp.conf"
python3 scripts/ue_identity/xapp_ue_identity.py \
  --config "$IDENTITY_DUAL_RUN/local.json" \
  --e2-config "$IDENTITY_DUAL_RUN/xapp.conf" \
  --observed-unique --fresh-only --duration 120 \
  --text-output "$IDENTITY_DUAL_RUN/bindings.txt" \
  --capture-events "$IDENTITY_DUAL_RUN/inputs.ndjson" \
  > "$IDENTITY_DUAL_RUN/rows.ndjson" \
  2> "$IDENTITY_DUAL_RUN/xapp.log"
IDENTITY_DUAL_RC=$?
printf 'xApp exit=%s\n' "$IDENTITY_DUAL_RC" | tee "$IDENTITY_DUAL_RUN/exit.txt"
```

The xApp runs in the foreground for 120 seconds, then deletes its subscriptions
and exits. To run a longer session, change only `--duration` (maximum 3600
seconds). Ctrl+C in this terminal ends the xApp and requests subscription
cleanup; it does not stop the UEs, DUs, CU or RIC. Keep those components running
until the xApp has finished cleanup.

| File in the printed directory | Contents |
| --- | --- |
| `bindings.txt` | Readable UE/DU/Core/session/current-IP association, 27 raw KPM measurements, and separately labelled xApp-derived failure ratios |
| `rows.ndjson` | The same correlated records in machine-readable form |
| `inputs.ndjson` | Decoded CU/DU reports and read-only Core snapshots used by the association |
| `xapp.log` | SDK registration, subscription, cleanup and error messages |
| `local.json`, `xapp.conf`, `exit.txt` | Configuration snapshots and the real process exit status |

In a **separate Spark diagnostics terminal**, paste the printed directory.
Shell variables do not cross terminals:

```bash
read -r -p 'Paste the current Spark capture directory: ' IDENTITY_WATCH_RUN
tail -n 40 "$IDENTITY_WATCH_RUN/xapp.log"
tail -n 45 "$IDENTITY_WATCH_RUN/bindings.txt"
```

Require `Registered E2 Nodes = 3`, three successful subscriptions and
`identity collector: 3 KPM subscriptions, duration=120` in `xapp.log`.
`bindings.txt` should contain records for both `DU_ID=1` and `DU_ID=2`.
These snapshot commands return immediately. To watch an active capture, use
`tail -n 45 -f "$IDENTITY_WATCH_RUN/bindings.txt"`; it intentionally waits for
new output even after the xApp exits. Ctrl+C there stops only `tail`.

Once subscriptions are ready, immediately run the Laptop's
[60-second concurrent iperf command](dual_ue_laptop_reconnect_quick_start.md#6-start-spark-section-7a-then-upload-for-60-seconds).
The [preceding current-IP/route preflight](dual_ue_laptop_reconnect_quick_start.md#5-check-both-current-ips-and-routes--laptop-terminal-3)
must pass first; keep both reconnect watchers running through this capture.
The [manual dual-upload procedure](dual_ue_laptop_quick_commands.md#dual-ul)
is available when using manual UE setup instead. Keep both clients' actual current
IP/SUPI/DNN and completion summaries for comparison; do not substitute old
`.2` addresses. The 120-second capture leaves time for startup and the upload.
UL traffic gives both DUs PUSCH samples for the RF check. Brief initial
unresolved rows can occur while fresh CU/Core/DU inputs arrive; inspect their
reasons instead of treating subscription success alone as a successful join.

### 7b. Six-minute bidirectional idle/resume and independent matching

This is an **optional follow-up**, not a prerequisite for the initial
expanded integration test. After 7a completes, prepare the Laptop's
[idle/resume command](dual_ue_laptop_quick_commands.md#binding-idle) and leave
it at `READY`. In the Spark xApp terminal, repeat the 7a capture command with
a fresh `mktemp` directory and **`--duration 360`** instead of 120. After
confirming three subscriptions, return to Laptop within ten seconds, enter
`START`, and let both clients and the xApp finish naturally.

The Laptop command runs UE1 15 s UL → 150 s quiet → 170 s UL, and UE2 175 s UL
→ 150 s quiet → 10 s UL. For this optional test, periodic ping/reconnect
probes and other WWAN traffic must not prevent the intended idle intervals.
Verify actual Core connected → idle → connected transitions, peer continuity,
and fresh resumed matches using the
[full six-minute procedure and inspection](development/ue_identity_xapp.md#six-minute-bidirectional-idleresume-test).
The quick summary below alone does not establish idle transitions.

### 7c. Inspect both UE bindings and the expanded E2SM measurements

<a id="7c-inspect-both-ue-bindings-and-the-seven-e2sm-measurements"></a>

<a id="7c-inspect-bindings-core-transitions-and-two-example-records"></a>

After the capture finishes, use the completed directory in a Spark diagnostics
terminal. This prints a summary and one matched TXT record per DU:

```bash
read -r -p 'Paste the completed Spark capture directory: ' IDENTITY_CHECK_RUN
cat "$IDENTITY_CHECK_RUN/exit.txt"
grep -E 'Registered E2 Nodes|identity collector:|DELETE RESPONSE|Sucessfully stopped' \
  "$IDENTITY_CHECK_RUN/xapp.log"
python3 - "$IDENTITY_CHECK_RUN" <<'PY_CHECK' | tee "$IDENTITY_CHECK_RUN/summary.txt"
from collections import Counter
import json
from pathlib import Path
import statistics
import sys

root = Path(sys.argv[1])
rows = [json.loads(line) for line in (root / 'rows.ndjson').open()]
sys.path.insert(0, '/home/nyu/Desktop/Falcon_repo/Falcon/scripts/ue_identity')
from metrics import EXPANDED
expected_metrics = set(EXPANDED)
expected_roles = {'1': ('imsi-001010000000101', 'internet'),
                  '2': ('imsi-001010000000102', 'internet2')}
print('Records:', len(rows), dict(Counter(r['binding_status'] for r in rows)))
problems = 0
reports = []
with (root / 'inputs.ndjson').open() as source:
    for line in source:
        event = json.loads(line)
        if event['kind'] == 'kpm_report':
            reports.append(event)
        problems += (event['kind'] not in ('core_snapshot', 'kpm_report')
                     or int(event.get('ingress_dropped_total', 0)) != 0)
print('Core/input errors or loss events:', problems)
def intervals(label, timestamps):
    gaps = [(b - a) / 1000 for a, b in zip(timestamps, timestamps[1:])]
    if gaps:
        ordered = sorted(gaps)
        p95 = ordered[min(len(ordered) - 1, (95 * len(ordered) - 1) // 100)]
        print(label, 'count=', len(timestamps), 'interval ms min/median/p95/max=',
              tuple(round(v, 3) for v in (min(gaps), statistics.median(gaps), p95, max(gaps))))
    else:
        print(label, 'insufficient reports for cadence inspection')
cu_reports = [e for e in reports if e['node']['node_type'] != 'ngran_gNB_DU']
intervals('CU receive', [int(e['received_at_mono_us']) for e in cu_reports])
blocks = (root / 'bindings.txt').read_text().split('\n\n')
for du, expected in expected_roles.items():
    selected = [r for r in rows if str(r['node'].get('du_id')) == du]
    matched = [r for r in selected if r['binding_status'] == 'matched']
    print('\nDU' + du, dict(Counter(r['binding_status'] for r in selected)))
    print('Unmatched reasons:', dict(Counter(r['reason'] for r in selected
                                            if r['binding_status'] != 'matched')))
    print('SUPI / DNN / IP / F1 / AMF / RAN:', sorted({
        (r['binding']['supi'], r['binding']['dnn'], r['ue_ipv4'],
         r['row']['ue']['gnb_cu_ue_f1ap_id'], r['binding']['amf_ue_ngap_id'],
         r['binding']['ran_ue_ngap_id']) for r in matched}))
    print('Unexpected SUPI/DNN on matched rows:', sum(
        (r['binding']['supi'], r['binding']['dnn']) != expected for r in matched))
    print('Rows with exactly 27 expected E2 metrics:', sum(
        set(r['row']['metrics']) == expected_metrics for r in selected), '/', len(selected))
    print('Granularity ms:', dict(Counter(r['row'].get('granularity_ms') for r in selected)))
    du_reports = [e for e in reports if str(e['node'].get('du_id')) == du
                  and e['node']['node_type'] == 'ngran_gNB_DU']
    intervals('DU' + du + ' header', [int(e['header_time_us']) for e in du_reports])
    intervals('DU' + du + ' receive', [int(e['received_at_mono_us']) for e in du_reports])
    for metric in EXPANDED:
        print(metric, dict(Counter(r['row']['metrics'].get(metric, {}).get('type', 'absent')
                                   for r in selected)))
    print('xApp-derived failure ratios (not raw E2 fields):', dict(Counter(
        name for r in selected for name in r.get('derived_metrics', {}))))
    print('Positive-UL rows:', sum(
        (r['row']['metrics'].get('DRB.UEThpUl', {}).get('value') or 0) > 0 for r in selected))
    example = next((b for b in blocks if b.startswith('record=') and ' status=matched ' in b
                    and f' DU_ID={du} ' in b), None)
    print('Matched TXT example:\n' + (example or 'No matched record'))
PY_CHECK
```

Check the actual results against both Laptop role summaries:

| Check | Expected result for this run |
| --- | --- |
| UE1 / logical FR1 | DU ID 1, SUPI `imsi-001010000000101`, DNN `internet`, current Laptop UE1 IP in `10.45.0.0/16` |
| UE2 / logical FR3 | DU ID 2, SUPI `imsi-001010000000102`, DNN `internet2`, current Laptop UE2 IP in `10.46.0.0/16` |
| Current association | Both roles have repeated `status=matched` records with actual F1/NGAP/GUAMI/PDU identifiers; no cross-UE binding. `--fresh-only` produces no cached bindings. |
| DU measurements | Both DUs carry all 27 raw names with units/types from the expansion contract; original seven names remain present. CQI/MCS are rounded INTEGER means; signed PHR is REAL. `PRB.UsageDl.Percent` / `PRB.UsageUl.Percent` preserve fractional percentages as REAL; `RRU.PrbTotDl/Ul` remain INTEGER. |
| Sample validity and age | CQI/MCS have sample counts; no observations produce noValue. PHR/BSR/buffer include age in ms and stay noValue until observed. Their latest values can persist across windows. |
| Derived values | HARQ/CRC failure ratios are separately labelled xApp calculations; zero denominator gives noValue. They are not IP packet loss or first-transmission BLER. |
| Rate and granularity | DU `granularity_ms=100`; measured header and receive interval medians near 100 ms for each DU; CU receive intervals near 1000 ms. Inspect p95/max and any gaps rather than assuming a hard deadline. |
| RF availability | Both paths produce REAL RF values during UL traffic; negative RSRP is valid. A period without usable PUSCH can report `no_value`, which must remain distinct from measured zero. |
| Delivery and cleanup | No Core/input errors or ingress loss; three subscription delete responses and xApp exit 0. |

`summary.txt` is an inspection aid, not an automatic acceptance verdict.
The 120-second window should produce roughly 1200 reports per continuously
reporting DU, less startup/cleanup and periods without any eligible UE. Actual
counts and intervals determine the result; the earlier 1-second captures are
baseline evidence, not evidence for the new 100 ms rate. This is not a guarantee
of 100 ms end-to-end latency: CU/Core identity refresh still has a 1-second cadence.
Compare the current Laptop IP and identity evidence with the actual CU/Core
inputs and output records. A correct DU RF value with `CU identity missing`
does not verify the combined identity join: check the CU identity overlay,
CU subscription and fresh CU input records. A missing RF name or rejected DU
subscription needs the RF-capable DU binary/configuration; `--du-metrics 5`
can diagnose legacy compatibility but does not complete this expanded test.
The accepted seven-measurement regression uses `--du-metrics 7` or
`configs/flexric/xapp_ue_identity.conf`; it does not exercise the new names.

These are new live results to be collected; the merged offline tests and
earlier DU-only RF capture do not replace this two-UE combined run. Cold-start
repeatability, bidirectional disturbance and protocol-explicit lifecycle/reuse
work retain their separate supplemental or development scope.

## 8. Shutdown and retained evidence

Finish laptop traffic and allow the finite xApp to receive all three subscription
delete responses and stop naturally. If using reconnect watchers, press Ctrl+C
in each Laptop watcher terminal and require that role's shutdown `SUCCESS`, as
shown in the [Laptop reconnect shutdown commands](dual_ue_laptop_reconnect_quick_start.md#8-stop-after-iperf-and-the-xapp-have-finished).
For manually connected UEs, follow [separate laptop shutdown](dual_ue_laptop_quick_commands.md#cleanup):
UE1 first, then UE2, using the updated helper's `--shutdown` to disconnect the PDU,
clear host IPv4 configuration, delete each modem's bearers and disable it.
After both laptop shutdown success markers, stop both iperf
server terminals, then each DU, CU and RIC in their own terminals with Ctrl+C.
Stop the shared core only after both DUs have finished using it:

```bash
sudo systemctl stop open5gs-amfd open5gs-smfd open5gs-upfd
sudo systemctl stop open5gs-nssfd open5gs-pcfd open5gs-ausfd open5gs-udmd open5gs-udrd
sudo systemctl stop open5gs-scpd open5gs-nrfd
```

Optional MongoDB shutdown preserves its container/data:

```bash
sudo docker stop open5gs-mongo
```

Retain each capture's `local.json`, `xapp.conf`, `exit.txt`, `inputs.ndjson`,
`rows.ndjson`, `bindings.txt`, `summary.txt` and `xapp.log`, together with the
RIC/CU/DU startup logs, actual source revisions and Laptop truth/events/client
logs/summary. `/tmp` may be cleared on reboot: copy the printed evidence
directories to a persistent experiment directory before shutdown. Keep raw
security-bearing Core logs and K/OPc outside Git. The October 21 live functional
results are retained in the [report](reports/ue_identity_dual_ue_live_2026-10-21.md);
record the new cold-start outcome separately from those historical trials.
