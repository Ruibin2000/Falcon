"""Production mapper -> real TCP publisher -> independent TXT subscriber."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import select
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_identity import ROOT, config, core_event
from test_scoped_identity import scoped_cu
from test_expansion import expanded_event
from mapping import Mapper
from metrics import EXPANDED
from subscription import Publisher, configuration
from subscription_feed import BoundReportFeed
from subscription_protocol import PROFILE, VERSION, decode, encode, link_key, mono_us
from dummy_subscriber import Connection, TextWriter


def until(predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.002)
    raise TimeoutError("test condition deadline")


@contextmanager
def service(settings=None):
    publisher = Publisher(dict(port=0, **(settings or {})), source="fixture").start()
    try:
        yield publisher
    finally:
        publisher.close()


def request(c, kind, **fields):
    c.send(dict(version=VERSION, type=kind, request_id="r", **fields))


def register(publisher, app="app", filter_spec=None):
    c = Connection("127.0.0.1", publisher.port)
    request(c, "register", app_id=app, expected_profile=PROFILE,
            filter=filter_spec or {"mode": "all_matched_links"})
    reply, _, _ = c.receive(2)
    if reply.get("status") != "registered":
        c.close()
        raise AssertionError(reply)
    return c, reply


def message(c, kind, seconds=2):
    deadline = time.monotonic() + seconds
    while True:
        obj, received, unix = c.receive(deadline - time.monotonic())
        if obj["type"] == kind:
            return obj


def eof(c):
    deadline = time.monotonic() + 2
    while True:
        try:
            c.receive(deadline - time.monotonic())
        except EOFError:
            return


def incoming(feed, event):
    event = copy.deepcopy(event)
    now = mono_us()
    event.update(received_at_mono_us=now, callback_at_mono_us=str(now),
                 source_instance_id="test-source", source_indication_seq="1")
    return feed.ingest(event)


def ready(publisher, ttl=3):
    cfg = config()
    cfg["source_ttl_s"] = ttl
    feed = BoundReportFeed(Mapper(cfg), publisher)
    incoming(feed, core_event())
    incoming(feed, scoped_cu())
    return feed


def du(du_id=1, stamp=11_000_000):
    event = expanded_event(du_id)
    event["rows"][0]["ue"]["gnb_cu_ue_f1ap_id"] = "1"
    event.update(received_at_us=stamp + 1000, header_time_us=str(stamp))
    return event


def exact(du_id="1", ue="1"):
    node = copy.deepcopy(config()["du_nodes"][int(du_id)-1])
    return {"mode": "links", "links": [{"node": node, "ue": {"id_type": "gnb_du", "gnb_cu_ue_f1ap_id": ue}}]}


class SubscriptionTests(unittest.TestCase):
    def test_native_callback_clock_has_same_python_process_origin(self):
        import os
        collector = os.environ.get("FALCON_IDENTITY_COLLECTOR", "/tmp/falcon-xapp-ue-identity-subscriptions")
        if not Path(collector).is_file():
            self.skipTest("build the subscription collector; verify_subscriptions.py requires this gate without skips")
        before = mono_us()
        native = int(subprocess.check_output([collector, "--check-clock"], text=True, timeout=5))
        after = mono_us()
        self.assertLessEqual(before, native)
        self.assertLessEqual(native, after)

    def test_cli_rejects_wrong_source_period_before_opening_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"settings.json").write_text('{"port":0}')
            source = (ROOT/"configs/flexric/xapp_ue_identity_expanded.conf").read_text().replace('time = 1000', 'time = 200')
            (root/"wrong.conf").write_text(source)
            command = [sys.executable, "-B", str(ROOT/"scripts/ue_identity/xapp_ue_identity.py"),
                "--publish-config", str(root/"settings.json"), "--e2-config", str(root/"wrong.conf"), "--duration", "0"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires CU identity at 1000 ms", result.stderr)
            self.assertEqual(result.stdout, "")

    def test_ambiguous_internal_json_is_rejected_without_silent_key_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"settings.json").write_text('{"port":0}')
            (root/"bad.ndjson").write_text('{"kind":"core_snapshot","kind":"core_error","received_at_us":10000000}\n')
            command = [sys.executable, "-B", str(ROOT/"scripts/ue_identity/xapp_ue_identity.py"),
                "--publish-config", str(root/"settings.json"), "--duration", "1", "--replay", str(root/"bad.ndjson"),
                "--publisher-summary", str(root/"summary.json")]
            result = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            summary = json.loads((root/"summary.json").read_text())
            self.assertIn("duplicate JSON field", summary["failures"])
            self.assertEqual(summary["counters"].get("reports_queued", 0), 0)

    def test_source_eof_preserves_final_queued_report_before_state_notice(self):
        with service() as pub:
            c, _ = register(pub)
            entered, release = threading.Event(), threading.Event()
            original = pub._publish

            def paused_publish():
                if pub.stats()["ingress_depth"]:
                    entered.set()
                    if not release.wait(2):
                        raise TimeoutError("EOF test barrier")
                original()

            try:
                with mock.patch.object(pub, "_publish", side_effect=paused_publish):
                    feed = ready(pub)
                    incoming(feed, du())
                    self.assertTrue(entered.wait(2))
                    pub.source_unavailable("test EOF")
                    release.set()
                    output = c.receive(2)[0]
                    self.assertEqual(output["type"], "kpm_report")
                    state = message(c, "binding_state")
                    self.assertEqual(state["data_state"], "source_unavailable")
                    self.assertEqual(output["report"]["ue_ipv4"], "10.45.0.10")
            finally:
                release.set()
                c.close()

    def test_multiple_ues_on_one_du_and_ip_change_snapshot_revision(self):
        with service() as pub:
            c, _ = register(pub)
            try:
                feed = ready(pub)
                core = core_event()
                third = copy.deepcopy(core["amf"][0])
                third.update(supi="imsi-001010000000103")
                third["gnb"].update(amf_ue_ngap_id=9003, ran_ue_ngap_id=303)
                core["amf"].append(third)
                third = copy.deepcopy(core["smf"][0])
                third.update(supi="imsi-001010000000103")
                third["pdu"][0]["ipv4"] = "10.45.0.33"
                core["smf"].append(third)
                incoming(feed, core)
                cu = scoped_cu()
                third = copy.deepcopy(cu["rows"][0])
                third["ue"].update(amf_ue_ngap_id="9003", f1ap_ids=["2091"], ran_ue_id_hex=f"{(1<<28)|43:016x}")
                cu["rows"].append(third)
                incoming(feed, cu)
                event = du()
                third = copy.deepcopy(event["rows"][0])
                third["ue"]["gnb_cu_ue_f1ap_id"] = "2091"
                event["rows"].append(third)
                incoming(feed, event)
                first, second = message(c, "kpm_report"), message(c, "kpm_report")
                self.assertEqual((first["report"]["ue_ipv4"], second["report"]["ue_ipv4"]), ("10.45.0.10", "10.45.0.33"))
                core["received_at_us"] = 11_100_000
                core["smf"][0]["pdu"][0]["ipv4"] = "10.45.0.99"
                incoming(feed, core)
                incoming(feed, du(stamp=11_200_000))
                changed = message(c, "kpm_report")
                self.assertEqual(changed["report"]["ue_ipv4"], "10.45.0.99")
                self.assertGreater(int(changed["binding_revision"]), int(first["binding_revision"]))
                self.assertEqual(first["report"]["ue_ipv4"], "10.45.0.10")
            finally:
                c.close()

    def test_27_metrics_full_bindings_duplicate_f1_and_exact_filter(self):
        with service() as pub:
            all_c, _ = register(pub, "all")
            one, _ = register(pub, "one", exact())
            try:
                feed = ready(pub)
                for du_id in (1, 2):
                    original = incoming(feed, du(du_id))[0]
                    obj = message(all_c, "kpm_report")
                    self.assertEqual(obj["report"], original)
                    self.assertEqual(obj["report"]["binding"]["serving_du_id"], str(du_id))
                    self.assertEqual(obj["report"]["ue_ipv4"], f"10.{44+du_id}.0.10")
                    self.assertEqual(len(obj["report"]["row"]["metrics"]), 27)
                    if du_id == 1:
                        self.assertEqual(message(one, "kpm_report")["report"], original)
                request(one, "ping")
                while True:
                    reply = one.receive(2)[0]
                    self.assertNotEqual(reply["type"], "kpm_report")
                    if reply["type"] == "pong":
                        break
            finally:
                all_c.close()
                one.close()

    def test_owned_report_and_bitwise_real_zero_novalue_uint32(self):
        with service() as pub:
            c, _ = register(pub)
            try:
                feed = ready(pub)
                event = du()
                metrics = event["rows"][0]["metrics"]
                metrics["PUSCH.SNR.dB"]["value"] = -0.0
                metrics["PUSCH.RSRP.dBFS"]["value"] = -13.123456789012345
                metrics["CQI"] = {"type": "no_value", "value": None}
                record = incoming(feed, event)[0]
                expected = copy.deepcopy(record)
                record["binding"]["supi"] = "overwritten"
                record["row"]["metrics"].clear()
                output = message(c, "kpm_report")["report"]
                self.assertEqual(output, expected)
                for name in ("PUSCH.SNR.dB", "PUSCH.RSRP.dBFS"):
                    self.assertEqual(struct.pack(">d", output["row"]["metrics"][name]["value"]),
                                     struct.pack(">d", expected["row"]["metrics"][name]["value"]))
                self.assertEqual(output["row"]["metrics"]["UL.BSR.Bytes"]["value"], 2**32-1)
            finally:
                c.close()

    def test_registration_barrier_excludes_callback_finishing_late(self):
        with service() as pub:
            feed = ready(pub)
            record = incoming(feed, du())[0]
            callback = mono_us()
            c, status = register(pub)
            try:
                record["sequence"] += 1
                self.assertTrue(pub.submit(record, callback_mono_us=callback, ready_mono_us=mono_us(), valid_until_mono_us=mono_us()+1_000_000))
                request(c, "ping")
                while True:
                    reply = c.receive(2)[0]
                    self.assertNotEqual(reply["type"], "kpm_report")
                    if reply["type"] == "pong":
                        break
                incoming(feed, du(stamp=11_100_000))
                output = message(c, "kpm_report")
                self.assertGreater(int(output["callback_at_mono_us"]), int(status["cutoff_at_mono_us"]))
                self.assertEqual(output["delivery_seq"], "1")
            finally:
                c.close()

    def test_binding_release_and_core_error_do_not_become_fresh_data(self):
        with service() as pub:
            c, _ = register(pub)
            try:
                feed = ready(pub)
                incoming(feed, du())
                message(c, "kpm_report")
                release = scoped_cu(stamp=11_100_000)
                release["rows"][0]["metrics"]["FALCON.UE.RRCState"]["value"] = 0
                incoming(feed, release)
                incoming(feed, du(stamp=11_200_000))
                incoming(feed, du(2, 11_200_000))
                output = message(c, "kpm_report")
                self.assertEqual(output["report"]["node"]["du_id"], "2")
                incoming(feed, dict(kind="core_error", reason="test timeout", received_at_us=11_300_000))
                request(c, "ping")
                self.assertEqual(message(c, "pong")["data_state"], "source_unavailable")
            finally:
                c.close()

    def test_expiry_updates_data_state_without_new_du_rows(self):
        with service() as pub:
            c, _ = register(pub)
            try:
                feed = ready(pub, ttl=0.2)
                event = du(stamp=11_000_000)
                incoming(feed, event)
                message(c, "kpm_report")
                until(lambda: mono_us() > next(iter(pub._states.values()))["until"])
                request(c, "ping")
                reply = message(c, "pong")
                self.assertIn(reply["data_state"], ("binding_invalid", "source_unavailable"))
                self.assertEqual(pub.stats()["reports_queued"], 1)
            finally:
                c.close()

    def test_invalid_profile_mapping_nonfinite_missing_metric_are_counted(self):
        with service() as pub:
            feed = ready(pub)
            for transform in (lambda r: r["row"]["metrics"].pop("CQI"),
                              lambda r: r["row"]["metrics"]["PUSCH.SNR.dB"].update(value=float("nan")),
                              lambda r: r["row"].update(granularity_ms=1000)):
                record = incoming(feed, du())[0]
                transform(record)
                self.assertFalse(pub.submit(record, callback_mono_us=mono_us(), ready_mono_us=mono_us(), valid_until_mono_us=mono_us()+1_000_000))
            self.assertEqual(pub.stats()["invalid_reports"], 3)

    def test_duplicate_invalid_requests_and_oversized_frames(self):
        with service() as pub:
            active, _ = register(pub, "dup")
            c = Connection("127.0.0.1", pub.port)
            try:
                request(c, "register", app_id="dup", expected_profile=PROFILE, filter={"mode": "all_matched_links"})
                self.assertEqual(c.receive(2)[0]["error_code"], "duplicate_app_id")
                request(c, "register", app_id="other", expected_profile="base5", filter={"mode": "all_matched_links"})
                self.assertEqual(c.receive(2)[0]["error_code"], "unsupported_profile")
                request(active, "register", app_id="dup", expected_profile=PROFILE, filter={"mode": "all_matched_links"})
                self.assertEqual(message(active, "registration_status")["error_code"], "already_registered")
            finally:
                active.close()
                c.close()
            for raw, expected in ((b'{"version":2,"version":1}\n', "invalid_request"), (b'\xff\n', "invalid_request"), (b'x'*8193+b'\n', "frame_too_large")):
                c = Connection("127.0.0.1", pub.port)
                try:
                    c.socket.setblocking(True)
                    c.socket.sendall(raw)
                    c.socket.setblocking(False)
                    self.assertEqual(c.receive(2)[0]["error_code"], expected)
                    eof(c)
                finally:
                    c.close()

    def test_partial_frames_unregister_ack_and_twenty_reconnects(self):
        with service({"write_chunk": 7}) as pub:
            c = Connection("127.0.0.1", pub.port)
            try:
                raw = encode(dict(version=2, type="register", request_id="r", app_id="partial", expected_profile=PROFILE,
                                  filter={"mode": "all_matched_links"}))
                c.socket.setblocking(True)
                c.socket.sendall(raw[:7])
                c.socket.sendall(raw[7:] + encode(dict(version=2, type="ping", request_id="p")))
                c.socket.setblocking(False)
                status = c.receive(2)[0]
                self.assertEqual(status["status"], "registered")
                self.assertEqual(message(c, "pong")["request_id"], "p")
                feed = ready(pub)
                incoming(feed, du())
                request(c, "unregister", subscription_id=status["subscription_id"])
                message(c, "unregistration_status")
                with self.assertRaises(EOFError):
                    c.receive(2)
            finally:
                c.close()
            ids = set()
            for _ in range(20):
                c, status = register(pub, "repeated")
                ids.add(status["subscription_id"])
                c.close()
                until(lambda: pub.stats().get("active_registrations", 0) == 0)
            self.assertEqual(len(ids), 20)

    def test_connection_registration_incomplete_and_idle_limits(self):
        for limits, registered, partial in (({"registration_ms": 60}, False, False),
                                            ({"incomplete_ms": 60}, True, True),
                                            ({"idle_ms": 60}, True, False)):
            with service(limits) as pub:
                c = register(pub)[0] if registered else Connection("127.0.0.1", pub.port)
                try:
                    if partial:
                        c.socket.send(b'{"version":')
                    eof(c)
                finally:
                    c.close()
        with service({"clients": 1}) as pub:
            c, _ = register(pub)
            second = Connection("127.0.0.1", pub.port)
            try:
                self.assertEqual(second.receive(2)[0]["error_code"], "too_many_clients")
            finally:
                c.close()
                second.close()

    def test_ingress_bounded_and_no_client_acquisition_continues(self):
        # Hold the worker stopped so overflow cannot depend on TCP buffering.
        pub = Publisher(dict(port=0, ingress_reports=1), source="fixture")
        try:
            feed = ready(pub)
            for _ in range(4):
                incoming(feed, du())
            self.assertEqual(pub.stats()["ingress_depth"], 1)
            self.assertEqual(pub.stats()["ingress_dropped"], 3)
            pub.start()
            until(lambda: pub.stats()["ingress_depth"] == 0)
            c, _ = register(pub)
            try:
                incoming(feed, du(stamp=11_100_000))
                self.assertEqual(message(c, "kpm_report")["ingress_dropped_total"], "3")
            finally:
                c.close()
        finally:
            pub.close()

    def test_slow_client_isolated_and_write_timeout(self):
        for timeout in (False, True):
            settings = dict(test_stall_app="slow", output_frames=8)
            if timeout:
                settings["write_ms"] = 60
            with service(settings) as pub:
                slow, _ = register(pub, "slow")
                fast, _ = register(pub, "fast")
                try:
                    feed = ready(pub)
                    for i in range(18 if not timeout else 2):
                        incoming(feed, du(stamp=11_000_000+i*1000))
                        message(fast, "kpm_report")
                    eof(slow)
                    expected = "disconnect_write_timeout" if timeout else "disconnect_output_overflow"
                    self.assertGreater(pub.stats().get(expected, 0), 0)
                    incoming(feed, du(stamp=11_200_000))
                    self.assertEqual(message(fast, "kpm_report")["report"]["node"]["du_id"], "1")
                finally:
                    slow.close()
                    fast.close()

    def test_quiet_source_ping_no_fake_reports_and_shutdown_bound(self):
        with service() as pub:
            c, _ = register(pub)
            try:
                request(c, "ping")
                self.assertEqual(message(c, "pong")["data_state"], "waiting_for_match")
                with self.assertRaises(TimeoutError):
                    c.receive(0.05)
                pub.source_unavailable("fixture stopped")
                request(c, "ping")
                self.assertEqual(message(c, "pong")["data_state"], "source_unavailable")
                self.assertEqual(pub.stats().get("reports_queued", 0), 0)
            finally:
                c.close()
        with service(dict(test_stall_app="slow", drain_ms=60)) as pub:
            c, _ = register(pub, "slow")
            try:
                feed = ready(pub)
                incoming(feed, du())
                until(lambda: pub.stats().get("reports_queued", 0) == 1)
                start = time.monotonic()
                pub.close()
                self.assertLess(time.monotonic() - start, 1)
            finally:
                c.close()

    def test_live_rejects_fixture_io_adapters_and_unsafe_bind(self):
        for values in (dict(write_chunk=7), dict(test_stall_app="x"), dict(bind="0.0.0.0"), dict(idle_ms=-1), dict(clients=True)):
            with self.assertRaises(ValueError):
                configuration(values)

    def test_txt_writer_failure_and_overflow_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = mock.Mock()
            fake.write.side_effect = [None, OSError("disk failed")]
            with mock.patch.object(Path, "open", return_value=fake):
                writer = TextWriter(Path(tmp)/"failed.txt")
            writer.offer(dict(type="kpm_report", data_source="fixture", subscription_id="s", report_seq="1", delivery_seq="1", link_id="l", binding_revision="1", report={}), mono_us(), 0)
            with self.assertRaises(RuntimeError):
                writer.close()
            writer = TextWriter(Path(tmp)/"slow.txt", limit=1, byte_limit=1)
            try:
                with self.assertRaises(RuntimeError):
                    writer.offer(dict(type="binding_state"), mono_us(), 0)
            finally:
                writer.close()

    def test_slow_dummy_txt_writer_fails_without_affecting_healthy_app(self):
        with tempfile.TemporaryDirectory() as temporary, service() as pub:
            root = Path(temporary)
            command = [sys.executable, "-B", str(ROOT/"scripts/ue_identity/dummy_subscriber.py"),
                "--port", str(pub.port), "--app-id", "slow-file", "--all-links", "--reports", "100", "--timeout", "5",
                "--text-output", str(root/"slow.txt"), "--summary", str(root/"summary.json"),
                "--writer-queue-reports", "4", "--test-writer-delay-ms", "100"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            fast, _ = register(pub, "healthy")
            try:
                until(lambda: pub.stats().get("active_registrations") == 2)
                feed = ready(pub)
                for index in range(30):
                    incoming(feed, du(stamp=11_000_000+index*1000))
                    message(fast, "kpm_report")
                out, err = process.communicate(timeout=5)
                self.assertNotEqual(process.returncode, 0, (out, err))
                summary = json.loads((root/"summary.json").read_text())
                self.assertIn("queue overflow", summary["error"])
                incoming(feed, du(stamp=11_100_000))
                self.assertEqual(message(fast, "kpm_report")["report"]["ue_ipv4"], "10.45.0.10")
            finally:
                fast.close()
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def test_serialization_limit_closes_consumer_without_truncated_json(self):
        with service() as pub:
            c, _ = register(pub)
            try:
                feed = ready(pub)
                record = incoming(feed, du())[0]
                message(c, "kpm_report")
                record["oversized_metadata"] = "x"*65536
                self.assertTrue(pub.submit(record, callback_mono_us=mono_us(), ready_mono_us=mono_us(), valid_until_mono_us=mono_us()+1_000_000))
                eof(c)
                self.assertEqual(pub.stats()["serialization_errors"], 1)
            finally:
                c.close()

    def test_two_actual_dummy_processes_persist_txt_and_timing(self):
        evidence_root = __import__("os").environ.get("FALCON_SUBSCRIPTION_EVIDENCE")
        directory = tempfile.TemporaryDirectory() if not evidence_root else None
        root = Path(evidence_root) if evidence_root else Path(directory.name)
        root.mkdir(parents=True, exist_ok=True)
        with service() as pub:
            links = root/"exact-links.json"
            links.write_text(json.dumps(exact()["links"]))
            processes = []
            originals = {}
            try:
                for app, filters in (("dummy-all", ["--all-links"]), ("dummy-exact", ["--links-file", str(links)])):
                    command = [sys.executable, "-B", str(ROOT/"scripts/ue_identity/dummy_subscriber.py"),
                               "--port", str(pub.port), "--app-id", app, *filters, "--reports", "12", "--timeout", "10",
                               "--text-output", str(root/f"{app}.txt"), "--receipts-output", str(root/f"{app}.jsonl"),
                               "--summary", str(root/f"{app}.summary.json"), "--check-timing"]
                    (root/f"{app}.command.json").write_text(json.dumps(command, indent=2))
                    out = (root/f"{app}.stdout.txt").open("w")
                    err = (root/f"{app}.stderr.txt").open("w")
                    processes.append((app, subprocess.Popen(command, stdout=out, stderr=err), out, err))
                until(lambda: pub.stats().get("active_registrations") == 2)
                feed = ready(pub)
                for index in range(16):
                    for du_id in (1, 2):
                        record = incoming(feed, du(du_id, 11_000_000 + index*100_000))[0]
                        originals[record["sequence"]] = copy.deepcopy(record)
                    time.sleep(0.1)
                for app, process, _, _ in processes:
                    self.assertEqual(process.wait(timeout=5), 0, (app, (root/f"{app}.stderr.txt").read_text(), (root/f"{app}.stdout.txt").read_text()))
                    summary = json.loads((root/f"{app}.summary.json").read_text())
                    self.assertEqual(summary["reports_received"], summary["text_reports_written"])
                    self.assertTrue(summary["unregistered"])
                    receipts = [json.loads(line) for line in (root/f"{app}.jsonl").read_text().splitlines()]
                    rows = [r for r in receipts if r["type"] == "kpm_report"]
                    self.assertGreaterEqual(len(rows), 12)
                    for row in rows:
                        original = originals[int(row["report_seq"])]
                        self.assertEqual(row["report"], original)
                        for name, metric in original["row"]["metrics"].items():
                            if metric["type"] == "real":
                                self.assertEqual(struct.pack(">d", metric["value"]), struct.pack(">d", row["report"]["row"]["metrics"][name]["value"]))
                    text = (root/f"{app}.txt").read_text()
                    self.assertEqual(text.count("\nrecord="), len(rows))
                    self.assertIn("UE_IPv4=10.45.0.10", text)
                    blocks = {int(block.split("report_seq=")[1].split()[0]): block for block in text.split("subscription=")[1:]}
                    for row in rows:
                        block = blocks[int(row["report_seq"])]
                        source = originals[int(row["report_seq"])]
                        self.assertIn(f"SUPI={source['binding']['supi']}", block)
                        self.assertIn(f"UE_IPv4={source['ue_ipv4']}", block)
                        for name, metric in source["row"]["metrics"].items():
                            value = "no_value" if metric["type"] == "no_value" else json.dumps(metric["value"])
                            self.assertIn(f"{name} = {value} [{metric['unit']}] ({metric['type']})", block)
                    if app == "dummy-exact":
                        self.assertNotIn("10.46.0.10", text)
                        self.assertTrue(all(r["report"]["node"]["du_id"] == "1" for r in rows))
                (root/"source-records.json").write_text(json.dumps(originals, allow_nan=False, indent=2))
                (root/"publisher.json").write_text(json.dumps(pub.stats(), indent=2))
            finally:
                for _, process, out, err in processes:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=5)
                    out.close()
                    err.close()
                if directory:
                    directory.cleanup()

    def test_real_coordinator_cli_fixture_replay_and_no_txt_sink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = root/"settings.json"
            settings.write_text('{"port":0}')
            # Generate synthetic Core/CU/27-metric input without local experiment data.
            events = [core_event(), scoped_cu()]
            for index in range(20):
                events.extend(du(du_id, 11_000_000 + index*100_000) for du_id in (1, 2))
            replay = root/"inputs.ndjson"
            replay.write_text("".join(json.dumps(event) + "\n" for event in events))
            command = [sys.executable, "-B", str(ROOT/"scripts/ue_identity/xapp_ue_identity.py"),
                       "--publish-config", str(settings), "--duration", "0", "--replay-speed", "2",
                       "--replay", str(replay),
                       "--publisher-summary", str(root/"publisher.json")]
            with (root/"service.err").open("w") as err:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=err, text=True)
                try:
                    self.assertTrue(select.select([process.stdout], [], [], 5)[0])
                    line = process.stdout.readline()
                    self.assertTrue(line.startswith("SUBSCRIPTION_READY"), (line, (root/"service.err").read_text()))
                    port = int(line.split("port=")[1].split()[0])
                    dummy = subprocess.run([sys.executable, "-B", str(ROOT/"scripts/ue_identity/dummy_subscriber.py"),
                        "--port", str(port), "--app-id", "cli", "--all-links", "--reports", "10", "--timeout", "10",
                        "--text-output", str(root/"dummy.txt")], capture_output=True, text=True, timeout=15)
                    self.assertEqual(dummy.returncode, 0, (dummy.stderr, dummy.stdout, (root/"service.err").read_text()))
                    text = (root/"dummy.txt").read_text()
                    self.assertEqual(text.count("\nrecord="), 10)
                    self.assertIn("UE_IPv4=10.45.0.10", text)
                    self.assertIn("UE_IPv4=10.46.0.10", text)
                    process.terminate()
                    self.assertEqual(process.wait(timeout=5), 0, (root/"service.err").read_text())
                    self.assertEqual(process.stdout.read(), "")  # No per-report stdout/TXT in publisher mode.
                    self.assertEqual(json.loads((root/"publisher.json").read_text())["status"], "passed")
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    process.stdout.close()


if __name__ == "__main__":
    unittest.main()
