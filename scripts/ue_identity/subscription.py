"""Bounded, source-driven application subscription service. No E2 APIs here."""
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import copy
import json
import os
import queue
import selectors
import socket
import sys
import threading
import uuid

from metrics import EXPANDED
from subscription_protocol import (VERSION, PROFILE, MAX_REQUEST, MAX_FRAME, decode,
                                   encode, identifier, link_id, mono_us, parse_filter,
                                   validate_report)

DEFAULTS = dict(bind="127.0.0.1", port=8765, clients=16, ingress_reports=256,
                ingress_bytes=4194304, output_frames=64, output_bytes=1048576,
                registration_ms=5000, incomplete_ms=5000, idle_ms=30000,
                write_ms=5000, drain_ms=2000, write_chunk=0, test_stall_app="")


def configuration(values=None, *, test_mode=False):
    values = values or {}
    if not isinstance(values, dict) or set(values) - set(DEFAULTS):
        raise ValueError("unknown subscription configuration")
    result = dict(DEFAULTS, **values)
    if result["bind"] != "127.0.0.1":
        raise ValueError("subscription service requires loopback binding")
    for key, high in (("port", 65535), ("clients", 16), ("ingress_reports", 256),
                      ("ingress_bytes", 4194304), ("output_frames", 64),
                      ("output_bytes", 1048576), ("registration_ms", 5000),
                      ("incomplete_ms", 5000), ("idle_ms", 30000),
                      ("write_ms", 5000), ("drain_ms", 2000), ("write_chunk", MAX_FRAME)):
        low = 0 if key in ("port", "write_chunk") else 1
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f"invalid subscription setting: {key}")
    if not isinstance(result["test_stall_app"], str) or (result["test_stall_app"] and not identifier(result["test_stall_app"])):
        raise ValueError("invalid test stall app")
    if not test_mode and (result["write_chunk"] or result["test_stall_app"]):
        raise ValueError("fixture I/O adapters are forbidden with live E2")
    return result


def owned_size(value):
    """Conservative Python allocation accounting, including duplicate references."""
    import sys
    total = sys.getsizeof(value)
    if isinstance(value, dict):
        total += sum(owned_size(k) + owned_size(v) for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        total += sum(owned_size(v) for v in value)
    return total


@dataclass
class Client:
    socket: socket.socket
    opened: int
    state: str = "awaiting_registration"
    app: str = ""
    subscription: str = ""
    filters: object = None
    cutoff: int = 0
    delivery: int = 0
    activity: int = 0
    partial_since: int = 0
    progress: int = 0
    drain_since: int = 0
    last_report: int = 0
    input: bytearray = field(default_factory=bytearray)
    output: deque = field(default_factory=deque)
    output_bytes: int = 0
    sent_frames: int = 0
    known_states: dict = field(default_factory=dict)
    peer: str = ""

    def matches(self, key):
        return self.filters is None or key in self.filters


class Publisher:
    def __init__(self, settings=None, *, source="e2"):
        if source not in ("e2", "replay", "fixture"):
            raise ValueError("invalid source")
        self.config = configuration(settings, test_mode=source != "e2")
        self.source = source
        self.instance = str(uuid.uuid4())
        self._lock = threading.Lock()
        self._queue = deque()
        self._queue_bytes = 0
        self._states = {}  # Bounded by the mapper's 256 admitted radio contexts.
        self._admission = True
        self._closing = False
        self._source_error = None
        self._stats = Counter()
        self._ready = threading.Event()
        self._error = None
        self._read, self._write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        self._thread = threading.Thread(target=self._run_guarded, name="kpm-publisher")
        self.port = None
        self._clients = {}
        self._next_subscription = 0

    def start(self):
        self._thread.start()
        if not self._ready.wait(5):
            self.close()
            raise TimeoutError("publisher startup deadline")
        if self._error:
            self.close()
            raise RuntimeError("publisher startup failed") from self._error
        return self

    def _wake(self):
        if self._write < 0:
            return
        try:
            os.write(self._write, b"1")
        except BlockingIOError:
            pass
        except OSError:
            if not self._closing:
                raise

    def _count(self, name, amount=1):
        with self._lock:
            self._stats[name] += amount

    def stats(self):
        with self._lock:
            return dict(self._stats, ingress_depth=len(self._queue),
                        ingress_bytes=self._queue_bytes, known_links=len(self._states),
                        failed=self._error is not None)

    def submit(self, record, *, callback_mono_us, ready_mono_us, valid_until_mono_us):
        """Called at the existing matcher output; never waits for an application."""
        try:
            key = validate_report(record)
            if not 0 < callback_mono_us <= ready_mono_us < valid_until_mono_us:
                raise ValueError("invalid report timing")
            snapshot = copy.deepcopy(record)
            size = owned_size(snapshot)
            signature = json.dumps([snapshot["binding"], snapshot["ue_ipv4"]], sort_keys=True)
        except (ValueError, KeyError, TypeError, RecursionError):
            self._count("invalid_reports")
            return False
        with self._lock:
            if not self._admission or self._closing:
                return False
            state = self._state(key)
            if state is None:
                return False
            if state.get("signature") != signature:
                state["binding_revision"] += 1
                state["version"] += 1
                state["signature"] = signature
            if state["status"] != "receiving":
                state["version"] += 1
            state.update(status="receiving", reason="current matched report", until=valid_until_mono_us)
            self._stats["matched_reports"] += 1
            if (len(self._queue) >= self.config["ingress_reports"]
                    or size > self.config["ingress_bytes"] - self._queue_bytes):
                self._stats["ingress_dropped"] += 1
                return False
            self._queue.append((snapshot, key, callback_mono_us, ready_mono_us,
                                valid_until_mono_us, state["binding_revision"], size))
            self._queue_bytes += size
            self._stats["ingress_peak"] = max(self._stats["ingress_peak"], len(self._queue))
            self._stats["ingress_peak_bytes"] = max(self._stats["ingress_peak_bytes"], self._queue_bytes)
        self._wake()
        return True

    def _state(self, key):
        if key not in self._states:
            if len(self._states) >= 256:
                self._stats["state_capacity_errors"] += 1
                return None
            self._states[key] = dict(version=0, binding_revision=0, signature=None,
                                     status="waiting_for_match", reason="no matched report", until=0)
        return self._states[key]

    def binding_state(self, key, status, reason):
        if status not in ("waiting_for_match", "binding_invalid", "source_unavailable"):
            raise ValueError("invalid binding state")
        with self._lock:
            state = self._state(key)
            if state is None:
                return
            if (state["status"], state["reason"]) != (status, reason):
                state.update(status=status, reason=str(reason)[:512], until=0,
                             version=state["version"] + 1)
                self._stats["binding_transitions"] += 1
        self._wake()

    def source_unavailable(self, reason):
        with self._lock:
            self._source_error = str(reason)[:512]
            for state in self._states.values():
                state.update(status="source_unavailable", reason=self._source_error,
                             until=0, version=state["version"] + 1)
        self._wake()

    def stop_admission(self):
        with self._lock:
            self._admission = False
        self._wake()

    def close(self):
        if self._write < 0:
            return
        with self._lock:
            self._admission = False
            self._closing = True
        self._wake()
        if self._thread.ident:
            self._thread.join(5)
            if self._thread.is_alive():
                raise RuntimeError("publisher did not stop within drain deadline")
        os.close(self._read)
        os.close(self._write)
        self._write = -1
        if self._error:
            raise RuntimeError("publisher worker failed") from self._error

    def _envelope(self, kind, **fields):
        return dict(version=VERSION, type=kind, broker_instance_id=self.instance,
                    data_source=self.source, metric_profile=PROFILE, **fields)

    def _log(self, event, client, **fields):
        """Lifecycle events only; keep report and heartbeat traffic off the console."""
        payload = dict(at_utc=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                       broker_instance_id=self.instance, data_source=self.source,
                       peer=client.peer, app_id=client.app or None,
                       subscription_id=client.subscription or None, **fields)
        try:
            print(event + " " + json.dumps(payload, separators=(",", ":")),
                  file=sys.stderr, flush=True)
        except (OSError, ValueError):
            self._count("lifecycle_log_errors")

    def _drop(self, client, reason):
        fd = client.socket.fileno()
        if fd < 0:
            return
        self._selector.unregister(client.socket)
        client.socket.close()
        self._clients.pop(fd, None)
        client.output.clear()
        self._count(f"disconnect_{reason}")
        self._count("active_connections", -1)
        if client.app:
            self._count("active_registrations", -1)
        self._log("APP_DISCONNECTED", client, reason=reason,
                  active_registrations=self.stats().get("active_registrations", 0))

    def _events(self, client):
        stalled = bool(self.config["test_stall_app"]) and client.app == self.config["test_stall_app"] and client.sent_frames > 0
        flags = selectors.EVENT_READ if client.state != "draining" else 0
        if client.output and not stalled:
            flags |= selectors.EVENT_WRITE
        # Draining test-stalled clients still need a selectable FD until deadline.
        self._selector.modify(client.socket, flags or selectors.EVENT_READ, client)

    def _enqueue(self, client, message):
        try:
            data = encode(message)
        except (ValueError, TypeError):
            self._count("serialization_errors")
            self._drop(client, "serialization_limit")
            return False
        if (len(client.output) >= self.config["output_frames"]
                or len(data) > self.config["output_bytes"] - client.output_bytes):
            self._count("client_overflows")
            self._drop(client, "output_overflow")
            return False
        if not client.output:
            client.progress = mono_us()
        client.output.append([data, 0])
        client.output_bytes += len(data)
        self._count("frames_queued")
        self._events(client)
        return True

    def _draining(self, client):
        if client.state != "draining":
            client.state = "draining"
            client.drain_since = mono_us()
        self._events(client)

    def _reject(self, client, request, code, *, registration=False, fatal=False,
                requested_app=None):
        self._count("admission_rejects")
        self._log("APP_REGISTER_REJECTED" if registration else "APP_REQUEST_REJECTED",
                  client, request_id=request if identifier(request) else None,
                  requested_app_id=requested_app, reason=code)
        fields = dict(status="rejected", error_code=code)
        if identifier(request):
            fields["request_id"] = request
        if self._enqueue(client, self._envelope("registration_status" if registration else "error", **fields)) and fatal:
            self._draining(client)

    def _data_state(self, client):
        with self._lock:
            now = mono_us()
            states = [("binding_invalid" if state["status"] == "receiving" and state["until"] <= now else state["status"])
                      for key, state in self._states.items() if client.matches(key)]
            source_error = self._source_error
        if source_error or "source_unavailable" in states:
            state = "source_unavailable"
        elif "receiving" in states:
            state = "receiving"
        elif "binding_invalid" in states:
            state = "binding_invalid"
        else:
            state = "waiting_for_match"
        return dict(data_state=state, last_matching_report_age_ms=(mono_us() - client.last_report) / 1000 if client.last_report else None)

    def _request(self, client, raw):
        request_id = None
        registration = False
        requested_app = None
        try:
            value = decode(raw)
            request_id = value.get("request_id")
            registration = value.get("type") == "register"
            if registration:
                requested_app = value.get("app_id") if identifier(value.get("app_id")) else None
                self._log("APP_REGISTER_RECEIVED", client,
                          request_id=request_id if identifier(request_id) else None,
                          requested_app_id=requested_app)
            if not identifier(request_id):
                raise ValueError("invalid_request")
            if type(value.get("version")) is not int or value["version"] != VERSION:
                raise ValueError("unsupported_version")
            kind = value.get("type")
            if registration:
                if not self._admission:
                    raise ValueError("shutting_down")
                if client.state == "registered":
                    raise ValueError("already_registered")
                if value.get("expected_profile") != PROFILE:
                    raise ValueError("unsupported_profile")
                if set(value) != {"version", "type", "request_id", "app_id", "expected_profile", "filter"} or not identifier(value.get("app_id")):
                    raise ValueError("invalid_request")
                filters = parse_filter(value["filter"])
                if any(c.app == value["app_id"] and c.state == "registered" for c in self._clients.values()):
                    raise ValueError("duplicate_app_id")
                client.cutoff = mono_us()
                client.app, client.filters, client.state = value["app_id"], filters, "registered"
                self._next_subscription += 1
                client.subscription = f"sub-{self._next_subscription}"
                self._count("active_registrations")
                if self._enqueue(client, self._envelope("registration_status", request_id=request_id,
                    status="registered", app_id=client.app, subscription_id=client.subscription,
                    metric_names=list(EXPANDED), filter=value["filter"], report_period_ms=100,
                    cu_period_ms=1000, core_period_ms=1000, cutoff_at_mono_us=str(client.cutoff),
                    delivery="best_effort_no_replay", **self._data_state(client))):
                    self._log("APP_REGISTERED", client, request_id=request_id,
                              filter_mode=value["filter"]["mode"],
                              exact_links=len(filters) if filters is not None else 0,
                              acknowledgement="queued",
                              active_registrations=self.stats().get("active_registrations", 0))
            elif kind == "ping" and set(value) == {"version", "type", "request_id"}:
                self._enqueue(client, self._envelope("pong", request_id=request_id, **self._data_state(client)))
            elif kind == "unregister" and client.state == "registered" and set(value) == {"version", "type", "request_id", "subscription_id"} and value["subscription_id"] == client.subscription:
                self._log("APP_UNREGISTER_RECEIVED", client, request_id=request_id)
                if self._enqueue(client, self._envelope("unregistration_status", request_id=request_id,
                                 status="unregistered", subscription_id=client.subscription)):
                    self._draining(client)
                    self._log("APP_UNREGISTERED", client, request_id=request_id,
                              acknowledgement="queued")
            else:
                raise ValueError("invalid_request")
            client.activity = mono_us()
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            code = str(exc) if str(exc) in {"unsupported_version", "unsupported_profile", "shutting_down", "already_registered", "duplicate_app_id"} else "invalid_request"
            self._reject(client, request_id, code, registration=registration,
                         fatal=not identifier(request_id), requested_app=requested_app)

    def _read_client(self, client):
        try:
            data = client.socket.recv(4096)
            if not data:
                self._drop(client, "eof")
                return
            for byte in data:
                if client.socket.fileno() < 0 or client.state == "draining":
                    return
                if byte == 10:
                    self._request(client, bytes(client.input))
                    client.input.clear()
                    client.partial_since = 0
                elif len(client.input) == MAX_REQUEST:
                    self._reject(client, None, "frame_too_large", fatal=True)
                else:
                    if not client.input:
                        client.partial_since = mono_us()
                    client.input.append(byte)
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            self._drop(client, "read_error")

    def _write_client(self, client):
        try:
            data, offset = client.output[0]
            end = min(len(data), offset + self.config["write_chunk"]) if self.config["write_chunk"] else len(data)
            count = client.socket.send(memoryview(data)[offset:end])
            if not count:
                self._drop(client, "write_error")
                return
            client.progress = mono_us()
            client.output[0][1] += count
            if client.output[0][1] == len(data):
                client.output.popleft()
                client.output_bytes -= len(data)
                client.sent_frames += 1
            self._events(client)
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            self._drop(client, "write_error")

    def _publish(self):
        for _ in range(64):
            with self._lock:
                if not self._queue:
                    break
                record, key, callback, ready, until, revision, size = self._queue.popleft()
                self._queue_bytes -= size
            # The snapshot was current when generated. Later source state must
            # not erase or relabel an earlier fresh report (including EOF's
            # final queued report). State notifications follow the queued data.
            if until <= mono_us():
                self._count("expired_reports")
                continue
            for client in list(self._clients.values()):
                if client.state != "registered" or callback <= client.cutoff or not client.matches(key):
                    continue
                client.delivery += 1
                message = self._envelope("kpm_report", subscription_id=client.subscription,
                    report_seq=str(record["sequence"]), delivery_seq=str(client.delivery),
                    link_id=link_id(key), binding_revision=str(revision),
                    callback_at_mono_us=str(callback), report_ready_at_mono_us=str(ready),
                    published_at_mono_us=str(mono_us()), valid_until_mono_us=str(until),
                    ingress_dropped_total=str(self.stats().get("ingress_dropped", 0)), report=record)
                if self._enqueue(client, message):
                    client.last_report = mono_us()
                    self._count("reports_queued")

    def _notify_states(self, now):
        with self._lock:
            for state in self._states.values():
                if state["status"] == "receiving" and state["until"] <= now:
                    state.update(status="binding_invalid", reason="binding source validity expired", version=state["version"] + 1)
            if self._queue:
                return
            states = [(key, dict(state)) for key, state in self._states.items()]
        for client in list(self._clients.values()):
            if client.state != "registered":
                continue
            for key, state in states:
                if client.socket.fileno() < 0:
                    break
                if client.matches(key) and client.known_states.get(key) != state["version"]:
                    client.known_states[key] = state["version"]
                    self._enqueue(client, self._envelope("binding_state", subscription_id=client.subscription,
                        link_id=link_id(key), binding_revision=str(state["binding_revision"]),
                        data_state=state["status"], reason=state["reason"]))

    def _run_guarded(self):
        try:
            self._run()
        except Exception as exc:
            self._error = exc
            self._ready.set()
        finally:
            if hasattr(self, "_selector"):
                for client in list(self._clients.values()):
                    self._drop(client, "shutdown")
                for key in list(self._selector.get_map().values()):
                    if isinstance(key.fileobj, socket.socket):
                        key.fileobj.close()
                self._selector.close()

    def _run(self):
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._read, selectors.EVENT_READ, "wake")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.config["bind"], self.config["port"]))
            listener.listen(16)
            listener.setblocking(False)
        except Exception:
            listener.close()
            raise
        self.port = listener.getsockname()[1]
        self._selector.register(listener, selectors.EVENT_READ, "listener")
        self._ready.set()
        shutdown = 0
        while True:
            now = mono_us()
            if not self._admission and listener is not None:
                self._selector.unregister(listener)
                listener.close()
                listener = None
            if self._closing and not shutdown:
                shutdown = now
                for client in list(self._clients.values()):
                    self._draining(client)
            for key, flags in self._selector.select(0.01):
                if key.data == "wake":
                    try:
                        os.read(self._read, 65536)
                    except BlockingIOError:
                        pass
                elif key.data == "listener":
                    try:
                        sock, peer = key.fileobj.accept()
                    except (BlockingIOError, InterruptedError):
                        continue
                    sock.setblocking(False)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    client = Client(sock, mono_us(), activity=mono_us(), peer=f"{peer[0]}:{peer[1]}")
                    self._selector.register(sock, selectors.EVENT_READ, client)
                    self._clients[sock.fileno()] = client
                    self._count("active_connections")
                    if len(self._clients) > self.config["clients"]:
                        self._reject(client, None, "too_many_clients", registration=True, fatal=True)
                else:
                    client = key.data
                    if client.socket.fileno() < 0:
                        continue
                    if flags & selectors.EVENT_READ and client.state != "draining":
                        self._read_client(client)
                    if client.socket.fileno() >= 0 and flags & selectors.EVENT_WRITE and client.output:
                        self._write_client(client)
            if not shutdown:
                self._publish()
                self._notify_states(mono_us())
            now = mono_us()
            for client in list(self._clients.values()):
                reason = None
                if client.state == "draining" and (not client.output or now - client.drain_since >= self.config["drain_ms"] * 1000):
                    reason = "drained"
                elif client.state == "awaiting_registration" and now - client.opened >= self.config["registration_ms"] * 1000:
                    reason = "registration_timeout"
                elif client.partial_since and now - client.partial_since >= self.config["incomplete_ms"] * 1000:
                    reason = "incomplete_timeout"
                elif client.state == "registered" and now - client.activity >= self.config["idle_ms"] * 1000:
                    reason = "idle_timeout"
                elif client.output and now - client.progress >= self.config["write_ms"] * 1000:
                    reason = "write_timeout"
                if reason:
                    self._drop(client, reason)
            if shutdown and (not self._clients or now - shutdown >= self.config["drain_ms"] * 1000):
                break
