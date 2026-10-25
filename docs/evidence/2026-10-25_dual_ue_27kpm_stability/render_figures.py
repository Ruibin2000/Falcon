"""Rebuild the figures, CSVs and independent checks from the archived capture.

Run with Python 3, numpy and matplotlib. No live services or repository imports
are required. Missing values remain gaps; zero RSRP is a normal numeric reading.
"""

import bisect
import csv
import gzip
import json
import math
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "falcon-report-matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
COLORS = {"1": "#176bb2", "2": "#df7424"}
LABELS = {"1": "FR1 / UE1", "2": "FR3 / UE2"}
PHASE_COLORS = {"fr1": "#dceaf7", "fr3": "#fbe8d3", "both": "#dff0e4"}
GROUPS = [
    ("baseline_seven", "Seven baseline KPM measurements", [
        "DRB.RlcSduDelayDl", "DRB.UEThpDl", "DRB.UEThpUl",
        "RRU.PrbTotDl", "RRU.PrbTotUl", "PUSCH.RSRP.dBFS", "PUSCH.SNR.dB",
    ]),
    ("radio_feedback", "CQI, MCS and uplink power headroom", [
        "CQI", "CQI.Samples", "DL.MCS", "UL.MCS", "DL.MCS.Samples",
        "UL.MCS.Samples", "UL.PHR.dB", "UL.PHR.AgeMs",
    ]),
    ("buffers", "Latest reported buffer values and their ages", [
        "UL.BSR.Bytes", "UL.BSR.AgeMs", "DL.Buffer.Bytes", "DL.Buffer.AgeMs",
    ]),
    ("load_and_outcomes", "MAC throughput, HARQ, CRC and REAL PRB utilization", [
        "DL.MAC.Throughput", "UL.MAC.Throughput", "DL.HARQ.Ok", "DL.HARQ.Nok",
        "UL.CRC.Ok", "UL.CRC.Nok", "PRB.UsageDl.Percent", "PRB.UsageUl.Percent",
    ]),
]
NAMES = [name for _, _, names in GROUPS for name in names]


def read_json(path):
    return json.loads((ROOT / path).read_text())


def read_ndjson(path):
    with gzip.open(ROOT / path, "rt") as stream:
        return [json.loads(line) for line in stream]


def epoch(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def dump(path, value):
    (ROOT / path).write_text(json.dumps(value, indent=2) + "\n")


def write_csv(path, names, records):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(ROOT / path, "wt", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(names)
        writer.writerows(records)


def main():
    summary = read_json("analysis.json")
    rows = read_ndjson("xapp/rows.ndjson.gz")
    events = read_ndjson("xapp/inputs.ndjson.gz")
    traffic = read_json("laptop/summary.json")
    origin = epoch(summary["utc_start"])
    duration = summary["capture_seconds"]
    selected = {du: [r for r in rows if r["node"]["du_id"] == du] for du in COLORS}
    reports = {
        du: [e for e in events if e["kind"] == "kpm_report"
             and e["node"]["node_type"] == "ngran_gNB_DU" and e["node"]["du_id"] == du]
        for du in COLORS
    }
    times = {du: np.array([int(r["header_time_us"]) / 1e6 - origin for r in rr])
             for du, rr in selected.items()}
    values = {
        du: {name: np.array([r["row"]["metrics"][name]["value"]
                            if r["row"]["metrics"][name]["value"] is not None else np.nan
                            for r in rr], dtype=float) for name in NAMES}
        for du, rr in selected.items()
    }
    # Compare every output record with its decoded E2 input, before Python mapping.
    raw = {}
    for e in events:
        if e["kind"] == "kpm_report" and e["node"]["node_type"] == "ngran_gNB_DU":
            for r in e["rows"]:
                raw[(e["node"]["du_id"], str(e["header_time_us"]),
                     str(r["ue"]["gnb_cu_ue_f1ap_id"]), r["sample_idx"])] = r["metrics"]
    audit = Counter()
    core = [e for e in events if e["kind"] == "core_snapshot"]
    cu = [e for e in events if e["kind"] == "kpm_report"
          and e["node"]["node_type"] != "ngran_gNB_DU"]
    core_times = [int(e["received_at_us"]) for e in core]
    cu_times = [int(e["received_at_us"]) for e in cu]
    ages = {"cu_ms": [], "core_ms": []}
    for r in rows:
        du = r["node"]["du_id"]
        m = r["row"]["metrics"]
        assert set(m) == set(NAMES) and len(m) == 27
        key = (du, str(r["header_time_us"]), str(r["row"]["ue"]["gnb_cu_ue_f1ap_id"]),
               r["row"]["sample_idx"])
        assert raw[key] == {n: {"type": v["type"], "value": v["value"]} for n, v in m.items()}
        audit["decoded_input_output_equal"] += 1
        for name, item in m.items():
            value = item["value"]
            assert (value is None) == (item["type"] == "no_value")
            assert value is None or math.isfinite(value)
            if name.endswith("AgeMs") and value is not None:
                assert value >= 0
        for prefix in ("DL.HARQ", "UL.CRC"):
            ok, nok = [m[prefix + "." + k]["value"] for k in ("Ok", "Nok")]
            expected = 100 * nok / (ok + nok) if ok is not None and nok is not None and ok + nok else None
            actual = r["derived_metrics"][prefix + ".FailureRatio"]["value"]
            assert actual == expected
        if r["binding_status"] != "matched":
            assert r["ue_ipv4"] is None
            continue
        t = int(r["received_at_us"])
        ci, ui = bisect.bisect_right(core_times, t) - 1, bisect.bisect_right(cu_times, t) - 1
        assert ci >= 0 and ui >= 0
        binding = r["binding"]
        c, u = core[ci], cu[ui]
        amf = [x for x in c["amf"] if x["supi"] == binding["supi"]]
        assert len(amf) == 1
        assert str(amf[0]["gnb"]["amf_ue_ngap_id"]) == binding["amf_ue_ngap_id"]
        assert str(amf[0]["gnb"]["ran_ue_ngap_id"]) == binding["ran_ue_ngap_id"]
        sessions = [p for x in c["smf"] if x["supi"] == binding["supi"] for p in x["pdu"]
                    if str(p["psi"]) == binding["pdu_session_id"] and p["dnn"] == binding["dnn"]]
        assert len(sessions) == 1 and sessions[0]["ipv4"] == r["ue_ipv4"]
        scope = [x["ue"] for x in u["rows"]
                 if str(x["ue"]["amf_ue_ngap_id"]) == binding["amf_ue_ngap_id"]]
        assert len(scope) == 1
        allocated = int(scope[0]["ran_ue_id_hex"], 16)
        assert str(allocated >> 28) == du == binding["serving_du_id"]
        assert str(allocated & ((1 << 28) - 1)) == binding["cu_ue_index"]
        assert key[2] in scope[0]["f1ap_ids"]
        guami = scope[0]["guami"]
        assert [str(guami[k]) for k in ("mcc", "mnc", "amf_region_id", "amf_set_id", "amf_pointer")] == binding["guami"]
        for label, timestamp in (("cu_ms", cu_times[ui]), ("core_ms", core_times[ci])):
            age = (t - timestamp) / 1000
            assert 0 <= age <= 3000
            ages[label].append(age)
        audit["matched_rows_checked_against_preceding_cu_and_core"] += 1
    assert audit["decoded_input_output_equal"] == 7158
    assert audit["matched_rows_checked_against_preceding_cu_and_core"] == 7138
    assert traffic["status"] == "completed" and not traffic["allocation_changes"]
    clients = [link for phase in traffic["phases"] for link in phase["links"]]
    assert len(clients) == 8 and all(link["exit_code"] == 0 for link in clients)
    for link in clients:
        client = read_json("laptop/" + link["log"])
        assert client["end"]["sum_sent"]["retransmits"] == 0
    for phase, result in zip(traffic["phases"], summary["phases"]):
        assert phase["phase"] == result["phase"]
        for link, saved in zip(phase["links"], result["clients"]):
            client = read_json("laptop/" + link["log"])
            assert client["end"]["sum_received"]["bits_per_second"] / 1e6 == saved["receiver_mbps"]
            assert client["end"]["sum_received"]["seconds"] == saved["receiver_seconds"]
    for du, rr in reports.items():
        gaps = np.diff([int(e["received_at_mono_us"]) for e in rr]) / 1000
        saved = summary["nodes"][du]["receive"]["interval_ms"]
        assert abs(np.median(gaps) - saved["median"]) < 1e-6
        assert abs(max(gaps) - saved["max"]) < 1e-6
        assert max(int(e.get("ingress_dropped_total", 0)) for e in rr) == 0
    zero_rsrp = sum(np.count_nonzero(values[du]["PUSCH.RSRP.dBFS"] == 0) for du in COLORS)
    assert zero_rsrp == 7
    verification = dict(audit) | {
        "iperf_completed": len(clients), "rsrp_zero_normal_readings": int(zero_rsrp),
        "max_preceding_source_age_ms": {k: max(v) for k, v in ages.items()},
        "plots_cover_unique_metric_names": len(set(NAMES)),
        "receiver_rates_and_durations_recomputed": True,
        "receive_medians_and_maxima_recomputed": True,
        "status": "passed",
    }

    headers = ["sequence", "path", "header_time_utc", "seconds_from_capture_start", "binding_status", "ue_ipv4"]
    for name in NAMES:
        headers += [name, name + ".record_type"]
    csv_rows = []
    for r in rows:
        record = [r["sequence"], LABELS[r["node"]["du_id"]],
                  datetime.fromtimestamp(int(r["header_time_us"]) / 1e6, ZoneInfo("UTC")).isoformat(),
                  round(int(r["header_time_us"]) / 1e6 - origin, 6), r["binding_status"], r["ue_ipv4"]]
        for name in NAMES:
            item = r["row"]["metrics"][name]
            record += [item["value"], item["type"]]
        csv_rows.append(record)
    write_csv("metrics_100ms.csv.gz", headers, csv_rows)
    available = []
    for name in NAMES:
        counts = {du: (int(np.isfinite(values[du][name]).sum()), int(np.isnan(values[du][name]).sum()))
                  for du in COLORS}
        available.append([name, rows[0]["row"]["metrics"][name]["unit"], *counts["1"], *counts["2"]])
    write_csv("metric_availability.csv", ["metric", "unit", "FR1_numeric", "FR1_no_value", "FR3_numeric", "FR3_no_value"], available)
    interval_rows = []
    for du, rr in reports.items():
        for previous, current in zip(rr, rr[1:]):
            interval_rows.append([LABELS[du], current["header_time_us"],
                                  (int(current["header_time_us"]) - int(previous["header_time_us"])) / 1000,
                                  (int(current["received_at_mono_us"]) - int(previous["received_at_mono_us"])) / 1000])
    write_csv("report_intervals.csv", ["path", "header_time_us", "header_interval_ms", "receive_interval_ms"], interval_rows)

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.titleweight": "semibold", "svg.fonttype": "none"})
    start_label = datetime.fromisoformat(summary["utc_start"]).astimezone(ZoneInfo("America/New_York"))
    xlabel = f"Seconds from capture start | {start_label:%Y-%m-%d %H:%M:%S %Z}"

    def decorate(ax, phase_labels=False):
        for phase in traffic["phases"]:
            a, b = epoch(phase["started_at"]) - origin, epoch(phase["ended_at"]) - origin
            ax.axvspan(a, b, color=PHASE_COLORS[phase["label"]], alpha=.65, zorder=0)
            if phase_labels:
                label = f"{phase['phase']}: " + {"fr1": "FR1", "fr3": "FR3", "both": "BOTH"}[phase["label"]]
                ax.text((a + b) / 2, 1.02, label, ha="center", va="bottom",
                        transform=ax.get_xaxis_transform(), fontsize=8)
        ax.set_xlim(0, duration)
        ax.set_xticks(np.arange(0, 361, 60))
        ax.grid(axis="y", alpha=.22)

    def save(fig, stem):
        fig.savefig(ROOT / (stem + ".png"), dpi=170)
        fig.savefig(ROOT / (stem + ".svg"))
        plt.close(fig)

    def plot_paths(ax, metric, ylabel, scale=1.0, derived=False):
        for du in COLORS:
            y = np.array([
                r["derived_metrics"][metric]["value"]
                if r["derived_metrics"][metric]["value"] is not None else np.nan
                for r in selected[du]
            ]) if derived else values[du][metric]
            ax.plot(times[du], y * scale, color=COLORS[du], lw=.55, marker=".",
                    markersize=1.7, alpha=.75, label=LABELS[du])
        ax.set_ylabel(ylabel)
        ax.legend(loc="lower left", ncol=2, fontsize=8, frameon=False)

    # Two path-specific traffic panels, followed by seven shared UL metric rows.
    ul_rows = [
        ("PUSCH.SNR.dB", "PUSCH SNR\n(dB)", 1, False),
        ("PUSCH.RSRP.dBFS", "PUSCH RSRP\n(dBFS)", 1, False),
        ("UL.CRC.FailureRatio", "UL CRC NOK\n(%, derived)", 1, True),
        ("UL.PHR.dB", "UL PHR\n(dB)", 1, False),
        ("UL.MCS", "UL MCS\n(index)", 1, False),
        ("PRB.UsageUl.Percent", "UL PRB use\n(%, REAL)", 1, False),
        ("UL.BSR.Bytes", "UL BSR\n(kB, latest report)", .001, False),
    ]
    fig, axes = plt.subplots(2 + len(ul_rows), 1, figsize=(14, 21), sharex=True,
                             constrained_layout=True)
    for index, du in enumerate(COLORS):
        ax = axes[index]
        bins = defaultdict(list)
        for t, value in zip(times[du], values[du]["UL.MAC.Throughput"]):
            bins[int(t)].append(value)
        xx = sorted(bins)
        ax.plot([x + .5 for x in xx], [np.nanmean(bins[x]) / 1000 for x in xx], color=COLORS[du], lw=1.2,
                label="DU UL MAC throughput (1 s mean)")
        for i, session in enumerate(summary["servers"]["FR1" if du == "1" else "FR3"]["sessions"]):
            accepted = epoch(session["accepted_utc"]) - origin
            ax.plot([accepted + (v["start"] + v["end"]) / 2 for v in session["intervals"]],
                    [v["mbps"] for v in session["intervals"]], color="#1f2328", ls="--", lw=1,
                    label="iperf3 receiver goodput (~1 s)" if i == 0 else None)
        ax.set_ylabel(LABELS[du] + "\nUL (Mbit/s)")
        ax.set_ylim(bottom=-.5)
        ax.legend(loc="upper left", fontsize=8, ncol=2, frameon=False)
    for ax, (metric, ylabel, scale, derived) in zip(axes[2:], ul_rows):
        plot_paths(ax, metric, ylabel, scale, derived)
        if derived:
            ax.set_ylim(-2, 102)
    for index, ax in enumerate(axes):
        decorate(ax, phase_labels=index == 0)
    axes[-1].set_xlabel(xlabel)
    fig.suptitle("Uplink traffic and main DU metrics over six minutes\nTraffic rows: solid = DU MAC, dashed = iperf3 receiver | metric rows: 100 ms", fontsize=14)
    save(fig, "traffic_and_rf")

    dl_rows = [
        ("DL.MAC.Throughput", "DL MAC rate\n(Mbit/s)", .001, False),
        ("CQI", "DL CQI\n(index)", 1, False),
        ("DL.MCS", "DL MCS\n(index)", 1, False),
        ("PRB.UsageDl.Percent", "DL PRB use\n(%, REAL)", 1, False),
        ("DL.Buffer.Bytes", "DL buffer\n(bytes, latest)", 1, False),
        ("DRB.RlcSduDelayDl", "DL RLC SDU delay\n(ms)", .1, False),
        ("DL.HARQ.FailureRatio", "DL HARQ NOK\n(%, derived)", 1, True),
    ]
    fig, axes = plt.subplots(len(dl_rows), 1, figsize=(14, 16.5), sharex=True,
                             constrained_layout=True)
    for index, (ax, (metric, ylabel, scale, derived)) in enumerate(zip(axes, dl_rows)):
        plot_paths(ax, metric, ylabel, scale, derived)
        decorate(ax, phase_labels=index == 0)
        if derived:
            ax.set_ylim(-2, 102)
    axes[-1].set_xlabel(xlabel)
    fig.suptitle("Main downlink metrics during the uplink experiment\nBlue = FR1 / UE1; orange = FR3 / UE2; phase shading follows the UL workload", fontsize=14)
    save(fig, "downlink_overview")
    verification["overview_rows"] = {"uplink": 2 + len(ul_rows), "downlink": len(dl_rows)}
    verification["overview_order"] = {
        "uplink": ["FR1 UL", "FR3 UL"] + [row[0] for row in ul_rows],
        "downlink": [row[0] for row in dl_rows],
    }

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    for index, du in enumerate(COLORS):
        rr = reports[du]
        gaps = np.diff([int(e["received_at_mono_us"]) for e in rr]) / 1000
        x = np.array([int(e["header_time_us"]) / 1e6 - origin for e in rr[1:]])
        ax = axes[0, index]
        ax.plot(x, gaps, color=COLORS[du], lw=.55)
        ax.axhline(100, color="#576579", ls="--", lw=.8)
        ax.set_title(LABELS[du] + " receive intervals")
        ax.set_ylabel("Interval (ms)")
        ax.set_ylim(96, 104)
        ax.set_xlabel("Seconds from capture start")
        decorate(ax)
        axes[1, 0].hist(gaps, bins=np.arange(96, 104.1, .15), color=COLORS[du], alpha=.55, label=LABELS[du])
        status = {"unresolved": 0, "ambiguous": 1, "matched": 2}
        axes[1, 1].step(times[du], [status[r["binding_status"]] + (index * .08) for r in selected[du]],
                        where="post", color=COLORS[du], label=LABELS[du], lw=1.7)
    axes[1, 0].set(xlabel="Receive interval (ms)", ylabel="Count", title="Distribution of all 7,156 DU receive intervals")
    axes[1, 0].axvline(100, color="#576579", ls="--", lw=.8)
    axes[1, 0].legend(frameon=False)
    axes[1, 1].set(xlim=(1.8, 6), ylim=(-.2, 2.35), xlabel="Seconds from capture start",
                   yticks=[0, 1, 2], yticklabels=["unresolved", "ambiguous", "matched"],
                   title="Startup binding settles after CU scope arrives")
    axes[1, 1].legend(frameon=False, loc="lower right")
    fig.suptitle("DU 100 ms delivery with CU identity at 1 s\nZero reported collector ingress drops; all 7,138 rows after startup matched", fontsize=14)
    save(fig, "cadence_and_binding")

    for stem, title, names in GROUPS:
        height = 3.05 * math.ceil(len(names) / 2)
        fig, axes = plt.subplots(math.ceil(len(names) / 2), 2, figsize=(14, height), constrained_layout=True)
        for index, (ax, name) in enumerate(zip(axes.flat, names)):
            unit = rows[0]["row"]["metrics"][name]["unit"]
            scale, label = (0.1, "ms") if name == "DRB.RlcSduDelayDl" else ((.001, "Mbit/s") if unit == "kbit/s" else (1, unit))
            for du in COLORS:
                ax.plot(times[du], values[du][name] * scale, color=COLORS[du], lw=.55,
                        marker=".", markersize=1.4, alpha=.8, label=LABELS[du])
            ax.set_title(name, fontsize=10)
            ax.set_ylabel(label)
            decorate(ax)
            if index >= len(names) - 2:
                ax.set_xlabel("Seconds from capture start")
        for ax in list(axes.flat)[len(names):]:
            ax.set_visible(False)
        axes.flat[0].legend(loc="upper right", ncol=2, fontsize=8, framealpha=.85)
        fig.suptitle(title + "\nRaw 100 ms records; gaps mean no_value; zero remains a numeric value", fontsize=14)
        save(fig, stem)
    dump("verification.json", verification)
    print(json.dumps(verification, indent=2))
    print("Generated seven PNG/SVG figures and three CSV datasets in", ROOT)


if __name__ == "__main__":
    main()
