# Dual UE Laptop Quick Commands — UE IP Binding and UL

Updated: 2026-10-24. Developer: Ruibin Chen. Pair this booklet with the updated
[Spark Quick Commands](dual_ue_spark_quick_commands.md) to reproduce the October 21
CU/DU/Core UE IP binding. Spark now starts RIC with the identity plugin, then
CU with its identity E2 overlay, both DUs and the new three-subscription xApp.
Laptop still prepares each intended modem/SIM/cell/PDU/route independently.

Spark's October 23 [TUN split](networking/dual_ue_tun_split.md) is applied: `ogstun_1`
serves `10.45.0.1` and `ogstun_2` serves `10.46.0.1`. Laptop APNs, service IPs
and policy tables are retained; WWAN names and bearer parameters still require
fresh discovery. After the SMF/UPF restart, re-enable each selected modem and
repeat its complete sequence below. Post-split traffic is retained in the
[October 23 MPTCP report](reports/mptcp_video_experiment_report_2026-10-23.md);
fresh UE2 PDU/IP recovery and both ping modes passed in the
[October 24 report](reports/ue2_fr3_recovery_experiment_report_2026-10-24.md).

**Acceptance scope, 2026-10-24:** cold-start, full repeatability/comparative
and bidirectional disturbance/survivor testing are
[supplemental experiments](development/dual_ue_supplemental_experiments.md),
excluded from current acceptance criteria and merge prerequisites.

The [live report](reports/ue_identity_dual_ue_live_2026-10-21.md) describes the
final implementation and six-minute bidirectional idle/resume validation
(645 matched / 648, zero cached). The new run must verify its own
current identities/IPs. Strict serving-DU/lifecycle proof, restart/reuse and
remaining performance gates are separate in [Plan 4](../plans/cu-ue-ip-e2-binding.md).
The [October 13 UL/KPM results](evidence/2026-10-13_dual_kpm_reports/manifest.json)
remain historical [Plan 3](../plans/dual-ue-du-fr1-channels.md) evidence.

Run all commands in this file on the UE laptop. Use Bash, one terminal per UE
for modem/bearer/path variables, and stop at failed checks. Spark startup, servers
and KPM capture are in [Dual UE Spark Quick Commands](dual_ue_spark_quick_commands.md).

## Manual startup order

This booklet starts the two UEs **manually**, one step at a time. Complete the
section 0 tool/helper preparation, then follow the full
[UE1 sequence](#ue1-start) first and the full [UE2 sequence](#ue2-start) in another
fresh Bash terminal. Both DUs and the required Spark servers must already be
running; Spark startup is in the paired booklet.

For each role, select the current modem by IMEI and verify its active SIM
(section 1.1 / 2.1), enable it if disabled, then check the serving cell and
restore its lock if needed (1.2 / 2.2). Continue with registration/PDU checks,
fresh bearer discovery, host IPv4 reset, policy routing and both bound and
ordinary ping (1.3–1.6 / 2.3–2.6). Run UL only after those checks pass.

Keep each role's terminal and variables for later traffic checks and shutdown.
Keep UE1's verified PDU/path active while preparing UE2. After a modem power or
reconnection event, repeat the affected role's complete manual sequence using
fresh modem, bearer, IP and interface values. Stop at any failed check.

The October 21 Laptop truth identified UE1 as IMSI `001010000000101`, APN `internet`,
IPv4 `10.45.0.2`, and UE2 as IMSI `001010000000102`, APN `internet2`, IPv4
`10.46.0.2`. These are historical allocations: rediscover modem/SIM/bearer,
IPv4/prefix/interface/gateway and routes on every new run. F1AP/NGAP IDs can
change after idle/resume too. KPM does not carry IMEI/IMSI/IP directly; Spark's
xApp associates CU/DU E2 identities with read-only AMF/SMF data. Compare its
output with Laptop truth and actual captured source events independently.

Daily sequence: complete sections 1 and 2 → install/reuse the section 3 helper
and run `--check-only` → Spark 7a plus Laptop's 60-second concurrent upload →
[section 3.1](#binding-idle) plus Spark 7b for the six-minute idle/resume test →
retain evidence → shutdown. All test launches are explicit operator commands.
The idle test is a pasted command using the existing helper; it requires no
file transfer or additional installed script. UDP and path-loss tests in 3.2
are separate optional Plan 3 work, not prerequisites for this binding repeat.

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
For the end of an experiment, `--shutdown` disconnects the selected modem,
clears its host IPv4 path, deletes all its listed bearer objects (including old
disconnected bearers) and disables it. It rereads the selected IMEI before modem
operations and requires zero bearers plus modem state `disabled` before reporting
shutdown complete. If this helper is already installed on Laptop, repeat this
installation block to replace the old copy; `--help` must list `--shutdown`.

```bash
cat > ~/falcon-reset-ue-network.py <<'FALCON_RESET_PY'
#!/usr/bin/env python3
"""Reset or shut down one Falcon laptop UE from current state, without session history."""

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


def mm_kv(*command):
    return {key.strip(): value.strip() for key, value in
            (line.split(":", 1) for line in read(*command).splitlines() if ":" in line)}


def checked_modem(path, imei):
    info = mm_kv("mmcli", "-m", path, "-K")
    if info.get("modem.generic.equipment-identifier") != imei:
        raise ValueError("Modem identity changed; stop before touching another modem")
    return info


def bearer_paths(info):
    return sorted(set(re.findall(r"/org/freedesktop/ModemManager1/Bearer/\d+", "\n".join(
        value for key, value in info.items() if key.startswith("modem.generic.bearers")))))


def shutdown_modem(path, imei):
    for bearer in bearer_paths(checked_modem(path, imei)):
        if bearer not in bearer_paths(checked_modem(path, imei)):
            continue
        details = mm_kv("mmcli", "-b", bearer, "-K")
        if details.get("bearer.status.connected") != "no":
            raise ValueError("Bearer remains connected or was reconnected; stop shutdown and inspect its connection owner")
        if bearer not in bearer_paths(checked_modem(path, imei)):
            continue
        change("mmcli", "-m", path, f"--delete-bearer={bearer}")
    info = checked_modem(path, imei)
    if bearer_paths(info):
        raise ValueError("Bearers remain or were recreated; modem shutdown is incomplete")
    if info.get("modem.generic.state") != "disabled":
        change("mmcli", "-m", path, "--disable")
    info = checked_modem(path, imei)
    if info.get("modem.generic.state") != "disabled" or bearer_paths(info):
        raise ValueError("Modem is not disabled with zero bearers; shutdown is incomplete")


def modem_inventory():
    inventory = []
    for path in sorted(set(re.findall(r"/org/freedesktop/ModemManager1/Modem/\d+", read("mmcli", "-L")))):
        kv = mm_kv("mmcli", "-m", path, "-K")
        ports = set(re.findall(r"([A-Za-z0-9_.-]+)\s+\(net\)", "\n".join(
            value for key, value in kv.items() if key.startswith("modem.generic.ports"))))
        inventory.append((path, kv.get("modem.generic.equipment-identifier"), ports, kv.get("modem.generic.state")))
    return inventory


def reset(ue, dry_run=False, disconnect=False, shutdown=False, *, inventory=None):
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
        inventory = modem_inventory() if inventory is None else inventory
    except (subprocess.CalledProcessError, FileNotFoundError):
        if pool_devices:
            raise ValueError("Cannot read current modem ownership; start ModemManager before address reset") from None
        inventory = []
    selected = [modem for modem in inventory if modem[1] == imei]
    if len(selected) > 1:
        raise ValueError("Expected IMEI matches multiple modems")
    shutdown_info = None
    if shutdown:
        if not selected:
            raise ValueError(f"UE{ue} modem is absent; use --ue {ue} without --shutdown for leftover IPv4 cleanup")
        shutdown_info = checked_modem(selected[0][0], imei)
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
    connected = bool(selected and selected[0][3] == "connected")
    if shutdown:
        connected = connected or shutdown_info.get("modem.generic.state") in ("connecting", "disconnecting")
        for bearer in bearer_paths(shutdown_info):
            connected = connected or mm_kv("mmcli", "-b", bearer, "-K").get("bearer.status.connected") == "yes"
    if (disconnect or shutdown) and selected and connected:
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
        if shutdown:
            for bearer in bearer_paths(shutdown_info):
                print("would run: " + shlex.join(("mmcli", "-m", selected[0][0], f"--delete-bearer={bearer}")))
            if shutdown_info.get("modem.generic.state") != "disabled":
                print("would run: " + shlex.join(("mmcli", "-m", selected[0][0], "--disable")))
        return
    for command in commands:
        if command[0] == "mmcli":
            checked_modem(command[2], imei)
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
    def verify_cleared():
        remaining_routes = ip_json("route", "show", "table", "main")
        remaining_addresses = ip_json("addr", "show")
        if (any(ipaddress.IPv4Address(info["local"]) in pool for device in remaining_addresses for info in device.get("addr_info", []))
                or ip_json("route", "show", "table", str(table)) or any(role_rule(rule) for rule in ip_json("rule", "show"))
                or any(route.get("dev") in targets or (route.get("dev") in legacy_devices
                       and route.get("dst", "default") != "default"
                       and ipaddress.IPv4Network(route["dst"], strict=False).subnet_of(pool)) for route in remaining_routes)):
            raise ValueError("Role IPv4 addresses/routes/rules remain or were recreated; reset is incomplete")
    verify_cleared()
    if shutdown:
        shutdown_modem(selected[0][0], imei)
        verify_cleared()
    print(f"UE{ue} reset complete: role IPv4 addresses, routes and policy rules cleared; WWAN baseline DOWN / MTU 1500")
    if shutdown:
        print(f"UE{ue} shutdown complete: IMEI={imei}; modem={selected[0][0]}; bearers=0; state=disabled")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ue", required=True, type=int, choices=(1, 2))
    parser.add_argument("--dry-run", action="store_true", help="Show the current reset scope without changes")
    parser.add_argument("--disconnect", action="store_true", help="Also disconnect this IMEI's current connected PDU")
    parser.add_argument("--shutdown", action="store_true", help="Disconnect, reset IPv4, delete all selected-modem bearers and disable it")
    args = parser.parse_args()
    if not args.dry_run and os.geteuid() != 0:
        parser.error("Run reset with sudo; --dry-run can run without sudo")
    try:
        reset(args.ue, args.dry_run, args.disconnect, args.shutdown)
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
| Spark TUN interface | `ogstun_1` | `ogstun_2` |
| Spark iperf3 port | `5201` | `5202` |
| Proposed policy table / lookup / guard priority | `151` / `10151` / `10152` | `152` / `10161` / `10162` |
| Server destination lookup / guard priority | `10153` / `10154` | `10163` / `10164` |
| Reset-surviving destination block priority | `20151` | `20152` |
| WWAN / UE IP / modem / bearer / AT port | Discover each run | Discover each run |

| Observed before the latest modem power cycle | UE1 | UE2 |
| --- | --- | --- |
| Modem / SIM / bearer | `6` / `6` / `4` | `5` / `5` / `3` |
| WWAN / IPv4 | `wwan1` / `10.45.0.2/30` | `wwan0` / `10.46.0.2/30` |
| AT port / USB device | `/dev/ttyUSB6` / `4-4` | `/dev/ttyUSB2` / `4-3` |
| Bearer gateway / MTU | `10.45.0.1` / `1400` | `10.46.0.1` / `1400` |

The **2026-10-24 operator serial listing** now resolves the AT ports as follows.
The older observation table above retains its original port numbering.

| Role | `AT_PORT` (preferred by-path) | Current tty device |
| --- | --- | --- |
| UE1 / FR1, USB `4-4` | `/dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.2-port0` | `/dev/ttyUSB2` |
| UE2 / FR3, USB `4-3` | `/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0` | `/dev/ttyUSB6` |

Sections 1.2 / 2.2 use these by-path values. If USB sockets change, rediscover
the paths; verify the selected role's serial identity before lock writes.

Rediscover these dynamic values after modem restart/reconnection. Both cells use
PLMN `00101`, TAC 7 and SST 1. DNN selects the UE pool; cell lock selects the DU.
The table above and earlier modem 9/10 or 13/14, bearer 7/8 or 9/10 and
`10.45.0.3/29` / `10.46.0.3/29` allocations are historical examples.
Recheck serving-cell correlation separately; the launcher does not query the
serving DU. The October 21 xApp supplies the separate CU/Core/DU association.

Treat locks as needing restoration after modem power/reconnection: the
operator reported a lock query of `0`, with affected role unspecified. See the
[power-cycle observation](evidence/2026-10-13_modem_lock_power_cycle/manifest.json).
A generic [Quectel support response](https://forums.quectel.com/t/rmu500-ek-to-prevent-from-handover/11554)
describes NV saving, but this device's actual readback is the operational gate.
A correct APN/subnet does not bind a SIM to a DU in the shared PLMN. Require the
exact lock, actual PCI/NCI/SSB and SA before PDU/routes; recheck the cell after
PDU establishment and before UL. Controlled cold-start restoration remains pending.

<a id="block-wifi-fallback"></a>

### 0.2. Block ordinary ping and test traffic from falling back to Wi-Fi

**Use the guarded reset blocks in 1.4 / 2.4.** Before clearing a role's host
path, they install an independent destination `unreachable` rule: priority
`20151` for `10.45.0.1/32`, or `20152` for `10.46.0.1/32`. These rules run before
the main-table Wi-Fi route (priority `32766`) and survive the reset helper's
cleanup of tables 151/152 and priorities 10151–10154 / 10161–10164.
The bare section 0.1 helper does not install these extra blocks.

After reset, ordinary `ping 10.45.0.1` / `ping 10.46.0.1` and TCP/UDP traffic
to that role's server must fail with an unreachable error, rather than succeed
over Wi-Fi. Each reset block checks the route and ordinary ping before allowing
a rebuild. Only these two IPv4 service destinations are covered; Wi-Fi stays
connected with its default route for SSH, management and other destinations.
This does not force general Internet traffic onto the UEs.

Sections 1.5 / 2.5 install all four normal role rules together: source lookup,
source guard, destination lookup and destination guard. Their priorities precede
`20151/20152`, so a healthy path sends both bound and ordinary traffic through
the correct WWAN/table. Sections 1.6 / 2.6 verify both routes before ping/UL.
A source-bound ping alone does not establish the path of an ordinary ping.

The independent blocks remain after shutdown and repeated resets. They are
runtime kernel rules, so rerun the guarded sequence after a laptop reboot;
this is not a persistent firewall installation. If a reserved block priority
contains a different rule, stop and inspect it. Do not delete an occupied slot
or add duplicates to make the command pass. A reused path must pass 1.6 / 2.6;
rebuild an old source-only path with 1.4–1.6 / 2.4–2.6.

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
readiness, use its actual QMI port and the [USIM check](single_ue/ue_laptop_quick_commands.md#1a-read-the-inserted-sim-and-usim-state).

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
AT_PORT=/dev/serial/by-path/pci-0000:00:14.0-usb-0:4:1.2-port0
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
reuse it only after 1.6 verifies both bound and ordinary routes. Otherwise use
this guarded reset. It installs the independent destination block **before**
removing the path, requires `UE1 reset complete`, and checks that ordinary
traffic is blocked after reset. Require `UE1 Wi-Fi fallback blocked: OK`
before proceeding to 1.5:

```bash
reset_ue1_block_wifi() {
  local rules block_rule
  rules=$(ip -4 rule show) || return 1
  block_rule=$(awk '$1 == "20151:" {$1=$1; print}' <<< "$rules")
  case "$block_rule" in
    '') sudo ip -4 rule add pref 20151 to 10.45.0.1/32 type unreachable || return 1 ;;
    '20151: from all to 10.45.0.1 unreachable'|'20151: from all to 10.45.0.1/32 unreachable') : ;;
    *) printf 'STOP: priority 20151 occupied; inspect before reset.\n'; return 1 ;;
  esac
  sudo python3 ~/falcon-reset-ue-network.py --ue 1 || return 1
  if ip -4 route get 10.45.0.1; then
    printf 'STOP: UE1 server is still routable after reset; inspect earlier policy rules.\n'
    return 1
  fi
  if ping -c 1 -W 1 10.45.0.1; then
    printf 'STOP: UE1 ordinary ping still succeeds after reset.\n'
    return 1
  fi
  printf 'UE1 Wi-Fi fallback blocked: OK\n'
}
if reset_ue1_block_wifi; then
  ip -o -4 addr show
  ip -4 rule show
  ip -4 route show table 151 || true
  ip -4 route show default
else
  printf 'STOP: guarded reset/check failed; do not rebuild or start traffic.\n'
fi
```

An empty/absent table can report `FIB table does not exist`; that is expected
after reset. Keep the new bearer parameters read in 1.3 for 1.5; refresh
them if the modem/bearer/interface changed meanwhile. **Run 1.5's empty-table
preflight only after reset, never on an existing valid path.**

<a id="ue1-build-path"></a>

### 1.5. Build UE1's fresh table 151 and rules

Reinspect table `151` and priorities `10151`–`10154`; require all four
slots free for a new path. Keep the independent priority-20151 block installed.
Use the just-read bearer IP/prefix/MTU/interface. This preflight refuses
collisions and an earlier matching policy rule:

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
    assert priority not in (int(lookup), int(guard), int(lookup) + 2, int(guard) + 2), f'Rule priority {priority} already occupied: {rule}'
    assert table_number(rule.get('table')) != int(table), 'Routing table already referenced'
    if priority < int(lookup) and not (priority == 0 and table_number(rule.get('table')) == 255):
        assert not rule.get('not') and 'not' not in rule.get('flags', []), 'Inverted earlier policy rule requires review'
        assert not (contains(rule.get('src'), source) and contains(rule.get('dst'), destination)), 'Matching earlier policy rule requires review'
routes = subprocess.run(['ip', '-j', '-4', 'route', 'show', 'table', table], capture_output=True, text=True)
if routes.returncode:
    assert 'FIB table does not exist' in routes.stderr, routes.stderr
else:
    assert not json.loads(routes.stdout), 'Routing table already has routes'
blocks = [rule for rule in rules if rule.get('priority') == 20151]
assert len(blocks) == 1, 'Run the guarded reset first: missing/duplicate reset block'
block = blocks[0]
assert block.get('src', 'all') == 'all' and block.get('dst') in ('10.45.0.1', '10.45.0.1/32') and block.get('action') == 'unreachable', f'Wrong reset block: {block}'
print('Policy slots and IPv4 parameters: OK')
PY
```

Require `Policy slots and IPv4 parameters: OK`. Install the source and
destination guards before exposing the source address, then install both
lookups. Save this run's ownership values and destination-rule record:

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
    > "$UE_RUN/route-state.txt" || return 1
  printf 'destination_lookup=10153 destination_guard=10154 server=10.45.0.1 table=151\n' \
    > "$UE_RUN/server-route-state.txt" || return 1
  sudo ip -4 rule add pref 10152 from "$PATH_IP/32" to 10.45.0.1/32 type unreachable &&
  sudo ip -4 rule add pref 10154 to 10.45.0.1/32 type unreachable &&
  sudo ip link set dev "$PATH_IF" mtu "$UE_MTU" up &&
  sudo ip -4 addr add "$PATH_CIDR" dev "$PATH_IF" noprefixroute &&
  sudo ip -4 route add table 151 10.45.0.1/32 dev "$PATH_IF" src "$PATH_IP" &&
  sudo ip -4 rule add pref 10151 from "$PATH_IP/32" to 10.45.0.1/32 lookup 151 &&
  sudo ip -4 rule add pref 10153 to 10.45.0.1/32 lookup 151
}
if prepare_dual_path; then
  ip -4 route get 10.45.0.1 from "$PATH_IP"
  ip -4 route get 10.45.0.1
  ip -4 route show default
  printf 'UE1 rules installed; complete 1.6 before traffic.\n'
else
  printf 'FAIL: path setup incomplete; stop and clean only this run.\n'
fi
```

Stop on a setup failure and repeat 1.4's guarded reset before retrying.
Keep `route-state.txt` and `server-route-state.txt` as evidence; reset does not
depend on them. The independent block remains installed throughout rebuilding.
The setup requires a dedicated QMI interface with no existing IPv4 address or
default route. Resolve unexpected interface ownership before continuing.

### 1.6. Verify bound and ordinary routes, private ping and management routing

Section 1.5 already installed all four role rules; this block only verifies
them. Require both route lookups to select UE1's current WWAN and table
`151`, and the ordinary lookup's preferred source to equal `$UE_IP`.
Reused paths must also have the independent reset block. Do not accept ping
success over Wi-Fi as a UE check.

```bash
ip -4 rule show
ip -4 route show table 151
if python3 - "$WWAN_IF" "$UE_IP" <<'PY'
import json, subprocess, sys
interface, source = sys.argv[1:]
rules = json.loads(subprocess.check_output(['ip', '-j', '-4', 'rule', 'show'], text=True))
blocks = [rule for rule in rules if rule.get('priority') == 20151]
assert len(blocks) == 1, 'UE1: run 1.4–1.6 to install the reset block'
block = blocks[0]
assert block.get('src', 'all') == 'all' and block.get('dst') in ('10.45.0.1', '10.45.0.1/32') and block.get('action') == 'unreachable', f'UE1: wrong reset block: {block}'
for mode, extra in [('source-bound', ['from', source]), ('ordinary', [])]:
    routes = json.loads(subprocess.check_output(['ip', '-N', '-j', '-4', 'route', 'get', '10.45.0.1', *extra], text=True))
    assert len(routes) == 1, f'UE1: expected one {mode} route'
    route = routes[0]
    assert route.get('dev') == interface and int(route.get('table', -1)) == 151, f'UE1: wrong {mode} route: {route}'
    if mode == 'ordinary':
        assert route.get('prefsrc') == source, f'UE1: wrong ordinary source: {route}'
    print(f'UE1 {mode} route: OK', route)
PY
then
  ping -I "$UE_IP" -c 5 10.45.0.1 &&
  ping -c 5 10.45.0.1 &&
  ip -4 route show default
else
  printf 'STOP: UE1 route verification failed; use 1.4–1.6 to reset/rebuild before traffic.\n'
fi
```

Require both ping checks to pass and the management Wi-Fi default to remain
intact. Save `PATH_*` values and recheck cell/SA after reconnect/reattachment.
The destination guard blocks ordinary traffic if table 151 loses its server
route; independent priority `20151` continues blocking after a reset removes
the four role rules. Other destinations can still use Wi-Fi.
An old source-only path must be reset/rebuilt with 1.4–1.6; do not skip the
destination rules or add duplicate priorities on top of an existing path.

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
readiness, use its actual QMI port and the [USIM check](single_ue/ue_laptop_quick_commands.md#1a-read-the-inserted-sim-and-usim-state).

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
AT_PORT=/dev/serial/by-path/pci-0000:00:14.0-usb-0:3:1.2-port0
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
reuse it only after 2.6 verifies both bound and ordinary routes. Otherwise use
this guarded reset. It installs the independent destination block **before**
removing the path, requires `UE2 reset complete`, and checks that ordinary
traffic is blocked after reset. Require `UE2 Wi-Fi fallback blocked: OK`
before proceeding to 2.5:

```bash
reset_ue2_block_wifi() {
  local rules block_rule
  rules=$(ip -4 rule show) || return 1
  block_rule=$(awk '$1 == "20152:" {$1=$1; print}' <<< "$rules")
  case "$block_rule" in
    '') sudo ip -4 rule add pref 20152 to 10.46.0.1/32 type unreachable || return 1 ;;
    '20152: from all to 10.46.0.1 unreachable'|'20152: from all to 10.46.0.1/32 unreachable') : ;;
    *) printf 'STOP: priority 20152 occupied; inspect before reset.\n'; return 1 ;;
  esac
  sudo python3 ~/falcon-reset-ue-network.py --ue 2 || return 1
  if ip -4 route get 10.46.0.1; then
    printf 'STOP: UE2 server is still routable after reset; inspect earlier policy rules.\n'
    return 1
  fi
  if ping -c 1 -W 1 10.46.0.1; then
    printf 'STOP: UE2 ordinary ping still succeeds after reset.\n'
    return 1
  fi
  printf 'UE2 Wi-Fi fallback blocked: OK\n'
}
if reset_ue2_block_wifi; then
  ip -o -4 addr show
  ip -4 rule show
  ip -4 route show table 152 || true
  ip -4 route show default
else
  printf 'STOP: guarded reset/check failed; do not rebuild or start traffic.\n'
fi
```

An empty/absent table can report `FIB table does not exist`; that is expected
after reset. Keep the new bearer parameters read in 2.3 for 2.5; refresh
them if the modem/bearer/interface changed meanwhile. **Run 2.5's empty-table
preflight only after reset, never on an existing valid path.**

<a id="ue2-build-path"></a>

### 2.5. Build UE2's fresh table 152 and rules

Reinspect table `152` and priorities `10161`–`10164`; require all four
slots free for a new path. Keep the independent priority-20152 block installed.
Use the just-read bearer IP/prefix/MTU/interface. This preflight refuses
collisions and an earlier matching policy rule:

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
    assert priority not in (int(lookup), int(guard), int(lookup) + 2, int(guard) + 2), f'Rule priority {priority} already occupied: {rule}'
    assert table_number(rule.get('table')) != int(table), 'Routing table already referenced'
    if priority < int(lookup) and not (priority == 0 and table_number(rule.get('table')) == 255):
        assert not rule.get('not') and 'not' not in rule.get('flags', []), 'Inverted earlier policy rule requires review'
        assert not (contains(rule.get('src'), source) and contains(rule.get('dst'), destination)), 'Matching earlier policy rule requires review'
routes = subprocess.run(['ip', '-j', '-4', 'route', 'show', 'table', table], capture_output=True, text=True)
if routes.returncode:
    assert 'FIB table does not exist' in routes.stderr, routes.stderr
else:
    assert not json.loads(routes.stdout), 'Routing table already has routes'
blocks = [rule for rule in rules if rule.get('priority') == 20152]
assert len(blocks) == 1, 'Run the guarded reset first: missing/duplicate reset block'
block = blocks[0]
assert block.get('src', 'all') == 'all' and block.get('dst') in ('10.46.0.1', '10.46.0.1/32') and block.get('action') == 'unreachable', f'Wrong reset block: {block}'
print('Policy slots and IPv4 parameters: OK')
PY
```

Require `Policy slots and IPv4 parameters: OK`. Install the source and
destination guards before exposing the source address, then install both
lookups. Save this run's ownership values and destination-rule record:

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
    > "$UE_RUN/route-state.txt" || return 1
  printf 'destination_lookup=10163 destination_guard=10164 server=10.46.0.1 table=152\n' \
    > "$UE_RUN/server-route-state.txt" || return 1
  sudo ip -4 rule add pref 10162 from "$PATH_IP/32" to 10.46.0.1/32 type unreachable &&
  sudo ip -4 rule add pref 10164 to 10.46.0.1/32 type unreachable &&
  sudo ip link set dev "$PATH_IF" mtu "$UE_MTU" up &&
  sudo ip -4 addr add "$PATH_CIDR" dev "$PATH_IF" noprefixroute &&
  sudo ip -4 route add table 152 10.46.0.1/32 dev "$PATH_IF" src "$PATH_IP" &&
  sudo ip -4 rule add pref 10161 from "$PATH_IP/32" to 10.46.0.1/32 lookup 152 &&
  sudo ip -4 rule add pref 10163 to 10.46.0.1/32 lookup 152
}
if prepare_dual_path; then
  ip -4 route get 10.46.0.1 from "$PATH_IP"
  ip -4 route get 10.46.0.1
  ip -4 route show default
  printf 'UE2 rules installed; complete 2.6 before traffic.\n'
else
  printf 'FAIL: path setup incomplete; stop and clean only this run.\n'
fi
```

Stop on a setup failure and repeat 2.4's guarded reset before retrying.
Keep `route-state.txt` and `server-route-state.txt` as evidence; reset does not
depend on them. The independent block remains installed throughout rebuilding.
The setup requires a dedicated QMI interface with no existing IPv4 address or
default route. Resolve unexpected interface ownership before continuing.

### 2.6. Verify bound and ordinary routes, private ping and management routing

Section 2.5 already installed all four role rules; this block only verifies
them. Require both route lookups to select UE2's current WWAN and table
`152`, and the ordinary lookup's preferred source to equal `$UE_IP`.
Reused paths must also have the independent reset block. Do not accept ping
success over Wi-Fi as a UE check.

```bash
ip -4 rule show
ip -4 route show table 152
if python3 - "$WWAN_IF" "$UE_IP" <<'PY'
import json, subprocess, sys
interface, source = sys.argv[1:]
rules = json.loads(subprocess.check_output(['ip', '-j', '-4', 'rule', 'show'], text=True))
blocks = [rule for rule in rules if rule.get('priority') == 20152]
assert len(blocks) == 1, 'UE2: run 2.4–2.6 to install the reset block'
block = blocks[0]
assert block.get('src', 'all') == 'all' and block.get('dst') in ('10.46.0.1', '10.46.0.1/32') and block.get('action') == 'unreachable', f'UE2: wrong reset block: {block}'
for mode, extra in [('source-bound', ['from', source]), ('ordinary', [])]:
    routes = json.loads(subprocess.check_output(['ip', '-N', '-j', '-4', 'route', 'get', '10.46.0.1', *extra], text=True))
    assert len(routes) == 1, f'UE2: expected one {mode} route'
    route = routes[0]
    assert route.get('dev') == interface and int(route.get('table', -1)) == 152, f'UE2: wrong {mode} route: {route}'
    if mode == 'ordinary':
        assert route.get('prefsrc') == source, f'UE2: wrong ordinary source: {route}'
    print(f'UE2 {mode} route: OK', route)
PY
then
  ping -I "$UE_IP" -c 5 10.46.0.1 &&
  ping -c 5 10.46.0.1 &&
  ip -4 route show default
else
  printf 'STOP: UE2 route verification failed; use 2.4–2.6 to reset/rebuild before traffic.\n'
fi
```

Require both ping checks to pass and the management Wi-Fi default to remain
intact. Save `PATH_*` values and recheck cell/SA after reconnect/reattachment.
The destination guard blocks ordinary traffic if table 152 loses its server
route; independent priority `20152` continues blocking after a reset removes
the four role rules. Other destinations can still use Wi-Fi.
An old source-only path must be reset/rebuilt with 2.4–2.6; do not skip the
destination rules or add duplicate priorities on top of an existing path.

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

## 3. Concurrent UL and UE IP binding preflight

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
address or wrong ordinary route needs the affected role's guarded reset,
rebuild and verification (1.4–1.6 / 2.4–2.6). Do not substitute an old address
to bypass a failed preflight.

Then start [Spark step 7a](dual_ue_spark_quick_commands.md#7a-first-verify-both-ip-bindings-during-a-60-second-dual-upload)'s
120-second identity capture and check its log in a separate Spark terminal.
Require `Registered E2 Nodes = 3`, three successful subscription responses and
`identity collector: 3 KPM subscriptions, duration=120`. Keep both Spark
servers, DUs, CU and RIC running. Launch both UL clients from one Laptop terminal:

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
codes 0 and two completed receiver summaries. In Spark 7c, compare each
`summary.json` role's IMSI/APN/current IP with the captured CU/Core/DU events
and the `bindings.txt` records followed by KPM. Successful subscriptions alone
do not prove identity or metric delivery. After this short test passes, run
3.1 to reproduce both idle/resume cases in one xApp instance.

The daily workflow keeps both DUs running. Label the individual traffic tests
with the other DU active and its UE test traffic idle. Isolated-radio comparison
trials remain a separate full-Plan-3 validation case, with refreshed identities
and paths required after any radio/modem restart.

<a id="binding-idle"></a>

### 3.1. Six-minute UE1 idle / UE2 idle IP binding test

Use a fresh Laptop terminal after both role sequences and the short dual-upload
binding check pass. Keep both DUs, CU/RIC/Core, PDU sessions and Spark servers
running. Close other clients, periodic ping and other WWAN traffic so CU can
reach its current 120-second inactivity threshold. Keep management traffic on
the management network. Do not disconnect bearers or toggle modem power.

| Nominal seconds after START | UE1 | UE2 |
| --- | --- | --- |
| 0–15 | UL | UL |
| 15–165 | Quiet 150 s; verify actual Core idle | Same uninterrupted UL |
| 165–175 | Resumed UL | Same UL |
| 175–325 | Same uninterrupted UL | Quiet 150 s; verify actual Core idle |
| 325–335 | Same UL | Resumed UL |

UE1 runs 15 s → quiet 150 s → 170 s; UE2 runs 175 s → quiet 150 s → 10 s.
Quiet begins after that UE's first iperf exits, so connection/transfer overhead
may shift these nominal boundaries. The full traffic run must finish within
345 seconds, with both resume phases inside the 360-second Spark capture.

Paste this command directly; it reuses `~/falcon-dual-ul.py`, creates logs and
runs no traffic until `START`. No additional script file or transfer is needed.
Leave it at `READY`, start [Spark 7b](dual_ue_spark_quick_commands.md#7b-six-minute-bidirectional-idleresume-and-independent-matching)'s
360-second xApp, then return here within ten seconds and enter `START`.

```bash
python3 - <<'PY'
import importlib.util, json, signal, subprocess, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location('ue_helper', Path.home() / 'falcon-dual-ul.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
roles = helper.discover_roles()
helper.verify_routes(roles)
assert len(roles) == 2 and {r['ue'] for r in roles} == {1, 2}
for r in roles:
    print(f"UE{r['ue']}: IMSI={r['imsi']} IP={r['source']} dev={r['interface']} -> {r['server']}:{r['port']}", flush=True)
print('READY: 启动 Spark 的360秒xApp，然后在10秒内回这里输入 START 并回车。', flush=True)
with open('/dev/tty') as tty:
    while True:
        line = tty.readline()
        if not line:
            raise SystemExit('终端已关闭')
        if line.strip() == 'START':
            break
assert helper.discover_roles() == roles, 'Bearer已变化，请重新检查'
helper.verify_routes(roles)

out = Path(tempfile.mkdtemp(prefix='falcon-dual-idle-'))
(out / 'truth.json').write_text(json.dumps(roles, indent=2) + '\n')
started = time.monotonic()
lock, stop, jobs = threading.Lock(), threading.Event(), []
stamp = lambda: datetime.now(ZoneInfo('America/New_York')).isoformat()
events = (out / 'events.ndjson').open('w')
print('Evidence:', out, 'START:', stamp(), flush=True)

def event(kind, **fields):
    with lock:
        item = dict(event=kind, time_edt=stamp(), elapsed_s=round(time.monotonic()-started, 3), **fields)
        events.write(json.dumps(item) + '\n'); events.flush()
        print(item, flush=True)

def flow(r, before, after):
    for phase, seconds in (('before', before), ('after', after)):
        if phase == 'after':
            event('quiet_started', ue=r['ue'], seconds=150)
            quiet_start = time.monotonic()
            if stop.wait(150):
                return
            event('quiet_finished', ue=r['ue'], actual_seconds=round(time.monotonic()-quiet_start, 3))
        log = out / f"ue{r['ue']}_{phase}.log"
        with lock:
            if stop.is_set():
                return
            stream = log.open('w')
            try:
                proc = subprocess.Popen(['iperf3', '-c', r['server'], '-p', str(r['port']),
                    '-B', r['source'], '-t', str(seconds), '-i', '1', '--get-server-output'],
                    stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
            except BaseException:
                stream.close()
                raise
            job = dict(ue=r['ue'], phase=phase, seconds=seconds, log=str(log), started_at=stamp())
            jobs.append((proc, stream, job))
        event('iperf_started', ue=r['ue'], phase=phase, seconds=seconds)
        try:
            rc = proc.wait(timeout=seconds+5)
        finally:
            stream.close()
        job.update(exit_code=rc, ended_at=stamp())
        event('iperf_finished', ue=r['ue'], phase=phase, exit_code=rc)
        if rc:
            raise RuntimeError(f"UE{r['ue']} {phase} exit={rc}; log={log}")

def halt(*_):
    raise KeyboardInterrupt
signal.signal(signal.SIGTERM, halt)
pool = ThreadPoolExecutor(max_workers=2)
status, error = 'completed', None
try:
    futures = [pool.submit(flow, r, *( (15, 170) if r['ue'] == 1 else (175, 10) )) for r in roles]
    for future in as_completed(futures, timeout=345):
        future.result()
except (Exception, KeyboardInterrupt) as exc:
    status, error = 'failed', str(exc) or type(exc).__name__
finally:
    stop.set()
    with lock:
        owned = list(jobs)
    for proc, _, _ in owned:
        if proc.poll() is None:
            proc.terminate()
    for proc, _, job in owned:
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
        job.update(exit_code=proc.returncode)
    pool.shutdown(wait=True)
    summary = dict(status=status, error=error, elapsed_seconds=round(time.monotonic()-started, 3),
                   links=roles, jobs=[job for _, _, job in jobs], ended_at=stamp())
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    events.close()
    for _, _, job in jobs:
        print(f"UE{job['ue']} {job['phase']} exit={job['exit_code']}")
        for line in Path(job['log']).read_text(errors='replace').splitlines():
            if any(word in line for word in ('sender', 'receiver', 'iperf Done', 'error')):
                print(line)
    print('STATUS:', status, 'ERROR:', error, 'Evidence:', out, flush=True)
raise SystemExit(0 if status == 'completed' else 1)
PY
```

The start instruction comes from `/dev/tty` because stdin contains the pasted
Python command. Current IMEI/SIM/bearer/IP/interface/routes are rediscovered and
checked before traffic. On failure/interruption the parent stops its own
clients and waits for them; keep the printed error/evidence rather than treating
a partial run as passed. Let all four clients and the Spark capture finish.

Require UE1/UE2 `before` and `after` exits all 0, all four receiver summaries,
`STATUS: completed`, and `ERROR: None`. Retain the printed Laptop evidence path.
Print the full current identity truth, including both roles, for comparison
with Spark (use that printed directory):

```bash
read -r -p 'Paste the completed Laptop evidence directory: ' LAPTOP_BINDING_RUN
python3 - "$LAPTOP_BINDING_RUN" <<'PY_SUMMARY'
import json
from pathlib import Path
import sys
s = json.loads((Path(sys.argv[1]) / 'summary.json').read_text())
print(json.dumps({key: s[key] for key in ('status', 'error', 'elapsed_seconds', 'links', 'jobs')}, indent=2))
PY_SUMMARY
```

In [Spark 7c](dual_ue_spark_quick_commands.md#7c-inspect-bindings-core-transitions-and-two-example-records),
verify each UE actually enters Core idle then reconnects. During each silent-DU
window, its active peer must continue current `matched` bindings using its own
fresh CU/Core data; this `--fresh-only` test must have zero cached rows. On
resume, use the actual new F1/NGAP contexts and the Laptop's current IP; IDs
need not equal the October 21 report or remain constant. Count/explain startup/resume
unresolved rows, and check for cross-UE assignments. All detailed criteria are
in Spark 7c; a completed iperf script alone does not pass binding acceptance.

Keep Laptop `truth.json`, `events.ndjson`, the four client logs and
`summary.json`, plus Spark's inputs/rows/TXT/config/logs. Copy evidence out of
`/tmp` before reboot. Spark source times determine idle/matching boundaries;
Laptop's clock is not calibrated against Spark. Report zero-throughput
intervals on continuing clients rather than inferring stall-free traffic from
exit 0. A new successful cold start is a separate reproduction result; the October 21
archived counts are not a requirement for the new run.

### 3.2. Supplemental UDP comparisons and path-loss experiments

These follow-up experiments are separate from current acceptance and merging.
The comparison recipe repeats each solo/other-DU-idle/concurrent case three
times, with controlled UL UDP at no greater than 70% of measured solo capacity:

```bash
set -o pipefail
read -r -p 'Measured controlled UL rate, for example 8M: ' UL_OFFERED_RATE
iperf3 -c "$PATH_SERVER" -p "$IPERF_PORT" -B "$PATH_IP" \
  -u -b "$UL_OFFERED_RATE" -t 60 -i 1 --get-server-output -J | tee "$UE_RUN/ul-udp.json"
UL_RC=$?
printf 'pipeline_exit=%d\n' "$UL_RC" | tee "$UE_RUN/ul-udp-exit.txt"
```

The earlier comparison targets were receiver goodput at least 90% of the
isolated result and UDP loss at most 1%, at the same offered load. They are
reference targets for future experiments, not current development acceptance
criteria. Retain jitter, cell/SA/PDU continuity and planned PHY observations. No application DL or mixed-direction trials are required.
Use distinct filenames for subsequent repetitions.

For the supplemental bidirectional path-loss experiment, stop traffic on one
UE and remove only its table route. Keep the other UE's ping/UL running. In the affected terminal:

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

## 4. Finish tests and shut down both Quectel modems

Finish the laptop traffic and let the finite Spark identity xApp receive all three subscription
delete responses and exit normally. Then complete UE1 shutdown followed by UE2
shutdown below. Keep ModemManager running for both role operations.

Use the updated section 0.1 helper. `--shutdown` implies PDU disconnection and
performs this sequence for the selected IMEI: `mmcli --simple-disconnect` when
connected, IPv4 address/route/rule cleanup, `mmcli --delete-bearer=...` for every
listed bearer, then `mmcli --disable`. The final checks require no bearers and
modem state `disabled`. This is separate from the startup/recovery reset: without
`--shutdown`, the helper retains its existing behavior; `--disconnect` alone
keeps bearer objects and leaves the modem enabled.

No saved `MODEM`, `BEARER`, `WWAN_IF`, `PATH_*`, IP/CIDR or old-session ledger is
needed. Each operation discovers the current modem by the role's IMEI and reads
its bearer list again. The other UE's modem, bearers, host path and Wi-Fi are
preserved. The independent destination blocks installed in 1.4 / 2.4 also
remain; shutdown must not reopen the private service destinations through Wi-Fi.
A failure prints `STOP`; require the shutdown success marker before continuing.
If the modem was already unplugged, use the ordinary `--ue 1/2` reset for
leftover host configuration; its hardware shutdown cannot be verified.

`--disable` disables network operations and enters the modem's low-power state.
Physical power disconnection is a separate step in 4.3. See the
[ModemManager modem API](https://github.com/linux-mobile-broadband/ModemManager/blob/main/introspection/org.freedesktop.ModemManager1.Modem.xml).

### 4.1. UE1 disconnect, delete bearers and disable — table 151

UE1 is selected by IMEI `863305041978437`. In the UE1 terminal, first confirm
the installed helper supports shutdown, then run:

```bash
python3 ~/falcon-reset-ue-network.py --help
sudo python3 ~/falcon-reset-ue-network.py --ue 1 --shutdown
mmcli -L
ip -o -4 addr show
ip -4 rule show
ip -4 route show table 151
ip -4 route show default
```

Require `UE1 reset complete` and `UE1 shutdown complete`, with `bearers=0` and
`state=disabled`. The log prints the actual modem path and each deleted bearer.
UE1's `internet` PDU, all its listed old/current bearers, IPv4 addresses,
table-151 routes and reserved rules are cleared. UE2 remains available.

### 4.2. UE2 disconnect, delete bearers and disable — table 152

After UE1 shutdown passes, run in the UE2 terminal. UE2 is selected by IMEI
`863305041980706`:

```bash
sudo python3 ~/falcon-reset-ue-network.py --ue 2 --shutdown
mmcli -L
ip -o -4 addr show
ip -4 rule show
ip -4 route show table 152
ip -4 route show default
```

Require `UE2 reset complete` and `UE2 shutdown complete`, with `bearers=0` and
`state=disabled`. UE2's `internet2` PDU, all its listed old/current bearers,
IPv4 addresses, table-152 routes and reserved rules are cleared.

The two tables may then report `FIB table does not exist`; that is expected when
their routes have been removed. Confirm no UE1/UE2 test addresses or priorities
10151–10154 / 10161–10164 remain, and that the management Wi-Fi default route is
intact. Keep priorities `20151/20152`: ordinary route lookups/pings to
`10.45.0.1` and `10.46.0.1` must still fail after shutdown.

### 4.3. Physical power disconnection and the next experiment

After both shutdown success markers, disconnect each Quectel board's USB and
external power if it has an independent supply. A software-disabled modem may
still appear in `mmcli -L`; it is not physically disconnected yet.

For the next experiment, use fresh UE1/UE2 Bash terminals and repeat the ordered
role sequences. Rediscover by IMEI/SIM, use `mmcli --enable` on the selected
disabled modem as shown there, restore the cell lock after power/reconnection
and read fresh bearer/IP/interface values before creating routes.

After both laptop modems are shut down, use
[Spark step 8](dual_ue_spark_quick_commands.md#8-shutdown-and-retained-evidence)
for server/RAN/core shutdown. Retain identity/cell/bearer/path/UL/KPM correlation
as current functional evidence. Record cold-start, full repeatability and
bidirectional disturbance/survivor observations in the separate supplemental
experiments; their completion is not required for current acceptance or merging.
