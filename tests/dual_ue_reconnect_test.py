#!/usr/bin/env python3
"""Exercise continuous recovery with simulated modems, routes, clocks and locks."""

import contextlib
import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts/dual_fr1"))
sys.path.insert(0, str(REPO / "tests"))
from dual_ue_connect_test import Network, cell_text
import connect_ue as CONNECT
import reconnect_ue as WATCH


class Stop:
    def __init__(self, after=1, on_wait=None):
        self.after, self.on_wait = after, on_wait
        self.waits = []
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.waits.append(seconds)
        if self.on_wait:
            self.on_wait(len(self.waits))
        if len(self.waits) >= self.after:
            self.stopped = True


class ReconnectTest(unittest.TestCase):
    def setUp(self):
        self.network = Network()
        for module in (CONNECT, CONNECT.reset):
            for name in ("read", "change"):
                mock = patch.object(module, name, getattr(self.network, name))
                mock.start()
                self.addCleanup(mock.stop)
        for mock in (patch.object(CONNECT.reset, "table_aliases", lambda: self.network.aliases),
                     patch.object(CONNECT, "network_driver", lambda interface: "qmi_wwan"),
                     patch.dict(CONNECT.os.environ, {"SSH_CONNECTION": ""})):
            mock.start()
            self.addCleanup(mock.stop)
        self.console = io.StringIO()
        for redirect in (contextlib.redirect_stdout(self.console), contextlib.redirect_stderr(self.console)):
            redirect.__enter__()
            self.addCleanup(redirect.__exit__, None, None, None)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.log = io.StringIO()

    def watcher(self, ue=1, level=1, extra=(), stop=None):
        args = WATCH.arguments(["--ue", str(ue), "--verbose", str(level), *extra])
        directory = self.root / f"ue{ue}"
        directory.mkdir(exist_ok=True)
        return WATCH.Watcher(args, directory, self.log, stop)

    def connect(self, ue=1):
        return CONNECT.Connection(ue).run()

    def disconnects(self):
        return [cmd for cmd in self.network.changes if cmd[-1] == "--simple-disconnect"]

    def test_cli_levels_defaults_and_invalid_parameters(self):
        args = WATCH.arguments(["--ue", "2"])
        self.assertEqual((args.interval, args.verbose), (1, 1))
        for options in (("--verbose", "0"), ("--verbose", "4"), ("--verbose",),
                        ("--interval", "0"), ("--interval", "nan"), ("--interval", "inf"),
                        ("--max-attempts", "0"), ("--registration-timeout", "301"),
                        ("--redial-after", "0"), ("--redial-cooldown", "-1")):
            with self.subTest(options=options), self.assertRaises(SystemExit):
                WATCH.arguments(["--ue", "1", *options])

    def test_minimal_only_attempt_number_and_result_and_full_log_is_saved(self):
        watcher = self.watcher(extra=("--once",))
        with patch.object(WATCH, "SHARED_LOCK", str(self.root / "network.lock")):
            self.assertEqual(watcher.run(), 0)
        self.assertEqual(self.console.getvalue(), "UE1 / FR1 attempt 1 ... SUCCESS\n")
        self.assertIn("[1/9]", self.log.getvalue())
        self.assertIn("packets transmitted", self.log.getvalue())
        result = json.loads((watcher.directory / "attempts.jsonl").read_text())
        self.assertEqual((result["status"], result["source"]), ("connected", "10.45.0.9"))
        self.assertTrue(json.loads((watcher.directory / "summary.json").read_text())["last_connection_verified"])
        self.assertTrue(all(cmd[cmd.index("-c") + 1] == "1" for cmd in self.network.pings))

    def test_normal_steps_and_full_output_have_identical_operations(self):
        operations = []
        for level in (1, 2, 3):
            self.network = Network()
            # Existing patches dispatch to the original network, so replace them
            # for this comparison rather than changing only the test attribute.
            with patch.object(CONNECT, "read", self.network.read), \
                    patch.object(CONNECT.reset, "read", self.network.read), \
                    patch.object(CONNECT, "change", self.network.change), \
                    patch.object(CONNECT.reset, "change", self.network.change):
                self.console.seek(0)
                self.console.truncate(0)
                self.watcher(level=level).attempt()
                operations.append(list(self.network.changes))
                output = self.console.getvalue()
                self.assertEqual("[1/9]" in output, level >= 2)
                self.assertEqual("packets transmitted" in output, level == 3)
                self.assertEqual("$ mmcli" in output, level == 3)
        self.assertEqual(operations[0], operations[1])
        self.assertEqual(operations[1], operations[2])

    def test_healthy_monitor_does_not_reconnect_or_print_extra_attempts(self):
        self.connect()
        self.network.changes.clear()
        self.console.seek(0)
        self.console.truncate(0)
        watcher = self.watcher(stop=Stop(after=3), extra=("--interval", "0.25"))
        with patch.object(WATCH, "SHARED_LOCK", str(self.root / "network.lock")):
            watcher.run()
        self.assertEqual(watcher.attempts, 1)
        self.assertEqual(watcher.stop.waits, [.25, .25, .25])
        self.assertEqual(self.network.changes, [])
        self.assertEqual(self.console.getvalue(), "UE1 / FR1 attempt 1 ... SUCCESS\n")

    def test_link_drop_after_initial_success_is_detected_and_reconnected(self):
        modem = next(iter(self.network.modems))

        def drop(index):
            if index == 1:
                imei, interface, _ = self.network.modems[modem]
                self.network.modems[modem] = (imei, interface, "registered")
                self.network.bearers[modem] = {key: "no" for key in self.network.bearers[modem]}

        watcher = self.watcher(stop=Stop(after=2, on_wait=drop))
        survivor = self.network.survivor(1)
        with patch.object(WATCH, "SHARED_LOCK", str(self.root / "network.lock")):
            watcher.run()
        self.assertEqual(watcher.attempts, 2)
        self.assertEqual(self.console.getvalue().count("SUCCESS"), 2)
        self.assertEqual(self.network.survivor(1), survivor)

    def test_failed_attempts_wait_between_operations_and_stop_at_limit(self):
        self.network.ping_failure = True
        watcher = self.watcher(stop=Stop(after=10), extra=("--interval", "2.5", "--max-attempts", "3"))
        with patch.object(WATCH, "SHARED_LOCK", str(self.root / "network.lock")):
            self.assertEqual(watcher.run(), 1)
        self.assertEqual(watcher.stop.waits, [2.5, 2.5])
        self.assertEqual(self.disconnects(), [])  # Threshold reached; redial would be attempt 4.
        self.assertEqual(self.console.getvalue().splitlines(), [f"UE1 / FR1 attempt {i} ... FAIL" for i in (1, 2, 3)])

    def test_suspended_pdu_redials_each_role_and_installs_new_ip(self):
        for ue in (1, 2):
            with self.subTest(ue=ue):
                self.connect(ue)
                other = self.network.survivor(ue)
                self.network.settings[ue]["suspended"] = "yes"
                change = self.network.change

                def allocate(*command):
                    change(*command)
                    if command[0] == "mmcli" and command[-1].startswith("--simple-connect="):
                        self.network.settings[ue].update(suspended="no", source=f"10.{44 + ue}.0.57")

                with patch.object(CONNECT, "change", allocate):
                    watcher = self.watcher(ue)
                    watcher.attempt()
                self.assertTrue(watcher.healthy)
                self.assertEqual(self.network.survivor(ue), other)
                record = json.loads((watcher.directory / "attempts.jsonl").read_text().splitlines()[-1])
                self.assertEqual(record["source"], f"10.{44 + ue}.0.57")
                self.assertEqual(record["redial_reason"], "suspended")
                self.assertTrue(CONNECT.Connection(ue).configured(record))
                self.assertIn(CONNECT.ROLES[ue]["block"], [r["priority"] for r in self.network.rules])

    def test_ping_failures_trigger_redial_then_recover(self):
        self.network.ping_failure = True
        watcher = self.watcher(extra=("--redial-after", "2"))
        watcher.attempt()
        watcher.attempt()
        self.assertEqual(self.disconnects(), [])
        change = self.network.change

        def restore(*command):
            change(*command)
            if command[-1] == "--simple-disconnect":
                self.network.ping_failure = False

        with patch.object(CONNECT, "change", restore):
            watcher.attempt()
        self.assertEqual(len(self.disconnects()), 1)
        self.assertTrue(watcher.healthy)
        self.assertEqual(watcher.ping_failures, 0)

    def test_forced_redial_cooldown_prevents_disconnect_storm(self):
        self.network.ping_failure = True
        watcher = self.watcher(extra=("--redial-after", "1", "--redial-cooldown", "30"))
        with patch.object(WATCH.time, "monotonic", return_value=100):
            watcher.attempt()
            watcher.attempt()
            watcher.attempt()
        self.assertEqual(len(self.disconnects()), 1)
        with patch.object(WATCH.time, "monotonic", return_value=131):
            watcher.attempt()
        self.assertEqual(len(self.disconnects()), 2)

    def test_changed_ip_is_rebuilt_without_forced_disconnect(self):
        self.network.ping_failure = True
        watcher = self.watcher(extra=("--redial-after", "1"))
        watcher.attempt()
        self.network.ping_failure = False
        self.network.settings[1]["source"] = "10.45.0.62"
        watcher.attempt()
        self.assertEqual(self.disconnects(), [])
        self.assertTrue(watcher.healthy)
        self.assertEqual(self.network.addresses[0]["addr_info"], [dict(local="10.45.0.62", prefixlen=29)])

    def test_wrong_cell_identity_foreign_apn_and_foreign_rule_never_force_disconnect(self):
        self.connect()
        modem = next(iter(self.network.modems))
        for fault in ("cell", "imsi", "apn", "rule"):
            with self.subTest(fault=fault):
                settings = dict(self.network.settings[1])
                rules = list(self.network.rules)
                self.network.settings[1]["suspended"] = "yes"
                if fault == "cell":
                    self.network.settings[1]["cell"] = cell_text(2)
                elif fault == "imsi":
                    self.network.settings[1]["imsi"] = "999999999999999"
                elif fault == "apn":
                    self.network.settings[1]["apn"] = "foreign"
                else:
                    self.network.rules.append(dict(priority=10151, src="all", dst="8.8.8.8", table=151))
                self.network.changes.clear()
                self.watcher().attempt()
                self.assertEqual(self.network.changes, [])
                self.assertEqual(self.network.modems[modem][2], "connected")
                self.network.settings[1] = settings
                self.network.rules = rules

    def test_failed_disconnect_does_not_flush_or_connect(self):
        self.connect()
        before = list(self.network.addresses[0]["addr_info"])
        self.network.settings[1]["suspended"] = "yes"
        self.network.changes.clear()
        self.network.fail = ("mmcli", "-m", next(iter(self.network.modems)), "--simple-disconnect")
        watcher = self.watcher()
        watcher.attempt()
        self.assertFalse(watcher.healthy)
        self.assertEqual(self.network.changes, [self.network.fail])
        self.assertEqual(self.network.addresses[0]["addr_info"], before)
        self.assertIsNotNone(watcher.last_redial)

    def test_changing_bearer_counters_do_not_prevent_suspended_recovery(self):
        self.connect()
        self.network.settings[1]["suspended"] = "yes"
        read, change = self.network.read, self.network.change
        counter = 0

        def read_counters(*command):
            nonlocal counter
            output = read(*command)
            if command[:2] == ("mmcli", "-b"):
                counter += 1
                output += f"\nbearer.stats.duration : {counter}\n"
            return output

        def restore(*command):
            change(*command)
            if command[-1].startswith("--simple-connect="):
                self.network.settings[1]["suspended"] = "no"

        watcher = self.watcher()
        with patch.object(CONNECT, "read", read_counters), patch.object(CONNECT, "change", restore):
            watcher.attempt()
        self.assertTrue(watcher.healthy)
        self.assertEqual(len(self.disconnects()), 1)

    def test_allocation_change_before_disconnect_is_rejected(self):
        self.connect()
        self.network.settings[1]["suspended"] = "yes"
        active = WATCH.Recovery.active
        calls = 0

        def drift(session):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.network.settings[1]["source"] = "10.45.0.61"
            return active(session)

        watcher = self.watcher()
        self.network.changes.clear()
        with patch.object(WATCH.Recovery, "active", drift):
            watcher.attempt()
        self.assertFalse(watcher.healthy)
        self.assertEqual(self.network.changes, [])
        self.assertIn("Bearer changed before disconnect", self.log.getvalue())

    def test_route_error_at_ping_step_does_not_count_as_ping_failure(self):
        routes = CONNECT.Connection.routes
        calls = 0

        def fail_late(session, bearer):
            nonlocal calls
            calls += 1
            if session.stage == "ping":
                raise subprocess.CalledProcessError(2, ["ip", "route", "get"], stderr="route changed")
            return routes(session, bearer)

        watcher = self.watcher(extra=("--redial-after", "1"))
        with patch.object(CONNECT.Connection, "routes", fail_late):
            watcher.attempt()
        self.assertFalse(watcher.healthy)
        self.assertEqual(watcher.ping_failures, 0)
        watcher.attempt()
        self.assertTrue(watcher.healthy)
        self.assertEqual(self.disconnects(), [])

    def test_health_probe_refuses_wifi_route_and_detects_mid_ping_rule_loss(self):
        self.connect()
        self.network.ordinary_wrong = True
        self.network.pings.clear()
        with self.assertRaisesRegex(ValueError, "Ordinary route"):
            WATCH.probe(CONNECT.Connection(1))
        self.assertEqual(self.network.pings, [])
        self.network.ordinary_wrong = False
        read = self.network.read

        def lose_rule(*command):
            output = read(*command)
            if command[0] == "ping":
                self.network.rules = [rule for rule in self.network.rules if rule["priority"] != 10153]
            return output

        with patch.object(CONNECT, "read", lose_rule):
            with self.assertRaises(subprocess.CalledProcessError):
                WATCH.probe(CONNECT.Connection(1))
        self.assertEqual(len(self.network.pings), 1)  # Ordinary ping is not sent over Wi-Fi.

    def test_signal_during_pdu_attempt_runs_shutdown_and_does_not_restart(self):
        real_open, change = open, self.network.change

        def local_open(path, *args, **kwargs):
            if str(path).startswith("/run/lock/"):
                path = self.root / Path(path).name
            return real_open(path, *args, **kwargs)

        def interrupt(*command):
            change(*command)
            if command[-1].startswith("--simple-connect="):
                signal.getsignal(signal.SIGINT)(signal.SIGINT, None)

        previous = signal.getsignal(signal.SIGINT)
        with patch("builtins.open", local_open), patch.object(WATCH.os, "geteuid", return_value=0), \
                patch.object(WATCH.shutil, "which", return_value="installed"), \
                patch.object(CONNECT, "change", interrupt):
            self.assertEqual(WATCH.main(["--ue", "1", "--once", "--output-root", str(self.root)]), 130)
        self.assertIs(signal.getsignal(signal.SIGINT), previous)
        summary = json.loads(next(self.root.glob("falcon-*/summary.json")).read_text())
        self.assertEqual((summary["attempts"], summary["signal"]), (1, signal.SIGINT))
        record = json.loads(next(self.root.glob("falcon-*/attempts.jsonl")).read_text())
        self.assertEqual(record["status"], "interrupted")
        self.assertEqual(summary["shutdown"]["status"], "completed")
        self.assertEqual(self.network.modems[next(iter(self.network.modems))][2], "disabled")
        self.assertEqual(len(self.disconnects()), 1)

    def test_busy_shared_lock_waits_without_counting_attempt_or_mutating(self):
        path = str(self.root / "network.lock")
        watcher = self.watcher(stop=Stop(after=2))
        with patch.object(WATCH, "SHARED_LOCK", path), open(path, "a") as lock:
            WATCH.fcntl.flock(lock, WATCH.fcntl.LOCK_EX | WATCH.fcntl.LOCK_NB)
            watcher.run()
        self.assertEqual(watcher.attempts, 0)
        self.assertEqual(self.network.changes, [])
        self.assertEqual(self.console.getvalue(), "")
        with patch.object(WATCH, "SHARED_LOCK", path):
            watcher.stop = Stop()
            watcher.args.once = True
            self.assertEqual(watcher.run(), 0)

    def test_stop_during_wait_shuts_down_and_returns_signal_status(self):
        stop = Stop(after=1)
        watcher = self.watcher(stop=stop)
        watcher.exit_signal = signal.SIGTERM
        with patch.object(WATCH, "SHARED_LOCK", str(self.root / "network.lock")):
            self.assertEqual(watcher.run(), 143)
        self.assertEqual(len(self.disconnects()), 1)
        self.assertEqual(self.network.modems[next(iter(self.network.modems))][2], "disabled")
        summary = json.loads((watcher.directory / "summary.json").read_text())
        self.assertEqual(summary["shutdown"]["status"], "completed")
        self.assertIn("UE1 shutdown: SUCCESS", self.console.getvalue())

    def test_idle_sigint_shuts_down_either_role_without_reconnecting_or_touching_peer(self):
        for ue in (1, 2):
            with self.subTest(ue=ue):
                self.network.__dict__.update(Network().__dict__)
                self.connect(3 - ue)
                before = self.network.survivor(ue)

                def stop(index):
                    raise CONNECT.StopRequested(signal.SIGINT)

                watcher = self.watcher(ue, stop=Stop(after=5, on_wait=stop))
                with patch.object(WATCH, "SHARED_LOCK", str(self.root / "network.lock")):
                    self.assertEqual(watcher.run(), 130)
                self.assertEqual(watcher.attempts, 1)
                modem = next(path for path, data in self.network.modems.items() if data[0] == CONNECT.ROLES[ue]["imei"])
                self.assertEqual((self.network.modems[modem][2], self.network.bearers[modem]), ("disabled", {}))
                self.assertEqual(self.network.survivor(ue), before)

    def test_shutdown_failure_is_visible_even_at_minimal_verbosity(self):
        def stop(index):
            self.network.fail = ("mmcli", "-m", next(iter(self.network.modems)), "--simple-disconnect")
            raise CONNECT.StopRequested(signal.SIGINT)

        watcher = self.watcher(stop=Stop(after=5, on_wait=stop))
        with patch.object(WATCH, "SHARED_LOCK", str(self.root / "network.lock")):
            self.assertEqual(watcher.run(), 130)
        summary = json.loads((watcher.directory / "summary.json").read_text())
        self.assertEqual(summary["shutdown"]["status"], "failed")
        self.assertIn("UE1 shutdown: FAIL", self.console.getvalue())
        self.assertIn("Cleanup incomplete:", self.console.getvalue())

    def test_shutdown_waits_for_shared_lock_when_interrupted_before_first_attempt(self):
        self.connect()
        path = str(self.root / "network.lock")
        ready = threading.Event()
        status = CONNECT.status
        change = self.network.change

        def announce(message, **kwargs):
            if "shared network lock before UE shutdown" in message:
                ready.set()
            return status(message, **kwargs)

        def stop(index):
            raise CONNECT.StopRequested(signal.SIGINT)

        def check_lock(*command):
            with open(path, "a") as contender:
                with self.assertRaises(BlockingIOError):
                    WATCH.fcntl.flock(contender, WATCH.fcntl.LOCK_EX | WATCH.fcntl.LOCK_NB)
            change(*command)

        watcher = self.watcher(stop=Stop(after=5, on_wait=stop))
        with open(path, "a") as held:
            WATCH.fcntl.flock(held, WATCH.fcntl.LOCK_EX | WATCH.fcntl.LOCK_NB)

            def release():
                ready.wait(timeout=2)
                WATCH.fcntl.flock(held, WATCH.fcntl.LOCK_UN)

            worker = threading.Thread(target=release)
            worker.start()
            try:
                with patch.object(WATCH, "SHARED_LOCK", path), patch.object(CONNECT, "status", announce), \
                        patch.object(CONNECT, "change", check_lock):
                    self.assertEqual(watcher.run(), 130)
            finally:
                worker.join(timeout=3)
        self.assertTrue(ready.is_set())
        self.assertFalse(worker.is_alive())
        self.assertEqual(watcher.attempts, 0)
        self.assertEqual(self.network.modems[next(iter(self.network.modems))][2], "disabled")

    def test_main_duplicate_watch_rejected_and_role_locks_are_independent(self):
        real_open = open

        def local_open(path, *args, **kwargs):
            if str(path).startswith("/run/lock/"):
                path = self.root / Path(path).name
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", local_open), patch.object(WATCH.os, "geteuid", return_value=0), \
                patch.object(WATCH.shutil, "which", return_value="installed"):
            with open("/run/lock/falcon-ue1-reconnect.lock", "a") as lock:
                WATCH.fcntl.flock(lock, WATCH.fcntl.LOCK_EX | WATCH.fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError, "already has an active connection or reconnect script"):
                    WATCH.main(["--ue", "1", "--once", "--output-root", str(self.root)])
                self.assertEqual(WATCH.main(["--ue", "2", "--once", "--output-root", str(self.root)]), 0)


if __name__ == "__main__":
    unittest.main()
