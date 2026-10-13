# Dual UE / Dual DU Quick Start — UL Only

Updated: 2026-10-13. This guide runs two RM500Q modems on one UE laptop through
two B210 DUs, one shared CU/Open5GS, and one FlexRIC RIC. Follow one stage at a
time and stop at a failed check. Use Bash and keep one laptop terminal per UE.

**Current session:** MongoDB, all ten SA services, CU, RIC and DU2 have been
started. DU2 radio/F1/E2 passed; UE2 registration and UL remain pending. If those
processes are still running, continue at [stage 5](#ue2-selection)
without restarting them. Validate UE2 UL first, then add DU1/UE1 for concurrent UL.
For this continuation, still run the subscriber-profile projection in stage 2
before attaching the new cards; those subscriber results remain pending.

The target is **UL only**. Underflow remediation is deferred; count/growth alone
is nonblocking. Failed UL, lost registration/PDU, wrong-cell attachment, crossed
IP paths and missing UL telemetry still keep their respective gates pending.
Dual-UE traffic and the new policy-routing procedure below are not yet live
accepted. See [Plan 3](../plans/dual-ue-du-fr1-channels.md), the
[DU2 runbook](dual_fr1_runbook.md), and [DU2 startup evidence](evidence/2026-10-13_du2_startup/manifest.json).

| Parameter | UE1 / DU1 | UE2 / DU2 |
| --- | --- | --- |
| B210 serial | `3271233` | `328B021` |
| Carrier / ARFCN | 3660 MHz / `644000` | 3600 MHz / `640000` |
| PCI / SSB / SCS / band | `1` / `643680` / 30 kHz / n78 | `2` / `639648` / 30 kHz / n78 |
| DU ID / sector / expected NCI | `1` / `0` / `6733824` | `2` / `1` / `6733825` |
| DU F1 bind | `127.0.10.2` | `127.0.10.3` |
| Intended modem IMEI | `863305041978437` | `863305041980706` |
| Intended SIM IMSI | `001010000000101` | `001010000000102` |
| Spark iperf3 port | `5201` | `5202` |
| Proposed policy table / lookup / guard priority | `151` / `10151` / `10152` | `152` / `10161` / `10162` |
| WWAN / UE IP / modem / bearer / AT port | Discover each run | Discover each run |

Both SSBs were observed in actual DU startup. Recheck startup after changing the
cell configuration/version. Use the observed SSB for the modem lock. Both cells
use n78 / 20 MHz / 30 kHz, PLMN `00101`, TAC 7, SST 1 and DNN `internet`.

## 1. Spark diagnostics — cold-start radio and config checks

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
[Spark stage 2](spark_quick_commands.md#2-restore-performance-settings-after-reboot).

## 2. Spark diagnostics — MongoDB, subscribers and 5GC

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
for (const imsi of ["001010000000101", "001010000000102"]) {
  const rows = subscribers.find({imsi}, {_id:0,imsi:1,slice:1}).toArray();
  const sessions = rows.length === 1 ? (rows[0].slice || [])
    .filter(s => s.sst === 1).flatMap(s => s.session || [])
    .filter(s => s.name === "internet" && s.type === 1) : [];
  const ok = rows.length === 1 && sessions.length === 1;
  print(imsi + ": " + (ok ? "OK (SST 1, internet, IPv4)" : "FAIL (record/session)"));
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
```

Require `10/10`; `ogstun` must be UP, MTU 1400, address `10.45.0.1/16`, with the
private route through `ogstun`. Detailed repair is in the
[full runbook](full_reproduction_runbook.md#7-start-only-the-required-5gc-functions).

## 3. Spark — CU and RIC in separate foreground terminals

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

## 4. Spark — start DU2 first

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

Keep DU1 stopped for this first UE2 registration/UL test. CU, RIC and DU2 have
already passed this stage in the current session.

<a id="ue2-selection"></a>

## 5. UE laptop — select UE2 by modem and SIM identity

Tools: ModemManager, libqmi-utils, minicom, iproute2, iperf3 and Python 3. For a
new laptop, use [UE tool installation](ue_laptop_quick_commands.md#1-install-tools-and-select-the-modem).
Open a **fresh UE2 Bash terminal**. Use this same terminal through bearer/routing/
traffic/cleanup. Later repeat in another fresh terminal for UE1, changing `UE=2`
to `UE=1`. This block reads identity only:

```bash
UE=2
case "$UE" in
  1) EXPECTED_IMEI=863305041978437; EXPECTED_IMSI=001010000000101
     ROUTE_TABLE=151; RULE_PREF=10151; GUARD_PREF=10152; IPERF_PORT=5201 ;;
  2) EXPECTED_IMEI=863305041980706; EXPECTED_IMSI=001010000000102
     ROUTE_TABLE=152; RULE_PREF=10161; GUARD_PREF=10162; IPERF_PORT=5202 ;;
esac
UE_RUN=$(mktemp -d /tmp/falcon-ue${UE}.XXXXXXXX)
printf 'UE run directory: %s\n' "$UE_RUN"
mm_value() {
  awk -F ':' -v key="$1" '
    { field=$1; gsub(/^[ \t]+|[ \t]+$/, "", field) }
    field==key { sub(/^[^:]*:[ \t]*/, ""); sub(/[ \t]+$/, ""); print; exit }
  '
}
select_ue() {
  [[ -z "${BEARER:-}" && -z "${WWAN_IF:-}" ]] || return 1
  mmcli -L || return 1
  read -r -p 'Modem number from the list: ' MODEM_ID
  [[ "$MODEM_ID" =~ ^[0-9]+$ ]] || return 1
  MODEM=/org/freedesktop/ModemManager1/Modem/$MODEM_ID
  MODEM_KV=$(mmcli -m "$MODEM" -K) || return 1
  [[ "$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.equipment-identifier)" = "$EXPECTED_IMEI" ]] || return 1
  MODEM_IDENTITY=$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.device-identifier)
  [[ -n "$MODEM_IDENTITY" && "$MODEM_IDENTITY" != -- ]] || return 1
  SIM_PATH=$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.sim)
  [[ "$SIM_PATH" =~ ^/org/freedesktop/ModemManager1/SIM/[0-9]+$ ]] || return 1
  SIM_KV=$(mmcli -i "$SIM_PATH" -K) || return 1
  [[ "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.active)" = yes ]] || return 1
  [[ "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.imsi)" = "$EXPECTED_IMSI" ]] || return 1
  printf 'UE%s modem=%s IMEI=%s IMSI=%s\n' "$UE" "$MODEM" "$EXPECTED_IMEI" "$EXPECTED_IMSI"
  mmcli -m "$MODEM"
}
select_ue || printf 'FAIL: modem/SIM selection; stop here.\n'
```

Require the intended IMEI/IMSI. Use the selected modem's real QMI port for the
[USIM readiness check](ue_laptop_quick_commands.md#1a-read-the-inserted-sim-and-usim-state).
If disabled, enable only this selected modem with `sudo mmcli -m "$MODEM" --enable`.
If its SIM is unreadable, resolve that first and repeat identity selection.

## 6. UE laptop — AT communication and cell lock

Read the selected modem's ports and inspect `/dev/serial/by-path/` when ModemManager
omits working AT ports. Select that modem's actual AT port; tty numbering changes
when two modems are present.

```bash
mmcli -m "$MODEM"
ls -l /dev/serial/by-path/
read -r -p 'Selected modem AT device, for example /dev/ttyUSB6: ' AT_PORT
sudo minicom -D "$AT_PORT" -b 115200
```

**Inside minicom, not Bash:** send `AT`, then `AT+CIMI`. Require `OK` and this
terminal's expected IMSI before changing preferences. For UE2:

```text
AT
AT+CIMI
AT+QNWPREFCFG="mode_pref",NR5G
AT+QNWPREFCFG="mode_pref"
AT+QNWPREFCFG="nr5g_disable_mode",2
AT+QNWPREFCFG="nr5g_disable_mode"
AT+QNWPREFCFG="nr5g_band"
AT+QNWLOCK="common/5g",2,639648,30,78
AT+QNWLOCK="common/5g"
AT+QENG="servingcell"
AT+C5GREG?
```

For UE1, use the same sequence with IMSI `001010000000101` and this lock:

```text
AT+QNWLOCK="common/5g",1,643680,30,78
```

Require configuration writes `OK`, n78 enabled, lock readback matching the intended
PCI/SSB, and serving cell `NR5G-SA / 001,01` on that cell. Require
`+C5GREG: 0,1` and corroborate with ModemManager below. Exit minicom with `Ctrl+A`,
then `X`. Recheck identity/lock after reconnecting or rebooting the modem.

## 7. UE laptop — registration, IPv4 PDU and actual bearer

```bash
mmcli -m "$MODEM" -K | awk '
  /modem\.generic\.(state|access-technologies)/ ||
  /modem\.3gpp\.(operator-code|registration-state|packet-service-state)/ {print}
'
```

Require `5gnr / 00101 / home / attached`. Then:

```bash
sudo mmcli -m "$MODEM" --simple-connect="apn=internet,ip-type=ipv4"
read_ue_bearer() {
  local path details
  local -a matches=()
  MODEM_KV=$(mmcli -m "$MODEM" -K) || return 1
  [[ "$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.device-identifier)" = "$MODEM_IDENTITY" ]] || return 1
  for path in $(printf '%s\n' "$MODEM_KV" | grep -oE '/org/freedesktop/ModemManager1/Bearer/[0-9]+' | sort -u); do
    details=$(mmcli -b "$path" -K) || return 1
    if [[ "$(printf '%s\n' "$details" | mm_value bearer.status.connected)" = yes &&
          "$(printf '%s\n' "$details" | mm_value bearer.properties.apn)" = internet ]]; then
      matches+=("$path")
    fi
  done
  [[ ${#matches[@]} -eq 1 ]] || return 1
  BEARER=${matches[0]}
  BEARER_KV=$(mmcli -b "$BEARER" -K) || return 1
  [[ "$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.suspended)" = no &&
     "$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.method)" = static ]] || return 1
  WWAN_IF=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.interface)
  UE_IP=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.address)
  UE_PREFIX=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.prefix)
  UE_MTU=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.mtu)
  printf 'UE%s bearer=%s interface=%s IPv4=%s/%s mtu=%s\n' "$UE" "$BEARER" "$WWAN_IF" "$UE_IP" "$UE_PREFIX" "$UE_MTU"
}
read_ue_bearer || printf 'FAIL: no unique usable IPv4 bearer; stop here.\n'
```

Require a distinct IP and dedicated WWAN for each UE. Preserve the actual modem,
SIM, bearer, interface and address in that UE's terminal. Authentication failures
need subscriber/SIM diagnosis before any IP routing changes.

## 8. UE laptop — install a dedicated source-policy path

Use this recipe for both the initial single-UE test and the later dual test. It
adds only a source-specific path to Spark `10.45.0.1`, leaving management defaults
intact. Resolve WWAN ownership with NetworkManager first; this recipe requires
a dedicated QMI interface with no existing IPv4 address or default route.

Inspect current rules and the role's proposed table first:

```bash
ip -4 rule show
ip -4 route show table "$ROUTE_TABLE"
ip -4 route show default
```

An absent table may report `FIB table does not exist`; that means it has no routes.
The table and both priorities must be unused. If other policy rules already
match this UE source before the proposed priority, review them before proceeding.
The following preflight rejects collisions and matching earlier rules:

```bash
python3 - "$UE_IP" "$UE_PREFIX" "$UE_MTU" "$ROUTE_TABLE" "$RULE_PREF" "$GUARD_PREF" <<'PY'
import ipaddress, json, pathlib, subprocess, sys
ip, prefix, mtu, table, lookup, guard = sys.argv[1:]
source = ipaddress.IPv4Address(ip)
ipaddress.IPv4Interface(ip + '/' + prefix)
assert source in ipaddress.IPv4Network('10.45.0.0/16') and ip != '10.45.0.1'
assert 576 <= int(mtu) <= 65535
aliases = {'local': 255, 'main': 254, 'default': 253}
for path in [pathlib.Path('/etc/iproute2/rt_tables'), *pathlib.Path('/etc/iproute2/rt_tables.d').glob('*')]:
    if not path.is_file(): continue
    for line in path.read_text().splitlines():
        fields = line.split('#', 1)[0].split()
        if len(fields) == 2 and fields[0].isdigit(): aliases[fields[1]] = int(fields[0])
def table_number(value):
    return int(value) if str(value).isdigit() else aliases.get(value)
def contains(selector, value):
    return selector in (None, 'all') or value in ipaddress.IPv4Network(selector, strict=False)
rules = json.loads(subprocess.check_output(['ip', '-j', '-4', 'rule', 'show']))
for rule in rules:
    priority = int(rule.get('priority', 0))
    assert priority not in (int(lookup), int(guard)), 'Rule priority already occupied'
    assert table_number(rule.get('table')) != int(table), 'Routing table already referenced'
    if priority < int(lookup) and not (priority == 0 and table_number(rule.get('table')) == 255):
        assert not rule.get('not') and 'not' not in rule.get('flags', []), 'Inverted earlier policy rule requires review'
        assert not (contains(rule.get('src'), source) and contains(rule.get('dst'), ipaddress.IPv4Address('10.45.0.1'))), 'Matching earlier policy rule requires review'
routes = subprocess.run(['ip', '-j', '-4', 'route', 'show', 'table', table], capture_output=True, text=True)
if routes.returncode:
    assert 'FIB table does not exist' in routes.stderr, routes.stderr
else:
    assert not json.loads(routes.stdout), 'Routing table already has routes'
print('Policy slots and IPv4 parameters: OK')
PY
```

Require `OK`. Check the dedicated interface, capture rollback values, and install
the guard **before** exposing the source address. This is a new procedure; on a
partial failure, stop and use stage 12 with the captured `PATH_*` values.

```bash
prepare_dual_path() {
  local mgmt_dev
  [[ "$WWAN_IF" =~ ^(wwan|wwp|rmnet)[[:alnum:]_.-]*$ ]] || return 1
  [[ "$(basename "$(readlink -f "/sys/class/net/$WWAN_IF/device/driver")")" = qmi_wwan ]] || return 1
  printf '%s\n' "$MODEM_KV" | grep -Fq "$WWAN_IF (net)" || return 1
  [[ -z "$(ip -o -4 addr show dev "$WWAN_IF")" ]] || return 1
  [[ -z "$(ip -4 route show default dev "$WWAN_IF")" &&
     -z "$(ip -6 route show default dev "$WWAN_IF")" ]] || return 1
  [[ -z "$(ip -o -4 addr show | awk -v wanted="$UE_IP" '{split($4,a,"/"); if(a[1]==wanted) print}')" ]] || return 1
  [[ -z "$(ip -o -4 addr show | awk '{split($4,a,"/"); if(a[1]=="10.45.0.1") print}')" ]] || return 1
  if [[ -n "${SSH_CONNECTION:-}" ]]; then
    mgmt_dev=$(ip route get "${SSH_CONNECTION%% *}" | awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}')
    [[ -n "$mgmt_dev" && "$mgmt_dev" != "$WWAN_IF" ]] || return 1
  fi
  PATH_IP=$UE_IP; PATH_CIDR=$UE_IP/$UE_PREFIX; PATH_IF=$WWAN_IF
  PATH_TABLE=$ROUTE_TABLE; PATH_RULE=$RULE_PREF; PATH_GUARD=$GUARD_PREF
  PATH_OLD_MTU=$(cat "/sys/class/net/$PATH_IF/mtu") || return 1
  PATH_WAS_UP=no
  ip -o link show dev "$PATH_IF" | grep -Eq '(<|,)UP(,|>)' && PATH_WAS_UP=yes
  declare -p MODEM MODEM_IDENTITY EXPECTED_IMEI EXPECTED_IMSI BEARER \
    PATH_IP PATH_CIDR PATH_IF PATH_TABLE PATH_RULE PATH_GUARD PATH_OLD_MTU PATH_WAS_UP \
    > "$UE_RUN/route-state.txt"
  sudo ip -4 rule add pref "$PATH_GUARD" from "$PATH_IP/32" to 10.45.0.1/32 type unreachable &&
  sudo ip link set dev "$PATH_IF" mtu "$UE_MTU" up &&
  sudo ip -4 addr add "$PATH_CIDR" dev "$PATH_IF" noprefixroute &&
  sudo ip -4 route add table "$PATH_TABLE" 10.45.0.1/32 dev "$PATH_IF" src "$PATH_IP" &&
  sudo ip -4 rule add pref "$PATH_RULE" from "$PATH_IP/32" to 10.45.0.1/32 lookup "$PATH_TABLE"
}
if prepare_dual_path; then
  ip -4 route get 10.45.0.1 from "$PATH_IP"
  ip -4 route show default
  ping -q -I "$PATH_IP" -c 5 10.45.0.1
else
  printf 'FAIL: path setup incomplete; stop and clean only this run.\n'
fi
```

Require the route to use `PATH_IF` with `PATH_IP`, successful private ping, and
unchanged management defaults. Save the `PATH_*` values until cleanup even if a
later bearer read changes `UE_IP`. If reverse-path filtering rejects return
traffic, inspect the selected WWAN settings using Plan 3 Step 8; record any
reviewed per-interface change and its rollback instead of changing all interfaces.

## 9. Spark + UE laptop — verify UE2 UL, then add UE1

**Spark UE2 iperf server terminal:**

```bash
iperf3 -s -B 10.45.0.1 -p 5202
```

**UE2 laptop terminal:**

```bash
TZ=America/New_York date --iso-8601=seconds | tee "$UE_RUN/ul-solo-start.txt"
set -o pipefail
iperf3 -c 10.45.0.1 -p "$IPERF_PORT" -B "$PATH_IP" \
  -t 60 -i 1 --get-server-output -J | tee "$UE_RUN/ul-solo.json"
TZ=America/New_York date --iso-8601=seconds | tee "$UE_RUN/ul-solo-end.txt"
```

Require a completed receiver summary and a stable SA/PDU path. Record bitrate
and sender retransmissions; this is an UL test. During this first UE2 UL window,
run the stage 11 monitor on Spark with only DU2 present and require reports plus
normal subscription/deletion/exit. After UE2 passes, start DU1 in
its own **Spark DU1 terminal**, retaining CU/RIC/DU2:

```bash
cd /home/nyu/ocudu
DU1_RUN=$(mktemp -d /tmp/falcon-du1-3660.XXXXXXXX)
printf 'DU1 run directory: %s\n' "$DU1_RUN"
set -o pipefail
sudo stdbuf -oL -eL build/apps/du_split_8/odu \
  -c configs/du1_b210_n78_3660mhz.yml \
  log --filename "$DU1_RUN/du.log" 2>&1 | tee "$DU1_RUN/startup.log"
```

Require radio `3271233`, USB 3, PCI 1 / carrier `644000` / SSB `643680`, F1/E2
completed and RIC DU ID 1. CU must now hold DU IDs 1 and 2 with distinct cells;
verify both actual NR CGIs in the CU evidence. Repeat stages 5–8 for UE1 in a
fresh laptop terminal with `UE=1`, confirming SIM1 and the UE1 lock.

**Spark UE1 iperf server terminal:**

```bash
iperf3 -s -B 10.45.0.1 -p 5201
```

Repeat the solo UL command in the UE1 terminal and label this case UE1 UL / DU2
idle. Before simultaneous UL, require
different modem/SIM/bearer/WWAN/IP identities and two correct source-policy routes.

## 10. Both UE terminals — simultaneous UL and path guards

Run this block in each UE's own terminal at approximately the same time:

```bash
ip -4 route get 10.45.0.1 from "$PATH_IP"
TZ=America/New_York date --iso-8601=seconds | tee "$UE_RUN/ul-dual-start.txt"
iperf3 -c 10.45.0.1 -p "$IPERF_PORT" -B "$PATH_IP" \
  -t 60 -i 1 --get-server-output -J | tee "$UE_RUN/ul-dual.json"
TZ=America/New_York date --iso-8601=seconds | tee "$UE_RUN/ul-dual-end.txt"
```

Retain separate UE1/UE2 receiver summaries and identities. For full Plan 3 UL
coexistence, repeat each solo/other-DU-idle/concurrent case three times.

For each RF-isolated case, stop the other DU while retaining CU/RIC and the tested
link. Restore both DUs afterward, refresh the affected UE's registration/bearer/
route ledger, and verify it before the next concurrent case.

Add UL UDP at a controlled rate no greater than 70% of each measured solo capacity:

```bash
read -r -p 'Measured controlled UL rate, for example 8M: ' UL_OFFERED_RATE
iperf3 -c 10.45.0.1 -p "$IPERF_PORT" -B "$PATH_IP" \
  -u -b "$UL_OFFERED_RATE" -t 60 -i 1 --get-server-output -J | tee "$UE_RUN/ul-udp.json"
```

At the same offered load, require receiver goodput at least 90% of its isolated
result and UDP loss at most 1%. Retain jitter, cell/SA/PDU continuity and the
planned PHY observations. No application DL or mixed-direction trials are required.
Use distinct filenames for subsequent repetitions.

Before declaring independent paths, stop traffic on one UE and remove only its
table route. Keep the other UE's ping/UL running. In the affected terminal:

```bash
sudo ip -4 route del table "$PATH_TABLE" 10.45.0.1/32 dev "$PATH_IF" src "$PATH_IP"
if ip -4 route get 10.45.0.1 from "$PATH_IP"; then
  printf 'FAIL: source fell through to another route; do not accept this path.\n'
else
  printf 'Source guard: OK (private destination unreachable).\n'
fi
sudo ip -4 route add table "$PATH_TABLE" 10.45.0.1/32 dev "$PATH_IF" src "$PATH_IP"
ip -4 route get 10.45.0.1 from "$PATH_IP"
```

Repeat for the other UE. Confirm the unaffected link survives. Verify counters/
captures on the intended WWAN and repeat after an actual bearer disconnect/
reattachment with refreshed identities. A route lookup alone is not packet-path
acceptance.

## 11. Spark xApp terminal — KPM smoke check and remaining attribution gate

Start the monitor after RIC has registered the intended DU nodes and while UL is
active. For the initial DU2 test it should discover one DU; for the later dual
test it should discover both DU IDs 1 and 2.

```bash
XAPP_RUN=$(mktemp -d /tmp/falcon-dual-kpm.XXXXXXXX)
set -o pipefail
stdbuf -oL -eL /usr/local/bin/flexric/xApp/c/xapp_oran_moni \
  -c /usr/local/etc/flexric/xapp_oran_sm.conf 2>&1 | tee "$XAPP_RUN/kpm.log"
XAPP_STATUS=${PIPESTATUS[0]}
printf 'xApp exit: %s; evidence: %s\n' "$XAPP_STATUS" "$XAPP_RUN"
```

Let the finite stock run finish and delete its subscriptions. Require exit 0,
the success marker, UE reports, numeric `DRB.UEThpUl` / `RRU.PrbTotUl`, and
`report_age_us`. DL values remain observations; report age is not application RTT.
Repeat completed runs during UL to accumulate at least 30 real rows per link.

The installed monitor prints the common gNB ID without DU ID on each KPM row.
With both DUs active, this is a transport smoke check; rows cannot be accepted
as per-DU telemetry solely from that output. Plan 3 Step 5's diagnostic patch,
DU-only config and lifecycle/attribution checks remain pending. Full acceptance
requires each row's full DU/UE identity correlated to modem/SIM/cell/bearer and
the traffic window; maintain the mapping after UE ID changes.

## 12. Cleanup and retained acceptance evidence

Stop iperf clients first. Let the finite xApp finish subscription deletion. In
each UE terminal, verify the same modem identity and its recorded interface:

```bash
CURRENT_MODEM_KV=$(mmcli -m "$MODEM" -K)
printf '%s\n' "$CURRENT_MODEM_KV" | mm_value modem.generic.device-identifier
printf 'Expected identity: %s; recorded WWAN: %s\n' "$MODEM_IDENTITY" "$PATH_IF"
```

Require the same identity and interface ownership. Then disconnect that modem's
PDU and remove only the captured run entries. If setup partially failed, an
already-absent entry needs no deletion; inspect it and continue with remaining
owned entries. If the interface disappeared, preserve the guard until the source
address is confirmed absent.

```bash
sudo mmcli -m "$MODEM" --simple-disconnect
sudo ip -4 rule del pref "$PATH_RULE" from "$PATH_IP/32" to 10.45.0.1/32 lookup "$PATH_TABLE"
sudo ip -4 route del table "$PATH_TABLE" 10.45.0.1/32 dev "$PATH_IF" src "$PATH_IP"
sudo ip -4 addr del "$PATH_CIDR" dev "$PATH_IF"
```

Only after the run's source address is absent on the laptop, remove its guard
and restore the recorded interface settings:

```bash
if [[ -z "$(ip -o -4 addr show | awk -v wanted="$PATH_IP" '{split($4,a,"/"); if(a[1]==wanted) print}')" ]]; then
  sudo ip -4 rule del pref "$PATH_GUARD" from "$PATH_IP/32" to 10.45.0.1/32 type unreachable
  sudo ip link set dev "$PATH_IF" mtu "$PATH_OLD_MTU"
  if [[ "$PATH_WAS_UP" = no ]]; then sudo ip link set dev "$PATH_IF" down; fi
else
  printf 'FAIL: source address remains; keep the guard and inspect cleanup.\n'
fi
ip -4 rule show
ip -4 route show default
```

Retain management Wi-Fi and the other UE's entries. Never flush shared routing
tables/interfaces. If variables were lost, inspect `route-state.txt` and the
actual modem/interface before reconstructing cleanup commands.

Stop Spark iperf servers, then each recorded DU, RIC, CU and the ten SA services
as needed. Optional MongoDB shutdown preserves its container/data. Follow
[Spark shutdown](spark_quick_commands.md#8-shut-down) for the core sequence.

Before marking the dual UL baseline accepted, retain both configs/hashes and
startup records, actual subscriber/modem/SIM/cell/bearer/IP/WWAN/UE-F1AP mapping,
UL results and time windows, path-guard/survivor evidence, per-DU KPM lifecycle/
rows, and reattachment/restart/cold-start results. Keep raw security-bearing logs
outside Git and review excerpts before saving them. Until those gates pass,
report **DU2 startup passed; dual-UE UL acceptance pending**.
