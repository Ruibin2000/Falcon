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
    profile.add_argument("--du-metrics", type=int, choices=(7, 5), default=7,
                         help="DU metric profile: 7 by default; use 5 for legacy DUs")
    parser.add_argument("--replay", type=Path, help="offline NDJSON input; does not start E2 or HTTP")
    parser.add_argument("--duration", type=int, default=60)
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
    if args.e2_config is None:
        name = "xapp_ue_identity_five.conf" if args.du_metrics == 5 else "xapp_ue_identity.conf"
        args.e2_config = ROOT / "configs/flexric" / name
    if not 1 <= args.duration <= 3600:
        parser.error("duration must be 1..3600 seconds")
    config = json.loads(args.config.read_text())
    if args.observed_unique:
        config["du_scope_mode"] = "observed_unique"
    if args.last_known or args.fresh_only:
        config["binding_policy"] = "last_known" if args.last_known else "fresh_only"
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


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print(f"identity xApp: {exc}", file=sys.stderr)
        raise SystemExit(1)
