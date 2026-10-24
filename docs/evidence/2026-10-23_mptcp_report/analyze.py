#!/usr/bin/env python3
"""Reproduce the screenshot session's tables and figures from archived records."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import gzip
import ipaddress
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
NY = ZoneInfo("America/New_York")
SERVERS = {0: "10.45.0.1", 1: "10.46.0.1"}
LABELS = {0: "FR1", 1: "FR3"}
POOLS = {i: ipaddress.ip_network(ip + "/16", strict=False) for i, ip in SERVERS.items()}


def timestamp(seconds):
    return datetime.fromtimestamp(seconds, NY).isoformat(timespec="microseconds")


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def describe(values):
    values = [v for v in values if v is not None]
    return {"n": len(values), "min": min(values) if values else None,
            "median": quantile(values, .5), "p95": quantile(values, .95),
            "max": max(values) if values else None}


def allocate(start, end, value):
    """Allocate an interval's bytes uniformly to overlapping wall-clock seconds."""
    assert end > start
    for second in range(math.floor(start), math.ceil(end)):
        overlap = max(0, min(end, second + 1) - max(start, second))
        if overlap:
            yield second, overlap, None if value is None else value * overlap / (end - start)


def counter_delta(previous, current):
    """Ports were not serialized: censor first, changed, ambiguous or reset flows."""
    if previous is None or current is None:
        return None, "missing_or_ambiguous"
    if (previous["local"], previous["remote"]) != (current["local"], current["remote"]):
        return None, "address_change"
    delta = current["bytes_recv"] - previous["bytes_recv"]
    return (delta, "observed") if delta >= 0 else (None, "counter_reset")


def read_jsonl(name):
    path = ROOT / name
    opener = gzip.open if name.endswith(".gz") else open
    with opener(path, "rt") as file:
        return [json.loads(line) for line in file]


def write_csv(name, rows):
    assert rows
    with (ROOT / name).open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def analyze():
    records = read_jsonl("session-metrics.jsonl.gz")
    assert records[0]["backend"] == "mptcp"
    raw = [r for r in records if r.get("record") == "metrics"]
    events = read_jsonl("session-events.jsonl")
    players = read_jsonl("session-player.jsonl.gz")
    session_start = next(e["ts_us"] / 1e6 for e in events if e["event"] == "session_established")
    session_end = next(e["ts_us"] / 1e6 for e in events if e["event"] == "session_closed")
    metrics = [r for r in raw if session_start <= r["ts_us"] / 1e6 <= session_end]
    assert len({r["session"] for r in raw}) == 1
    active_events = [e for e in events if session_start <= e["ts_us"] / 1e6 <= session_end]
    output = []
    previous_flows = {i: None for i in SERVERS}
    reasons = {i: Counter() for i in SERVERS}
    addresses = {i: set() for i in SERVERS}
    bins = defaultdict(lambda: defaultdict(float))
    previous_row = None
    unmapped_established = 0
    for row in metrics:
        t = row["ts_us"] / 1e6
        flow_candidates = {i: [] for i in SERVERS}
        for flow in (row.get("mptcp") or {}).get("subflow_stats", []):
            if flow.get("tcp_state") != 1:
                continue
            path = flow.get("path_id")
            if path not in SERVERS or flow.get("local") != SERVERS[path]:
                unmapped_established += 1
                continue
            assert ipaddress.ip_address(flow["remote"]) in POOLS[path]
            addresses[path].add(flow["remote"])
            flow_candidates[path].append(flow)
        flows = {i: fs[0] if len(fs) == 1 else None for i, fs in flow_candidates.items()}
        entry = {"timestamp": timestamp(t), "ts_us": row["ts_us"],
                 "elapsed_s": t - session_start, "payload_bytes": row["data_delivered_bytes"],
                 "mpx_dropped_bytes": row["data_dropped_bytes"],
                 "established_subflows": (row.get("mptcp") or {}).get("subflows"),
                 "mpx_payload_delta_bytes": None, "mpx_payload_mbps": None}
        paths = {p["id"]: p for p in row["paths"]}
        for i in SERVERS:
            flow = flows[i]
            delta, reason = counter_delta(previous_flows[i], flow)
            if previous_row is None:
                reason = "initial_snapshot"
            reasons[i][reason] += 1
            entry.update({f"path{i+1}_state": paths[i]["state"],
                          f"path{i+1}_remote": paths[i].get("remote", ""),
                          f"path{i+1}_tcp_rx_bytes": flow["bytes_recv"] if flow else None,
                          f"path{i+1}_tcp_rx_delta_bytes": delta,
                          f"path{i+1}_delta_status": reason,
                          f"path{i+1}_tcp_srtt_ms": flow["srtt_us"] / 1000 if flow and paths[i]["state"] == "up" and flow["srtt_us"] > 0 else None,
                          f"path{i+1}_heartbeat_srtt_ms": paths[i]["srtt_us"] / 1000 if paths[i]["state"] == "up" and paths[i]["srtt_us"] > 0 else None,
                          f"path{i+1}_tcp_total_retrans_snapshot": flow.get("retrans") if flow else None})
        if previous_row is not None:
            old_t = previous_row["ts_us"] / 1e6
            dt = t - old_t
            assert dt > 0
            payload_delta = row["data_delivered_bytes"] - previous_row["data_delivered_bytes"]
            assert payload_delta >= 0, "The session payload counter must not reset"
            entry["mpx_payload_delta_bytes"] = payload_delta
            entry["mpx_payload_mbps"] = payload_delta * 8 / dt / 1e6
            for second, overlap, amount in allocate(old_t, t, payload_delta):
                bins[second]["coverage_s"] += overlap
                bins[second]["payload_bytes"] += amount
            for i in SERVERS:
                for second, overlap, amount in allocate(old_t, t, entry[f"path{i+1}_tcp_rx_delta_bytes"]):
                    if amount is not None:
                        bins[second][f"path{i+1}_known_s"] += overlap
                        bins[second][f"path{i+1}_tcp_rx_bytes"] += amount
        output.append(entry)
        previous_flows, previous_row = flows, row
    seconds = []
    for second, values in sorted(bins.items()):
        entry = {"timestamp": timestamp(second), "epoch_s": second,
                 "coverage_s": values["coverage_s"], "mpx_payload_bytes": values["payload_bytes"],
                 "mpx_payload_mbps": values["payload_bytes"] * 8 / values["coverage_s"] / 1e6}
        for i in SERVERS:
            known = values[f"path{i+1}_known_s"]
            complete = abs(known - values["coverage_s"]) < 1e-6
            entry[f"path{i+1}_known_fraction"] = known / values["coverage_s"]
            entry[f"path{i+1}_observed_tcp_rx_bytes"] = values[f"path{i+1}_tcp_rx_bytes"]
            entry[f"path{i+1}_tcp_rx_mbps"] = values[f"path{i+1}_tcp_rx_bytes"] * 8 / values["coverage_s"] / 1e6 if complete else None
        seconds.append(entry)
    payload = metrics[-1]["data_delivered_bytes"] - metrics[0]["data_delivered_bytes"]
    assert math.isclose(sum(r["mpx_payload_bytes"] for r in seconds), payload, rel_tol=1e-9)

    cycles = []
    state_seconds = {}
    for i in SERVERS:
        changes = [e for e in active_events if e.get("link") == f"link-{i+1}" and e["event"] in ("path_up", "path_down", "path_degraded")]
        state = "probing"
        since = session_start
        totals = Counter()
        degraded = down = None
        for event in changes:
            t = event["ts_us"] / 1e6
            totals[state] += t - since
            since = t
            if event["event"] == "path_degraded":
                degraded = t
            elif event["event"] == "path_down":
                down = t
            else:
                if down is not None:
                    cycles.append({"path": i + 1, "degraded_at": timestamp(degraded) if degraded is not None else None,
                                   "down_at": timestamp(down), "up_at": timestamp(t),
                                   "down_s": t - down, "degraded_to_up_s": t - degraded if degraded is not None else None})
                degraded = down = None
            state = event["event"].removeprefix("path_")
        totals[state] += session_end - since
        assert math.isclose(sum(totals.values()), session_end - session_start, abs_tol=1e-6)
        state_seconds[f"path{i+1}"] = dict(totals)

    for cycle in cycles:
        # Use only sampled endpoints strictly inside the DOWN interval. This
        # avoids claiming byte precision at an unsampled event boundary.
        interior = [r for r in output if cycle["down_at"] <= r["timestamp"] < cycle["up_at"]]
        assert len(interior) >= 2
        first, last = interior[0], interior[-1]
        span = (last["ts_us"] - first["ts_us"]) / 1e6
        amount = last["payload_bytes"] - first["payload_bytes"]
        cycle.update({"interior_first_sample": first["timestamp"], "interior_last_sample": last["timestamp"],
                      "interior_span_s": span, "interior_mpx_payload_bytes": amount,
                      "interior_mean_mpx_payload_mbps": amount * 8 / span / 1e6})
        for i in SERVERS:
            cycle[f"interior_path{i+1}_observed_tcp_rx_bytes"] = sum(r[f"path{i+1}_tcp_rx_delta_bytes"] or 0 for r in interior[1:])

    player_events = []
    player_rows = []
    quality_seconds = Counter()
    for index, row in enumerate(players):
        report = row["report"]
        rendition = report.get("rendition") or {}
        player_rows.append({"timestamp": timestamp(row["rx_unix_ms"] / 1000), "epoch_s": row["rx_unix_ms"] / 1000,
                            "state": report["state"], "height": rendition.get("height"),
                            "nominal_mbps": rendition.get("kbps", 0) / 1000,
                            "buffer_s": report.get("buffer_s"),
                            "download_estimate_mbps": (report.get("throughput_kbps") or 0) / 1000,
                            "position_s": report.get("position_s"), "stalls": report.get("stalls"),
                            "stall_s": report.get("stall_s"), "stalled_now": report.get("stalled_now"),
                            "switches": report.get("switches"), "dropped_frames": report.get("dropped_frames"),
                            "total_frames": report.get("total_frames")})
        if index + 1 < len(players):
            quality_seconds[rendition.get("height", 0)] += (players[index+1]["rx_unix_ms"] - row["rx_unix_ms"]) / 1000
        for event in report.get("events", []):
            player_events.append({"timestamp": timestamp(event["ts_ms"] / 1000), "epoch_s": event["ts_ms"] / 1000,
                                  "type": event["type"], "detail_json": json.dumps(event, sort_keys=True)})
    stalls = []
    stall_start = None
    for event in player_events:
        if event["type"] == "stall_start":
            stall_start = event["epoch_s"]
        elif event["type"] == "stall_end":
            detail = json.loads(event["detail_json"])
            assert stall_start is not None
            stalls.append({"start": timestamp(stall_start), "end": event["timestamp"],
                           "duration_s": detail["duration_ms"] / 1000})
            assert abs(event["epoch_s"] - stall_start - stalls[-1]["duration_s"]) < .002
            stall_start = None
    assert stall_start is None
    final = players[-1]["report"]
    player_span = (players[-1]["rx_unix_ms"] - players[0]["rx_unix_ms"]) / 1000
    gap = [((b["ts_us"] - a["ts_us"]) / 1e6) for a, b in zip(metrics, metrics[1:])]
    focus = [r for r in output if "2026-10-23T19:32:00" <= r["timestamp"] < "2026-10-23T19:34:00"]
    focus_span = (focus[-1]["ts_us"] - focus[0]["ts_us"]) / 1e6
    focus_payload = focus[-1]["payload_bytes"] - focus[0]["payload_bytes"]
    result = {
        "session": metrics[0]["session"], "timezone": "America/New_York",
        "display_labels": {f"path{i+1}": LABELS[i] for i in SERVERS},
        "session_established": timestamp(session_start), "client_deregistered": timestamp(session_end),
        "session_duration_s": session_end - session_start,
        "raw_metrics_records": len(raw), "active_metrics_records": len(metrics),
        "excluded_post_deregistration_metrics": len(raw) - len(metrics),
        "metrics_first": output[0]["timestamp"], "metrics_last": output[-1]["timestamp"],
        "metrics_span_s": (metrics[-1]["ts_us"] - metrics[0]["ts_us"]) / 1e6,
        "sampling_interval_s": describe(gap), "delivered_application_channel_bytes": payload,
        "mean_mpx_payload_mbps": payload * 8 / ((metrics[-1]["ts_us"] - metrics[0]["ts_us"]) / 1e6) / 1e6,
        "mpx_dropped_bytes_final": metrics[-1]["data_dropped_bytes"],
        "one_second_payload_mbps": describe([r["mpx_payload_mbps"] for r in seconds]),
        "path_state_seconds": state_seconds,
        "path_event_counts": {f"path{i+1}": dict(Counter(e["event"] for e in active_events if e.get("link") == f"link-{i+1}")) for i in SERVERS},
        "path_down_cycles": cycles,
        "paths": {f"path{i+1}": {
            "server": SERVERS[i], "ue_addresses_observed": sorted(addresses[i]),
            "counter_interval_status_counts": dict(reasons[i]),
            "observed_nonnegative_tcp_rx_increments_bytes": sum(r[f"path{i+1}_tcp_rx_delta_bytes"] or 0 for r in output[1:]),
            "tcp_srtt_ms_while_control_up": describe([r[f"path{i+1}_tcp_srtt_ms"] for r in output]),
            "heartbeat_srtt_ms_while_up": describe([r[f"path{i+1}_heartbeat_srtt_ms"] for r in output]),
            "one_second_tcp_rx_mbps_complete_bins": describe([r[f"path{i+1}_tcp_rx_mbps"] for r in seconds]),
        } for i in SERVERS},
        "unmapped_established_flow_snapshots": unmapped_established,
        "screenshot_two_minute_window": {"samples": len(focus), "first": focus[0]["timestamp"],
                                         "last": focus[-1]["timestamp"], "span_s": focus_span,
                                         "delivered_application_channel_bytes": focus_payload,
                                         "mean_mpx_payload_mbps": focus_payload * 8 / focus_span / 1e6},
        "player": {"reports": len(players), "first": player_rows[0]["timestamp"], "last": player_rows[-1]["timestamp"],
                   "observed_receipt_span_s": player_span, "reported_startup_ms": final["startup_ms"],
                   "stalls": stalls, "reported_stalls_final": final["stalls"], "reported_stall_s_final": final["stall_s"],
                   "event_stall_fraction_of_observed_span_pct": sum(s["duration_s"] for s in stalls) / player_span * 100,
                   "buffer_s": describe([r["buffer_s"] for r in player_rows]),
                   "download_estimate_mbps": describe([r["download_estimate_mbps"] for r in player_rows]),
                   "nominal_rendition_seconds_left_hold": dict(quality_seconds),
                   "final_report": final, "event_counts": dict(Counter(e["type"] for e in player_events))},
        "method_limits": [
            "MPX payload counts application-channel bytes, including the TCP forwarder protocol; it is not pure encoded-video bytes",
            "Raw subflow records omit ports. Path receive increments censor first/missing/ambiguous/address-change/reset intervals; they cannot exactly reproduce the dashboard's 4-tuple rate calculation",
            "RTT distributions are samples of smoothed RTT while the control path is up, not packet RTT percentiles or one-way latency",
            "State-down intervals are heartbeat classifications, not measured physical outages or failure-detection/failover latency",
            "No packet capture, deployed UE config or UE event log was retained. No fault cause or precise failure trigger time is assigned",
            "Nominal rendition durations use each player report until the next receipt; they are not frame-level encoded bitrate statistics",
        ],
    }
    write_csv("transport_samples.csv", output)
    write_csv("throughput_1s.csv", seconds)
    write_csv("transport_events.csv", [{"timestamp": timestamp(e["ts_us"] / 1e6), "event": e["event"], "link": e.get("link", ""), "detail": e.get("detail", "")} for e in active_events])
    write_csv("path_down_cycles.csv", cycles)
    write_csv("player_samples.csv", player_rows)
    write_csv("player_events.csv", player_events)
    (ROOT / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result, output, seconds, player_rows, active_events


def plots(result, output, seconds, players, events):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/falcon-mptcp-report-mpl")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.ticker import ScalarFormatter

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "svg.fonttype": "none"})
    colors = ("#1976c9", "#e77928")
    convert = lambda value: datetime.fromtimestamp(value, NY)
    tx = [convert(r["epoch_s"] + .5) for r in seconds]
    mx = [convert(r["ts_us"] / 1e6) for r in output]
    px = [convert(r["epoch_s"]) for r in players]
    shot = datetime.fromisoformat("2026-10-23T19:33:42.744-04:00")
    for name, start, end in [
        ("session_overview", datetime.fromisoformat(result["metrics_first"]), datetime.fromisoformat(result["metrics_last"])),
        ("screenshot_window", datetime.fromisoformat("2026-10-23T19:31:45-04:00"), datetime.fromisoformat("2026-10-23T19:34:00-04:00")),
    ]:
        fig, axes = plt.subplots(4, 1, figsize=(13, 11), sharex=True, gridspec_kw={"height_ratios": [1.7, .8, 1.25, 1.4]}, layout="constrained")
        fig.suptitle("FR1 / FR3 MPTCP DASH experiment · " + ("complete session" if name == "session_overview" else "screenshot interval"), fontsize=16, fontweight="bold")
        axes[0].plot(tx, [r["mpx_payload_mbps"] for r in seconds], color="#596269", ls="--", lw=1.1, label="MPX delivered payload (1 s)")
        for i, color in enumerate(colors):
            role = "backup" if i == 0 else "primary"
            axes[0].plot(tx, [r[f"path{i+1}_tcp_rx_mbps"] for r in seconds], color=color, lw=1, label=f"{LABELS[i]} ({role}): TCP receive rate")
        axes[0].set_ylabel("Mbit/s")
        axes[0].legend(loc="upper left", ncol=3, fontsize=8)
        axes[0].set_title("Receiver counters; gaps in path curves mark censored intervals", loc="left", fontsize=10)
        states = {"probing": -1, "down": 0, "degraded": 1, "up": 2}
        for i, color in enumerate(colors):
            axes[1].step(mx, [states[r[f"path{i+1}_state"]] + .06 * i for r in output], where="post", color=color, lw=1.2, label=LABELS[i])
            axes[2].plot(mx, [r[f"path{i+1}_tcp_srtt_ms"] for r in output], color=color, lw=.8, label=f"{LABELS[i]} TCP SRTT")
        axes[1].set_yticks([-1, 0, 1, 2], ["probing", "down", "degraded", "up"])
        axes[1].set_ylim(-1.3, 2.5)
        axes[1].set_ylabel("Heartbeat state")
        axes[2].set_ylabel("TCP SRTT (ms, log)")
        axes[2].set_yscale("log")
        axes[2].set_yticks([20, 50, 100, 200, 500, 1000, 3000])
        axes[2].yaxis.set_major_formatter(ScalarFormatter())
        axes[2].legend(loc="upper right", fontsize=8)
        axes[2].set_title("Smoothed TCP RTT, shown only while the control path is up", loc="left", fontsize=10)
        axes[3].plot(px, [r["buffer_s"] for r in players], color="#24865b", lw=1.2, label="Playback buffer")
        axes[3].set_ylabel("Buffer (s)", color="#24865b")
        quality = axes[3].twinx()
        quality.step(px, [r["nominal_mbps"] for r in players], where="post", color="#8852b4", lw=1, alpha=.85, label="Nominal rendition")
        quality.set_ylabel("Rendition (Mbit/s)", color="#8852b4")
        quality.set_ylim(0, 9)
        axes[3].set_title("Player reports; gray band = the recorded 9.819 s rebuffer", loc="left", fontsize=10)
        for ax in axes:
            for cycle in result["path_down_cycles"]:
                ax.axvspan(datetime.fromisoformat(cycle["down_at"]), datetime.fromisoformat(cycle["up_at"]), color=colors[1], alpha=.06, zorder=-2)
            for stall in result["player"]["stalls"]:
                ax.axvspan(datetime.fromisoformat(stall["start"]), datetime.fromisoformat(stall["end"]), color="#64717c", alpha=.23, zorder=-1)
            ax.axvline(shot, color="#41464c", ls=":", lw=1)
            ax.grid(axis="y", color="#e1e5e8", lw=.6)
            ax.set_xlim(start, end)
        axes[0].set_ylim(bottom=0)
        axes[2].set_ylim(10, 4000)
        axes[3].set_ylim(bottom=0)
        axes[3].xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=9))
        axes[3].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S", tz=NY))
        axes[3].set_xlabel("2026-10-23 · America/New_York (EDT); dotted line = player report matching the screenshot")
        for extension in ("png", "svg"):
            fig.savefig(ROOT / f"{name}.{extension}", dpi=180, facecolor="white")
        plt.close(fig)


def self_test():
    assert quantile([0, 10], .95) == 9.5
    assert quantile([], .5) is None
    amounts = list(allocate(10.25, 12.5, 900))
    assert [round(a[1], 2) for a in amounts] == [.75, 1., .5]
    assert math.isclose(sum(a[2] for a in amounts), 900)
    assert all(a[2] is None for a in allocate(0, 2, None))
    first = {"local": "10.45.0.1", "remote": "10.45.0.3", "bytes_recv": 100}
    assert counter_delta(first, dict(first, bytes_recv=150)) == (50, "observed")
    assert counter_delta(first, dict(first, bytes_recv=10)) == (None, "counter_reset")
    assert counter_delta(first, dict(first, remote="10.45.0.4")) == (None, "address_change")
    assert counter_delta(None, first) == (None, "missing_or_ambiguous")
    print("PASS: percentile interpolation, byte-conserving binning, missing data, reset and address-change handling")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        analysis = analyze()
        plots(*analysis)
        print(json.dumps(analysis[0], indent=2))
