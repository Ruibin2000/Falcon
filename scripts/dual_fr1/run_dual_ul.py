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
        require("5gnr" in info.get("modem.generic.access-technologies", ""), f"{tag}: current access technology is not 5GNR")
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
        require(bearer.get("bearer.ipv4-config.gateway") == server, f"{tag}: unexpected bearer gateway")
        identity = info.get("modem.generic.device-identifier", "")
        require(identity not in ("", "--"), f"{tag}: missing current modem device identifier")
        result.append({"ue": ue, "imei": imei, "imsi": imsi, "apn": apn, "modem": modem,
                       "device_identifier": identity, "sim": sim, "bearer": bearer_path,
                       "source": source, "prefix": prefix, "interface": interface,
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
              f"{role['source']}/{role['prefix']} dev={role['interface']} table={role['table']} -> {role['server']}:{role['port']}", flush=True)
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
