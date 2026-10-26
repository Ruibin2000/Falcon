#!/usr/bin/env python3
"""Run the real base5 broker, codec fixtures and independent dummy over TCP."""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import socket
import struct
import subprocess
import sys
import time
import traceback
sys.dont_write_bytecode = True

MANDATORY = (
    "owned_snapshot_and_precision", "nonfinite_unsupported_and_novalue",
    "malformed_mapping_identity_and_pointers", "bounded_ingress_overflow_and_complete_key",
    "concurrent_callback_queue_and_disable", "two_dummy_clients_and_exact_filters",
    "codec_rows_states_and_bitwise_equality", "registration_barrier_and_no_replay",
    "invalid_version_duplicate_and_filters", "malformed_and_oversized_frames",
    "split_coalesced_input_and_partial_output", "unregister_eof_and_reconnect",
    "full_registry_and_registration_timeout", "incomplete_frame_timeout", "idle_timeout",
    "quiet_source_and_ping", "slow_client_overflow_isolation", "pending_write_timeout",
    "ingress_drop_publication", "serialization_limit", "sigint_sigterm_restart",
    "unsupported_profile_and_bad_fixture", "bounded_shutdown_drain",
    "base5_subscription_configuration",
    "callback_finishing_after_registration_cutoff",
)


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.005)
    raise TimeoutError("Condition deadline exceeded")


class Suite:
    def __init__(self, args):
        self.args = args
        self.root = Path(args.output_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        spec = importlib.util.spec_from_file_location("dummy_kpm_client", args.dummy)
        self.client = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.client)
        self.fixtures = self.root / "fixtures"
        self.results = {}
        self.run_id = 0

    def command(self, name, command, expected=0, env=None):
        (self.root / f"{name}.command.json").write_text(json.dumps(command, indent=2) + "\n")
        result = subprocess.run(command, capture_output=True, timeout=60, env=env)
        (self.root / f"{name}.stdout.txt").write_bytes(result.stdout)
        (self.root / f"{name}.stderr.txt").write_bytes(result.stderr)
        (self.root / f"{name}.status.json").write_text(json.dumps({"exit_code": result.returncode}) + "\n")
        if expected is not None and result.returncode != expected:
            raise AssertionError(f"{name}: exit {result.returncode}, expected {expected}: {result.stderr.decode(errors='replace')}")
        return result

    @contextlib.contextmanager
    def broker(self, *, repeat=True, period=10, config=None, fixtures=None, expected=0):
        self.run_id += 1
        run = self.root / f"broker-{self.run_id:02d}"
        run.mkdir()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        cfg = {"port": port, "evidence_limit": 100000}
        cfg.update(config or {})
        (run / "config.json").write_text(json.dumps(cfg))
        command = [self.args.broker, "--source", "fixture", "--metric-profile", "base5",
                   "--fixture-dir", str(fixtures or self.fixtures), "--fixture-period-ms", str(period),
                   "--fixture-plugin", self.args.fixture_plugin, "--broker-config", str(run / "config.json"),
                   "--callback-evidence", str(run / "callback.jsonl")]
        if repeat:
            command.append("--fixture-repeat")
        (run / "command.json").write_text(json.dumps(command, indent=2))
        with open(run / "stdout.txt", "wb") as out, open(run / "stderr.txt", "wb") as err:
            process = subprocess.Popen(command, stdout=out, stderr=err)
            try:
                def ready():
                    if process.poll() is not None:
                        raise AssertionError(f"Broker exited before readiness: {(run / 'stderr.txt').read_text()}")
                    return "BROKER_READY" in (run / "stdout.txt").read_text()
                until(ready)
                yield port, run, process
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise AssertionError("Broker exceeded shutdown deadline")
                (run / "status.json").write_text(json.dumps({"exit_code": code}))
                if code != expected:
                    raise AssertionError(f"Broker exit {code}, expected {expected}: {(run / 'stderr.txt').read_text()}")

    def connect(self, port):
        return self.client.Connection("127.0.0.1", port)

    def register(self, c, app="test", filter_spec=None, request="reg", version=1):
        c.send({"version": version, "type": "register", "request_id": request, "app_id": app,
                "filter": filter_spec or {"mode": "all_du_ues"}})
        return c.receive(2)

    def kpm(self, c, timeout=3):
        deadline = time.monotonic() + timeout
        while True:
            obj = c.receive(deadline - time.monotonic())
            if obj.get("type") == "kpm":
                return obj

    def control(self, c, kind, timeout=3):
        deadline = time.monotonic() + timeout
        while True:
            obj = c.receive(deadline - time.monotonic())
            if obj.get("type") == kind:
                return obj

    def eof(self, c, timeout=2):
        deadline = time.monotonic() + timeout
        while True:
            try:
                c.receive(deadline - time.monotonic())
            except EOFError:
                return

    def exact_filter(self, du="1", ue="1007"):
        item = json.loads((self.fixtures / "manifest.json").read_text())["cases"][0]["link"]
        item["node"]["du_id"] = du
        item["ue"]["gnb_cu_ue_f1ap_id"] = ue
        return {"mode": "links", "links": [item]}

    def dummy_pair(self, period=5, reports=64):
        links = self.root / "du1-ue1007-links.json"
        links.write_text(json.dumps(self.exact_filter()["links"], indent=2))
        with self.broker(period=period) as (port, run, _):
            children = []
            try:
                for app, filter_args in (("dummy-all", ["--all-links"]), ("dummy-exact", ["--links-file", str(links)])):
                    command = [sys.executable, self.args.dummy, "--port", str(port), "--app-id", app, *filter_args,
                               "--reports", str(reports), "--timeout", "60", "--expected-profile", "base5",
                               "--jsonl-output", str(self.root / f"{app}.jsonl")]
                    (self.root / f"{app}.command.json").write_text(json.dumps(command))
                    out = open(self.root / f"{app}.stdout.txt", "wb")
                    err = open(self.root / f"{app}.stderr.txt", "wb")
                    children.append((app, subprocess.Popen(command, stdout=out, stderr=err), out, err))
                for app, process, out, err in children:
                    code = process.wait(timeout=65)
                    (self.root / f"{app}.status.json").write_text(json.dumps({"exit_code": code}))
                    assert code == 0, (app, code, (self.root / f"{app}.stderr.txt").read_text())
            finally:
                for _, process, out, err in children:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=5)
                    out.close()
                    err.close()
        self.pair_trace = run / "callback.jsonl"
        rows = [json.loads(s) for s in (self.root / "dummy-exact.jsonl").read_text().splitlines()]
        kpm = [r for r in rows if r["type"] == "kpm"]
        assert len(kpm) >= reports
        assert all(r["node"]["du_id"] == "1" and r["ue"]["gnb_cu_ue_f1ap_id"] == "1007" for r in kpm)

    def equality(self):
        traces = [json.loads(s) for s in self.pair_trace.read_text().splitlines()]
        index = {(r["instance"], r["report_seq"], r["mcc"], r["mnc"], r["gnb"], r["bits"], r["du"], r["ue"], r["sample_idx"]): r for r in traces}
        seen = set()
        checked = 0
        for app in ("dummy-all", "dummy-exact"):
            for line in (self.root / f"{app}.jsonl").read_text().splitlines():
                row = json.loads(line)
                if row["type"] != "kpm":
                    continue
                n, u = row["node"], row["ue"]
                t = index[(row["broker_instance_id"], row["report_seq"], n["mcc"], n["mnc"], n["gnb_id"], n["gnb_id_bits"], n["du_id"], u["gnb_cu_ue_f1ap_id"], row["sample_idx"])]
                assert row["header_time_us"] == t["header_us"] and row["received_at_unix_us"] == t["received_us"]
                assert row["incomplete"] is (None if t["incomplete"] < 0 else bool(t["incomplete"]))
                assert u["ran_ue_id"] == t["ran_ue"]
                seen.add((n["du_id"], u["gnb_cu_ue_f1ap_id"]))
                for name, v in zip(self.client.NAMES, t["values"]):
                    m = row["metrics"][name]
                    assert m["kpm_type"] == ("absent", "integer", "real", "noValue", "unsupported")[v["type"]]
                    assert m["status"] == ("ok", "not_reported", "no_value", "invalid")[v["state"]]
                    seen.add(m["status"])
                    if m["status"] == "ok":
                        if v["type"] == 2:
                            assert struct.pack(">d", m["value"]).hex() == v["real_bits"]
                        else:
                            assert m["value"] == v["integer"]
                        if m["value"] == 0:
                            seen.add("zero")
                    else:
                        assert m["value"] is None
                seen.add(("incomplete", row["incomplete"]))
                checked += 1
        assert {("1", "1007"), ("1", "2091"), ("2", "1007"), "zero", "no_value", "not_reported", ("incomplete", True)} <= seen, seen
        (self.root / "equality.json").write_text(json.dumps({"rows_compared": checked, "finite_reals": "IEEE-754 exact", "status": "passed"}, indent=2))

    def barrier(self):
        with self.broker(period=1) as (port, run, _):
            until(lambda: (run / "callback.jsonl").stat().st_size > 4000)
            c = self.connect(port)
            try:
                status = self.register(c)
                assert status["type"] == "registration_status" and status["status"] == "registered"
                assert int(status["registration_cutoff_report_seq"]) > 0
                previous = 0
                for _ in range(25):
                    previous = self.client.validate_row(self.kpm(c), status, previous)
            finally:
                c.close()

    def invalid_requests(self):
        with self.broker() as (port, _, _):
            a, b = self.connect(port), self.connect(port)
            try:
                assert self.register(a, "active")["status"] == "registered"
                assert self.register(b, "version", version=99)["error_code"] == "unsupported_version"
                assert self.register(b, "active")["error_code"] == "duplicate_app_id"
                assert self.register(a, "again")["error_code"] == "already_registered"
                bad = self.exact_filter()
                bad["links"][0]["node"]["du_id"] = "01"
                assert self.register(b, "bad", bad)["error_code"] == "invalid_request"
                for filter_spec in ({"mode": "links", "links": []}, {"mode": "links", "links": self.exact_filter()["links"] * 33}, {"mode": "unknown"}):
                    assert self.register(b, "bad", filter_spec)["error_code"] == "invalid_request"
                assert self.register(b, "idle", self.exact_filter(ue="4000"))["status"] == "registered"
                assert self.kpm(a)["type"] == "kpm"
            finally:
                a.close()
                b.close()

    def malformed(self):
        with self.broker() as (port, _, _):
            for data, code in ((b"{broken}\n", "invalid_request"), (b"x" * 8193 + b"\n", "frame_too_large"), (b"{\"request_id\":\"a\\u0000b\"}\n", "invalid_request"), (b"\xff\n", "invalid_request")):
                c = self.connect(port)
                try:
                    c.socket.setblocking(True)
                    c.socket.sendall(data)
                    c.socket.setblocking(False)
                    assert c.receive(2)["error_code"] == code
                    self.eof(c)
                finally:
                    c.close()

    def partial_io(self):
        with self.broker(period=30, config={"write_chunk": 7}) as (port, _, _):
            c = self.connect(port)
            try:
                req = json.dumps({"version": 1, "type": "register", "request_id": "split", "app_id": "split", "filter": {"mode": "all_du_ues"}}).encode() + b"\n"
                c.socket.setblocking(True)
                c.socket.sendall(req[:5])
                c.socket.sendall(req[5:30])
                c.socket.sendall(req[30:] + b'{"version":1,"type":"ping","request_id":"p1"}\n{"version":1,"type":"ping","request_id":"p2"}\n')
                c.socket.setblocking(False)
                status = c.receive(2)
                assert status["status"] == "registered"
                assert self.control(c, "pong")["request_id"] == "p1"
                assert self.control(c, "pong")["request_id"] == "p2"
                assert self.kpm(c)["metrics"]
            finally:
                c.close()

    def reconnect(self):
        with self.broker() as (port, _, _):
            c = self.connect(port)
            old = self.register(c, "repeat")
            self.kpm(c)
            c.send({"version": 1, "type": "unregister", "request_id": "u", "subscription_id": old["subscription_id"]})
            ack = self.control(c, "unregistration_status")
            assert ack["status"] == "unregistered"
            try:
                c.receive(2)
                raise AssertionError("Data after unregister acknowledgment")
            except EOFError:
                pass
            c.close()
            c = self.connect(port)
            fresh = self.register(c, "repeat")
            assert fresh["subscription_id"] != old["subscription_id"]
            c.close()
            c = self.connect(port)
            try:
                reply = until(lambda: (s if (s := self.register(c, "repeat"))["status"] == "registered" else None))
                assert reply["subscription_id"] != fresh["subscription_id"]
            finally:
                c.close()

    def full_registry(self):
        with self.broker(period=1000, config={"clients": 2, "registration_ms": 150}) as (port, _, _):
            a, b = self.connect(port), self.connect(port)
            try:
                a.send({"version": 1, "type": "ping", "request_id": "a"})
                assert a.receive(2)["type"] == "pong"
                b.send({"version": 1, "type": "ping", "request_id": "b"})
                assert b.receive(2)["type"] == "pong"
                c = self.connect(port)
                try:
                    assert c.receive(2)["error_code"] == "too_many_clients"
                finally:
                    c.close()
                self.eof(a)
                self.eof(b)
                c = self.connect(port)
                try:
                    assert self.register(c)["status"] == "registered"
                finally:
                    c.close()
            finally:
                a.close()
                b.close()

    def timeout_case(self, field, partial=False):
        with self.broker(period=1000, config={field: 80}) as (port, _, _):
            c = self.connect(port)
            try:
                assert self.register(c)["status"] == "registered"
                if partial:
                    c.socket.send(b'{"version":')
                self.eof(c)
            finally:
                c.close()

    def quiet(self):
        with self.broker(period=1, repeat=False) as (port, run, _):
            until(lambda: len((run / "callback.jsonl").read_text().splitlines()) == 16)
            c = self.connect(port)
            try:
                assert self.register(c)["data_state"] == "waiting_for_kpm"
                c.send({"version": 1, "type": "ping", "request_id": "quiet"})
                p = c.receive(2)
                assert p["type"] == "pong" and p["data_state"] == "waiting_for_kpm" and p["last_matching_kpm_age_ms"] is None
                try:
                    c.receive(0.15)
                    raise AssertionError("Quiet source fabricated KPM")
                except TimeoutError:
                    pass
            finally:
                c.close()

    def slow(self, timeout=False):
        config = {"test_stall_app": "slow", "output_frames": 16}
        if timeout:
            config["write_ms"] = 60
        with self.broker(period=100 if timeout else 5, config=config) as (port, run, _):
            slow, fast = self.connect(port), self.connect(port)
            try:
                assert self.register(slow, "slow")["status"] == "registered"
                status = self.register(fast, "fast")
                previous = 0
                for _ in range(32):
                    previous = self.client.validate_row(self.kpm(fast, 5), status, previous)
                self.eof(slow)
                reason = "write_timeout" if timeout else "output_overflow"
                assert f"app=slow reason={reason}" in (run / "stderr.txt").read_text()
                assert self.kpm(fast)["type"] == "kpm"
            finally:
                slow.close()
                fast.close()

    def ingress(self):
        with self.broker(period=1, config={"ingress_rows": 1}) as (port, _, _):
            c = self.connect(port)
            try:
                assert self.register(c)["status"] == "registered"
                until(lambda: int(self.kpm(c)["ingress_dropped_total"]) > 0)
            finally:
                c.close()

    def serialization(self):
        with self.broker(period=100, config={"frame_bytes": 900}, expected=1) as (port, run, _):
            c = self.connect(port)
            try:
                assert self.register(c)["status"] == "registered"
                self.eof(c)
                assert "serialization_limit" in (run / "stderr.txt").read_text()
            finally:
                c.close()

    def signals(self):
        instances = []
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.broker() as (port, _, process):
                c = self.connect(port)
                try:
                    instances.append(self.register(c)["broker_instance_id"])
                    self.kpm(c)
                    process.send_signal(sig)
                    self.eof(c)
                    assert process.wait(timeout=3) == 0
                finally:
                    c.close()
        assert instances[0] != instances[1]

    def bad_profile(self):
        result = self.command("bad-profile", [self.args.broker, "--source", "fixture", "--metric-profile", "rf7", "--fixture-dir", str(self.fixtures)], expected=2)
        assert b"Usage:" in result.stderr
        bad = self.root / "bad-fixtures"
        bad.mkdir()
        (bad / "manifest.json").write_text('{"profile":"rf7","cases":[]}')
        with self.broker(fixtures=bad, expected=1) as (_, _, process):
            assert process.wait(timeout=2) == 1

    def check_source_config(self):
        repo = Path(__file__).resolve().parents[2]
        for name, expected in (("xapp_du_kpm_base5.conf", 0), ("xapp_du_rf_metrics.conf", 1), ("xapp_ue_identity_expanded.conf", 1)):
            self.command(f"config-{name}", [self.args.broker, "--source", "e2", "--check-config", "-c", str(repo / "configs/flexric" / name)], expected=expected)

    def shutdown(self):
        with self.broker(period=50, config={"test_stall_app": "slow", "drain_ms": 120}) as (port, run, process):
            c = self.connect(port)
            try:
                assert self.register(c, "slow")["status"] == "registered"
                until(lambda: (run / "callback.jsonl").stat().st_size > 1000)
                before = time.monotonic()
                process.terminate()
                assert process.wait(timeout=2) == 0
                assert time.monotonic() - before < 1
                self.eof(c)
            finally:
                c.close()

    def execute(self):
        (self.root / "required-tests.json").write_text(json.dumps({"profile": "base5", "required": MANDATORY}, indent=2))
        self.command("fixture-generator", [self.args.fixture_generator, str(self.fixtures)])
        result = self.command("unit-test", [self.args.unit_test])
        for line in result.stdout.decode().splitlines():
            if not line.startswith('{'):
                continue
            row = json.loads(line)
            self.results[row["case"]] = row["status"]
        tests = (
            ("two_dummy_clients_and_exact_filters", self.dummy_pair),
            ("codec_rows_states_and_bitwise_equality", self.equality),
            ("registration_barrier_and_no_replay", self.barrier),
            ("invalid_version_duplicate_and_filters", self.invalid_requests),
            ("malformed_and_oversized_frames", self.malformed),
            ("split_coalesced_input_and_partial_output", self.partial_io),
            ("unregister_eof_and_reconnect", self.reconnect),
            ("full_registry_and_registration_timeout", self.full_registry),
            ("incomplete_frame_timeout", lambda: self.timeout_case("incomplete_ms", partial=True)),
            ("idle_timeout", lambda: self.timeout_case("idle_ms")),
            ("quiet_source_and_ping", self.quiet),
            ("slow_client_overflow_isolation", self.slow),
            ("pending_write_timeout", lambda: self.slow(timeout=True)),
            ("ingress_drop_publication", self.ingress),
            ("serialization_limit", self.serialization),
            ("sigint_sigterm_restart", self.signals),
            ("unsupported_profile_and_bad_fixture", self.bad_profile),
            ("bounded_shutdown_drain", self.shutdown),
            ("base5_subscription_configuration", self.check_source_config),
        )
        for name, test in tests:
            try:
                test()
                self.results[name] = "passed"
                print(f"PASS {name}", flush=True)
            except Exception:
                self.results[name] = "failed"
                (self.root / f"{name}.failure.txt").write_text(traceback.format_exc())
                print(f"FAIL {name}: {traceback.format_exc()}", file=sys.stderr, flush=True)
        passed = all(self.results.get(name) == "passed" for name in MANDATORY)
        hashes = {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.fixtures.iterdir() if p.is_file()}
        hashes.update({str(Path(p).resolve()): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (self.args.broker, self.args.unit_test, self.args.fixture_generator, self.args.dummy, self.args.fixture_plugin, __file__)})
        (self.root / "sha256.json").write_text(json.dumps(hashes, indent=2))
        summary = {"profile": "base5", "data_source": "fixture", "required": len(MANDATORY),
                   "passed": sum(self.results.get(n) == "passed" for n in MANDATORY), "skipped": 0,
                   "results": self.results, "status": "passed" if passed else "failed", "live_acceptance": "pending"}
        (self.root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("broker", "unit-test", "fixture-generator", "dummy", "output-dir"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--metric-profile", choices=["base5"], default="base5")
    parser.add_argument("--fixture-plugin", default="/usr/local/lib/flexric/libkpm_sm.so")
    args = parser.parse_args()
    return Suite(args).execute()


if __name__ == "__main__":
    sys.exit(main())
