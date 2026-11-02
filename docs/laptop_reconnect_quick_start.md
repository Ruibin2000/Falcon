# Dual UE Laptop Reconnect — Quick Commands and Expected Results

Updated: 2026-11-02. Developer: Ruibin.

**Spark target:** DU1/DU2 statistics and KPM **100 ms**; CU identity **1 second**.

**Current Spark startup gains:** DU1 TX 70 / RX 35 dB; DU2 TX 60 / RX 10 dB,
following the actual OCUDU startup YAML after live tuning. DU2's values apply
to its modified 9250-MHz FR3 hardware path. See the
[Spark gain check](spark_quick_commands.md#5-start-du1-and-du2-in-separate-terminals-and-keep-both-running).

**Current radio profile:** DU1 uses 3660 MHz / 20 MHz / SSB `643680`;
DU2 uses a 3600-MHz logical n78 USRP interface, 40 MHz and SSB `638976`.
Its current Pi-Radio path has a 9250-MHz OTA center. The October 29 direct-radio
connections are historical; DU2 uses the modified FR3 path going forward. See the
[radio design and evidence scope](project_design_and_progress.md). Refresh the scripts
in section 2 before starting UE2: the earlier 20-MHz profile used SSB `639648`.
The modem lock and OCUDU/E2 cell information use the logical n78 frequency.

**Normal MPTCP operation:** complete sections 1–5, keep both UE watchers
running, then follow [section 7c](#7c-mptcp-operation-with-the-continuous-xapp)
and [Spark 7c](spark_quick_commands.md#7c-start-the-continuous-xapp-and-wait-for-mptcp-registration).
The continuous xApp waits for the formal MPTCP server to register and receive
matched KPM. There is no timed subscriber test in the normal startup flow.
Sections 6, 7 and 7a are optional standalone iperf/direct-TXT diagnostics.

[Full reference and troubleshooting](operations/reconnect_reference.md) ·
[Spark startup, sections 1–5](spark_quick_commands.md#1-check-radios-and-deploy-configuration-before-a-cold-start) ·
[Spark continuous xApp and MPTCP registration](spark_quick_commands.md#7c-start-the-continuous-xapp-and-wait-for-mptcp-registration)

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

**Cell-lock recovery, updated 2026-11-02:** both UE watchers retry a lock write
once with `CFUN=0`, then restore `CFUN=1`, when it returns CME 902 with a different
readback, or returns `OK` but readback remains disabled (`0`), and the selected
modem has no active PDU. A correct saved lock is
reused. An active PDU prevents this CFUN retry. The selected radio temporarily
goes offline during the retry; the script attempts to restore `CFUN=1` even if
the lock fails or Ctrl+C interrupts it. Lock readback is checked again after
functionality is restored. Registration, serving-cell, PDU and ping checks
must still pass before `SUCCESS`. This path has offline regression coverage;
physical recovery on the current firmware still requires a live test.

After a CFUN transition, Ctrl+C shutdown waits up to 30 seconds for a missing
target IMEI to reappear, then verifies the current modem/SIM before cleanup.
Ambiguous identities and wrong SIMs still stop cleanup immediately. A timeout
remains a cleanup failure. CME 905 still blocks registration; see the
[read-only firmware/lock diagnostic](operations/reconnect_reference.md#cme-905-during-cfun-recovery-and-modem-rediscovery).

If a manual AT session was left at `AT+CFUN=0`, restore `AT+CFUN=1` in that
modem's AT terminal, then exit minicom before starting its watcher. The watcher
must be able to verify the modem and SIM before it can make radio changes.
See [CME 902 details](operations/reconnect_reference.md#cme-902-after-a-du-gain-drop).

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
[AT port reference](operations/reconnect_reference.md#at-port-mapping).

## 4. Connect both UEs — Spark sections 1–5 already running

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
[section 7a's 120-second xApp capture](spark_quick_commands.md#7a-start-the-xapp-and-write-a-120-second-txt-capture).

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
[section 7a capture](spark_quick_commands.md#7a-start-the-xapp-and-write-a-120-second-txt-capture)
and compare `bindings.txt` with the current Laptop summary. Detailed analysis
commands are in the [development reference](reference/ue_identity_xapp.md#expanded-27-metric-capture-inspection).

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
stack-capture commands for [both DUs](spark_quick_commands.md#5a-spark-du1-terminal).
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
[section 7b's full 360-second xApp command](spark_quick_commands.md#7b-six-minute-reconnect-stability-with-alternating-and-concurrent-ul).

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
[full stability reference](operations/reconnect_reference.md#six-minute-reconnect-stability-test).
The traffic summary alone does not certify the xApp or the absence of brief
reconnect events between traffic snapshots.

## 7c. MPTCP operation with the continuous xApp

Keep the two watchers from section 4 running after both report `SUCCESS`.
Reuse healthy watchers and maintain one owner per UE. Confirm both current
addresses and routes using the same check as section 5:

```bash
python3 ~/falcon-ue-connect/run_dual_ul.py --check-only
```

This check starts no iperf traffic. Normal MPTCP operation does not require
Spark's optional iperf listeners or a scheduled 60/360-second traffic run.

On Spark, start the [continuous xApp service](spark_quick_commands.md#7c-start-the-continuous-xapp-and-wait-for-mptcp-registration),
then start or reconnect the integrated MPTCP server using its own launch
procedure. Wait for its `APP_REGISTER_RECEIVED` and `APP_REGISTERED` events
in the xApp terminal, followed by registration acknowledgement and fresh KPM
reception in the MPTCP application. The client uses TCP `127.0.0.1:8765`,
protocol version `2`, profile `du27_bound_v1` and its configured `app_id`.

| Laptop truth | Expected MPTCP association |
| --- | --- |
| UE1, DNN `internet`, current address in `10.45.0.0/16` | `report.ue_ipv4` matches the current UE1 source address |
| UE2, DNN `internet2`, current address in `10.46.0.0/16` | `report.ue_ipv4` matches the current UE2 source address |
| A UE reconnects and receives a new address | The application resolves the new address against its current path table |

Use current allocations from the check; do not substitute historical IPs or
Spark's `.1` endpoints. xApp sends full matched IDs + IP + 27 KPM reports,
nominally every 100 ms per active link. The MPTCP application consumes the
socket stream directly. Keep the UE watchers and xApp running throughout
MPTCP operation; no fixed test duration stops them. The server can disconnect
and register again independently of the UE watchers and RAN.

## 8. Stop after MPTCP and the xApp have finished

For a full testbed shutdown, finish MPTCP traffic and its KPM subscription,
then stop xApp normally on Spark and wait for its three E2 subscription delete
responses, following [Spark section 8](spark_quick_commands.md#8-shutdown-and-retained-evidence).
After that, shut down the two Laptop UE watchers below. For an optional
diagnostic run, finish its traffic and finite xApp first.

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
[Spark section 8](spark_quick_commands.md#8-shutdown-and-retained-evidence)
to stop the servers, DUs, CU, RIC and Core.
