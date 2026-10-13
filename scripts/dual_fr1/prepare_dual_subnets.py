#!/usr/bin/env python3
"""Prepare Open5GS 2.8 dual-DNN files and backups without changing the host."""

import argparse
import copy
import hashlib
from pathlib import Path
import re
import sys
import textwrap

import yaml


OLD = [
    {"subnet": "10.45.0.0/16", "gateway": "10.45.0.1"},
    {"subnet": "2001:db8:cafe::/48", "gateway": "2001:db8:cafe::1"},
]
NEW = [dict(row, dnn="internet") for row in OLD] + [
    {"subnet": "10.46.0.0/16", "gateway": "10.46.0.1", "dnn": "internet2"},
]


def prepare_yaml(raw, role):
    original = yaml.safe_load(raw)
    section = original[role]
    if section.get("session") not in (OLD, NEW):
        raise ValueError(f"{role}: unexpected session pools; review manually")
    if role == "smf" and section.get("info"):
        raise ValueError("smf.info is configured; review its DNN advertisement manually")
    start = re.search(r"(?m)^  session:\s*\n", raw)
    if not start:
        raise ValueError(f"{role}: expected a two-space session block")
    following = re.search(r"(?m)^  [A-Za-z_][\w-]*:", raw[start.end():])
    if not following:
        raise ValueError(f"{role}: cannot locate the end of the session block")
    end = start.end() + following.start()
    body = "  session:\n" + textwrap.indent(yaml.safe_dump(NEW, sort_keys=False), "    ")
    result = raw[:start.start()] + body + raw[end:]
    expected = copy.deepcopy(original)
    expected[role]["session"] = copy.deepcopy(NEW)
    if yaml.safe_load(result) != expected:
        raise ValueError(f"{role}: an unrelated configuration value changed")
    return result


def prepare_network(raw):
    if not re.search(r"(?m)^Name=ogstun\s*$", raw):
        raise ValueError("network file does not select ogstun")
    if len(re.findall(r"(?m)^Address=10\.45\.0\.1/16\s*$", raw)) != 1:
        raise ValueError("network file must contain one 10.45.0.1/16 address")
    if "10.46." in raw:
        if len(re.findall(r"(?m)^Address=10\.46\.0\.1/16\s*$", raw)) != 1:
            raise ValueError("network file has a conflicting 10.46 entry")
        return raw
    return raw.replace("Address=10.45.0.1/16", "Address=10.45.0.1/16\nAddress=10.46.0.1/16", 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smf", type=Path, default=Path("/etc/open5gs/smf.yaml"))
    parser.add_argument("--upf", type=Path, default=Path("/etc/open5gs/upf.yaml"))
    parser.add_argument("--network", type=Path, default=Path("/etc/systemd/network/99-open5gs.network"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    sources = [args.smf, args.upf, args.network]
    raw = [path.read_text() for path in sources]
    prepared = [prepare_yaml(raw[0], "smf"), prepare_yaml(raw[1], "upf"), prepare_network(raw[2])]
    output = args.output_dir
    if output.exists() and (output.is_symlink() or any(output.iterdir())):
        raise ValueError("output directory must be empty and not a symlink")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    checksums = []
    for directory in ("original", "prepared"):
        (output / directory).mkdir(mode=0o700)
    for path, before, after in zip(sources, raw, prepared):
        for directory, contents in (("original", before), ("prepared", after)):
            dest = output / directory / path.name
            dest.write_text(contents)
            dest.chmod(0o600)
        checksums.append(f"{hashlib.sha256(before.encode()).hexdigest()}  {path.resolve()}\n")
    (output / "source.sha256").write_text("".join(checksums))
    print(f"Prepared: {output}")
    print("UE1: internet / 10.45.0.0/16 / server 10.45.0.1")
    print("UE2: internet2 / 10.46.0.0/16 / server 10.46.0.1")
    print("Only files were prepared; services, subscriber records and interfaces were not changed.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, yaml.YAMLError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
