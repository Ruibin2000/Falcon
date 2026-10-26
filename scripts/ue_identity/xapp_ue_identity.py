#!/usr/bin/env python3
"""Standalone coordinator for the FlexRIC collector and read-only Core poller."""

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid

from core import InfoAPI, normalize, poll
from mapping import Mapper
from text_report import format_record, report_header

ROOT = Path(__file__).resolve().parents[2]
MAX_EVENT = 4 * 1024 * 1024


class BoundedEvents:
    """Bound both item count and encoded bytes, including Core snapshots."""

    def __init__(self, max_items=256, max_bytes=4 * 1024 * 1024):
        self.queue = queue.Queue(maxsize=max_items)
        self.max_bytes = max_bytes
        self.bytes = 0
        self.lock = threading.Lock()

    def put(self, payload):
        with self.lock:
            if self.bytes + len(payload) > self.max_bytes:
                return False
            try:
                self.queue.put_nowait(payload)
            except queue.Full:
                return False
            self.bytes += len(payload)
            return True

    def get(self, timeout):
        payload = self.queue.get(timeout=timeout)
        with self.lock:
            self.bytes -= len(payload)
        return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/ue_identity/local.json")
    parser.add_argument("--collector", type=Path, default=Path("/tmp/falcon-xapp-ue-identity"))
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument("--e2-config", type=Path, help="custom E2 subscription configuration")
    profile.add_argument("--du-metrics", type=int, choices=(27, 7, 5), default=None,
                         help="DU profile: 27 expanded; 7 accepted baseline (default); 5 legacy")
    parser.add_argument("--replay", type=Path, help="offline NDJSON input; does not start E2 or HTTP")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--publish-config", type=Path,
                        help="enable version-2 app subscriptions; defaults to 27 metrics and fresh-only binding")
    parser.add_argument("--publisher-summary", type=Path, help="new final publisher counters JSON")
    parser.add_argument("--report-evidence", type=Path, help="opt-in bounded matched-source JSONL and independent REAL bits")
    parser.add_argument("--replay-speed", type=float, default=1.0, help="subscription replay pace; 1 is original timing")
    parser.add_argument("--probe-core", action="store_true", help="read Core interfaces without starting E2")
    parser.add_argument("--capture-events", type=Path,
                        help="create a new NDJSON trace of decoded CU/DU and Core inputs for live verification")
    parser.add_argument("--text-output", type=Path,
                        help="create a new TXT report with UE/DU/AMF/session/IP binding followed by KPM; stdout stays NDJSON")
    parser.add_argument("--observed-unique", action="store_true",
                        help="experimental current-observation DU scope; strict mode otherwise withholds IP")
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--last-known", action="store_true",
                        help="keep a previously verified per-link binding during missing updates; label it cached")
    policy.add_argument("--fresh-only", action="store_true",
                        help="withhold IP when current inputs for this link cannot verify it; disable historical IP reuse")
    args = parser.parse_args()
    if args.publish_config and (args.text_output or args.last_known or args.probe_core):
        parser.error("subscription mode owns no TXT sink, requires fresh binding and cannot probe only")
    if args.publish_config and args.du_metrics not in (None, 27):
        parser.error("subscription mode requires the full 27-metric profile")
    if args.du_metrics is None:
        args.du_metrics = 27 if args.publish_config else 7
    if args.e2_config is None:
        name = {27: "xapp_ue_identity_expanded.conf", 7: "xapp_ue_identity.conf",
                5: "xapp_ue_identity_five.conf"}[args.du_metrics]
        args.e2_config = ROOT / "configs/flexric" / name
    if not 0 <= args.duration <= 3600 or (not args.duration and not args.publish_config):
        parser.error("duration must be 1..3600, or 0 for continuous subscription service")
    if not 0 < args.replay_speed <= 100:
        parser.error("replay speed must be positive and at most 100")
    config = json.loads(args.config.read_text())
    if args.observed_unique:
        config["du_scope_mode"] = "observed_unique"
    if args.last_known or args.fresh_only:
        config["binding_policy"] = "last_known" if args.last_known else "fresh_only"
    if args.publish_config:
        config["binding_policy"] = "fresh_only"
    if args.probe_core:
        client = InfoAPI(config.get("http_timeout_s", 0.5))
        amf = client.fetch(config["amf"]["url"])
        smf = client.fetch(config["smf_url"])
        result = normalize(config, amf, smf)
        print(json.dumps({"status": "ok", "amf_ues": len(amf), "smf_ues": len(smf),
                          "eligible_radio_contexts": len(result)}))
        return 0
    mapper = Mapper(config)
    with ExitStack() as outputs:
        capture = outputs.enter_context(args.capture_events.open("x", encoding="utf-8")) if args.capture_events else None
        report = outputs.enter_context(args.text_output.open("x", encoding="utf-8")) if args.text_output else None
        if report is not None:
            report.write(report_header(args.replay))
            report.flush()
        return run(args, config, mapper, capture, report)


def run(args, config, mapper, capture, report):
    if args.publish_config:
        return run_subscriptions(args, config, mapper, capture)

    def handle(event):
        if capture is not None:
            capture.write(json.dumps(event, allow_nan=False, separators=(",", ":")) + "\n")
            capture.flush()
        now = int(event.get("received_at_us", time.time_ns() // 1000))
        mono = event.get("received_at_mono_us", now if args.replay else time.monotonic_ns() // 1000)
        for row in mapper.ingest(event, now, mono):
            row["emitted_at_us"] = str(time.time_ns() // 1000)
            print(json.dumps(row, allow_nan=False, separators=(",", ":")), flush=True)
            if report is not None:
                report.write(format_record(row))
                report.flush()

    if args.replay:
        with args.replay.open("rb") as source:
            while line := source.readline(MAX_EVENT + 1):
                if len(line) > MAX_EVENT:
                    raise ValueError("replay event exceeds limit")
                handle(json.loads(line))
        return 0

    events = BoundedEvents()
    stop = threading.Event()
    loss = threading.Event()

    def publish(event):
        event["received_at_mono_us"] = time.monotonic_ns() // 1000
        payload = json.dumps(event, allow_nan=False, separators=(",", ":")).encode()
        if not events.put(payload):
            loss.set()

    def on_signal(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    read_fd, write_fd = os.pipe()
    env = dict(os.environ, FALCON_IDENTITY_FD=str(write_fd), FALCON_KPM_SECONDS=str(args.duration))
    child = subprocess.Popen([str(args.collector), "-c", str(args.e2_config)],
                             env=env, pass_fds=(write_fd,), stdout=sys.stderr, stderr=sys.stderr)
    os.close(write_fd)

    def read_e2():
        with os.fdopen(read_fd, "rb") as source:
            while True:
                line = source.readline(MAX_EVENT + 1)
                if not line:
                    break
                if len(line) > MAX_EVENT or not line.endswith(b"\n"):
                    loss.set()
                    break
                try:
                    event = json.loads(line)
                    event["received_at_us"] = time.time_ns() // 1000
                    publish(event)
                except (ValueError, TypeError):
                    loss.set()

    threading.Thread(target=read_e2, daemon=True).start()
    threading.Thread(target=poll, args=(config, publish, stop), daemon=True).start()
    deadline = time.monotonic() + args.duration
    try:
        while not stop.is_set() and time.monotonic() < deadline:
            if loss.is_set():
                handle({"kind": "ingress_loss", "received_at_us": time.time_ns() // 1000})
                loss.clear()
            try:
                handle(json.loads(events.get(timeout=0.1)))
            except queue.Empty:
                if child.poll() is not None:
                    break
            except (ValueError, TypeError, KeyError) as exc:
                handle({"kind": "ingress_loss", "received_at_us": time.time_ns() // 1000})
                print(f"identity input rejected: {exc}", file=sys.stderr)
    finally:
        stop.set()
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
            print("collector cleanup timed out; E2 deletion not verified", file=sys.stderr)
            return 1
    return 0 if child.returncode == 0 else 1


def run_subscriptions(args, config, mapper, capture):
    """Keep the original mapper; replace its production output sink with pushes."""
    from subscription import Publisher
    from subscription_feed import BoundReportFeed
    from subscription_protocol import mono_us, decode
    import gzip
    import re

    # Validate the actual chosen subscription without running SDK initialization.
    text = args.e2_config.read_text()
    groups = re.findall(r'\{\s*name\s*=\s*"KPM"\s*,\s*time\s*=\s*(\d+)\s*,\s*format\s*=\s*4\s*,\s*ran_type\s*=\s*"([^"]+)"\s*,\s*actions\s*=\s*\((.*?)\)\s*\}', text, re.S)
    from metrics import EXPANDED
    du = [(int(period), re.findall(r'name\s*=\s*"([^"]+)"', actions))
          for period, kind, actions in groups if kind == "ngran_gNB_DU"]
    if du != [(100, list(EXPANDED))]:
        raise ValueError("subscription mode requires the 27-name DU Style 4 config at 100 ms")
    cu = [(int(period), re.findall(r'name\s*=\s*"([^"]+)"', actions))
          for period, kind, actions in groups if kind in config["cu"]["node_types"]]
    if not cu or any(group != (1000, ["FALCON.UE.RRCState"]) for group in cu) or config.get("poll_period_s", 1.0) != 1.0:
        raise ValueError("du27_bound_v1 requires CU identity at 1000 ms and Core polling at 1 second")
    publisher = Publisher(json.loads(args.publish_config.read_text()), source="replay" if args.replay else "e2")
    stop = threading.Event()
    failures = []
    events = BoundedEvents()
    loss = threading.Event()
    child = None
    threads = []
    deadline = time.monotonic() + args.duration if args.duration else float("inf")
    old_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in old_handlers:
        signal.signal(sig, lambda _sig, _frame: stop.set())

    def enqueue(event):
        if "received_at_us" not in event:
            event["received_at_us"] = time.time_ns() // 1000
        event["received_at_mono_us"] = mono_us()
        payload = json.dumps(event, allow_nan=False, separators=(",", ":")).encode()
        if len(payload) > MAX_EVENT or not events.put(payload):
            loss.set()

    def live_reader(fd):
        try:
            with os.fdopen(fd, "rb") as source:
                while not stop.is_set():
                    line = source.readline(MAX_EVENT + 1)
                    if not line:
                        break
                    if len(line) > MAX_EVENT or not line.endswith(b"\n"):
                        raise ValueError("collector event frame exceeds bound")
                    event = decode(line)
                    if "callback_at_mono_us" not in event:
                        raise ValueError("collector needs rebuild: callback monotonic timestamp is missing")
                    enqueue(event)
        except (ValueError, OSError) as exc:
            failures.append(str(exc))
        finally:
            enqueue({"kind": "source_eof"})

    def replay_reader():
        opener = gzip.open if args.replay.suffix == ".gz" else open
        replay_instance = str(uuid.uuid4())
        first_wall = None
        started = mono_us()
        try:
            with opener(args.replay, "rb") as source:
                sequence = 0
                while not stop.is_set():
                    line = source.readline(MAX_EVENT + 1)
                    if not line:
                        break
                    if len(line) > MAX_EVENT:
                        raise ValueError("replay event exceeds limit")
                    event = decode(line)
                    wall = int(event["received_at_us"])
                    if first_wall is None:
                        first_wall = wall
                    due = started + (wall - first_wall) / args.replay_speed
                    if stop.wait(max(0, (due - mono_us()) / 1_000_000)):
                        break
                    sequence += 1
                    # Replay source time is projected onto the shared clock; label
                    # it separately from real callback instrumentation.
                    lag = max(0, wall - int(event.get("callback_at_us", wall)))
                    event.update(callback_at_mono_us=str(max(1, mono_us() - int(lag / args.replay_speed))),
                                 source_instance_id=replay_instance, source_indication_seq=str(sequence),
                                 callback_time_kind="replay_projection")
                    enqueue(event)
        except (ValueError, KeyError, OSError) as exc:
            failures.append(str(exc))
        finally:
            enqueue({"kind": "source_eof"})

    summary = None
    evidence = None
    try:
        if args.publisher_summary:
            summary = args.publisher_summary.open("x", encoding="utf-8")
        if args.report_evidence:
            from subscription_evidence import SourceEvidence
            evidence = SourceEvidence(args.report_evidence)
        publisher.start()
        print(f"SUBSCRIPTION_READY host=127.0.0.1 port={publisher.port} profile=du27_bound_v1 source={publisher.source} instance={publisher.instance}", flush=True)
        feed = BoundReportFeed(mapper, publisher, evidence)
        if args.replay:
            threads.append(threading.Thread(target=replay_reader, name="kpm-replay", daemon=True))
        else:
            read_fd, write_fd = os.pipe()
            env = dict(os.environ, FALCON_IDENTITY_FD=str(write_fd), FALCON_KPM_SECONDS=str(args.duration),
                       FALCON_IDENTITY_INSTANCE=str(uuid.uuid4()))
            try:
                child = subprocess.Popen([str(args.collector), "-c", str(args.e2_config)],
                                         env=env, pass_fds=(write_fd,), stdout=sys.stderr, stderr=sys.stderr)
            except Exception:
                os.close(read_fd)
                raise
            finally:
                os.close(write_fd)
            threads.extend([threading.Thread(target=live_reader, args=(read_fd,), name="kpm-source", daemon=True),
                            threading.Thread(target=poll, args=(config, enqueue, stop), name="kpm-core", daemon=True)])
        for thread in threads:
            thread.start()
        while not stop.is_set() and time.monotonic() < deadline:
            if publisher.stats()["failed"]:
                raise RuntimeError("publisher worker failed")
            if evidence and evidence.error:
                raise RuntimeError("source evidence writer failed") from evidence.error
            if loss.is_set():
                feed.ingest(dict(kind="ingress_loss", received_at_us=feed.clock()[0] or time.time_ns() // 1000,
                                 received_at_mono_us=mono_us()))
                loss.clear()
            try:
                event = json.loads(events.get(timeout=0.02))
            except queue.Empty:
                feed.refresh()
                continue
            if event["kind"] == "source_eof":
                publisher.source_unavailable("replay completed" if args.replay else "collector stopped")
                if not args.replay:
                    failures.append("collector stopped before service shutdown")
                    break
                continue  # Stay responsive after finite replay; never replay old KPM.
            if capture:
                capture.write(json.dumps(event, allow_nan=False, separators=(",", ":")) + "\n")
                capture.flush()
            try:
                feed.ingest(event)
            except (ValueError, KeyError, TypeError) as exc:
                failures.append(f"input rejected: {exc}")
                feed.ingest(dict(kind="ingress_loss", received_at_us=feed.clock()[0], received_at_mono_us=mono_us()))
    finally:
        stop.set()
        publisher.stop_admission()
        if child is not None:
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)
            try:
                if child.wait(timeout=10):
                    failures.append("collector nonzero exit")
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
                failures.append("collector cleanup timed out; E2 deletion unverified")
        for thread in threads:
            thread.join(timeout=3)
            if thread.is_alive():
                failures.append(f"thread did not stop: {thread.name}")
        publisher.close()
        if evidence:
            evidence.close()
        counters = publisher.stats()
        result = dict(source=publisher.source, metric_profile="du27_bound_v1", counters=counters,
                      failures=failures, status="failed" if failures or counters.get("invalid_reports") or counters.get("serialization_errors") else "passed")
        print("SUBSCRIPTION_SUMMARY " + json.dumps(result, separators=(",", ":")), file=sys.stderr)
        if summary:
            summary.write(json.dumps(result, indent=2) + "\n")
            summary.close()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"identity xApp: {exc}", file=sys.stderr)
        raise SystemExit(1)
