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
