#!/usr/bin/env python3
"""Plot the final live trial from retained inputs; optional extraction reads logs."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
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

os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="falcon-final-mpl-", dir="/tmp"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["svg.hashsalt"] = "falcon-final-ue-identity-2026-10-21"

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("America/New_York")
COLORS = {1: "#2563eb", 2: "#d97706"}
CU_LOG = Path("/tmp/falcon-identity-cu.9cKTWHpv/cu.log")
DU_LOGS = {1: Path("/tmp/falcon-identity-du1.h5S2k9VS/du.log"),
           2: Path("/tmp/falcon-identity-du2.nMXBOBbV/du.log")}


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def metric(row):
    item = row["row"]["metrics"]["DRB.UEThpUl"]
    return item.get("value") if item["type"] != "no_value" else None


def windows(rows):
    result = []
    for du in (1, 2):
        group = []
        for row in rows:
            if int(row["node"]["du_id"]) != du or not (metric(row) is not None and metric(row) > 0):
                continue
            if group and (int(row["header_time_us"]) - int(group[-1]["header_time_us"]) > 1_500_000
                          or row["row"]["ue"] != group[-1]["row"]["ue"]):
                result.append((du, group))
                group = []
            group.append(row)
        if group:
            result.append((du, group))
    assert len(result) == 4, "Expected two positive-UL phases per role"
    return result


def extract(rows, low, high):
    contexts, f1_ids, ngap_ids, excerpts = {}, {}, {}, []
    with CU_LOG.open(errors="replace") as stream:
        for line in stream:
            if not re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", line):
                continue
            if line[:19] < stamp(low - 30):
                continue
            if line[:19] >= stamp(high):
                break
            created = re.search(r"\[CU-UEMNG\].*ue=(\d+) du_index=\d+ gnb_du_id=(\d+) pci=(\d+) rnti=(0x[0-9a-f]+).*Created new CU-CP UE", line)
            added = re.search(r"\[CU-CP-F1\].*ue=(\d+) du_ue=\d+ cu_ue=(\d+): Added UE context", line)
            ids = re.search(r"\[NGAP\s*\].*ue=(\d+) ran_ue=(\d+) amf_ue=(\d+): InitialContextSetupRequest", line)
            if created:
                ue, du, pci, rnti = created.groups()
                contexts[ue] = dict(du_id=int(du), pci=int(pci), rnti=rnti)
            if added:
                f1_ids[added[1]] = added[2]
            if ids:
                ngap_ids[ids[1]] = (ids[2], ids[3])
            if created or added or ids:
                excerpts.append(line)
    mapping = {}
    for row in rows:
        if row["binding_status"] != "matched":
            continue
        du, f1 = int(row["node"]["du_id"]), row["row"]["ue"]["gnb_cu_ue_f1ap_id"]
        key = f"{du}/{f1}"
        binding = row["binding"]
        matches = [(ue, context) for ue, context in contexts.items()
                   if context["du_id"] == du and f1_ids.get(ue) == f1
                   and ngap_ids.get(ue) == (binding["ran_ue_ngap_id"], binding["amf_ue_ngap_id"])]
        assert len(matches) == 1, (key, matches)
        ue, context = matches[0]
        mapping[key] = dict(context, cu_internal_ue_index=ue, gnb_cu_ue_f1ap_id=f1,
                            amf_ue_ngap_id=binding["amf_ue_ngap_id"],
                            ran_ue_ngap_id=binding["ran_ue_ngap_id"])
    assert len(mapping) == 4
    (ROOT / "cu_phy_identity_excerpt.log").write_text("".join(excerpts))
    for du, source in DU_LOGS.items():
        allowed = {item["rnti"] for item in mapping.values() if item["du_id"] == du}
        counts = Counter()
        with source.open("rb") as stream, (ROOT / f"du{du}_pusch.log.gz").open("wb") as raw_target:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_target, mtime=0) as target:
                for raw in stream:
                    current = raw[:19].decode("ascii", errors="replace")
                    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", current):
                        continue
                    if current < stamp(low):
                        continue
                    if current >= stamp(high):
                        break
                    if b"PUSCH:" not in raw:
                        continue
                    match = re.search(rb"\brnti=(0x[0-9a-f]+)\b", raw)
                    if match and match[1].decode() in allowed:
                        target.write(raw)
                        counts[match[1].decode()] += 1
        assert allowed == set(counts), (du, counts)
    sources = dict(origin="Existing logs of the final operator-run live trial",
                   cu_source_file=str(CU_LOG), du_source_files={str(k): str(v) for k, v in DU_LOGS.items()},
                   archive_window_utc=[stamp(low) + "+00:00", stamp(high) + "+00:00"],
                   end_exclusive=True, mapping=mapping,
                   cu_excerpt="Only UE creation, F1 context addition and NGAP ID header lines; no security payloads")
    (ROOT / "phy_sources.json").write_text(json.dumps(sources, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract-phy", action="store_true")
    args = parser.parse_args()
    rows = [json.loads(line) for line in (ROOT / "rows.ndjson").read_text().splitlines()]
    audit = json.loads((ROOT / "audit.json").read_text())
    assert len(rows) == 648 and len({row["app_instance"] for row in rows}) == 1
    active = windows(rows)
    origin = min(int(group[0]["header_time_us"]) for _, group in active) / 1e6
    end = max(int(group[-1]["header_time_us"]) for _, group in active) / 1e6
    low, high = math.floor(origin), math.ceil(end) + 1
    if args.extract_phy:
        extract(rows, low, high)
    sources = json.loads((ROOT / "phy_sources.json").read_text())
    buckets = defaultdict(list)
    for du in (1, 2):
        with gzip.open(ROOT / f"du{du}_pusch.log.gz", "rt") as stream:
            for line in stream:
                fields = dict(re.findall(r"\b(rnti|crc|sinr)=([^\s]+)", line))
                assert fields["crc"] in ("OK", "KO")
                fields["sinr"] = float(fields["sinr"].removesuffix("dB"))
                buckets[(du, fields["rnti"], line[:19])].append(fields)
    per_second, plotted, phases, summaries = [], [], [], {}
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 7.5), sharex=True, constrained_layout=True)
    for du, group in active:
        first, last = int(group[0]["header_time_us"]) / 1e6, int(group[-1]["header_time_us"]) / 1e6
        f1 = group[0]["row"]["ue"]["gnb_cu_ue_f1ap_id"]
        context = sources["mapping"][f"{du}/{f1}"]
        label = f"UE{du} / DU{du}" if du not in summaries else None
        axes[0].plot([int(r["header_time_us"]) / 1e6 - origin for r in group],
                     [metric(r) / 1000 for r in group], color=COLORS[du], lw=1.5, label=label)
        unmatched = [r for r in group if r["binding_status"] != "matched"]
        axes[0].scatter([int(r["header_time_us"]) / 1e6 - origin for r in unmatched],
                        [metric(r) / 1000 for r in unmatched], facecolors="none",
                        edgecolors=COLORS[du], s=55, lw=1.5, zorder=5)
        points = []
        for second in range(math.ceil(first), math.floor(last)):
            values = buckets[(du, context["rnti"], stamp(second))]
            failed = sum(item["crc"] == "KO" for item in values)
            item = dict(du_id=du, f1ap_ue_id=f1, rnti=context["rnti"],
                        utc=stamp(second) + "+00:00", unix_s=second, attempts=len(values),
                        crc_ko=failed, crc_ok=len(values) - failed,
                        crc_failed_attempt_percent=100 * failed / len(values) if values else None)
            per_second.append(item)
            points.append(item)
        axes[1].plot([item["unix_s"] + 0.5 - origin for item in points],
                     [item["crc_failed_attempt_percent"] if item["attempts"] else float("nan") for item in points],
                     color=COLORS[du], lw=1.5, label=label)
        summary = summaries.setdefault(du, dict(attempts=0, crc_ko=0, sinr=[]))
        for point in points:
            values = buckets[(du, context["rnti"], stamp(point["unix_s"]))]
            summary["attempts"] += point["attempts"]
            summary["crc_ko"] += point["crc_ko"]
            summary["sinr"].extend(item["sinr"] for item in values if math.isfinite(item["sinr"]))
        phases.append(dict(du_id=du, f1ap_ue_id=f1, rnti=context["rnti"],
                           first_positive_header_utc=datetime.fromtimestamp(first, timezone.utc).isoformat(),
                           last_positive_header_utc=datetime.fromtimestamp(last, timezone.utc).isoformat(),
                           positive_kpm_rows=len(group), full_phy_bins=len(points)))
        for row in group:
            plotted.append(dict(sequence=row["sequence"], du_id=du, f1ap_ue_id=f1,
                                header_time_us=row["header_time_us"], binding_status=row["binding_status"],
                                ue_ipv4=row["ue_ipv4"], ul_mbit_s=metric(row) / 1000))
    for episode in audit["idle_resume"]:
        begin, finish = episode["start_us"] / 1e6 - origin, episode["end_us"] / 1e6 - origin
        for ax in axes:
            ax.axvspan(begin, finish, color=COLORS[int(episode["ue"])], alpha=0.10)
        axes[0].text((begin + finish) / 2, 1.01, f"UE{episode['ue']} Core idle",
                     transform=axes[0].get_xaxis_transform(), ha="center", fontsize=9)
    for ax in axes:
        ax.grid(alpha=0.25)
        ax.set_ylim(bottom=0)
        ax.legend(loc="upper right", ncol=2, fontsize=9)
    axes[0].set_ylabel("KPM UL throughput (Mbit/s)")
    axes[1].set_ylabel("PUSCH CRC failed attempts (%)")
    axes[1].set_xlabel(f"Seconds from first positive UL KPM header ({datetime.fromtimestamp(origin, TZ).strftime('%H:%M:%S.%f')[:-3]} EDT)")
    axes[1].set_xlim(0, end - origin)
    fig.suptitle("Final dual-UE IP binding: live bidirectional idle/resume\n"
                 "Positive-UL phases only; gaps have no plotted values; hollow markers = unresolved")
    fig.savefig(ROOT / "dual_ul_kpm.png", dpi=180)
    fig.savefig(ROOT / "dual_ul_kpm.svg", metadata={"Date": None})
    plt.close(fig)
    for name, data in (("plot_kpm.csv", plotted), ("phy_per_second.csv", per_second)):
        with (ROOT / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    for summary in summaries.values():
        summary["sinr_median_db"] = statistics.median(summary.pop("sinr"))
        summary["crc_failed_attempt_percent"] = 100 * summary["crc_ko"] / summary["attempts"]
    manifest = dict(experiment_date="2026-10-21", timezone="America/New_York",
                    app_instance=rows[0]["app_instance"], captured_rows=len(rows), plotted_positive_rows=len(plotted),
                    origin_utc=datetime.fromtimestamp(origin, timezone.utc).isoformat(), duration_s=end - origin,
                    phases=phases, phy=summaries,
                    window_definition="Per-role contiguous positive UL KPM phases; no points/lines through quiet gaps",
                    phy_bin_definition="Complete one-second bins inside each positive-UL phase; NaN for missing bins",
                    crc_definition="KO / (OK + KO) PUSCH decoding attempts, including HARQ retransmissions",
                    clock_boundary="Spark timestamps; Laptop process windows are not precisely aligned")
    names = ("plot.py", "rows.ndjson", "inputs.ndjson", "phy_sources.json", "cu_phy_identity_excerpt.log",
             "du1_pusch.log.gz", "du2_pusch.log.gz", "plot_kpm.csv", "phy_per_second.csv",
             "dual_ul_kpm.png", "dual_ul_kpm.svg")
    manifest["sha256"] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names}
    (ROOT / "plot_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: manifest[key] for key in ("plotted_positive_rows", "duration_s", "phases", "phy")}, indent=2))


if __name__ == "__main__":
    main()
