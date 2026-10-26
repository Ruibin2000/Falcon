#!/usr/bin/env python3
"""Paced archived-input -> actual xApp -> two actual dummy/TXT processes."""
import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import sys
import time

from metrics import EXPANDED
from subscription_protocol import link_key

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--source-events", type=Path, default=ROOT/"docs/evidence/2026-10-25_dual_ue_27kpm_stability/xapp/inputs.ndjson.gz")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 300:
        parser.error("offline replay span must be 5..300 seconds; this is not live stability acceptance")
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    first = None
    last = None
    selected = None
    opener = gzip.open if args.source_events.suffix == ".gz" else open
    with opener(args.source_events, "rb") as source, (out/"inputs.ndjson").open("wb") as target:
        for line in source:
            event = json.loads(line)
            now = int(event["received_at_us"])
            if first is None:
                first = now
            if now - first > args.seconds * 1_000_000:
                break
            target.write(line)
            last = now
            node = event.get("node", {})
            if selected is None and node.get("node_type") == "ngran_gNB_DU" and event.get("rows"):
                selected = dict(node={k: node[k] for k in ("mcc", "mnc", "node_type", "gnb_id", "du_id")},
                                ue=copy.deepcopy(event["rows"][0]["ue"]))
                selected["node"]["gnb_id_bits"] = 32 - node["gnb_padding"]
                selected["ue"] = {k: selected["ue"][k] for k in ("id_type", "gnb_cu_ue_f1ap_id")}
    if selected is None or last - first < (args.seconds-0.2)*1_000_000:
        raise ValueError("archived source is shorter than the requested replay span")
    (out/"settings.json").write_text('{"port":0}')
    (out/"links.json").write_text(json.dumps([selected], indent=2))
    command = [sys.executable, "-B", str(ROOT/"scripts/ue_identity/xapp_ue_identity.py"),
               "--publish-config", str(out/"settings.json"), "--duration", "0", "--replay", str(out/"inputs.ndjson"),
               "--report-evidence", str(out/"source.jsonl"), "--publisher-summary", str(out/"publisher.json")]
    (out/"publisher.command.json").write_text(json.dumps(command, indent=2))
    children = []
    resources = []
    service = None
    with (out/"publisher.stderr.txt").open("w") as err:
        try:
            service = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=err, text=True)
            if not select.select([service.stdout], [], [], 5)[0]:
                raise TimeoutError("publisher readiness deadline")
            ready = service.stdout.readline()
            (out/"publisher.stdout.txt").write_text(ready)
            if not ready.startswith("SUBSCRIPTION_READY"):
                raise RuntimeError("publisher did not start: " + ready)
            port = int(ready.split("port=")[1].split()[0])
            for app, filters in (("all", ["--all-links"]), ("exact", ["--links-file", str(out/"links.json")])):
                command = [sys.executable, "-B", str(ROOT/"scripts/ue_identity/dummy_subscriber.py"),
                    "--port", str(port), "--app-id", app, *filters, "--duration", str(args.seconds+3),
                    "--text-output", str(out/f"{app}.txt"), "--receipts-output", str(out/f"{app}.jsonl"),
                    "--summary", str(out/f"{app}.summary.json"), "--check-timing"]
                (out/f"{app}.command.json").write_text(json.dumps(command, indent=2))
                stdout = (out/f"{app}.stdout.txt").open("w")
                stderr = (out/f"{app}.stderr.txt").open("w")
                children.append((app, subprocess.Popen(command, stdout=stdout, stderr=stderr), stdout, stderr))
            deadline = time.monotonic()+args.seconds+12
            while any(child.poll() is None for _, child, _, _ in children):
                if service.poll() is not None:
                    raise RuntimeError("publisher exited during replay")
                if time.monotonic() > deadline:
                    raise TimeoutError("dummy run deadline")
                status = Path(f"/proc/{service.pid}/status").read_text()
                stat = Path(f"/proc/{service.pid}/stat").read_text().split()
                rss = next(line for line in status.splitlines() if line.startswith("VmRSS:"))
                resources.append(dict(mono_us=time.monotonic_ns()//1000, rss_kib=int(rss.split()[1]), cpu_ticks=int(stat[13])+int(stat[14])))
                time.sleep(0.5)
            for app, process, _, _ in children:
                if process.returncode:
                    raise RuntimeError(f"{app} dummy failed; see {out/app}")
            service.send_signal(signal.SIGTERM)
            if service.wait(timeout=5):
                raise RuntimeError("publisher normal shutdown failed")
            if service.stdout.read():
                raise AssertionError("routine report output leaked to publisher stdout")
        finally:
            for _, process, stdout, stderr in children:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=6)
                stdout.close()
                stderr.close()
            if service:
                if service.poll() is None:
                    service.terminate()
                    service.wait(timeout=6)
                service.stdout.close()
    traces = [json.loads(line) for line in (out/"source.jsonl").read_text().splitlines()]
    assert traces and all(t["ingress_admitted"] for t in traces)
    index = {str(t["report"]["sequence"]): t for t in traces}
    assert len(index) == len(traces)
    comparisons = {}
    for app in ("all", "exact"):
        frames = [json.loads(line) for line in (out/f"{app}.jsonl").read_text().splitlines()]
        registration = frames[0]
        assert registration["status"] == "registered" and frames[-1]["status"] == "unregistered"
        cutoff = int(registration["cutoff_at_mono_us"])
        expected = [str(t["report"]["sequence"]) for t in traces if int(t["callback_at_mono_us"]) > cutoff and
                    (app == "all" or link_key(t["report"]["node"], t["report"]["row"]["ue"]) == link_key(selected["node"], selected["ue"]))]
        reports = [r for r in frames if r["type"] == "kpm_report"]
        assert [r["report_seq"] for r in reports] == expected, f"{app}: source/receipt count, ordering or identity mismatch"
        text = (out/f"{app}.txt").read_text()
        blocks = {block.split("report_seq=")[1].split()[0]: block for block in text.split("subscription=")[1:]}
        assert len(blocks) == len(reports)
        for row in reports:
            trace = index[row["report_seq"]]
            assert row["report"] == trace["report"]
            assert row["report_ready_at_mono_us"] == trace["report_ready_at_mono_us"]
            block = blocks[row["report_seq"]]
            assert f"UE_IPv4={trace['report']['ue_ipv4']}" in block
            assert f"SUPI={trace['report']['binding']['supi']}" in block
            for name, metric in trace["report"]["row"]["metrics"].items():
                if metric["type"] == "real":
                    assert struct.pack(">d", row["report"]["row"]["metrics"][name]["value"]).hex() == trace["real_bits"][name]
                value = "no_value" if metric["type"] == "no_value" else json.dumps(metric["value"])
                assert f"{name} = {value} [{metric['unit']}] ({metric['type']})" in block
        summary = json.loads((out/f"{app}.summary.json").read_text())
        assert summary["status"] == "passed" and summary["reports_received"] == summary["text_reports_written"] == len(expected)
        for timing in summary["per_link_interval_ms"].values():
            assert timing["p99"] <= 150 and timing["max"] <= 200, timing
        comparisons[app] = dict(reports_compared=len(reports), txt_records=len(blocks), timing=summary["timing"],
                                intervals=summary["per_link_interval_ms"])
    publisher = json.loads((out/"publisher.json").read_text())
    assert publisher["status"] == "passed"
    for counter in ("ingress_dropped", "expired_reports", "serialization_errors", "client_overflows", "invalid_reports"):
        assert publisher["counters"].get(counter, 0) == 0, counter
    (out/"resources.json").write_text(json.dumps(resources, indent=2))
    summary = dict(status="passed", source="archived-input replay", span_seconds=args.seconds, nominal_du_period_ms=100,
                   profile="du27_bound_v1", source_matched_reports=len(traces), comparisons=comparisons,
                   max_reencoded_wire_frame_bytes=max(len((json.dumps({k:v for k,v in frame.items() if not k.startswith("dummy_")},separators=(',',':'))+'\n').encode()) for frame in frames),
                   rss_kib_min=min(r["rss_kib"] for r in resources), rss_kib_max=max(r["rss_kib"] for r in resources),
                   live_acceptance="pending", thirty_minute_live_stability="pending")
    (out/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    (out/"sha256.json").write_text(json.dumps({str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(out.iterdir()) if p.is_file() and p.name != "sha256.json"}, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "comparisons"}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        if "--output-dir" in sys.argv:
            target = Path(sys.argv[sys.argv.index("--output-dir")+1])
            if target.is_dir() and not (target/"summary.json").exists():
                (target/"summary.json").write_text(json.dumps(dict(status="failed", error=str(exc), live_acceptance="pending"), indent=2)+"\n")
        raise
