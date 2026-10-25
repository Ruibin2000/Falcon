#!/usr/bin/env python3
"""Audit the retained 100 ms capture and regenerate CSVs and publication plots.

Run from any directory: python3 /path/to/this/analyze.py
Only retained evidence is read; no radio, Core query or live xApp is started.
"""

from collections import Counter
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
METRICS = [
    ("DRB.RlcSduDelayDl", "DL RLC SDU delay", "ms", 0.1, "01_dl_rlc_delay"),
    ("DRB.UEThpDl", "DL UE throughput", "Mbit/s", 0.001, "02_dl_throughput"),
    ("DRB.UEThpUl", "UL UE throughput", "Mbit/s", 0.001, "03_ul_throughput"),
    ("RRU.PrbTotDl", "DL PRB utilization", "%", 1, "04_dl_prb"),
    ("RRU.PrbTotUl", "UL PRB utilization", "%", 1, "05_ul_prb"),
    ("PUSCH.RSRP.dBFS", "PUSCH RSRP", "dBFS", 1, "06_pusch_rsrp"),
    ("PUSCH.SNR.dB", "PUSCH SNR (selected PHY SINR estimate)", "dB", 1, "07_pusch_snr"),
]
COLORS = {"1": "#2166ac", "2": "#d95f02"}
LABELS = {"1": "FR1 (DU1)", "2": "FR3 (DU2)"}


def read_jsonl(name):
    with gzip.open(ROOT / name, "rt") as stream:
        return [json.loads(line) for line in stream]


def utc(us):
    return datetime.fromtimestamp(int(us) / 1e6, timezone.utc).isoformat(timespec="microseconds")


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    return {"n": len(values), "min": values[0], "median": statistics.median(values),
            "p95": values[math.ceil(len(values) * .95) - 1],
            "p99": values[math.ceil(len(values) * .99) - 1], "max": values[-1],
            "mean": statistics.mean(values)}


def normalized_row(row):
    row = json.loads(json.dumps(row))
    for metric in row["metrics"].values():
        metric.pop("unit", None)
    return row


def payload_key(node, header, row):
    return (str(node["du_id"]), int(header),
            json.dumps(normalized_row(row), sort_keys=True, separators=(",", ":")))


def cadence(reports):
    headers = [int(e["header_time_us"]) for e in reports]
    sorted_headers = sorted(set(headers))
    receive = [int(e["received_at_mono_us"]) for e in reports]
    sorted_deltas = [(b - a) / 1000 for a, b in zip(sorted_headers, sorted_headers[1:])]
    receive_deltas = [(b - a) / 1000 for a, b in zip(receive, receive[1:])]
    return {
        "reports": len(reports), "first_header_utc": utc(min(headers)),
        "last_header_utc": utc(max(headers)), "header_span_s": (max(headers) - min(headers)) / 1e6,
        "effective_header_hz": (len(headers) - 1) * 1e6 / (max(headers) - min(headers)),
        "sorted_header_interval_ms": distribution(sorted_deltas),
        "receive_interval_ms": distribution(receive_deltas),
        "receive_intervals_under_50ms": sum(x < 50 for x in receive_deltas),
        "receive_intervals_over_150ms": sum(x > 150 for x in receive_deltas),
        "receive_intervals_90_to_110ms": sum(90 <= x <= 110 for x in receive_deltas),
        "backwards_headers_in_receive_order": sum(b < a for a, b in zip(headers, headers[1:])),
        "duplicate_headers": len(headers) - len(sorted_headers),
        "sorted_header_gaps_over_150ms": [
            {"before_utc": utc(a), "after_utc": utc(b), "gap_ms": (b - a) / 1000}
            for a, b in zip(sorted_headers, sorted_headers[1:]) if b - a > 150000],
        "header_to_callback_ms": distribution([
            (int(e["callback_at_us"]) - int(e["header_time_us"])) / 1000 for e in reports]),
        "callback_to_python_ms": distribution([
            (int(e["received_at_us"]) - int(e["callback_at_us"])) / 1000 for e in reports]),
    }


def load_mapper():
    # Use archived source, so replay remains reproducible after product changes.
    for name, filename in (("core", "core_source.py"), ("capture_mapping", "mapping_source.py")):
        spec = importlib.util.spec_from_file_location(name, ROOT / filename)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules["capture_mapping"].Mapper


def analyze(events, rows):
    du_events = [e for e in events if e["kind"] == "kpm_report" and e["node"].get("du_id") is not None]
    cu_events = [e for e in events if e["kind"] == "kpm_report" and e["node"].get("du_id") is None]
    core_events = [e for e in events if e["kind"] == "core_snapshot"]
    inputs = Counter(payload_key(e["node"], e["header_time_us"], r) for e in du_events for r in e["rows"])
    outputs = Counter(payload_key(r["node"], r["header_time_us"], r["row"]) for r in rows)
    config = json.loads((ROOT / "local.json").read_text())
    config.update(du_scope_mode="observed_unique", binding_policy="fresh_only")
    mapper = load_mapper()(config)
    replay, independent_errors, ages = [], [], {"cu": [], "core": []}
    latest_core, latest_cu = None, None
    by_input = {(str(r["node"]["du_id"]), int(r["header_time_us"])): r for r in rows}
    for event in events:
        replay.extend(mapper.ingest(event, int(event["received_at_us"]), int(event["received_at_mono_us"])))
        if event["kind"] == "core_snapshot":
            latest_core = event
        elif event["kind"] == "kpm_report" and event["node"].get("du_id") is None:
            latest_cu = event
        elif event["kind"] == "kpm_report":
            output = by_input[(str(event["node"]["du_id"]), int(event["header_time_us"]))]
            if output["binding_status"] != "matched":
                continue
            binding = output["binding"]
            identity = output["row"]["ue"]["gnb_cu_ue_f1ap_id"]
            candidates = [r for r in latest_cu["rows"]
                          if identity in r["ue"]["f1ap_ids"]
                          and str(r["ue"]["amf_ue_ngap_id"]) == binding["amf_ue_ngap_id"]]
            amf = [u for u in latest_core["amf"] if u["supi"] == binding["supi"]
                   and str(u["gnb"]["amf_ue_ngap_id"]) == binding["amf_ue_ngap_id"]
                   and str(u["gnb"]["ran_ue_ngap_id"]) == binding["ran_ue_ngap_id"]
                   and u["cm_state"] == "connected"]
            smf = [p for u in latest_core["smf"] if u["supi"] == binding["supi"] for p in u["pdu"]
                   if str(p["psi"]) == binding["pdu_session_id"] and p["dnn"] == binding["dnn"]
                   and p["ipv4"] == output["ue_ipv4"] and p["pdu_state"] == "active"]
            expected_supi = {"1": "imsi-001010000000101", "2": "imsi-001010000000102"}
            expected_nci = {"1": 6733824, "2": 6733825}
            du = str(event["node"]["du_id"])
            scope_ok = (binding["supi"] == expected_supi[du]
                        and binding["guami"] == ["001", "01", "2", "1", "0"]
                        and len(candidates) == 1
                        and candidates[0]["ue"]["guami"] == config["amf"]["guami"]
                        and len(amf) == 1 and amf[0]["gnb"]["gnb_id"] == 411
                        and amf[0]["location"]["nr_cgi"]["nci"] == expected_nci[du])
            if not (len(candidates) == len(amf) == len(smf) == 1 and scope_ok):
                independent_errors.append(output["sequence"])
            for name, previous in (("cu", latest_cu), ("core", latest_core)):
                ages[name].append((event["received_at_mono_us"] - previous["received_at_mono_us"]) / 1000)
    def comparable(row):
        return {k: v for k, v in row.items() if k not in ("app_instance", "emitted_at_us")}
    replay_mismatches = sum(comparable(a) != comparable(b) for a, b in zip(replay, rows))
    replay_mismatches += abs(len(replay) - len(rows))
    audit = {
        "capture": "/tmp/falcon-identity-dual.zcurQDSb", "event_kinds": dict(Counter(e["kind"] for e in events)),
        "output_rows": len(rows), "statuses": dict(Counter(r["binding_status"] for r in rows)),
        "source_payloads_without_equal_output": sum((inputs - outputs).values()),
        "output_payloads_without_equal_source": sum((outputs - inputs).values()),
        "mapper_replay_mismatches": replay_mismatches,
        "independent_current_cu_amf_smf_join_errors": independent_errors,
        "nonmatched_rows_with_an_ip": sum(r.get("ue_ipv4") is not None for r in rows
                                          if r["binding_status"] != "matched"),
        "matched_preceding_source_age_ms": {k: distribution(v) for k, v in ages.items()},
        "incomplete_fields": dict(Counter(str(r["row"].get("incomplete")) for r in rows)),
        "drop_counters": dict(Counter(e.get("ingress_dropped_total") for e in du_events + cu_events)),
        "du": {}, "cu": cadence(cu_events),
        "core_receive_interval_ms": distribution([
            (b["received_at_mono_us"] - a["received_at_mono_us"]) / 1000
            for a, b in zip(core_events, core_events[1:])]),
    }
    for du in ("1", "2"):
        selected = [r for r in rows if str(r["node"]["du_id"]) == du]
        reports = [e for e in du_events if str(e["node"]["du_id"]) == du]
        result = cadence(reports)
        result["statuses"] = dict(Counter(r["binding_status"] for r in selected))
        result["reasons"] = dict(Counter(r["reason"] for r in selected))
        result["granularity_ms"] = dict(Counter(r["row"]["granularity_ms"] for r in selected))
        result["callback_to_output_ms"] = distribution([
            (int(r["emitted_at_us"]) - int(r["callback_at_us"])) / 1000 for r in selected])
        result["status_segments_in_receive_order"] = []
        for key, group in itertools.groupby(selected, key=lambda r: (
                r["binding_status"], r["row"]["ue"]["gnb_cu_ue_f1ap_id"], r.get("ue_ipv4"))):
            segment = list(group)
            result["status_segments_in_receive_order"].append({
                "status": key[0], "f1ap_id": key[1], "ip": key[2], "rows": len(segment),
                "min_header_utc": utc(min(int(r["header_time_us"]) for r in segment)),
                "max_header_utc": utc(max(int(r["header_time_us"]) for r in segment))})
        result["metrics"] = {}
        for name, *_ in METRICS:
            metrics = [r["row"]["metrics"][name] for r in selected]
            result["metrics"][name] = {"types": dict(Counter(m["type"] for m in metrics)),
                                       "raw_values": distribution([m["value"] for m in metrics if m["type"] != "no_value"])}
        active = [r for r in selected if r["row"]["metrics"]["DRB.UEThpUl"]["value"] > 1000]
        result["ul_over_1mbit_samples"] = len(active)
        result["ul_over_1mbit_rf_real_samples"] = sum(all(r["row"]["metrics"][name]["type"] == "real"
                   for name in ("PUSCH.RSRP.dBFS", "PUSCH.SNR.dB")) for r in active)
        result["ul_over_1mbit_prb_numeric_samples"] = sum(all(r["row"]["metrics"][name]["type"] != "no_value"
                   for name in ("RRU.PrbTotDl", "RRU.PrbTotUl")) for r in active)
        audit["du"][du] = result
    (ROOT / "audit.json").write_text(json.dumps(audit, indent=2, allow_nan=False) + "\n")
    return audit


def save_csv(rows):
    fields = ["sequence", "du_id", "logical_path", "header_time_utc", "elapsed_s", "binding_status",
              "reason", "f1ap_id", "ue_ipv4", "granularity_ms"]
    for name, *_ in METRICS:
        fields.extend([name, name + ".type"])
    t0 = min(int(r["header_time_us"]) for r in rows)
    with (ROOT / "seven_metrics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: (int(r["header_time_us"]), r["node"]["du_id"])):
            du = str(row["node"]["du_id"])
            item = {"sequence": row["sequence"], "du_id": du, "logical_path": LABELS[du],
                    "header_time_utc": utc(row["header_time_us"]),
                    "elapsed_s": (int(row["header_time_us"]) - t0) / 1e6,
                    "binding_status": row["binding_status"], "reason": row["reason"],
                    "f1ap_id": row["row"]["ue"]["gnb_cu_ue_f1ap_id"],
                    "ue_ipv4": row.get("ue_ipv4"), "granularity_ms": row["row"]["granularity_ms"]}
            for name, *_ in METRICS:
                item[name] = row["row"]["metrics"][name]["value"]
                item[name + ".type"] = row["row"]["metrics"][name]["type"]
            writer.writerow(item)


def plots(events, rows):
    os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="falcon-100ms-plot-", dir="/tmp"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "savefig.dpi": 180, "svg.fonttype": "none"})
    t0 = min(int(r["header_time_us"]) for r in rows)
    selected = {du: sorted((r for r in rows if str(r["node"]["du_id"]) == du),
                           key=lambda r: int(r["header_time_us"])) for du in ("1", "2")}
    end = (max(int(r["header_time_us"]) for r in rows) - t0) / 1e6
    annotation = ("All received samples; no smoothing. Blank = no_value or source gap >150 ms.\n"
                  "Path labels follow DU identity; FR1 IP was unresolved. Both radios use NR n78.")
    def metric_axis(ax, definition, overview=False):
        name, title, unit, scale, _ = definition
        for du in ("1", "2"):
            x, y, previous = [], [], None
            for r in selected[du]:
                current = int(r["header_time_us"])
                if previous is not None and current - previous > 150000:
                    x.append((previous + current - 2 * t0) / 2e6)
                    y.append(float("nan"))
                metric = r["row"]["metrics"][name]
                x.append((current - t0) / 1e6)
                y.append(float("nan") if metric["type"] == "no_value" else metric["value"] * scale)
                previous = current
            ax.plot(x, y, color=COLORS[du], linewidth=.8, marker=".", markersize=1.6,
                    alpha=.9, label=LABELS[du])
        ax.set_title(name if overview else name + " — " + title, loc="left", fontsize=11, pad=7)
        ax.set_ylabel(unit)
        ax.set_xlim(0, end)
        ax.grid(alpha=.2)
        if name == "RRU.PrbTotUl":
            ax.set_ylim(-2, 102)
        elif name == "RRU.PrbTotDl":
            ax.set_ylim(-.2, 5.8)
        if name.startswith("RRU."):
            ax.text(.99, .93, "FR3: no_value after F1 context changes to 2", transform=ax.transAxes,
                    ha="right", va="top", fontsize=8, color=COLORS["2"],
                    bbox={"facecolor": "white", "alpha": .8, "edgecolor": "none"})
        ax.legend(loc="upper left" if unit == "%" else "upper right", ncol=2, fontsize=8)
    with PdfPages(ROOT / "seven_metrics.pdf") as pdf:
        for definition in METRICS:
            fig, ax = plt.subplots(figsize=(12, 4.2))
            metric_axis(ax, definition)
            ax.set_xlabel("Elapsed collection time (s), from " + utc(t0))
            fig.text(.08, .025, annotation, fontsize=8, color="#444444")
            fig.subplots_adjust(left=.08, right=.98, top=.88, bottom=.25)
            for extension in ("png", "svg"):
                fig.savefig(ROOT / (definition[-1] + "." + extension))
            pdf.savefig(fig)
            plt.close(fig)
    fig, axes = plt.subplots(7, 1, figsize=(12, 17), sharex=True)
    for ax, definition in zip(axes, METRICS):
        metric_axis(ax, definition, overview=True)
    axes[-1].set_xlabel("Elapsed collection time (s), from " + utc(t0))
    fig.suptitle("Dual UE seven-metric KPM capture — DU 100 ms / CU 1 s", y=.985, fontsize=15)
    fig.text(.085, .02, annotation, fontsize=9)
    fig.subplots_adjust(left=.085, right=.98, top=.96, bottom=.075, hspace=.52)
    fig.savefig(ROOT / "seven_metrics_overview.png")
    fig.savefig(ROOT / "seven_metrics_overview.svg")
    plt.close(fig)
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    for du in ("1", "2"):
        q = [e for e in events if e["kind"] == "kpm_report" and str(e["node"].get("du_id")) == du]
        origin = q[0]["received_at_mono_us"]
        axes[0].scatter([(b["received_at_mono_us"] - origin) / 1e6 for b in q[1:]],
                        [(b["received_at_mono_us"] - a["received_at_mono_us"]) / 1000 for a, b in zip(q, q[1:])],
                        s=6, alpha=.45, color=COLORS[du], label=LABELS[du])
        latency = sorted((int(e["callback_at_us"]) - int(e["header_time_us"])) / 1000 for e in q)
        axes[1].plot(latency, [(i + 1) / len(latency) for i in range(len(latency))],
                     color=COLORS[du], label=LABELS[du])
        numeric = {"unresolved": 0, "ambiguous": 1, "matched": 2}
        axes[2].step([(int(r["header_time_us"]) - t0) / 1e6 for r in selected[du]],
                     [numeric[r["binding_status"]] + (-.07 if du == "1" else .07) for r in selected[du]],
                     where="post", color=COLORS[du], linewidth=1.2, label=LABELS[du])
    axes[0].axhline(100, color="#444444", linestyle="--", linewidth=.8, label="100 ms target")
    axes[0].set(xlabel="Elapsed Python receive time per DU (s)", ylabel="Receive interval (ms)",
                title="Arrival cadence: burst pairs separated by about 209 ms")
    axes[1].axvline(100, color="#444444", linestyle="--", linewidth=.8)
    axes[1].set(xlabel="DU header to C xApp callback (ms)", ylabel="Cumulative fraction",
                title="Same-host timestamp span; excludes the source measurement window")
    axes[2].set(yticks=[0, 1, 2], yticklabels=["unresolved", "ambiguous", "matched"],
                xlabel="Elapsed collection time (s)", title="IP binding status")
    for ax in axes:
        ax.legend(loc="best", ncol=3, fontsize=8)
        ax.grid(alpha=.2)
    fig.tight_layout(h_pad=2.4)
    fig.savefig(ROOT / "cadence_and_binding.png")
    fig.savefig(ROOT / "cadence_and_binding.svg")
    plt.close(fig)


def main():
    rows, events = read_jsonl("rows.ndjson.gz"), read_jsonl("inputs.ndjson.gz")
    audit = analyze(events, rows)
    save_csv(rows)
    plots(events, rows)
    files = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(ROOT.iterdir()) if p.is_file() and p.name != "artifact_manifest.json"}
    (ROOT / "artifact_manifest.json").write_text(json.dumps(files, indent=2) + "\n")
    print(json.dumps({k: audit[k] for k in ("output_rows", "statuses", "mapper_replay_mismatches",
          "source_payloads_without_equal_output", "output_payloads_without_equal_source",
          "independent_current_cu_amf_smf_join_errors")}, indent=2))


if __name__ == "__main__":
    main()
