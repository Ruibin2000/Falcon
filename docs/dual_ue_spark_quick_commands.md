# Dual UE Spark Quick Commands — UE IP Binding and UL

Updated: 2026-10-23. Developer: Ruibin Chen. This is the Spark half of the
operator-run reproduction of the October 21 CU/DU/Core UE IP binding. The
[live report](reports/ue_identity_dual_ue_live_2026-10-21.md) describes the final
implementation and six-minute bidirectional idle/resume capture
(645 matched / 648 records, zero cached). During each UE's
actual Core idle interval, its active peer had 30 consecutive matched UL rows.
Small startup/resume boundary gaps were retained and explained. New runs must
verify their actual identities and inputs; these counts and numeric IDs are
historical results, not expected allocations.

The standalone xApp combines DU KPM, CU identity-bearing E2 reports and existing
read-only AMF/SMF infoAPIs. Its `bindings.txt` contains only xApp records:
gNB/DU/F1 UE ID, SUPI, NGAP IDs/GUAMI, PDU session/DNN/IP, then KPM. The commands
below use `--observed-unique`; strict serving-DU/context-generation proof and
remaining restart/reuse/performance gates are still open in
[Plan 4](../plans/cu-ue-ip-e2-binding.md). Core source/IP allocation and Plan 2
broker/MPX integration are outside this change. The
[October 13 DU-only UL/KPM results](evidence/2026-10-13_dual_kpm_reports/manifest.json)
remain historical [Plan 3](../plans/dual-ue-du-fr1-channels.md) evidence.

Run all commands in this file on Spark. Use Bash and separate foreground
terminals for CU, RIC, each DU, each iperf server and xApp. Modem/AT/routing/client
commands are in [Dual UE Laptop Quick Commands](dual_ue_laptop_quick_commands.md).
Cold-start order: prepare candidate artifacts → Core → identity-configured RIC
→ identity-enabled CU → both DUs → both servers → complete Laptop UE1 sequence
→ complete Laptop UE2 sequence → section 7 binding tests. Every service/client
is started manually in the foreground. Reuse healthy infrastructure during
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
post-split UE/PDU/ping/traffic and cold-boot validation remain pending.

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

Require `PASS`. Keep the actual recorded RF conditions from Plan 3. The current
configs use TX 70 / RX 35 and 23.04 MS/s; these gains are not calibrated dBm.
Host performance restoration, when needed after reboot, is in
[step 2](#2-restore-performance-settings-after-reboot).

### 1a. Prepare the CU identity binary and isolated FlexRIC plugin

Run before starting CU/RIC/xApp. These are local builds; they start no services.
Both repositories must be on `Dual-UE` with the October 21 identity implementation present:

```bash
git -C /home/nyu/Desktop/Falcon_repo/Falcon branch --show-current
git -C /home/nyu/ocudu branch --show-current
cd /home/nyu/Desktop/Falcon_repo/Falcon
cmake --build /home/nyu/ocudu/build --target ocu -j4 &&
bash scripts/ue_identity/build.sh &&
/tmp/falcon-xapp-ue-identity --check-config configs/flexric/ric_ue_identity.conf &&
/tmp/falcon-xapp-ue-identity --check-config configs/flexric/xapp_ue_identity.conf
```

Stop on any build/config error. Require `/tmp/falcon-xapp-ue-identity` and
`/tmp/falcon-ue-identity-sm/libkpm_sm.so`. Rebuild after `/tmp` is cleared/rebooted.
The isolated KPM plugin includes the 40-bit AMF ID decoder fix; both RIC and
xApp configs select it. Installed FlexRIC files and its source tree are left
unchanged. Build only `ocu` here; retain the accepted DU executable/configs.
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
sudo stdbuf -oL -eL build/apps/cu/ocu \
  -c configs/cu.yml \
  -c /home/nyu/Desktop/Falcon_repo/Falcon/configs/ocudu/cu_identity_e2.yml \
  log --filename "$IDENTITY_CU_RUN/cu.log" \
  2>&1 | tee "$IDENTITY_CU_RUN/console.log"
```

Require N2 connection to `127.0.0.5:38412`, E2 connection to RIC, F1 listener
`127.0.10.1:38472`, and `==== CU started ===`. RIC must accept the CU/gNB 411
node and KPM function 2. The overlay enables CU-CP E2/identity metrics; using
only `configs/cu.yml` will omit the identity source required by this test.
Keep this terminal running. If RIC restarts, stop the test and restart CU and
both DUs in order before launching a new xApp; automatic E2 recovery is not
assumed.

## 5. Start DU1 and DU2 in separate terminals and keep both running

Complete the shared MongoDB/core/CU/RIC startup first. Start each DU in its own
foreground terminal before beginning either laptop UE sequence. Both DUs stay
running while UE1 and UE2 are prepared and measured.

The [console launcher](../scripts/dual_fr1/run_du_console.sh) uses util-linux
`script` to give sudo and the DU terminal-backed stdin/stdout/stderr while
recording `startup.log`. Run it directly in an interactive terminal. It
replaces the old `sudo ... | tee` pipeline, which left the DU behind sudo's
pseudo-terminal foreground group and prevented console input. The launcher
flushes output and propagates the child exit status; see
[script(1)](https://man7.org/linux/man-pages/man1/script.1.html).

### 5a. Spark DU1 terminal

```bash
cd /home/nyu/ocudu
DU1_RUN=$(mktemp -d /tmp/falcon-du1-3660.XXXXXXXX)
printf 'DU1 run directory: %s\n' "$DU1_RUN"
bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1/run_du_console.sh \
  "$DU1_RUN/startup.log" \
  sudo stdbuf -oL -eL build/apps/du_split_8/odu \
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
  sudo stdbuf -oL -eL build/apps/du_split_8/odu \
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
The laptop then follows the [complete UE1 sequence](dual_ue_laptop_quick_commands.md#ue1-start)
in its own terminal, followed by the [complete UE2 sequence](dual_ue_laptop_quick_commands.md#ue2-start)
in another terminal. Each sequence includes identity/cell/PDU, complete role reset,
its own table/rules, private ping and individual UL with the other UE's test
traffic idle. Keep both PDU paths active for the concurrent test in step 7.

## 7. Reproduce UE IP binding with the new CU/DU xApp

Complete both Laptop UE sequences, including current IMEI/IMSI/cell/bearer/IP
and route checks. Install or reuse `~/falcon-dual-ul.py` from
[Laptop section 3](dual_ue_laptop_quick_commands.md#dual-ul), then run its
`--check-only` preflight. Keep the two verified PDU paths and both foreground
iperf servers. Finish any other finite xApp before starting this one.

RIC must have accepted **three** intended nodes: CU/gNB 411, DU1 and DU2.
The xApp discovers nodes at startup; start it only after all three register.
The old DU-only monitor subscribes twice and cannot perform this IP join.
These tests use `--observed-unique --fresh-only`: current observations may
establish experimental bindings; historical IP fallback is disabled so a
`cached` record cannot conceal a failed current match. Normal `local.json`
retains its last-known policy outside these explicit tests.

### 7a. First verify both IP bindings during a 60-second dual upload

In the Spark xApp terminal:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
IDENTITY_DUAL_RUN=$(mktemp -d /tmp/falcon-identity-dual.XXXXXXXX)
printf 'Spark capture directory: %s\n' "$IDENTITY_DUAL_RUN"
cp configs/ue_identity/local.json "$IDENTITY_DUAL_RUN/local.json"
sha256sum scripts/ue_identity/*.py scripts/ue_identity/e2_collector.c \
  configs/ue_identity/local.json configs/flexric/*ue_identity.conf \
  configs/ocudu/cu_identity_e2.yml /tmp/falcon-xapp-ue-identity \
  /tmp/falcon-ue-identity-sm/libkpm_sm.so \
  /home/nyu/ocudu/build/apps/cu/ocu /home/nyu/ocudu/build/apps/du_split_8/odu \
  > "$IDENTITY_DUAL_RUN/source-sha256.txt"
printf '%s\n' '--observed-unique --fresh-only --duration 120' \
  > "$IDENTITY_DUAL_RUN/cli-overrides.txt"
python3 scripts/ue_identity/xapp_ue_identity.py \
  --config configs/ue_identity/local.json \
  --observed-unique --fresh-only --duration 120 \
  --text-output "$IDENTITY_DUAL_RUN/bindings.txt" \
  --capture-events "$IDENTITY_DUAL_RUN/inputs.ndjson" \
  > "$IDENTITY_DUAL_RUN/rows.ndjson" \
  2> "$IDENTITY_DUAL_RUN/xapp.log"
IDENTITY_DUAL_RC=$?
printf 'xApp exit=%s\n' "$IDENTITY_DUAL_RC" | tee "$IDENTITY_DUAL_RUN/exit.txt"
```

While this command is running, in a separate Spark diagnostics terminal use the
printed directory (shell variables do not cross terminals):

```bash
read -r -p 'Paste the current Spark capture directory: ' IDENTITY_WATCH_RUN
tail -n 25 "$IDENTITY_WATCH_RUN/xapp.log"
```

Require `Registered E2 Nodes = 3`, three successful subscription responses and
`identity collector: 3 KPM subscriptions, duration=120`. Then run
`python3 ~/falcon-dual-ul.py` on Laptop as instructed in its section 3.
Let both clients and the xApp finish naturally. Use 7c to inspect this capture.
Both roles must have matched positive-UL rows with their independently observed
current IPs, expected SUPIs/DNNs and actual DU/F1/NGAP identities. Require at
least 30 complete active samples per role; explain startup gaps individually.
The actual IPs/IDs/counts need not equal the October 21 report.

### 7b. Six-minute bidirectional idle/resume and independent matching

After the short test passes, leave Core/RIC/CU/DUs/servers and both PDU sessions
running. Close other clients and periodic ping/WWAN traffic. Keep CU's current
120-second inactivity timer; each role's 150-second quiet phase must produce
an actual Core idle observation. Do not disconnect either bearer or power-cycle
modems during this test.

1. On Laptop, prepare the inline command in
   [section 3.1](dual_ue_laptop_quick_commands.md#binding-idle). Leave it at `READY`.
2. On Spark, start this new foreground capture:

   ```bash
   cd /home/nyu/Desktop/Falcon_repo/Falcon
   IDENTITY_BIDIR_RUN=$(mktemp -d /tmp/falcon-identity-bidir.XXXXXXXX)
   printf 'Spark capture directory: %s\n' "$IDENTITY_BIDIR_RUN"
   cp configs/ue_identity/local.json "$IDENTITY_BIDIR_RUN/local.json"
   sha256sum scripts/ue_identity/*.py scripts/ue_identity/e2_collector.c \
     configs/ue_identity/local.json configs/flexric/*ue_identity.conf \
     configs/ocudu/cu_identity_e2.yml /tmp/falcon-xapp-ue-identity \
     /tmp/falcon-ue-identity-sm/libkpm_sm.so \
     /home/nyu/ocudu/build/apps/cu/ocu /home/nyu/ocudu/build/apps/du_split_8/odu \
     > "$IDENTITY_BIDIR_RUN/source-sha256.txt"
   printf '%s\n' '--observed-unique --fresh-only --duration 360' \
     > "$IDENTITY_BIDIR_RUN/cli-overrides.txt"
   python3 scripts/ue_identity/xapp_ue_identity.py \
     --config configs/ue_identity/local.json \
     --observed-unique --fresh-only --duration 360 \
     --text-output "$IDENTITY_BIDIR_RUN/bindings.txt" \
     --capture-events "$IDENTITY_BIDIR_RUN/inputs.ndjson" \
     > "$IDENTITY_BIDIR_RUN/rows.ndjson" \
     2> "$IDENTITY_BIDIR_RUN/xapp.log"
   IDENTITY_BIDIR_RC=$?
   printf 'xApp exit=%s\n' "$IDENTITY_BIDIR_RC" | tee "$IDENTITY_BIDIR_RUN/exit.txt"
   ```

3. Within ten seconds of starting xApp, return to Laptop, enter `START` and
   press Enter. The command runs UE1 15 s UL → 150 s quiet → 170 s UL, and UE2
   175 s UL → 150 s quiet → 10 s UL. Let all four clients and the full capture
   finish. No assistant-launched background program is needed.
4. Inspect this new directory using 7c and retain the Laptop summary/logs too.

### 7c. Inspect bindings, Core transitions and two example records

Run after either capture finishes. Paste that capture's printed directory:

```bash
read -r -p 'Paste the completed Spark capture directory: ' IDENTITY_CHECK_RUN
cat "$IDENTITY_CHECK_RUN/exit.txt"
grep -E 'Registered E2 Nodes|identity collector:|DELETE RESPONSE|Sucessfully stopped' \
  "$IDENTITY_CHECK_RUN/xapp.log"
python3 - "$IDENTITY_CHECK_RUN" <<'PY_CHECK'
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

root = Path(sys.argv[1])
rows = [json.loads(line) for line in (root / 'rows.ndjson').open()]
events = [json.loads(line) for line in (root / 'inputs.ndjson').open()]
print('Records:', len(rows), dict(Counter(r['binding_status'] for r in rows)))
print('App instances:', sorted({r['app_instance'] for r in rows}))
problems = [e for e in events if e['kind'] not in ('core_snapshot', 'kpm_report')
            or int(e.get('ingress_dropped_total', 0)) != 0]
print('Core/input errors or loss events:', len(problems))
for event in problems[:5]:
    print(event)
for du in ('1', '2'):
    selected = [r for r in rows if str(r['node'].get('du_id')) == du]
    print('DU' + du, dict(Counter(r['binding_status'] for r in selected)))
    signatures = sorted({
        (r['row']['ue']['gnb_cu_ue_f1ap_id'], r['binding']['supi'],
         r['binding']['amf_ue_ngap_id'], r['binding']['ran_ue_ngap_id'],
         r['binding']['dnn'], r['ue_ipv4'])
        for r in selected if r['binding_status'] == 'matched'})
    print('F1 / SUPI / AMF / RAN / DNN / IP:', signatures)
    print('Assurance:', dict(Counter(r.get('binding', {}).get('assurance', 'none') for r in selected)))
    print('Unmatched reasons:', dict(Counter(r['reason'] for r in selected if r['binding_status'] != 'matched')))
previous, idle_start, episodes = {}, {}, []
for event in events:
    if event['kind'] != 'core_snapshot':
        continue
    for ue in event['amf']:
        state = (ue['cm_state'], ue['gnb'].get('amf_ue_ngap_id'), ue['gnb'].get('ran_ue_ngap_id'))
        before = previous.get(ue['supi'])
        if before and before[0] == 'connected' and state[0] == 'idle':
            idle_start[ue['supi']] = int(event['received_at_us'])
        if state[0] == 'connected' and ue['supi'] in idle_start:
            episodes.append((ue['supi'], idle_start.pop(ue['supi']), int(event['received_at_us'])))
        if previous.get(ue['supi']) != state:
            stamp = datetime.fromtimestamp(int(event['received_at_us']) / 1e6, timezone.utc).astimezone(ZoneInfo('America/New_York'))
            print('Core transition:', stamp.isoformat(), ue['supi'], state)
            previous[ue['supi']] = state
peer_du = {'imsi-001010000000101': '2', 'imsi-001010000000102': '1'}
print('Completed connected -> idle -> connected intervals:', len(episodes))
for supi, begin, end in episodes:
    peer = peer_du.get(supi)
    selected = [r for r in rows if peer and str(r['node'].get('du_id')) == peer
                and begin <= int(r['received_at_us']) < end]
    print('Idle:', supi, 'seconds:', round((end - begin) / 1e6, 3),
          'peer DU:', peer, 'statuses:', dict(Counter(r['binding_status'] for r in selected)))
    print('Peer established-scope current matches:', sum(
        r['binding_status'] == 'matched' and
        r['binding']['assurance'] == 'established_du_scope_current_context' for r in selected))
    print('Peer positive-UL rows:', sum(
        (r['row']['metrics'].get('DRB.UEThpUl', {}).get('value') or 0) > 0 for r in selected))
if idle_start:
    print('Incomplete idle intervals at capture end:', sorted(idle_start))
blocks = (root / 'bindings.txt').read_text().split('\n\n')
for du in ('1', '2'):
    example = next((b for b in blocks if b.startswith('record=') and ' status=matched ' in b
                    and f' DU_ID={du} ' in b), None)
    print('\nDU' + du + ' example:\n' + (example or 'No matched record'))
PY_CHECK
```

This is an inspection summary, not an independent proof of every join. Compare
Laptop `summary.json`/`truth.json` IMEI/IMSI/APN/current IP with the actual
AMF/SMF and CU/DU events in `inputs.ndjson`, then the output rows/TXT. The
[matching topology and provider fields](reports/ue_identity_dual_ue_live_2026-10-21.md#matching-topology-and-information-supplied-by-each-component)
explain the chain. `bindings.txt` contains only xApp output; SDK messages are
in `xapp.log`, and inputs are separate. NGAP and F1 numbers are typed identifiers;
matching them does not rely on numeric equality.

For the **six-minute test**, require all of the following:

- One 360-second xApp instance, three intended subscriptions, all three delete
  responses, xApp exit 0 and no Core/input errors or ingress loss.
- Both UEs establish at least five consecutive matched samples, then each
  actually moves Core connected → idle → connected. Each observed idle interval
  should last at least ten seconds; quiet traffic alone does not prove idle.
- During each idle interval, the other UE keeps at least ten consecutive
  current `matched` records after the silent DU is outside the three-second
  TTL. Its own fresh CU/Core inputs and IP/DU/F1/NGAP/SUPI must agree. Silence
  on the other DU alone must not cause `cached` or missing IP.
- Each resumed UE gets at least five consecutive fresh matches for its actual
  new context, with no cross-UE binding. Check convergence within three reporting
  periods from the later matching fresh CU/Core prerequisite. Explain all
  startup/resume unresolved rows; never fill them with another context's IP.
- Both sessions retain their IP during ordinary idle. Investigate any change.
  All four Laptop clients exit 0 with receiver summaries and `STATUS: completed`.
  Keep/report any zero-throughput intervals; exit 0 does not prove stall-free UL.

`--fresh-only` requires zero cached records. Normal last-known mode may label
missing own verification inputs as `cached`; it is separate from this test.
Compare times within Spark's Core/CU/DU capture. Laptop wall-clock alignment
is uncalibrated; do not reuse the old approximate 199-second clock correction.
A successful new run from stopped infrastructure establishes this stage's
cold-start reproducibility; it does not close all strict lifecycle/reuse,
restart/recovery or repeated performance gates.

## 8. Shutdown and retained evidence

Finish laptop traffic and allow the finite xApp to receive all three subscription
delete responses and stop naturally. Then follow [separate laptop shutdown](dual_ue_laptop_quick_commands.md#cleanup):
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

Retain each capture's `local.json`, `cli-overrides.txt`, `source-sha256.txt`, `exit.txt`,
`inputs.ndjson`, `rows.ndjson`, `bindings.txt` and `xapp.log`, together with the
RIC/CU/DU startup logs, actual source revisions and Laptop truth/events/client
logs/summary. `/tmp` may be cleared on reboot: copy the printed evidence
directories to a persistent experiment directory before shutdown. Keep raw
security-bearing Core logs and K/OPc outside Git. The October 21 live functional
results are retained in the [report](reports/ue_identity_dual_ue_live_2026-10-21.md);
record the new cold-start outcome separately from those historical trials.
