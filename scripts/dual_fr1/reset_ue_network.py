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
