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
role's identity, lock/cell, bearer, complete host IPv4 reset and new-path verification.

The latest modem readback identifies UE1 as modem `9` and UE2 as modem `10`,
both connected with `5gnr`, PLMN `00101` and registration `home`. The previous
launcher falsely rejected UE1 by reading the parent access-technology key
instead of its `.value[1]` array entry, then by requiring the bearer default
gateway to equal the server endpoint. Both checks are corrected in section 3;
overwrite the saved laptop launcher with that version before rerunning preflight.
An earlier host readback had UE1 `10.45.0.3/29` on `wwan0` with table-151 source
rules/route intact. Read both current bearer allocations/routes again rather
than reusing these historical values. No historical allocation is needed for
role reset. Current cell/bearer/path preflight, ordinary ping/Wi-Fi-off checks
and measured dual UL/KPM are pending.
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

### 0.1. Install the role reset helper once on the laptop

Copy the following block once. It creates the same self-contained helper as
[`reset_ue_network.py`](../scripts/dual_fr1/reset_ue_network.py); a Falcon checkout
on the laptop is optional. The two role sequences then use short commands with
no previous IP, CIDR, modem index, interface name or run-directory variables.
The helper reads current modem ownership by IMEI, plus kernel addresses/rules/
routes. It clears the role's IPv4 addresses, its dedicated table and all reserved
rules (including duplicates and extra rules referencing that table), removes
legacy main-table WWAN routes and resets its WWAN to DOWN / MTU 1500. Wi-Fi and
the other UE's normal configuration are preserved. Without a modem/address,
stale rules and routes can still be cleared. A regular reset keeps the current
PDU; `--disconnect` also disconnects the selected IMEI's connected PDU.

```bash
cat > ~/falcon-reset-ue-network.py <<'FALCON_RESET_PY'
#!/usr/bin/env python3
"""Reset one Falcon laptop IPv4 role from current state, without session history."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys


ROLES = {
    1: ("863305041978437", "10.45.0.0/16", "10.45.0.1", 151, (10151, 10152, 10153, 10154)),
    2: ("863305041980706", "10.46.0.0/16", "10.46.0.1", 152, (10161, 10162, 10163, 10164)),
}
WWAN = re.compile(r"(?:wwan|wwp|rmnet)[A-Za-z0-9_.-]*")


def read(*command):
    return subprocess.check_output(command, text=True, stderr=subprocess.PIPE,
                                   env=dict(os.environ, LC_ALL="C"))


def change(*command):
    print("+ " + shlex.join(command), flush=True)
    subprocess.run(command, check=True, env=dict(os.environ, LC_ALL="C"))


def ip_json(*args):
    try:
        return json.loads(read("ip", "-j", "-4", *args))
    except subprocess.CalledProcessError as error:
        if args[:3] == ("route", "show", "table") and "FIB table does not exist" in (error.stderr or ""):
            return []
        raise


def table_aliases():
    aliases = {"local": 255, "main": 254, "default": 253}
    for directory in (Path("/etc/iproute2"), Path("/usr/lib/iproute2")):
        for path in [directory / "rt_tables", *sorted((directory / "rt_tables.d").glob("*"))]:
            if path.is_file():
                for line in path.read_text().splitlines():
                    fields = line.split("#", 1)[0].split()
                    if len(fields) == 2 and fields[0].isdigit():
                        aliases[fields[1]] = int(fields[0])
    return aliases


def modem_inventory():
    inventory = []
    for path in sorted(set(re.findall(r"/org/freedesktop/ModemManager1/Modem/\d+", read("mmcli", "-L")))):
        kv = dict(line.split(":", 1) for line in read("mmcli", "-m", path, "-K").splitlines() if ":" in line)
        kv = {key.strip(): value.strip() for key, value in kv.items()}
        ports = set(re.findall(r"([A-Za-z0-9_.-]+)\s+\(net\)", "\n".join(
            value for key, value in kv.items() if key.startswith("modem.generic.ports"))))
        inventory.append((path, kv.get("modem.generic.equipment-identifier"), ports, kv.get("modem.generic.state")))
    return inventory


def reset(ue, dry_run=False, disconnect=False):
    imei, subnet, server, table, priorities = ROLES[ue]
    pool = ipaddress.IPv4Network(subnet)
    aliases = table_aliases()

    def table_number(value):
        return int(value) if str(value).isdigit() else aliases.get(value)

    def role_rule(rule):
        return rule.get("priority") in priorities or table_number(rule.get("table")) == table

    addresses = ip_json("addr", "show")
    rules = ip_json("rule", "show")
    routes = ip_json("route", "show", "table", "main")
    private_routes = ip_json("route", "show", "table", str(table))
    if any(info.get("local") == server for device in addresses for info in device.get("addr_info", [])):
        raise ValueError("Spark service address is local; run this helper on the UE laptop")
    if any(table_number(rule.get("table")) == table and rule.get("priority") in (0, 32766, 32767) for rule in rules):
        raise ValueError("A built-in policy priority references the role table; resolve that conflict first")
    pool_devices = {device["ifname"] for device in addresses if any(
        ipaddress.IPv4Address(info["local"]) in pool for info in device.get("addr_info", []))}
    if any(not WWAN.fullmatch(device) for device in pool_devices):
        raise ValueError("Role addresses exist on a non-WWAN interface; inspect that interface")
    try:
        inventory = modem_inventory()
    except (subprocess.CalledProcessError, FileNotFoundError):
        if pool_devices:
            raise ValueError("Cannot read current modem ownership; start ModemManager before address reset") from None
        inventory = []
    selected = [modem for modem in inventory if modem[1] == imei]
    if len(selected) > 1:
        raise ValueError("Expected IMEI matches multiple modems")
    owned = set().union(*(modem[2] for modem in selected)) if selected else set()
    if any(not WWAN.fullmatch(device) for device in owned):
        raise ValueError("Selected modem exposes an unexpected network interface")
    targets = (owned & {device["ifname"] for device in addresses}) | pool_devices
    if any(ports & targets for _, other_imei, ports, _ in inventory if other_imei != imei):
        raise ValueError("A candidate interface belongs to another modem")
    if any(device["ifname"] in targets and any(ipaddress.IPv4Address(info["local"]) not in pool
           for info in device.get("addr_info", [])) for device in addresses):
        raise ValueError("Candidate WWAN also has addresses outside this role's pool")
    legacy_devices = {route["dev"] for route in routes if WWAN.fullmatch(route.get("dev", ""))
        and route.get("dst", "default") != "default"
        and ipaddress.IPv4Network(route["dst"], strict=False).subnet_of(pool)} - targets
    commands = []
    if disconnect and selected and selected[0][3] == "connected":
        commands.append(("mmcli", "-m", selected[0][0], "--simple-disconnect"))
    if private_routes:
        commands.append(("ip", "-4", "route", "flush", "table", str(table)))
    for device in sorted(targets):
        commands.extend([
            ("ip", "-4", "route", "flush", "table", "main", "dev", device),
            ("ip", "-4", "addr", "flush", "dev", device, "to", subnet),
            ("ip", "link", "set", "dev", device, "mtu", "1500", "down"),
        ])
    for device in sorted(legacy_devices):
        commands.append(("ip", "-4", "route", "flush", "table", "main", "dev", device, "to", subnet))
    print(f"UE{ue}: IMEI={imei}; reset table={table}, priorities={priorities}, pool={subnet}, WWAN={sorted(targets)}")
    if dry_run:
        for command in commands:
            print("would run: " + shlex.join(command))
        for rule in rules:
            if role_rule(rule):
                print("would remove rule: " + json.dumps(rule, sort_keys=True))
        return
    for command in commands:
        change(*command)
    if any(ipaddress.IPv4Address(info["local"]) in pool for device in ip_json("addr", "show")
           for info in device.get("addr_info", [])):
        raise ValueError("Role address remains or was recreated; keep its guards and stop")
    for rule in ip_json("rule", "show"):
        if role_rule(rule):
            command = ["ip", "-4", "rule", "del", "pref", str(rule["priority"])]
            if rule["priority"] not in priorities:
                command.extend(["lookup", str(table)])
            change(*command)
    remaining_routes = ip_json("route", "show", "table", "main")
    remaining_addresses = ip_json("addr", "show")
    if (any(ipaddress.IPv4Address(info["local"]) in pool for device in remaining_addresses for info in device.get("addr_info", []))
            or ip_json("route", "show", "table", str(table)) or any(role_rule(rule) for rule in ip_json("rule", "show"))
            or any(route.get("dev") in targets or (route.get("dev") in legacy_devices
                   and route.get("dst", "default") != "default"
                   and ipaddress.IPv4Network(route["dst"], strict=False).subnet_of(pool)) for route in remaining_routes)):
        raise ValueError("Role IPv4 addresses/routes/rules remain or were recreated; reset is incomplete")
    print(f"UE{ue} reset complete: role IPv4 addresses, routes and policy rules cleared; WWAN baseline DOWN / MTU 1500")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ue", required=True, type=int, choices=(1, 2))
    parser.add_argument("--dry-run", action="store_true", help="Show the current reset scope without changes")
    parser.add_argument("--disconnect", action="store_true", help="Also disconnect this IMEI's current connected PDU")
    args = parser.parse_args()
    if not args.dry_run and os.geteuid() != 0:
        parser.error("Run reset with sudo; --dry-run can run without sudo")
    try:
        reset(args.ue, args.dry_run, args.disconnect)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"STOP: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
FALCON_RESET_PY
python3 ~/falcon-reset-ue-network.py --help
```

For inspection only, run `python3 ~/falcon-reset-ue-network.py --ue 1 --dry-run`
or the same command with `--ue 2`. Apply commands appear in each role's sequence.
The script reports complete only after checking that addresses/routes/rules are
gone. If a command fails or another manager recreates the configuration, it
reports incomplete; address-removal failures retain the existing guards.

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
| Server destination lookup / guard priority | `10153` / `10154` | `10163` / `10164` |
| WWAN / UE IP / modem / bearer / AT port | Discover each run | Discover each run |

| Observed before the latest modem power cycle | UE1 | UE2 |
| --- | --- | --- |
| Modem / SIM / bearer | `6` / `6` / `4` | `5` / `5` / `3` |
| WWAN / IPv4 | `wwan1` / `10.45.0.2/30` | `wwan0` / `10.46.0.2/30` |
| AT port / USB device | `/dev/ttyUSB6` / `4-4` | `/dev/ttyUSB2` / `4-3` |
| Bearer gateway / MTU | `10.45.0.1` / `1400` | `10.46.0.1` / `1400` |

Rediscover these dynamic values after modem restart/reconnection. Both cells use
PLMN `00101`, TAC 7 and SST 1. DNN selects the UE pool; cell lock selects the DU.
UE1's earlier host allocation was `10.45.0.3/29` on `wwan0`; UE2's earlier
bearer 5 / `10.46.0.3/29` is also historical. Both now report connected 5GNR
under modem paths 9/10, but current SIM/cell/bearer/host-path checks remain needed.

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

After 1.1 succeeds, query UE1's current serving cell without opening minicom:

```bash
# UE1: $MODEM was selected using $EXPECTED_IMEI (863305041978437).
mmcli -L
mmcli -m "$MODEM"
sudo mmcli -m "$MODEM" --get-cell-info
```

Use the NR record marked `serving: yes`. For DU1, require PCI / `physical-ci`
`1` and Cell ID / `ci` `66C000` (hexadecimal; leading zeros may be omitted),
equivalent to NCI `6733824` in decimal. Both DUs use n78; check the actual
PCI/NCI to distinguish them. `$MODEM` belongs to this UE1 terminal and is
discovered by IMEI, so do not replace it with a remembered modem number.
Repeat this query after PDU establishment and before UL. If the option is
unsupported or the serving NR PCI/NCI is missing, use the AT readback below.
This query does not read or restore the cell lock; restore it below when needed.
See the [ModemManager cell-info interface](https://github.com/linux-mobile-broadband/ModemManager/blob/main/introspection/org.freedesktop.ModemManager1.Modem.xml).

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
address/table fields also support a verified existing path. Full cleanup uses
the role reset helper and its defined interface baseline, without old-session
metadata.

<a id="ue1-clean-old-path"></a>

### 1.4. Reset all UE1 host IPv4 state for a rebuild

Stop UE1's test traffic. For a fresh rebuild, run this role reset without
entering any historical IP/prefix/interface. It clears table `151`, priorities
`10151`–`10154`, any other IPv4 rule referencing table
`151`, and all `10.45.0.0/16` addresses on this role's current/orphan WWANs.
The helper also removes its legacy WWAN IPv4 routes in the main table and sets
the role's interfaces to DOWN / MTU 1500. Table 152 and the other UE's
addresses remain available. The current PDU stays connected for rebuilding.

If the existing path already matches the current verified bearer and works,
reuse it by going to 1.6. Otherwise execute the reset, require
`UE1 reset complete`, then proceed to 1.5:

```bash
sudo python3 ~/falcon-reset-ue-network.py --ue 1
ip -o -4 addr show
ip -4 rule show
ip -4 route show table 151
ip -4 route show default
```

An empty/absent table can report `FIB table does not exist`; that is expected
after reset. Keep the new bearer parameters read in 1.3 for 1.5; refresh
them if the modem/bearer/interface changed meanwhile. **Run 1.5's empty-table
preflight only after reset, never on an existing valid path.**

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
    assert priority not in (int(lookup), int(guard)), f'Rule priority {priority} already occupied: {rule}'
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

Stop on a setup failure and use the same role reset helper before retrying.
Keep `route-state.txt` as evidence; reset does not depend on it.
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

The source rules above support programs that bind UE1's IP, including the
iperf commands below. **Complete the destination lookup/guard installation here
to make ordinary `ping 10.45.0.1` select UE1. Reset plus 1.5 alone does not do
that.** Table 151's existing route supplies the current UE1 preferred source. Run this
after the source-bound checks pass and verify priorities `10153/10154` are
unused; inspect an occupied slot rather than adding duplicates.

```bash
ip -4 rule show
if ip -4 rule show | grep -Eq '^(10153|10154):'; then
  printf 'STOP: UE1 destination priorities occupied; inspect existing rules.\n'
else
  if printf 'destination_lookup=10153 destination_guard=10154 server=10.45.0.1 table=151\n' > "$UE_RUN/server-route-state.txt" &&
     sudo ip -4 rule add pref 10154 to 10.45.0.1/32 type unreachable &&
     sudo ip -4 rule add pref 10153 to 10.45.0.1/32 lookup 151; then
    if python3 - "$WWAN_IF" "$UE_IP" <<'PY'
import json, subprocess, sys
interface, source = sys.argv[1:]
routes = json.loads(subprocess.check_output(['ip', '-N', '-j', '-4', 'route', 'get', '10.45.0.1'], text=True))
assert len(routes) == 1, 'UE1: expected one unbound route'
route = routes[0]
assert route.get('dev') == interface and int(route.get('table', -1)) == 151 and route.get('prefsrc') == source, f'UE1: wrong unbound route: {route}'
print('UE1 unbound route: OK', route)
PY
    then
      ping -c 5 10.45.0.1
    else
      printf 'FAIL: ordinary traffic is not routed over UE1; stop before UL.\n'
    fi
  else
    printf 'FAIL: UE1 destination installation incomplete; stop before UL.\n'
  fi
fi
```

Require UE1's current WWAN, `table 151`, `src` equal to `$UE_IP`, and ping
replies. The destination guard prevents unbound traffic from falling through
to Wi-Fi if table 151 loses its server route. The Wi-Fi default stays available
for other destinations. With Wi-Fi off, repeat both the unbound and source-bound
checks; both must use UE1. This configuration targets only `10.45.0.1/32`.
The previous source-only recipe did not guarantee routing for an unbound ping.
Ping success over the Wi-Fi interface is not a passing UE check. The gate above
checks the unbound route's interface, table and source before sending the ping.

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

After 2.1 succeeds, query UE2's current serving cell without opening minicom:

```bash
# UE2: $MODEM was selected using $EXPECTED_IMEI (863305041980706).
mmcli -L
mmcli -m "$MODEM"
sudo mmcli -m "$MODEM" --get-cell-info
```

Use the NR record marked `serving: yes`. For DU2, require PCI / `physical-ci`
`2` and Cell ID / `ci` `66C001` (hexadecimal; leading zeros may be omitted),
equivalent to NCI `6733825` in decimal. Both DUs use n78; check the actual
PCI/NCI to distinguish them. `$MODEM` belongs to this UE2 terminal and is
discovered by IMEI, so do not replace it with a remembered modem number.
Repeat this query after PDU establishment and before UL. If the option is
unsupported or the serving NR PCI/NCI is missing, use the AT readback below.
This query does not read or restore the cell lock; restore it below when needed.
See the [ModemManager cell-info interface](https://github.com/linux-mobile-broadband/ModemManager/blob/main/introspection/org.freedesktop.ModemManager1.Modem.xml).

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
address/table fields also support a verified existing path. Full cleanup uses
the role reset helper and its defined interface baseline, without old-session
metadata.

<a id="ue2-clean-old-path"></a>

### 2.4. Reset all UE2 host IPv4 state for a rebuild

Stop UE2's test traffic. For a fresh rebuild, run this role reset without
entering any historical IP/prefix/interface. It clears table `152`, priorities
`10161`–`10164`, any other IPv4 rule referencing table
`152`, and all `10.46.0.0/16` addresses on this role's current/orphan WWANs.
The helper also removes its legacy WWAN IPv4 routes in the main table and sets
the role's interfaces to DOWN / MTU 1500. Table 151 and the other UE's
addresses remain available. The current PDU stays connected for rebuilding.

If the existing path already matches the current verified bearer and works,
reuse it by going to 2.6. Otherwise execute the reset, require
`UE2 reset complete`, then proceed to 2.5:

```bash
sudo python3 ~/falcon-reset-ue-network.py --ue 2
ip -o -4 addr show
ip -4 rule show
ip -4 route show table 152
ip -4 route show default
```

An empty/absent table can report `FIB table does not exist`; that is expected
after reset. Keep the new bearer parameters read in 2.3 for 2.5; refresh
them if the modem/bearer/interface changed meanwhile. **Run 2.5's empty-table
preflight only after reset, never on an existing valid path.**

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
    assert priority not in (int(lookup), int(guard)), f'Rule priority {priority} already occupied: {rule}'
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

Stop on a setup failure and use the same role reset helper before retrying.
Keep `route-state.txt` as evidence; reset does not depend on it.
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

The source rules above support programs that bind UE2's IP, including the
iperf commands below. **Complete the destination lookup/guard installation here
to make ordinary `ping 10.46.0.1` select UE2. Reset plus 2.5 alone does not do
that.** Table 152's existing route supplies the current UE2 preferred source. Run this
after the source-bound checks pass and verify priorities `10163/10164` are
unused; inspect an occupied slot rather than adding duplicates.

```bash
ip -4 rule show
if ip -4 rule show | grep -Eq '^(10163|10164):'; then
  printf 'STOP: UE2 destination priorities occupied; inspect existing rules.\n'
else
  if printf 'destination_lookup=10163 destination_guard=10164 server=10.46.0.1 table=152\n' > "$UE_RUN/server-route-state.txt" &&
     sudo ip -4 rule add pref 10164 to 10.46.0.1/32 type unreachable &&
     sudo ip -4 rule add pref 10163 to 10.46.0.1/32 lookup 152; then
    if python3 - "$WWAN_IF" "$UE_IP" <<'PY'
import json, subprocess, sys
interface, source = sys.argv[1:]
routes = json.loads(subprocess.check_output(['ip', '-N', '-j', '-4', 'route', 'get', '10.46.0.1'], text=True))
assert len(routes) == 1, 'UE2: expected one unbound route'
route = routes[0]
assert route.get('dev') == interface and int(route.get('table', -1)) == 152 and route.get('prefsrc') == source, f'UE2: wrong unbound route: {route}'
print('UE2 unbound route: OK', route)
PY
    then
      ping -c 5 10.46.0.1
    else
      printf 'FAIL: ordinary traffic is not routed over UE2; stop before UL.\n'
    fi
  else
    printf 'FAIL: UE2 destination installation incomplete; stop before UL.\n'
  fi
fi
```

Require UE2's current WWAN, `table 152`, `src` equal to `$UE_IP`, and ping
replies. The destination guard prevents unbound traffic from falling through
to Wi-Fi if table 152 loses its server route. The Wi-Fi default stays available
for other destinations. With Wi-Fi off, repeat both the unbound and source-bound
checks; both must use UE2. This configuration targets only `10.46.0.1/32`.
The previous source-only recipe did not guarantee routing for an unbound ping.
Ping success over the Wi-Fi interface is not a passing UE check. The gate above
checks the unbound route's interface, table and source before sending the ping.

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

Both UE sequences must pass their identity/cell/PDU/host-path checks before
concurrent traffic. The launcher discovers current modem/SIM/bearer paths by
IMEI/IMSI, reads the actual APN/IPv4/prefix/interface, and checks both source-bound
and ordinary destination routes. It contains no historical UE IP/interface tuple
to edit. Actual serving-cell/DU checks still come from 1.2/2.2; an IP/APN does
not prove the serving DU.

Save the updated launcher once on the laptop. This is the same self-contained
file as [`run_dual_ul.py`](../scripts/dual_fr1/run_dual_ul.py):

```bash
cat > ~/falcon-dual-ul.py <<'FALCON_DUAL_UL_PY'
#!/usr/bin/env python3
"""Discover both Falcon UE bearers, verify their routes, then run concurrent UL."""

import argparse
from datetime import datetime
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo


ROLES = (
    (1, "863305041978437", "001010000000101", "internet", "10.45.0.0/16", "10.45.0.1", 5201, 151),
    (2, "863305041980706", "001010000000102", "internet2", "10.46.0.0/16", "10.46.0.1", 5202, 152),
)


def read(*command):
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.PIPE,
                                       env=dict(os.environ, LC_ALL="C"))
    except subprocess.CalledProcessError as error:
        raise ValueError(f"{' '.join(command)}: {(error.stderr or '').strip() or 'command failed'}") from None


def kv(*command):
    return {key.strip(): value.strip() for key, value in
            (line.split(":", 1) for line in read(*command).splitlines() if ":" in line)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def field_values(info, name):
    """Read mmcli -K array .value[n] entries, or a scalar/comma-separated value."""
    indexed = []
    pattern = re.compile(re.escape(name) + r"\.value\[(\d+)\]")
    for key, value in info.items():
        match = pattern.fullmatch(key)
        if match:
            indexed.append((int(match[1]), value))
    values = [value for _, value in sorted(indexed)] if indexed else [info.get(name, "")]
    return {token.strip().lower() for value in values for token in value.split(",")
            if token.strip() not in ("", "--")}


def discover_roles():
    paths = sorted(set(re.findall(r"/org/freedesktop/ModemManager1/Modem/\d+", read("mmcli", "-L"))))
    modems = [(path, kv("mmcli", "-m", path, "-K")) for path in paths]
    result = []
    for ue, imei, imsi, apn, subnet, server, port, table in ROLES:
        tag = f"UE{ue}"
        matches = [(path, info) for path, info in modems if info.get("modem.generic.equipment-identifier") == imei]
        require(len(matches) == 1, f"{tag}: IMEI {imei} must match exactly one current modem")
        modem, info = matches[0]
        require(info.get("modem.generic.state") == "connected", f"{tag}: modem is not connected; complete its PDU/path sequence first")
        technologies = field_values(info, "modem.generic.access-technologies")
        require("5gnr" in technologies,
                f"{tag}: current access technology is not 5GNR; reported={sorted(technologies) or 'not reported'}")
        require(info.get("modem.3gpp.operator-code") == "00101", f"{tag}: wrong registered PLMN")
        sim = info.get("modem.generic.sim", "")
        require(re.fullmatch(r"/org/freedesktop/ModemManager1/SIM/\d+", sim), f"{tag}: no active SIM path")
        sim_info = kv("mmcli", "-i", sim, "-K")
        require(sim_info.get("sim.properties.active") == "yes" and sim_info.get("sim.properties.imsi") == imsi,
                f"{tag}: active SIM IMSI does not match {imsi}")
        bearer_matches = []
        for path in sorted(set(re.findall(r"/org/freedesktop/ModemManager1/Bearer/\d+", "\n".join(info.values())))):
            bearer = kv("mmcli", "-b", path, "-K")
            if bearer.get("bearer.status.connected") == "yes" and bearer.get("bearer.properties.apn") == apn:
                bearer_matches.append((path, bearer))
        require(len(bearer_matches) == 1, f"{tag}: expected exactly one connected {apn} bearer")
        bearer_path, bearer = bearer_matches[0]
        require(bearer.get("bearer.status.suspended") == "no" and bearer.get("bearer.ipv4-config.method") == "static",
                f"{tag}: bearer is suspended or lacks a static IPv4 configuration")
        source = str(ipaddress.IPv4Address(bearer.get("bearer.ipv4-config.address", "")))
        prefix = int(bearer.get("bearer.ipv4-config.prefix", "-1"))
        ipaddress.IPv4Interface(f"{source}/{prefix}")
        require(ipaddress.IPv4Address(source) in ipaddress.IPv4Network(subnet) and source != server,
                f"{tag}: bearer IPv4 is outside {subnet}")
        interface = bearer.get("bearer.status.interface", "")
        ports = set(re.findall(r"([A-Za-z0-9_.-]+)\s+\(net\)", "\n".join(
            value for key, value in info.items() if key.startswith("modem.generic.ports"))))
        require(re.fullmatch(r"(?:wwan|wwp|rmnet)[A-Za-z0-9_.-]*", interface) and interface in ports,
                f"{tag}: bearer interface does not belong to the selected modem")
        # Record the bearer default gateway; verify_routes checks the server's host route.
        gateway = bearer.get("bearer.ipv4-config.gateway") or None
        if gateway == "--":
            gateway = None
        identity = info.get("modem.generic.device-identifier", "")
        require(identity not in ("", "--"), f"{tag}: missing current modem device identifier")
        result.append({"ue": ue, "imei": imei, "imsi": imsi, "apn": apn, "modem": modem,
                       "device_identifier": identity, "sim": sim, "bearer": bearer_path,
                       "source": source, "prefix": prefix, "interface": interface, "gateway": gateway,
                       "server": server, "port": port, "table": table})
    require(len({role["source"] for role in result}) == 2 and len({role["interface"] for role in result}) == 2,
            "The two roles must have different current source addresses and dedicated WWAN interfaces")
    return result


def verify_routes(roles):
    addresses = json.loads(read("ip", "-j", "-4", "addr", "show"))
    for role in roles:
        tag = f"UE{role['ue']}"
        matching = [(device, address) for device in addresses for address in device.get("addr_info", [])
                    if address.get("local") == role["source"]]
        require(len(matching) == 1 and matching[0][0].get("ifname") == role["interface"]
                and matching[0][1].get("prefixlen") == role["prefix"],
                f"{tag}: current bearer address/prefix is not installed on its WWAN; rebuild the host path")
        for bound in (True, False):
            command = ["ip", "-N", "-j", "-4", "route", "get", role["server"]]
            if bound:
                command.extend(["from", role["source"]])
            routes = json.loads(read(*command))
            require(len(routes) == 1 and routes[0].get("dev") == role["interface"]
                    and int(routes[0].get("table", -1)) == role["table"],
                    f"{tag}: {'source-bound' if bound else 'ordinary'} traffic does not use its WWAN/table {role['table']}; complete step {role['ue']}.6")
            if not bound:
                require(routes[0].get("prefsrc") == role["source"], f"{tag}: ordinary traffic selects the wrong source address")


def stamp():
    return datetime.now(ZoneInfo("America/New_York")).isoformat()


def run(seconds=60, check_only=False, output_root="/tmp"):
    roles = discover_roles()
    verify_routes(roles)
    for role in roles:
        print(f"UE{role['ue']}: IMEI={role['imei']} IMSI={role['imsi']} bearer={role['bearer']} "
              f"{role['source']}/{role['prefix']} dev={role['interface']} table={role['table']} "
              f"gateway={role['gateway'] or 'not reported'} -> {role['server']}:{role['port']}", flush=True)
    if check_only:
        print("Both current bearer/host routes checked; no iperf traffic started")
        return 0
    require(discover_roles() == roles, "Modem/SIM/bearer identity changed during preflight; recheck before traffic")
    verify_routes(roles)
    directory = Path(tempfile.mkdtemp(prefix="falcon-dual-ul-", dir=output_root))
    result = {"status": "running", "started_at": stamp(), "links": [
        dict(role, log=str(directory / f"ue{role['ue']}.log"), pid=None, exit_code=None) for role in roles]}
    jobs = []
    print("Evidence:", directory, "START:", result["started_at"], flush=True)
    try:
        for link in result["links"]:
            stream = Path(link["log"]).open("w")
            try:
                process = subprocess.Popen(["iperf3", "-c", link["server"], "-p", str(link["port"]),
                    "-B", link["source"], "-t", str(seconds), "-i", "1", "--get-server-output"],
                    stdout=stream, stderr=subprocess.STDOUT)
            except BaseException:
                stream.close()
                raise
            link["pid"] = process.pid
            jobs.append((link, process, stream))
        for link, process, stream in jobs:
            link["exit_code"] = process.wait()
            link["ended_at"] = stamp()
            stream.close()
            print(f"UE{link['ue']} exit={link['exit_code']}", flush=True)
            for line in Path(link["log"]).read_text().splitlines():
                if any(word in line for word in ("sender", "receiver", "iperf Done", "error")):
                    print(f"UE{link['ue']}: {line}")
        result["status"] = "completed" if all(link["exit_code"] == 0 for link in result["links"]) else "failed"
    except (OSError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        result["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "aborted"
        result["error"] = str(error) or "KeyboardInterrupt"
        for link, process, stream in jobs:
            if process.poll() is None:
                process.terminate()
            try:
                link["exit_code"] = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                link["exit_code"] = process.wait()
            link["ended_at"] = stamp()
            stream.close()
    finally:
        result["ended_at"] = stamp()
        (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        print("END:", result["ended_at"], "STATUS:", result["status"], "Evidence:", directory, flush=True)
    return 0 if result["status"] == "completed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true", help="Read current identities/bearers/routes without starting traffic")
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("--seconds must be in 1..3600")
    try:
        return run(args.seconds, args.check_only)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"STOP: {error}; no dual UL run accepted", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
FALCON_DUAL_UL_PY
```

The launcher reads `mmcli -K` access technologies from `.value[n]` array
entries as well as a scalar value. An absent parent key is not evidence of
a non-5G connection. Missing actual technology reports and LTE-only reports
still fail preflight. See the [ModemManager output implementation](https://github.com/linux-mobile-broadband/ModemManager/blob/main/cli/mmcli-output.c).

The bearer gateway is its reported default gateway; the launcher records it in
the role summary and `summary.json`. It can differ from the server address or
be unreported. The actual source-bound and ordinary routes to each server must
still select that role's current WWAN, table 151/152 and current bearer address.
See the [ModemManager bearer IP configuration](https://github.com/linux-mobile-broadband/ModemManager/blob/main/introspection/org.freedesktop.ModemManager1.Bearer.xml).

Read-only preflight, without starting iperf or creating traffic logs:

```bash
python3 ~/falcon-dual-ul.py --check-only
```

Require both current role summaries and `Both current bearer/host routes checked`.
If UE2 is not connected, complete its sequence first. A missing current WWAN
address needs 1.5/2.5 rebuilding; a wrong ordinary route needs 1.6/2.6. Do not
substitute an old address to bypass a failed preflight.

Then start Spark step 7's 120-second diagnostic capture and wait for
`FALCON_CAPTURE subscriptions_kpm=2`. Keep both Spark servers, DUs, CU and RIC
running. Launch both UL clients from one laptop terminal:

```bash
python3 ~/falcon-dual-ul.py
```

This measured run rereads the current metadata/routes before starting either
client, uses both actual source addresses, creates a fresh `/tmp/falcon-dual-ul-*`
directory and records each process's real exit code with its modem/SIM/bearer/
interface/IP identity in `summary.json`. A preflight failure starts neither
client. A partial launch failure or Ctrl+C stops its started clients and records
an aborted/interrupted run. No Bash PID variables are needed.

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
if ip -4 route get "$PATH_SERVER"; then
  printf 'FAIL: unbound destination fell through; inspect its destination rules.\n'
else
  printf 'Destination guard: OK (private destination unreachable).\n'
fi
sudo ip -4 route add table "$PATH_TABLE" "$PATH_SERVER/32" dev "$PATH_IF" src "$PATH_IP"
ip -4 route get "$PATH_SERVER" from "$PATH_IP"
ip -4 route get "$PATH_SERVER"
```

Repeat for the other UE. Confirm the unaffected link survives. Verify counters/
captures on the intended WWAN and repeat after an actual bearer disconnect/
reattachment with refreshed identities. A route lookup alone is not packet-path
acceptance.

<a id="cleanup"></a>

## 4. Finish tests and reset each role

Stop clients and let the finite Spark xApp delete subscriptions and finish.
Use the same helper for a complete role reset and add `--disconnect` to end its
current connected PDU. No saved `PATH_*`, original IP/CIDR/interface, modem index
or old MTU/state is needed. This resets the role to the defined DOWN / MTU 1500
baseline rather than reconstructing an earlier session.

### 4.1. Final UE1 reset — table 151

```bash
sudo python3 ~/falcon-reset-ue-network.py --ue 1 --disconnect
ip -o -4 addr show
ip -4 rule show
ip -4 route show table 151
ip -4 route show default
```

Require `UE1 reset complete`. UE2 and Wi-Fi remain available.

### 4.2. Final UE2 reset — table 152

```bash
sudo python3 ~/falcon-reset-ue-network.py --ue 2 --disconnect
ip -o -4 addr show
ip -4 rule show
ip -4 route show table 152
ip -4 route show default
```

Require `UE2 reset complete`. After both laptop roles are reset, use
[Spark step 8](dual_ue_spark_quick_commands.md#8-shutdown-and-retained-evidence)
for server/RAN/core shutdown. Retain identity/cell/bearer/path/UL/KPM correlation
and restart/guard/survivor observations; full acceptance remains pending.
