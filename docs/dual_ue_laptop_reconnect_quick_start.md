# Dual UE Laptop Reconnect — Quick Commands and Expected Results

Updated: 2026-10-26. Developer: Ruibin.

**Spark target:** DU1/DU2 statistics and KPM **100 ms**; CU identity **1 second**.

**Current application subscription tests:** use
[7c](#7c-live-app-subscription-test-with-one-dummy) for the 120-second test or
[7d](#7d-six-minute-alternating-ul-with-one-subscribed-dummy) for the six-minute
alternating test. Their numbers match the Spark handbook. Both use one dummy
on Spark, while Laptop runs the two UE watchers and traffic. Sections 6–7a retain
the earlier direct xApp-to-TXT diagnostic workflow.

[Full reference and troubleshooting](runbooks/dual_ue_laptop_reconnect_reference.md) ·
[Spark startup and servers, sections 1–6](dual_ue_spark_quick_commands.md#1-check-radios-and-deploy-configuration-before-a-cold-start) ·
[Spark xApp capture and inspection, section 7](dual_ue_spark_quick_commands.md#7-start-the-dual-ue-identityrf-xapp-and-save-txt-results)

## 1. Laptop dependencies — once

```bash
sudo apt install modemmanager iproute2 iputils-ping python3 iperf3
sudo systemctl enable --now ModemManager
```

**Expected:** all packages installed; ModemManager active.

## 2. Copy or update scripts — Laptop terminal, watchers stopped

```bash
(
  set -euo pipefail
  mkdir -p ~/falcon-ue-connect
  ssh -T nyu@10.20.44.26 \
    'tar -C /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1 -czf - reconnect_ue1.sh reconnect_ue2.sh reconnect_ue.py connect_ue.py reset_ue_network.py run_dual_ul.py run_dual_stability.py' |
    tar -xzf - -C ~/falcon-ue-connect
  ls -l ~/falcon-ue-connect/{reconnect_ue1.sh,reconnect_ue2.sh,reconnect_ue.py,connect_ue.py,reset_ue_network.py,run_dual_ul.py,run_dual_stability.py}
)
```

**Expected:** seven files listed; one SSH login; no intermediate archive file.

## 3. Check USB wiring — Laptop terminal

```bash
grep '^UE_AT_PORT=' ~/falcon-ue-connect/reconnect_ue{1,2}.sh
ls -l /dev/serial/by-path/pci-0000:00:14.0-usb-0:{4,3}:1.2-port0
```

**Expected:** UE1 uses `usb-0:4:1.2-port0`; UE2 uses
`usb-0:3:1.2-port0`; both resolve to serial devices. Connect the modems to
their assigned sockets and close minicom. The watchers verify USB ownership
and IMEI/IMSI; a listing alone does not prove modem identity. For swapped
cables or a port-ownership error, use the
[AT port reference](runbooks/dual_ue_laptop_reconnect_reference.md#at-port-mapping).

## 4. Connect both UEs — Spark sections 1–6 already running

**Laptop terminal 1 — UE1 / FR1:**

```bash
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --interval 3 --verbose 2
```

**Expected:** all nine connection steps pass, followed by:

```text
PASS: UE1 / FR1 connected
UE1 / FR1 attempt N: SUCCESS
```

**Laptop terminal 2 — UE2 / FR3:**

```bash
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --interval 3 --verbose 2
```

**Expected:** all nine connection steps pass, followed by:

```text
PASS: UE2 / FR3 connected
UE2 / FR3 attempt N: SUCCESS
```

**Expected while waiting:** both terminals remain running; healthy checks are
silent at level 2. Keep them open throughout the capture. `N` is the actual
attempt number; continue only after both UEs report `SUCCESS`.

## 5. Check both current IPs and routes — Laptop terminal 3

```bash
python3 ~/falcon-ue-connect/run_dual_ul.py --check-only
```

**Expected:** two current role summaries and:

```text
Both current bearer/host routes checked; no iperf traffic started
```

| Role | Current IP | Spark destination | Route table |
| --- | --- | --- | --- |
| UE1 / FR1 | Discovered in `10.45.0.0/16` | `10.45.0.1:5201` | `151` |
| UE2 / FR3 | Discovered in `10.46.0.0/16` | `10.46.0.1:5202` | `152` |

## 6. Start Spark section 7a, then upload for 60 seconds

**Spark terminal:** run
[section 7a's 120-second xApp capture](dual_ue_spark_quick_commands.md#7a-start-the-xapp-and-write-a-120-second-txt-capture).

**Expected before starting traffic:** three E2 nodes, three successful
subscriptions, and `identity collector: 3 KPM subscriptions, duration=120`.

**Laptop terminal 3 — immediately after subscriptions are ready:**

```bash
python3 ~/falcon-ue-connect/run_dual_ul.py --seconds 60
```

**Expected:** two concurrent Laptop → Spark TCP uploads; a printed
`/tmp/falcon-dual-ul-*` evidence directory; receiver summaries for both roles;
`UE1 exit=0`, `UE2 exit=0`, and `STATUS: completed`.

## 7. Inspect results — keep both watchers running

**Laptop terminal 3 — paste the directory printed by the upload command:**

```bash
read -r -p 'Paste the current Laptop upload directory: ' LAPTOP_UL_RUN
cat "$LAPTOP_UL_RUN/summary.json"
tail -n 12 "$LAPTOP_UL_RUN/ue1.log" "$LAPTOP_UL_RUN/ue2.log"
```

**Expected:** `status` is `completed`; both links have `exit_code: 0`; current
IP, IMSI and APN are recorded for each role. Retain `summary.json` and both logs.

**Spark terminal:** after the 120-second capture exits, retain the
[section 7a capture](dual_ue_spark_quick_commands.md#7a-start-the-xapp-and-write-a-120-second-txt-capture)
and compare `bindings.txt` with the current Laptop summary. Detailed analysis
commands are in the [development reference](development/ue_identity_xapp.md#expanded-27-metric-capture-inspection).

| Expected Spark result | UE1 / FR1 | UE2 / FR3 |
| --- | --- | --- |
| Repeated matched records | `DU_ID=1` | `DU_ID=2` |
| SUPI | `imsi-001010000000101` | `imsi-001010000000102` |
| DNN | `internet` | `internet2` |
| UE IPv4 | Matches current Laptop UE1 summary | Matches current Laptop UE2 summary |
| KPM | 27 raw measurements from Spark's expanded profile, including `PUSCH.RSRP.dBFS` and `PUSCH.SNR.dB` | Same 27 measurements |
| DU cadence | `granularity_ms=100`, about 10 reports/s | `granularity_ms=100`, about 10 reports/s |
| RF during UL | REAL samples; periods without usable PUSCH can be `no_value` | Same |

**Expected capture completion:** xApp exit 0, three subscription delete
responses, and no Core/input errors or ingress loss. Retain Spark's
`bindings.txt`, `rows.ndjson`, `inputs.ndjson`, `xapp.log`,
configuration snapshots and `exit.txt`, with the Laptop evidence. Copy both
printed capture directories to persistent experiment storage before reboot.
CU identity reports remain at 1000 ms and Core polling at 1 second. Laptop
watcher commands, their `--interval 3`, and the 60-second upload stay the same.

## 7a. Six-minute stability test — both reconnect watchers stay running

**Spark preparation:** for this diagnostic trial, select the optional temporary
stack-capture commands for [both DUs](dual_ue_spark_quick_commands.md#5a-spark-du1-terminal).
Keep both DU debug directories with the Spark capture; the Laptop commands
below are unchanged.

**Laptop terminal 3 — copy/update the traffic helpers after previous traffic/capture has finished:**

```bash
(
  set -euo pipefail
  mkdir -p ~/falcon-ue-connect
  ssh -T nyu@10.20.44.26 \
    'tar -C /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1 -czf - run_dual_ul.py run_dual_stability.py' |
    tar -xzf - -C ~/falcon-ue-connect
  python3 ~/falcon-ue-connect/run_dual_stability.py
)
```

**Expected:** both current UE addresses, then `READY`. Leave this prompt open.
This two-file transfer uses one SSH login and creates no intermediate archive.
Both reconnect watchers from section 4 stay running; only the traffic helpers
are updated. Keep each watcher's printed evidence directory. Do not start
another watcher for a UE that already has one running.

**Spark terminal:** start
[section 7b's full 360-second xApp command](dual_ue_spark_quick_commands.md#7b-six-minute-reconnect-stability-with-alternating-and-concurrent-ul).

**Expected:** three subscriptions and
`identity collector: 3 KPM subscriptions, duration=360`.

**Laptop terminal 3 — within ten seconds of subscriptions:**

```text
START
```

| Phase | Duration | iperf upload |
| --- | --- | --- |
| 1 | 50 s | FR1 |
| 2 | 50 s | FR3 |
| 3 | 50 s | FR1 + FR3 |
| 4 | 50 s | FR1 |
| 5 | 50 s | FR3 |
| 6 | 50 s | FR1 + FR3 |

**Expected:** six completed phases, eight successful receivers,
`STATUS: completed`, and a `/tmp/falcon-dual-stability-*` evidence directory.
Watchers keep checking/recovering; do not stop them or alter gains.

**Laptop terminal 3 — paste the printed traffic directory:**

```bash
read -r -p 'Paste the Laptop stability directory: ' LAPTOP_STABILITY_RUN
cat "$LAPTOP_STABILITY_RUN/summary.json"
```

**Expected:** `status: completed`, six phases, no allocation changes and
all eight client exits 0. Keep `events.ndjson`, `truth.json`, the eight client
JSON files, and both watchers' evidence directories. Let the Spark xApp finish
its full 360 seconds and require exit 0. Interpret reconnect events, identity
continuity, 27 metrics, cadence, gaps and radio warnings with the
[full stability reference](runbooks/dual_ue_laptop_reconnect_reference.md#six-minute-reconnect-stability-test).
The traffic summary alone does not certify the xApp or the absence of brief
reconnect events between traffic snapshots.

## 7c. Live app subscription test with one dummy

Pair with [Spark 7c](dual_ue_spark_quick_commands.md#7c-live-app-subscription-test-with-one-dummy).
The Spark dummy receives for 120 seconds; Laptop uploads concurrently for 60 seconds.

Keep the existing UE1 and UE2 watchers running after both report `SUCCESS`.
If they are not running, start each in its own Laptop terminal after Spark
sections 1–6 are ready:

**Laptop terminal 1 — UE1:**

```bash
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --interval 3 --verbose 2
```

**Laptop terminal 2 — UE2:**

```bash
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --interval 3 --verbose 2
```

Reuse healthy existing watchers; keep one owner per UE. Keep both Spark iperf
servers listening at `10.45.0.1:5201` and `10.46.0.1:5202`.

**Laptop terminal 3 — update the two traffic helpers:**

```bash
(
  set -euo pipefail
  mkdir -p ~/falcon-ue-connect
  ssh -T nyu@10.20.44.26 \
    'tar -C /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1 -czf - run_dual_ul.py run_dual_stability.py' |
    tar -xzf - -C ~/falcon-ue-connect
)
```

Check both current UE IPs and routes:

```bash
python3 ~/falcon-ue-connect/run_dual_ul.py --check-only
```

Require both role checks to pass. Start Spark 7c's xApp and single dummy, then
wait for its three E2 subscriptions and `APP_REGISTERED` for `dual-ue-dummy`.
Immediately run the upload in Laptop terminal 3:

```bash
python3 ~/falcon-ue-connect/run_dual_ul.py --seconds 60
```

Expected: both client exits 0, `STATUS: completed` and a printed
`/tmp/falcon-dual-ul-*` directory. Keep that directory and both watcher logs.
Let the Spark dummy finish 120 seconds and unregister; keep the watchers running
if continuing with the six-minute test.

## 7d. Six-minute alternating UL with one subscribed dummy

Pair with [Spark 7d](dual_ue_spark_quick_commands.md#7d-six-minute-alternating-ul-with-one-subscribed-dummy).
Finish previous iperf clients before preparing this run. Spark's single dummy
receives both links for 360 seconds; the six traffic phases each last 50 seconds.

Keep the existing UE1 and UE2 watchers running after both report `SUCCESS`.
If they are not running, start each in its own Laptop terminal after Spark
sections 1–6 are ready:

**Laptop terminal 1 — UE1:**

```bash
sudo bash ~/falcon-ue-connect/reconnect_ue1.sh --interval 3 --verbose 2
```

**Laptop terminal 2 — UE2:**

```bash
sudo bash ~/falcon-ue-connect/reconnect_ue2.sh --interval 3 --verbose 2
```

Reuse healthy existing watchers; keep one owner per UE. Keep both Spark iperf
servers listening at `10.45.0.1:5201` and `10.46.0.1:5202`.

**Laptop terminal 3 — update the traffic helpers and wait at READY:**

```bash
(
  set -euo pipefail
  mkdir -p ~/falcon-ue-connect
  ssh -T nyu@10.20.44.26 \
    'tar -C /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1 -czf - run_dual_ul.py run_dual_stability.py' |
    tar -xzf - -C ~/falcon-ue-connect
  python3 ~/falcon-ue-connect/run_dual_stability.py
)
```

Require both current role summaries followed by `READY`. Leave this prompt
open, then start Spark 7d's fresh xApp service and its single 360-second dummy.
Within **10 seconds of `APP_REGISTERED`** in the Spark xApp terminal, enter this
at the Laptop traffic prompt:

```text
START
```

| Phase | Duration | iperf upload |
| --- | --- | --- |
| 1 | 50 s | UE1 / FR1 |
| 2 | 50 s | UE2 / FR3 |
| 3 | 50 s | UE1 + UE2 |
| 4 | 50 s | UE1 / FR1 |
| 5 | 50 s | UE2 / FR3 |
| 6 | 50 s | UE1 + UE2 |

Keep both watchers running and gains fixed. The 300 seconds of scheduled traffic
plus bounded path checks fit inside the 360-second dummy window when started
on time. The xApp itself remains continuous (`duration=0`).

Expected: six completed phases, eight successful iperf receivers, all client
exits 0, no allocation changes, `STATUS: completed` and a printed
`/tmp/falcon-dual-stability-*` directory. Retain `summary.json`, `events.ndjson`,
`truth.json`, all eight `phaseN-ueM.json` files and both watcher directories.
Let the Spark dummy finish all 360 seconds and unregister, then stop the xApp
normally before following section 8 if ending the testbed.

## 8. Stop after iperf and the xApp have finished

**Laptop terminal 1:** press Ctrl+C and wait for:

```text
UE1 shutdown [OK]: bearers=0, state=disabled, role host path cleared
UE1 shutdown: SUCCESS
```

**Laptop terminal 2:** press Ctrl+C and wait for:

```text
UE2 shutdown [OK]: bearers=0, state=disabled, role host path cleared
UE2 shutdown: SUCCESS
```

**Expected:** both UEs are shut down; management Wi-Fi remains available;
the experiment destinations remain blocked from Wi-Fi fallback. Then follow
[Spark section 8](dual_ue_spark_quick_commands.md#8-shutdown-and-retained-evidence)
to stop the servers, DUs, CU, RIC and Core.
