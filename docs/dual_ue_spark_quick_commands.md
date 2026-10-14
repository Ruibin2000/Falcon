# Dual UE Spark Quick Commands — UL Only

Updated: 2026-10-13. Both intended SIMs have registered on their intended
cells and both private paths pinged successfully. UE2 single-DU UL passed at
receiver 15.5 Mbit/s / Retr 1 with 12 KPM smoke reports. UE1 UL with UE2 test
traffic idle passed at receiver 10.5 Mbit/s / Retr 0 / pipeline exit 0. See
[UE1 UL evidence](evidence/2026-10-13_du1_ul/manifest.json),
[UE2 UL evidence](evidence/2026-10-13_du2_ul/manifest.json) and
[dual IPv4 path evidence](evidence/2026-10-13_dual_ipv4_paths/manifest.json).

The latest measured concurrent TCP UL passed: receiver **UE1 13.8 Mbit/s /
UE2 17.3 Mbit/s**, both sender Retr 0, both process exits 0. Spark received
**123 UE callbacks per DU**, including 63/61 complete UL-active five-metric rows;
approximately 62/61 fall inside the clock-corrected laptop run window. Both
subscription/deletion pairs and normal xApp exit passed. See
[dual UL/KPM evidence and plots](evidence/2026-10-13_dual_kpm_reports/manifest.json).
The manually simultaneous clock readbacks put Spark about **199.27 seconds
ahead of Laptop**; the corrected latest window is 22:17:25–22:18:27 EDT.
Precise clock synchronization, full cross-layer identity correlation and the
remaining repeated/UDP/guard/survivor/cold-start acceptance are pending.
The earlier [subscription-only probe](evidence/2026-10-13_dual_kpm_subscriptions/manifest.json)
received zero UE callbacks and remains historical evidence.
UL is the acceptance target; underflow count/growth remediation is deferred.
Wrong-cell attachment, lost SA/PDU, wrong IP paths, failed UL and missing UL
telemetry still keep their acceptance gates pending. See
[Plan 3](../plans/dual-ue-du-fr1-channels.md).

Run all commands in this file on Spark. Use Bash and separate foreground
terminals for CU, RIC, each DU, each iperf server and xApp. Modem/AT/routing/client
commands are in [Dual UE Laptop Quick Commands](dual_ue_laptop_quick_commands.md).
Daily order: shared core/CU/RIC → both DUs → both servers → complete laptop
UE1 sequence → complete laptop UE2 sequence → concurrent UL/KPM. Reuse running
infrastructure during modem recovery; steps 1–5 cover a stopped testbed.
After a modem power cycle, repeat the affected role's complete laptop sequence
([UE1](dual_ue_laptop_quick_commands.md#ue1-start) / [UE2](dual_ue_laptop_quick_commands.md#ue2-start)) before traffic. The operator reported
lock query `0`; its lock must be restored and the actual serving cell verified.
The latest measured laptop launcher record has UE1 modem/SIM 13 / bearer 9 /
`10.45.0.6/30` / `wwan0` / table 151, and UE2 modem/SIM 14 / bearer 10 /
`10.46.0.5/30` / `wwan1` / table 152. Identity, bearer and both source-bound /
ordinary routes passed before traffic. CU records tie DU1 / PCI1 to F1AP UE 11
and DU2 / PCI2 to F1AP UE 7. Full modem/SIM-to-F1AP correlation remains a
separate ledger. Earlier modem 9/10 and bearer 7/8 preflight allocations are
historical. The launcher supports indexed access-tech fields and records the
bearer default gateway while actual routes determine the server path.
UE1's earlier `10.45.0.3/29` / `wwan0` and UE2's earlier bearer 5 /
`10.46.0.3/29` are historical. Keep the Spark `.1` endpoints and discover both
current laptop bearer allocations and host routes with the updated launcher.
The explicit table-151/table-152 inspection, complete per-role host IPv4 reset
without old-session parameters, guarded rebuilding and both private-path checks are in
[UE1 recovery](dual_ue_laptop_quick_commands.md#ue1-clean-old-path) and
[UE2 recovery](dual_ue_laptop_quick_commands.md#ue2-clean-old-path).
These tables belong to the laptop. Spark keeps service addresses `10.45.0.1`
and `10.46.0.1`, and its two iperf listeners continue to use the same bindings.

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
| Spark iperf3 port | `5201` | `5202` |
| Proposed policy table / lookup / guard priority | `151` / `10151` / `10152` | `152` / `10161` / `10162` |
| WWAN / UE IP / modem / bearer / AT port | Discover each run | Discover each run |

The reviewed dual-subnet migration is complete. Preserve bundle
`/tmp/falcon-dual-subnets.Ir8TjqjO`; do not reapply the first-migration script to
the migrated core. See [Dual UE Subnets](dual_ue_subnets.md). Both cells use
PLMN `00101`, TAC 7, SST 1 and n78 / 20 MHz / SCS 30 kHz. Keep K/OPc private
and preserve the baseline subscriber; do not blindly reset SQN.

## 1. Check radios and deploy configuration before a cold start

For a cold start, check hardware while both DUs are stopped. Keep the verified
separate USB controller arrangement. The observed paths were DU1 `2-1.3` /
`NVDA8000:00` and DU2 `6-1.1` / `NVDA8000:02`; rediscover after reconnection.

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
Wait for UHD firmware loading and rediscovery to complete.

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
the [subscriber procedure](sim_provisioning_and_dual_ue.md#prepare-open5gs-subscribers).
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
ip -o link show dev ogstun
ip -o -4 addr show dev ogstun
ip -4 route show 10.45.0.0/16
ip -4 route show 10.46.0.0/16
```

Require `10/10`; `ogstun` must be UP, MTU 1400, with addresses `10.45.0.1/16`
and `10.46.0.1/16`, and both private routes through `ogstun`. The second DNN,
subscriber and address setup is in the [migration guide](dual_ue_subnets.md).
Original single-subnet repair is in the
[full runbook](full_reproduction_runbook.md#7-start-only-the-required-5gc-functions).

## 4. Start CU and RIC in separate foreground terminals

**CU terminal:**

```bash
cd /home/nyu/ocudu
CU_RUN=$(mktemp -d /tmp/falcon-dual-cu.XXXXXXXX)
printf 'CU run directory: %s\n' "$CU_RUN"
sudo build/apps/cu/ocu -c configs/cu.yml log --filename "$CU_RUN/cu.log"
```

Require N2 connection to `127.0.0.5:38412` completed, F1 listener
`127.0.10.1:38472`, and `==== CU started ===`. Keep this terminal running.

**RIC terminal:**

```bash
RIC_RUN=$(mktemp -d /tmp/falcon-dual-ric.XXXXXXXX)
printf 'RIC run directory: %s\n' "$RIC_RUN"
set -o pipefail
stdbuf -oL -eL /usr/local/bin/flexric/ric/nearRT-RIC \
  -c /usr/local/etc/flexric/ric.conf 2>&1 | tee "$RIC_RUN/ric.log"
```

Require E2 port `36421`, E42 port `36422` and KPM SM ID `2` loaded. Keep RIC
running; a RIC restart requires restarting DUs before the next E2/xApp test.

## 5. Start DU1 and DU2 in separate terminals and keep both running

Complete the shared MongoDB/core/CU/RIC startup first. Start each DU in its own
foreground terminal before beginning either laptop UE sequence. Both DUs stay
running while UE1 and UE2 are prepared and measured.

### 5a. Spark DU1 terminal

```bash
cd /home/nyu/ocudu
DU1_RUN=$(mktemp -d /tmp/falcon-du1-3660.XXXXXXXX)
printf 'DU1 run directory: %s\n' "$DU1_RUN"
set -o pipefail
sudo stdbuf -oL -eL build/apps/du_split_8/odu \
  -c configs/du1_b210_n78_3660mhz.yml \
  log --filename "$DU1_RUN/du.log" 2>&1 | tee "$DU1_RUN/startup.log"

```

Require radio `3271233` / USB 3, PCI 1 / carrier `644000` / SSB `643680`,
F1/E2 completed, `==== DU started ===`, and RIC accepted gNB 411 / DU ID 1.
Leave this terminal running.

### 5b. Spark DU2 terminal

```bash
cd /home/nyu/ocudu
DU2_RUN=$(mktemp -d /tmp/falcon-du2-3600.XXXXXXXX)
printf 'DU2 run directory: %s\n' "$DU2_RUN"
set -o pipefail
sudo stdbuf -oL -eL build/apps/du_split_8/odu \
  -c configs/du2_b210_n78_20mhz.yml -c configs/du2_flexric.yml \
  log --filename "$DU2_RUN/du.log" 2>&1 | tee "$DU2_RUN/startup.log"

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

## 7. KPM subscriptions and actual two-link metric delivery

RIC must have registered `gnb=411 / DU ID 1` and `gnb=411 / DU ID 2`, accepting KPM
RAN function ID 2 for both. Keep both DUs and RIC running. Complete any existing
finite monitor before launching another. Start the 120-second capture first;
after both subscriptions succeed, run [laptop section 3](dual_ue_laptop_quick_commands.md#dual-ul)'s concurrent clients.
The updated laptop launcher reads both current bearers by IMEI/SIM and checks
both routes before starting traffic; complete its `--check-only` preflight before
starting this timed capture. Historical IP/interface tuples must not be reused.

The historical DU2-only stock-monitor run remains retained evidence. Its
callback prints the shared gNB ID without DU ID. Use the DU-tagged diagnostic
below for the current two-DU workflow; require actual reports from both nodes.
DL values remain observations; report age is not application RTT.

### 7a. Build the DU-tagged diagnostic

The maintained source derives from the pinned local FlexRIC monitor. It adds
DU identity to every callback block, configurable finite capture duration and
dense subscription-handle cleanup. Reuse the current pinned API/library:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
bash scripts/dual_fr1/build_kpm_monitor.sh /tmp/falcon-xapp-oran-moni-dual
```

Require `Built: /tmp/falcon-xapp-oran-moni-dual`. This leaves installed FlexRIC
binaries and the running RIC/DUs intact. It expects the current E2AP v3 / KPM v3
build under `/home/nyu/flexric/build-ocudu`; compare build flags before using a
different FlexRIC build.

### 7b. Capture while both UEs upload

Run in the Spark xApp terminal:

```bash
XAPP_RUN=$(mktemp -d /tmp/falcon-dual-kpm.XXXXXXXX)
printf 'KPM evidence: %s\n' "$XAPP_RUN"
TZ=America/New_York date -Ins | tee "$XAPP_RUN/start.txt"
set -o pipefail
FALCON_KPM_SECONDS=120 /tmp/falcon-xapp-oran-moni-dual \
  -c /usr/local/etc/flexric/xapp_oran_sm.conf \
  2>&1 | tee "$XAPP_RUN/kpm.log"
XAPP_RC=$?
printf 'pipeline_exit=%d\n' "$XAPP_RC" | tee "$XAPP_RUN/exit.txt"
TZ=America/New_York date -Ins | tee "$XAPP_RUN/end.txt"
```

Before laptop clients start, require both `FALCON_E2_NODE` lines with DU IDs 1
and 2, two successful KPM subscriptions and
`FALCON_CAPTURE subscriptions_kpm=2`. During upload, require `FALCON_KPM_NODE`
blocks from both DU IDs, `UE ID ... gnb_cu_ue_f1ap` lines, all five numeric metrics
and `report_age_us`. Each node header applies to its following callback block;
preserve complete blocks when associating UE/metrics with the DU.

Let the monitor finish naturally. Require both delete responses, normal stop,
success marker and pipeline exit 0. Inspect:

```bash
grep -E 'FALCON_E2_NODE|FALCON_CAPTURE|FALCON_KPM_NODE|UE ID type|DRB.UEThpUl|RRU.PrbTotUl|DELETE RESPONSE|SUCCESSFULLY' "$XAPP_RUN/kpm.log"
cat "$XAPP_RUN/exit.txt"
```

Keep the full log and both laptop logs/time bounds. Subscription or exit 0 alone
does not prove UE KPM delivery. Full acceptance requires at least 30 complete
real UL-window rows per link and DU/F1AP UE/modem/SIM/cell/bearer correlation.
Refresh the mapping after UE ID changes.

The completed 19:29:23–19:30:14 EDT probe discovered both DU IDs, subscribed
twice, deleted twice and exited 0, but received zero UE callback blocks. The
automatic follow-up did not execute; manual capture commands were supplied.
Two subsequent 120-second captures completed normally with 123 callbacks per
DU. The latest `0B8F17Sp` capture aligns with the operator's concurrent UL after
the approximate +199.27-second clock correction; it contains 61 near-simultaneous
complete UL-active row pairs. See the [retained analysis](evidence/2026-10-13_dual_kpm_reports/manifest.json).
Normal completion did not exercise the earlier disconnected-xApp deletion-failure
abort path. That FlexRIC failure-path defect remains unfixed; both delete
responses and normal exit are still required for each new capture.

## 8. Shutdown and retained evidence

Finish laptop traffic and allow the finite xApp to receive both subscription
delete responses and stop naturally. Then follow [separate laptop shutdown](dual_ue_laptop_quick_commands.md#cleanup):
UE1 first, then UE2, using the updated helper's `--shutdown` to disconnect the PDU,
clear host IPv4 configuration, delete each modem's bearers and disable it.
After both laptop shutdown success markers, stop both iperf
server terminals, then each DU, RIC and CU in their own terminals with Ctrl+C.
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

Retain actual configuration hashes/startup records, subscriber public identities
and session shapes, CU CGI/F1AP mappings, xApp/RIC lifecycle and full DU-tagged
KPM blocks with UL-window correlation. Keep raw security-bearing core logs and
K/OPc outside Git. Full concurrent UL/KPM and repeated/UDP/guard/survivor/cold-start
acceptance remain pending.
