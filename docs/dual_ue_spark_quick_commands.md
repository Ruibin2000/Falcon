# Dual UE Spark Quick Commands — 100 ms DU / 1 s CU and app subscriptions

Updated: 2026-10-26. Developer: Ruibin Chen.

This is the complete Spark startup and experiment procedure for two UEs,
using the first expanded **27-measurement** DU profile at **100 ms** and CU identity
reports at **1 second**. Follow sections 1–6 to prepare/start the testbed,
then [section 7c](#7c-live-app-subscription-test-with-one-dummy) for the current
application subscription test. Keep the Python matching/publisher implementation:
one xApp service pushes both links to **one all-links dummy**, which writes TXT.
Run a 120-second dummy session overlapping a 60-second dual uplink, then use the
same procedure for a 30-minute session. Sections 7a/7b retain the earlier direct
xApp-to-TXT diagnostic captures.

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
and legacy five profiles remain available; diagnostic mode defaults to seven,
while application subscription mode defaults to 27 and fresh-only matching.
Reuse healthy Core/RIC/CU/DUs when their current binaries and configurations
already provide the verified 27-metric/100 ms input. Rebuild/restart RAN components
when changing those sources/configurations. Section 7c builds a fresh collector
separately before starting the application subscription service.

The accepted E2 binaries already enable `SCTP_NODELAY` to avoid holding small
KPM messages behind delayed acknowledgments. This behavior is retained.
Verify actual receive spacing and ordering again with the expanded capture.

The xApp combines DU KPM, CU identity-bearing E2 reports and existing
read-only AMF/SMF infoAPIs. Each matched report retains:
gNB/DU/F1 UE ID, SUPI, NGAP IDs/GUAMI, PDU session/DNN/IP, then KPM. The commands
in sections 7a/7b retain `--observed-unique` for legacy CU compatibility.
Section 7c uses the current explicit CU scope and fresh-only matching. The updated CU
carries serving-DU scope in its optional RAN UE identity; the captured
`local.json` admits `du36-cuue28-v1`. Updated records should show
`assurance=cu_reported_du_scope` and a `CU scope:` line. Equal F1 IDs on the two
DUs are supported. Shared context-generation and remaining restart/reuse/
performance gates are still open in
[Plan 4](../plans/cu-ue-ip-e2-binding.md). The application interface is described in
the [subscription guide](kpm_app_interface.md) and
[Plan 2](../plans/xapp-kpm-app-subscription.md). Core IP allocation and MPTCP
steering remain separate from this dummy delivery test. The
[October 13 DU-only UL/KPM results](evidence/2026-10-13_dual_kpm_reports/manifest.json)
remain historical [Plan 3](../plans/dual-ue-du-fr1-channels.md) evidence.

Run setup/service commands on Spark; the traffic block explicitly marked Laptop
runs there. Use Bash and separate foreground
terminals for CU, RIC, each DU, each iperf server, xApp and the single dummy. Use the
[Laptop reconnect Quick Start](dual_ue_laptop_reconnect_quick_start.md) for
automatic UE connection/recovery and the section 7 concurrent iperf test;
manual modem/AT/routing/client commands remain in
[Dual UE Laptop Quick Commands](dual_ue_laptop_quick_commands.md).
Startup order: prepare artifacts → Core → identity-configured RIC
→ identity-enabled CU → both DUs → both servers → complete Laptop UE1 sequence
→ complete Laptop UE2 sequence → section 7c xApp → single dummy → dual upload.
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

Run before starting CU/RIC/xApp. Use the current Falcon checkout containing the
subscription implementation and the integrated OCUDU
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

**Normal startup:**

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

**Optional temporary stack capture — use this instead of the normal block:**

```bash
bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/debug_du1.sh
```

Expected: `DU1 debug directory: /tmp/falcon-du1-crash.XXXXXXXX`. This uses the
same integrated DU binary and DU1 config under GDB, retaining console input
and gain timestamps. Start only one launcher for this DU.

Require radio `3271233` / USB 3, PCI 1 / carrier `644000` / SSB `643680`,
F1/E2 completed, `==== DU started ===`, and RIC accepted gNB 411 / DU ID 1.
Leave this terminal running.

### 5b. Spark DU2 terminal

**Normal startup:**

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

**Optional temporary stack capture — use this instead of the normal block:**

```bash
bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/debug_du2.sh
```

Expected: `DU2 debug directory: /tmp/falcon-du2-crash.XXXXXXXX`. This uses the
same integrated DU binary, DU2 config and DU2 E2 overlay under GDB.
Start only one launcher for this DU.

Require radio `328B021` / USB 3, PCI 2 / carrier `640000` / SSB `639648`,
F1/E2 completed, `==== DU started ===`, and RIC accepted gNB 411 / DU ID 2.
Leave this terminal running.

For the diagnostic stability trial, choose the optional capture launcher for
**both DUs** when starting the testbed. Reuse an already-debugged DU; an existing
normal DU needs to exit before its replacement is started. Neither launcher
attaches to or stops an existing DU. On a fatal signal, each debugger saves
that DU's all-thread stacks and status in its own directory; keep both paths.
See [capture details and output files](troubleshooting/du2_crash_capture.md).
No DU rebuild or system core-dump configuration change is needed. Mark the
trial as running under GDB, which can change execution timing.

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

Start each logged server in its own Spark terminal. Before replacing an old
unlogged listener, finish active Laptop traffic and press Ctrl+C in that
server's original terminal. Then use the commands below for the new trial.

**Spark UE1 / FR1 server terminal:**

```bash
FR1_IPERF_RUN=$(mktemp -d /tmp/falcon-iperf-fr1.XXXXXXXX)
printf 'FR1 iperf server directory: %s\n' "$FR1_IPERF_RUN"
set -o pipefail
TZ=UTC stdbuf -oL -eL iperf3 -s -B 10.45.0.1 -p 5201 -i 1 \
  --timestamps='%Y-%m-%dT%H:%M:%SZ ' --forceflush \
  2>&1 | tee "$FR1_IPERF_RUN/server.log"
FR1_IPERF_RC=${PIPESTATUS[0]}
printf 'iperf server exit=%s\n' "$FR1_IPERF_RC" | tee "$FR1_IPERF_RUN/exit.txt"
```

**Spark UE2 / FR3 server terminal:**

```bash
FR3_IPERF_RUN=$(mktemp -d /tmp/falcon-iperf-fr3.XXXXXXXX)
printf 'FR3 iperf server directory: %s\n' "$FR3_IPERF_RUN"
set -o pipefail
TZ=UTC stdbuf -oL -eL iperf3 -s -B 10.46.0.1 -p 5202 -i 1 \
  --timestamps='%Y-%m-%dT%H:%M:%SZ ' --forceflush \
  2>&1 | tee "$FR3_IPERF_RUN/server.log"
FR3_IPERF_RC=${PIPESTATUS[0]}
printf 'iperf server exit=%s\n' "$FR3_IPERF_RC" | tee "$FR3_IPERF_RUN/exit.txt"
```

Require `Server listening` on both ports. Keep both printed directories:
`server.log` records standard output and errors while also showing them in the
terminal. iperf report lines carry UTC timestamps; `--forceflush` and line
buffering keep the log current. Preserve untimestamped error lines with their
surrounding output. `exit.txt` records the actual iperf exit code only after
the foreground server ends; its absence while listening is expected.

Reuse listeners already started with these logged commands; start one listener
per address/port. Keep both listeners, both DUs, CU and RIC running.
To inspect a saved/live server log in another Spark terminal, paste either
printed server directory:

```bash
read -r -p 'Paste the FR1 or FR3 iperf server directory: ' IPERF_SERVER_READ
tail -n 40 "$IPERF_SERVER_READ/server.log"
```

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

For the current **application subscription** test, use
[7c](#7c-live-app-subscription-test-with-one-dummy). The 7a/7b commands below
remain direct diagnostic captures: the xApp itself writes their TXT. Run one
xApp mode at a time. Section 7c instead has the dummy own TXT and receipt timing.

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

Expected: both roles repeatedly show `status=matched` with their current
Laptop IP, SUPI and DNN; both DUs carry 27 raw metrics with `granularity_ms=100`.
Allow startup rows to remain unresolved until fresh CU/Core inputs arrive.
For detailed metric, timing and input-loss analysis, use the
[development reference](development/ue_identity_xapp.md#expanded-27-metric-capture-inspection).

### 7b. Six-minute reconnect stability with alternating and concurrent UL

Keep **both reconnect watchers running** throughout this test. Run this after
7a completes; finish the previous xApp and all previous iperf clients first.
Keep Spark's two servers, both DUs, CU, RIC and Core running. Use fixed gains
and leave other applications off the WWAN paths. The test uses the expanded
27-metric DU profile at **100 ms**, CU identity at **1 second**, and a fresh
**360-second** xApp capture.

Both iperf listeners must use the logged commands from
[section 6](#6-start-both-iperf-servers-before-the-laptop-sequences).
Retain the FR1 and FR3 server directories to correlate connection/reset errors
with the Laptop's per-phase results.

For this diagnostic run, use **both** optional stack-capture launchers from
[DU1 startup](#5a-spark-du1-terminal) and [DU2 startup](#5b-spark-du2-terminal)
when preparing the testbed. Keep the two printed `/tmp/falcon-duN-crash.*`
directories with the xApp capture. A fresh trial is required after replacing
a running DU; repeat UE connection verification before traffic.

Before starting this capture, complete the preparation in the
[Laptop reconnect stability commands](dual_ue_laptop_reconnect_quick_start.md#7a-six-minute-stability-test--both-reconnect-watchers-stay-running)
until the traffic runner shows `READY` and both watchers have reported
`SUCCESS`. All Laptop transfers, watcher/traffic commands, phase schedules
and result checks are maintained there. Normal watcher pings stay enabled;
this test does not require RRC/Core idle.

**Spark xApp terminal — start the complete six-minute capture:**

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
IDENTITY_DUAL_RUN=$(mktemp -d /tmp/falcon-identity-dual.XXXXXXXX)
printf 'Spark capture directory: %s\n' "$IDENTITY_DUAL_RUN"
cp configs/ue_identity/local.json "$IDENTITY_DUAL_RUN/local.json"
cp configs/flexric/xapp_ue_identity_expanded.conf "$IDENTITY_DUAL_RUN/xapp.conf"
python3 scripts/ue_identity/xapp_ue_identity.py \
  --config "$IDENTITY_DUAL_RUN/local.json" \
  --e2-config "$IDENTITY_DUAL_RUN/xapp.conf" \
  --observed-unique --fresh-only --duration 360 \
  --text-output "$IDENTITY_DUAL_RUN/bindings.txt" \
  --capture-events "$IDENTITY_DUAL_RUN/inputs.ndjson" \
  > "$IDENTITY_DUAL_RUN/rows.ndjson" \
  2> "$IDENTITY_DUAL_RUN/xapp.log"
IDENTITY_DUAL_RC=$?
printf 'xApp exit=%s\n' "$IDENTITY_DUAL_RC" | tee "$IDENTITY_DUAL_RUN/exit.txt"
```

**Separate Spark diagnostics terminal — paste the printed capture directory:**

```bash
read -r -p 'Paste the current Spark capture directory: ' IDENTITY_WATCH_RUN
tail -n 40 "$IDENTITY_WATCH_RUN/xapp.log"
```

Expected: three successful subscriptions and
`identity collector: 3 KPM subscriptions, duration=360`. Continue the linked
Laptop procedure within ten seconds of subscriptions. Let the xApp finish its
full 360 seconds and cleanup even after traffic completes. The 300 seconds of
scheduled alternating/concurrent traffic leave startup and post-traffic
coverage; correlate against the Laptop's actual `events.ndjson` timestamps.

| Check after this run | Expected observation |
| --- | --- |
| Identity | After subscription warmup, both roles remain currently matched to their own SUPI/DNN/current IP; no cross-UE assignment or cached fallback. Count any later unresolved/ambiguous interval. |
| Delivery | Both DUs retain 100 ms granularity and receive/header intervals near 100 ms through solo, concurrent and low-traffic periods. Record p95/p99/max, gaps and ingress drops; CU stays near 1000 ms. |
| Measurements | All 27 raw names retain the contract's types/units; CQI/MCS sample validity, signed PHR, ages, REAL/INTEGER PRB and derived failure ratios remain consistent. Low-traffic RF `no_value` is allowed. |
| Traffic response | Each role's UL metrics follow its own iperf phases. The other role retains identity continuity; watcher probes can produce nonzero standby traffic. MAC/RLC rates need not equal application goodput. |
| Runtime and cleanup | No process crash; inspect RF underflow/late/busy and other DU warnings separately. Three subscription deletions and xApp exit 0 alone do not prove radio stability or physical RF accuracy. |

Keep the printed Spark capture, Laptop traffic evidence and **both reconnect
evidence directories**, together with DU/CU/RIC logs and **both DU debug
directories** when using stack capture. Keep the **FR1 and FR3 iperf server
directories** from section 6 as well. `status.json` / `backtrace.txt` are
written only after that debugger stops/exits, so they need not exist while a
healthy DU is still running. Timestamp/source checks
and metric correctness criteria are in the
[stability analysis reference](runbooks/dual_ue_laptop_reconnect_reference.md#six-minute-reconnect-stability-test).
The detailed raw capture inspection remains in the
[development reference](development/ue_identity_xapp.md#expanded-27-metric-capture-inspection).

### 7c. Live app subscription test with one dummy

Use this path for the Python matching/publisher version. **Run exactly one dummy
with `--all-links`**; it receives both DU/UE links in the same connection and TXT.
Finish any 7a/7b xApp first. Keep Core, RIC, CU, both DUs and both iperf servers
running, and complete the Laptop current-IP/route preflight. Healthy RAN services
can be reused. The three intended E2 nodes must already be present before xApp
startup. App reconnects do not reconnect the RAN or create more E2 subscriptions.

#### 7c1. Spark xApp terminal

Build the current C collector to a new run directory, even when reusing running
RAN services. This preserves the previous collector and uses the callback-entry
timestamps required by the subscription service. The Python service still owns
identity matching and publication. The build and configuration check start no
radio or RIC services; stop here on any error.

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
KPM_SUB_RUN=$(mktemp -d /tmp/falcon-dual-subscriptions.XXXXXXXX)
printf 'Subscription service directory: %s\n' "$KPM_SUB_RUN"
cp configs/ue_identity/local.json "$KPM_SUB_RUN/local.json"
cp configs/ue_identity/subscriptions.json "$KPM_SUB_RUN/subscriptions.json"
FALCON_IDENTITY_SM_DIR="$KPM_SUB_RUN/sm" \
  bash scripts/ue_identity/build.sh "$KPM_SUB_RUN/collector" &&
sed "s#^SM_DIR = .*#SM_DIR = \"$KPM_SUB_RUN/sm/\"#" \
  configs/flexric/xapp_ue_identity_expanded.conf > "$KPM_SUB_RUN/xapp.conf" &&
"$KPM_SUB_RUN/collector" --check-config "$KPM_SUB_RUN/xapp.conf" &&
"$KPM_SUB_RUN/collector" --check-clock
```

Keep the printed directory. Retain the source/configuration identities, then
start the service in the foreground:

```bash
git -C /home/nyu/Desktop/Falcon_repo/Falcon rev-parse HEAD > "$KPM_SUB_RUN/falcon-head.txt"
git -C /home/nyu/Desktop/Falcon_repo/Falcon status --short > "$KPM_SUB_RUN/falcon-status.txt"
git -C /home/nyu/flexric rev-parse HEAD > "$KPM_SUB_RUN/flexric-head.txt"
git -C /home/nyu/ocudu rev-parse HEAD > "$KPM_SUB_RUN/ocudu-head.txt"
sha256sum "$KPM_SUB_RUN/collector" "$KPM_SUB_RUN/sm/libkpm_sm.so" \
  "$KPM_SUB_RUN/local.json" "$KPM_SUB_RUN/xapp.conf" \
  "$KPM_SUB_RUN/subscriptions.json" scripts/ue_identity/*.py \
  scripts/ue_identity/e2_collector.c > "$KPM_SUB_RUN/sha256.txt"
set -o pipefail
(
  printf '%s\n' "$BASHPID" > "$KPM_SUB_RUN/xapp.pid"
  exec python3 -B scripts/ue_identity/xapp_ue_identity.py \
    --collector "$KPM_SUB_RUN/collector" \
    --config "$KPM_SUB_RUN/local.json" --e2-config "$KPM_SUB_RUN/xapp.conf" \
    --publish-config "$KPM_SUB_RUN/subscriptions.json" --fresh-only --duration 0 \
    --capture-events "$KPM_SUB_RUN/inputs.ndjson" \
    --report-evidence "$KPM_SUB_RUN/source.jsonl" \
    --publisher-summary "$KPM_SUB_RUN/publisher.json"
) 2>&1 | tee -i "$KPM_SUB_RUN/xapp.log"
KPM_SUB_RC=${PIPESTATUS[0]}
printf 'xApp exit=%s\n' "$KPM_SUB_RC" | tee "$KPM_SUB_RUN/exit.txt"
```

Require **both** readiness checkpoints in `xapp.log`:

- `SUBSCRIPTION_READY host=127.0.0.1 port=8765 profile=du27_bound_v1 source=e2`:
  the application listener is ready. It can admit a waiting application.
- Three registered E2 nodes, three successful subscriptions, and
  `identity collector: 3 KPM subscriptions, duration=0`: CU and both DUs are
  subscribed. Repeated correctly bound dummy reports below establish delivery.

Leave this terminal running. `--duration 0` runs until Ctrl+C. Routine xApp TXT
and per-report stdout are disabled; `inputs.ndjson` and `source.jsonl` are explicit
verification traces for this test. The service uses current explicit CU scope
from `local.json` and forces fresh-only matching. It pushes each new matched
report when generated, without another 100 ms transmission timer.

#### 7c2. Spark dummy terminal

In a new foreground terminal, paste the service directory. Variables do not
cross terminals. The first run uses **120 seconds**; after it passes, change
`DUMMY_SECONDS` to **1800** for a 30-minute single-client session. Run one session
at a time and retain a new output directory for each session.

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
read -r -p 'Paste the subscription service directory: ' KPM_SERVICE_RUN
DUMMY_SECONDS=120
KPM_DUMMY_RUN=$(mktemp -d /tmp/falcon-dual-dummy.XXXXXXXX)
printf 'Single dummy directory: %s\n' "$KPM_DUMMY_RUN"
printf '%s\n' "$KPM_SERVICE_RUN" > "$KPM_DUMMY_RUN/service-directory.txt"
printf '%s\n' "$DUMMY_SECONDS" > "$KPM_DUMMY_RUN/duration-seconds.txt"
set -o pipefail
python3 -B scripts/ue_identity/dummy_subscriber.py \
  --host 127.0.0.1 --port 8765 --app-id dual-ue-dummy --all-links \
  --expected-profile du27_bound_v1 --duration "$DUMMY_SECONDS" \
  --text-output "$KPM_DUMMY_RUN/bindings.txt" \
  --receipts-output "$KPM_DUMMY_RUN/receipts.jsonl" \
  --summary "$KPM_DUMMY_RUN/summary.json" --check-timing \
  2>&1 | tee -i "$KPM_DUMMY_RUN/dummy.log"
KPM_DUMMY_RC=${PIPESTATUS[0]}
printf 'dummy exit=%s\n' "$KPM_DUMMY_RC" | tee "$KPM_DUMMY_RUN/exit.txt"
```

This is one subscriber for both links. It sends heartbeat every 10 seconds,
validates complete 27-metric/binding envelopes, timestamps full-frame receipt,
and writes TXT in a separate bounded worker. At the end it unregisters, receives
the final acknowledgment/EOF, drains TXT and writes its summary. Leave the xApp
running until the dummy finishes. Current dummy reconnect is manual: rerun this
block with a new directory after the previous process exits.

The **xApp terminal** now prints `APP_REGISTER_RECEIVED`, followed by
`APP_REGISTERED` with the app/subscription IDs, filter and active registration
count. A rejected registration prints `APP_REGISTER_REJECTED` with its reason.
Normal completion prints `APP_UNREGISTER_RECEIVED`, `APP_UNREGISTERED`, then
`APP_DISCONNECTED` with `reason: drained`; unexpected closure/timeout/slow-client
removal carries its own reason. These UTC-stamped lines are retained in
`xapp.log`. `acknowledgement: queued` means the server accepted the request and
queued its response; check the dummy's received status below as well. Routine
KPM reports and heartbeat do not print lifecycle lines.

#### 7c3. Spark diagnostics terminal and Laptop traffic

Paste both directories in a third Spark terminal while the dummy is running:

```bash
read -r -p 'Paste the subscription service directory: ' KPM_CHECK_SERVICE
read -r -p 'Paste the single dummy directory: ' KPM_CHECK_DUMMY
tail -n 30 "$KPM_CHECK_SERVICE/xapp.log"
rg 'APP_(REGISTER|UNREGISTER|DISCONNECTED|REQUEST_REJECTED)' "$KPM_CHECK_SERVICE/xapp.log"
head -n 1 "$KPM_CHECK_DUMMY/receipts.jsonl" | python3 -m json.tool
tail -n 50 "$KPM_CHECK_DUMMY/bindings.txt"
```

Require the first JSON frame to be `registration_status`, `status: registered`,
`data_source: e2`, `metric_profile: du27_bound_v1`, with the all-links filter.
Both `DU_ID=1` and `DU_ID=2` must then appear in dummy TXT, currently matched to
their own SUPI/DNN and actual Laptop IPv4. Initial binding waits are allowed;
a successful listener/registration alone does not prove either link is receiving.
To watch TXT continuously, use `tail -n 50 -f "$KPM_CHECK_DUMMY/bindings.txt"`;
Ctrl+C there stops only `tail`.

Once registration and both links are receiving, immediately run the existing
Laptop upload command after its current-IP/route preflight:

```bash
python3 ~/falcon-ue-connect/run_dual_ul.py --seconds 60
```

Run that command **on the Laptop**, retaining its evidence directory and both
receiver summaries. Use the Laptop quick start's preflight and traffic commands;
this subscription test uses **Spark 7c instead of its older 7a capture launch**.
The xApp stays running after the 120-second dummy session. Low-traffic KPM
`no_value` is valid; stale/unmatched identities are withheld and reported as
binding state, without ending the app registration.

For the 30-minute session, keep the same single dummy connected for 1800 seconds.
Retain the declared traffic/gain schedule and all Laptop watcher events. In a
separate Spark terminal, sample Python service resources until it stops (Ctrl+C
ends only this monitor):

```bash
read -r -p 'Paste the subscription service directory: ' KPM_RESOURCE_RUN
KPM_RESOURCE_PID=$(cat "$KPM_RESOURCE_RUN/xapp.pid")
while kill -0 "$KPM_RESOURCE_PID" 2>/dev/null; do
  date -u '+%Y-%m-%dT%H:%M:%SZ'
  ps -p "$KPM_RESOURCE_PID" -o pid=,etimes=,%cpu=,rss=,vsz=,nlwp=
  sleep 5
done | tee -a "$KPM_RESOURCE_RUN/resources.log"
```

RSS/VSZ are KiB and `%CPU` is the process lifetime average. Keep raw samples and
queue/drop counters; elapsed time alone does not establish stability. For app
reconnect checks, let this dummy exit, rerun 7c2 with a fresh output directory
and the same app ID, and confirm a new subscription ID without restarting xApp
or adding E2 subscriptions. Keep only one dummy process active at a time.

#### 7c4. Check the completed dummy session

After dummy exit, in the diagnostics terminal:

```bash
cat "$KPM_CHECK_DUMMY/exit.txt"
cat "$KPM_CHECK_DUMMY/summary.json"
python3 - "$KPM_CHECK_SERVICE" "$KPM_CHECK_DUMMY" <<'PY_CHECK'
from collections import Counter
import json
from pathlib import Path
import struct
import sys
service, dummy = map(Path, sys.argv[1:])
frames = [json.loads(line) for line in (dummy/'receipts.jsonl').read_text().splitlines()]
registration, final = frames[0], frames[-1]
assert registration['status'] == 'registered' and registration['data_source'] == 'e2'
assert final['status'] == 'unregistered'
reports = [f for f in frames if f['type'] == 'kpm_report']
assert reports, 'No reports received'
summary = json.loads((dummy/'summary.json').read_text())
assert summary['status'] == 'passed' and summary['unregistered']
assert not summary['interrupted'], 'Dummy session stopped before its planned duration'
assert summary['reports_received'] == summary['text_reports_written'] == len(reports)
cutoff = int(registration['cutoff_at_mono_us'])
last = int(reports[-1]['report_seq'])
# The xApp is still running: read only newline-complete source trace records.
raw = (service/'source.jsonl').read_bytes().rsplit(b'\n', 1)[0]
source = [json.loads(line) for line in raw.splitlines() if line]
window = [t for t in source if int(t['callback_at_mono_us']) > cutoff
          and t['report']['sequence'] <= last]
assert all(t['ingress_admitted'] for t in window), 'Source handoff rejected'
assert [str(t['report']['sequence']) for t in window] == [r['report_seq'] for r in reports], 'Source/receipt gap or reordering'
text = (dummy/'bindings.txt').read_text()
blocks = {b.split('report_seq=')[1].split()[0]: b for b in text.split('subscription=')[1:]}
assert len(blocks) == len(reports), 'TXT count mismatch'
counts = Counter()
for frame, trace in zip(reports, window):
    report = frame['report']
    assert report == trace['report'], 'Changed binding or value'
    assert frame['ingress_dropped_total'] == report['ingress_dropped_total'] == '0'
    assert report['binding_status'] == 'matched' and report['row']['granularity_ms'] == 100
    assert len(report['row']['metrics']) == 27
    counts[report['node']['du_id']] += 1
    block = blocks[frame['report_seq']]
    assert f"UE_IPv4={report['ue_ipv4']}" in block and f"SUPI={report['binding']['supi']}" in block
    for name, metric in report['row']['metrics'].items():
        value = 'no_value' if metric['type'] == 'no_value' else json.dumps(metric['value'])
        assert f"{name} = {value} [{metric['unit']}] ({metric['type']})" in block
        if metric['type'] == 'real':
            assert struct.pack('>d', metric['value']).hex() == trace['real_bits'][name]
assert counts['1'] >= 100 and counts['2'] >= 100, counts
for link, timing in summary['per_link_interval_ms'].items():
    assert timing['p99'] <= 150 and timing['max'] <= 200, (link, timing)
print(json.dumps({'source_receipt_txt_window': 'passed', 'reports_by_du': counts,
                  'timing': summary['timing'], 'intervals': summary['per_link_interval_ms']}, indent=2))
PY_CHECK
```

Require dummy exit 0, summary `passed`, equal receive/TXT counts, correct current
IP/SUPI/DNN for each DU, and zero unexplained gaps. Compare the bindings with
Laptop truth independently. The source comparison covers admission through the
last delivered report; reports generated after unregister are outside that
session. Review startup/invalid-binding periods and acquisition loss separately
in `inputs.ndjson` and CU/Core logs. The retained JSONL contains binding-state and
heartbeat frames in addition to KPM, so total JSONL lines are not the report count.

`--check-timing` enforces ready→receipt p95 ≤ 10 ms, p99 ≤ 25 ms, max ≤ 100 ms,
and callback→receipt p99 ≤ 100 ms. The additional check above requires per-link
receipt-interval p99 ≤ 150 ms and max ≤ 200 ms. Receipt time precedes TXT work;
writer delay is separate in `summary.json`. Preserve any missed budget or source
outage with its timestamps. A 120-second pass is functional evidence; the longer
run records **one-client** stability under its actual traffic/source conditions.

Finish Laptop traffic and all dummy sessions, then press Ctrl+C in the **xApp
terminal**. Keep CU, both DUs and RIC alive during E2 cleanup. In diagnostics:

```bash
cat "$KPM_CHECK_SERVICE/exit.txt"
cat "$KPM_CHECK_SERVICE/publisher.json"
```

Require xApp exit 0, `status: passed`, no failures, three normal E2 deletions,
zero active connections/registrations and empty ingress. For a healthy run,
`ingress_dropped`, `client_overflows`, `serialization_errors`, `invalid_reports`,
`expired_reports` and unexpected disconnect counters must be zero (absent counters
mean zero); normal `disconnect_drained` records completed unregisters. Retain
all raw failures and both run directories. The full
[interface guide](kpm_app_interface.md) documents lifecycle and bounds.

## 8. Shutdown and retained evidence

For section 7c, finish Laptop traffic, let the single dummy unregister and drain
TXT, then press Ctrl+C in the xApp terminal. Require dummy and xApp exit 0,
zero active registrations in the service summary, and all three E2 subscription
delete responses while CU/DUs/RIC are still running. For sections 7a/7b, allow
the finite diagnostic xApp to receive all three delete responses and stop
naturally. If using reconnect watchers, press Ctrl+C
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

For section 7c retain the complete service and dummy directories: binary/plugin
and configuration identities, `xapp.log`, `inputs.ndjson`, `source.jsonl`,
`publisher.json`, both exit files, dummy `bindings.txt`, `receipts.jsonl`,
`summary.json` and optional `resources.log`. Keep each sequential dummy session
separately when checking reconnects.

For sections 7a/7b retain each capture's `local.json`, `xapp.conf`, `exit.txt`, `inputs.ndjson`,
`rows.ndjson`, `bindings.txt` and `xapp.log`, together with the
RIC/CU/DU startup logs, actual source revisions and Laptop truth/events/client
logs/summary. Also retain both `/tmp/falcon-iperf-fr1.*` and
`/tmp/falcon-iperf-fr3.*` server directories, including `server.log` and the
post-exit `exit.txt`. `/tmp` may be cleared on reboot: copy the printed evidence
directories to a persistent experiment directory before shutdown. Keep raw
security-bearing Core logs and K/OPc outside Git. The October 21 live functional
results are retained in the [report](reports/ue_identity_dual_ue_live_2026-10-21.md);
record the new cold-start outcome separately from those historical trials.
