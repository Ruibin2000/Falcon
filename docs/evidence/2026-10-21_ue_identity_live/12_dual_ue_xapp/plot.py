#!/usr/bin/env python3
"""Plot this live capture; optional PHY extraction only reads existing CU/DU logs."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import tempfile
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="falcon-identity-mpl-", dir="/tmp"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("America/New_York")
CU_LOG = Path("/tmp/falcon-identity-cu.9cKTWHpv/cu.log")
DU_LOGS = {1: Path("/tmp/falcon-identity-du1.h5S2k9VS/du.log"),
           2: Path("/tmp/falcon-identity-du2.nMXBOBbV/du.log")}
COLORS = {1: "#2563eb", 2: "#d97706"}


def utc_seconds(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def numeric(row, name):
    metric = row["row"]["metrics"][name]
    return float("nan") if metric["type"] == "no_value" else metric["value"]


def extract_phy(rows, start, end):
    # Whitelist only identity-bearing CU log records, excluding security payloads.
    contexts, f1, ngap, excerpts = {}, {}, {}, []
    low = utc_seconds(start - 30)
    high = utc_seconds(start + 1)
    with CU_LOG.open(errors="replace") as stream:
        for line in stream:
            stamp = line[:19]
            if len(stamp) != 19 or stamp[4] != "-" or stamp[10] != "T":
                continue
            if stamp < low:
                continue
            if stamp >= high:
                if stamp > utc_seconds(start + 5):
                    break
                continue
            created = re.search(r"\[CU-UEMNG\].*ue=(\d+) du_index=\d+ gnb_du_id=(\d+) pci=(\d+) rnti=(0x[0-9a-f]+).*Created new CU-CP UE", line)
            added = re.search(r"\[CU-CP-F1\].*ue=(\d+) du_ue=\d+ cu_ue=(\d+): Added UE context", line)
            ids = re.search(r"\[NGAP\s*\].*ue=(\d+) ran_ue=(\d+) amf_ue=(\d+):", line)
            if created:
                ue, du, pci, rnti = created.groups()
                contexts[ue] = {"du_id": int(du), "pci": int(pci), "rnti": rnti}
            if added:
                f1[added[1]] = added[2]
            if ids:
                ngap[ids[1]] = {"ran": ids[2], "amf": ids[3]}
            if created or added or ids:
                excerpts.append(line)
    (ROOT / "cu_phy_identity_excerpt.log").write_text("".join(excerpts))
    mapping = {}
    for du in (1, 2):
        selected = [row for row in rows if int(row["node"]["du_id"]) == du and row["binding_status"] == "matched"]
        identities = {(row["row"]["ue"]["gnb_cu_ue_f1ap_id"], row["binding"]["amf_ue_ngap_id"],
                       row["binding"]["ran_ue_ngap_id"]) for row in selected}
        assert len(identities) == 1
        f1_id, amf_id, ran_id = next(iter(identities))
        matches = [(ue, context) for ue, context in contexts.items() if context["du_id"] == du
                   and f1.get(ue) == f1_id and ngap.get(ue) == {"amf": amf_id, "ran": ran_id}]
        assert len(matches) == 1, (du, identities, contexts, f1, ngap)
        ue, context = matches[0]
        mapping[str(du)] = dict(context, cu_internal_ue_index=ue, gnb_cu_ue_f1ap_id=f1_id,
                               amf_ue_ngap_id=amf_id, ran_ue_ngap_id=ran_id)
        observed = Counter()
        source = DU_LOGS[du]
        with source.open("rb") as stream, gzip.open(ROOT / f"du{du}_pusch.log.gz", "wb") as target:
            for raw in stream:
                stamp = raw[:19].decode("ascii", errors="replace")
                if len(stamp) != 19 or stamp[4] != "-" or stamp[10] != "T":
                    continue
                if stamp < utc_seconds(start):
                    continue
                if stamp >= utc_seconds(end):
                    if stamp > utc_seconds(end + 5):
                        break
                    continue
                if b"PUSCH:" not in raw:
                    continue
                match = re.search(rb"\brnti=(0x[0-9a-f]+)\b", raw)
                assert match is not None
                rnti = match[1].decode()
                observed[rnti] += 1
                if rnti == context["rnti"]:
                    target.write(raw)
        assert observed[context["rnti"]] > 0
        mapping[str(du)]["all_logged_pusch_rntis_in_window"] = dict(observed)
        mapping[str(du)]["source_file"] = str(source)
    archive = {"cu_source_file": str(CU_LOG), "source": "actual existing logs, identity-only CU excerpt and selected-RNTI PUSCH records",
               "window_utc": [utc_seconds(start) + "+00:00", utc_seconds(end) + "+00:00"],
               "end_exclusive": True, "window_definition": "first positive KPM header floored to second, through floor(last positive header)+2 seconds",
               "mapping": mapping}
    (ROOT / "phy_sources.json").write_text(json.dumps(archive, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract-phy", action="store_true", help="archive selected PHY records from the known live log files; starts no services")
    args = parser.parse_args()
    rows = [json.loads(line) for line in (ROOT / "rows.ndjson").read_text().splitlines()]
    assert len(rows) == 223
    positive = [row for row in rows if numeric(row, "DRB.UEThpUl") > 0]
    origin = min(int(row["header_time_us"]) for row in rows) / 1e6
    active_start = min(int(row["header_time_us"]) for row in positive) / 1e6
    active_end = max(int(row["header_time_us"]) for row in positive) / 1e6
    plotted_rows = [row for row in rows if active_start <= int(row["header_time_us"]) / 1e6 <= active_end]
    phy_start, phy_end = math.ceil(active_start), math.floor(active_end)
    assert phy_start < phy_end
    start, end = int(active_start), int(active_end) + 2
    if args.extract_phy:
        extract_phy(rows, start, end)
    sources = json.loads((ROOT / "phy_sources.json").read_text())
    assert sources["window_utc"] == [utc_seconds(start) + "+00:00", utc_seconds(end) + "+00:00"]
    per_second, summary = [], {}
    for du in (1, 2):
        buckets = defaultdict(list)
        with gzip.open(ROOT / f"du{du}_pusch.log.gz", "rt") as stream:
            for line in stream:
                if not utc_seconds(phy_start) <= line[:19] < utc_seconds(phy_end):
                    continue
                values = dict(re.findall(r"\b(rnti|mod|rv|tbs|crc|sinr)=([^\s]+)", line))
                assert values["rnti"] == sources["mapping"][str(du)]["rnti"]
                assert values["crc"] in ("OK", "KO")
                values["sinr"] = float(values["sinr"].removesuffix("dB"))
                buckets[line[:19]].append(values)
        all_values = [value for values in buckets.values() for value in values]
        crc = Counter(value["crc"] for value in all_values)
        summary[str(du)] = {"rnti": sources["mapping"][str(du)]["rnti"], "attempts": len(all_values),
                            "crc": dict(crc), "crc_failed_attempt_percent": 100 * crc["KO"] / len(all_values),
                            "sinr_median_db": statistics.median(value["sinr"] for value in all_values if math.isfinite(value["sinr"]))}
        for second in range(phy_start, phy_end):
            values = buckets.get(utc_seconds(second), [])
            failed = sum(value["crc"] == "KO" for value in values)
            finite_sinrs = [value["sinr"] for value in values if math.isfinite(value["sinr"])]
            per_second.append({"du_id": du, "rnti": summary[str(du)]["rnti"], "utc": utc_seconds(second) + "+00:00",
                               "unix_s": second, "attempts": len(values), "crc_ok": len(values) - failed, "crc_ko": failed,
                               "crc_failed_attempt_percent": 100 * failed / len(values) if values else None,
                               "sinr_mean_db": statistics.mean(finite_sinrs) if finite_sinrs else None})
    with (ROOT / "phy_per_second.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(per_second[0]))
        writer.writeheader()
        writer.writerows(per_second)
    with (ROOT / "plot_kpm.csv").open("w", newline="") as stream:
        fields = ["sequence", "du_id", "f1ap_ue_id", "header_time_us", "time_edt", "binding_status", "ue_ipv4", "ul_mbit_s"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in plotted_rows:
            writer.writerow({"sequence": row["sequence"], "du_id": row["node"]["du_id"],
                             "f1ap_ue_id": row["row"]["ue"]["gnb_cu_ue_f1ap_id"], "header_time_us": row["header_time_us"],
                             "time_edt": datetime.fromtimestamp(int(row["header_time_us"]) / 1e6, TZ).isoformat(),
                             "binding_status": row["binding_status"], "ue_ipv4": row["ue_ipv4"],
                             "ul_mbit_s": numeric(row, "DRB.UEThpUl") / 1000})
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.9), sharex=True, constrained_layout=True)
    for du in (1, 2):
        selected = [row for row in plotted_rows if int(row["node"]["du_id"]) == du]
        times = [(int(row["header_time_us"]) / 1e6 - origin) for row in selected]
        f1 = selected[0]["row"]["ue"]["gnb_cu_ue_f1ap_id"]
        axes[0].plot(times, [numeric(row, "DRB.UEThpUl") / 1000 for row in selected], color=COLORS[du], linewidth=1.5,
                     label=f"DU{du} / F1AP UE {f1}")
        unmatched = [row for row in selected if row["binding_status"] != "matched"]
        axes[0].scatter([(int(row["header_time_us"]) / 1e6 - origin) for row in unmatched],
                        [numeric(row, "DRB.UEThpUl") / 1000 for row in unmatched], facecolors="none", edgecolors=COLORS[du],
                        s=45, linewidths=1.4, zorder=5, label="Initial unmatched sample" if du == 1 else None)
        observed = [row for row in per_second if row["du_id"] == du]
        axes[1].plot([row["unix_s"] + 0.5 - origin for row in observed],
                     [row["crc_failed_attempt_percent"] if row["attempts"] else float("nan") for row in observed],
                     color=COLORS[du], linewidth=1.5, label=f"DU{du} / RNTI {summary[str(du)]['rnti']}")
    for ax in axes:
        ax.grid(alpha=0.25)
        handles, labels = ax.get_legend_handles_labels()
        order = sorted(range(len(labels)), key=lambda index: labels[index] == "Initial unmatched sample")
        ax.legend([handles[index] for index in order], [labels[index] for index in order],
                  loc="lower left", bbox_to_anchor=(0, 1.01), ncol=3, fontsize=8, borderaxespad=0)
        ax.set_ylim(bottom=0)
    axes[0].set_ylabel("KPM UL throughput (Mbit/s)")
    axes[1].set_ylabel("PUSCH CRC failed attempts (%)")
    axes[1].set_xlabel(f"Seconds from first Spark KPM header ({datetime.fromtimestamp(origin, TZ).strftime('%H:%M:%S.%f')[:-3]} EDT)")
    axes[1].set_xlim(active_start - origin, active_end - origin)
    fig.suptitle("Dual DU uplink: 2026-10-21 live identity capture\nUL-active interval: KPM/RLC throughput and PUSCH decoding attempts")
    fig.savefig(ROOT / "dual_ul_kpm.png", dpi=180)
    fig.savefig(ROOT / "dual_ul_kpm.svg", metadata={"Date": None})
    plt.close(fig)
    manifest = {"experiment_date": "2026-10-21", "timezone": "America/New_York", "x_axis_clock": "Spark",
                "origin_utc": datetime.fromtimestamp(origin, timezone.utc).isoformat(),
                "plotted_window_utc": [datetime.fromtimestamp(value, timezone.utc).isoformat() for value in (active_start, active_end)],
                "plotted_duration_s": active_end - active_start, "captured_kpm_rows": len(rows), "plotted_kpm_rows": len(plotted_rows),
                "plot_window_definition": "first through last positive UL KPM header; exact Laptop process window unaligned",
                "unmatched_samples": "first two DU samples retained and shown with hollow markers; their IP fields stay null",
                "phy_archive_window": sources["window_utc"],
                "phy_window": [utc_seconds(phy_start) + "+00:00", utc_seconds(phy_end) + "+00:00"],
                "phy_bin_definition": "only complete wall-clock one-second bins within plotted KPM window, drawn at bin midpoints",
                "phy_end_exclusive": True, "phy": summary,
                "crc_definition": "KO / (OK + KO) logged PUSCH decoding attempts, includes retransmissions; not TCP loss or calibrated first-transmission BLER",
                "empty_phy_seconds": "blank/NaN, never zero-filled",
                "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                           ("plot.py", "rows.ndjson", "phy_sources.json", "cu_phy_identity_excerpt.log", "du1_pusch.log.gz", "du2_pusch.log.gz",
                            "plot_kpm.csv", "phy_per_second.csv", "dual_ul_kpm.png", "dual_ul_kpm.svg")}}
    (ROOT / "plot_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"figures": ["dual_ul_kpm.png", "dual_ul_kpm.svg"], "phy": summary,
                      "plotted_kpm_rows": len(plotted_rows), "plot_window": manifest["plotted_window_utc"],
                      "phy_window": manifest["phy_window"]}, indent=2))


if __name__ == "__main__":
    main()
