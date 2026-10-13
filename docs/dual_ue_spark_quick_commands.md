# Dual UE Spark Quick Commands — UL Only

Updated: 2026-10-13. Both intended SIMs have registered on their intended
cells and both private paths pinged successfully. UE2 single-DU UL passed at
receiver 15.5 Mbit/s / Retr 1 with 12 KPM smoke reports. UE1 UL with UE2 test
traffic idle passed at receiver 10.5 Mbit/s / Retr 0 / pipeline exit 0. See
[UE1 UL evidence](evidence/2026-10-13_du1_ul/manifest.json),
[UE2 UL evidence](evidence/2026-10-13_du2_ul/manifest.json) and
[dual IPv4 path evidence](evidence/2026-10-13_dual_ipv4_paths/manifest.json).

The latest Spark diagnostic discovered both DU IDs, subscribed twice and deleted
both subscriptions with exit 0, but received zero UE callback blocks. Actual
two-link KPM delivery and trustworthy concurrent UL results remain pending; see
[subscription-only evidence](evidence/2026-10-13_dual_kpm_subscriptions/manifest.json).
UL is the acceptance target; underflow count/growth remediation is deferred.
Wrong-cell attachment, lost SA/PDU, wrong IP paths, failed UL and missing UL
telemetry still keep their acceptance gates pending. See
[Plan 3](../plans/dual-ue-du-fr1-channels.md).

Run all commands in this file on Spark. Use Bash and separate foreground
terminals for CU, RIC, each DU, each iperf server and xApp. Modem/AT/routing/client
commands are in [Dual UE Laptop Quick Commands](dual_ue_laptop_quick_commands.md).
Resume at steps 6–7 in the current running session; steps 1–5 are for cold start.

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

## 5. Start DU2 first

**DU2 terminal:**

```bash
cd /home/nyu/ocudu
DU2_RUN=$(mktemp -d /tmp/falcon-du2-3600.XXXXXXXX)
printf 'DU2 run directory: %s\n' "$DU2_RUN"
set -o pipefail
sudo stdbuf -oL -eL build/apps/du_split_8/odu \
  -c configs/du2_b210_n78_20mhz.yml -c configs/du2_flexric.yml \
  log --filename "$DU2_RUN/du.log" 2>&1 | tee "$DU2_RUN/startup.log"
```

Require radio `328B021`, USB 3, PCI 2, carrier `640000` / 3600 MHz, SSB `639648`,
F1-C/E2AP completed, and `==== DU started ===`. RIC must show
`Node ID 411 ... ngran_gNB_DU ID 2` and accept KPM function ID 2.

For a cold-start isolated UE2 test, keep DU1 stopped and complete laptop steps
1–5 after starting its server below. This phase passed in the current session;
both DUs are running, so continue at steps 6–7 without restarting them.

## 6. Start both iperf servers and add DU1 after UE2 passes

Spark UE2 server terminal:

```bash
iperf3 -s -B 10.46.0.1 -p 5202
```

Require `Server listening on 5202`. Have the laptop complete UE2 identity/cell/PDU/
private ping and 60-second UL with DU2 only; use Spark step 7 for KPM.
This initial UE2 phase already passed in the current session.
After UE2 passes, start DU1 in its own terminal while retaining CU/RIC/DU2:

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
F1/E2 completed and RIC accepted DU ID 1. Retain actual CU NR CGI/F1AP evidence.
This DU1 startup also passed in the current session.

Spark UE1 server terminal:

```bash
iperf3 -s -B 10.45.0.1 -p 5201
```

Require `Server listening on 5201`. Both listeners must stay running for concurrent
UL; reuse existing server terminals rather than creating duplicate listeners.
The laptop selects/locks/connects UE1 and measures UE1 UL / DU2 test traffic idle
before the concurrent case. That UE1 UL phase already passed this session.

## 7. KPM subscriptions and actual two-link metric delivery

RIC must have registered `gnb=411 / DU ID 1` and `gnb=411 / DU ID 2`, accepting KPM
RAN function ID 2 for both. Keep both DUs and RIC running. Complete any existing
finite monitor before launching another. Start the 120-second capture first;
after both subscriptions succeed, run laptop step 6's concurrent clients.

### 7a. Stock single-DU smoke monitor

For the initial DU2-only UL test, use the installed finite monitor:

```bash
XAPP_RUN=$(mktemp -d /tmp/falcon-kpm-solo.XXXXXXXX)
set -o pipefail
stdbuf -oL -eL /usr/local/bin/flexric/xApp/c/xapp_oran_moni \
  -c /usr/local/etc/flexric/xapp_oran_sm.conf 2>&1 | tee "$XAPP_RUN/kpm.log"
XAPP_RC=$?
printf 'pipeline_exit=%d\n' "$XAPP_RC" | tee "$XAPP_RUN/exit.txt"
```

Require exit 0, actual UE reports, numeric `DRB.UEThpUl` / `RRU.PrbTotUl`, report
age, subscription/delete responses and normal stop. The stock callback prints
the common gNB ID without DU ID; use the diagnostic below for two-DU attribution.
DL values remain observations; report age is not application RTT.

### 7b. Build the DU-tagged diagnostic

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

### 7c. Capture while both UEs upload

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
Actual two-link KPM remains pending until overlapping traffic/capture evidence
is inspected.

## 8. Shutdown and retained evidence

Stop laptop clients and clean each recorded path using [laptop step 7](dual_ue_laptop_quick_commands.md#7-cleanup-and-retained-evidence).
Allow the finite xApp to delete subscriptions and stop naturally. Stop both iperf
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
