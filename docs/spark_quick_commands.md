# Spark Quick Commands

Network update, 2026-10-23: the installed Spark uses `ogstun_1 / 10.45.0.1`
for UE1 and `ogstun_2 / 10.46.0.1` for UE2. The checks below use UE1's current
interface. See the [TUN split and script archive](dual_ue_tun_split.md) and
[dual-UE Spark commands](dual_ue_spark_quick_commands.md) for both paths.

Updated: 2026-10-23. Use this guide on the installed Spark testbed. For a new host, see [Software and Drivers](software_installation_and_drivers.md); for detailed configuration, see the [Full Reproduction Runbook](full_reproduction_runbook.md). UE commands are in [UE Laptop Quick Commands](ue_laptop_quick_commands.md). Use Bash, run one step at a time, and stop at any `FAIL` result.

For the 2026-10-13 two-DU/two-modem workflow and current UL-only scope, use
[Dual UE Spark quick commands](dual_ue_spark_quick_commands.md), including the supplied DU2 config,
its verified SSB, and separate laptop source-policy routes.

Verified on 2026-10-07: **DU E2 Setup, all five actual UE KPM measurements, the repaired report-time display, normal subscription deletion, and successful xApp exit**. Earlier UE ID `2` had `report_age_us` values of **499–717 µs**; the latest repeat with UE ID `7` had **591–796 µs**. These are historical 3750-MHz results. The 2026-10-05 UE application traffic / TCP result used TX **80** / RX **40**. Read current gains from the actual configuration file in step 1; the 2026-10-12 inspection found TX **70** / RX **35**. Neither snapshot establishes current runtime status.

This procedure uses the complete [DU1 3660-MHz configuration](../configs/ocudu/dual_fr1/du1_b210_n78_3660mhz.yml), including radio, cell, F1, E2/KPM, and metrics settings, to migrate **one UE / one DU to 3660 MHz**, following [Plan 3](../plans/dual-ue-du-fr1-channels.md). The 2026-10-12 session verified new-carrier operation, IPv4 application traffic, and five-metric KPM reception. The current scope is **uplink only**: TCP receiver 17.0 Mbit/s over 30.24 seconds, sender Retr 0, ping 5/5 with 0% loss, and 12 KPM reports for UE F1AP ID 5. **RF stability remains pending**: 117 underflows were observed by 11:39:44 EDT. See the [daily log](../dev_logs/2026-10-12_ruibin.md) and [evidence manifest](evidence/2026-10-12_du1_3660mhz/manifest.json). Before RF startup, use the operating conditions and authorization covering the full 3650–3670 MHz channel recorded for that plan. The new file copies the actual base gains; select and record the actual gain/attenuation for this setup before transmission. The historical SSB lock `649632` must be replaced by the value from the new DU startup output.

Historical verified versions: OCUDU `050a2bb`; FlexRIC `73650812`, build directory `build-ocudu`, GCC 13.3 / Debug / `E2AP_V3` / `KPM_V3_00` / `NONE_XAPP` / `XAPP_MULTILANGUAGE=OFF`.

Run checks in a diagnostics terminal. CU, FlexRIC, DU, and iperf each need their own foreground terminal. Use the same xApp Bash terminal for steps 6 and 7; shell variables are not shared between terminals.

## 0 Check the SIM and subscriber plan

The new Open Cells cards OC011830 / IMSI `001010000000101` and OC011831 / IMSI `001010000000102` are provisioned, Milenage-authenticated, and verified as ready in Quectel modems. The 2026-10-12 excerpts did not retain the active IMSI. Both new IMSIs subsequently registered on their intended DUs on 2026-10-13, with separate IPv4/private-ping and role UL functionality checkpoints; see the current dual-UE booklets. The earlier baseline IMSI `001010000000001` and its single-DU/KPM results remain separate.

Before using either new card, prepare its own matching core subscriber from protected `~/sim_du1_credentials.txt` or `~/sim_du2_credentials.txt`, SST 1 and IPv4 type 1. The migrated deployment uses UE1 `internet` and UE2 `internet2`; use the paired dual-UE booklets for that topology. Keep K/OPc private. The programming tool's recommended SQN reference `96` requires verification of the installed core's representation/current state; do not blindly insert or reset decimal 96. See [SIM assignments](sim_provisioning_and_dual_ue.md#sim-assignments) and [Open5GS preparation](sim_provisioning_and_dual_ue.md#prepare-open5gs-subscribers).

These launch commands cover **DU1 only**. The supplied DU2 config, actual B210 `328B021`, PCI 2 / SSB 639648, and distinct DU/network identities are covered by [Dual UE Spark quick commands](dual_ue_spark_quick_commands.md). IMSI does not automatically bind a UE to a DU; verify serving-cell readback. Both registered WWAN/IP paths have now passed private ping; concurrent UL/KPM acceptance and MPTCP remain pending; see [dual-UE validation](sim_provisioning_and_dual_ue.md#validate-two-ue-paths).

## 1 Check before startup

Run in the Spark diagnostics terminal. **Run UHD checks only while DU is stopped.** If an earlier DU/CU experiment is still running, follow the shutdown steps first.

```bash
if pgrep -x odu >/dev/null; then
  printf 'FAIL: DU is running; stop it before probing B210\n'
else
  lsusb -t
  sudo uhd_find_devices
fi
```

Confirm `5000M` in the USB tree and match the discovered B210 serial to `ru_sdr.device_args` printed below.

Falcon keeps the maintained configuration copy. Deploy it into OCUDU's `configs/` directory, then read the deployed file used to start DU1. Repeat this copy after editing the Falcon configuration:

```bash
cp /home/nyu/Desktop/Falcon_repo/Falcon/configs/ocudu/dual_fr1/du1_b210_n78_3660mhz.yml \
  /home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml
cat /home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml
```

Use the printed radio serial, gains, sample rate, and cell values as the file snapshot for this run. The new file sets ARFCN **644000** / **3660 MHz**, n78, 20 MHz, and SCS 30 kHz. The original 3750-MHz base and E2 files remain available as historical references. SSB is derived by OCUDU and is read separately in step 5.

Check that the installed DU binary accepts this configuration file without opening the radio:

```bash
/home/nyu/ocudu/build/apps/du_split_8/odu --dryrun \
  -c /home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml
```

Require exit status 0. This binary's dry run checks parsing/autoderivation and exits before full runtime validation; successful parsing does not establish RF operation or UE acceptance.

## 2 Restore performance settings after reboot

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

## 3 Start MongoDB and the core

Preserve the existing `open5gs-mongo` container and data volume. The baseline subscriber `001010000000001` should have SST 1, session `internet`, and type 1; see the [subscriber check](full_reproduction_runbook.md#5-start-mongodb-and-verify-the-subscriber). When using the new cards, run the separate nonsecret [two-subscriber preflight](full_reproduction_runbook.md#5a-prepare-the-two-provisioned-open-cells-subscribers) after MongoDB is ready. That check is a reproduction procedure and cannot prove K/OPc or SQN correctness.

```bash
sudo docker start open5gs-mongo >/dev/null &&
sudo docker exec open5gs-mongo mongosh --quiet --eval '
const r = db.adminCommand({ping: 1});
if (r.ok !== 1) { print("MongoDB: FAIL"); quit(1); }
print("MongoDB: OK");
'
```

On this dedicated Spark, stop the installed LTE/optional services first. Omit absent units on another host:

```bash
sudo systemctl stop open5gs-mmed open5gs-hssd open5gs-pcrfd open5gs-sgwcd open5gs-sgwud
sudo systemctl stop open5gs-bsfd open5gs-seppd
```

Start the ten SA units sequentially, then check each one and list only failures. A single `is-active --quiet` call with multiple units cannot prove that all are active.

```bash
CORE_UNITS=(open5gs-nrfd open5gs-scpd open5gs-udrd open5gs-udmd open5gs-ausfd open5gs-pcfd open5gs-nssfd open5gs-upfd open5gs-smfd open5gs-amfd)
for unit in "${CORE_UNITS[@]}"; do
  if ! sudo systemctl start "$unit"; then
    printf 'FAIL: Cannot start %s\n' "$unit"
    break
  fi
done
active=0
for unit in "${CORE_UNITS[@]}"; do
  if systemctl is-active --quiet "$unit"; then
    active=$((active + 1))
  else
    printf 'FAIL: %s (%s)\n' "$unit" "$(systemctl is-active "$unit")"
  fi
done
printf '5GC active: %d/10\n' "$active"
```

Check UE1's existing `ogstun_1` for its UP flag, MTU 1400, address, and private route:

```bash
if ip -o link show dev ogstun_1 | awk '/(<|,)UP(,|>)/ && / mtu 1400 / {ok=1} END {exit !ok}' &&
   ip -o -4 addr show dev ogstun_1 | awk '$4 == "10.45.0.1/16" {ok=1} END {exit !ok}' &&
   ip -4 route show 10.45.0.0/16 | awk '/^10\.45\.0\.0\/16 .*dev ogstun_1( |$)/ {ok=1} END {exit !ok}'; then
  printf 'ogstun_1: OK (UP, MTU 1400, 10.45.0.1/16, route)\n'
else
  printf 'ogstun_1: FAIL; check networkd and the 99-open5gs configuration\n'
fi
```

## 4 Start CU and FlexRIC in foreground terminals

**CU terminal:**

```bash
cd /home/nyu/ocudu
sudo build/apps/cu/ocu -c configs/cu.yml
```

Confirm N2 `completed` and `==== CU started ===`; keep CU running. Start FlexRIC in its own terminal and save the current log:

```bash
set -o pipefail
stdbuf -oL -eL /usr/local/bin/flexric/ric/nearRT-RIC -c /usr/local/etc/flexric/ric.conf 2>&1 |
  tee /tmp/flexric-ric.log
```

## 5 Start DU with E2 enabled

The deployed `configs/du1_b210_n78_3660mhz.yml` already enables DU1 E2/KPM and metrics. Run in the **DU terminal**; this starts B210 RF transmission at the migrated carrier. Load this one configuration file. The `log --filename` argument directs the DU log to this run's directory:

```bash
cd /home/nyu/ocudu
set -o pipefail
DU1_RUN=$(mktemp -d /tmp/falcon-du1-3660.XXXXXXXX)
printf 'DU1 run directory: %s\n' "$DU1_RUN"
sudo stdbuf -oL -eL build/apps/du_split_8/odu \
  -c configs/du1_b210_n78_3660mhz.yml \
  log --filename "$DU1_RUN/du.log" 2>&1 | tee "$DU1_RUN/startup.log"
```

Confirm the startup cell line shows `dl_arfcn=644000 (n78)` and `dl_freq=3660 MHz`. The operator-provided 2026-10-12 startup summary recorded **PCI 1 / SSB 643680 / SCS 30 kHz**. The matching lock is now written directly in [UE step 2](ue_laptop_quick_commands.md#2-configure-nr-sa-and-lock-the-private-cell):

```text
AT+QNWLOCK="common/5g",1,643680,30,78
```

For unchanged cell settings and derivation logic, this SSB stays the same across restarts. Compare the recorded tuple with the current startup line; recheck it after carrier, band, bandwidth, SCS, SSB/CORESET, or OCUDU version changes. Then verify the UE's actual serving cell. Do not substitute the carrier ARFCN or calculate SSB by subtracting the historical offset.

The following **optional helper** reads the current startup line and generates the lock command. Use it if the SSB differs from the recorded value or when checking a changed configuration at this carrier. In the **diagnostics terminal**, paste the run directory printed by this launch:

```bash
read -r -p 'DU1 run directory printed by this launch: ' DU1_RUN
python3 - "$DU1_RUN/startup.log" <<'PY'
import re
import sys

with open(sys.argv[1]) as source:
    text = source.read()
cells = re.findall(
    r"Cell pci=(\d+),[^\n]*dl_arfcn=(\d+) \(n(\d+)\), "
    r"dl_freq=([\d.]+) MHz, dl_ssb_arfcn=(\d+)", text)
if len(cells) != 1:
    sys.exit("FAIL: expected exactly one startup cell; inspect this run's log")
pci, carrier, band, freq, ssb = cells[0]
if (carrier, band, float(freq)) != ("644000", "78", 3660.0):
    sys.exit("FAIL: startup carrier differs from the 3660-MHz configuration")
print(f"Carrier={carrier} / {freq} MHz; PCI={pci}; SSB={ssb}; SCS=30 kHz")
print(f'AT+QNWLOCK="common/5g",{pci},{ssb},30,{band}')
PY
```

Use the command matching the current startup in [UE step 2](ue_laptop_quick_commands.md#2-configure-nr-sa-and-lock-the-private-cell). Require `OK`, read back the lock, then verify the actual serving cell and SA registration. The recorded SSB establishes the DU startup tuple. The 2026-10-12 ping, TCP uplink, CU/DU UE context, and KPM excerpts establish functional operation; sustained RF stability and the run's subscriber identity record remain pending. `/tmp` logs are temporary; retain this run's configs, hashes, and traffic/KPM evidence before reboot or cleanup.

Confirm F1-C / E2AP `completed` and `==== DU started ===` for this DU1 baseline. A future second DU requires its own reviewed configuration and per-DU evidence; the summary below proves only the current single-DU connections. FlexRIC should receive this DU's `E2 SETUP-REQUEST` and accept KPM ID `2`. In the diagnostics terminal, check the summary of the three SCTP connections:

```bash
sudo ss -H -an -A sctp | awk '
  /ESTAB/ && /:38412([[:space:]]|$)/ {n2=1}
  /ESTAB/ && /:38472([[:space:]]|$)/ {f1=1}
  /ESTAB/ && /:36421([[:space:]]|$)/ {e2=1}
  END {
    printf "SCTP: N2=%s F1=%s E2=%s\n", n2 ? "OK" : "FAIL", f1 ? "OK" : "FAIL", e2 ? "OK" : "FAIL"
    exit !(n2 && f1 && e2)
  }'
if [ ! -f /tmp/flexric-ric.log ]; then
  printf 'RIC log was not saved; confirm acceptance of KPM ID 2 in the running RIC terminal.\n'
elif grep -q 'Accepting RAN function ID 2 with def = ORAN-E2SM-KPM' /tmp/flexric-ric.log; then
  printf 'RIC accepted DU KPM: OK\n'
else
  printf 'RIC accepted DU KPM: FAIL; inspect the current FlexRIC log\n'
fi
```

Step 4 creates `/tmp/flexric-ric.log` through `tee`. An earlier direct RIC launch did not create this file. Inspect the running RIC terminal instead; saving a log does not require restarting the connection.

## 6 Verify the KPM subscription

**After this DU is accepted, run the entire block below in the Spark xApp terminal.** The example collects for about 10 seconds, then deletes the subscription and exits. Full output goes into a temporary log; a normal run prints one summary line. `KPM_LOG` exists only in this Bash terminal, so run the step 7 log commands here too. Earlier direct xApp launches without output redirection did not create this log file.

```bash
KPM_LOG=$(mktemp /tmp/flexric-kpm.XXXXXX.log)
/usr/local/bin/flexric/xApp/c/xapp_oran_moni \
  -c /usr/local/etc/flexric/xapp_oran_sm.conf >"$KPM_LOG" 2>&1
KPM_EXIT=$?
if [ "$KPM_EXIT" -eq 0 ] &&
   grep -q 'Successfully subscribed to RAN_FUNC_ID 2' "$KPM_LOG" &&
   grep -q 'E42 SUBSCRIPTION DELETE RESPONSE rx' "$KPM_LOG" &&
   grep -q 'Test xApp run SUCCESSFULLY' "$KPM_LOG"; then
  printf 'KPM: OK (subscription, deletion, exit); log=%s\n' "$KPM_LOG"
else
  printf 'KPM: FAIL (exit=%s); log=%s\n' "$KPM_EXIT" "$KPM_LOG"
  tail -n 30 "$KPM_LOG"
fi
```

Subscription can succeed without UE measurements. The `OK` result above confirms the subscription lifecycle, not UE KPM reception.

## 7 Validate UE traffic and KPM reports

Historical runs received all five DU measurements for UE IDs `14`, `2`, and `7`. At 3660 MHz on 2026-10-12, the accepted functional run received **12 complete reports for UE F1AP ID 5**, with RLC UL throughput 15.634–22.830 Mbit/s and UL PRB usage 86–88%. The operator's 30-second TCP uplink reported sender 17.7 Mbit/s / Retr 0 and receiver 17.0 Mbit/s. The procedure below repeats this uplink check; exact wall-clock alignment of the retained TCP and KPM windows was not recorded.

After UE registration, an IPv4 bearer, WWAN configuration, and ping succeed, start the server in the Spark **iperf terminal**:

```bash
iperf3 -s -B 10.45.0.1
```

After the UE laptop starts its 30-second TCP transfer, immediately run the entire step 6 block in the Spark **xApp terminal** so the roughly 10-second collection window overlaps UE traffic. After xApp exits, **stay in the same xApp terminal** to inspect the measurements:

```bash
if [ -n "${KPM_LOG:-}" ] && [ -f "$KPM_LOG" ]; then
  grep -E 'UE ID type|^DRB\.|^RRU\.' "$KPM_LOG" | tail -n 20
else
  printf 'KPM log is unset or missing; first run the entire step 6 block in this terminal.\n'
fi
```

If you switch terminals, first run `read -r -p 'Paste the full file path printed after log= in step 6: ' KPM_LOG` to select that capture's log, then run the check above. Do not guess an old log filename.

Require a UE ID and values for all five DU measurements before recording reception as successful. Empty output, `noValue`, or subscription success alone cannot prove that actual UE measurements arrived.

An xApp without the timestamp patch displays an invalid `KPM-v3 ind_msg latency`; the normal measurement summary excludes this line. The current source, installation, and actual UE `report_age_us` display have passed verification. Use the next step for repeat checks.

### 7a Verify reports after the timestamp repair

On 2026-10-07, an earlier run after installation received **12 reports** for UE ID `2`, with `report_age_us` of **499–717 µs**. The latest repeat received **12 reports** for UE ID `7`, with **591–796 µs**. Both completed subscription, deletion, and xApp exit successfully. An intervening run subscribed successfully but received no UE reports. **CU, DU, and RIC do not need a restart.** Wait for any existing xApp to exit, then repeat the check in this order.

1. Start the server in the Spark **iperf terminal**; skip this if it is already running:

```bash
iperf3 -s -B 10.45.0.1
```

2. In the UE laptop's Bash terminal where WWAN was configured, start a 30-second uplink transfer:

```bash
iperf3 -c 10.45.0.1 -B "${UE_IP:?Use the terminal where WWAN was configured}" -t 30 -i 0
```

3. Immediately after UE traffic starts, run the entire block below in the Spark **xApp terminal** so its roughly 10-second collection window overlaps the transfer. This creates a new log and does not depend on `KPM_LOG` from an earlier terminal:

```bash
KPM_LOG=$(mktemp /tmp/flexric-kpm.XXXXXX.log)
if /usr/local/bin/flexric/xApp/c/xapp_oran_moni \
  -c /usr/local/etc/flexric/xapp_oran_sm.conf >"$KPM_LOG" 2>&1; then
  KPM_EXIT=0
else
  KPM_EXIT=$?
fi
if [ "$KPM_EXIT" -eq 0 ] &&
   grep -q 'Successfully subscribed to RAN_FUNC_ID 2' "$KPM_LOG" &&
   grep -q 'E42 SUBSCRIPTION DELETE RESPONSE rx' "$KPM_LOG" &&
   grep -q 'Test xApp run SUCCESSFULLY' "$KPM_LOG"; then
  KPM_REPORTS=$(awk '/^KPM-v3 report_age_us/ {n++} END {print n+0}' "$KPM_LOG")
  KPM_UES=$(awk '/^UE ID type = gNB-DU/ {n++} END {print n+0}' "$KPM_LOG")
  if [ "$KPM_REPORTS" -gt 0 ] && [ "$KPM_UES" -gt 0 ]; then
    printf 'KPM: OK (subscription, deletion, exit); UE reports=%s; log=%s\n' "$KPM_REPORTS" "$KPM_LOG"
    grep -E 'report_age_us|UE ID type' "$KPM_LOG" | tail -n 15
  else
    printf 'KPM: OK (subscription, deletion, exit); NO_UE (no UE reports in this run); log=%s\n' "$KPM_LOG"
    printf 'Confirm UE registration and overlap between traffic and collection.\n'
  fi
else
  printf 'KPM: FAIL (exit=%s; lifecycle checks failed); log=%s\n' "$KPM_EXIT" "$KPM_LOG"
  tail -n 30 "$KPM_LOG"
fi
```

A positive `UE reports` count confirms UE reports arrived in this run. `NO_UE` means subscription, deletion, and exit succeeded but no UE report arrived; check UE registration and traffic overlap. It does not establish a timestamp-repair failure. The printed path contains the full log; use step 7 in the same terminal to inspect the five measurements.

`report_age_us` is in microseconds and includes report processing, queuing, and forwarding time. It is not pure network delay or application RTT. A 30-second TCP uplink passed on 2026-10-12. Precise traffic/KPM timing correlation, report-period accuracy, and sustained stability remain to be verified. Downlink is outside the current acceptance scope. For the cause and accuracy limits, see the [Timestamp Repair Record](troubleshooting/2026-10-07_flexric_latency_fix.md).

If the repair needs reinstalling later, run the following in a Spark terminal and enter the sudo password. The script backs up and atomically replaces the KPM library and two C monitors:

```bash
sudo bash /home/nyu/Desktop/Falcon_repo/Falcon/scripts/flexric/install_timestamp_fix.sh
```

## 8 Shut down

1. Stop iperf, video, and other applications on both hosts. Let the finite xApp delete its subscription and exit normally.
2. Disconnect the UE laptop's bearer and remove this run's manual WWAN address and private host route; see [UE Shutdown](ue_laptop_quick_commands.md).
3. Press **`Ctrl+C` in the DU terminal**. Wait for `Stopping...` and the shell prompt; confirm DU has exited before stopping FlexRIC and CU.
4. Press **`Ctrl+C` in the FlexRIC terminal**, then **`Ctrl+C` in the CU terminal**.
5. Stop the ten core services in reverse order in the diagnostics terminal. WebUI/MongoDB may remain running.

```bash
CORE_UNITS=(open5gs-nrfd open5gs-scpd open5gs-udrd open5gs-udmd open5gs-ausfd open5gs-pcfd open5gs-nssfd open5gs-upfd open5gs-smfd open5gs-amfd)
for unit in open5gs-amfd open5gs-smfd open5gs-upfd open5gs-nssfd open5gs-pcfd open5gs-ausfd open5gs-udmd open5gs-udrd open5gs-scpd open5gs-nrfd; do
  sudo systemctl stop "$unit" || break
done
remaining=0
if pgrep -a -x 'odu|nearRT-RIC|ocu|xapp_oran_moni'; then
  printf 'FAIL: The processes above are still running\n'
  remaining=1
fi
for unit in "${CORE_UNITS[@]}"; do
  if systemctl is-active --quiet "$unit"; then
    printf 'FAIL: %s is still active\n' "$unit"
    remaining=1
  fi
done
[ "$remaining" -ne 0 ] || printf 'Stopped: DU / RIC / CU / xApp / 10 core units\n'
```

For a full shutdown, finish with `sudo docker stop open5gs-mongo` and `sudo systemctl stop open5gs-webui` if that unit is installed. Do not delete containers or volumes. Expand the current logs only after a failure, replacing the unit below with the failed service:

```bash
sudo journalctl -u open5gs-amfd --since '5 minutes ago' --no-pager -n 30
sudo grep -Ei 'E2|subscription|decode|error|failure' "${DU1_RUN:?Use this run directory from step 5}/du.log" | tail -n 30
tail -n 30 /tmp/flexric-ric.log
```

For RF errors and USB issues, follow the [full runbook](full_reproduction_runbook.md#9-confirm-rf-and-start-the-du); do not probe B210 while DU is running. The old FlexRIC `1a3903a7` failed the Format 4 subscription in this test. Use the verified `73650812` build and matching libraries.
