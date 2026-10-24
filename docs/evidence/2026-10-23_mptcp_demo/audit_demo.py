#!/usr/bin/env python3
"""Audit retained demo telemetry without contacting the testbed."""

from datetime import datetime
import gzip
import json
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
NY = ZoneInfo("America/New_York")
EXPECTED = {0: ("10.45.0.1", "10.45.0.3"), 1: ("10.46.0.1", "10.46.0.4")}


def stamp(microseconds):
    return datetime.fromtimestamp(microseconds / 1_000_000, NY).isoformat()


def audit():
    with gzip.open(ROOT / "metrics-19-32-to-19-34.jsonl.gz", "rt") as file:
        records = [json.loads(line) for line in file]
    metrics = [row for row in records if row.get("record") == "metrics"]
    assert records[0]["backend"] == "mptcp"
    sessions = {row["session"] for row in metrics}
    assert len(sessions) == 1
    session = sessions.pop()
    both_established = 0
    previous = {}
    growth = {}
    for row in metrics:
        established = {}
        for flow in (row.get("mptcp") or {}).get("subflow_stats", []):
            path = flow.get("path_id")
            if path not in EXPECTED or flow.get("tcp_state") != 1:
                continue
            assert (flow["local"], flow["remote"]) == EXPECTED[path]
            established[path] = flow
            prior = previous.get(path)
            if prior is not None:
                old_time, old = prior
                delta = flow["bytes_recv"] - old["bytes_recv"]
                if delta > growth.get(path, {}).get("delta_bytes", 0):
                    growth[path] = {
                        "from": stamp(old_time), "to": stamp(row["ts_us"]),
                        "bytes_recv_before": old["bytes_recv"],
                        "bytes_recv_after": flow["bytes_recv"],
                        "delta_bytes": delta,
                    }
            previous[path] = (row["ts_us"], flow)
        both_established += set(established) == set(EXPECTED)
    assert both_established > 0 and set(growth) == set(EXPECTED)

    events = [json.loads(line) for line in (ROOT / "server-events.jsonl").read_text().splitlines()]
    cycle = []
    for event in events:
        if event.get("session") != session or event.get("link") != "link-2":
            continue
        when = stamp(event["ts_us"])
        if "T19:33:" in when:
            cycle.append({"at": when, "event": event["event"], "detail": event["detail"]})
    assert [entry["event"] for entry in cycle] == ["path_degraded", "path_down", "path_up"]

    players = [json.loads(line) for line in (ROOT / "player-demo.jsonl").read_text().splitlines()]
    matches = []
    for row in players:
        report = row.get("report", {})
        if (report.get("state") == "playing" and report.get("rendition", {}).get("height") == 720
                and report["rendition"].get("kbps") == 5000
                and round(report.get("buffer_s") or 0, 1) == 8.9
                and round((report.get("throughput_kbps") or 0) / 1000) == 15
                and int(report.get("position_s") or 0) == 727
                and report.get("stalls") == 1 and round(report.get("stall_s") or 0, 1) == 9.8
                and report.get("loops") == 4):
            matches.append({"received_at": stamp(row["rx_unix_ms"] * 1000), "record": row})
    assert len(matches) == 1, "Expected one report matching the screenshot's visible player fields"

    du2 = (ROOT / "du2-console.log").read_text()
    assert "Available commands:" in du2
    for gain in (5, 20, 15):
        assert f"Rx gain set to {gain} dB for port 0." in du2
    for role in (1, 2):
        console = (ROOT / f"du{role}-console.log").read_text()
        assert 'COMMAND="exec sudo stdbuf' in console
        assert 'COMMAND_EXIT_CODE="0"' in console

    return {
        "status": "Passed", "timezone": "America/New_York", "backend": "mptcp",
        "session": session, "retained_metrics_records": len(metrics),
        "first_metrics_at": stamp(metrics[0]["ts_us"]),
        "last_metrics_at": stamp(metrics[-1]["ts_us"]),
        "records_with_both_expected_established_subflows": both_established,
        "expected_server_to_ue_address_pairs": EXPECTED,
        "positive_receive_counter_examples": growth,
        "link_2_cycle": cycle,
        "player_report_matching_visible_screenshot_fields": matches[0],
        "du2_rx_gain_acknowledgments_dB": [5, 20, 15],
        "limits": [
            "Primary/backup operation; this does not establish simultaneous bandwidth aggregation",
            "Counter examples are individual intervals, not end-to-end throughput or failover latency",
            "Screenshot filename time differs from the matched player report; no cause is assigned",
            "DU gain commands lack timestamps; causal alignment with path events is not established",
            "DU1 startup/logging/exit are retained; a live DU1 help or gain acknowledgment is not recorded",
            "The new laptop reset blocks, cold boot and RIC broker integration are not validated here",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2) + "\n", end="")
