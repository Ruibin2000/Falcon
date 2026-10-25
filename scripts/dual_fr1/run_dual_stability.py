#!/usr/bin/env python3
"""Run six alternating/concurrent UL phases while both reconnect watchers run."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

import run_dual_ul as ul


PHASES = (("fr1", (1,)), ("fr3", (2,)), ("both", (1, 2))) * 2
PHASE_SECONDS = 50
RUN_BUDGET = 335
QUERY_TIMEOUT = 5


def stamp():
    return datetime.now(timezone.utc).isoformat()


def snapshot(deadline=None):
    """Reuse identity/route checks with bounded, read-only subprocess calls."""
    original = ul.read

    def read(*command):
        remaining = QUERY_TIMEOUT if deadline is None else min(QUERY_TIMEOUT, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("Traffic run exceeded its 335-second budget")
        try:
            return subprocess.check_output(command, text=True, stderr=subprocess.PIPE,
                                           timeout=remaining, env=dict(os.environ, LC_ALL="C"))
        except subprocess.CalledProcessError as error:
            raise ValueError(f"{' '.join(command)}: {(error.stderr or '').strip() or 'query failed'}") from None

    ul.read = read
    try:
        roles = ul.discover_roles()
        ul.verify_routes(roles)
        return roles
    finally:
        ul.read = original


def finish_children(jobs):
    """Reap only this traffic runner's children; leave reconnect/UEs running."""
    for job in jobs:
        if job["process"].poll() is None:
            job["process"].terminate()
    for job in jobs:
        process = job["process"]
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        job["stream"].close()
        job["record"]["exit_code"] = process.returncode


def receiver_result(log):
    result = json.loads(log.read_text())
    if result.get("error"):
        raise ValueError(result["error"])
    receiver = result["end"]["sum_received"]
    if receiver["bytes"] <= 0 or receiver["seconds"] < PHASE_SECONDS - 2:
        raise ValueError("Receiver did not complete a full, positive-byte transfer")
    zero_intervals = sum(
        item.get("sum", {}).get("bits_per_second", 0) == 0
        for item in result.get("intervals", []))
    return dict(bytes=receiver["bytes"], seconds=receiver["seconds"],
                bits_per_second=receiver["bits_per_second"], zero_intervals=zero_intervals)


def run(wait_for_start=True, output_root="/tmp"):
    baseline = snapshot(time.monotonic() + 15)
    for role in baseline:
        print(f"UE{role['ue']}: IP={role['source']} dev={role['interface']} "
              f"APN={role['apn']} -> {role['server']}:{role['port']}", flush=True)
    if wait_for_start:
        print("READY: keep both reconnect watchers running; start Spark's 360-second xApp.", flush=True)
        while input("Within 10 seconds of subscriptions, enter START: ").strip() != "START":
            pass

    root = Path(tempfile.mkdtemp(prefix="falcon-dual-stability-", dir=output_root))
    started = time.monotonic()
    deadline = started + RUN_BUDGET
    result = dict(profile="alternating-concurrent-ul", status="running", started_at=stamp(),
                  phase_seconds=PHASE_SECONDS, baseline=baseline, phases=[], allocation_changes=[])
    (root / "truth.json").write_text(json.dumps(baseline, indent=2) + "\n")
    events = (root / "events.ndjson").open("w")
    jobs = []

    def event(kind, **fields):
        row = dict(event=kind, timestamp=stamp(), elapsed_seconds=round(time.monotonic() - started, 3), **fields)
        events.write(json.dumps(row) + "\n")
        events.flush()

    def check_roles(phase, point):
        roles = snapshot(deadline)
        event("snapshot", phase=phase, point=point, roles=roles)
        if roles != baseline:
            change = dict(phase=phase, point=point, roles=roles, timestamp=stamp())
            result["allocation_changes"].append(change)
            print(f"Phase {phase}: allocation/context changed; preserved as instability evidence", flush=True)
        return roles

    print("Laptop stability directory:", root, flush=True)
    try:
        event("started", roles=baseline)
        for number, (label, active_ues) in enumerate(PHASES, 1):
            roles = check_roles(number, "before")
            phase = dict(phase=number, label=label, active_ues=active_ues,
                         started_at=stamp(), started_elapsed_seconds=round(time.monotonic() - started, 3),
                         status="running", links=[])
            result["phases"].append(phase)
            print(f"[{number}/6] {label.upper()} upload {PHASE_SECONDS}s ...", flush=True)
            jobs = []
            for role in roles:
                if role["ue"] not in active_ues:
                    continue
                log = root / f"phase{number}-ue{role['ue']}.json"
                record = dict(role, log=log.name, started_at=stamp(), exit_code=None)
                phase["links"].append(record)
                stream = log.open("w")
                try:
                    process = subprocess.Popen(
                        ["iperf3", "-c", role["server"], "-p", str(role["port"]),
                         "-B", role["source"], "-t", str(PHASE_SECONDS), "-i", "1",
                         "--json", "--get-server-output"], stdin=subprocess.DEVNULL,
                        stdout=stream, stderr=subprocess.STDOUT)
                except BaseException:
                    stream.close()
                    raise
                record["pid"] = process.pid
                jobs.append(dict(process=process, stream=stream, record=record))
                event("iperf_started", phase=number, ue=role["ue"], source=role["source"], pid=process.pid)

            phase_deadline = min(deadline, time.monotonic() + PHASE_SECONDS + 5)
            while True:
                running = False
                for job in jobs:
                    code = job["process"].poll()
                    if code is None:
                        running = True
                    elif job["record"]["exit_code"] is None:
                        job["record"].update(exit_code=code, ended_at=stamp())
                        event("iperf_finished", phase=number, ue=job["record"]["ue"], exit_code=code)
                if not running:
                    break
                if time.monotonic() >= phase_deadline:
                    raise TimeoutError(f"Phase {number}: iperf exceeded its time budget")
                time.sleep(0.2)

            finish_children(jobs)
            for link in phase["links"]:
                try:
                    link["receiver"] = receiver_result(root / link["log"])
                except (OSError, ValueError, KeyError, TypeError) as error:
                    link["error"] = str(error)
            phase["status"] = "completed" if all(
                link["exit_code"] == 0 and "error" not in link for link in phase["links"]) else "failed"
            phase.update(ended_at=stamp(), ended_elapsed_seconds=round(time.monotonic() - started, 3))
            event("phase_finished", **phase)
            check_roles(number, "after")
            print(f"[{number}/6] {label.upper()} {phase['status'].upper()}", flush=True)
        result["status"] = "completed" if (
            not result["allocation_changes"] and all(p["status"] == "completed" for p in result["phases"])) else "failed"
    except (Exception, KeyboardInterrupt) as error:
        result.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "aborted",
                      error=str(error) or type(error).__name__)
        if result["phases"] and result["phases"][-1]["status"] == "running":
            result["phases"][-1].update(status=result["status"], ended_at=stamp())
        event(result["status"], error=result["error"])
    finally:
        finish_children(jobs)
        result.update(ended_at=stamp(), elapsed_seconds=round(time.monotonic() - started, 3))
        (root / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
        events.close()
        print("STATUS:", result["status"], "Evidence:", root, flush=True)
        print("Reconnect watchers and both UEs remain running.", flush=True)
    return 0 if result["status"] == "completed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-now", action="store_true", help="Skip READY prompt; Spark capture must already be subscribed")
    args = parser.parse_args()
    def interrupt(*_):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        return run(wait_for_start=not args.start_now)
    except (OSError, ValueError, subprocess.SubprocessError, TimeoutError, EOFError, KeyboardInterrupt) as error:
        print(f"STOP before traffic: {str(error) or type(error).__name__}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
