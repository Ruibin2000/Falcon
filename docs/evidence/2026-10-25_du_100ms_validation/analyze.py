#!/usr/bin/env python3
"""Audit and plot the retained augMIYJM capture without accessing live services."""

from collections import Counter
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
METRICS = [
    ("DRB.RlcSduDelayDl", "DL RLC SDU delay", "ms", .1, "01_dl_rlc_delay"),
    ("DRB.UEThpDl", "DL throughput", "Mbit/s", .001, "02_dl_throughput"),
    ("DRB.UEThpUl", "UL throughput", "Mbit/s", .001, "03_ul_throughput"),
    ("RRU.PrbTotDl", "DL PRB utilization", "%", 1, "04_dl_prb"),
    ("RRU.PrbTotUl", "UL PRB utilization", "%", 1, "05_ul_prb"),
    ("PUSCH.RSRP.dBFS", "UL PUSCH RSRP", "dBFS", 1, "06_pusch_rsrp"),
    ("PUSCH.SNR.dB", "UL PUSCH SNR", "dB", 1, "07_pusch_snr"),
]
COLORS = {"1": "#0072B2", "2": "#D55E00"}
LABELS = {"1": "FR1 (DU1)", "2": "FR3 (DU2)"}


def read(name):
    with gzip.open(ROOT / name, "rt") as stream:
        return [json.loads(line) for line in stream]


def utc(us):
    return datetime.fromtimestamp(int(us) / 1e6, timezone.utc).isoformat(timespec="microseconds")


def stats(values):
    a = sorted(values)
    if not a:
        return {"n": 0}
    return {"n": len(a), "min": a[0], "median": statistics.median(a),
            "p95": a[math.ceil(.95 * len(a)) - 1], "p99": a[math.ceil(.99 * len(a)) - 1],
            "max": a[-1], "mean": statistics.mean(a)}


def payload(node, header, row):
    row = json.loads(json.dumps(row))
    for metric in row["metrics"].values():
        metric.pop("unit", None)
    return (str(node["du_id"]), int(header), json.dumps(row, sort_keys=True, separators=(",", ":")))


def cadence(reports):
    headers = [int(e["header_time_us"]) for e in reports]
    ordered = sorted(set(headers))
    intervals = [(b["received_at_mono_us"] - a["received_at_mono_us"]) / 1000
                 for a, b in zip(reports, reports[1:])]
    return {
        "reports": len(reports), "first_header_utc": utc(min(headers)), "last_header_utc": utc(max(headers)),
        "header_span_s": (max(headers) - min(headers)) / 1e6,
        "effective_report_hz": (len(headers) - 1) * 1e6 / (max(headers) - min(headers)),
        "sorted_header_interval_ms": stats([(b - a) / 1000 for a, b in zip(ordered, ordered[1:])]),
        "receive_interval_ms": stats(intervals),
        "receive_intervals_90_to_110ms": sum(90 <= t <= 110 for t in intervals),
        "receive_intervals_above_150ms": sum(t > 150 for t in intervals),
        "backward_headers": sum(b < a for a, b in zip(headers, headers[1:])),
        "duplicate_headers": len(headers) - len(ordered),
        "header_to_callback_ms": stats([(int(e["callback_at_us"]) - int(e["header_time_us"])) / 1000
                                        for e in reports]),
    }


def archived_mapper():
    for name, filename in (("core", "core_source.py"), ("capture_mapping", "mapping_source.py")):
        spec = importlib.util.spec_from_file_location(name, ROOT / filename)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules["capture_mapping"].Mapper


def audit(events, rows):
    kpm = [e for e in events if e["kind"] == "kpm_report"]
    du = [e for e in kpm if e["node"].get("du_id") is not None]
    cu = [e for e in kpm if e["node"].get("du_id") is None]
    cores = [e for e in events if e["kind"] == "core_snapshot"]
    original = Counter(payload(e["node"], e["header_time_us"], q) for e in du for q in e["rows"])
    output = Counter(payload(r["node"], r["header_time_us"], r["row"]) for r in rows)
    by_key = {(str(r["node"]["du_id"]), int(r["header_time_us"])): r for r in rows}
    assert len(by_key) == len(rows), "Duplicate output header within a DU"
    config = json.loads((ROOT / "local.json").read_text())
    config.update(du_scope_mode="observed_unique", binding_policy="fresh_only")
    mapper = archived_mapper()(config)
    replay, errors = [], []
    ages = {"cu": [], "core": []}
    current_cu = current_core = None
    for event in events:
        replay.extend(mapper.ingest(event, int(event["received_at_us"]), int(event["received_at_mono_us"])))
        if event["kind"] == "core_snapshot":
            current_core = event
        elif event["kind"] == "kpm_report" and event["node"].get("du_id") is None:
            current_cu = event
        elif event["kind"] == "kpm_report":
            d = str(event["node"]["du_id"])
            row = by_key[(d, int(event["header_time_us"]))]
            if row["binding_status"] != "matched":
                continue
            b = row["binding"]
            candidates = [r for r in current_cu["rows"]
                          if str(int(r["ue"]["ran_ue_id_hex"], 16) >> 28) == d
                          and str(int(r["ue"]["ran_ue_id_hex"], 16) & ((1 << 28) - 1)) == b["cu_ue_index"]
                          and row["row"]["ue"]["gnb_cu_ue_f1ap_id"] in r["ue"]["f1ap_ids"]
                          and r["ue"]["amf_ue_ngap_id"] == b["amf_ue_ngap_id"]
                          and [str(r["ue"]["guami"][k]) for k in
                               ("mcc", "mnc", "amf_region_id", "amf_set_id", "amf_pointer")] == b["guami"]]
            amf = [u for u in current_core["amf"] if u["supi"] == b["supi"]
                   and str(u["gnb"]["amf_ue_ngap_id"]) == b["amf_ue_ngap_id"]
                   and str(u["gnb"]["ran_ue_ngap_id"]) == b["ran_ue_ngap_id"]
                   and u["gnb"]["gnb_id"] == 411 and u["cm_state"] == "connected"
                   and u["location"]["nr_cgi"]["nci"] == {"1": 6733824, "2": 6733825}[d]]
            smf = [p for u in current_core["smf"] if u["supi"] == b["supi"] for p in u["pdu"]
                   if str(p["psi"]) == b["pdu_session_id"] and p["dnn"] == b["dnn"]
                   and p["ipv4"] == row["ue_ipv4"] and p["pdu_state"] == "active"]
            expected = {"1": "imsi-001010000000101", "2": "imsi-001010000000102"}[d]
            if not (len(candidates) == len(amf) == len(smf) == 1 and b["supi"] == expected
                    and b["serving_du_id"] == d):
                errors.append(row["sequence"])
            for name, source in (("cu", current_cu), ("core", current_core)):
                age = (event["received_at_mono_us"] - source["received_at_mono_us"]) / 1000
                ages[name].append(age)
                if not 0 <= age < config["source_ttl_s"] * 1000:
                    errors.append(row["sequence"])
    def comparable(row):
        return {k: v for k, v in row.items() if k not in ("app_instance", "emitted_at_us")}
    matched = [r for r in rows if r["binding_status"] == "matched"]
    first = matched[0]
    result = {
        "capture": "/tmp/falcon-identity-dual.augMIYJM", "output_rows": len(rows),
        "events": dict(Counter(e["kind"] for e in events)),
        "statuses": dict(Counter(r["binding_status"] for r in rows)),
        "input_payloads_without_equal_output": sum((original - output).values()),
        "output_payloads_without_equal_input": sum((output - original).values()),
        "replay_mismatches": sum(comparable(a) != comparable(b) for a, b in zip(replay, rows)) + abs(len(replay) - len(rows)),
        "independent_join_errors": errors, "matched_source_age_ms": {k: stats(v) for k, v in ages.items()},
        "first_matched_sequence": first["sequence"], "first_matched_header_utc": utc(first["header_time_us"]),
        "nonmatched_after_first_match": sum(r["binding_status"] != "matched" for r in rows if r["sequence"] >= first["sequence"]),
        "unverified_published_ips": sum(r["ue_ipv4"] is not None for r in rows if r["binding_status"] != "matched"),
        "incomplete": dict(Counter(str(r["row"].get("incomplete")) for r in rows)),
        "drop_counters": dict(Counter(e.get("ingress_dropped_total") for e in kpm)),
        "cu": cadence(cu), "core_receive_interval_ms": stats([
            (b["received_at_mono_us"] - a["received_at_mono_us"]) / 1000 for a, b in zip(cores, cores[1:])]), "du": {},
    }
    for d in ("1", "2"):
        selected = [r for r in rows if str(r["node"]["du_id"]) == d]
        record = cadence([e for e in du if str(e["node"]["du_id"]) == d])
        record["statuses"] = dict(Counter(r["binding_status"] for r in selected))
        record["granularity_ms"] = dict(Counter(str(r["row"]["granularity_ms"]) for r in selected))
        record["f1_ids"] = dict(Counter(r["row"]["ue"]["gnb_cu_ue_f1ap_id"] for r in selected))
        record["bindings"] = [json.loads(s) for s in sorted({json.dumps(dict(r["binding"], ue_ipv4=r["ue_ipv4"]), sort_keys=True)
                              for r in selected if r["binding_status"] == "matched"})]
        record["callback_to_output_ms"] = stats([(int(r["emitted_at_us"]) - int(r["callback_at_us"])) / 1000 for r in selected])
        record["metrics"] = {}
        for name, *_ in METRICS:
            values = [r["row"]["metrics"][name] for r in selected]
            record["metrics"][name] = {"types": dict(Counter(v["type"] for v in values)),
                                       "raw_values": stats([v["value"] for v in values if v["type"] != "no_value"])}
        active = [r for r in selected if r["row"]["metrics"]["DRB.UEThpUl"]["value"] > 1000]
        record["ul_over_1mbit_samples"] = len(active)
        record["ul_over_1mbit_numeric_rf_and_prb"] = sum(all(r["row"]["metrics"][n]["type"] != "no_value"
            for n in ("PUSCH.RSRP.dBFS", "PUSCH.SNR.dB", "RRU.PrbTotDl", "RRU.PrbTotUl")) for r in active)
        result["du"][d] = record
    (ROOT / "audit.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def csv_export(rows):
    origin = min(int(r["header_time_us"]) for r in rows)
    fields = ["sequence", "du_id", "path", "header_utc", "elapsed_s", "granularity_ms", "binding_status",
              "reason", "f1ap_id", "ue_ipv4", "supi", "amf_ue_ngap_id", "ran_ue_ngap_id"]
    for name, *_ in METRICS:
        fields.extend((name, name + ".type", name + ".unit"))
    with (ROOT / "seven_metrics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in sorted(rows, key=lambda r: (int(r["header_time_us"]), r["sequence"])):
            d, binding = str(r["node"]["du_id"]), r.get("binding", {})
            item = {"sequence": r["sequence"], "du_id": d, "path": LABELS[d], "header_utc": utc(r["header_time_us"]),
                    "elapsed_s": (int(r["header_time_us"]) - origin) / 1e6,
                    "granularity_ms": r["row"]["granularity_ms"], "binding_status": r["binding_status"],
                    "reason": r["reason"], "f1ap_id": r["row"]["ue"]["gnb_cu_ue_f1ap_id"], "ue_ipv4": r["ue_ipv4"]}
            for name in ("supi", "amf_ue_ngap_id", "ran_ue_ngap_id"):
                item[name] = binding.get(name)
            for name, *_ in METRICS:
                m = r["row"]["metrics"][name]
                item.update({name: m["value"], name + ".type": m["type"], name + ".unit": m["unit"]})
            writer.writerow(item)


def plots(events, rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "savefig.dpi": 180, "svg.fonttype": "none"})
    origin = min(int(r["header_time_us"]) for r in rows)
    groups = {d: sorted((r for r in rows if str(r["node"]["du_id"]) == d), key=lambda r: int(r["header_time_us"]))
              for d in ("1", "2")}
    end = (max(int(r["header_time_us"]) for r in rows) - origin) / 1e6
    xlabel = "Elapsed collection time (s), from " + utc(origin).replace("+00:00", " UTC")
    footer = "All received samples; no smoothing. Gaps = no_value; numeric zero retained. FR1/FR3 are logical labels; both radios use n78."
    def draw(ax, definition, overview=False):
        name, title, unit, scale, _ = definition
        for d in ("1", "2"):
            series = groups[d]
            x = [(int(r["header_time_us"]) - origin) / 1e6 for r in series]
            y = [float("nan") if r["row"]["metrics"][name]["type"] == "no_value"
                 else r["row"]["metrics"][name]["value"] * scale for r in series]
            ax.plot(x, y, linewidth=.8, marker=".", markersize=1.3, color=COLORS[d], alpha=.9, label=LABELS[d])
        ax.set_title(name if overview else name + " — " + title, loc="left", fontsize=11)
        ax.set(xlim=(0, end), ylabel=unit)
        ax.grid(alpha=.2)
        ax.legend(loc="upper right", ncol=2, fontsize=8)
        if name == "RRU.PrbTotUl": ax.set_ylim(-2, 102)
        if name == "RRU.PrbTotDl": ax.set_ylim(-.3, 14)
    with PdfPages(ROOT / "seven_metrics.pdf") as pdf:
        for definition in METRICS:
            fig, ax = plt.subplots(figsize=(12, 4.1))
            draw(ax, definition)
            ax.set_xlabel(xlabel)
            fig.text(.075, .025, footer, fontsize=7.5, color="#444444")
            fig.subplots_adjust(left=.075, right=.98, top=.88, bottom=.22)
            for suffix in ("png", "svg"):
                fig.savefig(ROOT / (definition[-1] + "." + suffix))
            pdf.savefig(fig)
            plt.close(fig)
    fig, axes = plt.subplots(7, 1, figsize=(12, 17), sharex=True)
    for ax, definition in zip(axes, METRICS): draw(ax, definition, overview=True)
    axes[-1].set_xlabel(xlabel)
    fig.suptitle("Dual UE validation — DU 100 ms / CU 1 s", y=.985, fontsize=15)
    fig.text(.075, .025, footer, fontsize=8)
    fig.subplots_adjust(left=.075, right=.98, top=.96, bottom=.07, hspace=.52)
    for suffix in ("png", "svg"): fig.savefig(ROOT / ("seven_metrics_overview." + suffix))
    plt.close(fig)
    fig, axes = plt.subplots(3, 1, figsize=(12, 9))
    for d in ("1", "2"):
        q = [e for e in events if e["kind"] == "kpm_report" and str(e["node"].get("du_id")) == d]
        t0 = q[0]["received_at_mono_us"]
        axes[0].plot([(e["received_at_mono_us"] - t0) / 1e6 for e in q[1:]],
                     [(b["received_at_mono_us"] - a["received_at_mono_us"]) / 1000 for a, b in zip(q, q[1:])],
                     linewidth=.6, color=COLORS[d], alpha=.8, label=LABELS[d])
        delays = sorted((int(e["callback_at_us"]) - int(e["header_time_us"])) / 1000 for e in q)
        axes[1].plot(delays, [(i + 1) / len(delays) for i in range(len(delays))], color=COLORS[d], label=LABELS[d])
        initial = [r for r in groups[d] if int(r["header_time_us"]) - origin < 3_000_000]
        codes = {"unresolved": 0, "ambiguous": 1, "matched": 2}
        axes[2].step([(int(r["header_time_us"]) - origin) / 1e6 for r in initial],
                     [codes[r["binding_status"]] + (-.04 if d == "1" else .04) for r in initial],
                     where="post", color=COLORS[d], label=LABELS[d])
    axes[0].axhline(100, color="#444444", linestyle="--", linewidth=.8)
    axes[0].set(title="Actual receive spacing", xlabel="Elapsed receive time per DU (s)", ylabel="Interval (ms)")
    axes[1].set(title="DU header to C xApp callback (same-host timestamps)", xlabel="Timestamp span (ms)", ylabel="Cumulative fraction")
    axes[2].set(title="Startup identity association (first 3 s)", xlabel="Elapsed collection time (s)",
                yticks=[0, 1, 2], yticklabels=["unresolved", "ambiguous", "matched"])
    for ax in axes:
        ax.legend(loc="best", ncol=2, fontsize=8)
        ax.grid(alpha=.2)
    fig.tight_layout(h_pad=2.1)
    for suffix in ("png", "svg"): fig.savefig(ROOT / ("cadence_and_startup." + suffix))
    plt.close(fig)


def main():
    events, rows = read("inputs.ndjson.gz"), read("rows.ndjson.gz")
    result = audit(events, rows)
    csv_export(rows)
    with tempfile.TemporaryDirectory(prefix="falcon-100ms-mpl-", dir="/tmp") as cache:
        os.environ["MPLCONFIGDIR"] = cache
        plots(events, rows)
    manifest = {p.name: {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(ROOT.iterdir()) if p.is_file() and p.name != "artifact_manifest.json"}
    (ROOT / "artifact_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("output_rows", "statuses", "input_payloads_without_equal_output",
        "output_payloads_without_equal_input", "replay_mismatches", "independent_join_errors")}, indent=2))


if __name__ == "__main__":
    main()
