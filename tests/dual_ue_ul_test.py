#!/usr/bin/env python3
"""Test dynamic bearer discovery and concurrent-launch failure handling offline."""

import contextlib
import copy
from datetime import datetime
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("run_dual_ul", REPO / "scripts/dual_fr1/run_dual_ul.py")
UL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UL)


class Network:
    def __init__(self):
        self.modems, self.sims, self.bearers = {}, {}, {}
        self.addresses, self.routes = [], {}
        self.sources = ("10.45.0.3", "10.46.0.8")
        for ue, imei, imsi, apn, _, server, _, table in UL.ROLES:
            modem = f"/org/freedesktop/ModemManager1/Modem/{100 + ue}"
            sim = f"/org/freedesktop/ModemManager1/SIM/{200 + ue}"
            bearer = f"/org/freedesktop/ModemManager1/Bearer/{300 + ue}"
            source, interface = self.sources[ue - 1], f"wwan{ue + 5}"
            self.modems[modem] = {"modem.generic.equipment-identifier": imei,
                "modem.generic.device-identifier": f"identity-{ue}", "modem.generic.state": "connected",
                "modem.generic.access-technologies.length": "1", "modem.generic.access-technologies.value[1]": "5gnr",
                "modem.3gpp.operator-code": "00101",
                "modem.generic.sim": sim, "modem.generic.ports.value[1]": f"{interface} (net)",
                "modem.generic.bearers.value[1]": bearer}
            self.sims[sim] = {"sim.properties.active": "yes", "sim.properties.imsi": imsi}
            self.bearers[bearer] = {"bearer.status.connected": "yes", "bearer.status.suspended": "no",
                "bearer.properties.apn": apn, "bearer.ipv4-config.method": "static",
                "bearer.ipv4-config.address": source, "bearer.ipv4-config.prefix": "29",
                "bearer.ipv4-config.gateway": server, "bearer.status.interface": interface}
            self.addresses.append({"ifname": interface, "addr_info": [{"local": source, "prefixlen": 29}]})
            self.routes[server] = {"dev": interface, "table": table, "prefsrc": source}
        self.iperf = []
        self.processes = []
        self.codes = (0, 0)
        self.spawn_failure = False
        self.interrupt = False
        self.kill_required = False
        self.list_reads = 0
        self.identity_change = False

    def read(self, *command):
        if command == ("mmcli", "-L"):
            self.list_reads += 1
            if self.identity_change and self.list_reads == 2:
                self.modems[next(iter(self.modems))]["modem.generic.device-identifier"] = "new-identity"
            return "\n".join(self.modems)
        if command[0] == "mmcli":
            info = {"-m": self.modems, "-i": self.sims, "-b": self.bearers}[command[1]][command[2]]
            return "\n".join(f"{key} : {value}" for key, value in info.items())
        if command == ("ip", "-j", "-4", "addr", "show"):
            return json.dumps(self.addresses)
        if command[:6] == ("ip", "-N", "-j", "-4", "route", "get"):
            route = copy.deepcopy(self.routes[command[6]])
            if "from" in command:
                expected = next(bearer["bearer.ipv4-config.address"] for bearer in self.bearers.values()
                    if bearer["bearer.ipv4-config.gateway"] == command[6] and bearer["bearer.status.connected"] == "yes")
                if command[-1] != expected:
                    raise ValueError("stale source address")
            return json.dumps([route])
        raise AssertionError(command)

    def popen(self, command, stdout, stderr):
        self.iperf.append(command)
        if self.spawn_failure and len(self.iperf) == 2:
            raise OSError("fixture second launch failed")
        process = Process(self, len(self.iperf) - 1)
        self.processes.append(process)
        stdout.write("[fixture] 1.00 Mbits/sec sender\n[fixture] 1.00 Mbits/sec receiver\niperf Done.\n")
        stdout.flush()
        return process


class Process:
    def __init__(self, network, index):
        self.network, self.index = network, index
        self.pid = 9000 + index
        self.code = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        if self.network.interrupt and not self.terminated:
            self.network.interrupt = False
            raise KeyboardInterrupt()
        if self.terminated and self.network.kill_required and not self.killed:
            raise subprocess.TimeoutExpired("fixture", timeout)
        self.code = -9 if self.killed else -15 if self.terminated else self.network.codes[self.index]
        return self.code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class DualULTest(unittest.TestCase):
    def setUp(self):
        self.network = Network()
        self.temp = tempfile.TemporaryDirectory(prefix="falcon-dual-ul-test-")
        self.addCleanup(self.temp.cleanup)
        for target, name, replacement in ((UL, "read", self.network.read),
                                          (UL.subprocess, "Popen", self.network.popen)):
            mock = patch.object(target, name, replacement)
            mock.start()
            self.addCleanup(mock.stop)
        self.stdout = io.StringIO()
        capture = contextlib.redirect_stdout(self.stdout)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def run_launcher(self, check_only=False):
        return UL.run(check_only=check_only, output_root=self.temp.name)

    def summary(self):
        files = list(Path(self.temp.name).glob("*/summary.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text())

    def assert_preflight_failure(self, message):
        with self.assertRaisesRegex(ValueError, message):
            self.run_launcher()
        self.assertEqual(self.network.iperf, [])
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_discovers_reallocated_addresses_and_changed_interfaces_without_old_values(self):
        self.assertEqual(self.run_launcher(), 0)
        self.assertEqual([command[command.index("-B") + 1] for command in self.network.iperf], list(self.network.sources))
        self.assertEqual([link["interface"] for link in self.summary()["links"]], ["wwan6", "wwan7"])
        self.assertEqual(self.summary()["status"], "completed")
        self.assertEqual([link["exit_code"] for link in self.summary()["links"]], [0, 0])
        started = datetime.fromisoformat(self.summary()["started_at"])
        ended = datetime.fromisoformat(self.summary()["ended_at"])
        self.assertIsNotNone(started.utcoffset())
        self.assertLessEqual(started, ended)

    def test_ue2_disconnected_starts_neither_client(self):
        self.network.modems["/org/freedesktop/ModemManager1/Modem/102"]["modem.generic.state"] = "registered"
        self.assert_preflight_failure("UE2: modem is not connected")

    def test_wrong_sim_starts_neither_client(self):
        self.network.sims["/org/freedesktop/ModemManager1/SIM/201"]["sim.properties.imsi"] = "wrong-imsi"
        self.assert_preflight_failure("UE1: active SIM")

    def test_mmcli_indexed_access_technology_array_passes(self):
        self.assertEqual(self.run_launcher(check_only=True), 0)
        self.assertEqual(self.network.iperf, [])

    def test_scalar_access_technology_is_also_supported(self):
        for info in self.network.modems.values():
            del info["modem.generic.access-technologies.length"]
            info["modem.generic.access-technologies"] = info.pop("modem.generic.access-technologies.value[1]")
        self.assertEqual(self.run_launcher(check_only=True), 0)

    def test_multiple_indexed_access_technologies_include_nr(self):
        for info in self.network.modems.values():
            info["modem.generic.access-technologies.length"] = "2"
            info["modem.generic.access-technologies.value[1]"] = "lte"
            info["modem.generic.access-technologies.value[2]"] = "5gnr"
        self.assertEqual(self.run_launcher(check_only=True), 0)

    def test_lte_only_is_still_rejected_before_traffic(self):
        self.network.modems["/org/freedesktop/ModemManager1/Modem/101"]["modem.generic.access-technologies.value[1]"] = "lte"
        self.assert_preflight_failure("not 5GNR.*lte")

    def test_missing_access_technology_is_reported_and_rejected(self):
        del self.network.modems["/org/freedesktop/ModemManager1/Modem/101"]["modem.generic.access-technologies.value[1]"]
        self.assert_preflight_failure("not 5GNR.*not reported")

    def test_ignores_disconnected_old_bearer(self):
        path = "/org/freedesktop/ModemManager1/Bearer/9"
        self.network.bearers[path] = {"bearer.status.connected": "no", "bearer.properties.apn": "internet"}
        self.network.modems["/org/freedesktop/ModemManager1/Modem/101"]["modem.generic.bearers.value[2]"] = path
        self.assertEqual(self.run_launcher(), 0)
        self.assertEqual(self.summary()["links"][0]["source"], "10.45.0.3")

    def test_duplicate_connected_apn_is_not_guessed(self):
        path = "/org/freedesktop/ModemManager1/Bearer/999"
        self.network.bearers[path] = copy.deepcopy(self.network.bearers["/org/freedesktop/ModemManager1/Bearer/301"])
        self.network.modems["/org/freedesktop/ModemManager1/Modem/101"]["modem.generic.bearers.value[2]"] = path
        self.assert_preflight_failure("exactly one connected internet bearer")

    def test_wifi_route_is_not_accepted(self):
        self.network.routes["10.45.0.1"] = {"dev": "wifi", "table": 254, "prefsrc": "10.20.91.243"}
        self.assert_preflight_failure("does not use its WWAN")

    def test_missing_destination_rule_is_not_accepted(self):
        original = self.network.read
        def read(*command):
            if command[:6] == ("ip", "-N", "-j", "-4", "route", "get") and "from" not in command:
                return json.dumps([{"dev": "wifi", "table": 254, "prefsrc": "10.20.91.243"}])
            return original(*command)
        with patch.object(UL, "read", read):
            self.assert_preflight_failure("ordinary traffic")

    def test_missing_current_host_address_is_not_accepted(self):
        self.network.addresses[0]["addr_info"] = []
        self.assert_preflight_failure("bearer address/prefix is not installed")

    def test_wrong_prefix_is_not_accepted(self):
        self.network.addresses[0]["addr_info"][0]["prefixlen"] = 30
        self.assert_preflight_failure("bearer address/prefix is not installed")

    def test_wrong_apn_is_not_accepted(self):
        self.network.bearers["/org/freedesktop/ModemManager1/Bearer/302"]["bearer.properties.apn"] = "internet"
        self.assert_preflight_failure("connected internet2 bearer")

    def test_identity_change_before_launch_starts_neither_client(self):
        self.network.identity_change = True
        self.assert_preflight_failure("identity changed during preflight")

    def test_check_only_does_not_create_logs_or_start_traffic(self):
        self.assertEqual(self.run_launcher(check_only=True), 0)
        self.assertEqual(self.network.iperf, [])
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_real_process_failure_is_recorded_as_failed(self):
        self.network.codes = (0, 1)
        self.assertEqual(self.run_launcher(), 1)
        self.assertEqual(self.summary()["status"], "failed")
        self.assertEqual([link["exit_code"] for link in self.summary()["links"]], [0, 1])

    def test_second_launch_failure_stops_first_client_and_records_abort(self):
        self.network.spawn_failure = True
        self.assertEqual(self.run_launcher(), 1)
        self.assertTrue(self.network.processes[0].terminated)
        self.assertEqual(self.summary()["status"], "aborted")
        self.assertEqual([link["exit_code"] for link in self.summary()["links"]], [-15, None])

    def test_keyboard_interrupt_reaps_both_children(self):
        self.network.interrupt = True
        self.assertEqual(self.run_launcher(), 1)
        self.assertTrue(all(process.terminated for process in self.network.processes))
        self.assertEqual(self.summary()["status"], "interrupted")

    def test_abort_escalates_to_kill_only_for_its_unresponsive_child(self):
        self.network.spawn_failure = True
        self.network.kill_required = True
        self.assertEqual(self.run_launcher(), 1)
        self.assertTrue(self.network.processes[0].killed)
        self.assertEqual(self.summary()["links"][0]["exit_code"], -9)


if __name__ == "__main__":
    unittest.main()
