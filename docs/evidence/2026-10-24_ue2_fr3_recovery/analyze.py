#!/usr/bin/env python3
"""Recompute the two FR3 recovery cycles from retained, read-only evidence."""

import argparse
from bisect import bisect_left
from collections import Counter
import csv
from datetime import datetime, timedelta
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
import runpy


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def elapsed(start, end):
    return round((instant(end) - instant(start)).total_seconds(), 6)


def read_json(name):
    return json.loads((HERE / name).read_text())


def read_jsonl(name):
    return [json.loads(line) for line in (HERE / name).read_text().splitlines() if line]


def save_json(name, value):
    (HERE / name).write_text(json.dumps(value, indent=2) + "\n")


def protocol_events(name):
    records = []
    for line in (HERE / name).read_text().splitlines():
        match = re.match(r"(\d+) (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+) (.*)", line)
        if match:
            records.append(dict(source_line=int(match[1]), time_utc=match[2] + "+00:00", message=match[3]))
    return records


def first_event(records, pattern, after):
    return next(event for event in records if instant(event["time_utc"]) > instant(after)
                and re.search(pattern, event["message"]))


def console_stop_time(last_gain):
    """Timestamp the final echoed Ctrl+C using the same output timing stream."""
    data = (HERE / "spark/du2-startup.log").read_bytes().split(b"\n", 1)[1]
    offset, total, ends, times = 0, Decimal(0), [], []
    for raw in (HERE / "spark/du2-startup.log.timing").read_bytes().splitlines(keepends=True):
        if not raw.endswith(b"\n"):
            break
        kind, delay, value = raw.split(maxsplit=2)
        total += Decimal(delay.decode())
        if kind == b"O":
            offset += int(value)
            ends.append(offset)
            times.append(total)
    data = data[:offset]
    last_ack = list(re.finditer(rb"Tx gain set to 70 dB for port 0\.", data))[-1]
    stop = list(re.finditer(rb"\^C", data))[-1]
    delta = times[bisect_left(ends, stop.end())] - times[bisect_left(ends, last_ack.end())]
    return (instant(last_gain["time_utc"]) + timedelta(microseconds=int(delta * 1000000))).isoformat()


def health_checks(log):
    starts = list(re.finditer(r"^(\S+) UE2 health check started$", log, re.M))
    ending = re.compile(r"^(\S+) (?:UE2 health check OK: (\S+) via (\S+); elapsed=([0-9.]+)s|Health check failed: (.+))$", re.M)
    records = []
    for index, start in enumerate(starts):
        stop = starts[index + 1].start() if index + 1 < len(starts) else len(log)
        block = log[start.end():stop]
        end = ending.search(block)
        if not end:
            continue
        rtts = [float(value) for value in re.findall(r"rtt min/avg/max/mdev = [^/]+/([^/]+)/", block[:end.start()])]
        ok = end[2] is not None
        records.append(dict(started_at=start[1], ended_at=end[1], status="ok" if ok else "failed",
                            source=end[2], interface=end[3], elapsed_seconds=float(end[4]) if ok else None,
                            source_bound_rtt_ms=rtts[0] if len(rtts) == 2 else None,
                            ordinary_rtt_ms=rtts[1] if len(rtts) == 2 else None,
                            raw_rtt_count=len(rtts), error=end[5], log_position=start.start()))
    return records


def command_counts(text):
    return dict(pdu_connect=len(re.findall(r"^\+ .* --simple-connect", text, re.M)),
                pdu_disconnect=len(re.findall(r"^\+ .* --simple-disconnect", text, re.M)),
                explicit_registration=len(re.findall(r"^\+ .* --3gpp-register", text, re.M)))


def analyze():
    manifest, summary = read_json("source_manifest.json"), read_json("laptop/summary.json")
    attempts = read_jsonl("laptop/attempts.jsonl")
    log = gzip.decompress((HERE / "laptop/run.log.gz").read_bytes()).decode()
    validation = []

    def require(condition, description):
        if not condition:
            raise ValueError(description)
        validation.append(dict(check=description, passed=True))

    for source in manifest["sources"]:
        if source["transformation"] not in ("Exact bytes", "Deterministic gzip of exact bytes"):
            continue
        data = (HERE / source["archived_as"]).read_bytes()
        if source["transformation"].startswith("Deterministic gzip"):
            data = gzip.decompress(data)
        require(hashlib.sha256(data).hexdigest() == source["sha256"], "Source hash: " + source["archived_as"])

    gain_tool = runpy.run_path(str(REPO / "scripts/dual_fr1/extract_du_gain_times.py"))
    gains = gain_tool["gain_events"](HERE / "spark/du2-startup.log", HERE / "spark/du2-startup.log.timing")
    for gain in gains:
        gain["console_log"] = "spark/du2-startup.log"
    require([(g["direction"], g["port"], g["gain_db"]) for g in gains] ==
            [("tx", 0, 40.0), ("tx", 0, 70.0)] * 2, "Two acknowledged TX 40/70 dB cycles, no RX command")
    stop_time = console_stop_time(gains[-1])
    health = health_checks(log)
    before_stop = [row for row in health if instant(row["ended_at"]) < instant(stop_time)]
    good = [row for row in before_stop if row["status"] == "ok"]
    bad = [row for row in before_stop if row["status"] == "failed"]
    cutoff = good[-1]["ended_at"]
    included = [row for row in attempts if instant(row["ended_at"]) <= instant(cutoff)]
    excluded = [row for row in attempts if row not in included]
    successful = [row for row in included if row["status"] == "connected"]
    failures = [row for row in included if row["status"] != "connected"]
    require(len(attempts) == summary["attempts"] == 87, "Raw archive contains all 87 attempts")
    require([r["attempt"] for r in included] == list(range(1, 85)), "Analysis contains attempts 1 through 84")
    require([r["attempt"] for r in excluded] == [85, 86, 87], "Only terminal-stop attempts 85 through 87 are excluded")
    require(all(instant(row["started_at"]) > instant(stop_time) for row in excluded), "Excluded attempts start after the DU console stop")
    require([row["attempt"] for row in successful] == [1, 29, 84], "Startup and both recovery attempts passed")
    require(len(good) == 637 and len(bad) == 2, "Pre-stop monitoring contains 637 healthy rounds and two failures")
    require(all(row["raw_rtt_count"] == 2 for row in good), "Every healthy round contains both ping RTT results")
    require(len(health) - len(before_stop) == 1, "One later stop-stage health failure is excluded")
    startup = successful[0]["radio_recovery"]
    require(startup["verified_lock"] == ["2", "639648", "30", "78"] and startup["lock_action"] == "reused",
            "Startup attempt 1 verified the existing correct cell lock")
    require(startup["serial_registration"]["expected_serving_cell"], "Startup AT query reported the expected NR SA cell")

    du, cu = protocol_events("spark/du2-events.log"), protocol_events("spark/cu-events.log")
    cycles = []
    for index in range(2):
        low, restored = gains[2 * index:2 * index + 2]
        completed = successful[index + 1]
        failed = bad[index]
        prach = first_event(du, r"PRACH:", restored["time_utc"])
        rrc = first_event(cu, r"rrcSetupComplete", prach["time_utc"])
        cu_ue = int(re.search(r"\bue=(\d+)", rrc["message"])[1])
        identity = rf"\bue={cu_ue}\b.*"
        context = first_event(cu, identity + "InitialContextSetupResponse", rrc["time_utc"])
        release_request = first_event(cu, identity + "PDUSessionResourceReleaseCommand", context["time_utc"])
        release_response = first_event(cu, identity + "PDUSessionResourceReleaseResponse", release_request["time_utc"])
        pdu_request = first_event(cu, identity + "PDUSessionResourceSetupRequest", release_response["time_utc"])
        pdu_response = first_event(cu, identity + "PDUSessionResourceSetupResponse", pdu_request["time_utc"])
        rlf = first_event(du, r"RLF detected", low["time_utc"])
        removal = first_event(du, r"F1 UE context removed", rlf["time_utc"])
        failed_rows = [row for row in failures if instant(failed["ended_at"]) <= instant(row["started_at"]) < instant(completed["started_at"])]
        repairs = [row["radio_recovery"] for row in failed_rows if row.get("radio_recovery", {}).get("status") == "waiting_radio"]
        disconnecting = [row["attempt"] for row in failed_rows if row.get("registration", {}).get("state") == "disconnecting"]
        begin = log.index("Health check failed:", failed["log_position"])
        end = re.search(rf"UE2 / FR3 attempt {completed['attempt']}: SUCCESS", log[begin:]).end() + begin
        counts = command_counts(log[begin:end])
        require(len(repairs) == 1 and repairs[0]["verified_lock"] == ["2", "639648", "30", "78"],
                f"Cycle {index + 1}: correct lock reverified during radio loss")
        require(repairs[0]["pdu_preserved"] and not repairs[0]["registration_requested"],
                f"Cycle {index + 1}: radio check preserved the PDU without an explicit registration request")
        require(counts == dict(pdu_connect=1, pdu_disconnect=0, explicit_registration=0),
                f"Cycle {index + 1}: one normal PDU connect, no forced disconnect or registration")
        require(all("1 packets transmitted, 1 received" in completed[field] for field in ("source_bound_ping", "ordinary_ping")),
                f"Cycle {index + 1}: both final ping modes succeeded")
        require(instant(removal["time_utc"]) < instant(restored["time_utc"]),
                f"Cycle {index + 1}: old radio context was removed before gain restoration")
        require(instant(pdu_response["time_utc"]) < instant(completed["ended_at"]),
                f"Cycle {index + 1}: core PDU response precedes watcher verification on native UTC clocks")
        rtts = {field: float(re.search(r"rtt min/avg/max/mdev = [^/]+/([^/]+)/", completed[field])[1])
                for field in ("source_bound_ping", "ordinary_ping")}
        cycles.append(dict(cycle=index + 1, gain_low=low, gain_restored=restored, health_failure=failed,
                           spark_events=dict(rlf=rlf, old_context_removed=removal, prach=prach, rrc_setup_complete=rrc,
                                             context_response=context, old_pdu_release_command=release_request,
                                             old_pdu_release_response=release_response, pdu_setup_request=pdu_request,
                                             pdu_setup_response=pdu_response),
                           verified_at=completed["ended_at"], successful_attempt=completed["attempt"],
                           failed_attempts=[row["attempt"] for row in failed_rows],
                           failed_stages=dict(Counter(row["stage"] for row in failed_rows)),
                           disconnecting_attempts=disconnecting,
                           successful_attempt_seconds=elapsed(completed["started_at"], completed["ended_at"]),
                           same_host_seconds=dict(low_gain_hold=elapsed(low["time_utc"], restored["time_utc"]),
                                                  restored_gain_to_detected_prach=elapsed(restored["time_utc"], prach["time_utc"]),
                                                  prach_to_rrc_setup_complete=elapsed(prach["time_utc"], rrc["time_utc"]),
                                                  prach_to_cu_context_response=elapsed(prach["time_utc"], context["time_utc"]),
                                                  prach_to_new_pdu_response=elapsed(prach["time_utc"], pdu_response["time_utc"]),
                                                  new_pdu_request_to_response=elapsed(pdu_request["time_utc"], pdu_response["time_utc"]),
                                                  reported_health_failure_to_verified=elapsed(failed["ended_at"], completed["ended_at"])),
                           cross_host_seconds_approx=dict(restored_gain_to_verified=elapsed(restored["time_utc"], completed["ended_at"]),
                                                          prach_to_verified=elapsed(prach["time_utc"], completed["ended_at"])),
                           before={key: successful[index][key] for key in ("source", "prefix", "bearer")},
                           after={key: completed[key] for key in ("source", "prefix", "bearer", "interface", "mtu")},
                           final_ping_rtt_ms=rtts, radio_preparation=repairs[0], recovery_commands=counts))

    analyzed_log = log[:good[-1]["log_position"]] + log[good[-1]["log_position"]:].split("\n2026-", 1)[0]
    counts = command_counts(analyzed_log)
    require(counts == dict(pdu_connect=3, pdu_disconnect=0, explicit_registration=1),
            "Analyzed period has three connects, zero disconnects, and one startup registration request")
    known_queries = {"AT+CGSN", "AT+CIMI", 'AT+QNWLOCK="common/5g"', 'AT+QNWPREFCFG="mode_pref"',
                     'AT+QNWPREFCFG="nr5g_disable_mode"', 'AT+QNWPREFCFG="nr5g_band"', 'AT+QENG="servingcell"', 'AT+C5GREG?'}
    at_commands = re.findall(r"^AT > (.+)$", analyzed_log, re.M)
    require(set(at_commands) <= known_queries, "Only read-only AT commands were recorded in the analyzed period")
    require([row["source"] for row in successful] == ["10.46.0.44", "10.46.0.45", "10.46.0.46"],
            "Each recovery verified the newly assigned UE IPv4 address")
    post = [row for row in good if instant(row["started_at"]) > instant(successful[-1]["ended_at"])]
    require(len(post) == 576, "576 healthy rounds followed the second recovery before operator shutdown")
    durations = [elapsed(row["started_at"], row["ended_at"]) for row in failures]
    result = dict(experiment_date="2026-10-24", author="Ruibin", run=manifest["run"], result="two_completed_recovery_cycles_passed",
                  clock_policy=read_json("clock-context.json")["analysis_policy"],
                  analysis_window=dict(started_at=summary["started_at"], ended_at=cutoff,
                                       duration_seconds=elapsed(summary["started_at"], cutoff),
                                       operator_du_stop_observed_utc=stop_time,
                                       excluded_attempts=[row["attempt"] for row in excluded],
                                       excluded_terminal_health_failures=1, shutdown_evaluation_excluded=True),
                  settings={key: summary[key] for key in ("interval_seconds", "verbose", "auto_cell_lock", "cell_lock_cooldown",
                                                          "registration_grace", "registration_request_timeout", "pdu_disconnect_timeout")},
                  startup=dict(attempt=1, status=successful[0]["status"], duration_seconds=elapsed(successful[0]["started_at"], successful[0]["ended_at"]),
                               verified_at=successful[0]["ended_at"], verified_lock=startup["verified_lock"], lock_action=startup["lock_action"]),
                  attempts=dict(raw_count=len(attempts), analyzed_count=len(included), successes=[row["attempt"] for row in successful],
                                retry_count=len(failures), failed_stages=dict(Counter(row["stage"] for row in failures)),
                                failed_duration_seconds_min=min(durations), failed_duration_seconds_max=max(durations)),
                  healthy_checks=dict(count=len(good), per_ip=dict(Counter(row["source"] for row in good)),
                                      first_completed_at=good[0]["ended_at"], last_completed_at=cutoff,
                                      after_second_recovery_count=len(post),
                                      second_recovery_to_last_healthy_seconds=elapsed(successful[-1]["ended_at"], cutoff)),
                  analyzed_commands=counts, gain_events=gains, cycles=cycles, validation=validation)
    save_json("analysis.json", result)
    (HERE / "gain-events.jsonl").write_text("".join(json.dumps(row) + "\n" for row in gains))
    with (HERE / "attempts.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["attempt", "included", "started_at_utc", "ended_at_utc", "elapsed_seconds", "status", "stage", "modem_state", "registration", "radio_action", "source"])
        for row in attempts:
            writer.writerow([row["attempt"], row in included, row["started_at"], row["ended_at"], elapsed(row["started_at"], row["ended_at"]),
                             row["status"], row.get("stage", "passed"), row.get("registration", {}).get("state", ""),
                             row.get("registration", {}).get("registration_state", ""), row.get("radio_recovery", {}).get("status", ""), row.get("source", "")])
    with (HERE / "health_checks.csv").open("w", newline="") as stream:
        fields = ["started_at", "ended_at", "status", "source", "interface", "source_bound_rtt_ms", "ordinary_rtt_ms"]
        writer = csv.DictWriter(stream, ["included"] + fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(dict(included=instant(row["ended_at"]) <= instant(cutoff), **{k: row[k] for k in fields}) for row in health)
    return result, before_stop


def plots(result, health):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as dates
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "svg.hashsalt": "falcon-fr3-x8_2w4ru"})
    fig, axes = plt.subplots(3, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [1, 1.25, 1]})
    begin = instant(result["analysis_window"]["started_at"])
    end = instant(result["cycles"][-1]["verified_at"]) + timedelta(seconds=10)
    x = [begin] + [instant(g["time_utc"]) for g in result["gain_events"]] + [end]
    axes[0].step(x, [70, 40, 70, 40, 70, 70], where="post", color="#4477aa", linewidth=2)
    axes[0].set(ylim=(30, 80), yticks=[40, 70], ylabel="TX gain (dB)")
    good = [row for row in health if row["status"] == "ok" and instant(row["ended_at"]) <= end]
    for field, label, color in [("source_bound_rtt_ms", "Source-bound ping", "#228833"), ("ordinary_rtt_ms", "Ordinary ping", "#aa3377")]:
        axes[1].scatter([instant(row["ended_at"]) for row in good], [row[field] for row in good], s=10, color=color, label=label)
    axes[1].set_ylabel("Ping RTT (ms)")
    axes[1].legend(loc="upper right", fontsize=8)
    successes = [result["startup"]] + result["cycles"]
    axes[2].step([instant(s["verified_at"]) for s in successes] + [end], [44, 45, 46, 46], where="post", color="#222222", linewidth=2)
    axes[2].set(yticks=[44, 45, 46], yticklabels=["10.46.0.44", "10.46.0.45", "10.46.0.46"], ylabel="Verified UE IP", ylim=(43.5, 46.5))
    for index, cycle in enumerate(result["cycles"], 1):
        for axis in axes:
            axis.axvspan(instant(cycle["health_failure"]["ended_at"]), instant(cycle["verified_at"]), color="#ddaa33", alpha=0.17)
            axis.axvline(instant(cycle["spark_events"]["prach"]["time_utc"]), color="#777777", linestyle=":", linewidth=1)
        axes[0].text(instant(cycle["gain_low"]["time_utc"]), 77, f"Cycle {index}", fontsize=9)
    for axis in axes:
        axis.grid(axis="y", alpha=0.2)
        for edge in ("top", "right"):
            axis.spines[edge].set_visible(False)
    axes[-1].xaxis.set_major_formatter(dates.DateFormatter("%H:%M:%S", tz=begin.tzinfo))
    axes[-1].set_xlabel("2026-10-24 UTC; native host clocks after NTP synchronization")
    axes[-1].set_xlim(begin, end)
    fig.suptitle("UE2 / FR3: two automatic recoveries with new IP allocations", x=0.01, ha="left", fontsize=13)
    fig.text(0.01, 0.01, "Shading: failed health report to verified recovery. Dotted lines: DU-detected PRACH.\n"
             "RTT dots use health-check completion times. IP steps show verified allocations; they do not imply reachability during shaded intervals.", fontsize=8)
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    for suffix in ("png", "svg"):
        fig.savefig(HERE / f"recovery_timeline.{suffix}", dpi=180, metadata={"Date": None} if suffix == "svg" else None)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(10, 4.5))
    for index, cycle in enumerate(result["cycles"]):
        wait = cycle["same_host_seconds"]["restored_gain_to_detected_prach"]
        core = cycle["same_host_seconds"]["prach_to_new_pdu_response"]
        total = cycle["cross_host_seconds_approx"]["restored_gain_to_verified"]
        axis.barh(index, wait, height=0.45, color="#4477aa", label="Before detected PRACH" if index == 0 else None)
        axis.barh(index, core, left=wait, height=0.45, color="#228833", label="PRACH to new PDU response" if index == 0 else None)
        axis.barh(index, total-wait-core, left=wait+core, height=0.45, color="#aa3377", hatch="///", label="To script verification (approx.)" if index == 0 else None)
        axis.text(wait/2, index, f"{wait:.3f} s", ha="center", va="center", color="white", fontweight="bold")
        axis.text(total+0.3, index, f"≈ {total:.3f} s", va="center", fontweight="bold")
    axis.set(yticks=[0, 1], yticklabels=["Cycle 1", "Cycle 2"], xlabel="Seconds since TX gain restored to 70 dB", xlim=(0, 29))
    axis.invert_yaxis()
    axis.set_title("FR3 recovery latency after TX gain restoration", loc="left", pad=14)
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=1, frameon=False, fontsize=8)
    axis.xaxis.grid(True, alpha=0.2)
    axis.set_axisbelow(True)
    for edge in ("top", "right", "left"):
        axis.spines[edge].set_visible(False)
    fig.text(0.01, 0.01, "Blue and green intervals use Spark only. The hatched tail and total use both NTP-synchronized host clocks; residual offset was not calibrated per trial.", fontsize=7.5)
    fig.tight_layout(rect=(0, 0.10, 1, 1))
    for suffix in ("png", "svg"):
        fig.savefig(HERE / f"recovery_latencies.{suffix}", dpi=180, metadata={"Date": None} if suffix == "svg" else None)
    plt.close(fig)


def checksums():
    paths = sorted(path for path in HERE.rglob("*") if path.is_file() and path.name != "sha256sums.txt" and "__pycache__" not in path.parts)
    (HERE / "sha256sums.txt").write_text("".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + str(path.relative_to(HERE)) + "\n" for path in paths))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plot", action="store_true", help="Regenerate PNG/SVG figures with matplotlib")
    arguments = parser.parse_args()
    result, health = analyze()
    if arguments.plot:
        plots(result, health)
    checksums()
    print(f"PASS: {len(result['validation'])} data checks; {result['attempts']['analyzed_count']} analyzed attempts; two completed recovery cycles")
    for cycle in result["cycles"]:
        print(json.dumps(dict(cycle=cycle["cycle"], same_host_seconds=cycle["same_host_seconds"], cross_host_seconds_approx=cycle["cross_host_seconds_approx"]), indent=2))
