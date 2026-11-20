"""Real PTYs/process groups with fake components; no Docker, systemd or radios."""

import importlib.util
import io
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
role,root,crash,missing,hang,grandchild,protocol,*options=sys.argv[1:]
subscriptions=int(options[0]) if options else 3
root=Path(root)
def record(kind,**fields):
 with (root/'events.jsonl').open('a') as f:f.write(json.dumps(dict(role=role,kind=kind,**fields))+'\n')
record('started',pid=os.getpid(),tty=os.isatty(0),controlling=os.tcgetpgrp(0)==os.getpgrp())
def stop(number,frame):
 if hang=='yes':return
 record('stop',signal=number)
 if role=='xapp':
  for _ in range(subscriptions):print('[xApp]: E42 SUBSCRIPTION DELETE RESPONSE rx',flush=True)
  (root/'publisher.json').write_text(json.dumps(dict(status='passed',counters=dict(active_connections=0,active_registrations=0))))
 sys.exit(0)
signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
if grandchild=='yes':
 code="import os,signal,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); signal.signal(signal.SIGINT,signal.SIG_IGN); signal.signal(signal.SIGHUP,signal.SIG_IGN); Path(__import__('sys').argv[1]).write_text(str(os.getpid())); time.sleep(60)"
 subprocess.Popen([sys.executable,'-c',code,str(root/'grandchild.pid')])
if missing!='yes':print('READY '+role,flush=True)
if protocol=='yes':
 time.sleep(.15)  # The process/transport can be up before protocol success.
 buffered_native = None
 if role in ('cu','du1','du2'):
  buffered_native=(root/(role+'.log')).open('w',buffering=8192)
 def native(name,line):
  print(line,flush=True)
  if buffered_native is not None:buffered_native.write(line+'\n')
 if role in ('cu','du1','du2'):
  if role.startswith('du'):
   du=role[-1]
   (root/('f1-'+du)).write_text(du)
   native(role,'[DU-F1] [I] Rx PDU du='+du+' tid=0: F1SetupResponse')
  native(role,'[E2] [I] E2 Setup procedure successful.')
 elif role=='xapp':
  for line in ('[xApp]: E42 SETUP-RESPONSE rx','[xApp]: xApp ID = 7',
               '[xApp]: Registered E2 Nodes = '+str(subscriptions),
               'SUBSCRIPTION_READY host=127.0.0.1 port=8765 profile=du27_bound_v1 source=e2',
               'identity collector: '+str(subscriptions)+' KPM subscriptions, duration=0'):
   print(line,flush=True)
started=time.monotonic()
while True:
 if role=='cu' and protocol=='yes':
  for du in ('1','2'):
   notification=root/('f1-'+du)
   if notification.exists():
    notification.unlink()
    native('cu','[CU-CP-F1] [I] Rx PDU du='+du+' tid=0: F1SetupRequest')
    native('cu','[CU-CP-F1] [I] Tx PDU du='+du+' tid=0: F1SetupResponse')
 if crash!='none' and time.monotonic()-started>float(crash):record('crash');sys.exit(7)
 if role in ('du1','du2') and select.select([sys.stdin],[],[],0.02)[0]:
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


def plan(root, crash=None, missing=None, hang=None, grandchild=False, protocols=False, missing_protocol=None,
         du1_only=False, du2_wired20_only=False):
    root = Path(root)
    args = settings()
    args.du1_only = du1_only
    args.du2_wired20_only = du2_wired20_only
    subscriptions = 1 + len(AUTO.du_names(args))
    script = root / "component.py"
    script.write_text(FAKE)
    services = [AUTO.Service(name, [sys.executable, "-u", str(script), name, str(root),
                "0.9" if crash == name else "none", "yes" if missing == name else "no",
                "yes" if hang == name else "no", "yes" if grandchild and name == "xapp" else "no",
                "yes" if protocols and name != missing_protocol else "no", str(subscriptions)],
                root, ("READY " + name,)) for name in AUTO.service_order(args)]
    if protocols:
        # Use the deployed plan for protocol/logging choices; only replace
        # executable/marker details with the isolated component fixture.
        (root / "local.json").write_text('{"cu":{"gnb_id":411}}')
        for name in AUTO.du_names(args):
            (root / f"{name}.yml").write_text(f"gnb_du_id: {name[-1]}\n")
        deployed = {service.name: service for service in AUTO.service_plan(args, root)}
        for service in services:
            production = deployed[service.name]
            service.required_protocol = production.required_protocol
            if service.name in ("cu", "du1", "du2"):
                service.native_log = production.native_log
                service.gnb_id = production.gnb_id
                service.du_id = production.du_id
            elif service.name == "xapp":
                service.markers += (f"identity collector: {subscriptions} KPM subscriptions, duration=0",)
    return services


def wait_for(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = condition()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("offline fixture deadline")


class SupervisorTests(unittest.TestCase):
    def test_configured_gain_values_are_preserved_and_invalid_values_rejected(self):
        for tx, rx in ((70, 45), (60, 35), (59.5, 34.5), (0, 0)):
            with self.subTest(tx=tx, rx=rx):
                self.assertEqual(AUTO.radio_gains({"ru_sdr": dict(tx_gain=tx, rx_gain=rx)}, "DU2"), (tx, rx))
        for value in (None, True, "35", float("nan"), float("inf"), -1):
            for key in ("tx_gain", "rx_gain"):
                with self.subTest(key=key, value=value):
                    radio = dict(tx_gain=60, rx_gain=35)
                    radio[key] = value
                    with self.assertRaisesRegex(AUTO.Fault, "finite nonnegative"):
                        AUTO.radio_gains({"ru_sdr": radio}, "DU2")

    def run_case(self, root, *, crash=None, missing=None, hang=None, grandchild=False,
                 health=0, recover=False, action=None, protocols=False, missing_protocol=None,
                 du1_only=False, du2_wired20_only=False):
        host = FakeHost(root, health, recover)
        args = settings()
        args.du1_only = du1_only
        args.du2_wired20_only = du2_wired20_only
        if missing:
            args.startup_timeout = 0.2
        if missing_protocol:
            args.startup_timeout = 0.5
        sup = AUTO.Supervisor(args, root, host)
        worker_errors = []
        worker = None
        if not crash and not missing and not missing_protocol and not (health and not recover):
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
        result = sup.execute(plan(root, crash=crash, missing=missing, hang=hang, grandchild=grandchild,
                                  protocols=protocols, missing_protocol=missing_protocol, du1_only=du1_only,
                                  du2_wired20_only=du2_wired20_only), interactive=False)
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

    def test_fr1_only_order_status_gain_routing_and_two_subscription_cleanup(self):
        with tempfile.TemporaryDirectory() as root, patch.object(sys, "stdout", io.StringIO()) as output:
            def gain(sup):
                self.assertNotIn("du2", sup.children)
                sup.input_command("rx_gain 0 25")
                wait_for(lambda: '"kind": "input"' in (Path(root) / "events.jsonl").read_text())
            result, sup, _ = self.run_case(root, du1_only=True, protocols=True, action=gain)
            self.assertEqual(result, 0, sup.cleanup_errors)
            events = [json.loads(line) for line in (Path(root) / "events.jsonl").read_text().splitlines()]
            self.assertEqual([e["role"] for e in events if e["kind"] == "started"], ["ric", "cu", "du1", "xapp"])
            self.assertEqual([e["role"] for e in events if e["kind"] == "stop"], ["xapp", "du1", "cu", "ric"])
            self.assertEqual([(e["role"], e["line"]) for e in events if e["kind"] == "input"], [("du1", "rx_gain 0 25")])
            self.assertEqual(sup.children["xapp"].deletions, 2)
            state = json.loads((Path(root) / "status.json").read_text())
            self.assertEqual(state["profile"], "fr1-ue1")
            self.assertEqual(state["gain_target"], "du1")
            text = output.getvalue()
            self.assertIn("E2 nodes registered=2/2", text)
            self.assertIn("DUs registered=1/1", text)
            self.assertIn("E2 nodes subscribed=2", text)
            self.assertNotIn("[du2]", text)

    def test_fr1_only_component_failures_stop_the_selected_services(self):
        for name in ("ric", "cu", "du1", "xapp"):
            with self.subTest(component=name), tempfile.TemporaryDirectory() as root:
                result, sup, _ = self.run_case(root, crash=name, du1_only=True)
                self.assertEqual(result, 1)
                self.assertIn(name + " exited unexpectedly", sup.reason)
                self.assertNotIn("du2", sup.children)

    def test_wired_du2_only_uses_same_protocol_gates_gain_routing_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root, patch.object(sys, "stdout", io.StringIO()) as output:
            def gain(sup):
                self.assertNotIn("du1", sup.children)
                sup.input_command("rx_gain 0 25")
                wait_for(lambda: '"kind": "input"' in (Path(root) / "events.jsonl").read_text())
            result, sup, _ = self.run_case(root, du2_wired20_only=True, protocols=True, action=gain)
            self.assertEqual(result, 0, sup.cleanup_errors)
            events = [json.loads(line) for line in (Path(root) / "events.jsonl").read_text().splitlines()]
            self.assertEqual([e["role"] for e in events if e["kind"] == "started"], ["ric", "cu", "du2", "xapp"])
            self.assertEqual([e["role"] for e in events if e["kind"] == "stop"], ["xapp", "du2", "cu", "ric"])
            self.assertEqual([(e["role"], e["line"]) for e in events if e["kind"] == "input"], [("du2", "rx_gain 0 25")])
            self.assertTrue(all(e["tty"] and e["controlling"] for e in events if e["kind"] == "started"))
            self.assertEqual(sup.children["xapp"].deletions, 2)
            state = json.loads((Path(root) / "status.json").read_text())
            self.assertEqual((state["profile"], state["gain_target"]), ("wired-du2-ue2", "du2"))
            self.assertIn("E2 nodes registered=2/2", output.getvalue())
            self.assertIn("DUs registered=1/1", output.getvalue())
            self.assertNotIn("[du1]", output.getvalue())

    def test_wired_component_failure_cleans_up_without_starting_du1(self):
        for name in ("ric", "cu", "du2", "xapp"):
            with self.subTest(component=name), tempfile.TemporaryDirectory() as root:
                result, sup, _ = self.run_case(root, crash=name, du2_wired20_only=True)
                self.assertEqual(result, 1)
                self.assertIn(name + " exited unexpectedly", sup.reason)
                self.assertNotIn("du1", sup.children)

    def test_wired_preflight_and_prepare_need_no_ota_du_configs_or_ue1(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            args = settings()
            args.du2_wired20_only = True
            args.ocudu, args.flexric, args.ric = root / "ocudu", root / "flexric", root / "ric"
            configs = args.ocudu / "configs"
            configs.mkdir(parents=True)
            (configs / "cu.yml").write_text('cu_cp:\n  max_nof_dus: 1\n  f1ap:\n    bind_addrs: 127.0.10.1\n')
            for relative in ("src/xApp/libe42_xapp.a", "src/util/CMakeFiles/e2_time_obj.dir/time_now_us.c.o"):
                path = args.flexric / "build-ocudu" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            for path in (args.ocudu / "build-integrated/apps/cu/ocu", AUTO.du_binary(args), args.ric):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("#!/bin/sh\nexit 0\n")
                path.chmod(0o755)
            identity_before = (ROOT / "configs/ue_identity/local.json").read_text()
            with patch.object(AUTO.shutil, "which", return_value="/usr/bin/fake"):
                sources = AUTO.check_files(args)
            self.assertNotIn("du1.yml", sources)
            self.assertNotIn("du2_e2.yml", sources)
            self.assertEqual(sources["du2.yml"], ROOT / "configs/ocudu/dual_fr1/du2_b210_n78_20mhz_wired.yml")
            run = root / "run"
            run.mkdir()
            sup = AUTO.Supervisor(args, run, FakeHost(run))
            def command(argv, **kwargs):
                if argv[0] == "bash":
                    (run / "collector").touch()
                    (run / "sm").mkdir()
                    (run / "sm/libkpm_sm.so").touch()
                return "offline fixture\n"
            try:
                with patch.object(sup, "command", side_effect=command), patch.object(sup, "say"):
                    services = {s.name: s for s in AUTO.prepare(sup, sources)}
                self.assertEqual(list(services), ["ric", "cu", "du2", "xapp"])
                self.assertNotIn(run / "du2_e2.yml", services["du2"].argv)
                self.assertIn("identity collector: 2 KPM subscriptions, duration=0", services["xapp"].markers)
                identity = json.loads((run / "local.json").read_text())
                self.assertEqual(identity["dnns"], ["internet2"])
                self.assertEqual([node["du_id"] for node in identity["du_nodes"]], ["2"])
                self.assertEqual((ROOT / "configs/ue_identity/local.json").read_text(), identity_before)
                manifest = json.loads((run / "manifest.json").read_text())
                self.assertEqual(manifest["profile"], "wired-du2-ue2")
                self.assertEqual(manifest["hashes"][str(run / "local.json")], AUTO.file_sha256(run / "local.json"))
            finally:
                sup.audit.close()
            # Custom candidates use the same profile checks, not the 40-MHz overlay.
            selected = root / "candidate.yml"
            config = AUTO.yaml.safe_load(sources["du2.yml"].read_text())
            config["ru_sdr"]["rx_gain"] = 30
            selected.write_text(AUTO.yaml.safe_dump(config))
            args.du2_config = selected
            with patch.object(AUTO.shutil, "which", return_value="/usr/bin/fake"):
                self.assertEqual(AUTO.check_files(args)["du2.yml"], selected)
                config["cell_cfg"]["channel_bandwidth_MHz"] = 40
                selected.write_text(AUTO.yaml.safe_dump(config))
                with self.assertRaisesRegex(AUTO.Fault, "20 MHz"):
                    AUTO.check_files(args)

    def test_fr1_preflight_needs_no_du2_configuration_and_scopes_identity_to_ue1(self):
        with tempfile.TemporaryDirectory() as root:
            args = settings()
            args.du1_only = True
            args.ocudu, args.flexric, args.ric = Path(root) / "ocudu", Path(root) / "flexric", Path(root) / "ric"
            configs = args.ocudu / "configs"
            configs.mkdir(parents=True)
            (configs / "cu.yml").write_text('cu_cp:\n  max_nof_dus: 1\n  f1ap:\n    bind_addrs: 127.0.10.1\n')
            (configs / "du1_b210_n78_3660mhz.yml").write_text((ROOT / "configs/ocudu/dual_fr1/du1_b210_n78_3660mhz.yml").read_text())
            for relative in ("src/xApp/libe42_xapp.a", "src/util/CMakeFiles/e2_time_obj.dir/time_now_us.c.o"):
                path = args.flexric / "build-ocudu" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            for path in (args.ocudu / "build-integrated/apps/cu/ocu", AUTO.du_binary(args), args.ric):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("#!/bin/sh\nexit 0\n")
                path.chmod(0o755)
            with patch.object(AUTO.shutil, "which", return_value="/usr/bin/fake"):
                sources = AUTO.check_files(args)
            self.assertNotIn("du2.yml", sources)
            self.assertNotIn("du2_e2.yml", sources)
            identity = json.loads(sources["local.json"].read_text())
            self.assertEqual(identity["dnns"], ["internet"])
            self.assertEqual([n["du_id"] for n in identity["du_nodes"]], ["1"])
            self.assertEqual(identity["cu"]["ran_ue_id_format"], "du36-cuue28-v1")

            # A comparison run must work even without the deployed DU1 file,
            # and must validate the selected radio configuration itself.
            deployed = configs / "du1_b210_n78_3660mhz.yml"
            selected = Path(root) / "comparison.yml"
            config = AUTO.yaml.safe_load(deployed.read_text())
            config["ru_sdr"]["rx_gain"] = 35
            selected.write_text(AUTO.yaml.safe_dump(config))
            deployed.unlink()
            args.du1_config = selected
            with patch.object(AUTO.shutil, "which", return_value="/usr/bin/fake"):
                comparison = AUTO.check_files(args)
                self.assertEqual(comparison["du1.yml"], selected.resolve())
                self.assertEqual(AUTO.yaml.safe_load(comparison["du1.yml"].read_text())["ru_sdr"]["rx_gain"], 35)
                config["ru_sdr"]["rx_gain"] = -1
                selected.write_text(AUTO.yaml.safe_dump(config))
                with self.assertRaisesRegex(AUTO.Fault, "finite nonnegative"):
                    AUTO.check_files(args)
                selected.unlink()
                with self.assertRaisesRegex(AUTO.Fault, "Missing configuration"):
                    AUTO.check_files(args)

    def test_fr1_cuda_plan_requires_initialization_only_for_du1(self):
        with tempfile.TemporaryDirectory() as root:
            plan(root, protocols=True, du1_only=True)
            args = settings()
            args.du1_only, args.cuda = True, True
            services = {s.name: s for s in AUTO.service_plan(args, Path(root))}
            self.assertEqual(list(services), ["ric", "cu", "du1", "xapp"])
            self.assertIn(Path(root) / "cuda_uplink.yml", services["du1"].argv)
            self.assertIn("Resident LDPC decoder enabled for PUSCH acceleration", services["du1"].markers)
            self.assertIn("identity collector: 2 KPM subscriptions, duration=0", services["xapp"].markers)

    def test_every_component_crash_stops_all_other_components(self):
        for name in AUTO.ORDER:
            with self.subTest(component=name), tempfile.TemporaryDirectory() as root:
                result, sup, host = self.run_case(root, crash=name)
                self.assertEqual(result, 1)
                self.assertIn(name + " exited unexpectedly", sup.reason)
                self.assertEqual(set(sup.children), set(AUTO.ORDER))

    def test_protocol_confirmations_are_printed_before_ready_and_next_start(self):
        with tempfile.TemporaryDirectory() as root, patch.object(sys, "stdout", io.StringIO()) as output:
            def idle_logs(sup):
                for name in ("cu", "du1", "du2"):
                    # An idle native file can still be empty while its protocol
                    # success is already visible through the live stdout sink.
                    self.assertEqual((Path(root) / (name + ".log")).stat().st_size, 0)
                    self.assertEqual(sup.children[name].protocol["e2"], "registered")
            result, sup, _ = self.run_case(root, protocols=True, action=idle_logs)
            self.assertEqual(result, 0, sup.cleanup_errors)
            text = output.getvalue()
            for name, next_name in (("cu", "du1"), ("du1", "du2"), ("du2", "xapp")):
                success = text.index("E2_REGISTERED node=" + name.upper())
                ready = text.index("[READY] " + name)
                self.assertLess(success, ready)
                self.assertLess(ready, text.index("[START] " + next_name))
            for name in ("du1", "du2"):
                self.assertLess(text.index("F1_DU_REGISTERED node=" + name.upper()), text.index("[READY] " + name))
            self.assertLess(text.index("E42_REGISTERED node=xApp"), text.index("[READY] xapp"))
            self.assertLess(text.index("KPM_SUBSCRIPTIONS_READY"), text.index("[READY] xapp"))
            self.assertLess(text.index("[READY] xapp"), text.index("[STATUS] phase=running"))
            self.assertLess(text.index("[STATUS] phase=running"), text.index("[RUNNING]"))
            self.assertIn("E2 nodes registered=3/3", text)
            self.assertIn("DUs registered=2/2", text)
            self.assertIn("E2 nodes subscribed=3", text)

    def test_deployed_native_services_use_flushed_stdout(self):
        with tempfile.TemporaryDirectory() as root:
            plan(root, protocols=True)
            services = AUTO.service_plan(settings(), Path(root))
            for service in services:
                if service.name in ("cu", "du1", "du2"):
                    self.assertEqual(service.argv[service.argv.index("--filename") + 1], "stdout")
                    self.assertIsNone(service.native_log)
                    self.assertIn("e2", service.required_protocol)

    def test_wait_prints_pending_registration_progress(self):
        with tempfile.TemporaryDirectory() as root:
            sup = AUTO.Supervisor(settings(), root, FakeHost(root))
            self.addCleanup(sup.audit.close)
            condition = unittest.mock.Mock(side_effect=[
                AUTO.Fault("cu awaiting registration: e2=waiting"),
                AUTO.Fault("cu awaiting registration: e2=waiting"), True])
            with patch.object(sup, "pump"), patch.object(sup.stop_event, "wait"), \
                 patch.object(AUTO.time, "monotonic", side_effect=[0, 0, 5]), \
                 patch.object(sys, "stdout", io.StringIO()) as output:
                sup.wait("cu", condition, timeout=20)
            self.assertIn("[WAIT] cu (5s): cu awaiting registration: e2=waiting", output.getvalue())

    def test_cuda_selects_both_du_binaries_and_requires_gpu_initialization(self):
        with tempfile.TemporaryDirectory() as root:
            plan(root, protocols=True)
            args = settings()
            args.cuda, args.cuda_build = True, Path(root) / "gpu-build"
            services = {service.name: service for service in AUTO.service_plan(args, Path(root))}
            self.assertEqual(services["cu"].argv[0], args.ocudu / "build-integrated/apps/cu/ocu")
            for name in ("du1", "du2"):
                self.assertEqual(services[name].argv[0], args.cuda_build / "apps/du_split_8/odu")
                self.assertIn(Path(root) / "cuda_uplink.yml", services[name].argv)
                self.assertIn("Resident LDPC decoder enabled for PUSCH acceleration", services[name].markers)
                self.assertIn("E2: Connection", services[name].markers)

    def test_cuda_preflight_rejects_cpu_only_and_stale_artifacts(self):
        with tempfile.TemporaryDirectory() as root:
            args = settings()
            args.cuda, args.cuda_build = True, Path(root)
            binary = AUTO.du_binary(args)
            binary.parent.mkdir(parents=True)
            binary.write_text("fake GPU binary")
            binary.chmod(0o755)
            cache = Path(root) / "CMakeCache.txt"
            cache.write_text("ENABLE_CUDA:BOOL=OFF\n")
            with self.assertRaisesRegex(AUTO.Fault, "does not have CUDA"):
                AUTO.check_cuda_artifact(args)
            cache.write_text("ENABLE_CUDA:BOOL=ON\nCUDA_ACCEL_FOUND:BOOL=TRUE\n")
            with self.assertRaisesRegex(AUTO.Fault, "missing or stale"):
                AUTO.check_cuda_artifact(args)
            value = dict(status="passed", du_sha256=AUTO.file_sha256(binary),
                         overlay_sha256=AUTO.file_sha256(ROOT / "configs/ocudu/cuda_uplink.yml"))
            (Path(root) / "falcon-cuda-validation.json").write_text(json.dumps(value))
            AUTO.check_cuda_artifact(args)
            binary.write_text("changed binary")
            with self.assertRaisesRegex(AUTO.Fault, "does not match"):
                AUTO.check_cuda_artifact(args)

    def test_alive_component_without_protocol_success_times_out_before_next_start(self):
        with tempfile.TemporaryDirectory() as root, patch.object(sys, "stdout", io.StringIO()) as output:
            result, sup, _ = self.run_case(root, protocols=True, missing_protocol="du2")
            self.assertEqual(result, 1)
            self.assertIn("du2 startup timed out", sup.reason)
            self.assertIn("awaiting registration", sup.reason)
            self.assertNotIn("[READY] du2", output.getvalue())
            self.assertNotIn("xapp", sup.children)

    def test_startup_timeout_stops_prior_components_and_core(self):
        with tempfile.TemporaryDirectory() as root:
            result, sup, host = self.run_case(root, missing="du2")
            self.assertEqual(result, 1)
            self.assertIn("du2 startup timed out", sup.reason)
            self.assertNotIn("xapp", sup.children)

    def test_du2_commands_only_and_invalid_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            def action(sup):
                for invalid in ("tx_gain 1 60", "rx_gain 0 900", "tx_gain 0 nan", "rx_gain 0 35\nstop", "du1 tx_gain 0 1"):
                    sup.input_command(invalid)
                sup.input_command("tx_gain 0 60")
                sup.input_command("rx_gain 0 35")
                wait_for(lambda: (Path(root) / "events.jsonl").read_text().count('"kind": "input"') == 2)
            result, sup, host = self.run_case(root, action=action)
            self.assertEqual(result, 0, sup.cleanup_errors)
            events = [json.loads(line) for line in (Path(root) / "events.jsonl").read_text().splitlines()]
            inputs = [e for e in events if e["kind"] == "input"]
            self.assertEqual([(e["role"], e["line"]) for e in inputs], [("du2", "tx_gain 0 60"), ("du2", "rx_gain 0 35")])

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
        self.verified_controller_stop("spark_auto.py", False)

    def test_stop_command_signals_the_fr1_entry_point(self):
        self.verified_controller_stop("spark_fr1_auto.py", True)

    def test_stop_command_signals_the_wired_entry_point(self):
        self.verified_controller_stop("spark_wired_du2_auto.py", False, True)

    def verified_controller_stop(self, entry, du1_only, du2_wired20_only=False):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            # Use the real public script basename for the /proc identity guard.
            wrapper = directory / entry
            wrapper.write_text("import runpy; runpy.run_path(" + repr(str(Path(__file__).resolve())) + ", run_name='__main__')\n")
            with (directory / "controller.log").open("w") as output:
                proc = subprocess.Popen([sys.executable, "-B", str(wrapper), "--fake-supervisor", root,
                                         "wired" if du2_wired20_only else "fr1" if du1_only else "dual"],
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


class StatusTests(unittest.TestCase):
    def child(self, root, name, events):
        directory = Path(root)
        native = directory / (name + ".log") if name in ("cu", "du1", "du2") else None
        spec = AUTO.Service(name, [sys.executable, "-u", "-c",
                                  "import sys; [print(line,end='',flush=True) for line in sys.stdin]"],
                            directory, native_log=native, gnb_id="411",
                            du_id={"du1": "1", "du2": "2"}.get(name))
        child = AUTO.Child(spec, directory, events)
        def cleanup():
            AUTO.signal_group(child.process.pid, signal.SIGKILL)
            child.process.wait(timeout=3)
            child.close_log()
        self.addCleanup(cleanup)
        return child

    def console(self, child, line):
        os.write(child.master, (line + "\n").encode())

    def native(self, child, line):
        with child.spec.native_log.open("a") as stream:
            stream.write(line + "\n")

    def test_du_readiness_waits_for_both_f1_sides_and_e2(self):
        with tempfile.TemporaryDirectory() as root:
            sup = AUTO.Supervisor(settings(), root, FakeHost(root))
            self.addCleanup(sup.audit.close)
            cu = self.child(root, "cu", sup.events)
            du = self.child(root, "du1", sup.events)
            du.spec.required_protocol = ("e2", "f1")
            sup.children = dict(cu=cu, du1=du)
            with self.assertRaisesRegex(AUTO.Fault, "e2=waiting"):
                sup.service_ready("du1")
            self.native(du, "[E2] [I] E2 Setup procedure successful.")
            wait_for(lambda: du.protocol.get("e2") == "registered")
            with self.assertRaisesRegex(AUTO.Fault, "f1=waiting"):
                sup.service_ready("du1")
            self.native(du, "[DU-F1] [I] Rx PDU du=1 tid=0: F1SetupResponse")
            wait_for(lambda: du.protocol.get("f1") == "registered")
            with self.assertRaisesRegex(AUTO.Fault, "CU F1=waiting"):
                sup.service_ready("du1")
            self.native(cu, "[CU-CP-F1] [I] Tx PDU du=1 tid=0: F1SetupResponse")
            wait_for(lambda: cu.protocol.get("f1:1") == "registered")
            self.assertTrue(sup.service_ready("du1"))

    def test_cuda_status_waits_for_each_du_initialization_log(self):
        with tempfile.TemporaryDirectory() as root:
            args = settings()
            args.cuda = True
            sup = AUTO.Supervisor(args, root, FakeHost(root))
            self.addCleanup(sup.audit.close)
            for name in ("du1", "du2"):
                child = self.child(root, name, sup.events)
                sup.children[name] = child
                child.spec.markers = ("Resident LDPC decoder enabled for PUSCH acceleration",)
                self.assertFalse(child.ready())
                self.console(child, "[PHY] [I] Resident LDPC decoder enabled for PUSCH acceleration")
                wait_for(child.ready)
                self.assertEqual(child.protocol["cuda_pusch"], "ready")
            with patch.object(sys, "stdout", io.StringIO()) as output:
                sup.drain_events()
                sup.show_status()
            self.assertIn("[du1] CUDA_PUSCH_READY", output.getvalue())
            self.assertIn("[du2] CUDA_PUSCH_READY", output.getvalue())
            self.assertEqual(output.getvalue().count("uplink=cuda_ready"), 2)

    def test_success_requires_protocol_confirmation_and_native_tail_is_live(self):
        with tempfile.TemporaryDirectory() as root:
            events = queue.Queue()
            child = self.child(root, "cu", events)
            self.console(child, "E2AP: Connection to Near-RT-RIC completed (configured addrs 127.0.0.1, port 36421)")
            wait_for(lambda: len(child.tail) == 1)
            self.assertNotIn("e2", child.protocol)
            self.assertTrue(events.empty())
            child.spec.native_log.write_text("[E2] [I] E2 Setup procedure successful.")
            wait_for(lambda: child.native.pending)
            self.assertNotIn("e2", child.protocol)  # An incomplete line waits.
            self.native(child, "")
            wait_for(lambda: child.protocol.get("e2") == "registered")
            self.native(child, "[E2] [I] E2 Setup procedure successful.")
            self.native(child, "[CU-F1] [I] Rx PDU du=1 tid=0: F1SetupRequest")
            self.native(child, "[CU-F1] [I] Tx PDU du=1 tid=0: F1SetupResponse")
            self.native(child, "[CU-F1] [I] Rx PDU du=2 tid=0: F1SetupRequest")
            self.native(child, "[CU-F1] [I] Tx PDU du=2 tid=0: F1SetupFailure")
            wait_for(lambda: child.protocol.get("f1:2") == "failed")
            output = []
            while not events.empty():
                output.append(events.get_nowait())
            self.assertEqual(sum("E2_REGISTERED" in line for _, line in output), 1)
            self.assertIn(("ric", "E2_REGISTERED node=CU gnb_id=411 evidence=e2_setup_success"), output)
            self.assertEqual(child.protocol["f1:1"], "registered")
            self.assertFalse(any("F1_DU_REGISTERED node=DU2" in line for _, line in output))
            self.assertTrue(all(len(line) <= 16384 for line in child.tail))

    def test_status_aggregates_protocol_subscriptions_broker_apps_and_down_events(self):
        with tempfile.TemporaryDirectory() as root:
            sup = AUTO.Supervisor(settings(), root, FakeHost(root))
            self.addCleanup(sup.audit.close)
            sup.children = {name: self.child(root, name, sup.events) for name in AUTO.ORDER}
            sup.phase, sup.core_ready = "running", True
            before = sup.connection_status()
            self.assertEqual(before["ric"]["registered_e2_nodes"], 0)
            self.assertIsNone(before["xapp"]["subscribed_e2_nodes"])
            for name in ("cu", "du1", "du2"):
                self.native(sup.children[name], "[E2] [I] E2 Setup procedure successful.")
            for du in (1, 2):
                self.native(sup.children["cu"], f"[CU-F1] [I] Tx PDU du={du} tid=0: F1SetupResponse")
            xapp = sup.children["xapp"]
            for line in (
                "[xApp]: E42 SETUP-RESPONSE rx", "[xApp]: xApp ID = 7",
                "[xApp]: Registered E2 Nodes = 3", "identity collector: 2 KPM subscriptions, duration=0",
                "SUBSCRIPTION_READY host=127.0.0.1 port=8765 profile=du27_bound_v1 source=e2",
                'APP_REGISTERED {"app_id":"mptcp-server","subscription_id":"sub-1","request_id":"r1"}',
            ):
                self.console(xapp, line)
            wait_for(lambda: sup.connection_status()["ric"]["registered_e2_nodes"] == 3
                     and sup.connection_status()["cu"]["registered_dus"] == 2 and len(xapp.apps) == 1)
            value = sup.snapshot()["connections"]
            self.assertEqual(value["ric"]["xapp"], "registered")
            self.assertEqual(value["ric"]["xapp_id"], "7")
            self.assertEqual(value["cu"]["registered_dus"], 2)
            self.assertEqual(value["xapp"]["subscribed_e2_nodes"], 2)  # Not the inventory count.
            self.assertEqual(value["xapp"]["available_e2_nodes"], 3)
            self.assertEqual(value["xapp"]["registered_apps"], 1)
            output = io.StringIO()
            with patch.object(sys, "stdout", output):
                sup.input_command("status")
            self.assertIn("E2 nodes registered=3/3", output.getvalue())
            self.assertIn("DUs registered=2/2", output.getvalue())
            self.assertIn("E2 nodes subscribed=2", output.getvalue())
            self.assertIn("apps registered=1", output.getvalue())
            self.console(xapp, 'APP_DISCONNECTED {"app_id":"mptcp-server","subscription_id":"sub-1","reason":"drained"}')
            wait_for(lambda: not xapp.apps)
            self.assertEqual(sup.connection_status()["xapp"]["registered_apps"], 0)
            du2 = sup.children["du2"]
            du2.process.terminate()
            du2.process.wait(timeout=3)
            with patch.object(sys, "stdout", output), self.assertRaisesRegex(AUTO.Fault, "du2 exited unexpectedly"):
                sup.pump()
            self.assertIn("[du2] DOWN", output.getvalue())
            value = sup.snapshot()["connections"]
            self.assertEqual(value["ric"]["registered_e2_nodes"], 2)
            self.assertEqual(value["ric"]["e2_nodes"]["du2"], "down")
            self.assertEqual(value["cu"]["registered_dus"], 1)

    def test_native_disconnect_and_reconnect_update_counts(self):
        with tempfile.TemporaryDirectory() as root:
            events = queue.Queue()
            du = self.child(root, "du2", events)
            self.native(du, "[E2] [I] E2 Setup procedure successful.")
            wait_for(lambda: du.protocol.get("e2") == "registered")
            self.native(du, "[SCTP-GW] [I] E2AP: Received SCTP shutdown completed. Notifying connection drop to upper layers")
            self.native(du, "[SCTP-GW] [I] F1-C: Received SCTP shutdown completed. Notifying connection drop to upper layers")
            wait_for(lambda: du.protocol.get("e2") == "disconnected" and du.protocol.get("f1") == "disconnected")
            self.native(du, "[E2] [I] E2 Setup procedure successful.")
            self.native(du, "[DU-F1] [I] Rx PDU du=2 tid=1: F1SetupResponse")
            wait_for(lambda: du.protocol.get("e2") == "registered" and du.protocol.get("f1") == "registered")
            self.native(du, "[SCTP-GW] [I] E2: Received SCTP shutdown completed. Notifying connection drop to upper layers")
            wait_for(lambda: du.protocol.get("e2") == "disconnected")
            self.native(du, "[E2] [I] E2 Setup procedure successful.")
            wait_for(lambda: du.protocol.get("e2") == "registered")
            output = []
            while not events.empty():
                output.append(events.get_nowait()[1])
            self.assertEqual(sum(line.startswith("E2_REGISTERED") for line in output), 3)
            self.assertTrue(any(line.startswith("F1_DU_DISCONNECTED") for line in output))

    def test_ric_requests_are_separate_from_registration_and_xapp_id_updates(self):
        with tempfile.TemporaryDirectory() as root:
            events = queue.Queue()
            ric, xapp = self.child(root, "ric", events), self.child(root, "xapp", events)
            self.console(ric, "[E2AP]: E2 SETUP-REQUEST rx from PLMN   1. 1 Node ID 411 RAN type ngran_gNB_DU ID 2")
            self.console(ric, "[iApp]: E42 SETUP-REQUEST rx")
            self.console(ric, "[iApp]: E42 SETUP-RESPONSE tx")
            self.console(xapp, "[xApp]: xApp ID = 7")  # Inventory update alone isn't a setup confirmation.
            wait_for(lambda: len(xapp.tail) == 1 and len(ric.tail) == 3)
            self.assertNotIn("e42", xapp.protocol)
            output = [events.get_nowait()[1] for _ in range(3)]
            self.assertEqual(output[0], "E2_REGISTER_RECEIVED node=DU2 gnb_id=411 du_id=2")
            self.assertFalse(any(line.startswith("E2_REGISTERED") or line.startswith("E42_REGISTERED") for line in output))
            self.console(xapp, "[xApp]: E42 SETUP-RESPONSE rx")
            self.console(xapp, "[xApp]: xApp ID = 7")
            wait_for(lambda: xapp.protocol.get("e42") == "registered")
            self.console(ric, "[NEAR-RIC]: xApp 7 disconnected!")
            wait_for(lambda: ric.protocol.get("e42:7") == "disconnected")

    def test_tail_handles_rotation_truncation_and_bounds_partial_lines(self):
        with tempfile.TemporaryDirectory() as root:
            path, lines = Path(root) / "native.log", []
            tail = AUTO.LogTail(path, lines.append)
            self.addCleanup(tail.close)
            tail.poll()  # File not created yet.
            path.write_bytes(b"x" * 300000)
            tail.poll()
            self.assertEqual(tail.stream.tell(), 262144)
            self.assertEqual(len(tail.pending), 16384)
            path.write_bytes(b"new\n")
            tail.poll()
            self.assertEqual(lines, [b"new"])
            path.rename(path.with_suffix(".old"))
            path.write_bytes(b"rotated\n")
            tail.poll()
            self.assertEqual(lines, [b"new", b"rotated"])


class HostTests(unittest.TestCase):
    def test_wired_database_and_tun_checks_require_only_ue2(self):
        calls = []
        def command(args):
            calls.append(args)
            if args[0] == "docker":
                return ""
            if args[0] == "systemctl":
                return "\n".join(["active"] * 10)
            if "link" in args:
                self.assertEqual(args[-1], "ogstun_2")
                return json.dumps([dict(flags=["UP"], mtu=1400)])
            if "addr" in args:
                self.assertEqual(args[-1], "ogstun_2")
                return json.dumps([dict(addr_info=[dict(local="10.46.0.1", prefixlen=16)])])
            self.assertEqual(args[-1], "10.46.0.0/16")
            return json.dumps([dict(dev="ogstun_2")])
        identity = dict(amf=dict(url="http://127.0.0.5:9090/ue-info"), smf_url="http://127.0.0.4:9090/pdu-info")
        host = AUTO.Host(command, identity, ("du2",))
        host.database_check(subscribers=True)
        self.assertIn("001010000000102", calls[-1][-1])
        self.assertIn("internet2", calls[-1][-1])
        self.assertNotIn("001010000000101", calls[-1][-1])
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"items":[],"pager":{"page":0}}'
        opener = unittest.mock.MagicMock()
        opener.open.return_value = response
        with patch.object(AUTO.urllib.request, "build_opener", return_value=opener):
            host.core_check()

    def test_fr1_database_checks_only_ue1_and_core_checks_only_ogstun1(self):
        calls = []
        def command(args):
            calls.append(args)
            if args[0] == "docker":
                return ""
            if args[0] == "systemctl":
                return "\n".join(["active"] * 10)
            if "link" in args:
                self.assertEqual(args[-1], "ogstun_1")
                return json.dumps([dict(flags=["UP"], mtu=1400)])
            if "addr" in args:
                self.assertEqual(args[-1], "ogstun_1")
                return json.dumps([dict(addr_info=[dict(local="10.45.0.1", prefixlen=16)])])
            self.assertEqual(args[-1], "10.45.0.0/16")
            return json.dumps([dict(dev="ogstun_1")])
        identity = dict(amf=dict(url="http://127.0.0.5:9090/ue-info"), smf_url="http://127.0.0.4:9090/pdu-info")
        host = AUTO.Host(command, identity, ("du1",))
        host.database_check(subscribers=True)
        script = calls[-1][-1]
        self.assertIn("001010000000101", script)
        self.assertNotIn("001010000000102", script)
        self.assertNotIn("internet2", script)
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'{"items":[],"pager":{"page":0}}'
        opener = unittest.mock.MagicMock()
        opener.open.return_value = response
        with patch.object(AUTO.urllib.request, "build_opener", return_value=opener):
            host.core_check()

    def test_fr1_transport_requires_two_e2_and_one_f1_associations(self):
        rows = "\n".join([
            "LISTEN 0 128 127.0.0.1:36421 0.0.0.0:*",
            "LISTEN 0 128 127.0.0.1:36422 0.0.0.0:*",
            "ESTAB 0 0 127.0.0.1:36421 127.0.0.1:40001",
            "ESTAB 0 0 127.0.0.1:36421 127.0.0.1:40002",
            "ESTAB 0 0 127.0.10.1:38472 127.0.10.2:40003",
            "ESTAB 0 0 127.0.0.1:45000 127.0.0.5:38412",
            "ESTAB 0 0 127.0.0.1:36422 127.0.0.1:45001",
        ])
        tcp = "LISTEN 0 128 127.0.0.1:8765 0.0.0.0:*"
        host = AUTO.Host(lambda args: rows if "sctp" in args else tcp, {}, ("du1",))
        ready = {"ric", "cu", "du1", "xapp"}
        host.transport_check(ready)
        host.command = lambda args: rows.replace("127.0.0.1:36421 127.0.0.1:40002", "127.0.0.1:36423 127.0.0.1:40002") if "sctp" in args else tcp
        with self.assertRaisesRegex(AUTO.Fault, "E2 association"):
            host.transport_check(ready)

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
        args.du1_only = len(sys.argv) > 3 and sys.argv[3] == "fr1"
        args.du2_wired20_only = len(sys.argv) > 3 and sys.argv[3] == "wired"
        args.stop_timeout = 0.5
        root = Path(sys.argv[2])
        supervisor = AUTO.Supervisor(args, root, FakeHost(root))
        sys.exit(supervisor.execute(plan(root, du1_only=args.du1_only,
                                         du2_wired20_only=args.du2_wired20_only), interactive=False))
    unittest.main()
