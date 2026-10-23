#!/usr/bin/env python3
"""Check this Spark's captured configuration and the two TUN layouts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import yaml

BUNDLE = Path(__file__).resolve().parent
MANIFEST = json.loads((BUNDLE / "manifest.json").read_text())
TARGETS = {
    "upf.yaml": Path("/etc/open5gs/upf.yaml"),
    "99-open5gs.netdev": Path("/etc/systemd/network/99-open5gs.netdev"),
    "99-open5gs.network": Path("/etc/systemd/network/99-open5gs.network"),
    "99-open5gs-ue2.netdev": Path("/etc/systemd/network/99-open5gs-ue2.netdev"),
    "99-open5gs-ue2.network": Path("/etc/systemd/network/99-open5gs-ue2.network"),
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def query(*args):
    return json.loads(subprocess.check_output(["ip", "-j", *args], text=True))


def services():
    for unit in ("systemd-networkd", "open5gs-upfd", "open5gs-smfd"):
        subprocess.run(["systemctl", "is-active", "--quiet", unit], check=True)


def management():
    return {
        "defaults": query("-4", "route", "show", "default"),
        "rules": query("-4", "rule", "show"),
    }


def layout(split):
    rows = query("-4", "addr", "show")
    for address, dev in (("10.45.0.1", "ogstun_1" if split else "ogstun"),
                         ("10.46.0.1", "ogstun_2" if split else "ogstun")):
        owners = [(row, addr) for row in rows for addr in row.get("addr_info", [])
                  if addr.get("local") == address]
        require(len(owners) == 1, f"{address} must exist on exactly one interface")
        row, addr = owners[0]
        require(row["ifname"] == dev and addr["prefixlen"] == 16,
                f"{address}/16 must belong to {dev}")
        require(row["mtu"] == 1400 and "UP" in row["flags"],
                f"{dev} must be UP with MTU 1400")
        destination = address.rsplit(".", 1)[0] + ".2"
        routes = query("-4", "route", "get", destination, "from", address)
        require(len(routes) == 1 and routes[0].get("dev") == dev,
                f"The return route from {address} to {destination} must use {dev}")
    links = query("link", "show")
    forbidden = {"ogstun"} if split else {"ogstun_1", "ogstun_2", "ogstun2"}
    require(not any(row["ifname"] in forbidden for row in links),
            "An unexpected TUN interface exists; inspect it before continuing")


def check_bundle():
    for path, expected in MANIFEST["sources"].items():
        require(digest(BUNDLE / "original" / Path(path).name) == expected,
                f"Backup changed: {path}")
    for name, expected in MANIFEST["prepared"].items():
        require(digest(BUNDLE / "prepared" / name) == expected,
                f"Prepared file changed: {name}")


def preflight():
    check_bundle()
    for path, expected in MANIFEST["sources"].items():
        require(digest(Path(path)) == expected,
                f"Source changed after preparation: {path}; prepare a new bundle")
    for name in ("99-open5gs-ue2.netdev", "99-open5gs-ue2.network"):
        target = TARGETS[name]
        require(not target.exists() and not target.is_symlink(), f"{target} already exists")
    services()
    layout(False)
    for route in query("-4", "route", "show", "table", "all"):
        if route.get("dst") in ("10.45.0.0/16", "10.46.0.0/16"):
            require(route.get("dev") == "ogstun", "Unexpected private subnet route")
    (BUNDLE / "baseline.json").write_text(json.dumps(management(), indent=2) + "\n")
    print("Preflight passed: captured files match, both pools use ogstun, services are active.")


def rollback_guard():
    check_bundle()
    for name, target in TARGETS.items():
        if target.exists() or target.is_symlink():
            allowed = {MANIFEST["prepared"][name]}
            original = BUNDLE / "original" / name
            if original.exists():
                allowed.add(digest(original))
            require(digest(target) in allowed,
                    f"{target} changed independently; refusing to overwrite it")


def verify(split):
    services()
    layout(split)
    for name in ("upf.yaml", "99-open5gs.netdev", "99-open5gs.network"):
        expected = BUNDLE / ("prepared" if split else "original") / name
        require(digest(TARGETS[name]) == digest(expected), f"Wrong deployed file: {name}")
    for path, expected in MANIFEST["sources"].items():
        if Path(path).name == "smf.yaml":
            require(digest(Path(path)) == expected, f"Unexpected change: {path}")
    for name in ("99-open5gs-ue2.netdev", "99-open5gs-ue2.network"):
        target = TARGETS[name]
        if split:
            require(digest(target) == MANIFEST["prepared"][name], f"Wrong persistence file: {name}")
        else:
            require(not target.exists() and not target.is_symlink(), f"Remove split file: {target}")
    upf = yaml.safe_load(TARGETS["upf.yaml"].read_text())["upf"]["session"]
    for pool in upf:
        expected = ("ogstun_2" if pool["dnn"] == "internet2" else "ogstun_1") if split else "ogstun"
        require(pool.get("dev", "ogstun") == expected, "UPF session selects the wrong TUN")
    baseline = json.loads((BUNDLE / "baseline.json").read_text())
    require(management() == baseline, "Default route or policy rules changed; inspect them")
    print("Spark configuration verified: " + ("UE1=ogstun_1, UE2=ogstun_2" if split else "both UEs=ogstun"))


if __name__ == "__main__":
    try:
        action = sys.argv[1]
        if action == "preflight":
            preflight()
        elif action == "rollback-guard":
            rollback_guard()
        elif action in ("verify-split", "verify-shared"):
            verify(action == "verify-split")
        else:
            raise RuntimeError("Unknown action")
    except (RuntimeError, OSError, subprocess.CalledProcessError, ValueError, IndexError) as error:
        print(f"STOP: {error}", file=sys.stderr)
        sys.exit(1)
