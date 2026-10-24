# Full Reproduction Runbook: Single-Link 5G SA

Network update, 2026-10-23: this installed Spark now uses `ogstun_1` for UE1
`10.45.0.1/16` and `ogstun_2` for UE2 `10.46.0.1/16`, both MTU 1400. The
Spark commands below use UE1's new interface. The
[TUN split guide](../networking/dual_ue_tun_split.md) contains the applied configuration,
archived scripts and rollback; post-split UE traffic and cold-boot validation
remain pending. Earlier measurements below retain their original scope.

Last updated: 2026-10-23. The **2026-10-12 3660-MHz single-UE/DU1 uplink checkpoint passed** private ping, a 30-second TCP uplink with receiver 17.0 Mbit/s and sender Retr 0, and 12 complete five-metric KPM reports for UE F1AP ID 5. **RF stability remains pending** because of recurring underflows; downlink is outside the current acceptance scope. The earlier 2026-10-05 and 2026-10-07 results remain historical evidence. See the [daily log](../../dev_logs/2026-10-12_ruibin.md), [retained evidence](../evidence/2026-10-12_du1_3660mhz/manifest.json), and [Spark](../single_ue/spark_quick_commands.md) / [UE](../single_ue/ue_laptop_quick_commands.md) quick commands.

**Startup:** physical connections → USB 3 verification → host performance → clean SA service selection → MongoDB → subscriber/IPv4/NRF checks → required 5GC → `ogstun_1` for UE1 → CU → FlexRIC → DU with complete 3660-MHz configuration → xApp subscription check → laptop setup → NR/SA cell lock → registration → IPv4 PDU session → active bearer → WWAN configuration → ping → traffic with KPM reception check.

**Shutdown:** traffic and xApp subscription → PDU session → manual laptop addresses/routes → optional modem disable → DU → FlexRIC → CU → required 5GC → optional/legacy services for a full shutdown → optional WebUI/MongoDB stop.

Open Cells SIMs OC011830 (`001010000000101`) and OC011831 (`001010000000102`) have now been provisioned, authenticated with Milenage, and verified as ready in Quectel modems. Those checks do not establish RAN/Open5GS registration of the new IMSIs. The existing single-link commands and results below retain baseline IMSI `001010000000001`. See [SIM Provisioning and Dual-UE Preparation](../setup/sim_provisioning_and_dual_ue.md) before replacing that baseline card.

Execute one numbered stage at a time. Check the stated evidence before advancing. Labels identify the execution host: `[SPARK]`, `[LAPTOP]`, or `[RM500Q AT]`. CU/DU and application commands remain in foreground terminals. Keep the laptop's management Wi-Fi default route. Public Internet, NAT, and MASQUERADE are not needed for laptop-to-Spark traffic.

## 1. Baseline and physical connections

The current functional uplink configuration is n78, carrier ARFCN **644000 / 3660 MHz**, SSB ARFCN **643680**, 20 MHz, 30 kHz SCS, PCI 1, PLMN `00101`, TAC 7, SST 1, DNN `internet`, and IPv4. B210 serial is `3271233`, sample rate 23.04 MS/s, and the actual new file uses **TX 70 / RX 35**. It includes E2/KPM and scheduler/RLC metrics in one file. Historical carrier 650000 / 3750 MHz and SSB 649632 remain documented in the [configuration history](../project_progress_and_configuration.md#configuration-records); the old files are preserved. Record actual gains per run; gain is not calibrated dBm or EIRP.

`[SPARK]` Connect B210 through USB 3; do not place the working DU on a 480M USB 2 path. Attach the verified RF antenna path before enabling transmission. Use the authorized laboratory frequency and power conditions. B210 frequency conversion for FR3 is future work.

`[LAPTOP]` Connect RMU500EK with RM500Q-GL, the test USIM, antennas, and the tested data/auxiliary-power USB connections. USB IDs and port numbers must be rediscovered after reboot or movement to a new laptop. For two modems, use one Bash terminal per UE and verify the modem IMEI/device identity and inserted SIM before acting. Do not overwrite the first UE's variables by selecting a second modem in its active terminal. The two terminals share Linux routing tables; separate WWAN/IP paths and MPTCP remain preparation work.

## 2. Check for old RAN processes before probing the B210

`[SPARK]`

```bash
pgrep -a -x odu || true
pgrep -a -x ocu || true
```

If an old experiment is running, follow [shutdown](#16-shutdown) first. For an orphaned foreground terminal, inspect these named processes and then request graceful termination:

`[SPARK]`

```bash
sudo pkill -INT -x odu
sudo pkill -INT -x ocu
pgrep -a -x odu || true
pgrep -a -x ocu || true
```

`pkill` may return status 1 if no matching process exists. Wait until neither CU nor DU remains; do not probe an active DU's radio. These names refer to the single-link experiment on the dedicated host.

`[SPARK]` Once the DU is stopped:

```bash
lsusb
lsusb -t
sudo uhd_find_devices
```

Expect B210 `3271233` at `5000M`. Optional hardware probe, while DU is stopped:

`[SPARK]`

```bash
sudo uhd_usrp_probe --args="type=b200,serial=3271233"
```

Expect `Operating over USB 3` and register loopback success. Do not run device discovery, probe, or benchmark during DU operation.

## 3. Apply the recorded host performance settings

`[SPARK]`

```bash
cd /home/nyu/ocudu
sudo ./scripts/ocudu_performance
```

For the three prompts, answer `Y`, `Y`, `Y`, as in the successful session. The script sets CPU governors to performance, disables DRM KMS polling, and sets four network-buffer limits/defaults to 33554432 bytes. The script describes the network-buffer adjustment as intended for Ethernet USRPs; its individual contribution to this USB B210 result was not isolated. The combined host tuning and privileged DU launch reduced recurring RF failures.

`[SPARK]`

```bash
cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort | uniq -c
sudo cat /sys/module/drm_kms_helper/parameters/poll
sysctl net.core.rmem_max net.core.wmem_max net.core.rmem_default net.core.wmem_default
```

Recorded target: `20 performance`, DRM polling `N`, network values `33554432`. Check again after a host reboot; persistence has not been established. Do not add kernel, boot, CPU-isolation, IRQ, or PREEMPT_RT changes.

## 4. Select the local SA services

`[SPARK]` On this dedicated testbed, stop unrelated installed services that were found still running after earlier SA shutdowns:

```bash
sudo systemctl stop open5gs-mmed open5gs-hssd open5gs-pcrfd open5gs-sgwcd open5gs-sgwud
sudo systemctl stop open5gs-bsfd open5gs-seppd
```

The first group is legacy LTE EPC. BSF and SEPP are optional for this single-PLMN experiment; their cleanup does not imply that they caused the SA failures. An absent unit on another deployment should be omitted. WebUI is subscriber administration only and may remain running.

## 5. Start MongoDB and verify the subscriber

`[SPARK]`

```bash
sudo docker ps -a --filter name=open5gs-mongo
sudo docker start open5gs-mongo
sudo docker exec open5gs-mongo mongosh --quiet --eval 'db.adminCommand({ping: 1})'
```

Expect the existing `mongo:7.0-jammy` container and `{ ok: 1 }`. Preserve `open5gs-mongo-data`; do not create a replacement database or delete volumes. Native MongoDB 8 remains disabled.

`[SPARK]` Print only nonsecret subscriber fields:

```bash
sudo docker exec open5gs-mongo mongosh --quiet --eval '
db.getSiblingDB("open5gs").subscribers.find(
  {imsi:"001010000000001"},
  {_id:0,imsi:1,"slice.sst":1,"slice.session.name":1,"slice.session.type":1}
).pretty()
'
```

Required: IMSI `001010000000001`, SST 1, session name `internet`, session **type 1 (IPv4)**. Type 3 is IPv4v6 and was rejected by this OCUDU build. If the subscriber is absent, stop and provision it using the SIM's known authentication parameters through the existing administrative workflow. IMSI cannot reveal Ki/OPc. Never commit credentials, authentication vectors, or derived RAN security keys.

If the existing SST 1 / `internet` session is type 3, this targeted repair updates its type without replacing security fields or other sessions:

`[SPARK]`

```bash
sudo docker exec open5gs-mongo mongosh --quiet --eval '
db.getSiblingDB("open5gs").subscribers.updateOne(
  {imsi:"001010000000001"},
  {$set:{"slice.$[s].session.$[p].type":1}},
  {arrayFilters:[{"s.sst":1},{"p.name":"internet"}]}
)
'
```

Rerun the projection and require type 1. No matched slice/session means the intended entry has not been repaired. The session recorded on 2026-10-05 occupied `slice.0.session.0`; named array filters avoid assuming that index on a later database.

### 5a Prepare the two provisioned Open Cells subscribers

The new cards are intended for UE1/DU1 and UE2/DU2, respectively:

| Card | New IMSI | Matching protected credential file |
| --- | --- | --- |
| OC011830 | `001010000000101` | `~/sim_du1_credentials.txt` |
| OC011831 | `001010000000102` | `~/sim_du2_credentials.txt` |

Create each Open5GS record through the installed administrative workflow with its own matching K/OPc, PLMN `00101`, SST 1, DNN `internet`, and IPv4 session type 1. The files remain private with mode 600; do not print them or put credentials in commands/logs committed to Git. K/OPc cannot be reconstructed from IMSI/ICCID, and SIM1's pair must not be copied into SIM2's record.

The programming authentication succeeded at SQN `64` and recommended core reference `96`. Verify the installed Open5GS UI/API/database representation and current SQN before applying that reference; it is not a permanent value to reset after further authentication. Local representation verification and creation of these two subscriber records remain pending. See [Prepare Open5GS subscribers](../setup/sim_provisioning_and_dual_ue.md#prepare-open5gs-subscribers).

`[SPARK]` After administrative preparation, this read-only reproduction check prints one nonsecret result per new subscriber. It does not validate the secret fields or SQN:

```bash
sudo docker exec open5gs-mongo mongosh --quiet --eval '
const subscribers = db.getSiblingDB("open5gs").subscribers;
let failed = false;
for (const imsi of ["001010000000101", "001010000000102"]) {
  const records = subscribers.find({imsi}, {_id:0,imsi:1,slice:1}).toArray();
  if (records.length !== 1) {
    print(imsi + ": FAIL (records=" + records.length + ")");
    failed = true;
    continue;
  }
  const sessions = (records[0].slice || []).filter(s => s.sst === 1)
    .flatMap(s => s.session || []).filter(s => s.name === "internet" && s.type === 1);
  const ok = sessions.length === 1;
  print(imsi + ": " + (ok ? "OK (SST 1, internet, IPv4 type 1)" : "FAIL (slice/session)"));
  failed = failed || !ok;
}
if (failed) quit(1);
'
```

Keep the baseline subscriber `001010000000001` unless intentionally retiring it. This two-record check is a procedure, not evidence that the new subscribers have already been created or registered.

## 6. Check infrastructure configuration

`[SPARK]`

```bash
grep -n -A5 'serving:' /etc/open5gs/nrf.yaml
grep -n -A15 -E 'guami:|tai:|plmn_support:' /etc/open5gs/amf.yaml
grep -nE 'device_args|srate|clock:|clock_ppm|freq_offset|tx_gain|rx_gain|dl_arfcn|band:|channel_bandwidth_MHz|common_scs|plmn:|tac:|pci:|all_level' /home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml
sed -n '1,85p' /home/nyu/ocudu/configs/cu.yml
```

NRF `serving` and AMF GUAMI/TAI/PLMN support must be MCC `001`, MNC `01`; AMF TAC 7 and SST 1. NRF's old `999/70` entry caused NF discovery failure and Registration Reject 95. Compare the OCUDU output with [configuration records](../project_progress_and_configuration.md#configuration-records). Preserve leading zeros when editing PLMN fields.

Runtime IP relationships: CU N2 `127.0.0.1` → AMF `127.0.0.5:38412`; DU F1-C `127.0.10.2` → CU `127.0.10.1:38472`; DU F1-U `127.0.10.2:2152` ↔ CU `127.0.10.1:2152`; CU N3 `127.0.0.1:2152` ↔ UPF `127.0.0.7:2152`; SMF PFCP `127.0.0.4:8805` ↔ UPF `127.0.0.7:8805`.

## 7. Start only the required 5GC functions

`[SPARK]` Execute sequentially, checking for command errors:

```bash
sudo systemctl daemon-reload
sudo systemctl start open5gs-nrfd
sudo systemctl start open5gs-scpd
sudo systemctl start open5gs-udrd
sudo systemctl start open5gs-udmd
sudo systemctl start open5gs-ausfd
sudo systemctl start open5gs-pcfd
sudo systemctl start open5gs-nssfd
sudo systemctl start open5gs-upfd
sudo systemctl start open5gs-smfd
sudo systemctl start open5gs-amfd
```

`[SPARK]`

```bash
for service in open5gs-nrfd open5gs-scpd open5gs-udrd open5gs-udmd open5gs-ausfd open5gs-pcfd open5gs-nssfd open5gs-upfd open5gs-smfd open5gs-amfd; do
  printf '%-20s ' "$service"
  systemctl is-active "$service"
done
sudo ss -lnpA sctp
sudo ss -lunp | grep -E ':8805|:2152'
sudo journalctl -u open5gs-amfd -u open5gs-smfd -u open5gs-upfd --since '5 minutes ago' --no-pager
```

Every listed service must be `active`; AMF listens on `127.0.0.5:38412`, UPF on `127.0.0.7:2152`, and SMF/UPF PFCP association succeeds. Review current timestamps; old reject or shutdown records do not describe this startup.

`[SPARK]`

```bash
ip link show ogstun_1
ip -4 addr show dev ogstun_1
ip -4 route show
systemctl is-active systemd-networkd
cat /etc/systemd/network/99-open5gs.netdev /etc/systemd/network/99-open5gs.network
```

Require `ogstun_1` to be administratively UP with MTU 1400, gateway
`10.45.0.1/16`, and a route to `10.45.0.0/16` through that interface. The
persistent `99-open5gs.netdev` now defines `Name=ogstun_1`, `Kind=tun`, and
`99-open5gs.network` matches it. The separate `99-open5gs-ue2.netdev` /
`99-open5gs-ue2.network` pair configures `ogstun_2 / 10.46.0.1/16`.
The UPF service requests `systemd-networkd`; verify its pool-specific `dev`
settings using the [TUN split guide](../networking/dual_ue_tun_split.md). Cold-boot recovery
remains untested. Diagnose missing interfaces, addresses or routes through
those files and networkd; do not restart management networking or add Internet
NAT. Interface state alone does not prove UE connectivity.

## 8. Archive old RAN logs and start the CU

`[SPARK]` Only while CU/DU are stopped, preserve previous logs instead of deleting them. These archives remain local and may contain security material:

```bash
RAN_ARCHIVE=$(mktemp -d /tmp/falcomm-ran-logs.XXXXXX)
sudo chmod 700 "$RAN_ARCHIVE"
for logfile in /tmp/cu.log /tmp/du.log; do
  if sudo test -f "$logfile"; then
    sudo mv "$logfile" "$RAN_ARCHIVE/"
  fi
done
```

`[SPARK]` In the CU terminal:

```bash
cd /home/nyu/ocudu
sudo build/apps/cu/ocu -c configs/cu.yml
```

Expect N2 connection to `127.0.0.5:38412`, F1-C listener at `127.0.10.1:38472`, and `==== CU started ===`. Both RAN logs use `all_level: info` for local debugging; sanitize excerpts before sharing them.

`[SPARK]` In a separate diagnostics terminal:

```bash
sudo journalctl -u open5gs-amfd --since '5 minutes ago' --no-pager | grep -Ei 'gNB|NGAP|error|reject'
sudo ss -anpA sctp
```

Require the current AMF `gNB-N2 accepted` / added-gNB entry and an established N2 association.

## 9. Confirm RF and start the DU

Confirm n78, ARFCN 644000, 3660 MHz, 20 MHz, 30 kHz, PLMN `00101`, TAC 7, PCI 1, B210 `3271233`, and actual TX/RX gain against stage 6. The deployed file uses TX 70 / RX 35. The DU command below enables RF transmission.

### 9a Deploy the complete DU1 configuration

The new standalone file already contains radio, cell, F1, E2/KPM, and metrics
settings. Copy the maintained file to the Spark deployment directory and check
parsing; keep the historical base/E2 files available for reference.

`[SPARK]`

```bash
cp /home/nyu/Desktop/Falcon_repo/Falcon/configs/ocudu/dual_fr1/du1_b210_n78_3660mhz.yml \
  /home/nyu/ocudu/configs/du1_b210_n78_3660mhz.yml
cd /home/nyu/ocudu
build/apps/du_split_8/odu --dryrun -c configs/du1_b210_n78_3660mhz.yml
echo "dryrun_exit=$?"
```

Require `dryrun_exit=0`. Dry run checks parsing/autoderivation and exits before
full runtime validation or RF startup. Embedded E2 is already present; no
`ENABLE_EXPORT` or ZeroMQ rebuild is required.

### 9b Start FlexRIC and the DU

Use installed FlexRIC `73650812`, built with `E2AP_V3` / `KPM_V3_00`; see [installation](../setup/software_installation_and_drivers.md#8-flexric-installation-on-spark). CU must already be running. In a separate RIC terminal:

`[SPARK]`

```bash
/usr/local/bin/flexric/ric/nearRT-RIC \
  -c /usr/local/etc/flexric/ric.conf
```

Keep it running. Check its two SCTP listeners once:

```bash
ss -lnp -A sctp | grep -E ':36421|:36422'
```

Require `127.0.0.1:36421` for E2 and `127.0.0.1:36422` for xApp E42. Start DU only after CU and RIC are available: its E2 Setup requires F1 component information, and restarting RIC requires restarting DU for a new association.

`[SPARK]` In the DU terminal:

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

The [console launcher](../../scripts/dual_fr1/run_du_console.sh) uses `script`
to preserve the interactive terminal and record output. After startup, enter
`;h;` and require the help response. Use one semicolon-delimited console
command at a time; see [temporary RX gain](../dual_ue_spark_quick_commands.md#5d-console-input-and-temporary-rx-gain).

Expect B210 / USB 3 initialization, 23.04 MHz master clock, cell PCI 1 / 20 MHz / n78 / carrier ARFCN 644000 / SSB ARFCN 643680, F1-C and E2 connections completed, and `==== DU started ===`. RIC should accept `ngran_gNB_DU`, DU ID 1, node ID 411 and RAN function ID 2 (`ORAN-E2SM-KPM`). Check the running DU without opening the B210 from another tool:

`[SPARK]` In a separate diagnostics terminal, select this launch's log directory:

```bash
read -r -p 'DU1 run directory printed by this launch: ' DU1_RUN
sudo ss -anpA sctp
sudo ss -lunp | grep 2152
sudo grep -Ei 'PRACH|PUSCH|CRC|SINR|UE Create|underflow|overflow|late' "${DU1_RUN:?Select the current DU run directory}/du.log" | tail -100
sudo grep -Ei 'PDUSession|Unsupported PDU Session Type|Validation.*failed' /tmp/cu.log | tail -80
sudo grep -Eic 'underflow' "${DU1_RUN:?Select the current DU run directory}/du.log"
sudo grep -Eic 'late' "${DU1_RUN:?Select the current DU run directory}/du.log"
sudo grep -Eic 'overflow' "${DU1_RUN:?Select the current DU run directory}/du.log"
```

N2, F1-C and E2 to `:36421` must be `ESTAB`. GTP-U listeners include DU `127.0.10.2`, CU F1-U `127.0.10.1`, CU N3 `127.0.0.1`, UPF `127.0.0.7`, all port 2152. Open5GS SMF may also listen on `127.0.0.4:2152`; it is separate from the four data-path endpoints.

Counters of zero make `grep -c` return status 1; this is not itself a failure. Observe whether counters grow during traffic. For an ongoing monitor:

`[SPARK]` In a separate diagnostics terminal:

```bash
sudo tail -F "${DU1_RUN:?Select the current DU run directory}/du.log" | grep --line-buffered -Ei 'underflow|overflow|late|RF.*failure'
```

Stop this monitor with `Ctrl+C`. Continuous RF failures require investigation; an isolated late event does not establish a stable long-duration result. The recorded post-tuning check was underflow 0, late 1, not a guaranteed result for every run.

### 9c Verify the KPM subscription

`[SPARK]` After RIC has registered the DU, run in another terminal:

```bash
/usr/local/bin/flexric/xApp/c/xapp_oran_moni \
  -c /usr/local/etc/flexric/xapp_oran_sm.conf
```

Require `Registered E2 Nodes = 1`, `SUBSCRIPTION RESPONSE rx` and `Successfully subscribed to RAN_FUNC_ID 2`. This example collects for about 10 seconds, sends a subscription delete and exits with `Test xApp run SUCCESSFULLY`. The DU block uses KPM Format 4, a 1000 ms period and five DU metrics. Without an eligible UE, subscription can succeed with no measurement indications. Actual UE reception is checked in stage 14a.

If subscription fails, consult the [2026-10-07 record](../troubleshooting/2026-10-07_flexric_bringup.md). `log.all_level: info` does not override the separate E2AP logger's warning default; for detailed E2 diagnosis set `log.e2ap_level: debug` in the complete DU configuration and restart DU after RIC is running. Share only narrow E2/KPM excerpts, not complete RAN logs.

## 10. Prepare a new Ubuntu/Linux laptop

`[LAPTOP]` Install only if missing on this laptop:

```bash
sudo apt update
sudo apt install -y modemmanager libqmi-utils minicom iproute2 iperf3 usbutils
sudo systemctl enable --now ModemManager
systemctl is-active ModemManager
lsusb
ls -l /dev/cdc-wdm* /dev/ttyUSB* 2>/dev/null || true
ip -br link | grep -E 'wwan|rmnet' || true
mmcli -L
```

Expect USB `2c7c:0800`, a Quectel RM500QGL_VH modem, QMI, AT and network ports. Drivers observed in the working setup were `option`, `qmi_wwan`, and `cdc_wdm`. If ports are absent, follow the [laptop driver inspection](../setup/software_installation_and_drivers.md#72-kernel-driver-responsibilities) and inspect recurring disconnects before changing modem firmware.

`[LAPTOP]` Use one terminal per UE. The following identity-selection wrapper is a reproduction procedure; the supplied session verified the underlying `mmcli` reads. For the provisioned-card plan, the observed modem IMEIs were `863305041978437` (Quectel #1) and `863305041980706` (Quectel #2). Select the intended device identity rather than the first entry from `mmcli -L`:

```bash
mm_value() {
  awk -F ':' -v key="$1" '
    { field=$1; gsub(/^[ \t]+|[ \t]+$/, "", field) }
    field==key { sub(/^[^:]*:[ \t]*/, ""); sub(/[ \t]+$/, ""); print; exit }
  '
}

select_rm500q() {
  local listing path details model identity imei
  local -a candidates=() matched=()
  if [ -n "${BEARER:-}" ] || [ -n "${WWAN_IF:-}" ]; then
    printf 'This terminal retains a UE bearer/WWAN; finish cleanup and use a fresh UE terminal.\n'
    return 1
  fi
  MODEM=""
  listing=$(mmcli -L) || return 1
  mapfile -t candidates < <(printf '%s\n' "$listing" |
    awk '/RM500Q/ { print }' | grep -oE '/org/freedesktop/ModemManager1/Modem/[0-9]+')
  if [ ${#candidates[@]} -eq 0 ]; then
    printf 'No RM500Q found; check USB and drivers before retrying.\n'; return 1
  fi
  read -r -p 'Expected RM500Q IMEI or device identifier: ' EXPECTED_MODEM_ID
  [ -n "$EXPECTED_MODEM_ID" ] || return 1
  for path in "${candidates[@]}"; do
    details=$(mmcli -m "$path" -K) || return 1
    model=$(printf '%s\n' "$details" | mm_value modem.generic.model)
    identity=$(printf '%s\n' "$details" | mm_value modem.generic.device-identifier)
    imei=$(printf '%s\n' "$details" | mm_value modem.generic.equipment-identifier)
    printf 'candidate=%s imei=%s identity=%s\n' "$path" "$imei" "$identity"
    if [[ "$model" = *RM500Q* && -n "$identity" && "$identity" != -- ]] &&
       [[ "$EXPECTED_MODEM_ID" = "$imei" || "$EXPECTED_MODEM_ID" = "$identity" ]]; then
      matched+=("$path")
    fi
  done
  if [ ${#matched[@]} -ne 1 ]; then
    printf 'Expected identity matched %s modems; stop and inspect.\n' "${#matched[@]}"; return 1
  fi
  MODEM=${matched[0]}
  MODEM_KV=$(mmcli -m "$MODEM" -K) || { MODEM=""; return 1; }
  MODEM_IDENTITY=$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.device-identifier)
  imei=$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.equipment-identifier)
  if [[ "$EXPECTED_MODEM_ID" != "$imei" && "$EXPECTED_MODEM_ID" != "$MODEM_IDENTITY" ]]; then
    MODEM=""; printf 'Device identity changed; stop here.\n'; return 1
  fi
  printf 'modem=%s imei=%s firmware=%s\n' "$MODEM" "$imei" \
    "$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.revision)"
}
select_rm500q
```

A previously disabled modem needs `sudo mmcli -m "$MODEM" --enable`. Firmware verified in the earlier working link is `RM500QGLABR13A03M4G`. After a power cycle, modem/SIM IDs and ports must be rediscovered by identity; do not reuse historical numbers. Do not rerun selection in a terminal retaining an active bearer/WWAN.

`[LAPTOP]` Read the selected modem's actual SIM path and `(qmi)` port, using QMI proxy alongside ModemManager. This compact wrapper is a read-only reproduction procedure:

```bash
MODEM_KV=$(mmcli -m "$MODEM" -K)
SIM_PATH=$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.sim)
if [[ "$SIM_PATH" =~ ^/org/freedesktop/ModemManager1/SIM/[0-9]+$ ]] && \
   SIM_KV=$(mmcli -i "$SIM_PATH" -K); then
  printf 'SIM active=%s IMSI=%s ICCID=%s operator=%s name=%s\n' \
    "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.active)" \
    "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.imsi)" \
    "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.iccid)" \
    "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.operator-code)" \
    "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.operator-name)"
else
  printf 'No valid SIM readout for the selected modem; stop here.\n'
fi
mapfile -t QMI_PORTS < <(printf '%s\n' "$MODEM_KV" |
  grep -oE 'cdc-wdm[0-9]+ \(qmi\)' | awk '{print $1}' | sort -u)
if [ ${#QMI_PORTS[@]} -eq 1 ]; then
  QMI_PORT=${QMI_PORTS[0]}
  if QMI_STATUS=$(sudo qmicli -p -d "/dev/$QMI_PORT" --uim-get-card-status); then
    printf '%s\n' "$QMI_STATUS" | awk '/Card state:|Application type:|Application state:|Personalization state:|PIN1 state:|PIN2 state:/ {print}'
  else
    printf 'USIM query failed; stop and inspect.\n'
  fi
else
  printf 'Expected one QMI port on this modem; found %s. Stop and inspect.\n' "${#QMI_PORTS[@]}"
fi
```

Match the readout to the intended card in [SIM assignments](../setup/sim_provisioning_and_dual_ue.md#sim-assignments). Both provisioned cards were active, preferred PLMN `00101` with LTE/5G NR, and had card present, USIM/application/personalization ready, and PIN1 disabled. PIN2 `enabled-not-verified` did not prevent the reported checks and does not currently need changing. The historical baseline's all-FF ICCID did not prevent authentication; do not mistake it for the new cards' actual ICCIDs.

SIM-ready status is separate from network registration. SIM2 was still `searching / detached`; its approximately 88% signal quality did not prove detection of the private `00101` cell or RAN/core attachment. Both new IMSIs still require real registration. Carrier profiles `Volte_OpenMkt-Commercial-CMCC` and `ROW_Commercial` differed between units/sessions; record the difference for later troubleshooting, without changing it solely because SIM checks succeeded.

`[LAPTOP]` The existing optional NAS diagnostics remain available for serving-system and signal troubleshooting. Use the unique QMI port discovered above with proxy mode:

```bash
if [ ${#QMI_PORTS[@]} -eq 1 ]; then
  sudo qmicli -p -d "/dev/${QMI_PORTS[0]}" --nas-get-serving-system
  sudo qmicli -p -d "/dev/${QMI_PORTS[0]}" --nas-get-signal-info
else
  printf 'No unique QMI port for the selected modem; stop and inspect.\n'
fi
```

For a SIM swap, stop traffic and disconnect/clean up any bearer using [stage 16](#16-shutdown), disable the selected modem, physically power off/disconnect the RMU, swap the card, and reconnect power. Start a fresh UE terminal, then rediscover identity, modem/SIM paths, and ports. Do not hot-swap. See [Quectel verification and safe handling](../setup/sim_provisioning_and_dual_ue.md#verify-the-cards-through-quectel).

## 11. Configure RM500Q NR SA and lock the private cell

The cell lock in this stage applies to **DU1 only**. DU2 configuration, B210 serial, PCI/SSB, and F1/E2 bind addresses are not yet supplied; do not use the DU1 lock or launch as a DU2 template. IMSI assignment does not automatically route a modem to a DU.

`[LAPTOP]` After the modem identity check in stage 10, open the current setup's AT port directly. ModemManager may omit working AT ports:

```bash
sudo minicom -D /dev/ttyUSB2 -b 115200
```

Type `AT` in minicom and require `OK` before configuring the modem. Keep ModemManager running; missing `(at)` entries alone require no reboot or `AT+CFUN`. After USB reconnection, rerun stage 10's identity selection and check the actual ttyUSB numbering.

`[RM500Q AT]` Type into minicom, not the Linux shell:

```text
AT
AT+CIMI
AT+CFUN=1,1
```

Expect `OK` and baseline IMSI `001010000000001` for the original test card, then a modem reboot. A newly provisioned card must report its actual `001010000000101` or `001010000000102` instead; that identity read is not a registration result. USB ports and ModemManager IDs may change. Exit/reopen minicom after enumeration, discover the modem and AT port again using stages 10–11, and wait for `RDY` / `+CPIN: READY` where provided. Do not reboot again after the final cell lock.

`[RM500Q AT]` Set preferences in this order, requiring `OK` after each write:

```text
AT+QNWPREFCFG="mode_pref",NR5G
AT+QNWPREFCFG="mode_pref"
AT+QNWPREFCFG="nr5g_disable_mode",2
AT+QNWPREFCFG="nr5g_disable_mode"
AT+QNWPREFCFG="nr5g_band"
AT+QNWLOCK="common/5g",1,643680,30,78
AT+QNWLOCK="common/5g"
```

For this tested firmware, disable mode 2 disables NSA and gives SA-only operation. The band query must include n78; the tested selection was 78. The lock parameters are **PCI 1, SSB ARFCN 643680, SCS 30, band 78**. Do not use carrier ARFCN 644000 in place of the SSB lock value. Old `QCFG` preference commands returned ERROR on this firmware. Recheck preferences and lock after every physical/CFUN reboot because they may reset.

`[RM500Q AT]`

```text
AT+QENG="servingcell"
AT+C5GREG?
AT+QNWINFO
```

Require `NR5G-SA`, PLMN `001/01`, PCI 1, TAC 7, SSB 643680, band 78 and `+C5GREG: 0,1`. `NOCONN` in QENG is acceptable idle/camped state; confirm registration with C5GREG. If not registered, use `AT+QSCAN=3` to establish whether the private cell is detectable, then follow [the troubleshooting record](../troubleshooting/2026-10-05_sa_bringup.md). A scan can take time; retain its result.

Exit minicom with `Ctrl+A`, then `X`. Leave ModemManager managing the connection; do not open the same AT port in another terminal simultaneously. If another process holds the selected AT port, close the conflicting session and inspect ownership rather than resetting the firmware.

## 12. Register and create an IPv4 PDU session

`[LAPTOP]` If the modem rebooted before PDU setup, rerun the stage 10 identity selection in its own UE terminal. Do not reselect another modem in an active WWAN terminal:

```bash
select_rm500q
mmcli -m "$MODEM"
```

Require registered state, access technology `5gnr`, operator `00101`, home registration, and packet service attached. Then:

`[LAPTOP]`

```bash
sudo mmcli -m "$MODEM" --simple-connect="apn=internet,ip-type=ipv4"
mmcli -m "$MODEM"
```

Expect `successfully connected the modem` and connected state. If it fails, diagnose PDU setup separately from registration. CU logs may show `Unsupported PDU Session Type: ipv4v6` even though Open5GS allocated an IP; check subscriber type 1 first.

## 13. Inspect the active bearer and configure WWAN

`[LAPTOP]` Obtain all bearer paths from the selected modem and find its connected `internet` bearer. Use `mm_value` defined in stage 10:

```bash
BEARER=""
matches=()
discovery_ok=yes
if MODEM_KV=$(mmcli -m "$MODEM" -K); then
  for path in $(printf '%s\n' "$MODEM_KV" |
    grep -oE '/org/freedesktop/ModemManager1/Bearer/[0-9]+' | sort -u); do
    details=$(mmcli -b "$path" -K) || { discovery_ok=no; break; }
    connected=$(printf '%s\n' "$details" | mm_value bearer.status.connected)
    apn=$(printf '%s\n' "$details" | mm_value bearer.properties.apn)
    if [ "$connected" = yes ] && [ "$apn" = internet ]; then matches+=("$path"); fi
  done
else
  discovery_ok=no
fi
if [ "$discovery_ok" = yes ] && [ ${#matches[@]} -eq 1 ] && \
   BEARER_KV=$(mmcli -b "${matches[0]}" -K); then
  BEARER=${matches[0]}
  UE_CONNECTED=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.connected)
  UE_SUSPENDED=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.suspended)
  WWAN_IF=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.interface)
  UE_IP=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.address)
  UE_PREFIX=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.prefix)
  UE_MTU=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.mtu)
  UE_METHOD=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.method)
  printf 'bearer=%s connected=%s suspended=%s if=%s IPv4=%s/%s mtu=%s method=%s\n' \
    "$BEARER" "$UE_CONNECTED" "$UE_SUSPENDED" "$WWAN_IF" "$UE_IP" "$UE_PREFIX" "$UE_MTU" "$UE_METHOD"
else
  printf 'No unique usable bearer found (discovery=%s, matches=%s); stop and inspect.\n' "$discovery_ok" "${#matches[@]}"
fi
```

Do not use `--list-bearers`; the tested CLI rejected that form. `mmcli -m` → bearer path → `mmcli -b` is supported. The modem's **EPS initial bearer ip type** may still say `ipv4v6`; the **active bearer** must say IPv4. Expect connected yes, suspended no, an interface (historically `wwan0`), and static IPv4 settings.

`[LAPTOP]` Extract the current bearer allocation instead of hard-coding `10.45.0.2` or `wwan0`:

```bash
BEARER_KV=$(mmcli -b "$BEARER" -K)
UE_CONNECTED=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.connected)
UE_SUSPENDED=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.suspended)
MODEM_KV=$(mmcli -m "$MODEM" -K)
WWAN_IF=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.interface)
UE_IP=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.address)
UE_PREFIX=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.prefix)
UE_MTU=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.mtu)
UE_METHOD=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.method)
printf 'interface=%s address=%s/%s mtu=%s method=%s\n' "$WWAN_IF" "$UE_IP" "$UE_PREFIX" "$UE_MTU" "$UE_METHOD"
```

The successful session reported `wwan0`, `10.45.0.2/30`, gateway `10.45.0.1`, MTU 1400, method static. Current values may differ. Stop if fields are empty/`--`, the interface is absent, the address is outside the private allocation, or the method is not static. Use the displayed bearer values; do not substitute management-interface addresses.

ModemManager reports the connection's IP settings; it does not itself configure the host interface. This explains the observed connected bearer with a DOWN/addressless WWAN device. See [ModemManager IP setup](https://modemmanager.org/docs/modemmanager/ip-connectivity-setup-in-lte-modems/).

`[LAPTOP]` The following guarded reproduction procedure configures only the dedicated QMI WWAN and one private host route. It refuses management-interface changes and refuses to replace another modem's route. The reported single-link session established static IPv4 manually; this new guard wrapper has not been executed against the live modem:

```bash
configure_wwan() {
  local current_ips mgmt_dev driver host_devs
  [[ -n "$BEARER" && "$UE_CONNECTED" = yes && "$UE_SUSPENDED" = no && "$UE_METHOD" = static ]] || return 1
  [[ "$UE_IP" =~ ^10\.45\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
  (( 10#${BASH_REMATCH[1]} <= 255 && 10#${BASH_REMATCH[2]} <= 255 )) || return 1
  [[ "$UE_IP" != 10.45.0.1 && "$UE_PREFIX" =~ ^[0-9]+$ && "$UE_MTU" =~ ^[0-9]+$ ]] || return 1
  (( UE_PREFIX >= 1 && UE_PREFIX <= 32 && UE_MTU >= 576 && UE_MTU <= 65535 )) || return 1
  [[ "$WWAN_IF" =~ ^(wwan|wwp|rmnet)[[:alnum:]_.-]*$ ]] || return 1
  ip link show dev "$WWAN_IF" >/dev/null || return 1
  driver=$(basename "$(readlink -f "/sys/class/net/$WWAN_IF/device/driver")")
  [[ "$driver" = qmi_wwan ]] || return 1
  printf '%s\n' "$MODEM_KV" | grep -Fq "$WWAN_IF (net)" || return 1
  [[ -z "$(ip -4 route show default dev "$WWAN_IF")" &&
     -z "$(ip -6 route show default dev "$WWAN_IF")" ]] || return 1
  if [ -n "$SSH_CONNECTION" ]; then
    mgmt_dev=$(ip route get "${SSH_CONNECTION%% *}" | awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}')
    [[ -n "$mgmt_dev" && "$mgmt_dev" != "$WWAN_IF" ]] || return 1
  fi
  current_ips=$(ip -o -4 addr show dev "$WWAN_IF" | awk '{print $4}')
  [[ -z "$current_ips" || "$current_ips" = "$UE_IP/$UE_PREFIX" ]] || return 1
  host_devs=$(ip -4 route show exact 10.45.0.1/32 |
    awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}' | sort -u)
  if [[ -n "$host_devs" && "$host_devs" != "$WWAN_IF" ]]; then
    printf 'The private host route belongs to another interface; dual-path routing must be planned first.\n'
    return 1
  fi
  sudo ip link set dev "$WWAN_IF" mtu "$UE_MTU" up &&
  sudo ip -4 addr replace "$UE_IP/$UE_PREFIX" dev "$WWAN_IF" noprefixroute &&
  sudo ip -4 route replace 10.45.0.1/32 dev "$WWAN_IF" src "$UE_IP"
}
if configure_wwan; then
  ip -4 route get 10.45.0.1 from "$UE_IP"
  ip -4 route show default
else
  printf 'WWAN configuration is incomplete; check the bearer, dedicated interface, and management routes before testing.\n'
fi
```

For this wrapper, populate `UE_CONNECTED` and `UE_SUSPENDED` from the active bearer using `mm_value bearer.status.connected` and `mm_value bearer.status.suspended`, respectively. Both must be `yes` / `no` before configuration. Separate UE terminals do not isolate the Linux route table. This single main-table host route is not a dual-path routing implementation; design and verify interface/source-specific routes before bringing up a second simultaneous path or MPTCP.

Verify destination `10.45.0.1` uses the modem interface and `$UE_IP`; management Wi-Fi default remains unchanged. If NetworkManager manages an active cellular profile, use one owner for WWAN configuration: disconnect that profile before manual setup, or configure equivalent local routes in the profile. Do not disable NetworkManager globally.

## 14. Ping and throughput

`[LAPTOP]`

```bash
ping -I "$WWAN_IF" -c 5 10.45.0.1
```

`[SPARK]` Enter the **current** bearer address from the laptop, then reverse ping:

```bash
read -r -p 'Current UE IPv4 address from active bearer: ' UE_IP
ping -I ogstun_1 -c 5 "$UE_IP"
iperf3 -s -B 10.45.0.1
```

Keep the iperf server in its own terminal. The historical 3750-MHz uplink used a 10-second run (sender 6.29 / receiver 5.09 Mbit/s). At 3660 MHz on 2026-10-12, a 30-second TCP uplink passed with sender 17.7 Mbit/s / Retr 0 and receiver 17.0 Mbit/s. This establishes functionality; recurring RF underflows keep stability acceptance open.

`[LAPTOP]` The current checkpoint is **uplink only**. Repeat the TCP check and retain receiver goodput and sender retransmissions:

```bash
iperf3 -c 10.45.0.1 -B "$UE_IP" -t 30 -i 0
```

Downlink, UDP, and video are future work outside this checkpoint. After uplink stability is accepted, a separately scoped UDP campaign can use individually controlled offered rates. Record direction, duration, sender/receiver rates, retransmissions, UDP jitter/loss, and concurrent DU RF-error counts. Do not infer UDP/video performance from the first TCP test. If routing is correct but traffic fails, check host firewall and service binding before adding forwarding/NAT.

### 14a Validate UE KPM reports during traffic

Initial actual UE reception passed on 2026-10-07: gNB-DU UE F1AP ID `14` produced all five measurements. The 2026-10-12 run at 3660 MHz received 12 complete five-metric reports for UE F1AP ID 5, ages 508–820 µs, and subscription/deletion plus the monitor success marker. A 30-second TCP uplink result was recorded in the same session; exact wall-clock alignment of the retained application and KPM windows was not captured. The procedure below repeats the uplink check with fresh logs. The installed timestamp-repair library and monitor match the repaired build. **Keep CU, RIC and DU running; this repair does not require their restart.** Reuse the existing iperf server or start it using stage 14, and complete stages 12–14 on the laptop.

`[LAPTOP]` In the same Bash terminal used to configure WWAN, start the uplink:

```bash
iperf3 -c 10.45.0.1 -B "${UE_IP:?Use the terminal where WWAN was configured}" -t 30 -i 0
```

`[SPARK]` Immediately run the installed xApp in its own terminal, so its approximately 10-second observation window overlaps the traffic. This creates a fresh log and prints a compact result:

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

Require a positive UE-report count, `report_age_us` and a gNB-DU UE ID together. `NO_UE` means subscription, deletion and exit succeeded but no UE report arrived in this run; confirm UE registration and traffic overlap rather than treating this as a timestamp-repair failure. A repaired live run passed with UE ID `2`, 12 report-age values of **499–717 microseconds** and normal subscription deletion/exit. This verifies the display, not precise clock/delay accuracy. See [Spark step 7a](../single_ue/spark_quick_commands.md#7a-verify-reports-after-the-timestamp-repair) for the two-host sequence and [step 7](../single_ue/spark_quick_commands.md#7-validate-ue-traffic-and-kpm-reports) for the five-metric log summary.

Require actual `UE ID type = gNB-DU` reports with measurement names and values such as `DRB.UEThpUl` and `RRU.PrbTotUl`. Record the current UE ID, direction, application rate and report cadence. Throughput is in kbps, PRB usage in percent, and `DRB.RlcSduDelayDl` in 0.1 ms units. Earlier UE `14` selected samples were UL 14163–14675 kbps, UL PRB 86% and RLC DL delay 1.580–1.730 ms after conversion. Later UE `2` selected samples were UL 11916–11927 kbps, UL PRB 88% and RLC DL delay 1.380–1.440 ms. The [timestamp repair](../troubleshooting/2026-10-07_flexric_latency_fix.md) is installed and its live display is verified; signed `report_age_us` includes processing and queuing time.

## 15. Video experiment (procedure; not yet verified)

`[SPARK]` Install FFmpeg if missing and receive in a graphical session:

```bash
sudo apt install -y ffmpeg
ffplay -fflags nobuffer 'udp://10.45.0.1:5000?fifo_size=1000000&overrun_nonfatal=1'
```

For a headless receiver, use a local recording instead of ffplay (choose a new output filename):

`[SPARK]`

```bash
ffmpeg -i 'udp://10.45.0.1:5000?fifo_size=1000000&overrun_nonfatal=1' -c copy received-private-5g.ts
```

`[LAPTOP]` Confirm a supported capture device/format before sending:

```bash
sudo apt install -y ffmpeg v4l-utils
v4l2-ctl --list-devices
read -r -p 'Camera device path shown above: ' CAMERA_DEVICE
v4l2-ctl -d "$CAMERA_DEVICE" --list-formats-ext
```

`[LAPTOP]` Adapt capture size/rate to a supported format; the example is 640×480 at 30 frames/s:

```bash
ffmpeg -f v4l2 -framerate 30 -video_size 640x480 -i "$CAMERA_DEVICE" \
  -an -c:v libx264 -pix_fmt yuv420p -preset ultrafast -tune zerolatency \
  -b:v 3M -maxrate 3M -bufsize 1M -g 30 -f mpegts \
  "udp://10.45.0.1:5000?localaddr=$UE_IP&pkt_size=1316"
```

The destination/host route and explicit sender `localaddr` keep traffic on the private link. The 1316-byte UDP payload fits the recorded 1400-byte MTU with IPv4/UDP headers. See [FFmpeg UDP options](https://ffmpeg.org/ffmpeg-protocols.html#udp). Confirm camera permissions, encoder availability and receiver firewall locally; do not claim this video procedure was demonstrated on 2026-10-05.

## 16. Shutdown

Stop iperf, ffmpeg, ffplay, and any receiver with `Ctrl+C` before releasing the bearer. Let the finite KPM xApp finish and delete its subscription while DU and RIC are available.

`[LAPTOP]` In each UE's own shell, retain the original modem identity and bearer allocation. This guarded reproduction procedure disconnects the selected modem before removing only this run's address and host route; it does not select the first modem or flush an interface:

```bash
cleanup_ue() {
  local current_identity current_modem_kv driver
  [[ -n "$MODEM" && -n "$MODEM_IDENTITY" && -n "$WWAN_IF" && -n "$UE_IP" && -n "$UE_PREFIX" ]] || return 1
  current_modem_kv=$(mmcli -m "$MODEM" -K) || return 1
  current_identity=$(printf '%s\n' "$current_modem_kv" | mm_value modem.generic.device-identifier)
  [[ "$current_identity" = "$MODEM_IDENTITY" ]] || return 1
  printf '%s\n' "$current_modem_kv" | grep -Fq "$WWAN_IF (net)" || return 1
  sudo mmcli -m "$MODEM" --simple-disconnect || return 1
  driver=$(basename "$(readlink -f "/sys/class/net/$WWAN_IF/device/driver")")
  [[ "$driver" = qmi_wwan ]] || return 1
  if ip -4 route show exact 10.45.0.1/32 dev "$WWAN_IF" | grep -Fq "src $UE_IP"; then
    sudo ip -4 route del 10.45.0.1/32 dev "$WWAN_IF" src "$UE_IP" || return 1
  fi
  if ip -o -4 addr show dev "$WWAN_IF" | awk '{print $4}' | grep -Fxq "$UE_IP/$UE_PREFIX"; then
    sudo ip -4 addr del "$UE_IP/$UE_PREFIX" dev "$WWAN_IF" || return 1
  fi
  printf 'PDU disconnected; the manual address and route for this run are removed.\n'
  ip -br -4 addr show dev "$WWAN_IF"
}
cleanup_ue || printf 'Cleanup is incomplete; check the same modem and interface and any command errors. Do not guess an interface or flush it.\n'
```

If variables were lost or the modem rebooted, reconfirm the original identity/interface and manual address before cleanup; do not select another modem or guess a WWAN device. Confirm the test address is gone. Optional radio disable after successful cleanup, while that RMU remains connected:

`[LAPTOP]`

```bash
sudo mmcli -m "$MODEM" --disable
```

Disconnect the bearer before physically unplugging the RMU. Next, press `Ctrl+C` in the DU terminal and require `Stopping...`; RF transmission ends. Then stop FlexRIC with `Ctrl+C`, followed by CU. Stop DU before RIC so the E2 connection is still available during DU teardown. For orphaned RAN sessions use the inspected-name `pkill -INT -x` method in stage 2. Avoid SIGKILL as routine cleanup.

`[SPARK]` Stop the core sequentially:

```bash
sudo systemctl stop open5gs-amfd
sudo systemctl stop open5gs-smfd
sudo systemctl stop open5gs-upfd
sudo systemctl stop open5gs-nssfd
sudo systemctl stop open5gs-pcfd
sudo systemctl stop open5gs-ausfd
sudo systemctl stop open5gs-udmd
sudo systemctl stop open5gs-udrd
sudo systemctl stop open5gs-scpd
sudo systemctl stop open5gs-nrfd
```

`[SPARK]` For a **full Open5GS shutdown**, also stop optional/legacy services if installed:

```bash
sudo systemctl stop open5gs-bsfd open5gs-seppd open5gs-mmed open5gs-hssd open5gs-pcrfd open5gs-sgwcd open5gs-sgwud
```

`[SPARK]` WebUI and MongoDB can remain available between experiments; stop them only if desired. Omit WebUI if its unit is absent:

```bash
sudo systemctl stop open5gs-webui
sudo docker stop open5gs-mongo
```

Never remove containers/volumes during normal shutdown. Verify:

`[SPARK]`

```bash
pgrep -a -x odu || true
pgrep -a -x ocu || true
systemctl --no-pager list-units 'open5gs-*' --type=service --state=running
pgrep -a -x nearRT-RIC || true
pgrep -a -x xapp_oran_moni || true
sudo ss -lunp | grep 2152 || true
sudo docker ps --filter name=open5gs-mongo
```

For a full shutdown, no CU/DU/RIC/xApp, running Open5GS services, or their GTP-U listeners remain. Docker is separate: MongoDB may run intentionally or be stopped; the persistent container/volume must remain.

## 17. Acceptance and next session

- [ ] B210 `3271233` at USB 3; performance settings checked.
- [ ] All ten required core functions active; NRF PLMN correct; subscriber type 1.
- [ ] CU N2 and DU F1-C established; expected four GTP-U endpoints present.
- [ ] FlexRIC registers DU1 and KPM function ID 2; xApp subscribes/deletes successfully.
- [ ] RM500Q detects the private SSB and reports NR5G-SA / PLMN `00101` / C5GREG registered.
- [ ] Authentication and packet attachment succeed; IPv4 bearer connected.
- [ ] Actual bearer address/prefix/MTU applied to the laptop modem interface.
- [ ] Private route confirmed; laptop and Spark reach each other; iperf transfers data.
- [ ] Actual UE KPM IDs and metric values received during traffic at the configured period.
- [ ] RF-error growth and test duration recorded; traffic stopped before teardown.

FlexRIC E2 Setup, actual UE KPM reception and subscription/deletion passed on 2026-10-07. Synchronized KPM/application traffic correlation, report timing, cold restart/new-laptop reproduction, longer TCP tests, downlink, UDP loss/jitter, live video and long-duration RF stability remain acceptance work. Preserve and document the working single-link configuration while preparing the second path. Complete Baseline v1 acceptance before active AI steering experiments.

### 17a Next acceptance phase for the provisioned UE pair

Completed: OC011830 / IMSI `001010000000101` and OC011831 / IMSI `001010000000102` personalization, independent K/OPc generation, Milenage authentication, and Quectel SIM/USIM reads. SIM2 was also checked in the second physical modem. This does not extend the older baseline's registration, user-plane, or KPM result to those two new IMSIs.

Next: prepare both correctly matched core records and verify SQN handling; provide and review DU2's configuration, radio serial, cell/SSB/PCI, and distinct DU/network identifiers and addresses; start Open5GS → shared CU → FlexRIC → DU1 → DU2 with their corresponding RF paths; then validate each modem's actual serving cell, `5gnr / 00101 / home / attached`, active IPv4 bearer, and independent WWAN/IP path. Start FlexRIC before either DU; DU1 uses its complete 3660-MHz configuration and DU2 requires its own reviewed E2 settings. The existing launch and cell-lock commands cover DU1 only. IMSI does not select a DU automatically.

Two simultaneous paths, source/interface-specific routing, MPTCP, and per-DU/per-UE metrics for path steering remain unverified. See [Validate two UE paths](../setup/sim_provisioning_and_dual_ue.md#validate-two-ue-paths) for the required evidence and [SIM troubleshooting lessons](../setup/sim_provisioning_and_dual_ue.md#troubleshooting-and-lessons-learned).
