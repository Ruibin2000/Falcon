# Dual UE Laptop Quick Commands — UL Only

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

Run all commands in this file on the UE laptop. Use Bash, one terminal per UE
for modem/bearer/path variables, and stop at failed checks. Spark startup, servers
and KPM capture are in [Dual UE Spark Quick Commands](dual_ue_spark_quick_commands.md).

Follow the complete **UE1 sequence first**, then the complete **UE2 sequence**
in another fresh Bash terminal. Both DUs and both Spark servers must already be
running; Spark startup is in the paired booklet. Keep UE1's verified PDU/path
active while preparing UE2. After a power/reconnection event, repeat the affected
role's identity, lock/cell, bearer, old-path cleanup and new-path verification.

The latest UE2 report is bearer 5 / `wwan0` / `10.46.0.3/29` / MTU 1400;
old rules 10161/10162 still used `10.46.0.2`, so restored routing remains pending.
The earlier concurrent launcher's printed exit codes/time bounds were invalid
because its `wait`/`printf` lost variable expansions. Preserve its logs and use
section 3's Python launcher after both role paths pass.

## 0. Role assignments

On a new laptop, install the required tools:

```bash
sudo apt update
sudo apt install -y modemmanager libqmi-utils minicom iproute2 iperf3 usbutils python3
sudo systemctl enable --now ModemManager
```

| Parameter | UE1 / DU1 | UE2 / DU2 |
| --- | --- | --- |
| Carrier / ARFCN | 3660 MHz / `644000` | 3600 MHz / `640000` |
| PCI / SSB / SCS / band | `1` / `643680` / 30 kHz / n78 | `2` / `639648` / 30 kHz / n78 |
| DU ID / sector / expected NCI | `1` / `0` / `6733824` | `2` / `1` / `6733825` |
| Intended modem IMEI | `863305041978437` | `863305041980706` |
| Intended SIM IMSI | `001010000000101` | `001010000000102` |
| DNN / APN | `internet` | `internet2` |
| Expected UE IPv4 pool | `10.45.0.0/16` | `10.46.0.0/16` |
| Spark service IP | `10.45.0.1` | `10.46.0.1` |
| Spark iperf3 port | `5201` | `5202` |
| Proposed policy table / lookup / guard priority | `151` / `10151` / `10152` | `152` / `10161` / `10162` |
| WWAN / UE IP / modem / bearer / AT port | Discover each run | Discover each run |

| Observed before the latest modem power cycle | UE1 | UE2 |
| --- | --- | --- |
| Modem / SIM / bearer | `6` / `6` / `4` | `5` / `5` / `3` |
| WWAN / IPv4 | `wwan1` / `10.45.0.2/30` | `wwan0` / `10.46.0.2/30` |
| AT port / USB device | `/dev/ttyUSB6` / `4-4` | `/dev/ttyUSB2` / `4-3` |
| Bearer gateway / MTU | `10.45.0.1` / `1400` | `10.46.0.1` / `1400` |

Rediscover these dynamic values after modem restart/reconnection. Both cells use
PLMN `00101`, TAC 7 and SST 1. DNN selects the UE pool; cell lock selects the DU.
The latest UE2 readback is bearer 5 / `10.46.0.3/29` on `wwan0`; revalidate its
cell, gateway and host configuration before testing. UE1's previous values also
need fresh confirmation before the next dual test.

Treat locks as needing restoration after modem power/reconnection: the
operator reported a lock query of `0`, with affected role unspecified. See the
[power-cycle observation](evidence/2026-10-13_modem_lock_power_cycle/manifest.json).
A generic [Quectel support response](https://forums.quectel.com/t/rmu500-ek-to-prevent-from-handover/11554)
describes NV saving, but this device's actual readback is the operational gate.
A correct APN/subnet does not bind a SIM to a DU in the shared PLMN. Require the
exact lock, actual PCI/NCI/SSB and SA before PDU/routes; recheck the cell after
PDU establishment and before UL. Controlled cold-start restoration remains pending.

<a id="ue1-start"></a>

## 1. UE1 — complete sequence in its own terminal

Keep both Spark DUs running. Open a fresh UE1 Bash terminal and follow
1.1–1.7 in order. Keep this terminal and its variables for later tests/cleanup.

### 1.1. Select UE1 automatically by IMEI and verify its SIM

This block reads identity only and requires one IMEI match plus the active
SIM IMSI `001010000000101`. It discovers the current modem number:

```bash
UE=1
EXPECTED_IMEI=863305041978437
EXPECTED_IMSI=001010000000101
APN=internet
UE_SUBNET=10.45.0.0/16
SERVER_IP=10.45.0.1
ROUTE_TABLE=151
RULE_PREF=10151
GUARD_PREF=10152
IPERF_PORT=5201
UE_RUN=$(mktemp -d /tmp/falcon-ue${UE}.XXXXXXXX)
printf 'UE run directory: %s\n' "$UE_RUN"
mm_value() {
  awk -F ':' -v key="$1" '
    { field=$1; gsub(/^[ \t]+|[ \t]+$/, "", field) }
    field==key { sub(/^[^:]*:[ \t]*/, ""); sub(/[ \t]+$/, ""); print; exit }
  '
}
select_ue() {
  local listing path details model imei identity selected_identity
  local -a candidates=() matches=()
  [[ -z "${BEARER:-}" && -z "${WWAN_IF:-}" ]] || return 1
  MODEM=""; MODEM_KV=""; MODEM_IDENTITY=""; SIM_PATH=""; SIM_KV=""
  listing=$(mmcli -L) || return 1
  mapfile -t candidates < <(printf '%s\n' "$listing" |
    grep -oE '/org/freedesktop/ModemManager1/Modem/[0-9]+' | sort -u)
  for path in "${candidates[@]}"; do
    details=$(mmcli -m "$path" -K) || return 1
    model=$(printf '%s\n' "$details" | mm_value modem.generic.model)
    imei=$(printf '%s\n' "$details" | mm_value modem.generic.equipment-identifier)
    identity=$(printf '%s\n' "$details" | mm_value modem.generic.device-identifier)
    if [[ "$model" = *RM500Q* && "$imei" = "$EXPECTED_IMEI" &&
          -n "$identity" && "$identity" != -- ]]; then
      matches+=("$path")
      selected_identity=$identity
    fi
  done
  if [[ ${#matches[@]} -ne 1 ]]; then
    printf 'FAIL: IMEI %s matched %s modems; inspect USB/identity.\n' \
      "$EXPECTED_IMEI" "${#matches[@]}"
    return 1
  fi
  MODEM=${matches[0]}
  MODEM_KV=$(mmcli -m "$MODEM" -K) || return 1
  [[ "$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.equipment-identifier)" = "$EXPECTED_IMEI" ]] || return 1
  MODEM_IDENTITY=$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.device-identifier)
  [[ "$MODEM_IDENTITY" = "$selected_identity" ]] || return 1
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

Stop at a failed identity/SIM check. If the selected modem is disabled,
run `sudo mmcli -m "$MODEM" --enable` and repeat identity validation. For USIM
readiness, use its actual QMI port and the [USIM check](ue_laptop_quick_commands.md#1a-read-the-inserted-sim-and-usim-state).

<a id="ue1-cell-lock"></a>

### 1.2. Verify the AT port and restore the DU1 lock

Read the selected modem's device/ports and match them to the USB serial links.
AT port numbers change on reconnect; confirm `AT+CIMI` before any write.

```bash
mmcli -m "$MODEM"
ls -l /dev/serial/by-path/
read -r -p 'Selected UE1 AT device, for example /dev/ttyUSB6: ' AT_PORT
sudo minicom -D "$AT_PORT" -b 115200
```

Inside minicom, first read:

```text
AT
AT+CIMI
AT+QNWLOCK="common/5g"
AT+QENG="servingcell"
AT+C5GREG?
```

Require IMSI `001010000000101`. If the lock and actual cell already match, continue
to 1.3. Otherwise set NR5G-SA preferences and this role's exact lock:

```text
AT+QNWPREFCFG="mode_pref",NR5G
AT+QNWPREFCFG="mode_pref"
AT+QNWPREFCFG="nr5g_disable_mode",2
AT+QNWPREFCFG="nr5g_disable_mode"
AT+QNWPREFCFG="nr5g_band"
AT+QNWLOCK="common/5g",1,643680,30,78
AT+QNWLOCK="common/5g"
AT+QENG="servingcell"
AT+C5GREG?
```

Require writes `OK`, lock `1,643680,30,78`, NR5G-SA / `001,01` / TAC 7,
PCI `1`, NCI `00066C000`, SSB `643680`, n78 and `+C5GREG: 0,1`.
Exit minicom with Ctrl+A, then X. A correct APN/IP or lock tuple alone does not
prove the actual serving cell. Recheck this cell after PDU establishment and
before UL; stop this role's setup/test if identity or cell differs.

### 1.3. Connect `internet` IPv4 and read the actual bearer

```bash
mmcli -m "$MODEM" -K | awk '
  /modem\.generic\.(state|access-technologies)/ ||
  /modem\.3gpp\.(operator-code|registration-state|packet-service-state)/ {print}
'
```

Require `5gnr / 00101 / home / attached`. Then connect and discover its bearer:

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
          "$(printf '%s\n' "$details" | mm_value bearer.properties.apn)" = "$APN" ]]; then
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
if read_ue_bearer; then
  PATH_IP=$UE_IP; PATH_CIDR=$UE_IP/$UE_PREFIX; PATH_IF=$WWAN_IF
  PATH_SERVER=10.45.0.1; PATH_TABLE=151; PATH_RULE=10151; PATH_GUARD=10152
else
  printf 'FAIL: no unique usable IPv4 bearer; stop here.\n'
fi
```

Require APN `internet`, an address in `10.45.0.0/16`, static IPv4, a non-suspended
connected bearer and the modem's own dedicated interface. Keep the actual
`UE_IP`, `UE_PREFIX`, `UE_MTU` and `WWAN_IF`; never substitute an old allocation.
Recheck 1.2's cell before rebuilding the host path. The fresh `PATH_*`
address/table fields also support a verified existing path; original rollback
MTU/state must come from its recorded ledger, not the current configured link.

<a id="ue1-clean-old-path"></a>

### 1.4. Inspect and remove only UE1's old path

Stop this UE's test traffic. Keep a newly identity/cell-verified PDU connected
during a host-only rebind. Inspect old addresses/rules/routes first:

```bash
ip -o -4 addr show
ip -4 rule show
ip -4 route show table 151
ip -4 route show default
```

Table `151` belongs to the laptop. An absent table can report
`FIB table does not exist`; old rules may remain after USB/interface loss.
Record the old path separately from the new bearer. If the current path already
uses the verified new allocation and works, skip cleanup/installation and go to
1.6. Otherwise remove only this role's recorded entries.

The following cleanup uses the retained old session values. If its old IP,
prefix or interface differs from inspected state, reconstruct the owned values
before editing the commands. It skips absent entries, refuses a wrong modem or
old address/interface/prefix, and keeps the guard until the old address is absent
everywhere. Preserve the other UE and Wi-Fi; never flush shared routing tables.

```bash
cleanup_old_ue1_path() {
  local current
  current=$(mmcli -m "$MODEM" -K) || return 1
  [[ "$(printf '%s\n' "$current" | mm_value modem.generic.equipment-identifier)" = 863305041978437 ]] || return 1
  if ip -o -4 addr show | grep -Eq 'inet 10[.]45[.]0[.]2/'; then
    ip -o -4 addr show dev wwan1 | grep -Fq 'inet 10.45.0.2/30 ' || {
      printf 'STOP: old UE1 address/interface/prefix differs; inspect ownership.\n'; return 1;
    }
    printf '%s\n' "$current" | grep -Fq 'wwan1 (net)' || return 1
  fi
  if ip -4 rule show | grep -Eq '^10151:[[:space:]]+from 10[.]45[.]0[.]2(/32)? to 10[.]45[.]0[.]1(/32)? lookup 151([[:space:]]|$)'; then
    sudo ip -4 rule del pref 10151 from 10.45.0.2/32 to 10.45.0.1/32 lookup 151 || return 1
  fi
  if ip -4 route show table 151 10.45.0.1/32 2>/dev/null | grep -Eq '^10[.]45[.]0[.]1(/32)? dev wwan1 .*src 10[.]45[.]0[.]2([[:space:]]|$)'; then
    sudo ip -4 route del table 151 10.45.0.1/32 dev wwan1 src 10.45.0.2 || return 1
  fi
  if ip -o -4 addr show dev wwan1 2>/dev/null | grep -Fq 'inet 10.45.0.2/30 '; then
    sudo ip -4 addr del 10.45.0.2/30 dev wwan1 || return 1
  fi
  if ip -o -4 addr show | grep -Eq 'inet 10[.]45[.]0[.]2/'; then
    printf 'STOP: old UE1 source remains; keep its guard.\n'; return 1
  fi
  if ip -4 rule show | grep -Eq '^10152:[[:space:]]+from 10[.]45[.]0[.]2(/32)? to 10[.]45[.]0[.]1(/32)? unreachable([[:space:]]|$)'; then
    sudo ip -4 rule del pref 10152 from 10.45.0.2/32 to 10.45.0.1/32 type unreachable || return 1
  fi
  printf 'Matching old UE1 entries removed; inspect table 151 and its priorities.\n'
}
cleanup_old_ue1_path
```

<a id="ue1-build-path"></a>

### 1.5. Build UE1's fresh table 151 and rules

Reinspect table `151` and priorities `10151/10152`; require them free
for a new path. Use the just-read bearer IP/prefix/MTU/interface. This preflight
refuses collisions and an earlier matching policy rule:

```bash
python3 - "$UE_IP" "$UE_PREFIX" "$UE_MTU" "$ROUTE_TABLE" "$RULE_PREF" "$GUARD_PREF" "$UE_SUBNET" "$SERVER_IP" <<'PY'
import ipaddress, json, pathlib, subprocess, sys
ip, prefix, mtu, table, lookup, guard, subnet, server = sys.argv[1:]
source = ipaddress.IPv4Address(ip)
destination = ipaddress.IPv4Address(server)
ipaddress.IPv4Interface(ip + '/' + prefix)
assert source in ipaddress.IPv4Network(subnet) and source != destination, 'Wrong UE subnet/address'
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
        assert not (contains(rule.get('src'), source) and contains(rule.get('dst'), destination)), 'Matching earlier policy rule requires review'
routes = subprocess.run(['ip', '-j', '-4', 'route', 'show', 'table', table], capture_output=True, text=True)
if routes.returncode:
    assert 'FIB table does not exist' in routes.stderr, routes.stderr
else:
    assert not json.loads(routes.stdout), 'Routing table already has routes'
print('Policy slots and IPv4 parameters: OK')
PY
```

Require `Policy slots and IPv4 parameters: OK`. Install the source guard before
exposing the source address, and save this run's rollback/ownership values:

```bash
prepare_dual_path() {
  local mgmt_dev
  [[ "$UE" = 1 && "$APN" = internet && "$SERVER_IP" = 10.45.0.1 &&
     "$ROUTE_TABLE" = 151 && "$RULE_PREF" = 10151 && "$GUARD_PREF" = 10152 ]] || return 1
  [[ "$WWAN_IF" =~ ^(wwan|wwp|rmnet)[[:alnum:]_.-]*$ ]] || return 1
  [[ "$(basename "$(readlink -f "/sys/class/net/$WWAN_IF/device/driver")")" = qmi_wwan ]] || return 1
  printf '%s\n' "$MODEM_KV" | grep -Fq "$WWAN_IF (net)" || return 1
  [[ -z "$(ip -o -4 addr show dev "$WWAN_IF")" ]] || return 1
  [[ -z "$(ip -4 route show default dev "$WWAN_IF")" &&
     -z "$(ip -6 route show default dev "$WWAN_IF")" ]] || return 1
  [[ -z "$(ip -o -4 addr show | awk -v wanted="$UE_IP" '{split($4,a,"/"); if(a[1]==wanted) print}')" ]] || return 1
  [[ -z "$(ip -o -4 addr show | awk -v wanted="$SERVER_IP" '{split($4,a,"/"); if(a[1]==wanted) print}')" ]] || return 1
  if [[ -n "${SSH_CONNECTION:-}" ]]; then
    mgmt_dev=$(ip route get "${SSH_CONNECTION%% *}" | awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}')
    [[ -n "$mgmt_dev" && "$mgmt_dev" != "$WWAN_IF" ]] || return 1
  fi
  PATH_IP=$UE_IP; PATH_CIDR=$UE_IP/$UE_PREFIX; PATH_IF=$WWAN_IF
  PATH_SERVER=$SERVER_IP
  PATH_TABLE=$ROUTE_TABLE; PATH_RULE=$RULE_PREF; PATH_GUARD=$GUARD_PREF
  PATH_OLD_MTU=$(cat "/sys/class/net/$PATH_IF/mtu") || return 1
  PATH_WAS_UP=no
  ip -o link show dev "$PATH_IF" | grep -Eq '(<|,)UP(,|>)' && PATH_WAS_UP=yes
  declare -p MODEM MODEM_IDENTITY EXPECTED_IMEI EXPECTED_IMSI BEARER \
    APN UE_SUBNET PATH_SERVER PATH_IP PATH_CIDR PATH_IF PATH_TABLE PATH_RULE PATH_GUARD PATH_OLD_MTU PATH_WAS_UP \
    > "$UE_RUN/route-state.txt"
  sudo ip -4 rule add pref 10152 from "$PATH_IP/32" to 10.45.0.1/32 type unreachable &&
  sudo ip link set dev "$PATH_IF" mtu "$UE_MTU" up &&
  sudo ip -4 addr add "$PATH_CIDR" dev "$PATH_IF" noprefixroute &&
  sudo ip -4 route add table 151 10.45.0.1/32 dev "$PATH_IF" src "$PATH_IP" &&
  sudo ip -4 rule add pref 10151 from "$PATH_IP/32" to 10.45.0.1/32 lookup 151
}
if prepare_dual_path; then
  ip -4 route get 10.45.0.1 from "$PATH_IP"
  ip -4 route show default
  ping -q -I "$PATH_IP" -c 5 "$PATH_SERVER"
else
  printf 'FAIL: path setup incomplete; stop and clean only this run.\n'
fi
```

Stop on a setup failure and preserve `route-state.txt` for precise cleanup.
The setup requires a dedicated QMI interface with no existing IPv4 address or
default route. Resolve unexpected interface ownership before continuing.

### 1.6. Verify table 151, private ping and management routing

```bash
ip -4 rule show
ip -4 route show table 151
ip -4 route get 10.45.0.1 from "$UE_IP"
ping -I "$UE_IP" -c 5 10.45.0.1
ip -4 route show default
```

Require this UE's actual interface and `table 151`, private ping replies,
and the unchanged Wi-Fi default route. Save `PATH_*` values even if a later
bearer allocation changes. Recheck cell/SA after reconnect/reattachment.

### 1.7. Run UE1's 60-second TCP UL, then keep it connected

Wait for Spark's `10.45.0.1:5201` server to show `Server listening`.
Both DUs stay running; the other UE's test traffic stays idle during this case:

```bash
TZ=America/New_York date --iso-8601=seconds | tee "$UE_RUN/ul-solo-start.txt"
set -o pipefail
iperf3 -c 10.45.0.1 -p 5201 -B "$PATH_IP" \
  -t 60 -i 1 --get-server-output -J | tee "$UE_RUN/ul-solo.json"
UL_RC=$?
printf 'pipeline_exit=%d\n' "$UL_RC" | tee "$UE_RUN/ul-solo-exit.txt"
TZ=America/New_York date --iso-8601=seconds | tee "$UE_RUN/ul-solo-end.txt"
```

Require pipeline exit 0 and a completed receiver summary. Record receiver
goodput, sender retransmissions, time bounds and cell/SA/PDU continuity. Keep
this modem, PDU, path, terminal and its Spark server active for the dual test.

Proceed to the UE2 sequence in a different fresh terminal.

<a id="ue2-start"></a>

## 2. UE2 — complete sequence in its own terminal

Keep UE1's verified PDU/path active, with its test traffic idle. Open a new
UE2 Bash terminal and follow 2.1–2.7 in order. Keep both Spark DUs running.

### 2.1. Select UE2 automatically by IMEI and verify its SIM

<a id="ue2-selection"></a>

This block reads identity only and requires one IMEI match plus the active
SIM IMSI `001010000000102`. It discovers the current modem number:

```bash
UE=2
EXPECTED_IMEI=863305041980706
EXPECTED_IMSI=001010000000102
APN=internet2
UE_SUBNET=10.46.0.0/16
SERVER_IP=10.46.0.1
ROUTE_TABLE=152
RULE_PREF=10161
GUARD_PREF=10162
IPERF_PORT=5202
UE_RUN=$(mktemp -d /tmp/falcon-ue${UE}.XXXXXXXX)
printf 'UE run directory: %s\n' "$UE_RUN"
mm_value() {
  awk -F ':' -v key="$1" '
    { field=$1; gsub(/^[ \t]+|[ \t]+$/, "", field) }
    field==key { sub(/^[^:]*:[ \t]*/, ""); sub(/[ \t]+$/, ""); print; exit }
  '
}
select_ue() {
  local listing path details model imei identity selected_identity
  local -a candidates=() matches=()
  [[ -z "${BEARER:-}" && -z "${WWAN_IF:-}" ]] || return 1
  MODEM=""; MODEM_KV=""; MODEM_IDENTITY=""; SIM_PATH=""; SIM_KV=""
  listing=$(mmcli -L) || return 1
  mapfile -t candidates < <(printf '%s\n' "$listing" |
    grep -oE '/org/freedesktop/ModemManager1/Modem/[0-9]+' | sort -u)
  for path in "${candidates[@]}"; do
    details=$(mmcli -m "$path" -K) || return 1
    model=$(printf '%s\n' "$details" | mm_value modem.generic.model)
    imei=$(printf '%s\n' "$details" | mm_value modem.generic.equipment-identifier)
    identity=$(printf '%s\n' "$details" | mm_value modem.generic.device-identifier)
    if [[ "$model" = *RM500Q* && "$imei" = "$EXPECTED_IMEI" &&
          -n "$identity" && "$identity" != -- ]]; then
      matches+=("$path")
      selected_identity=$identity
    fi
  done
  if [[ ${#matches[@]} -ne 1 ]]; then
    printf 'FAIL: IMEI %s matched %s modems; inspect USB/identity.\n' \
      "$EXPECTED_IMEI" "${#matches[@]}"
    return 1
  fi
  MODEM=${matches[0]}
  MODEM_KV=$(mmcli -m "$MODEM" -K) || return 1
  [[ "$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.equipment-identifier)" = "$EXPECTED_IMEI" ]] || return 1
  MODEM_IDENTITY=$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.device-identifier)
  [[ "$MODEM_IDENTITY" = "$selected_identity" ]] || return 1
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

Stop at a failed identity/SIM check. If the selected modem is disabled,
run `sudo mmcli -m "$MODEM" --enable` and repeat identity validation. For USIM
readiness, use its actual QMI port and the [USIM check](ue_laptop_quick_commands.md#1a-read-the-inserted-sim-and-usim-state).

<a id="ue2-cell-lock"></a>

### 2.2. Verify the AT port and restore the DU2 lock

Read the selected modem's device/ports and match them to the USB serial links.
AT port numbers change on reconnect; confirm `AT+CIMI` before any write.

```bash
mmcli -m "$MODEM"
ls -l /dev/serial/by-path/
read -r -p 'Selected UE2 AT device, for example /dev/ttyUSB2: ' AT_PORT
sudo minicom -D "$AT_PORT" -b 115200
```

Inside minicom, first read:

```text
AT
AT+CIMI
AT+QNWLOCK="common/5g"
AT+QENG="servingcell"
AT+C5GREG?
```

Require IMSI `001010000000102`. If the lock and actual cell already match, continue
to 2.3. Otherwise set NR5G-SA preferences and this role's exact lock:

```text
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

Require writes `OK`, lock `2,639648,30,78`, NR5G-SA / `001,01` / TAC 7,
PCI `2`, NCI `00066C001`, SSB `639648`, n78 and `+C5GREG: 0,1`.
Exit minicom with Ctrl+A, then X. A correct APN/IP or lock tuple alone does not
prove the actual serving cell. Recheck this cell after PDU establishment and
before UL; stop this role's setup/test if identity or cell differs.

### 2.3. Connect `internet2` IPv4 and read the actual bearer

```bash
mmcli -m "$MODEM" -K | awk '
  /modem\.generic\.(state|access-technologies)/ ||
  /modem\.3gpp\.(operator-code|registration-state|packet-service-state)/ {print}
'
```

Require `5gnr / 00101 / home / attached`. Then connect and discover its bearer:

```bash
sudo mmcli -m "$MODEM" --simple-connect="apn=internet2,ip-type=ipv4"
read_ue_bearer() {
  local path details
  local -a matches=()
  MODEM_KV=$(mmcli -m "$MODEM" -K) || return 1
  [[ "$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.device-identifier)" = "$MODEM_IDENTITY" ]] || return 1
  for path in $(printf '%s\n' "$MODEM_KV" | grep -oE '/org/freedesktop/ModemManager1/Bearer/[0-9]+' | sort -u); do
    details=$(mmcli -b "$path" -K) || return 1
    if [[ "$(printf '%s\n' "$details" | mm_value bearer.status.connected)" = yes &&
          "$(printf '%s\n' "$details" | mm_value bearer.properties.apn)" = "$APN" ]]; then
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
if read_ue_bearer; then
  PATH_IP=$UE_IP; PATH_CIDR=$UE_IP/$UE_PREFIX; PATH_IF=$WWAN_IF
  PATH_SERVER=10.46.0.1; PATH_TABLE=152; PATH_RULE=10161; PATH_GUARD=10162
else
  printf 'FAIL: no unique usable IPv4 bearer; stop here.\n'
fi
```

Require APN `internet2`, an address in `10.46.0.0/16`, static IPv4, a non-suspended
connected bearer and the modem's own dedicated interface. Keep the actual
`UE_IP`, `UE_PREFIX`, `UE_MTU` and `WWAN_IF`; never substitute an old allocation.
Recheck 2.2's cell before rebuilding the host path. The fresh `PATH_*`
address/table fields also support a verified existing path; original rollback
MTU/state must come from its recorded ledger, not the current configured link.

<a id="ue2-clean-old-path"></a>

### 2.4. Inspect and remove only UE2's old path

Stop this UE's test traffic. Keep a newly identity/cell-verified PDU connected
during a host-only rebind. Inspect old addresses/rules/routes first:

```bash
ip -o -4 addr show
ip -4 rule show
ip -4 route show table 152
ip -4 route show default
```

Table `152` belongs to the laptop. An absent table can report
`FIB table does not exist`; old rules may remain after USB/interface loss.
Record the old path separately from the new bearer. If the current path already
uses the verified new allocation and works, skip cleanup/installation and go to
2.6. Otherwise remove only this role's recorded entries.

The following cleanup uses the retained old session values. If its old IP,
prefix or interface differs from inspected state, reconstruct the owned values
before editing the commands. It skips absent entries, refuses a wrong modem or
old address/interface/prefix, and keeps the guard until the old address is absent
everywhere. Preserve the other UE and Wi-Fi; never flush shared routing tables.

```bash
cleanup_old_ue2_path() {
  local current
  current=$(mmcli -m "$MODEM" -K) || return 1
  [[ "$(printf '%s\n' "$current" | mm_value modem.generic.equipment-identifier)" = 863305041980706 ]] || return 1
  if ip -o -4 addr show | grep -Eq 'inet 10[.]46[.]0[.]2/'; then
    ip -o -4 addr show dev wwan0 | grep -Fq 'inet 10.46.0.2/30 ' || {
      printf 'STOP: old UE2 address/interface/prefix differs; inspect ownership.\n'; return 1;
    }
    printf '%s\n' "$current" | grep -Fq 'wwan0 (net)' || return 1
  fi
  if ip -4 rule show | grep -Eq '^10161:[[:space:]]+from 10[.]46[.]0[.]2(/32)? to 10[.]46[.]0[.]1(/32)? lookup 152([[:space:]]|$)'; then
    sudo ip -4 rule del pref 10161 from 10.46.0.2/32 to 10.46.0.1/32 lookup 152 || return 1
  fi
  if ip -4 route show table 152 10.46.0.1/32 2>/dev/null | grep -Eq '^10[.]46[.]0[.]1(/32)? dev wwan0 .*src 10[.]46[.]0[.]2([[:space:]]|$)'; then
    sudo ip -4 route del table 152 10.46.0.1/32 dev wwan0 src 10.46.0.2 || return 1
  fi
  if ip -o -4 addr show dev wwan0 2>/dev/null | grep -Fq 'inet 10.46.0.2/30 '; then
    sudo ip -4 addr del 10.46.0.2/30 dev wwan0 || return 1
  fi
  if ip -o -4 addr show | grep -Eq 'inet 10[.]46[.]0[.]2/'; then
    printf 'STOP: old UE2 source remains; keep its guard.\n'; return 1
  fi
  if ip -4 rule show | grep -Eq '^10162:[[:space:]]+from 10[.]46[.]0[.]2(/32)? to 10[.]46[.]0[.]1(/32)? unreachable([[:space:]]|$)'; then
    sudo ip -4 rule del pref 10162 from 10.46.0.2/32 to 10.46.0.1/32 type unreachable || return 1
  fi
  printf 'Matching old UE2 entries removed; inspect table 152 and its priorities.\n'
}
cleanup_old_ue2_path
```

<a id="ue2-build-path"></a>

### 2.5. Build UE2's fresh table 152 and rules

Reinspect table `152` and priorities `10161/10162`; require them free
for a new path. Use the just-read bearer IP/prefix/MTU/interface. This preflight
refuses collisions and an earlier matching policy rule:

```bash
python3 - "$UE_IP" "$UE_PREFIX" "$UE_MTU" "$ROUTE_TABLE" "$RULE_PREF" "$GUARD_PREF" "$UE_SUBNET" "$SERVER_IP" <<'PY'
import ipaddress, json, pathlib, subprocess, sys
ip, prefix, mtu, table, lookup, guard, subnet, server = sys.argv[1:]
source = ipaddress.IPv4Address(ip)
destination = ipaddress.IPv4Address(server)
ipaddress.IPv4Interface(ip + '/' + prefix)
assert source in ipaddress.IPv4Network(subnet) and source != destination, 'Wrong UE subnet/address'
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
        assert not (contains(rule.get('src'), source) and contains(rule.get('dst'), destination)), 'Matching earlier policy rule requires review'
routes = subprocess.run(['ip', '-j', '-4', 'route', 'show', 'table', table], capture_output=True, text=True)
if routes.returncode:
    assert 'FIB table does not exist' in routes.stderr, routes.stderr
else:
    assert not json.loads(routes.stdout), 'Routing table already has routes'
print('Policy slots and IPv4 parameters: OK')
PY
```

Require `Policy slots and IPv4 parameters: OK`. Install the source guard before
exposing the source address, and save this run's rollback/ownership values:

```bash
prepare_dual_path() {
  local mgmt_dev
  [[ "$UE" = 2 && "$APN" = internet2 && "$SERVER_IP" = 10.46.0.1 &&
     "$ROUTE_TABLE" = 152 && "$RULE_PREF" = 10161 && "$GUARD_PREF" = 10162 ]] || return 1
  [[ "$WWAN_IF" =~ ^(wwan|wwp|rmnet)[[:alnum:]_.-]*$ ]] || return 1
  [[ "$(basename "$(readlink -f "/sys/class/net/$WWAN_IF/device/driver")")" = qmi_wwan ]] || return 1
  printf '%s\n' "$MODEM_KV" | grep -Fq "$WWAN_IF (net)" || return 1
  [[ -z "$(ip -o -4 addr show dev "$WWAN_IF")" ]] || return 1
  [[ -z "$(ip -4 route show default dev "$WWAN_IF")" &&
     -z "$(ip -6 route show default dev "$WWAN_IF")" ]] || return 1
  [[ -z "$(ip -o -4 addr show | awk -v wanted="$UE_IP" '{split($4,a,"/"); if(a[1]==wanted) print}')" ]] || return 1
  [[ -z "$(ip -o -4 addr show | awk -v wanted="$SERVER_IP" '{split($4,a,"/"); if(a[1]==wanted) print}')" ]] || return 1
  if [[ -n "${SSH_CONNECTION:-}" ]]; then
    mgmt_dev=$(ip route get "${SSH_CONNECTION%% *}" | awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}')
    [[ -n "$mgmt_dev" && "$mgmt_dev" != "$WWAN_IF" ]] || return 1
  fi
  PATH_IP=$UE_IP; PATH_CIDR=$UE_IP/$UE_PREFIX; PATH_IF=$WWAN_IF
  PATH_SERVER=$SERVER_IP
  PATH_TABLE=$ROUTE_TABLE; PATH_RULE=$RULE_PREF; PATH_GUARD=$GUARD_PREF
  PATH_OLD_MTU=$(cat "/sys/class/net/$PATH_IF/mtu") || return 1
  PATH_WAS_UP=no
  ip -o link show dev "$PATH_IF" | grep -Eq '(<|,)UP(,|>)' && PATH_WAS_UP=yes
  declare -p MODEM MODEM_IDENTITY EXPECTED_IMEI EXPECTED_IMSI BEARER \
    APN UE_SUBNET PATH_SERVER PATH_IP PATH_CIDR PATH_IF PATH_TABLE PATH_RULE PATH_GUARD PATH_OLD_MTU PATH_WAS_UP \
    > "$UE_RUN/route-state.txt"
  sudo ip -4 rule add pref 10162 from "$PATH_IP/32" to 10.46.0.1/32 type unreachable &&
  sudo ip link set dev "$PATH_IF" mtu "$UE_MTU" up &&
  sudo ip -4 addr add "$PATH_CIDR" dev "$PATH_IF" noprefixroute &&
  sudo ip -4 route add table 152 10.46.0.1/32 dev "$PATH_IF" src "$PATH_IP" &&
  sudo ip -4 rule add pref 10161 from "$PATH_IP/32" to 10.46.0.1/32 lookup 152
}
if prepare_dual_path; then
  ip -4 route get 10.46.0.1 from "$PATH_IP"
  ip -4 route show default
  ping -q -I "$PATH_IP" -c 5 "$PATH_SERVER"
else
  printf 'FAIL: path setup incomplete; stop and clean only this run.\n'
fi
```

Stop on a setup failure and preserve `route-state.txt` for precise cleanup.
The setup requires a dedicated QMI interface with no existing IPv4 address or
default route. Resolve unexpected interface ownership before continuing.

### 2.6. Verify table 152, private ping and management routing

```bash
ip -4 rule show
ip -4 route show table 152
ip -4 route get 10.46.0.1 from "$UE_IP"
ping -I "$UE_IP" -c 5 10.46.0.1
ip -4 route show default
```

Require this UE's actual interface and `table 152`, private ping replies,
and the unchanged Wi-Fi default route. Save `PATH_*` values even if a later
bearer allocation changes. Recheck cell/SA after reconnect/reattachment.

### 2.7. Run UE2's 60-second TCP UL, then keep it connected

Wait for Spark's `10.46.0.1:5202` server to show `Server listening`.
Both DUs stay running; the other UE's test traffic stays idle during this case:

```bash
TZ=America/New_York date --iso-8601=seconds | tee "$UE_RUN/ul-solo-start.txt"
set -o pipefail
iperf3 -c 10.46.0.1 -p 5202 -B "$PATH_IP" \
  -t 60 -i 1 --get-server-output -J | tee "$UE_RUN/ul-solo.json"
UL_RC=$?
printf 'pipeline_exit=%d\n' "$UL_RC" | tee "$UE_RUN/ul-solo-exit.txt"
TZ=America/New_York date --iso-8601=seconds | tee "$UE_RUN/ul-solo-end.txt"
```

Require pipeline exit 0 and a completed receiver summary. Record receiver
goodput, sender retransmissions, time bounds and cell/SA/PDU continuity. Keep
this modem, PDU, path, terminal and its Spark server active for the dual test.

Recheck UE1's private ping in its own terminal, then continue to section 3.

<a id="dual-ul"></a>

## 3. Concurrent UL, controlled UDP and path guards

Start Spark step 7's 120-second diagnostic capture first. Wait for
`FALCON_CAPTURE subscriptions_kpm=2`, then start both clients from one laptop
terminal using this block after UE1 and UE2 each complete their full sequence.
Update the role tuples from fresh identity/cell/bearer readbacks if values change.

This launcher checks both routes before starting traffic, creates a fresh log
directory, and records each iperf process's actual exit code without Bash PID
variables. Keep both Spark servers, DUs, CU and RIC running:

```bash
python3 - <<'PY'
import json, subprocess, tempfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

def stamp():
    return datetime.now(ZoneInfo("America/New_York")).isoformat()

roles = [
    (1, "10.45.0.1", "10.45.0.2", "5201", "wwan1", 151),
    (2, "10.46.0.1", "10.46.0.3", "5202", "wwan0", 152),
]
for ue, server, source, port, interface, table in roles:
    routes = json.loads(subprocess.check_output(
        ["ip", "-j", "-4", "route", "get", server, "from", source], text=True))
    assert len(routes) == 1 and routes[0].get("dev") == interface, f"UE{ue}: wrong interface"
    assert int(routes[0].get("table", -1)) == table, f"UE{ue}: wrong policy table"

run = Path(tempfile.mkdtemp(prefix="falcon-dual-ul-", dir="/tmp"))
result = {"started_at": stamp(), "links": []}
jobs = []
print("Evidence:", run, "START:", result["started_at"], flush=True)
for ue, server, source, port, interface, table in roles:
    path = run / f"ue{ue}.log"
    stream = path.open("w")
    process = subprocess.Popen(
        ["iperf3", "-c", server, "-p", port, "-B", source,
         "-t", "60", "-i", "1", "--get-server-output"],
        stdout=stream, stderr=subprocess.STDOUT)
    jobs.append((ue, process, stream, path, server, source, port))
for ue, process, stream, path, server, source, port in jobs:
    code = process.wait()
    stream.close()
    result["links"].append({"ue": ue, "source": source, "server": server,
                            "port": int(port), "exit_code": code, "log": str(path)})
    print(f"UE{ue} exit={code}", flush=True)
    for line in path.read_text().splitlines():
        if any(word in line for word in ["sender", "receiver", "iperf Done", "error"]):
            print(f"UE{ue}: {line}")
result["ended_at"] = stamp()
(run / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
print("END:", result["ended_at"], "Evidence:", run, flush=True)
raise SystemExit(0 if all(link["exit_code"] == 0 for link in result["links"]) else 1)
PY
```

Retain the printed directory, both logs and `summary.json`. Require both exit
codes 0 and two completed receiver summaries. Inspect actual DU/UE-tagged KPM
blocks in the same UL window; successful subscriptions alone do not prove data
delivery. For full Plan 3 UL
coexistence, repeat each solo/other-DU-idle/concurrent case three times.

The daily workflow keeps both DUs running. Label the individual traffic tests
with the other DU active and its UE test traffic idle. Isolated-radio comparison
trials remain a separate full-Plan-3 validation case, with refreshed identities
and paths required after any radio/modem restart.

Add UL UDP at a controlled rate no greater than 70% of each measured solo capacity:

```bash
set -o pipefail
read -r -p 'Measured controlled UL rate, for example 8M: ' UL_OFFERED_RATE
iperf3 -c "$PATH_SERVER" -p "$IPERF_PORT" -B "$PATH_IP" \
  -u -b "$UL_OFFERED_RATE" -t 60 -i 1 --get-server-output -J | tee "$UE_RUN/ul-udp.json"
UL_RC=$?
printf 'pipeline_exit=%d\n' "$UL_RC" | tee "$UE_RUN/ul-udp-exit.txt"
```

At the same offered load, require receiver goodput at least 90% of its isolated
result and UDP loss at most 1%. Retain jitter, cell/SA/PDU continuity and the
planned PHY observations. No application DL or mixed-direction trials are required.
Use distinct filenames for subsequent repetitions.

Before declaring independent paths, stop traffic on one UE and remove only its
table route. Keep the other UE's ping/UL running. In the affected terminal:

```bash
sudo ip -4 route del table "$PATH_TABLE" "$PATH_SERVER/32" dev "$PATH_IF" src "$PATH_IP"
if ip -4 route get "$PATH_SERVER" from "$PATH_IP"; then
  printf 'FAIL: source fell through to another route; do not accept this path.\n'
else
  printf 'Source guard: OK (private destination unreachable).\n'
fi
sudo ip -4 route add table "$PATH_TABLE" "$PATH_SERVER/32" dev "$PATH_IF" src "$PATH_IP"
ip -4 route get "$PATH_SERVER" from "$PATH_IP"
```

Repeat for the other UE. Confirm the unaffected link survives. Verify counters/
captures on the intended WWAN and repeat after an actual bearer disconnect/
reattachment with refreshed identities. A route lookup alone is not packet-path
acceptance.

<a id="cleanup"></a>

## 4. Finish tests and clean each role in its own terminal

Stop clients and let the finite Spark xApp delete subscriptions and finish.
Clean one role at a time with its saved run metadata; preserve the other UE and
Wi-Fi. Skip already-absent owned entries after inspecting them. If an interface
disappeared, retain its source guard until the old source address is absent.

### 4.1. Final UE1 cleanup — table 151

Run only in the UE1 terminal retaining its `MODEM`, `PATH_*` and
`route-state.txt`. Verify identity and interface ownership first:

```bash
mmcli -m "$MODEM"
CURRENT_MODEM_KV=$(mmcli -m "$MODEM" -K)
printf '%s\n' "$CURRENT_MODEM_KV" | mm_value modem.generic.device-identifier
printf 'Expected identity: %s; recorded WWAN: %s\n' "$MODEM_IDENTITY" "$PATH_IF"
```

Require IMEI `863305041978437` and that modem's recorded interface before deleting
owned state. Disconnect its PDU and remove only its saved lookup/route/address:

```bash
sudo mmcli -m "$MODEM" --simple-disconnect
sudo ip -4 rule del pref 10151 from "$PATH_IP/32" to 10.45.0.1/32 lookup 151
sudo ip -4 route del table 151 10.45.0.1/32 dev "$PATH_IF" src "$PATH_IP"
sudo ip -4 addr del "$PATH_CIDR" dev "$PATH_IF"
```

Only after its source address is absent everywhere, remove its guard and
restore this run's recorded interface MTU/state:

```bash
if [[ -z "$(ip -o -4 addr show | awk -v wanted="$PATH_IP" '{split($4,a,"/"); if(a[1]==wanted) print}')" ]]; then
  sudo ip -4 rule del pref 10152 from "$PATH_IP/32" to 10.45.0.1/32 type unreachable
  if [[ -n "${PATH_OLD_MTU:-}" && -n "${PATH_WAS_UP:-}" ]]; then
    sudo ip link set dev "$PATH_IF" mtu "$PATH_OLD_MTU"
    if [[ "$PATH_WAS_UP" = no ]]; then sudo ip link set dev "$PATH_IF" down; fi
  else
    printf 'Original MTU/state not recorded; inspect the owned ledger before link restoration.\n'
  fi
else
  printf 'FAIL: source address remains; keep the guard and inspect cleanup.\n'
fi
ip -4 rule show
ip -4 route show default
```

### 4.2. Final UE2 cleanup — table 152

Run only in the UE2 terminal retaining its `MODEM`, `PATH_*` and
`route-state.txt`. Verify identity and interface ownership first:

```bash
mmcli -m "$MODEM"
CURRENT_MODEM_KV=$(mmcli -m "$MODEM" -K)
printf '%s\n' "$CURRENT_MODEM_KV" | mm_value modem.generic.device-identifier
printf 'Expected identity: %s; recorded WWAN: %s\n' "$MODEM_IDENTITY" "$PATH_IF"
```

Require IMEI `863305041980706` and that modem's recorded interface before deleting
owned state. Disconnect its PDU and remove only its saved lookup/route/address:

```bash
sudo mmcli -m "$MODEM" --simple-disconnect
sudo ip -4 rule del pref 10161 from "$PATH_IP/32" to 10.46.0.1/32 lookup 152
sudo ip -4 route del table 152 10.46.0.1/32 dev "$PATH_IF" src "$PATH_IP"
sudo ip -4 addr del "$PATH_CIDR" dev "$PATH_IF"
```

Only after its source address is absent everywhere, remove its guard and
restore this run's recorded interface MTU/state:

```bash
if [[ -z "$(ip -o -4 addr show | awk -v wanted="$PATH_IP" '{split($4,a,"/"); if(a[1]==wanted) print}')" ]]; then
  sudo ip -4 rule del pref 10162 from "$PATH_IP/32" to 10.46.0.1/32 type unreachable
  if [[ -n "${PATH_OLD_MTU:-}" && -n "${PATH_WAS_UP:-}" ]]; then
    sudo ip link set dev "$PATH_IF" mtu "$PATH_OLD_MTU"
    if [[ "$PATH_WAS_UP" = no ]]; then sudo ip link set dev "$PATH_IF" down; fi
  else
    printf 'Original MTU/state not recorded; inspect the owned ledger before link restoration.\n'
  fi
else
  printf 'FAIL: source address remains; keep the guard and inspect cleanup.\n'
fi
ip -4 rule show
ip -4 route show default
```

The earlier literal-command sessions did not capture `route-state.txt`; their
preflight interfaces were DOWN / MTU 1500. Reconstruct missing cleanup metadata
only from verified ownership and evidence. Future setup above saves a new ledger
for each role. After both laptop paths are cleaned, use [Spark step 8](dual_ue_spark_quick_commands.md#8-shutdown-and-retained-evidence)
for server/RAN/core shutdown. Retain identity/cell/bearer/path/UL/KPM correlation
and restart/guard/survivor observations; full acceptance remains pending.
