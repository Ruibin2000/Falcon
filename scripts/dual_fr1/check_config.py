#!/usr/bin/env python3
"""Check the single-cell, two-B210 Plan 3 configuration without opening radios.

Requires PyYAML. This checks offline identities and topology, not RF authorization,
SSB/CORESET derivation, connected hardware, subscriber records, or live acceptance.
OCUDU's pinned defaults are gNB 411/22 bits and sector 0 for a one-cell DU.
Frequency checks describe the logical USRP-side n78 carriers. DU2's external
Pi-Radio conversion to 9250 MHz is outside these OCUDU configuration checks.
"""

import argparse
import copy
import ipaddress
import os
from pathlib import Path
import re
import sys

import yaml


REPO = Path(__file__).resolve().parents[2]


def mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def section(config, key):
    return mapping(config.get(key, {}), key)


def load(path):
    return mapping(yaml.safe_load(Path(path).read_text()), str(path))


def merge(base, overlay):
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def integer(value, label):
    if type(value) is not int:
        raise ValueError(f"{label} must be an integer")
    return value


def address(value, label):
    try:
        return str(ipaddress.IPv4Address(value))
    except (ipaddress.AddressValueError, TypeError):
        raise ValueError(f"{label} must be an IPv4 address") from None


def identity(config):
    return (integer(config.get("gnb_id", 411), "gnb_id"),
            integer(config.get("gnb_id_bit_length", 22), "gnb_id_bit_length"))


def validate(cu, du1, du2):
    errors, rows = [], []

    def require(condition, message):
        if not condition:
            errors.append(message)

    cu_identity = identity(cu)
    cu_cp = section(cu, "cu_cp")
    cu_f1 = address(section(cu_cp, "f1ap").get("bind_addrs"), "CU F1 bind")
    require(cu_cp.get("max_nof_dus", 6) >= 2, "CU capacity is less than two DUs")
    for label, config in [("DU1", du1), ("DU2", du2)]:
        require("cells" not in config, f"{label}: checker supports one cell_cfg per DU")
        gnb, bits = identity(config)
        require((gnb, bits) == cu_identity, f"{label}: gNB identity differs from CU")
        require(22 <= bits <= 32 and 0 <= gnb < (1 << bits), f"{label}: invalid gNB identity")
        if not 22 <= bits <= 32:
            raise ValueError(f"{label}: invalid gNB bit length")
        cell, radio = section(config, "cell_cfg"), section(config, "ru_sdr")
        sector = integer(cell.get("sector_id", 0), f"{label} sector_id")
        require(0 <= sector < (1 << (36 - bits)), f"{label}: sector_id exceeds NCI space")
        pci = integer(cell.get("pci"), f"{label} PCI")
        du_id = integer(config.get("gnb_du_id"), f"{label} DU ID")
        require(0 <= du_id < (1 << 36), f"{label}: invalid DU ID")
        require(0 <= pci <= 1007, f"{label}: invalid PCI")
        require(cell.get("plmn") == "00101", f"{label}: PLMN must be the string 00101")
        require(cell.get("tac") == 7, f"{label}: expected TAC 7")
        bandwidth = integer(cell.get("channel_bandwidth_MHz"), f"{label} bandwidth")
        expected_bandwidth, expected_srate = (20, 23.04) if label == "DU1" else (40, 46.08)
        require(cell.get("band") == 78 and cell.get("common_scs") == 30
                and bandwidth == expected_bandwidth,
                f"{label}: expected explicit n78 / {expected_bandwidth} MHz / 30 kHz")
        arfcn = integer(cell.get("dl_arfcn"), f"{label} ARFCN")
        center = 3000 + 0.015 * (arfcn - 600000)
        interval = (center - bandwidth / 2, center + bandwidth / 2)
        require(arfcn % 2 == 0, f"{label}: ARFCN is off the n78 30-kHz channel raster")
        require(3550 <= interval[0] and interval[1] <= 3700,
                f"{label}: full nominal channel is outside 3550-3700 MHz")
        require(radio.get("device_driver") == "uhd", f"{label}: expected UHD radio")
        args = str(radio.get("device_args", ""))
        serials = re.findall(r"(?:^|,)\s*serial=([^,\s]+)", args)
        serial = serials[0] if len(serials) == 1 else ""
        require(bool(re.fullmatch(r"[A-Za-z0-9]+", serial))
                and not re.search(r"REPLACE|PLACEHOLDER|TODO", serial, re.I),
                f"{label}: missing actual B210 serial; discover hardware before startup")
        require("type=b200" in args.split(","), f"{label}: expected B210 device type=b200")
        require(radio.get("srate") == expected_srate,
                f"{label}: expected sample rate {expected_srate} MS/s")
        f1 = section(config, "f1ap")
        bind = address(f1.get("bind_addrs"), f"{label} F1-C bind")
        require(address(f1.get("addrs"), f"{label} CU destination") == cu_f1,
                f"{label}: F1-C destination differs from CU listener")
        sockets = section(config, "f1u").get("socket", [])
        require(isinstance(sockets, list) and len(sockets) == 1,
                f"{label}: expected exactly one F1-U socket")
        if not isinstance(sockets, list) or len(sockets) != 1:
            raise ValueError(f"{label}: invalid F1-U sockets")
        f1u = address(mapping(sockets[0], "F1-U socket").get("bind_addr"), f"{label} F1-U bind")
        require(bind == f1u and bind != cu_f1, f"{label}: F1 binds must match and differ from CU")
        e2, metrics = section(config, "e2"), section(config, "metrics")
        require(e2.get("enable_du_e2") is True and e2.get("e2sm_kpm_enabled") is True,
                f"{label}: DU E2/KPM must be enabled")
        require(e2.get("addrs") == ["127.0.0.1"] and e2.get("port") == 36421,
                f"{label}: expected shared RIC destination 127.0.0.1:36421")
        local_e2 = e2.get("bind_addrs")
        require(isinstance(local_e2, list) and len(local_e2) == 1,
                f"{label}: expected one E2 local bind")
        if isinstance(local_e2, list) and len(local_e2) == 1:
            address(local_e2[0], f"{label} E2 bind")
        if label == "DU2":
            require(local_e2 == [bind], "DU2: E2 local bind must match its F1 address")
        layers, periods = section(metrics, "layers"), section(metrics, "periodicity")
        require(layers.get("enable_sched") is True and layers.get("enable_rlc") is True
                and periods.get("du_report_period") == 100,
                f"{label}: scheduler/RLC metrics and 100-ms reporting are required")
        logfile = Path(str(section(config, "log").get("filename", "")))
        require(logfile.is_absolute(), f"{label}: log filename must be absolute")
        require(logfile.parent.is_dir() and os.access(logfile.parent, os.W_OK)
                and (not logfile.exists() or (logfile.is_file() and os.access(logfile, os.W_OK))),
                f"{label}: log path must be writable")
        rows.append(dict(label=label, serial=serial, du_id=du_id, pci=pci,
                         cgi=(cell.get("plmn"), (gnb << (36 - bits)) | sector),
                         f1=bind, f1u=f1u, log=str(logfile), interval=interval,
                         center_mhz=center, bandwidth_mhz=bandwidth, srate=radio.get("srate")))
    for key in ["serial", "du_id", "pci", "cgi", "f1", "f1u", "log"]:
        require(rows[0][key] != rows[1][key], f"Duplicate {key} across DU1 and DU2")
    left, right = sorted(rows, key=lambda row: row["interval"][0])
    require(left["interval"][1] <= right["interval"][0], "Nominal DU channels overlap")
    return errors, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cu", type=Path, default=Path("/home/nyu/ocudu/configs/cu.yml"))
    parser.add_argument("--du1", type=Path, default=REPO / "configs/ocudu/dual_fr1/du1_b210_n78_3660mhz.yml")
    parser.add_argument("--du2", type=Path, default=REPO / "configs/ocudu/dual_fr1/du2_b210_n78_40mhz.yml")
    parser.add_argument("--du2-e2", type=Path, default=REPO / "configs/ocudu/dual_fr1/du2_flexric.yml")
    args = parser.parse_args()
    try:
        errors, rows = validate(load(args.cu), load(args.du1), merge(load(args.du2), load(args.du2_e2)))
    except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    for row in rows:
        print(f'{row["label"]}: DU {row["du_id"]}, PCI {row["pci"]}, '
              f'NCI {row["cgi"][1]}, {row["center_mhz"]:.0f} MHz, '
              f'BW {row["bandwidth_mhz"]} MHz, {row["srate"]} MS/s, F1 {row["f1"]}')
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    if errors:
        return 1
    print("PASS: offline dual-DU identity/topology checks; live RF/subscriber/UL gates remain pending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
