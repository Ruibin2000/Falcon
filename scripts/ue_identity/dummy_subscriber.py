#!/usr/bin/env python3
"""Independent version-2 subscriber: socket receipt, bound KPM validation and TXT."""
import argparse
from collections import deque
import json
from pathlib import Path
import queue
import select
import signal
import socket
import sys
import threading
import time

from metrics import EXPANDED
from subscription_protocol import (VERSION, PROFILE, MAX_FRAME, decode, encode,
                                   link_id, mono_us, validate_report, parse_filter)
from core import integer
from text_report import format_record


class Connection:
    def __init__(self, host, port):
        self.socket = socket.create_connection((host, port), 5)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.socket.setblocking(False)
        self.partial = bytearray()
        self.frames = deque()

    def send(self, obj):
        remaining = memoryview(encode(obj))
        deadline = time.monotonic() + 2
        while remaining:
            timeout = deadline - time.monotonic()
            if timeout <= 0 or not select.select([], [self.socket], [], timeout)[1]:
                raise TimeoutError("request write deadline")
            try:
                count = self.socket.send(remaining)
            except BlockingIOError:
                continue
            if not count:
                raise EOFError("socket closed during request")
            remaining = remaining[count:]

    def receive(self, timeout):
        deadline = time.monotonic() + max(0, timeout)
        while not self.frames:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.socket], [], [], remaining)[0]:
                raise TimeoutError("response deadline")
            try:
                data = self.socket.recv(MAX_FRAME)
            except BlockingIOError:
                continue
            received, unix = mono_us(), time.time_ns() // 1000
            if not data:
                if self.partial:
                    raise ValueError("truncated final frame")
                raise EOFError("server EOF")
            self.partial.extend(data)
            while b"\n" in self.partial:
                index = self.partial.index(10)
                if index + 1 > MAX_FRAME:
                    raise ValueError("oversized server frame")
                line = bytes(self.partial[:index])
                del self.partial[:index + 1]
                self.frames.append((line, received, unix))
            if len(self.partial) >= MAX_FRAME:
                raise ValueError("oversized server partial frame")
        raw, received, unix = self.frames.popleft()
        return decode(raw), received, unix

    def close(self):
        self.socket.close()


class TextWriter:
    """Bounded writer: receiving/timestamping never waits for disk progress."""
    def __init__(self, text, receipt=None, *, limit=256, byte_limit=4194304, delay_ms=0):
        self.text = Path(text).open("x", encoding="utf-8")
        try:
            self.receipt = Path(receipt).open("x", encoding="utf-8") if receipt else None
        except Exception:
            self.text.close()
            raise
        self.queue = queue.Queue(maxsize=limit)
        self.lock = threading.Lock()
        self.bytes = 0
        self.byte_limit = byte_limit
        self.delay = delay_ms / 1000
        self.stop = threading.Event()
        self.error = None
        self.written = 0
        self.max_write_delay_us = 0
        self.peak = 0
        self.thread = threading.Thread(target=self._run, name="kpm-txt-writer", daemon=True)
        self.thread.start()

    def offer(self, obj, received, unix):
        data = dict(obj, dummy_received_at_mono_us=str(received), dummy_received_at_unix_us=str(unix))
        from subscription import owned_size
        size = owned_size(data)
        with self.lock:
            if self.error:
                raise RuntimeError("TXT writer failed") from self.error
            if size > self.byte_limit - self.bytes:
                raise RuntimeError("TXT writer byte queue overflow")
            try:
                self.queue.put_nowait((data, size))
            except queue.Full as exc:
                raise RuntimeError("TXT writer item queue overflow") from exc
            self.bytes += size
            self.peak = max(self.peak, self.queue.qsize())

    def _run(self):
        try:
            self.text.write("Falcon bound KPM subscriber report\nTransport=version-2 application subscription; timestamps use CLOCK_MONOTONIC.\nSource kind is stated per received record.\n\n")
            while not self.stop.is_set() or not self.queue.empty():
                try:
                    obj, size = self.queue.get(timeout=0.02)
                except queue.Empty:
                    continue
                try:
                    if self.delay:
                        time.sleep(self.delay)
                    if obj["type"] == "kpm_report":
                        self.text.write(f"subscription={obj['subscription_id']} report_seq={obj['report_seq']} source={obj['data_source']} "
                                        f"delivery_seq={obj['delivery_seq']} link_id={obj['link_id']} "
                                        f"binding_revision={obj['binding_revision']} dummy_received_at_mono_us={obj['dummy_received_at_mono_us']}\n")
                        self.text.write(format_record(obj["report"]))
                        self.text.flush()
                        self.written += 1
                        written = mono_us()
                        self.max_write_delay_us = max(self.max_write_delay_us, written - int(obj["dummy_received_at_mono_us"]))
                        obj["dummy_written_at_mono_us"] = str(written)
                    if self.receipt:
                        self.receipt.write(json.dumps(obj, allow_nan=False, separators=(",", ":")) + "\n")
                        self.receipt.flush()
                finally:
                    with self.lock:
                        self.bytes -= size
        except Exception as exc:
            self.error = exc
        finally:
            try:
                self.text.close()
                if self.receipt:
                    self.receipt.close()
            except Exception as exc:
                self.error = exc

    def close(self):
        self.stop.set()
        self.thread.join(5)
        if self.thread.is_alive():
            raise TimeoutError("TXT writer drain deadline")
        if self.error:
            raise RuntimeError("TXT writer failed") from self.error


def distribution(values):
    if not values:
        return dict(count=0, p50=None, p95=None, p99=None, max=None)
    values = sorted(values)
    import math
    return {"count": len(values), **{f"p{p}": values[max(0, math.ceil(len(values) * p / 100) - 1)] / 1000 for p in (50, 95, 99)},
            "max": values[-1] / 1000}


def validate_push(obj, registration, delivery, last_per_link, received):
    if any(obj.get(k) != registration[k] for k in ("broker_instance_id", "metric_profile", "data_source", "subscription_id")) or obj.get("version") != VERSION:
        raise ValueError("changed instance, subscription, version, source or profile")
    if integer(obj["delivery_seq"]) != str(delivery + 1):
        raise ValueError("delivery sequence gap/duplicate")
    key = validate_report(obj["report"])
    if obj["link_id"] != link_id(key):
        raise ValueError("inconsistent complete link identity")
    if int(integer(obj["report_seq"])) != obj["report"]["sequence"]:
        raise ValueError("report sequence mismatch")
    previous = last_per_link.get(key)
    if previous and (int(obj["report_seq"]) <= previous[0] or int(obj["binding_revision"]) < previous[1]):
        raise ValueError("reordered report or binding revision")
    callback, ready, published, until = (int(integer(obj[k])) for k in (
        "callback_at_mono_us", "report_ready_at_mono_us", "published_at_mono_us", "valid_until_mono_us"))
    if not int(registration["cutoff_at_mono_us"]) < callback <= ready <= published <= received < until:
        raise ValueError("pre-cutoff, expired or inconsistent report timing")
    interval = received - previous[2] if previous else None
    last_per_link[key] = (int(obj["report_seq"]), int(integer(obj["binding_revision"])), received)
    return dict(push=received - ready, callback_to_receive=received - callback,
                matching=ready - callback, publishing=published - ready,
                queue_and_socket=received - published), interval


def run(args):
    writer = TextWriter(args.text_output, args.receipts_output, delay_ms=args.test_writer_delay_ms,
                        limit=args.writer_queue_reports, byte_limit=args.writer_queue_bytes)
    connection = None
    stop = threading.Event()
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in handlers:
        signal.signal(sig, lambda _sig, _frame: stop.set())
    failure = None
    deliveries = 0
    times = {name: [] for name in ("push", "callback_to_receive", "matching", "publishing", "queue_and_socket")}
    intervals = {}
    last = {}
    unregistered = False
    try:
        connection = Connection(args.host, args.port)
        filter_spec = {"mode": "all_matched_links"} if args.all_links else {
            "mode": "links", "links": json.loads(Path(args.links_file).read_text())}
        keys = parse_filter(filter_spec)
        connection.send(dict(version=VERSION, type="register", request_id="reg-1", app_id=args.app_id,
                             expected_profile=PROFILE, filter=filter_spec))
        registration, received, unix = connection.receive(5)
        if (registration.get("type") != "registration_status" or registration.get("status") != "registered"
                or registration.get("request_id") != "reg-1" or registration.get("app_id") != args.app_id
                or registration.get("version") != VERSION or registration.get("metric_profile") != args.expected_profile
                or registration.get("metric_names") != list(EXPANDED) or registration.get("data_source") not in ("e2", "replay", "fixture")
                or registration.get("filter") != filter_spec):
            raise ValueError(f"registration rejected/inconsistent: {registration}")
        if args.test_writer_delay_ms and registration["data_source"] == "e2":
            raise ValueError("test writer delay forbidden with live source")
        writer.offer(registration, received, unix)
        deadline = time.monotonic() + (args.duration if args.duration is not None else args.timeout)
        ping_at = time.monotonic() + 10
        pending_ping = None

        def consume(obj, received, unix):
            nonlocal deliveries, pending_ping
            if any(obj.get(k) != registration[k] for k in ("broker_instance_id", "metric_profile", "data_source")) or obj.get("version") != VERSION:
                raise ValueError("changed broker envelope")
            if obj["type"] == "kpm_report":
                measurements, interval = validate_push(obj, registration, deliveries, last, received)
                key = link_key_from_message(obj)
                if keys is not None and key not in keys:
                    raise ValueError("exact-link filter leakage")
                if deliveries >= 200000:
                    raise ValueError("timing sample capacity exceeded")
                deliveries += 1
                for name, value in measurements.items():
                    times[name].append(value)
                if interval is not None:
                    intervals.setdefault(obj["link_id"], []).append(interval)
            elif obj["type"] == "pong":
                if not pending_ping or obj.get("request_id") != pending_ping:
                    raise ValueError("unexpected pong")
                pending_ping = None
            elif obj["type"] == "binding_state":
                if obj.get("subscription_id") != registration["subscription_id"]:
                    raise ValueError("changed binding-state subscription")
            else:
                raise ValueError(f"unexpected server message: {obj}")
            writer.offer(obj, received, unix)

        while not stop.is_set() and time.monotonic() < deadline and (args.reports is None or deliveries < args.reports):
            if writer.error:
                raise RuntimeError("TXT writer failed") from writer.error
            now = time.monotonic()
            if now >= ping_at:
                if pending_ping:
                    raise TimeoutError("missing pong")
                pending_ping = f"ping-{deliveries}"
                connection.send(dict(version=VERSION, type="ping", request_id=pending_ping))
                ping_at = now + 10
            try:
                obj, received, unix = connection.receive(min(0.5, deadline - now, ping_at - now))
            except TimeoutError:
                continue
            consume(obj, received, unix)
        if args.reports is not None and deliveries < args.reports and not stop.is_set():
            raise TimeoutError(f"received {deliveries}, expected {args.reports}")
        connection.send(dict(version=VERSION, type="unregister", request_id="unreg-1", subscription_id=registration["subscription_id"]))
        drain_until = time.monotonic() + 2
        while True:
            obj, received, unix = connection.receive(drain_until - time.monotonic())
            if obj.get("type") == "unregistration_status":
                if (obj.get("status") != "unregistered" or obj.get("request_id") != "unreg-1"
                        or obj.get("subscription_id") != registration["subscription_id"]
                        or obj.get("broker_instance_id") != registration["broker_instance_id"]):
                    raise ValueError("invalid unregister acknowledgment")
                writer.offer(obj, received, unix)
                unregistered = True
                break
            consume(obj, received, unix)
        try:
            connection.receive(2)
        except EOFError:
            pass
        else:
            raise ValueError("message after unregister acknowledgment")
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, TimeoutError, EOFError) as exc:
        failure = str(exc)
    finally:
        if connection:
            connection.close()
        try:
            writer.close()
        except (OSError, RuntimeError, TimeoutError) as exc:
            failure = str(exc)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    if writer.written != deliveries:
        failure = failure or "TXT report count differs from received count"
    summaries = {name + "_ms": distribution(values) for name, values in times.items()}
    if args.check_timing and deliveries:
        push, total = summaries["push_ms"], summaries["callback_to_receive_ms"]
        if push["p95"] > 10 or push["p99"] > 25 or push["max"] > 100 or total["p99"] > 100:
            failure = failure or "planned push/callback timing budget exceeded"
    summary = dict(status="failed" if failure else "passed", error=failure, reports_received=deliveries,
                   text_reports_written=writer.written, unregistered=unregistered, interrupted=stop.is_set(),
                   timing=summaries, per_link_interval_ms={key: distribution(values) for key, values in intervals.items()},
                   writer_queue_peak=writer.peak, writer_max_delay_ms=writer.max_write_delay_us / 1000)
    if args.summary:
        with Path(args.summary).open("x", encoding="utf-8") as output:
            output.write(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, separators=(",", ":")), flush=True)
    return 1 if failure else 0


def link_key_from_message(obj):
    from subscription_protocol import link_key
    return link_key(obj["report"]["node"], obj["report"]["row"]["ue"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--app-id", required=True)
    filter_args = parser.add_mutually_exclusive_group(required=True)
    filter_args.add_argument("--all-links", action="store_true")
    filter_args.add_argument("--links-file")
    duration = parser.add_mutually_exclusive_group()
    duration.add_argument("--reports", type=int)
    duration.add_argument("--duration", type=float)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--expected-profile", choices=[PROFILE], default=PROFILE)
    parser.add_argument("--text-output", required=True)
    parser.add_argument("--receipts-output")
    parser.add_argument("--summary")
    parser.add_argument("--check-timing", action="store_true")
    parser.add_argument("--test-writer-delay-ms", type=float, default=0)
    parser.add_argument("--writer-queue-reports", type=int, default=256)
    parser.add_argument("--writer-queue-bytes", type=int, default=4194304)
    args = parser.parse_args()
    if args.reports is None and args.duration is None:
        args.reports = 30
    if args.timeout <= 0 or (args.reports is not None and args.reports < 1) or (args.duration is not None and not 0 < args.duration <= 86400) or not 0 <= args.test_writer_delay_ms <= 10000:
        parser.error("invalid duration/count/timeout/delay")
    if not 1 <= args.writer_queue_reports <= 256 or not 1 <= args.writer_queue_bytes <= 4194304:
        parser.error("invalid writer queue bound")
    for path in (args.text_output, args.receipts_output, args.summary):
        if path and Path(path).exists():
            parser.error(f"output already exists: {path}")
    try:
        return run(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"dummy subscriber: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
