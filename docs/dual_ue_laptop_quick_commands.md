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

For the current running session, resume at step 6 after Spark starts its KPM
capture. Both laptop paths already exist; verify them rather than reinstalling
them. The earlier concurrent launcher lost variable expansions in `wait`/`printf`;
its printed zero exit codes and immediate end timestamp are invalid. Preserve
its `01` logs and use the Python launcher below for a fresh recorded test.

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

| Observed this session | UE1 | UE2 |
| --- | --- | --- |
| Modem / SIM / bearer | `6` / `6` / `4` | `5` / `5` / `3` |
| WWAN / IPv4 | `wwan1` / `10.45.0.2/30` | `wwan0` / `10.46.0.2/30` |
| AT port / USB device | `/dev/ttyUSB6` / `4-4` | `/dev/ttyUSB2` / `4-3` |
| Bearer gateway / MTU | `10.45.0.1` / `1400` | `10.46.0.1` / `1400` |

Rediscover these dynamic values after modem restart/reconnection. Both cells use
PLMN `00101`, TAC 7 and SST 1. DNN selects the UE pool; cell lock selects the DU.

<a id="ue2-selection"></a>

## 1. Select the modem automatically by IMEI and verify its SIM

Tools: ModemManager, libqmi-utils, minicom, iproute2, iperf3 and Python 3. For a
new laptop, use [UE tool installation](ue_laptop_quick_commands.md#1-install-tools-and-select-the-modem).
Open a **fresh UE2 Bash terminal**. Use this same terminal through bearer/routing/
traffic/cleanup. Later repeat in another fresh terminal for UE1, changing `UE=2`
to `UE=1`. This block reads identity only. It scans the current modem paths for
the role's expected IMEI, requires exactly one match, then verifies the inserted
SIM's IMSI. No modem number needs to be entered or retained across reconnections:

```bash
UE=2
case "$UE" in
  1) EXPECTED_IMEI=863305041978437; EXPECTED_IMSI=001010000000101
     APN=internet; UE_SUBNET=10.45.0.0/16; SERVER_IP=10.45.0.1
     ROUTE_TABLE=151; RULE_PREF=10151; GUARD_PREF=10152; IPERF_PORT=5201 ;;
  2) EXPECTED_IMEI=863305041980706; EXPECTED_IMSI=001010000000102
     APN=internet2; UE_SUBNET=10.46.0.0/16; SERVER_IP=10.46.0.1
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

Require the intended IMEI/IMSI. Use the selected modem's real QMI port for the
[USIM readiness check](ue_laptop_quick_commands.md#1a-read-the-inserted-sim-and-usim-state).
If disabled, enable only this selected modem with `sudo mmcli -m "$MODEM" --enable`.
If its SIM is unreadable, resolve that first and repeat identity selection.

## 2. AT communication and cell lock

Read the selected modem's ports and inspect `/dev/serial/by-path/` when ModemManager
omits working AT ports. Select that modem's actual AT port; tty numbering changes
when two modems are present.

```bash
mmcli -m "$MODEM"
ls -l /dev/serial/by-path/
read -r -p 'Selected modem AT device, for example /dev/ttyUSB6: ' AT_PORT
sudo minicom -D "$AT_PORT" -b 115200
```

**Inside minicom, not Bash:** first read:

```text
AT
AT+CIMI
AT+QNWLOCK="common/5g"
AT+QENG="servingcell"
AT+C5GREG?
```

Require `OK` and this terminal's expected IMSI before changing preferences.
If the lock and actual serving cell already match the role, continue at step 3.
Otherwise configure and verify them. For UE2:

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
PCI/SSB, and serving cell `NR5G-SA / 001,01` on that cell: UE1 NCI `00066C000`, UE2 NCI
`00066C001`, TAC 7. Require
`+C5GREG: 0,1` and corroborate with ModemManager below. Exit minicom with `Ctrl+A`,
then `X`. Recheck identity/lock after reconnecting or rebooting the modem.

Do not rewrite an already matching lock before every PDU connection. Quectel's
[RMU500-EK support response](https://forums.quectel.com/t/rmu500-ek-to-prevent-from-handover/11554)
states the 5G lock is saved to NV and takes effect after restart. The current
`RM500QGLABR13A03M4G` run confirms successful write/readback and the intended
serving cell; power-cycle retention and enforcement with both DUs present are
still unverified. After a modem restart/reconnection, read the lock first; skip
rewriting a matching tuple, reapply a missing/wrong tuple, and verify the actual
serving cell. Include restart/retention in the later cold-start acceptance.

## 3. Registration, IPv4 PDU and the actual bearer

```bash
mmcli -m "$MODEM" -K | awk '
  /modem\.generic\.(state|access-technologies)/ ||
  /modem\.3gpp\.(operator-code|registration-state|packet-service-state)/ {print}
'
```

Require `5gnr / 00101 / home / attached`. Then:

```bash
sudo mmcli -m "$MODEM" --simple-connect="apn=$APN,ip-type=ipv4"
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
read_ue_bearer || printf 'FAIL: no unique usable IPv4 bearer; stop here.\n'
```

Require the role's APN, an address in its expected IPv4 pool and a dedicated WWAN
for each UE. Preserve the actual modem,
SIM, bearer, interface and address in that UE's terminal. Authentication failures
need subscriber/SIM diagnosis before any IP routing changes.

## 4. Install and verify each source-policy path

Use this recipe for both the initial single-UE test and the later dual test. It
adds only a source-specific path to the role's Spark service IP, leaving management defaults
intact. Resolve WWAN ownership with NetworkManager first; this recipe requires
a dedicated QMI interface with no existing IPv4 address or default route.

In the current session, both paths already exist. If their readbacks match the
role, skip installation and continue with traffic checks. For a new path,
inspect current rules and the role's proposed table first:

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

Require `OK`. Check the dedicated interface, capture rollback values, and install
the guard **before** exposing the source address. This is a new procedure; on a
partial failure, stop and use step 7 with the captured `PATH_*` values.

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
  sudo ip -4 rule add pref "$PATH_GUARD" from "$PATH_IP/32" to "$PATH_SERVER/32" type unreachable &&
  sudo ip link set dev "$PATH_IF" mtu "$UE_MTU" up &&
  sudo ip -4 addr add "$PATH_CIDR" dev "$PATH_IF" noprefixroute &&
  sudo ip -4 route add table "$PATH_TABLE" "$PATH_SERVER/32" dev "$PATH_IF" src "$PATH_IP" &&
  sudo ip -4 rule add pref "$PATH_RULE" from "$PATH_IP/32" to "$PATH_SERVER/32" lookup "$PATH_TABLE"
}
if prepare_dual_path; then
  ip -4 route get "$PATH_SERVER" from "$PATH_IP"
  ip -4 route show default
  ping -q -I "$PATH_IP" -c 5 "$PATH_SERVER"
else
  printf 'FAIL: path setup incomplete; stop and clean only this run.\n'
fi
```

Require the route to use `PATH_IF` with `PATH_IP`, successful private ping, and
unchanged management defaults. Save the `PATH_*` values until cleanup even if a
later bearer read changes `UE_IP`. If reverse-path filtering rejects return
traffic, inspect the selected WWAN settings using Plan 3 Step 8; record any
reviewed per-interface change and its rollback instead of changing all interfaces.

## 5. Measure each link's TCP UL

Wait for the selected Spark server to show `Server listening` in Spark step 6.
Use the selected UE terminal and its saved `PATH_*` values:

```bash
TZ=America/New_York date --iso-8601=seconds | tee "$UE_RUN/ul-solo-start.txt"
set -o pipefail
iperf3 -c "$PATH_SERVER" -p "$IPERF_PORT" -B "$PATH_IP" \
  -t 60 -i 1 --get-server-output -J | tee "$UE_RUN/ul-solo.json"
UL_RC=$?
printf 'pipeline_exit=%d\n' "$UL_RC" | tee "$UE_RUN/ul-solo-exit.txt"
TZ=America/New_York date --iso-8601=seconds | tee "$UE_RUN/ul-solo-end.txt"
```

Require pipeline exit 0, a completed receiver summary and continued cell/SA/PDU.
Run Spark step 7's KPM monitor while UL is active. First test UE2 with DU2 only;
then Spark starts DU1 and you repeat laptop steps 1–5 for UE1 in a fresh terminal.
Label UE1 UL / DU2 test traffic idle separately from an isolated DU1 case.
Both role UL functionality checkpoints already passed in this session.

## 6. Concurrent UL, controlled UDP and path guards

Start Spark step 7's 120-second diagnostic capture first. Wait for
`FALCON_CAPTURE subscriptions_kpm=2`, then start both clients from one laptop
terminal using this block. The role tuples match this session; update them from
fresh identity/cell/bearer readbacks if addresses/interfaces change.

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
    (2, "10.46.0.1", "10.46.0.2", "5202", "wwan0", 152),
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

For each RF-isolated case, stop the other DU while retaining CU/RIC and the tested
link. Restore both DUs afterward, refresh the affected UE's registration/bearer/
route ledger, and verify it before the next concurrent case.

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

## 7. Cleanup and retained evidence

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
sudo ip -4 rule del pref "$PATH_RULE" from "$PATH_IP/32" to "$PATH_SERVER/32" lookup "$PATH_TABLE"
sudo ip -4 route del table "$PATH_TABLE" "$PATH_SERVER/32" dev "$PATH_IF" src "$PATH_IP"
sudo ip -4 addr del "$PATH_CIDR" dev "$PATH_IF"
```

Only after the run's source address is absent on the laptop, remove its guard
and restore the recorded interface settings:

```bash
if [[ -z "$(ip -o -4 addr show | awk -v wanted="$PATH_IP" '{split($4,a,"/"); if(a[1]==wanted) print}')" ]]; then
  sudo ip -4 rule del pref "$PATH_GUARD" from "$PATH_IP/32" to "$PATH_SERVER/32" type unreachable
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

The current live paths were configured with literal commands, so no
`route-state.txt` was captured for them. Both preflight interface states were
DOWN / MTU 1500. Reconstruct cleanup variables only after verifying the current
modem/interface ownership and exact observed addresses/rules in the evidence;
dynamic modem IDs must not be assumed unchanged.

After laptop traffic and path cleanup, use [Spark step 8](dual_ue_spark_quick_commands.md#8-shutdown-and-retained-evidence) for server/RAN/core shutdown.
Retain modem/SIM/cell/bearer/IP/WWAN mappings, path ownership and rollback values,
UL logs/time bounds/exit codes, guard/survivor observations and restart results.

