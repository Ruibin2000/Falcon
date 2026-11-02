"""Real PTYs/process groups with fake components; no Docker, systemd or radios."""

import importlib.util
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("spark_auto", ROOT / "scripts/spark_auto.py")
AUTO = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = AUTO
spec.loader.exec_module(AUTO)


FAKE = r'''
import json,os,select,signal,subprocess,sys,time
from pathlib import Path
role,root,crash,missing,hang,grandchild=sys.argv[1:]
root=Path(root)
def record(kind,**fields):
 with (root/'events.jsonl').open('a') as f:f.write(json.dumps(dict(role=role,kind=kind,**fields))+'\n')
record('started',pid=os.getpid(),tty=os.isatty(0),controlling=os.tcgetpgrp(0)==os.getpgrp())
def stop(number,frame):
 if hang=='yes':return
 record('stop',signal=number)
 if role=='xapp':
  for _ in range(3):print('[xApp]: E42 SUBSCRIPTION DELETE RESPONSE rx',flush=True)
  (root/'publisher.json').write_text(json.dumps(dict(status='passed',counters=dict(active_connections=0,active_registrations=0))))
 sys.exit(0)
signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
if grandchild=='yes':
 code="import os,signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); signal.signal(signal.SIGINT,signal.SIG_IGN); signal.signal(signal.SIGHUP,signal.SIG_IGN); Path(__import__('sys').argv[1]).write_text(str(os.getpid())); time.sleep(60)"
 subprocess.Popen([sys.executable,'-c',code,str(root/'grandchild.pid')])
if missing!='yes':print('READY '+role,flush=True)
started=time.monotonic()
while True:
 if crash!='none' and time.monotonic()-started>float(crash):record('crash');sys.exit(7)
 if role=='du2' and select.select([sys.stdin],[],[],0.02)[0]:
  data=os.read(0,4096).decode()
  for part in data.split(';'):
   line=part.replace('\n','').strip()
   if line:
    record('input',line=line)
    print('Tx gain set to 60 dB for port 0.',flush=True)
 else:time.sleep(0.01)
'''


def settings():
    return AUTO.parser().parse_args([
        "--startup-timeout", "2", "--stop-timeout", "0.3",
        "--health-interval", "0.1", "--health-failures", "3", "--no-input"])


class FakeHost:
    def __init__(self, root, fail_health=0, recover=False):
        self.root = Path(root)
        self.calls = []
        self.fail_health = fail_health
        self.recover = recover
        self.health_calls = 0

    def call(self, method):
        self.calls.append(method)
        with (self.root / "host.jsonl").open("a") as stream:
            stream.write(json.dumps(method) + "\n")

    def database_start(self):
        self.call("database_start")

    def database_check(self, subscribers=False):
        if not subscribers:
            self.health_calls += 1
            if self.fail_health and (not self.recover or self.health_calls <= self.fail_health):
                raise AUTO.Fault("database probe failed")

    def core_start(self):
        self.call("core_start")

    def core_check(self):
        pass

    def transport_check(self, ready):
        pass

    def core_stop(self):
        self.call("core_stop")

    def core_stopped(self):
        return True

    def core_kill(self):
        self.call("core_kill")


def plan(root, crash=None, missing=None, hang=None, grandchild=False):
    root = Path(root)
    script = root / "component.py"
    script.write_text(FAKE)
    return [AUTO.Service(name, [sys.executable, "-u", str(script), name, str(root),
                "0.9" if crash == name else "none", "yes" if missing == name else "no",
                "yes" if hang == name else "no", "yes" if grandchild and name == "xapp" else "no"],
                root, ("READY " + name,)) for name in AUTO.ORDER]


def wait_for(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("offline fixture deadline")


class SupervisorTests(unittest.TestCase):
    def run_case(self, root, *, crash=None, missing=None, hang=None, grandchild=False,
                 health=0, recover=False, action=None):
        host = FakeHost(root, health, recover)
        args = settings()
        if missing:
            args.startup_timeout = 0.2
        sup = AUTO.Supervisor(args, root, host)
        worker_errors = []
        worker = None
        if not crash and not missing and not (health and not recover):
            def operator():
                try:
                    wait_for(lambda: sup.phase == "running")
                    time.sleep(0.3 if recover else 0.1)
                    if action:
                        action(sup)
                    sup.request_stop("offline operator")
                except BaseException as exc:
                    worker_errors.append(exc)
                    sup.request_stop("test worker failed")
            worker = threading.Thread(target=operator)
            worker.start()
        result = sup.execute(plan(root, crash=crash, missing=missing, hang=hang, grandchild=grandchild), interactive=False)
        if worker:
            worker.join(timeout=2)
        self.assertEqual(worker_errors, [])
        self.assertEqual(host.calls, ["database_start", "core_start", "core_stop"])
        for child in sup.children.values():
            self.assertIsNotNone(child.process.poll())
            self.assertFalse(AUTO.group_alive(child.process.pid))
            self.assertFalse(child.thread.is_alive())
        return result, sup, host

    def test_order_real_controlling_ptys_and_normal_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            result, sup, host = self.run_case(root)
            self.assertEqual(result, 0, sup.cleanup_errors)
            events = [json.loads(line) for line in (Path(root) / "events.jsonl").read_text().splitlines()]
            self.assertEqual([e["role"] for e in events if e["kind"] == "started"], list(AUTO.ORDER))
            self.assertEqual([e["role"] for e in events if e["kind"] == "stop"], ["xapp", "du2", "du1", "cu", "ric"])
            self.assertTrue(all(e["tty"] and e["controlling"] for e in events if e["kind"] == "started"))
            state = json.loads((Path(root) / "status.json").read_text())
            self.assertEqual(state["phase"], "stopped")
            self.assertTrue(state["mongo_preserved"])
            self.assertEqual(sup.children["xapp"].deletions, 3)

    def test_every_component_crash_stops_all_other_components(self):
        for name in AUTO.ORDER:
            with self.subTest(component=name), tempfile.TemporaryDirectory() as root:
                result, sup, host = self.run_case(root, crash=name)
                self.assertEqual(result, 1)
                self.assertIn(name + " exited unexpectedly", sup.reason)
                self.assertEqual(set(sup.children), set(AUTO.ORDER))

    def test_startup_timeout_stops_prior_components_and_core(self):
        with tempfile.TemporaryDirectory() as root:
            result, sup, host = self.run_case(root, missing="du2")
            self.assertEqual(result, 1)
            self.assertIn("du2 startup timed out", sup.reason)
            self.assertNotIn("xapp", sup.children)

    def test_du2_commands_only_and_invalid_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            def action(sup):
                for invalid in ("tx_gain 1 60", "rx_gain 0 900", "tx_gain 0 nan", "rx_gain 0 10\nstop", "du1 tx_gain 0 1"):
                    sup.input_command(invalid)
                sup.input_command("tx_gain 0 60")
                sup.input_command("rx_gain 0 10")
                wait_for(lambda: (Path(root) / "events.jsonl").read_text().count('"kind": "input"') == 2)
            result, sup, host = self.run_case(root, action=action)
            self.assertEqual(result, 0, sup.cleanup_errors)
            events = [json.loads(line) for line in (Path(root) / "events.jsonl").read_text().splitlines()]
            inputs = [e for e in events if e["kind"] == "input"]
            self.assertEqual([(e["role"], e["line"]) for e in inputs], [("du2", "tx_gain 0 60"), ("du2", "rx_gain 0 10")])

    def test_sustained_database_failure_stops_all(self):
        with tempfile.TemporaryDirectory() as root:
            result, sup, host = self.run_case(root, health=3)
            self.assertEqual(result, 1)
            self.assertEqual(host.health_calls, 3)
            self.assertIn("Sustained infrastructure health failure", sup.reason)

    def test_transient_probe_failure_and_absent_clients_do_not_stop(self):
        with tempfile.TemporaryDirectory() as root:
            result, sup, host = self.run_case(root, health=1, recover=True)
            self.assertEqual(result, 0, sup.reason)
            self.assertGreater(host.health_calls, 1)
            self.assertEqual(sup.children["xapp"].apps, set())

    def test_hung_child_escalation_does_not_prevent_rest_of_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            result, sup, host = self.run_case(root, hang="du2")
            self.assertEqual(result, 1)
            self.assertTrue(any("du2" in error and "forced=True" in error for error in sup.cleanup_errors))
            self.assertEqual(host.calls[-1], "core_stop")

    def test_xapp_orphan_collector_group_is_reaped(self):
        with tempfile.TemporaryDirectory() as root:
            result, sup, host = self.run_case(root, grandchild=True)
            pid = int((Path(root) / "grandchild.pid").read_text())
            self.assertFalse(AUTO.group_alive(sup.children["xapp"].process.pid))
            self.assertEqual(result, 1)  # Forced cleanup is visibly not a pass.

    def test_sigint_to_real_controller_process_cleans_up(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            with (directory / "controller.log").open("w") as output:
                proc = subprocess.Popen([sys.executable, "-B", __file__, "--fake-supervisor", root],
                                        stdout=output, stderr=output, start_new_session=True)
                try:
                    def running():
                        try:
                            return json.loads((directory / "status.json").read_text())["phase"] == "running"
                        except (OSError, ValueError):
                            return False
                    wait_for(running)
                    proc.send_signal(signal.SIGINT)
                    self.assertEqual(proc.wait(timeout=8), 0, (directory / "controller.log").read_text())
                    state = json.loads((directory / "status.json").read_text())
                    self.assertEqual(state["phase"], "stopped")
                    self.assertEqual(state["reason"], "SIGINT")
                    self.assertTrue(all(p["exit_code"] == 0 for p in state["processes"].values()))
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
                        # A failing test must not leave fixture components alive.
                        if (directory / "status.json").is_file():
                            state = json.loads((directory / "status.json").read_text())
                            for value in state["processes"].values():
                                AUTO.signal_group(value["pid"], signal.SIGKILL)

    def test_no_ui_backpressure_or_unbounded_partial_lines(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            code = "import sys; print('x'*1000000); [print('Tx gain set to 60 dB') for _ in range(2000)]"
            child = AUTO.Child(AUTO.Service("du2", [sys.executable, "-c", code], directory), directory, queue.Queue(maxsize=1))
            try:
                self.assertEqual(child.process.wait(timeout=5), 0)
                self.assertTrue(child.finished.wait(2))
                self.assertLessEqual(len(child.tail), 100)
                self.assertTrue(all(len(line) <= 16384 for line in child.tail))
                self.assertGreater(child.path.stat().st_size, 1000000)
            finally:
                AUTO.signal_group(child.process.pid, signal.SIGKILL)
                child.close_log()

    def test_xapp_registration_lifecycle_reaches_terminal_queue(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            messages = [
                ("APP_REGISTER_RECEIVED", dict(app_id=None, requested_app_id="mptcp-server", request_id="reg-1")),
                ("APP_REGISTERED", dict(app_id="mptcp-server", request_id="reg-1", subscription_id="sub-1", acknowledgement="queued")),
                ("APP_REGISTER_REJECTED", dict(app_id=None, requested_app_id="another-server", request_id="reg-2", reason="unsupported_profile")),
                ("APP_UNREGISTER_RECEIVED", dict(app_id="mptcp-server", request_id="unreg-1", subscription_id="sub-1")),
                ("APP_UNREGISTERED", dict(app_id="mptcp-server", request_id="unreg-1", subscription_id="sub-1", acknowledgement="queued")),
                ("APP_DISCONNECTED", dict(app_id="mptcp-server", subscription_id="sub-1", reason="drained")),
            ]
            lines = [kind + " " + json.dumps(fields) for kind, fields in messages]
            events = queue.Queue()
            child = AUTO.Child(AUTO.Service("xapp", [sys.executable, "-c",
                               "import sys; [print(line,flush=True) for line in sys.argv[1:]]", *lines], directory), directory, events)
            try:
                self.assertEqual(child.process.wait(timeout=5), 0)
                self.assertTrue(child.finished.wait(2))
                output = [events.get_nowait() for _ in messages]
                self.assertTrue(all(name == "xapp" for name, _ in output))
                self.assertEqual(output[0][1], "APP_REGISTER_RECEIVED app=mptcp-server request=reg-1")
                self.assertEqual(output[1][1], "APP_REGISTERED app=mptcp-server request=reg-1 subscription=sub-1 acknowledgement=queued")
                self.assertIn("app=another-server request=reg-2 reason=unsupported_profile", output[2][1])
                self.assertEqual([line.split()[0] for _, line in output], [kind for kind, _ in messages])
                self.assertEqual(child.apps, set())
                self.assertTrue(events.empty())
                self.assertIn("APP_REGISTER_RECEIVED", child.path.read_text())
            finally:
                AUTO.signal_group(child.process.pid, signal.SIGKILL)
                child.close_log()

    def test_status_write_failure_still_cleans_up_processes(self):
        with tempfile.TemporaryDirectory() as root:
            host = FakeHost(root)
            sup = AUTO.Supervisor(settings(), root, host)
            with patch.object(AUTO, "atomic_json", side_effect=OSError("disk full")):
                result = sup.execute(plan(root), interactive=False)
            self.assertEqual(result, 1)
            self.assertIn("Controller status file unavailable", sup.cleanup_errors)
            self.assertEqual(host.calls[-1], "core_stop")
            self.assertTrue(all(not AUTO.group_alive(child.process.pid) for child in sup.children.values()))

    def test_stop_command_rejects_stale_or_foreign_pid(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            state = dict(supervisor="falcon-spark-auto", phase="running", pid=os.getpid(), start_ticks="0")
            AUTO.atomic_json(directory / "status.json", state)
            with patch.object(AUTO.os, "kill") as kill:
                with self.assertRaisesRegex(AUTO.Fault, "Stale controller PID"):
                    AUTO.main(["--stop", root])
                state["start_ticks"] = AUTO.start_ticks(os.getpid())
                AUTO.atomic_json(directory / "status.json", state)
                with self.assertRaisesRegex(AUTO.Fault, "not a spark_auto controller"):
                    AUTO.main(["--stop", root])
                kill.assert_not_called()

    def test_stop_command_signals_the_verified_controller(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            # Use the real public script basename for the /proc identity guard.
            wrapper = directory / "spark_auto.py"
            wrapper.write_text("import runpy; runpy.run_path(" + repr(str(Path(__file__).resolve())) + ", run_name='__main__')\n")
            with (directory / "controller.log").open("w") as output:
                proc = subprocess.Popen([sys.executable, "-B", str(wrapper), "--fake-supervisor", root],
                                        stdout=output, stderr=output, start_new_session=True)
                try:
                    def running():
                        try:
                            return json.loads((directory / "status.json").read_text())["phase"] == "running"
                        except (OSError, ValueError):
                            return False
                    wait_for(running)
                    self.assertEqual(AUTO.main(["--stop", root]), 0)
                    self.assertEqual(proc.wait(timeout=8), 0, (directory / "controller.log").read_text())
                    state = json.loads((directory / "status.json").read_text())
                    self.assertEqual(state["phase"], "stopped")
                    self.assertTrue(all(not AUTO.group_alive(value["pid"]) for value in state["processes"].values()))
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
                        if (directory / "status.json").is_file():
                            state = json.loads((directory / "status.json").read_text())
                            for value in state["processes"].values():
                                AUTO.signal_group(value["pid"], signal.SIGKILL)


class HostTests(unittest.TestCase):
    def test_ss_duplicate_association_rows_are_counted_once(self):
        rows = AUTO.socket_rows("\n".join([
            "LISTEN 0 128 127.0.10.1:38472 0.0.0.0:*",
            "ESTAB 0 0 127.0.10.1:38472 127.0.10.2:40000",
            "`- ESTAB 0 0 127.0.10.1%lo:38472 127.0.10.2:40000",
        ]))
        self.assertEqual(len(rows), 2)

    def test_core_stop_requires_all_ten_final_states(self):
        host = AUTO.Host(lambda *args, **kwargs: "", {})
        self.assertFalse(host.core_stopped())
        host.command = lambda *args, **kwargs: "\n".join(["inactive"] * 9 + ["deactivating"])
        self.assertFalse(host.core_stopped())
        host.command = lambda *args, **kwargs: "\n".join(["inactive"] * 9 + ["failed"])
        self.assertTrue(host.core_stopped())

    def test_sctp_tcp_states_and_transport_requirements(self):
        sctp = "\n".join([
            "LISTEN 0 128 127.0.0.1:36421 0.0.0.0:*",
            "LISTEN 0 128 127.0.0.1:36422 0.0.0.0:*",
            *[f'ESTAB 0 0 127.0.0.1:36421 127.0.0.1:{40000+i}' for i in range(3)],
            *[f'ESTAB 0 0 127.0.10.1:38472 127.0.10.{i+2}:40000' for i in range(2)],
            "ESTAB 0 0 127.0.0.1:45000 127.0.0.5:38412",
            "ESTAB 0 0 127.0.0.1:36422 127.0.0.1:45001",
        ])
        tcp = "LISTEN 0 128 127.0.0.1:8765 0.0.0.0:*"
        host = AUTO.Host(lambda args: sctp if "sctp" in args else tcp, {})
        host.transport_check(set(AUTO.ORDER))
        host.command = lambda args: sctp.replace('127.0.0.1:36422 127.0.0.1:45001', '127.0.0.1:36423 127.0.0.1:45001') if "sctp" in args else tcp
        with self.assertRaisesRegex(AUTO.Fault, "E42 association"):
            host.transport_check(set(AUTO.ORDER))

    def test_empty_infoapi_is_healthy_and_wrong_routes_are_not(self):
        def command(args):
            if args[0] == "systemctl":
                return "\n".join(["active"] * 10)
            tun = args[-1]
            if "link" in args:
                return json.dumps([dict(flags=["UP"], mtu=1400)])
            if "addr" in args:
                return json.dumps([dict(addr_info=[dict(local="10.45.0.1" if tun.endswith("1") else "10.46.0.1", prefixlen=16)])])
            return json.dumps([dict(dev="ogstun_1" if tun.startswith("10.45") else "ogstun_2")])
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"items":[],"pager":{"page":0}}'
        opener = unittest.mock.MagicMock()
        opener.open.return_value = response
        identity = dict(amf=dict(url="http://127.0.0.5:9090/ue-info"), smf_url="http://127.0.0.4:9090/pdu-info")
        with patch.object(AUTO.urllib.request, "build_opener", return_value=opener):
            host = AUTO.Host(command, identity)
            host.core_check()
            host.command = lambda args: json.dumps([dict(dev="wrong")]) if "route" in args else command(args)
            with self.assertRaisesRegex(AUTO.Fault, "Wrong route"):
                host.core_check()

    def test_cancelled_preparation_command_reaps_its_group(self):
        with tempfile.TemporaryDirectory() as root:
            sup = AUTO.Supervisor(settings(), root, FakeHost(root))
            worker = threading.Timer(0.1, lambda: sup.request_stop("cancel build"))
            worker.start()
            try:
                with self.assertRaises(AUTO.Stopping):
                    sup.command([sys.executable, "-c", "import time; time.sleep(60)"])
            finally:
                worker.join()
                sup.audit.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fake-supervisor":
        args = settings()
        args.stop_timeout = 0.5
        root = Path(sys.argv[2])
        supervisor = AUTO.Supervisor(args, root, FakeHost(root))
        sys.exit(supervisor.execute(plan(root), interactive=False))
    unittest.main()
