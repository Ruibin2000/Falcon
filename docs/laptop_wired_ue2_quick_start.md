# Laptop Wired UE2 Quick Start

Updated: 2026-11-19. Start the wired controller using the
[Spark wired DU2 guide](spark_wired_du2_quick_start.md), then connect UE2 after
`[RUNNING]`. For manual startup in separate terminals, start Core, RIC, CU and
DU2 first and wait for `==== DU started ===`.

This guide operates UE2 only. The operator executes all commands manually.
The wired entry point reuses the same `reconnect_ue.py` / `connect_ue.py` engine,
identity checks, PDU/routing verification and Ctrl+C cleanup as the dual-UE and
UE1 watchers. It selects the wired 20-MHz SSB and label, verifies or restores the
cell lock at startup, then requests registration and establishes the PDU session.

## 1. Fixed Profile and Preparation

| Parameter | UE2 wired20 |
| --- | --- |
| Modem IMEI / SIM IMSI | `863305041980706` / `001010000000102` |
| PLMN / PCI / NCI | `00101` / `2` / `66C001` |
| Carrier / SSB / SCS | `640000` / **`639648`** / 30 kHz |
| Radio mode / band / bandwidth | NR SA / n78 / 20 MHz |
| APN / IPv4 pool | `internet2` / `10.46.0.0/16` |
| Spark destination / iperf port | `10.46.0.1` / `5202` |
| Spark TX / RX / digital backoff | **70 / 35 / 12 dB**; DU metrics every 100 ms |
| Laptop policy table | `152` |
| AT port | `/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0` |
| Watcher entry point | `~/falcon-ue2-wired20/reconnect_ue2_wired20.sh` |

Quectel ANT3 connects to common port 3 of the splitter, with no common
attenuator. The 50-dB DL branch connects to B210 RF A TX/RX; the 60-dB UL branch
connects to RF A RX2. The fixed Spark baseline is TX 70 / RX 35.

The operator accepted the DL measurements on 2026-11-19: PCI `2`, NCI `66C001`,
`C5GREG: 0,1`, and QENG RSRP **-99 dBm**, RSRQ **-11 dB**, SINR **24 dB**.
A subsequent snapshot was approximately -98 dBm / 24 dB. Preserve TX 70,
digital backoff 12 dB, the 50-dB DL branch, no common attenuator, and the existing
3600-MHz / 20-MHz / TDD settings during UL comparisons.

The selected RX-35 60-second UL run measured median SINR 23.6 dB and mean MAC
throughput 39.41 Mbps. The iperf receiver reported 37.4 Mbps and the sender
reported zero TCP retransmissions. These are observations from one run, not
configured SINR targets, proof of an optimal gain, or long-term stability results.

The wired Spark profile retains the native PUSCH power-control defaults; it does
not additionally enable closed-loop control or specify a SINR target. No extra
Laptop AT power setting is required. Observe actual UL SINR, CRC and throughput
on Spark while running the traffic in section 5.

Modem objects, bearer IDs, WWAN interface names and UE IPv4 addresses can change.
Rediscover them rather than assuming modem `/0`, interface `wwan0`, or a previous
address. The successful run used `10.46.0.5`; verify the address after reconnecting.

Install the prerequisites once:

```bash
sudo apt install modemmanager minicom iproute2 iputils-ping python3 iperf3
sudo systemctl enable --now ModemManager
```

Stop the old watcher for this UE and wait for cleanup before updating the five
files in the separate Laptop directory:

```bash
(
  set -euo pipefail
  mkdir -p ~/falcon-ue2-wired20
  ssh -T nyu@10.20.44.26 \
    'tar -C /home/nyu/Desktop/Falcon_repo/Falcon/scripts/dual_fr1 -czf - reconnect_ue2_wired20.sh reconnect_ue2_wired20.py reconnect_ue.py connect_ue.py reset_ue_network.py' |
    tar -xzf - -C ~/falcon-ue2-wired20
  ls -l ~/falcon-ue2-wired20/{reconnect_ue2_wired20.sh,reconnect_ue2_wired20.py,reconnect_ue.py,connect_ue.py,reset_ue_network.py}
  bash ~/falcon-ue2-wired20/reconnect_ue2_wired20.sh --help
)
```

`10.20.44.26` is the Spark management address in the existing guides; replace it
if it has changed. Require all five files and a successful help command. Use the
wired entry point rather than the 40-MHz OTA `reconnect_ue2.sh`.

Check the physical USB connection and current modem objects:

```bash
ls -l /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0
mmcli -L
```

The by-path name depends on the physical USB socket. After moving the cable,
verify ownership and IMEI, then pass the correct `--at-port /dev/serial/by-path/...`
to the watcher. Do not guess from a transient ttyUSB number.

## 2. Minicom Checks After Reset or Failed Cell Acquisition

Skip this section if the wired cell already connects correctly. Otherwise, stop
the UE2 watcher and wait for cleanup. Keep ModemManager running. Use minicom and
the watcher separately so they do not compete for the AT port.

```bash
sudo minicom -D /dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0 -b 115200
```

Query each command separately. IMEI and IMSI must match the UE2 identity above:

```text
AT
AT+CGSN
AT+CIMI
AT+CFUN?
```

After confirming identity, set and read back NR SA / n78:

```text
AT+QNWPREFCFG="mode_pref",NR5G
AT+QNWPREFCFG="mode_pref"
AT+QNWPREFCFG="nr5g_disable_mode",2
AT+QNWPREFCFG="nr5g_disable_mode"
AT+QNWPREFCFG="nr5g_band",78
AT+QNWPREFCFG="nr5g_band"
AT+QNWLOCK="common/5g"
AT+QENG="servingcell"
AT+C5GREG?
```

If `CFUN?` returns `0`, verify identity and that no watcher is running before
issuing `AT+CFUN=1` separately. Require `OK`, then query again. If CME 905 appears,
retain the raw response and stop repeated resets.

Normal watcher startup verifies the saved lock. It reuses a matching lock and
writes a missing or mismatched lock, then checks its readback. If a write is
rejected or returns `OK` while readback remains `0`, the shared recovery engine
may retry under `CFUN=0` only when its ownership and inactive-PDU guards permit.
It restores and verifies `CFUN=1` afterward.

The target is PLMN `00101`, PCI `2`, NCI `00066C001`, SSB `639648`, band `78`.
`NOCONN` in QENG means idle rather than an active RRC connection; check cell
identity and C5GREG as well. The expected home registration status is the second
C5GREG value `1`. `SEARCH` means no suitable serving cell has been acquired;
check the Spark DU and DL wiring first.

Startup enables the shared `--auto-cell-lock` path. When a write is needed, it
sends:

```text
AT+QNWLOCK="common/5g",2,639648,30,78
```

Require readback `+QNWLOCK: "common/5g",2,639648,30,78`. Firmware has previously
returned `OK` followed by disabled lock readback, and CFUN restoration has also
failed. These are startup failures; the watcher does not bypass them to start a
PDU session. SSB `638976` belongs to the older 40-MHz profile. A valid saved lock
must still be followed by registration, serving-cell and all nine access checks.

Exit minicom with **Ctrl+A, then X** before proceeding.

## 3. Start the Wired UE2 Watcher

Run this in a dedicated Laptop terminal and leave it open:

```bash
sudo bash ~/falcon-ue2-wired20/reconnect_ue2_wired20.sh \
  --auto-cell-lock --interval 3 --verbose 3 --registration-timeout 30
```

Require `startup cell-lock verification/restoration is on`, followed by
`Startup radio [OK]: cell lock verified`, then all nine checks:

1. Modem / SIM identity
2. Modem registration
3. Serving cell
4. PDU session / serving-cell recheck
5. WWAN / policy routing / Wi-Fi fallback block
6. Source-bound and ordinary routes
7. Source-bound ping
8. Ordinary ping
9. Final identity / cell / network verification

The final success markers are:

```text
PASS: UE2 / n78-wired20 connected
UE2 / n78-wired20 attempt N: SUCCESS
```

`--registration-timeout 30` supplies a per-attempt registration wait budget.
`--interval 3` controls the delay after each check or attempt; it does not change
Spark's **100-ms metrics**.

The entry point defaults to the complete command above. Explicit arguments can
override the interval, verbosity and wait budget. The shared engine verifies
modem/SIM and AT-port ownership, verifies or restores PCI `2` / SSB `639648`,
enables the modem as needed, requests PLMN `00101`, establishes the `internet2`
PDU, configures this role's host path and verifies connectivity. A matching saved
lock is reused. Later radio failures retain the shared cooldown/recovery logic.
Use `--verbose 2` for less output; healthy checks may then remain quiet. Run only
one UE2 watcher.

Retain the printed evidence directory, such as
`/tmp/falcon-ue2-reconnect-XXXXXXXX`. Spark automatic mode has already started the
xApp at `[RUNNING]`. In manual mode, return to Spark and start the
[xApp](spark_wired_du2_quick_start.md#7-manual-xapp-terminal-100-ms-and-27-metrics).

## 4. Current IP, Routes and Ping

Keep the watcher running and use another Laptop Bash terminal. This block reads
the current source address from the ordinary route and verifies that ordinary
and source-bound routes both use table 152 and the same interface. Stop traffic
preparation if the check fails, and repeat it after any PDU address change.

```bash
if UE2_IP=$(python3 - <<'PY'
import ipaddress
import json
import subprocess

def route(*extra):
    rows = json.loads(subprocess.check_output(
        ['ip', '-N', '-j', '-4', 'route', 'get', '10.46.0.1', *extra], text=True))
    assert len(rows) == 1, 'Expected one route'
    assert int(rows[0].get('table', -1)) == 152, 'Expected UE2 table 152'
    return rows[0]

ordinary = route()
source = str(ipaddress.IPv4Address(ordinary['prefsrc']))
assert ipaddress.IPv4Address(source) in ipaddress.IPv4Network('10.46.0.0/16')
bound = route('from', source)
assert bound['dev'] == ordinary['dev'], 'Ordinary/bound interfaces differ'
print(source)
PY
); then
  printf 'Current UE2 IP: %s\n' "$UE2_IP"
  ip -4 route get 10.46.0.1
  ip -4 route get 10.46.0.1 from "$UE2_IP"
  ping -I "$UE2_IP" -c 5 10.46.0.1
  ping -c 5 10.46.0.1
else
  unset UE2_IP
  printf 'STOP: UE2 route verification failed; restore all nine watcher checks first.\n'
fi
```

Both pings must succeed through UE2 WWAN / table 152. The destination
`10.46.0.1` must use the UE path. The watcher's independent fallback block remains
after cleanup to prevent management Wi-Fi from producing a false connectivity
pass when the UE is disconnected.

## 5. Recorded 60-Second UL Experiment and Optional DL Test

In another Spark terminal, start `iperf3 -s -B 10.46.0.1 -p 5202` and require
`Server listening`. Use the Laptop terminal that passed section 4, keep the
watcher running, and run one traffic direction at a time. Run standalone iperf
separately from the formal MPTCP workload.

The successful UL run, Laptop to Spark, used:

```bash
iperf3 -c 10.46.0.1 -p 5202 -B 10.46.0.5 -t 60 -i 1
```

The following block keeps those parameters, substitutes the verified current IP,
and saves text output and UTC timestamps. Run it in the section-4 terminal:

```bash
if [ -n "${UE2_IP:-}" ]; then
  UE2_TRAFFIC_RUN=$(mktemp -d /tmp/falcon-ue2-wired20-traffic.XXXXXXXX)
  printf 'Traffic logs: %s\n' "$UE2_TRAFFIC_RUN"
  printf '%s\n' "$UE2_IP" > "$UE2_TRAFFIC_RUN/ue2-ip.txt"
  date -u --iso-8601=seconds > "$UE2_TRAFFIC_RUN/ul-start.txt"
  iperf3 -c 10.46.0.1 -p 5202 -B "$UE2_IP" -t 60 -i 1 2>&1 |
    tee "$UE2_TRAFFIC_RUN/ul.log"
  UE2_UL_RC=${PIPESTATUS[0]}
  printf 'UL exit=%s\n' "$UE2_UL_RC" | tee "$UE2_TRAFFIC_RUN/ul-exit.txt"
  date -u --iso-8601=seconds > "$UE2_TRAFFIC_RUN/ul-end.txt"
  tail -n 6 "$UE2_TRAFFIC_RUN/ul.log"
else
  printf 'Repeat section 4 to obtain a verified current UE2_IP first.\n'
fi
```

Require exit code 0 and retain the sender/receiver summaries. The recorded
RX-35 result was:

```text
[  5]   0.00-60.00  sec   271 MBytes  37.8 Mbits/sec    0             sender
[  5]   0.00-60.11  sec   268 MBytes  37.4 Mbits/sec                  receiver
```

The corresponding Spark window was 2026-11-19 16:07:25-16:08:25 America/New_York
(21:07:25-21:08:25 UTC). DU median UL SINR was 23.6 dB, median RSRP was -25.6 dBFS,
CRC NOK was 10.59%, and the window contained two RF underflows and zero RF-late
messages. MAC throughput and application throughput are different measurements;
CRC errors and TCP retransmissions describe different layers.

Export the Spark evidence using
[section 8 of the Spark guide](spark_wired_du2_quick_start.md#8-recorded-ul-experiment-and-log-export).
Compare only the actual traffic window, excluding startup history. If the
watcher reconnects during traffic, verify the new address and record the two
sessions separately. The final raw export and summaries are retained in the
local archive `docs/experiments/evidence/2026-11-19_ue2_wired20_baseline/` on Spark;
see the [archive policy](experiments/README.md#local-archive-policy).

For a separate DL test, Spark to Laptop, recheck the section-4 route/address and
run in the same terminal:

```bash
if [ -n "${UE2_IP:-}" ] && [ -d "${UE2_TRAFFIC_RUN:-}" ]; then
  date -u --iso-8601=seconds > "$UE2_TRAFFIC_RUN/dl-start.txt"
  iperf3 -c 10.46.0.1 -p 5202 -B "$UE2_IP" -R -t 60 -i 1 2>&1 |
    tee "$UE2_TRAFFIC_RUN/dl.log"
  UE2_DL_RC=${PIPESTATUS[0]}
  printf 'DL exit=%s\n' "$UE2_DL_RC" | tee "$UE2_TRAFFIC_RUN/dl-exit.txt"
  date -u --iso-8601=seconds > "$UE2_TRAFFIC_RUN/dl-end.txt"
  tail -n 6 "$UE2_TRAFFIC_RUN/dl.log"
else
  printf 'Verify the current address and prepare the UL traffic directory first.\n'
fi
```

## 6. Current RSRP, SINR and Troubleshooting

Observe **UL** in the native Spark DU `t` table or xApp `PUSCH.SNR.dB` (actually
SINR) and `PUSCH.RSRP.dBFS`. Observe **DL** in Quectel's NR5G RSRP / RSRQ / SINR.
USRP RX gain changes UL reception; it does not directly raise UE DL RSRP.

If ModemManager supports extended signal queries, find the current object with
`mmcli -L`, enter its index/path, and verify IMEI `863305041980706` before using
the signal commands:

```bash
mmcli -L
read -r -p 'Current UE2 modem index or object path: ' UE2_MODEM
mmcli -m "$UE2_MODEM" -K
```

After verifying identity:

```bash
sudo mmcli -m "$UE2_MODEM" --signal-setup=3
watch -n 3 "mmcli -m '$UE2_MODEM' --signal-get"
```

An unsupported extended-signal query is not proof of RF failure. For serial
QENG queries, finish traffic, stop the watcher normally, then use minicom as in
section 2. Exit minicom before restarting the watcher.

| Symptom | Check |
| --- | --- |
| Wrong IMEI/IMSI or AT-port ownership failure | Verify the USB connection and actual modem; preserve identity checks |
| Registration failure or `SEARCH` | Check Spark DU, NR SA / n78, ANT3, the DL branch and SSB `639648` |
| Wrong serving cell | Check for an OTA entry point, stale lock or external operator cell |
| Registration passes but PDU fails | Check the `internet2` subscriber, SMF/UPF and `ogstun_2`; retain both sides' logs |
| CME 902/905 or saved lock still `0` | Retain raw AT responses and recovery records; mismatched readback cannot pass startup |
| Ping fails | Verify current bearer/IP, table 152 and both routes; preserve the fallback guard |

## 7. Stop and Retain Evidence

Finish application and iperf traffic first.

For **Spark automatic mode**, press Ctrl+C in the Laptop watcher terminal and
wait for successful cleanup, then enter `stop` or Ctrl+C in the Spark controller.
The controller cleans up xApp, DU2, CU, RIC and Core.

For **manual mode**, stop the Spark xApp first and wait for both E2 subscription
deletions, then press Ctrl+C in the Laptop watcher terminal.

In both modes, require:

```text
UE2 shutdown [OK]: bearers=0, state=disabled, role host path cleared
UE2 shutdown: SUCCESS
Stopped; evidence saved: /tmp/falcon-ue2-reconnect-XXXXXXXX
```

The watcher disconnects this role's PDU, clears its addresses/policy path and
disables UE2. The independent Wi-Fi fallback block remains. Exiting minicom with
Ctrl+A then X is separate from watcher cleanup.

In manual mode, stop DU2/CU/RIC using the Spark guide afterward, preserving shared
services still in use. Automatic mode uses the controller's existing Core
management and shutdown behavior; stop it through the controller.

Retain the watcher directory (`run.log`, `attempts.jsonl`, and `summary.json`
produced at exit) and traffic directory alongside the Spark DU/CU/xApp evidence.
Nine PASS checks establish access; they do not establish a specified SINR,
throughput or long-term stability. Copy required `/tmp` evidence to persistent
storage before rebooting, following the
[local archive policy](experiments/README.md#local-archive-policy).
