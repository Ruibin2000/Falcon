#!/usr/bin/env python3
"""Exercise UE connection and failure paths without touching hardware or networking."""

import contextlib
import copy
import io
import ipaddress
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import termios
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts/dual_fr1"))
sys.path.insert(0, str(REPO / "tests"))
import connect_ue as CONNECT
from dual_ue_reset_test import Kernel as ResetKernel


def kv_text(fields):
    return "\n".join(f"{key} : {value}" for key, value in fields.items())


def cell_text(ue, **overrides):
    role = CONNECT.ROLES[ue]
    cell = {"cell type": "5gnr", "serving": "yes", "operator id": "00101", "tac": "7",
            "ci": f"{role['nci']:X}", "physical ci": f"{role['pci']:X}", "nrarfcn": str(role["carrier"])}
    cell.update(overrides)
    return ", ".join(f"{key}: {value}" for key, value in cell.items())


class Network(ResetKernel):
    def __init__(self):
        super().__init__()
        self.addresses[0]["addr_info"] = []
        self.addresses[1]["addr_info"] = []
        self.rules = [rule for rule in self.rules if rule["priority"] in (0, 32766, 32767)]
        self.routes = [route for route in self.routes if route.get("dev") == "wifi"]
        self.links.update(wwan0=(1500, "DOWN"), wwan1=(1500, "DOWN"))
        self.settings = {}
        for ue, (path, (imei, interface, _)) in enumerate(self.modems.items(), 1):
            self.modems[path] = (imei, interface, "registered")
            self.bearers[path] = {next(iter(self.bearers[path])): "no"}
            self.settings[ue] = dict(imsi=CONNECT.ROLES[ue]["imsi"], technology="5gnr", plmn="00101",
                                     identity=f"device-{ue}", cell=cell_text(ue), mtu="1400", prefix="29",
                                     source="10.45.0.9" if ue == 1 else "10.46.0.34",
                                     apn=CONNECT.ROLES[ue]["apn"], suspended="no", method="static", sim_active="yes",
                                     registration="home", packet="attached")
        self.ping_failure = False
        self.ordinary_wrong = False
        self.bypass_after_reset = False
        self.drift_on_connect = False
        self.cell_queries = 0
        self.pings = []
        self.reads = []

    def role(self, modem):
        return list(self.modems).index(modem) + 1

    def device(self, interface):
        modem = next(path for path, (_, name, _) in self.modems.items() if name == interface)
        return Path(f"/sys/mock/ue{self.role(modem)}")

    def lookup(self, command):
        destination = command[command.index("get") + 1]
        source = command[command.index("from") + 1] if "from" in command else None
        if ((self.ordinary_wrong and source is None and any(r.get("table") in (151, 152) for r in self.rules))
                or (self.bypass_after_reset and not any(r.get("table") in (151, 152) for r in self.rules))):
            return json.dumps([dict(dev="wifi", prefsrc="10.20.91.243", table=254)])
        for rule in sorted(self.rules, key=lambda rule: rule["priority"]):
            if rule.get("src", "all") != "all" and (source is None or ipaddress.IPv4Address(source) not in ipaddress.IPv4Network(rule["src"], strict=False)):
                continue
            if rule.get("dst", "all") != "all" and ipaddress.IPv4Address(destination) not in ipaddress.IPv4Network(rule["dst"], strict=False):
                continue
            if rule.get("action") == "unreachable":
                raise subprocess.CalledProcessError(2, command, stderr="RTNETLINK answers: Network is unreachable")
            table = self.number(rule.get("table"))
            candidates = [route for route in self.routes if self.number(route["table"]) == table and
                          (route.get("dst") == "default" or ipaddress.IPv4Address(destination) in ipaddress.IPv4Network(route["dst"], strict=False))]
            if candidates:
                return json.dumps([candidates[0]])
        raise subprocess.CalledProcessError(2, command, stderr="Network is unreachable")

    def read(self, *command):
        self.reads.append(command)
        if command[:2] == ("mmcli", "-m"):
            if command[2] not in self.modems:
                raise subprocess.CalledProcessError(1, command, stderr="couldn't find modem")
            ue = self.role(command[2])
            config = self.settings[ue]
            if "--get-cell-info" in command:
                self.cell_queries += 1
                if config["cell"] is None:
                    raise subprocess.CalledProcessError(1, command, stderr="Unsupported")
                return kv_text({"modem.generic.cell-info.length": "1", "modem.generic.cell-info.value[1]": config["cell"]})
            return super().read(*command) + "\n" + kv_text({
                "modem.generic.device-identifier": config["identity"],
                "modem.generic.physdev": f"/sys/mock/ue{ue}",
                "modem.generic.access-technologies.value[1]": config["technology"],
                "modem.3gpp.operator-code": config["plmn"],
                "modem.3gpp.registration-state": config["registration"],
                "modem.3gpp.packet-service-state": config["packet"],
                "modem.generic.sim": f"/org/freedesktop/ModemManager1/SIM/{ue}"})
        if command[:2] == ("mmcli", "-i"):
            config = self.settings[int(command[2].rsplit("/", 1)[1])]
            return kv_text({"sim.properties.active": config["sim_active"], "sim.properties.imsi": config["imsi"]})
        if command[:2] == ("mmcli", "-b"):
            modem = next(path for path, bearers in self.bearers.items() if command[2] in bearers)
            config = self.settings[self.role(modem)]
            return super().read(*command) + "\n" + kv_text({
                "bearer.properties.apn": config["apn"], "bearer.status.suspended": config["suspended"],
                "bearer.status.interface": self.modems[modem][1], "bearer.ipv4-config.method": config["method"],
                "bearer.ipv4-config.address": config["source"], "bearer.ipv4-config.prefix": config["prefix"],
                "bearer.ipv4-config.mtu": config["mtu"]})
        if command[:6] == ("ip", "-j", "-6", "route", "show", "default"):
            return "[]"
        if command[:4] == ("ip", "-j", "link", "show"):
            names = [command[5]] if "dev" in command else list(self.links)
            return json.dumps([dict(ifname=name, mtu=self.links[name][0], flags=[self.links[name][1]]) for name in names])
        if command[:6] == ("ip", "-N", "-j", "-4", "route", "get"):
            return self.lookup(command)
        if command[0] == "ping":
            self.pings.append(command)
            if self.ping_failure:
                raise subprocess.CalledProcessError(1, command, output="5 packets transmitted, 0 received\n")
            return "5 packets transmitted, 5 received, 0% packet loss\n"
        return super().read(*command)

    def change(self, *command):
        if self.fail and tuple(command[:len(self.fail)]) == self.fail:
            self.changes.append(command)
            raise subprocess.CalledProcessError(1, command)
        if command[0] == "mmcli" and (command[-1] == "--disable" or command[-1].startswith("--delete-bearer=")):
            return super().change(*command)
        if command[0] == "mmcli":
            self.changes.append(command)
            path = command[2]
            imei, interface, _ = self.modems[path]
            if command[3] == "--enable":
                self.modems[path] = (imei, interface, "registered")
            elif command[3] == "--3gpp-register-in-operator=00101":
                self.modems[path] = (imei, interface, "registered")
                self.settings[self.role(path)].update(registration="home", packet="attached", plmn="00101", technology="5gnr")
            elif command[3] == "--simple-disconnect":
                self.modems[path] = (imei, interface, "registered")
                self.bearers[path] = {bearer: "no" for bearer in self.bearers[path]}
            elif command[3].startswith("--simple-connect="):
                self.modems[path] = (imei, interface, "connected")
                self.bearers[path] = {bearer: "yes" for bearer in self.bearers[path]}
                if self.drift_on_connect:
                    self.settings[self.role(path)]["cell"] = cell_text(3 - self.role(path))
            else:
                raise AssertionError(command)
        elif command[:4] == ("ip", "-4", "rule", "add"):
            self.changes.append(command)
            rule = dict(priority=int(command[5]), src="all", dst=command[command.index("to") + 1])
            if "from" in command:
                rule["src"] = command[command.index("from") + 1]
            if "lookup" in command:
                rule["table"] = int(command[-1])
            else:
                rule["action"] = command[-1]
            self.rules.append(rule)
        elif command[:4] == ("ip", "-4", "addr", "add"):
            self.changes.append(command)
            address = ipaddress.IPv4Interface(command[4])
            device = next(entry for entry in self.addresses if entry["ifname"] == command[6])
            device["addr_info"].append(dict(local=str(address.ip), prefixlen=address.network.prefixlen))
        elif command[:4] == ("ip", "-4", "route", "add"):
            self.changes.append(command)
            self.routes.append(dict(table=int(command[5]), dst=command[6], dev=command[8], prefsrc=command[-1]))
        else:
            super().change(*command)


class ConnectTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.lock_path = str(Path(self.temporary.name) / "network.lock")
        mock = patch.object(CONNECT, "NETWORK_LOCK", self.lock_path)
        mock.start()
        self.addCleanup(mock.stop)
        self.network = Network()
        self.real_change = CONNECT.change
        for module in (CONNECT, CONNECT.reset):
            for name in ("read", "change"):
                mock = patch.object(module, name, getattr(self.network, name))
                mock.start()
                self.addCleanup(mock.stop)
        for mock in (patch.object(CONNECT.reset, "table_aliases", lambda: self.network.aliases),
                     patch.object(CONNECT, "network_driver", lambda interface: "qmi_wwan"),
                     patch.object(CONNECT, "network_device", lambda interface: self.network.device(interface)),
                     patch.dict(CONNECT.os.environ, {"SSH_CONNECTION": ""})):
            mock.start()
            self.addCleanup(mock.stop)
        self.output = io.StringIO()
        for redirect in (contextlib.redirect_stdout(self.output), contextlib.redirect_stderr(self.output)):
            redirect.__enter__()
            self.addCleanup(redirect.__exit__, None, None, None)

    def session(self, ue=1, **kwargs):
        return CONNECT.Connection(ue, **kwargs)

    def no_connect(self):
        self.assertFalse(any(c[0] == "mmcli" and "--simple-connect=" in c[-1] for c in self.network.changes))

    def invoke_main(self, ue=1, verbose=False, check_only=False, exit_on_success=True):
        real_open = open
        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            def open_local_lock(path, *args, **kwargs):
                if str(path).startswith("/run/lock/falcon-"):
                    path = str(Path(temporary) / Path(path).name)
                return real_open(path, *args, **kwargs)
            argv = ["connect_ue.py", "--ue", str(ue), "--output-root", temporary]
            if verbose:
                argv.append("--verbose")
            if check_only:
                argv.append("--check-only")
            if exit_on_success:
                argv.append("--exit-on-success")
            with patch("builtins.open", open_local_lock), patch.object(CONNECT.os, "geteuid", return_value=0), \
                    patch.object(CONNECT.shutil, "which", return_value="installed"), patch.object(sys, "argv", argv), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = CONNECT.main()
            summary_path = next(Path(temporary).glob("*/summary.json"))
            return (exit_code, stdout.getvalue(), stderr.getvalue(),
                    json.loads(summary_path.read_text()), summary_path.with_name("run.log").read_text())

    def test_fresh_ue1_connects_and_both_ping_modes_pass(self):
        before = self.network.survivor(1)
        result = self.session().run()
        self.assertEqual(result["status"], "connected")
        self.assertEqual(result["source"], "10.45.0.9")
        self.assertEqual(result["prefix"], 29)
        self.assertEqual(self.network.survivor(1), before)
        self.assertEqual(len(self.network.pings), 2)
        self.assertIn("-I", self.network.pings[0])
        self.assertNotIn("-I", self.network.pings[1])
        self.assertGreaterEqual(self.network.cell_queries, 3)

    def test_both_roles_run_sequentially_and_preserve_first(self):
        self.session().run()
        first = copy.deepcopy((self.network.addresses[0], self.network.modems[next(iter(self.network.modems))]))
        result = self.session(2).run()
        self.assertEqual(result["source"], "10.46.0.34")
        self.assertEqual(result["path"], "FR3")
        self.assertEqual((self.network.addresses[0], self.network.modems[next(iter(self.network.modems))]), first)
        self.assertEqual({r["priority"] for r in self.network.rules}, {0, 32766, 32767, 10151, 10152, 10153, 10154, 20151, 10161, 10162, 10163, 10164, 20152})

    def test_second_run_reuses_healthy_pdu_and_host_path(self):
        self.session().run()
        self.network.changes.clear()
        self.session().run()
        self.assertEqual(self.network.changes, [])

    def test_disabled_modem_enabled_before_cell_check(self):
        path = next(iter(self.network.modems))
        self.network.modems[path] = (*self.network.modems[path][:2], "disabled")
        self.session().run()
        self.assertEqual(self.network.changes[0], ("mmcli", "-m", path, "--enable"))

    def test_wrong_or_incomplete_cell_stops_before_pdu_or_host_mutation(self):
        for cell in (cell_text(2), cell_text(1, **{"physical ci": "2"}),
                     cell_text(1, ci="--"), cell_text(1, serving="no"), cell_text(1, **{"cell type": "lte"}),
                     cell_text(1, **{"operator id": "99999"}), cell_text(1, tac="8"),
                     cell_text(1, nrarfcn="1"), None, "--"):
            with self.subTest(cell=cell):
                self.network.settings[1]["cell"] = cell
                with self.assertRaises(CONNECT.CellError):
                    self.session().run()
                self.assertEqual(self.network.changes, [])

    def test_wrong_registration_stops_before_pdu_or_network(self):
        for key, value in (("plmn", "99999"), ("technology", "lte"), ("technology", "lte, 5gnr")):
            with self.subTest(key=key, value=value):
                previous = self.network.settings[1][key]
                self.network.settings[1][key] = value
                with self.assertRaises(CONNECT.CellError):
                    self.session().run()
                self.assertEqual(self.network.changes, [])
                self.network.settings[1][key] = previous

    def test_wrong_sim_stops_before_any_mutation(self):
        self.network.settings[1]["imsi"] = CONNECT.ROLES[2]["imsi"]
        with self.assertRaisesRegex(ValueError, "IMSI mismatch"):
            self.session().run()
        self.assertEqual(self.network.changes, [])

    def test_reused_modem_index_identity_change_is_rejected(self):
        session = self.session()
        session.discover()
        self.network.settings[1]["identity"] = "replacement-device"
        with self.assertRaisesRegex(ValueError, "identity changed"):
            session.registered(True)
        self.assertEqual(self.network.changes, [])

    def test_registration_wait_reports_states_and_later_succeeds(self):
        session = self.session(registration_timeout=6)
        session.discover()
        modem = next(iter(self.network.modems))
        imei, interface, _ = self.network.modems[modem]
        self.network.modems[modem] = (imei, interface, "enabled")
        clock = [0.0]
        waits = []

        def advance(seconds):
            waits.append(seconds)
            clock[0] += seconds
            if clock[0] >= 4:
                self.network.modems[modem] = (imei, interface, "registered")

        with patch.object(CONNECT.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(CONNECT.time, "sleep", advance):
            info = session.registered(True)
        self.assertEqual(info["modem.generic.state"], "registered")
        self.assertEqual(waits, [0.25] * 16)
        self.assertIn("state=enabled", self.output.getvalue())
        self.assertIn("state=registered", self.output.getvalue())
        self.assertEqual(session.result["registration"]["elapsed_seconds"], 4)
        self.assertEqual(self.network.changes, [])

    def test_connected_state_does_not_bypass_searching_3gpp_registration(self):
        session = self.session(registration_timeout=3)
        session.discover()
        modem = next(iter(self.network.modems))
        self.network.modems[modem] = (*self.network.modems[modem][:2], "connected")
        self.network.settings[1].update(registration="searching", packet="detached")
        clock, waits = [0.0], []
        def advance(seconds):
            waits.append(seconds)
            clock[0] += seconds
        with patch.object(CONNECT.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(CONNECT.time, "sleep", advance):
            with self.assertRaisesRegex(CONNECT.CellError, "3gpp=searching packet=detached"):
                session.registered(True)
        self.assertEqual(waits, [0.25] * 12)
        self.assertFalse(self.network.changes)

    def test_registration_timeout_retains_last_state_and_does_not_oversleep(self):
        session = self.session(registration_timeout=3)
        session.discover()
        modem = next(iter(self.network.modems))
        self.network.modems[modem] = (*self.network.modems[modem][:2], "enabled")
        clock, waits = [0.0], []

        def advance(seconds):
            waits.append(seconds)
            clock[0] += seconds

        with patch.object(CONNECT.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(CONNECT.time, "sleep", advance):
            with self.assertRaisesRegex(CONNECT.CellError, "after 3s: state=enabled"):
                session.registered(True)
        self.assertEqual(waits, [0.25] * 12)
        self.assertEqual(session.result["registration"]["state"], "enabled")
        self.assertEqual(session.result["registration"]["plmn"], "00101")
        self.assertEqual(self.network.changes, [])

    def test_registration_query_is_announced_before_a_blocked_read(self):
        session = self.session()
        session.discover()
        with patch.object(session, "checked_modem", side_effect=subprocess.TimeoutExpired(["mmcli", "-m"], 75)):
            with self.assertRaises(subprocess.TimeoutExpired):
                session.registered(True)
        self.assertIn("Registration: querying current modem", self.output.getvalue())
        self.assertEqual(self.network.changes, [])

    def test_ctrl_c_is_reported_as_cancelled_with_exit_130(self):
        other = self.network.survivor(1)
        with patch.object(CONNECT.Connection, "registered", side_effect=KeyboardInterrupt):
            code, stdout, stderr, summary, log = self.invoke_main(verbose=True)
        self.assertEqual(code, 130)
        self.assertEqual(summary["status"], "interrupted")
        self.assertEqual(summary["stage"], "registration")
        self.assertIn("[2/9] Modem registration [CANCELLED]", stdout)
        self.assertIn("Interrupted by user (Ctrl+C)", stderr)
        self.assertIn("Interrupted by user", summary["error"])
        self.assertEqual(summary["shutdown"]["status"], "completed")
        self.assert_shutdown(1)
        self.assertEqual(self.network.survivor(1), other)

    def assert_shutdown(self, ue):
        modem = next(path for path, data in self.network.modems.items() if data[0] == CONNECT.ROLES[ue]["imei"])
        self.assertEqual(self.network.modems[modem][2], "disabled")
        self.assertEqual(self.network.bearers[modem], {})
        self.assertEqual(self.network.links[self.network.modems[modem][1]], (1500, "DOWN"))
        self.assertFalse(any(r.get("table") == CONNECT.ROLES[ue]["table"] for r in self.network.routes))
        self.assertTrue(any(r["priority"] == CONNECT.ROLES[ue]["block"] for r in self.network.rules))
        with self.assertRaises(subprocess.CalledProcessError):
            self.network.lookup(("ip", "-N", "-j", "-4", "route", "get", CONNECT.ROLES[ue]["server"]))

    def test_default_success_holds_without_probes_and_releases_global_lock(self):
        before = self.network.survivor(1)
        observed = []

        def pause():
            observed.append((len(self.network.reads), len(self.network.pings)))
            with open("/run/lock/falcon-ue-connect.lock", "a") as lock:
                CONNECT.fcntl.flock(lock, CONNECT.fcntl.LOCK_EX | CONNECT.fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "already has an active"):
                with CONNECT.role_lock(1):
                    self.fail("Idle holder must still own this UE")
            with CONNECT.role_lock(2):
                pass
            self.assertEqual(observed[-1], (len(self.network.reads), len(self.network.pings)))
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)

        with patch.object(CONNECT.signal, "pause", side_effect=pause) as waiting:
            code, stdout, _, summary, _ = self.invoke_main(exit_on_success=False)
        self.assertEqual(waiting.call_count, 1)
        self.assertEqual(code, 130)
        self.assertIn("waiting for Ctrl+C", stdout)
        self.assertEqual(len(self.network.pings), 2)  # Only the two initial verification commands.
        self.assertEqual(summary["lifecycle"], "stopped")
        self.assertEqual(summary["shutdown"]["status"], "completed")
        self.assert_shutdown(1)
        self.assertEqual(self.network.survivor(1), before)

    def test_check_only_success_exits_without_idle_wait(self):
        self.session().run()
        self.network.changes.clear()
        with patch.object(CONNECT, "wait_for_stop") as waiting:
            code, _, _, summary, _ = self.invoke_main(check_only=True, exit_on_success=False)
        waiting.assert_not_called()
        self.assertEqual((code, summary["status"]), (0, "checked"))
        self.assertEqual(self.network.changes, [])

    def test_interrupt_during_pdu_host_rebuild_and_ping_shuts_down_only_selected_role(self):
        for ue in (1, 2):
            for phase in ("pdu", "host", "ping"):
                with self.subTest(ue=ue, phase=phase):
                    self.network.__dict__.update(Network().__dict__)
                    survivor = self.network.survivor(ue)
                    other_modem = list(self.network.modems)[2 - ue]
                    other_radio = copy.deepcopy((self.network.modems[other_modem], self.network.bearers[other_modem]))
                    read, change = self.network.read, self.network.change

                    def mutate(*command):
                        change(*command)
                        if ((phase == "pdu" and command[-1].startswith("--simple-connect="))
                                or (phase == "host" and command[:4] == ("ip", "-4", "addr", "add"))):
                            raise CONNECT.StopRequested(signal.SIGINT)

                    def query(*command):
                        output = read(*command)
                        if phase == "ping" and command[0] == "ping":
                            raise CONNECT.StopRequested(signal.SIGINT)
                        return output

                    with patch.object(CONNECT, "change", mutate), patch.object(CONNECT, "read", query):
                        code, _, _, summary, _ = self.invoke_main(ue)
                    self.assertEqual(code, 130)
                    self.assertEqual(summary["shutdown"]["status"], "completed")
                    self.assert_shutdown(ue)
                    self.assertEqual(self.network.survivor(ue), survivor)
                    self.assertEqual((self.network.modems[other_modem], self.network.bearers[other_modem]), other_radio)

    def test_sigterm_uses_same_shutdown_and_restores_signal_handlers(self):
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

        def terminate(session, enable):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

        with patch.object(CONNECT.Connection, "registered", terminate):
            code, _, _, summary, _ = self.invoke_main()
        self.assertEqual(code, 143)
        self.assertEqual(summary["signal"], signal.SIGTERM)
        self.assert_shutdown(1)
        self.assertEqual({sig: signal.getsignal(sig) for sig in previous}, previous)

    def test_repeat_stop_signals_cannot_interrupt_disconnect_delete_disable(self):
        self.session().run()
        change = self.network.change
        signals_seen = []

        def repeat(*command):
            if command[0] == "mmcli":
                for sig in (signal.SIGINT, signal.SIGTERM):
                    self.assertIs(signal.getsignal(sig), signal.SIG_IGN)
                    os.kill(os.getpid(), sig)
                    signals_seen.append(sig)
            change(*command)

        with patch.object(CONNECT.Connection, "registered", side_effect=KeyboardInterrupt), \
                patch.object(CONNECT, "change", repeat):
            code, _, _, summary, _ = self.invoke_main()
        self.assertEqual(code, 130)
        self.assertGreaterEqual(len(signals_seen), 6)
        self.assertEqual(summary["shutdown"]["status"], "completed")
        self.assert_shutdown(1)

    def test_shutdown_failure_is_reported_and_does_not_print_success(self):
        self.session().run()
        self.network.fail = ("mmcli", "-m", next(iter(self.network.modems)), "--simple-disconnect")
        with patch.object(CONNECT.Connection, "registered", side_effect=KeyboardInterrupt):
            code, stdout, stderr, summary, _ = self.invoke_main()
        self.assertEqual(code, 130)
        self.assertEqual(summary["shutdown"]["status"], "failed")
        self.assertIn("cleanup is incomplete", stderr)
        self.assertNotIn("shutdown [OK]", stdout)
        self.assertTrue(any(r["priority"] == 20151 for r in self.network.rules))

    def test_check_only_ctrl_c_also_runs_requested_shutdown(self):
        self.session().run()
        with patch.object(CONNECT.Connection, "registered", side_effect=KeyboardInterrupt):
            code, _, _, summary, _ = self.invoke_main(check_only=True)
        self.assertEqual(code, 130)
        self.assertEqual(summary["shutdown"]["status"], "completed")
        self.assert_shutdown(1)

    def test_shutdown_rediscovers_renumbered_modem_instead_of_reusing_old_path(self):
        old = next(iter(self.network.modems))
        new = "/org/freedesktop/ModemManager1/Modem/999"
        read = self.network.read

        def renumber(*command):
            output = read(*command)
            if command[0] == "ping":
                self.network.modems = {new: self.network.modems[old], **{p: d for p, d in self.network.modems.items() if p != old}}
                self.network.bearers[new] = self.network.bearers.pop(old)
                raise CONNECT.StopRequested(signal.SIGINT)
            return output

        with patch.object(CONNECT, "read", renumber):
            code, _, _, summary, _ = self.invoke_main()
        self.assertEqual((code, summary["shutdown"]["status"]), (130, "completed"))
        self.assert_shutdown(1)
        self.assertIn(("mmcli", "-m", new, "--disable"), self.network.changes)
        self.assertNotIn(("mmcli", "-m", old, "--disable"), self.network.changes)

    def test_cell_drift_after_pdu_stops_before_wwan_configuration(self):
        self.network.drift_on_connect = True
        with self.assertRaises(CONNECT.CellError):
            self.session().run()
        self.assertEqual(self.network.addresses[0]["addr_info"], [])
        self.assertEqual([r["priority"] for r in self.network.rules if r["priority"] < 30000 and r["priority"] != 0], [20151])
        self.assertEqual(self.network.pings, [])

    def test_foreign_apn_is_never_disconnected_or_replaced(self):
        path = next(iter(self.network.modems))
        self.network.bearers[path] = {bearer: "yes" for bearer in self.network.bearers[path]}
        self.network.settings[1]["apn"] = "somebody-else"
        with self.assertRaisesRegex(ValueError, "different APN"):
            self.session().run()
        self.no_connect()
        self.assertFalse(any(c[0] == "mmcli" for c in self.network.changes))

    def test_bad_bearer_address_prefix_mtu_or_suspended_state_stops(self):
        for key, value in (("source", "10.46.0.2"), ("source", "10.45.0.1"), ("prefix", "99"),
                           ("mtu", "0"), ("mtu", "--"), ("suspended", "yes"), ("method", "dhcp")):
            with self.subTest(key=key, value=value):
                network = Network()
                self.network.__dict__.update(network.__dict__)
                self.network.settings[1][key] = value
                with self.assertRaises(ValueError):
                    self.session().run()
                self.assertEqual(self.network.addresses[0]["addr_info"], [])
                self.assertEqual(self.network.pings, [])

    def test_reserved_priority_foreign_rule_is_preserved(self):
        foreign = dict(priority=10151, src="all", dst="192.168.1.1", table=151)
        self.network.rules.append(foreign)
        with self.assertRaisesRegex(ValueError, "foreign rule"):
            self.session().run()
        self.assertIn(foreign, self.network.rules)
        self.assertFalse(any("flush" in c for c in self.network.changes))

    def test_independent_block_collision_stops_before_connect(self):
        self.network.rules.append(dict(priority=20151, src="all", dst="10.46.0.1", action="unreachable"))
        with self.assertRaisesRegex(ValueError, "block"):
            self.session().run()
        self.assertEqual(self.network.changes, [])

    def test_earlier_catch_all_policy_stops_without_deleting_it(self):
        foreign = dict(priority=100, src="all", table=999)
        self.network.rules.append(foreign)
        with self.assertRaisesRegex(ValueError, "earlier policy"):
            self.session().run()
        self.assertIn(foreign, self.network.rules)

    def test_another_network_address_on_wwan_is_preserved(self):
        self.network.addresses[0]["addr_info"].append(dict(local="192.168.1.10", prefixlen=24))
        with self.assertRaisesRegex(ValueError, "another network"):
            self.session().run()
        self.assertEqual(self.network.addresses[0]["addr_info"][0]["local"], "192.168.1.10")

    def test_spark_host_is_rejected_before_modem_enable(self):
        self.network.addresses.append(dict(ifname="ogstun_2", addr_info=[dict(local="10.46.0.1", prefixlen=16)]))
        with self.assertRaisesRegex(ValueError, "UE laptop"):
            self.session().run()
        self.assertEqual(self.network.changes, [])

    def test_failed_host_rebuild_clears_partial_path_and_retains_block(self):
        self.network.fail = ("ip", "-4", "route", "add")
        with self.assertRaises(subprocess.CalledProcessError):
            self.session().run()
        self.assertEqual(self.network.addresses[0]["addr_info"], [])
        self.assertFalse(any(r["priority"] in CONNECT.ROLES[1]["priorities"] for r in self.network.rules))
        self.assertTrue(any(r["priority"] == 20151 for r in self.network.rules))
        self.assertFalse(any(r["table"] == 151 for r in self.network.routes))
        with self.assertRaises(subprocess.CalledProcessError):
            self.network.lookup(("ip", "-N", "-j", "-4", "route", "get", "10.45.0.1"))

    def test_reset_must_actually_block_ordinary_route_before_rebuild(self):
        self.network.bypass_after_reset = True
        with self.assertRaisesRegex(ValueError, "still routable"):
            self.session().run()
        self.assertEqual(self.network.pings, [])
        self.assertTrue(any(r["priority"] == 20151 for r in self.network.rules))

    def test_source_bound_route_alone_cannot_pass(self):
        self.network.ordinary_wrong = True
        with self.assertRaisesRegex(ValueError, "Ordinary.*route"):
            self.session().run()
        self.assertEqual(self.network.pings, [])

    def test_ping_failure_is_not_accepted_and_keeps_built_path_for_inspection(self):
        self.network.ping_failure = True
        session = self.session()
        with self.assertRaises(subprocess.CalledProcessError):
            session.run()
        self.assertEqual(session.stage, "ping")
        self.assertEqual(session.result["status"], "started")
        self.assertIn("0 received", session.result["source_bound_ping"])
        self.assertTrue(session.configured(session.bearer()))

    def test_check_only_is_read_only_and_starts_no_ping(self):
        self.session().run()
        self.network.changes.clear()
        self.network.pings.clear()
        result = self.session().run(check_only=True)
        self.assertEqual(result["status"], "checked")
        self.assertEqual(self.network.changes, [])
        self.assertEqual(self.network.pings, [])

    def test_reset_after_success_keeps_ordinary_wifi_fallback_block(self):
        self.session().run()
        CONNECT.reset.reset(1)
        self.assertTrue(any(r["priority"] == 20151 for r in self.network.rules))
        with self.assertRaises(subprocess.CalledProcessError):
            self.network.lookup(("ip", "-N", "-j", "-4", "route", "get", "10.45.0.1"))

    def test_serial_fallback_reads_only_if_mm_cannot_prove_cell(self):
        self.network.settings[1]["cell"] = None
        cell = dict(pci=1, nci=0x66C000, plmn="00101", tac=7, arfcn=643680, band=78, source="AT query")
        with patch.object(CONNECT, "serial_cell", return_value=cell) as query:
            self.session(at_port="/dev/ttyUSB2").run()
            self.assertEqual(query.call_count, 3)

    def test_complete_wrong_mm_cell_cannot_be_overridden_by_at_port(self):
        self.network.settings[1]["cell"] = cell_text(2)
        with patch.object(CONNECT, "serial_cell") as query:
            with self.assertRaises(CONNECT.CellError):
                self.session(at_port="/dev/ttyUSB2").run()
            query.assert_not_called()
        self.assertEqual(self.network.changes, [])

    def test_serial_fallback_does_not_run_when_mm_matches(self):
        with patch.object(CONNECT, "serial_cell") as query:
            self.session(at_port="/dev/ttyUSB2").run()
            query.assert_not_called()

    def test_dynamic_modem_index_and_wwan_name(self):
        old = next(iter(self.network.modems))
        new = "/org/freedesktop/ModemManager1/Modem/999"
        original = self.network.modems[old]
        self.network.modems = {new: (original[0], "wwan7", original[2]), **{p: m for p, m in self.network.modems.items() if p != old}}
        self.network.bearers[new] = self.network.bearers.pop(old)
        self.network.addresses[0]["ifname"] = "wwan7"
        self.network.links["wwan7"] = self.network.links.pop("wwan0")
        result = self.session().run()
        self.assertEqual((result["modem"], result["interface"]), (new, "wwan7"))

    def test_old_source_only_path_and_reallocated_ip_are_rebuilt(self):
        self.session().run()
        self.network.rules = [r for r in self.network.rules if r["priority"] not in (10153, 10154)]
        self.network.settings[1]["source"] = "10.45.0.17"
        result = self.session().run()
        self.assertEqual(result["source"], "10.45.0.17")
        self.assertEqual(self.network.addresses[0]["addr_info"], [dict(local="10.45.0.17", prefixlen=29)])
        self.assertEqual(sum(r["priority"] in CONNECT.ROLES[1]["priorities"] for r in self.network.rules), 4)

    def test_explicit_disconnect_recovers_suspended_pdu_with_new_ip_for_either_role(self):
        for ue, source in ((1, "10.45.0.25"), (2, "10.46.0.42")):
            with self.subTest(ue=ue):
                self.network.__dict__.update(Network().__dict__)
                self.session(1).run()
                self.session(2).run()
                survivor = self.network.survivor(ue)
                modem = list(self.network.modems)[ue - 1]
                other = list(self.network.modems)[2 - ue]
                peer = copy.deepcopy((self.network.modems[other], self.network.bearers[other]))
                self.network.settings[ue]["suspended"] = "yes"
                self.network.changes.clear()
                with self.assertRaisesRegex(ValueError, "suspended"):
                    self.session(ue).run()
                self.assertEqual(self.network.changes, [])
                CONNECT.reset.reset(ue, disconnect=True)
                self.assertEqual(self.network.modems[modem][2], "registered")
                self.assertTrue(any(r["priority"] == CONNECT.ROLES[ue]["block"] for r in self.network.rules))
                with self.assertRaises(subprocess.CalledProcessError):
                    self.network.lookup(("ip", "-N", "-j", "-4", "route", "get", CONNECT.ROLES[ue]["server"]))
                # The radio/5GC returns an unsuspended bearer with a new allocation.
                self.network.settings[ue].update(suspended="no", source=source)
                result = self.session(ue).run()
                self.assertEqual((result["status"], result["source"]), ("connected", source))
                self.assertEqual(self.network.survivor(ue), survivor)
                self.assertEqual((self.network.modems[other], self.network.bearers[other]), peer)
                modem_commands = [c for c in self.network.changes if c[0] == "mmcli"]
                self.assertEqual([c[-1] for c in modem_commands], ["--simple-disconnect",
                                 f"--simple-connect=apn={CONNECT.ROLES[ue]['apn']},ip-type=ipv4"])
                self.assertTrue(all(c[2] == modem for c in modem_commands))

    def test_explicit_disconnect_then_restart_recovers_ping_failure_with_same_ip(self):
        self.session(1).run()
        self.session(2).run()
        survivor = self.network.survivor(2)
        self.network.ping_failure = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.session(2).run()
        CONNECT.reset.reset(2, disconnect=True)
        self.network.ping_failure = False
        result = self.session(2).run()
        self.assertEqual((result["status"], result["source"]), ("connected", "10.46.0.34"))
        self.assertEqual(self.network.survivor(2), survivor)

    def test_failed_explicit_disconnect_keeps_existing_path_and_guard_for_inspection(self):
        self.session(2).run()
        addresses = copy.deepcopy(self.network.addresses)
        modem = list(self.network.modems)[1]
        self.network.changes.clear()
        self.network.fail = ("mmcli", "-m", modem, "--simple-disconnect")
        with self.assertRaises(subprocess.CalledProcessError):
            CONNECT.reset.reset(2, disconnect=True)
        self.assertEqual(self.network.addresses, addresses)
        self.assertEqual(self.network.changes, [("mmcli", "-m", modem, "--simple-disconnect")])
        self.assertTrue(any(r["priority"] == 20152 for r in self.network.rules))

    def test_other_ue_changes_during_ping_are_independent(self):
        original_read = self.network.read
        def read_with_change(*command):
            output = original_read(*command)
            if command[0] == "ping":
                self.network.links["wwan1"] = (1300, "UP")
            return output
        with patch.object(CONNECT, "read", read_with_change):
            self.assertEqual(self.session().run()["status"], "connected")

    def test_other_ue_changes_during_connect_are_independent(self):
        original_change = self.network.change
        def change_with_drift(*command):
            original_change(*command)
            if command[0] == "mmcli":
                self.network.links["wwan1"] = (1300, "UP")
        with patch.object(CONNECT, "change", change_with_drift):
            self.assertEqual(self.session().run()["status"], "connected")
        self.assertEqual(self.network.links["wwan1"], (1300, "UP"))

    def test_management_changes_during_pdu_or_ping_still_fail_verification(self):
        for phase in ("pdu", "ping"):
            with self.subTest(phase=phase):
                self.network.__dict__.update(Network().__dict__)
                read, change = self.network.read, self.network.change

                def drift():
                    self.network.links["wifi"] = (1300, "UP")

                def changing_read(*command):
                    output = read(*command)
                    if phase == "ping" and command[0] == "ping":
                        drift()
                    return output

                def changing_change(*command):
                    change(*command)
                    if phase == "pdu" and command[-1].startswith("--simple-connect="):
                        drift()

                with patch.object(CONNECT, "read", changing_read), patch.object(CONNECT, "change", changing_change):
                    with self.assertRaisesRegex(ValueError, "Management configuration changed"):
                        self.session().run()

    def test_peer_changes_during_our_kernel_writes_are_still_rejected(self):
        change = self.network.change

        def corrupt(*command):
            change(*command)
            if command[:4] == ("ip", "-4", "addr", "add"):
                self.network.links["wwan1"] = (1300, "UP")

        with patch.object(CONNECT, "change", corrupt):
            with self.assertRaisesRegex(ValueError, "other-UE configuration changed during host update"):
                self.session().run()

    def test_radio_and_ping_are_unlocked_but_kernel_writes_are_exclusive(self):
        read, change = self.network.read, self.network.change
        seen = set()

        def unlocked():
            with open(self.lock_path, "a") as contender:
                CONNECT.fcntl.flock(contender, CONNECT.fcntl.LOCK_EX | CONNECT.fcntl.LOCK_NB)

        def checked_read(*command):
            if command[0] in ("mmcli", "ping"):
                unlocked()
                seen.add(command[0])
            return read(*command)

        def checked_change(*command):
            if command[0] == "ip":
                with open(self.lock_path, "a") as contender:
                    with self.assertRaises(BlockingIOError):
                        CONNECT.fcntl.flock(contender, CONNECT.fcntl.LOCK_SH | CONNECT.fcntl.LOCK_NB)
                seen.add("host_write")
            else:
                unlocked()
                seen.add("radio_write")
            change(*command)

        with patch.object(CONNECT, "read", checked_read), patch.object(CONNECT, "change", checked_change):
            session = self.session()
            session.run()
            result = CONNECT.shutdown_on_interrupt(1, modem_cache=session.modem_cache)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(seen, {"mmcli", "ping", "host_write", "radio_write"})

    def test_changed_physical_wwan_owner_stops_before_host_reset(self):
        with patch.object(CONNECT, "network_device", return_value=Path("/sys/mock/other-modem")):
            with self.assertRaisesRegex(ValueError, "WWAN physical device changed"):
                self.session().run()
        self.assertFalse(any("flush" in command for command in self.network.changes))
        self.assertEqual(self.network.addresses[0]["addr_info"], [])

    def test_partial_rebuild_does_not_cleanup_a_replaced_physical_interface(self):
        change = self.network.change
        replaced = False
        changes_at_failure = []

        def owner(interface):
            return Path("/sys/mock/replacement") if replaced else self.network.device(interface)

        def fail_after_replacement(*command):
            nonlocal replaced
            change(*command)
            if command[:4] == ("ip", "-4", "addr", "add"):
                replaced = True
                changes_at_failure.append(len(self.network.changes))
                raise subprocess.CalledProcessError(1, command)

        with patch.object(CONNECT, "network_device", owner), patch.object(CONNECT, "change", fail_after_replacement):
            with self.assertRaises(subprocess.CalledProcessError):
                self.session().run()
        self.assertEqual(len(self.network.changes), changes_at_failure[0])
        self.assertIn("Cleanup incomplete", self.output.getvalue())
        self.assertTrue(any(rule["priority"] == 20151 for rule in self.network.rules))

    def test_two_ues_connect_concurrently_and_keep_separate_host_paths(self):
        # Share one simulated kernel between threads and synchronize both radio
        # connects. Host changes still use real flock on separate descriptors.
        barrier = threading.Barrier(2)
        change = self.network.change
        results, errors = {}, []
        wifi = self.network.links["wifi"]

        def together(*command):
            change(*command)
            if command[0] == "mmcli" and command[-1].startswith("--simple-connect="):
                barrier.wait(timeout=2)

        def worker(ue):
            try:
                results[ue] = self.session(ue).run()
            except BaseException as error:
                errors.append(error)

        with patch.object(CONNECT, "change", together):
            workers = [threading.Thread(target=worker, args=(ue,), daemon=True) for ue in (1, 2)]
            for worker_thread in workers:
                worker_thread.start()
            for worker_thread in workers:
                worker_thread.join(timeout=4)
        self.assertFalse(any(worker_thread.is_alive() for worker_thread in workers), "Concurrent startup stalled")
        self.assertEqual(errors, [])
        self.assertEqual(set(results), {1, 2})
        for ue, result in results.items():
            self.assertEqual(result["status"], "connected")
            self.assertTrue(self.session(ue).configured(result))
        self.assertEqual(self.network.links["wifi"], wifi)
        self.assertEqual({rule["priority"] for rule in self.network.rules if rule["priority"] in (20151, 20152)}, {20151, 20152})

    def test_multiple_active_bearers_require_manual_inspection(self):
        path = next(iter(self.network.modems))
        self.network.bearers[path] = {"/org/freedesktop/ModemManager1/Bearer/701": "yes",
                                     "/org/freedesktop/ModemManager1/Bearer/702": "yes"}
        with self.assertRaisesRegex(ValueError, "Multiple connected bearers"):
            self.session().run()
        self.no_connect()

    def test_serial_fallback_wrong_cell_stops_before_pdu(self):
        self.network.settings[1]["cell"] = None
        with patch.object(CONNECT, "serial_cell", return_value=dict(pci=2, nci=0x66C001)):
            with self.assertRaises(CONNECT.CellError):
                self.session(at_port="/dev/ttyUSB2").run()
        self.assertEqual(self.network.changes, [])

    def test_main_records_success_and_failed_serving_check(self):
        real_open = open
        with tempfile.TemporaryDirectory() as temporary:
            def open_local_lock(path, *args, **kwargs):
                if str(path).startswith("/run/lock/falcon-"):
                    path = str(Path(temporary) / Path(path).name)
                return real_open(path, *args, **kwargs)
            for wrong in (False, True):
                with self.subTest(wrong_cell=wrong):
                    root = Path(temporary) / str(wrong)
                    root.mkdir()
                    self.network.settings[1]["cell"] = cell_text(2 if wrong else 1)
                    with patch("builtins.open", open_local_lock), patch.object(CONNECT.os, "geteuid", return_value=0), \
                            patch.object(CONNECT.shutil, "which", return_value="installed"), \
                            patch.object(sys, "argv", ["connect_ue.py", "--ue", "1", "--exit-on-success", "--output-root", str(root)]):
                        status = CONNECT.main()
                    summary_path = next(root.glob("*/summary.json"))
                    summary = json.loads(summary_path.read_text())
                    log = summary_path.with_name("run.log").read_text()
                    self.assertEqual(status, 1 if wrong else 0)
                    self.assertEqual(summary["status"], "serial_check_required" if wrong else "connected")
                    self.assertEqual(summary_path.parent.stat().st_mode & 0o777, 0o700)
                    if wrong:
                        self.assertIn('AT+QNWLOCK="common/5g",1,643680,30,78', log)
                    else:
                        self.assertIn("5 received", summary["ordinary_ping"])
                        self.assertIn("PASS: UE1", log)

    def test_default_output_is_compact_and_full_details_are_still_logged(self):
        for ue in (1, 2):
            with self.subTest(ue=ue):
                self.network.__dict__.update(Network().__dict__)
                code, stdout, stderr, summary, log = self.invoke_main(ue)
                self.assertEqual((code, stderr, summary["status"]), (0, "", "connected"))
                for index in range(1, 10):
                    self.assertRegex(stdout, rf"\[{index}/9\] [^\n]+ \[OK\]")
                self.assertIn(f"PASS: UE{ue}", stdout)
                self.assertIn("Evidence saved:", stdout)
                self.assertNotIn("IMEI=", stdout)
                self.assertNotIn("5 packets transmitted", stdout)
                self.assertNotIn("UE1 reset complete", stdout)
                self.assertIn("IMEI=", log)
                self.assertIn("5 packets transmitted", log)
                self.assertIn("5 received", summary["ordinary_ping"])

    def test_verbose_shows_details_with_the_same_connection_operations(self):
        code, _, _, _, _ = self.invoke_main()
        self.assertEqual(code, 0)
        quiet_operations = list(self.network.changes)
        quiet_pings = list(self.network.pings)
        self.network.__dict__.update(Network().__dict__)
        code, stdout, stderr, summary, log = self.invoke_main(verbose=True)
        self.assertEqual((code, stderr, summary["status"]), (0, "", "connected"))
        self.assertIn("IMEI=", stdout)
        self.assertIn("PDU PASS:", stdout)
        self.assertIn("UE1 reset complete", stdout)
        self.assertIn("5 packets transmitted", stdout)
        self.assertIn("table 151", stdout)
        self.assertIn("5 packets transmitted", log)
        self.assertEqual(self.network.changes, quiet_operations)
        self.assertEqual(self.network.pings, quiet_pings)

    def test_quiet_cell_failure_keeps_manual_configuration_instructions_visible(self):
        self.network.settings[1]["cell"] = cell_text(2)
        code, stdout, stderr, summary, _ = self.invoke_main()
        self.assertEqual(code, 1)
        self.assertIn("[3/9] Serving cell ... [FAIL]", stdout)
        self.assertNotIn("[4/9]", stdout)
        self.assertNotIn("PASS: UE1", stdout)
        self.assertIn("STOP at serving cell", stderr)
        self.assertIn('AT+QNWLOCK="common/5g",1,643680,30,78', stderr)
        self.assertEqual(summary["status"], "serial_check_required")
        self.assertEqual(self.network.changes, [])

    def test_quiet_ping_failure_is_visible_without_raw_output_and_is_logged(self):
        self.network.ping_failure = True
        code, stdout, stderr, summary, log = self.invoke_main()
        self.assertEqual(code, 1)
        self.assertIn("[7/9] Source-bound ping ... [FAIL]", stdout)
        self.assertIn("STOP at ping", stderr)
        self.assertNotIn("5 packets transmitted", stdout + stderr)
        self.assertNotIn("PASS: UE1", stdout)
        self.assertIn("0 received", log)
        self.assertIn("0 received", summary["source_bound_ping"])
        self.assertEqual(summary["status"], "failed")

    def test_quiet_check_only_marks_ping_skipped_and_makes_no_changes(self):
        self.session().run()
        self.network.changes.clear()
        self.network.pings.clear()
        code, stdout, stderr, summary, _ = self.invoke_main(check_only=True)
        self.assertEqual((code, stderr, summary["status"]), (0, "", "checked"))
        self.assertIn("[7/9] Source-bound ping [SKIP: check-only]", stdout)
        self.assertIn("[8/9] Ordinary ping [SKIP: check-only]", stdout)
        self.assertIn("checked (ping not run)", stdout)
        self.assertEqual((self.network.changes, self.network.pings), ([], []))

    def test_reset_subprocess_output_uses_verbosity_and_complete_logging(self):
        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                stdout, stderr, log = io.StringIO(), io.StringIO(), io.StringIO()
                original = CONNECT.reset.change
                completed = subprocess.CompletedProcess(["ip", "test"], 0, "reset child stdout\n", "reset child stderr\n")
                # Use the real command runner with a fake subprocess; never touch the host.
                real_change = self.real_change
                with patch.object(CONNECT, "change", real_change), \
                        patch.object(CONNECT.subprocess, "run", return_value=completed), \
                        contextlib.redirect_stdout(CONNECT.Tee(stdout, log, verbose)), \
                        contextlib.redirect_stderr(CONNECT.Tee(stderr, log, verbose)), CONNECT.capture_reset_output():
                    CONNECT.reset.change("ip", "test")
                self.assertIs(CONNECT.reset.change, original)
                self.assertIn("+ ip test", log.getvalue())
                self.assertIn("reset child stdout", log.getvalue())
                self.assertIn("reset child stderr", log.getvalue())
                if verbose:
                    self.assertIn("reset child stdout", stdout.getvalue())
                    self.assertIn("reset child stderr", stderr.getvalue())
                else:
                    self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")


class CellParsingTest(unittest.TestCase):
    def test_mm_rejects_neighbor_and_ambiguous_serving_cells(self):
        with self.assertRaises(CONNECT.CellError):
            CONNECT.mm_serving_cell({"modem.generic.cell-info": cell_text(1, serving="no")})
        with self.assertRaises(CONNECT.CellError):
            CONNECT.mm_serving_cell({"modem.generic.cell-info.value[1]": cell_text(1),
                                     "modem.generic.cell-info.value[2]": cell_text(2)})

    def test_mm_hex_identifiers_and_optional_fields(self):
        cell = CONNECT.mm_serving_cell({"modem.generic.cell-info": "cell type: 5gnr, serving: yes, ci: 0066c000, physical-ci: 0x1"})
        self.assertEqual((cell["pci"], cell["nci"]), (1, 0x66C000))

    def test_real_archived_qeng_readbacks(self):
        for ue, name in ((1, "operator_ue1_readback.txt"), (2, "operator_ue2_coexistence_readback.txt")):
            text = (REPO / "docs/evidence/2026-10-13_du1_registration" / name).read_text()
            replies = [line for line in text.splitlines() if line.startswith('+QENG: "servingcell"')]
            self.assertTrue(replies)
            for reply in replies:
                cell = CONNECT.qeng_serving_cell(reply)
                self.assertEqual((cell["pci"], cell["nci"], cell["arfcn"], cell["band"], cell["plmn"]),
                                 (ue, CONNECT.ROLES[ue]["nci"], CONNECT.ROLES[ue]["ssb"], 78, "00101"))

    def test_qeng_search_and_nsa_are_not_sa_serving_proof(self):
        for reply in ('+QENG: "servingcell","SEARCH"', '+QENG: "servingcell","NOCONN","NR5G-NSA","TDD",001,01'):
            with self.assertRaises(CONNECT.CellError):
                CONNECT.qeng_serving_cell(reply)


class SerialQueryTest(unittest.TestCase):
    def test_query_only_serial_protocol_and_settings_restore(self):
        for wrong_imei in (False, True):
            with self.subTest(wrong_imei=wrong_imei):
                master, slave = os.openpty()
                original = termios.tcgetattr(slave)
                observed = []
                replies = {"AT+CGSN": "000000000000000" if wrong_imei else CONNECT.ROLES[1]["imei"],
                           "AT+CIMI": CONNECT.ROLES[1]["imsi"],
                           'AT+QENG="servingcell"': '+QENG: "servingcell","NOCONN","NR5G-SA","TDD",001,01,00066C000,1,7,643680,78,1,-95,-11,20,1,35'}
                def modem():
                    pending = b""
                    deadline = time.monotonic() + 3
                    expected = 1 if wrong_imei else 3
                    while len(observed) < expected and time.monotonic() < deadline:
                        if not select.select([master], [], [], 0.1)[0]:
                            continue
                        pending += os.read(master, 4096)
                        while b"\r" in pending:
                            raw, pending = pending.split(b"\r", 1)
                            command = raw.decode("ascii")
                            observed.append(command)
                            os.write(master, ("\r\n" + replies.get(command, "ERROR") + "\r\nOK\r\n").encode("ascii"))
                worker = threading.Thread(target=modem, daemon=True)
                worker.start()
                try:
                    with patch.object(CONNECT, "verify_at_port", return_value=Path(os.ttyname(slave))):
                        if wrong_imei:
                            with self.assertRaisesRegex(CONNECT.CellError, "identity mismatch"):
                                CONNECT.serial_cell("test-owned-port", {}, CONNECT.ROLES[1])
                        else:
                            cell = CONNECT.serial_cell("test-owned-port", {}, CONNECT.ROLES[1])
                            self.assertEqual((cell["pci"], cell["nci"]), (1, 0x66C000))
                    worker.join(timeout=4)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(observed, ["AT+CGSN"] if wrong_imei else ["AT+CGSN", "AT+CIMI", 'AT+QENG="servingcell"'])
                    self.assertEqual(termios.tcgetattr(slave), original)
                finally:
                    worker.join(timeout=4)
                    os.close(slave)
                    os.close(master)

    def test_usb_port_of_another_modem_is_rejected(self):
        with patch.object(CONNECT, "usb_parent", side_effect=[Path("/usb/modem2"), Path("/usb/modem1")]):
            with self.assertRaisesRegex(CONNECT.CellError, "does not belong"):
                CONNECT.verify_at_port("/dev/ttyUSB987", {"wwan0"})

    def test_busy_serial_port_is_rejected(self):
        descriptor = SimpleNamespace(resolve=lambda: Path("/dev/ttyUSB987"))
        process = SimpleNamespace(iterdir=lambda: [descriptor])
        with patch.object(CONNECT, "usb_parent", return_value=Path("/usb/modem1")), \
                patch.object(Path, "glob", return_value=[process]):
            with self.assertRaisesRegex(CONNECT.CellError, "busy"):
                CONNECT.verify_at_port("/dev/ttyUSB987", {"wwan0"})


class PduDisconnectTimeoutTest(unittest.TestCase):
    def test_disconnect_uses_two_second_client_limit_and_three_second_watchdog(self):
        command = ("mmcli", "-m", "owned-modem", "--simple-disconnect")
        output = io.StringIO()
        completed = subprocess.CompletedProcess(command, 0, stdout="disconnected\n", stderr="")
        with patch.object(CONNECT.subprocess, "run", return_value=completed) as run, \
                patch.object(CONNECT.time, "monotonic", side_effect=[10, 10.4]), \
                contextlib.redirect_stdout(output):
            CONNECT.change(*command)
        self.assertEqual(run.call_args.args[0], (*command, "--timeout=2"))
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertTrue(run.call_args.kwargs["start_new_session"])
        self.assertIn("elapsed=0.400s", output.getvalue())

    def test_dbus_timeout_preserves_the_error_and_elapsed_time(self):
        command = ("mmcli", "-m", "owned-modem", "--simple-disconnect")
        completed = subprocess.CompletedProcess(command, 1, stdout="", stderr="Timeout was reached\n")
        output, error = io.StringIO(), io.StringIO()
        with patch.object(CONNECT.subprocess, "run", return_value=completed), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), \
                self.assertRaises(subprocess.CalledProcessError):
            CONNECT.change(*command)
        self.assertIn("Timeout was reached", error.getvalue())
        self.assertIn("PDU disconnect client elapsed=", output.getvalue())

    def test_process_watchdog_failure_is_not_reported_as_success(self):
        output = io.StringIO()
        with patch.object(CONNECT.subprocess, "run", side_effect=subprocess.TimeoutExpired("mmcli", 3)), \
                contextlib.redirect_stdout(output), self.assertRaises(subprocess.TimeoutExpired):
            CONNECT.change("mmcli", "-m", "owned-modem", "--simple-disconnect")
        self.assertIn("process watchdog=3s", output.getvalue())

    def test_other_commands_keep_their_existing_timeout(self):
        for command in (("mmcli", "-m", "owned-modem", "--enable"),
                        ("ip", "link", "set", "dev", "owned-wwan", "up")):
            with self.subTest(command=command), \
                    patch.object(CONNECT.subprocess, "run", return_value=subprocess.CompletedProcess(command, 0)) as run, \
                    contextlib.redirect_stdout(io.StringIO()):
                CONNECT.change(*command)
                self.assertEqual(run.call_args.args[0], command)
                self.assertEqual(run.call_args.kwargs["timeout"], 75)


class StopSignalTest(unittest.TestCase):
    def test_cleanup_children_survive_repeated_foreground_group_stop_signals(self):
        # The harness owns a separate session, so this test never signals the
        # test runner or any real modem process. Its child deliberately resets
        # SIGINT/SIGTERM to defaults, as an external executable might do.
        child = """import os, signal
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)
parent_group = os.getpgid(os.getppid())
os.killpg(parent_group, signal.SIGINT)
os.killpg(parent_group, signal.SIGTERM)
print('cleanup child survived')
"""
        harness = (f"import sys\nsys.path.insert(0, {str(REPO / 'scripts/dual_fr1')!r})\n"
                   "import connect_ue as c\n"
                   "with c.ignore_stop_signals():\n"
                   f"    print(c.read(sys.executable, '-c', {child!r}))\n"
                   f"    c.change(sys.executable, '-c', {child!r})\n")
        result = subprocess.run([sys.executable, "-B", "-c", harness], capture_output=True, text=True,
                                timeout=10, start_new_session=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(result.stdout.count("cleanup child survived"), 2)


if __name__ == "__main__":
    unittest.main()
