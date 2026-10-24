#!/usr/bin/env python3
"""Guarded radio recovery against simulated modems and a real pseudo-terminal."""

import contextlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import termios
import threading
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/dual_fr1"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dual_ue_reconnect_test as fixture
import connect_ue as CONNECT
import reconnect_ue as WATCH


class FakeAT:
    def __init__(self, ue=2, wrong_identity=None, reject=None, wrong_lock=False, correct_settings=False,
                 registered=False):
        self.role = CONNECT.ROLES[ue]
        self.registered = registered
        self.wrong_identity, self.reject, self.wrong_lock = wrong_identity, reject, wrong_lock
        self.settings = dict(mode_pref="NR5G" if correct_settings else "LTE",
                             nr5g_disable_mode="2" if correct_settings else "1",
                             nr5g_band="77:78" if correct_settings else "41")
        self.lock = f'{ue},{self.role["ssb"]},30,78' if correct_settings else "0"
        self.commands = []

    def reply(self, command):
        self.commands.append(command)
        if command == self.reject:
            return "\r\n+CME ERROR: 902\r\n"
        if command in ("AT+CGSN", "AT+CIMI"):
            value = self.role["imei"] if command == "AT+CGSN" else self.role["imsi"]
            if command == self.wrong_identity:
                value = "000000000000000"
            response = value
        elif command.startswith("AT+QNWPREFCFG="):
            name, _, value = command.split("=", 1)[1].partition(",")
            name = name.strip('"')
            if value:
                self.settings[name] = value
                response = ""
            else:
                response = f'+QNWPREFCFG: "{name}",{self.settings[name]}'
        elif command.startswith('AT+QNWLOCK="common/5g",'):
            if not self.wrong_lock:
                self.lock = command.partition('",')[2]
            response = ""
        elif command == 'AT+QNWLOCK="common/5g"':
            response = '+QNWLOCK: "common/5g",' + self.lock
        elif command == 'AT+QENG="servingcell"':
            response = (f'+QENG: "servingcell","NOCONN","NR5G-SA","TDD",001,01,'
                        f'{self.role["nci"]:09X},{self.role["pci"]},7,{self.role["ssb"]},78,1,-95,-11,20,1,35'
                        if self.registered else '+QENG: "servingcell","SEARCH"')
        elif command == "AT+C5GREG?":
            response = "+C5GREG: 0,1" if self.registered else "+C5GREG: 0,2"
        else:
            return "\r\nERROR\r\n"
        return "\r\n" + response + "\r\nOK\r\n"

    @contextlib.contextmanager
    def port(self):
        master, slave = os.openpty()
        original = termios.tcgetattr(slave)
        stop = threading.Event()

        def modem():
            pending = b""
            while not stop.is_set():
                if not select.select([master], [], [], 0.02)[0]:
                    continue
                pending += os.read(master, 4096)
                while b"\r" in pending:
                    raw, pending = pending.split(b"\r", 1)
                    os.write(master, self.reply(raw.decode("ascii")).encode("ascii"))

        worker = threading.Thread(target=modem, daemon=True)
        worker.start()
        try:
            with patch.object(CONNECT, "verify_at_port", return_value=Path(os.ttyname(slave))):
                yield self
        finally:
            stop.set()
            worker.join(timeout=2)
            restored = termios.tcgetattr(slave)
            os.close(slave)
            os.close(master)
            if worker.is_alive() or restored != original:
                raise AssertionError("AT transaction did not release/restore the serial port")


class ImmediateRegistrationRequest(WATCH.RegistrationRequest):
    """Legacy scenario fixture; never launches a real mmcli process."""
    def start(self):
        self.data["status"] = "waiting"
        try:
            CONNECT.change(*self.command)
        except KeyboardInterrupt:
            self.finish("interrupted", None)
            raise
        except WATCH.ERRORS as error:
            self.finish("process_timeout" if isinstance(error, subprocess.TimeoutExpired) else "failed",
                        getattr(error, "returncode", None))
            self.data.update(error=str(error), stderr=getattr(error, "stderr", "") or "")
            raise
        else:
            self.finish("returned", 0)


class RadioRecoveryTest(unittest.TestCase):
    setUp = fixture.ReconnectTest.setUp
    watcher = fixture.ReconnectTest.watcher
    connect = fixture.ReconnectTest.connect
    disconnects = fixture.ReconnectTest.disconnects

    def auto(self, ue=2, **kwargs):
        watcher = self.watcher(ue=ue, extra=("--auto-cell-lock", "--registration-grace", "0",
                                           "--at-port", "owned-at-port"), **kwargs)
        watcher.registration_factory = ImmediateRegistrationRequest
        watcher.startup_radio = dict(status="completed")  # These scenarios exercise later radio failures.
        return watcher

    def wrong_cell(self, ue=2):
        self.network.settings[ue]["cell"] = fixture.cell_text(3 - ue)

    def test_cli_requires_owned_port_and_valid_cooldown(self):
        for options in (("--auto-cell-lock",), ("--cell-lock-cooldown", "0"),
                        ("--cell-lock-cooldown", "nan")):
            with self.subTest(options=options), self.assertRaises(SystemExit):
                WATCH.arguments(["--ue", "2", *options])
        self.assertFalse(WATCH.arguments(["--ue", "2"]).auto_cell_lock)

    def test_cli_registration_request_timeout_is_bounded_below_process_watchdog(self):
        self.assertEqual(WATCH.arguments(["--ue", "2"]).registration_request_timeout, 5)
        for value in ("0", "71", "nan"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                WATCH.arguments(["--ue", "2", "--registration-request-timeout", value])
        args = WATCH.arguments(["--ue", "2", "--registration-request-timeout", "12"])
        self.assertEqual(args.registration_request_timeout, 12)

    def test_selected_dbus_wait_is_sent_to_mmcli_and_request_return_is_recorded(self):
        self.wrong_cell()
        watcher = self.auto(level=2)
        watcher.args.registration_request_timeout = 12
        with FakeAT().port():
            watcher.attempt()
        record = json.loads((watcher.directory / "attempts.jsonl").read_text())
        request = record["radio_recovery"]["registration_request"]
        self.assertEqual((request["status"], request["mmcli_timeout_seconds"], request["process_timeout_seconds"]),
                         ("returned", 12, 17))
        self.assertGreaterEqual(request["elapsed_seconds"], 0)
        self.assertTrue(any(cmd[-1] == "--timeout=12" for cmd in self.network.changes))
        self.assertIn("mmcli limit 12s", self.console.getvalue())
        self.assertFalse(watcher.healthy)  # A returned registration call is not connectivity proof.

    def test_dbus_error_and_process_watchdog_have_separate_request_evidence(self):
        for process_timeout in (False, True):
            with self.subTest(process_timeout=process_timeout):
                self.wrong_cell()
                watcher = self.auto()
                records_path = watcher.directory / "attempts.jsonl"
                records_path.unlink(missing_ok=True)
                def change(*command):
                    if process_timeout:
                        raise CONNECT.subprocess.TimeoutExpired(command, 75)
                    raise CONNECT.subprocess.CalledProcessError(1, command, stderr="Timeout was reached")
                with FakeAT().port(), patch.object(CONNECT, "change", change):
                    watcher.attempt()
                evidence = json.loads(records_path.read_text())["radio_recovery"]
                request = evidence["registration_request"]
                self.assertEqual(request["status"], "process_timeout" if process_timeout else "failed")
                self.assertEqual(evidence["status"], "failed")
                if not process_timeout:
                    self.assertEqual(request["stderr"], "Timeout was reached")
                self.assertIn("elapsed_seconds", request)
                self.assertEqual(self.console.getvalue().splitlines()[-1], "UE2 / FR3 attempt 1 ... FAIL")

    def test_ctrl_c_while_registration_waits_records_interruption_and_shuts_down(self):
        self.wrong_cell()
        watcher = self.auto()
        original_change = self.network.change
        def change(*command):
            if "--3gpp-register-in-operator=00101" in command:
                raise CONNECT.StopRequested(signal.SIGINT)
            return original_change(*command)
        with FakeAT().port(), patch.object(CONNECT, "change", change):
            self.assertEqual(watcher.run(), 130)
        evidence = json.loads((watcher.directory / "attempts.jsonl").read_text())["radio_recovery"]
        self.assertEqual(evidence["registration_request"]["status"], "interrupted")
        self.assertEqual(evidence["status"], "interrupted")
        summary = json.loads((watcher.directory / "summary.json").read_text())
        self.assertEqual(summary["shutdown"]["status"], "completed")
        self.assertEqual(summary["registration_request_timeout"], 5)
        self.assertEqual(self.network.modems[next(iter(self.network.modems))][2], "registered")

    def test_both_roles_restore_own_lock_with_verified_readback(self):
        for ue in (1, 2):
            with self.subTest(ue=ue), FakeAT(ue).port() as modem:
                evidence = {}
                WATCH.restore_cell_lock("owned-at-port", {}, CONNECT.ROLES[ue], evidence)
                role = CONNECT.ROLES[ue]
                self.assertEqual(evidence["verified_lock"], [str(ue), str(role["ssb"]), "30", "78"])
                self.assertEqual(modem.commands[:2], ["AT+CGSN", "AT+CIMI"])
                self.assertEqual(evidence["writes"], ['AT+QNWPREFCFG="mode_pref",NR5G',
                    'AT+QNWPREFCFG="nr5g_disable_mode",2', 'AT+QNWPREFCFG="nr5g_band",78',
                    f'AT+QNWLOCK="common/5g",{ue},{role["ssb"]},30,78'])
                self.assertEqual(modem.commands[-2:], ['AT+QENG="servingcell"', "AT+C5GREG?"])

    def test_matching_saved_preferences_and_lock_are_reused_without_writes(self):
        with FakeAT(correct_settings=True).port():
            evidence = {}
            WATCH.restore_cell_lock("owned-at-port", {}, CONNECT.ROLES[2], evidence)
        self.assertFalse(evidence.get("writes"))
        self.assertEqual(evidence["lock_action"], "reused")

    def test_saved_matching_lock_avoids_a_rejected_duplicate_write(self):
        command = 'AT+QNWLOCK="common/5g",2,639648,30,78'
        with FakeAT(correct_settings=True, reject=command).port() as modem:
            evidence = {}
            WATCH.restore_cell_lock("owned-at-port", {}, CONNECT.ROLES[2], evidence)
        self.assertNotIn(command, modem.commands)
        self.assertEqual(evidence["verified_lock"], ["2", "639648", "30", "78"])

    def test_902_without_matching_readback_stops_before_registration(self):
        self.wrong_cell()
        watcher = self.auto()
        with FakeAT(reject='AT+QNWLOCK="common/5g",2,639648,30,78').port():
            watcher.attempt()
        evidence = json.loads((watcher.directory / "attempts.jsonl").read_text())["radio_recovery"]
        self.assertEqual(evidence["status"], "failed")
        self.assertEqual(evidence["previous_lock"], ["0"])
        self.assertEqual(evidence["lock_after_error"], ["0"])
        self.assertEqual(evidence["lock_write_error"]["cme_code"], 902)
        self.assertNotIn("verified_lock", evidence)
        self.assertFalse(self.network.changes)

    def test_902_can_only_continue_after_independent_exact_target_readback(self):
        with FakeAT().port() as modem:
            original = modem.reply
            def reply(command):
                response = original(command)
                if command == 'AT+QNWLOCK="common/5g",2,639648,30,78':
                    return "\r\n+CME ERROR: 902\r\n"
                return response
            evidence = {}
            with patch.object(modem, "reply", reply):
                WATCH.restore_cell_lock("owned-at-port", {}, CONNECT.ROLES[2], evidence)
        self.assertEqual(evidence["lock_action"], "verified_after_902")
        self.assertEqual(evidence["verified_lock"], ["2", "639648", "30", "78"])
        self.assertEqual(evidence["lock_write_error"]["cme_code"], 902)

    def lost_connected_ue(self):
        self.connect(1)
        self.connect(2)
        self.network.settings[2].update(registration="searching", packet="detached", plmn="--", technology="--")
        self.network.changes.clear()
        self.network.pings.clear()
        watcher = self.auto()
        watcher.args.registration_timeout = 0
        return watcher, list(self.network.modems)[1]

    def test_reported_connected_searching_detached_releases_pdu_before_lock_and_recovers_new_ip(self):
        watcher, path = self.lost_connected_ue()
        peer = list(self.network.modems)[0]
        peer_before = (self.network.modems[peer], dict(self.network.bearers[peer]))
        with FakeAT().port() as modem:
            original = modem.reply
            def reply(command):
                if command.startswith('AT+QNWLOCK="common/5g",'):
                    # This assertion models the required sequence; it does not
                    # assign a vendor meaning to CME 902 on physical hardware.
                    self.assertNotIn("yes", self.network.bearers[path].values())
                return original(command)
            with patch.object(modem, "reply", reply):
                watcher.attempt()
        record = json.loads((watcher.directory / "attempts.jsonl").read_text())
        self.assertEqual(record["radio_recovery"]["status"], "applied")
        self.assertEqual(record["radio_recovery"]["previous_lock"], ["0"])
        self.assertTrue(record["radio_recovery"]["pdu_disconnected"])
        self.assertTrue(record["radio_recovery"]["registration_requested"])
        self.assertEqual(self.disconnects(), [("mmcli", "-m", path, "--simple-disconnect")])
        with self.assertRaises(CONNECT.subprocess.CalledProcessError):
            self.network.lookup(("ip", "-N", "-j", "-4", "route", "get", "10.46.0.1"))
        self.assertEqual((self.network.modems[peer], self.network.bearers[peer]), peer_before)
        self.network.settings[2].update(cell=fixture.cell_text(2), source="10.46.0.99")
        watcher.attempt()
        self.assertTrue(watcher.healthy)
        result = json.loads((watcher.directory / "attempts.jsonl").read_text().splitlines()[-1])
        self.assertEqual(result["source"], "10.46.0.99")
        self.assertTrue(any("10.46.0.99" in cmd for cmd in self.network.pings))
        self.assertEqual((self.network.modems[peer], self.network.bearers[peer]), peer_before)

    def test_stale_connected_pdu_wrong_serial_identity_does_not_disconnect(self):
        watcher, path = self.lost_connected_ue()
        with FakeAT(wrong_identity="AT+CIMI").port():
            watcher.attempt()
        self.assertFalse(self.disconnects())
        self.assertFalse(self.network.changes)
        self.assertIn("yes", self.network.bearers[path].values())

    def test_stale_pdu_failed_disconnect_does_not_clear_host_or_write_lock(self):
        watcher, path = self.lost_connected_ue()
        self.network.fail = ("mmcli", "-m", path, "--simple-disconnect")
        with FakeAT().port() as modem:
            watcher.attempt()
        self.assertFalse(any(cmd.startswith('AT+QNWLOCK="common/5g",') for cmd in modem.commands))
        self.assertFalse(any(cmd[0] == "ip" for cmd in self.network.changes))
        self.assertIn("yes", self.network.bearers[path].values())

    def test_radio_recovery_timeout_does_not_ping_the_old_ip_after_registration_returns(self):
        watcher, path = self.lost_connected_ue()
        peer = self.network.survivor(2)
        original = self.network.change
        def change(*command):
            if command[-1] == "--simple-disconnect":
                self.network.changes.append(command)
                self.network.modems[path] = (*self.network.modems[path][:2], "disconnecting")
                raise subprocess.CalledProcessError(1, command, stderr="Timeout was reached")
            return original(*command)
        with FakeAT().port(), patch.object(CONNECT, "change", change):
            watcher.attempt()
        self.assertTrue(watcher.pending_disconnect)
        self.network.modems[path] = (*self.network.modems[path][:2], "registered")
        self.network.settings[2].update(registration="home", packet="attached", plmn="00101", technology="5gnr")
        with patch.object(WATCH, "restore_cell_lock") as lock:
            watcher.attempt()
        lock.assert_not_called()
        self.assertFalse(watcher.healthy)
        self.assertFalse(self.network.pings)
        self.assertEqual(len(self.disconnects()), 1)
        self.network.bearers[path] = {bearer: "no" for bearer in self.network.bearers[path]}
        self.network.settings[2]["source"] = "10.46.0.90"
        watcher.attempt()
        self.assertTrue(watcher.healthy)
        self.assertFalse(watcher.pending_disconnect)
        self.assertEqual(len(self.disconnects()), 1)
        self.assertTrue(any("10.46.0.90" in command for command in self.network.pings))
        self.assertEqual(self.network.survivor(2), peer)

    def test_stale_pdu_radio_calls_and_registration_are_outside_shared_lock(self):
        watcher, _ = self.lost_connected_ue()
        original_read, original_change, original_at = self.network.read, self.network.change, CONNECT.at_reply
        def assert_unlocked():
            with open(WATCH.SHARED_LOCK, "a") as lock:
                CONNECT.fcntl.flock(lock, CONNECT.fcntl.LOCK_EX | CONNECT.fcntl.LOCK_NB)
        def read(*command):
            if command[0] == "mmcli":
                assert_unlocked()
            return original_read(*command)
        def change(*command):
            if command[0] == "mmcli":
                assert_unlocked()
            return original_change(*command)
        def query(fd, command):
            assert_unlocked()
            return original_at(fd, command)
        with FakeAT().port(), patch.object(CONNECT, "read", read), \
                patch.object(CONNECT, "change", change), patch.object(CONNECT, "at_reply", query):
            watcher.attempt()
        record = json.loads((watcher.directory / "attempts.jsonl").read_text())
        self.assertEqual(record["radio_recovery"]["status"], "applied")

    def test_stale_pdu_bearer_change_before_disconnect_is_rejected(self):
        watcher, _ = self.lost_connected_ue()
        session = watcher.session(recovery=True)
        session.discover()
        original_active = session.active
        calls = [0]
        def active():
            info, bearers = original_active()
            calls[0] += 1
            if calls[0] == 2:
                self.network.settings[2]["source"] = "10.46.0.98"
                info, bearers = original_active()
            return info, bearers
        with FakeAT().port(), patch.object(session, "active", active):
            with self.assertRaisesRegex(ValueError, "Bearer changed"):
                session.release_radio_pdu({})
        self.assertFalse(self.network.changes)

    def test_live_at_radio_loss_preserves_pdu_when_saved_settings_match(self):
        self.connect(2)
        self.wrong_cell()
        watcher = self.auto()
        self.network.changes.clear()
        with FakeAT(correct_settings=True).port():
            watcher.attempt()
        self.assertFalse(self.network.changes)
        record = json.loads((watcher.directory / "attempts.jsonl").read_text())
        self.assertFalse(record["radio_recovery"]["registration_requested"])
        self.assertTrue(record["radio_recovery"]["pdu_preserved"])
        self.assertEqual(record["radio_recovery"]["status"], "waiting_radio")
        self.assertTrue(record["radio_recovery"]["serial_registration"]["radio_lost"])

    def test_radio_loss_with_correct_lock_recovers_each_role_without_disconnect(self):
        for ue in (1, 2):
            for changed_ip in (False, True):
                with self.subTest(ue=ue, changed_ip=changed_ip):
                    self.network.__dict__.update(fixture.Network().__dict__)
                    self.connect(1)
                    self.connect(2)
                    peer = self.network.survivor(ue)
                    path = list(self.network.modems)[ue - 1]
                    self.network.settings[ue].update(registration="searching", packet="detached",
                                                     plmn="--", technology="--")
                    self.network.changes.clear()
                    self.network.pings.clear()
                    watcher = self.auto(ue=ue)
                    records = watcher.directory / "attempts.jsonl"
                    records.unlink(missing_ok=True)
                    with FakeAT(ue, correct_settings=True).port() as modem:
                        watcher.attempt()
                    record = json.loads(records.read_text())
                    self.assertEqual(record["radio_recovery"]["status"], "waiting_radio")
                    self.assertFalse(self.network.changes)
                    self.assertFalse(self.network.pings)
                    self.assertFalse(watcher.pending_disconnect)
                    self.assertFalse(any(command.startswith('AT+QNWLOCK="common/5g",')
                                         for command in modem.commands))
                    self.network.settings[ue].update(registration="home", packet="attached",
                                                     plmn="00101", technology="5gnr")
                    if changed_ip:
                        self.network.settings[ue]["source"] = f"10.{44 + ue}.0.91"
                    current_ip = self.network.settings[ue]["source"]
                    watcher.attempt()
                    self.assertTrue(watcher.healthy)
                    self.assertFalse(self.disconnects())
                    self.assertFalse(any("--3gpp-register" in argument or "--simple-connect=" in argument
                                         for command in self.network.changes for argument in command))
                    bound = [command for command in self.network.pings if "-I" in command]
                    self.assertEqual(len(bound), 1)
                    self.assertEqual(bound[0][bound[0].index("-I") + 1], current_ip)
                    self.assertEqual(self.network.survivor(ue), peer)

    def test_read_only_radio_inspection_never_writes_mismatched_settings(self):
        for only_lock_missing in (False, True):
            with self.subTest(only_lock_missing=only_lock_missing), FakeAT(correct_settings=only_lock_missing).port() as modem:
                modem.lock = "0"
                evidence = {}
                with self.assertRaises(WATCH.RadioSettingsMismatch):
                    WATCH.restore_cell_lock("owned-at-port", {}, CONNECT.ROLES[2], evidence, read_only=True)
                self.assertEqual(evidence["previous_lock"], ["0"])
                self.assertEqual(evidence["lock_action"], "write_required")
                self.assertIn("required_write", evidence)
                self.assertIn("qeng", evidence)
                self.assertFalse(evidence.get("writes"))
                self.assertFalse(any(command.startswith('AT+QNWPREFCFG="mode_pref",')
                                     or command.startswith('AT+QNWLOCK="common/5g",')
                                     for command in modem.commands))

    def test_disconnecting_state_reports_pending_release_without_radio_work(self):
        self.connect(2)
        path = list(self.network.modems)[1]
        self.network.modems[path] = (*self.network.modems[path][:2], "disconnecting")
        self.network.settings[2].update(registration="idle", packet="detached", plmn="--", technology="--")
        self.network.changes.clear()
        watcher = self.auto(level=2)
        watcher.last_redial = WATCH.time.monotonic() - 3
        with patch.object(WATCH, "restore_cell_lock") as radio:
            watcher.attempt()
        radio.assert_not_called()
        self.assertFalse(self.network.changes)
        record = json.loads((watcher.directory / "attempts.jsonl").read_text())
        self.assertEqual(record["radio_recovery"]["status"], "waiting_pdu_release")
        self.assertGreaterEqual(record["radio_recovery"]["elapsed_seconds"], 3)
        self.assertIn("PDU release to finish", self.console.getvalue())
        self.assertIn("no duplicate request", self.console.getvalue())

    def test_live_registered_expected_cell_preserves_working_pdu(self):
        self.connect(2)
        self.wrong_cell()
        watcher = self.auto()
        self.network.changes.clear()
        with FakeAT(correct_settings=True).port() as modem:
            original = modem.reply
            def reply(command):
                if command == 'AT+QENG="servingcell"':
                    return '\r\n+QENG: "servingcell","NOCONN","NR5G-SA","TDD",001,01,00066C001,2,7,639648,78,1,-93,-11,19,1,37\r\nOK\r\n'
                if command == "AT+C5GREG?":
                    return "\r\n+C5GREG: 0,1\r\nOK\r\n"
                return original(command)
            with patch.object(modem, "reply", reply):
                watcher.attempt()
        self.assertFalse(self.network.changes)
        record = json.loads((watcher.directory / "attempts.jsonl").read_text())
        self.assertFalse(record["radio_recovery"]["registration_requested"])
        self.assertFalse(watcher.healthy)  # MM cell evidence must still pass on a later attempt.

    def test_wrong_serial_identity_stops_before_all_configuration(self):
        for wrong in ("AT+CGSN", "AT+CIMI"):
            with self.subTest(wrong=wrong), FakeAT(wrong_identity=wrong).port() as modem:
                evidence = {}
                with self.assertRaisesRegex(CONNECT.CellError, "identity mismatch"):
                    WATCH.restore_cell_lock("owned-at-port", {}, CONNECT.ROLES[2], evidence)
                self.assertFalse(evidence.get("writes"))
                self.assertEqual(modem.commands, ["AT+CGSN"] if wrong == "AT+CGSN" else ["AT+CGSN", "AT+CIMI"])

    def test_rejected_write_and_wrong_lock_readback_do_not_proceed(self):
        for options, message in ((dict(reject='AT+QNWPREFCFG="mode_pref",NR5G'), "902"),
                                 (dict(wrong_lock=True), "readback mismatch")):
            with self.subTest(options=options), FakeAT(**options).port() as modem:
                with self.assertRaisesRegex(CONNECT.CellError, message):
                    WATCH.restore_cell_lock("owned-at-port", {}, CONNECT.ROLES[2], {})
                self.assertNotIn("AT+C5GREG?", modem.commands)

    def test_settings_readback_must_match_before_lock_write(self):
        with FakeAT().port() as modem:
            original_reply = modem.reply
            def ignore_setting(command):
                reply = original_reply(command)
                if command == 'AT+QNWPREFCFG="mode_pref",NR5G':
                    modem.settings["mode_pref"] = "LTE"
                return reply
            with patch.object(modem, "reply", ignore_setting), self.assertRaisesRegex(CONNECT.CellError, "Setting readback"):
                WATCH.restore_cell_lock("owned-at-port", {}, CONNECT.ROLES[2], {})
            self.assertFalse(any(cmd.startswith('AT+QNWLOCK="common/5g",') for cmd in modem.commands))

    def test_radio_recovery_then_next_attempt_verifies_everything(self):
        self.wrong_cell()
        watcher = self.auto()
        with FakeAT().port():
            watcher.attempt()
        self.assertFalse(watcher.healthy)
        first = json.loads((watcher.directory / "attempts.jsonl").read_text())
        self.assertEqual(first["radio_recovery"]["status"], "applied")
        self.assertEqual(first["status"], "radio_retry_pending")
        self.assertFalse(self.network.pings)
        self.assertFalse(self.disconnects())
        self.network.settings[2]["cell"] = fixture.cell_text(2)
        with patch.object(WATCH, "restore_cell_lock") as radio:
            watcher.attempt()
        radio.assert_not_called()
        self.assertTrue(watcher.healthy)
        self.assertEqual(self.network.modems[next(iter(self.network.modems))][2], "registered")
        self.assertTrue(all(cmd[-1] == "10.46.0.1" for cmd in self.network.pings))
        self.assertEqual(self.console.getvalue(), "UE2 / FR3 attempt 1 ... FAIL\nUE2 / FR3 attempt 2 ... SUCCESS\n")

    def test_registration_failure_restores_lock_then_requests_lab_plmn(self):
        modem_path = list(self.network.modems)[1]
        imei, interface, _ = self.network.modems[modem_path]
        self.network.modems[modem_path] = (imei, interface, "enabled")
        watcher = self.auto()
        watcher.args.registration_timeout = 0  # No simulated-clock sleep needed.
        original_change = self.network.change
        def change(*command):
            if "--3gpp-register-in-operator=00101" in command:
                with open(WATCH.SHARED_LOCK, "a") as lock:
                    CONNECT.fcntl.flock(lock, CONNECT.fcntl.LOCK_EX | CONNECT.fcntl.LOCK_NB)
                self.network.changes.append(command)
                self.network.modems[modem_path] = (imei, interface, "registered")
            else:
                original_change(*command)
        with FakeAT().port(), patch.object(CONNECT, "change", change):
            watcher.attempt()
        self.assertIn(("mmcli", "-m", modem_path, "--3gpp-register-in-operator=00101", "--timeout=5"), self.network.changes)
        self.assertFalse(watcher.healthy)
        watcher.attempt()
        self.assertTrue(watcher.healthy)

    def test_rejected_registration_is_recorded_and_does_not_start_pdu(self):
        modem_path = list(self.network.modems)[1]
        imei, interface, _ = self.network.modems[modem_path]
        self.network.modems[modem_path] = (imei, interface, "enabled")
        watcher = self.auto()
        watcher.args.registration_timeout = 0
        def change(*command):
            raise CONNECT.subprocess.CalledProcessError(1, command, stderr="NoNetworkFound")
        with FakeAT().port(), patch.object(CONNECT, "change", change):
            watcher.attempt()
        result = json.loads((watcher.directory / "attempts.jsonl").read_text())
        self.assertEqual(result["radio_recovery"]["status"], "failed")
        self.assertEqual(result["radio_recovery"]["verified_lock"], ["2", "639648", "30", "78"])
        self.assertTrue(result["radio_recovery"]["registration_requested"])
        self.assertFalse(watcher.healthy)
        self.assertFalse(self.network.changes)
        self.assertFalse(self.network.pings)

    def test_wrong_lock_readback_does_not_request_registration(self):
        self.wrong_cell()
        watcher = self.auto()
        with FakeAT(wrong_lock=True).port():
            watcher.attempt()
        result = json.loads((watcher.directory / "attempts.jsonl").read_text())
        self.assertEqual(result["radio_recovery"]["status"], "failed")
        self.assertIn("readback mismatch", result["radio_recovery"]["error"])
        self.assertFalse(self.network.changes)

    def test_cooldown_applies_to_failed_radio_commands_but_checks_keep_running(self):
        self.wrong_cell()
        watcher = self.auto()
        with patch.object(WATCH, "restore_cell_lock", side_effect=CONNECT.CellError("No signal / rejected")) as radio:
            watcher.attempt()
            watcher.attempt()
            self.assertEqual(radio.call_count, 1)
            watcher.last_cell_lock -= watcher.args.cell_lock_cooldown + 1
            watcher.attempt()
            self.assertEqual(radio.call_count, 2)
        records = [json.loads(line) for line in (watcher.directory / "attempts.jsonl").read_text().splitlines()]
        self.assertEqual([r["radio_recovery"]["status"] for r in records], ["failed", "cooldown", "failed"])

    def test_port_busy_or_wrong_usb_never_writes_or_requests_registration(self):
        self.wrong_cell()
        for message in ("AT port busy; close minicom", "AT port does not belong to selected modem"):
            with self.subTest(message=message), patch.object(CONNECT, "verify_at_port", side_effect=CONNECT.CellError(message)), \
                    patch.object(CONNECT, "at_reply") as query:
                watcher = self.auto()
                watcher.attempt()
                query.assert_not_called()
                self.assertFalse(watcher.healthy)
                self.assertIn(message, self.log.getvalue())
        self.assertFalse(any("--3gpp-register" in cmd[-1] for cmd in self.network.changes))

    def test_foreign_sim_or_apn_or_host_resource_prevents_radio_repair(self):
        for foreign in ("SIM", "APN", "host"):
            with self.subTest(foreign=foreign):
                self.network.settings[2].update(imsi=CONNECT.ROLES[2]["imsi"], apn="internet2")
                self.wrong_cell()
                modem_path = list(self.network.modems)[1]
                self.network.bearers[modem_path] = {key: "no" for key in self.network.bearers[modem_path]}
                if foreign == "SIM":
                    self.network.settings[2]["imsi"] = "foreign"
                elif foreign == "APN":
                    self.network.settings[2]["apn"] = "foreign"
                    self.network.bearers[modem_path] = {key: "yes" for key in self.network.bearers[modem_path]}
                else:
                    self.network.rules.append(dict(priority=10161, src="all", dst="8.8.8.8", table=152))
                with patch.object(WATCH, "restore_cell_lock") as radio:
                    self.auto().attempt()
                    radio.assert_not_called()

    def test_ping_failure_and_healthy_monitoring_do_not_write_radio(self):
        watcher = self.auto()
        with patch.object(WATCH, "restore_cell_lock") as radio:
            watcher.attempt()
            WATCH.probe(watcher.session())
            self.network.ping_failure = True
            watcher.attempt()
        radio.assert_not_called()

    def test_at_port_without_opt_in_remains_read_only(self):
        self.wrong_cell()
        with patch.object(WATCH, "restore_cell_lock") as radio:
            self.watcher(ue=2, extra=("--at-port", "owned-at-port")).attempt()
        radio.assert_not_called()

    def test_radio_io_and_registration_do_not_hold_shared_network_lock(self):
        self.wrong_cell()
        watcher = self.auto()
        def radio(*args):
            with open(WATCH.SHARED_LOCK, "a") as lock:
                CONNECT.fcntl.flock(lock, CONNECT.fcntl.LOCK_EX | CONNECT.fcntl.LOCK_NB)
            # The independent peer can complete its startup while FR3 repairs.
            self.connect(1)
        with patch.object(WATCH, "restore_cell_lock", side_effect=radio):
            watcher.attempt()
        self.assertFalse(watcher.healthy)
        self.assertEqual(self.network.modems[next(iter(self.network.modems))][2], "connected")

    def test_ctrl_c_during_at_write_restores_terminal_and_runs_ue_shutdown(self):
        self.wrong_cell()
        watcher = self.auto(level=1)
        original_query = CONNECT.at_reply
        def query(fd, command):
            if command.startswith('AT+QNWLOCK="common/5g",'):
                raise CONNECT.StopRequested(signal.SIGINT)
            return original_query(fd, command)
        with FakeAT().port(), patch.object(CONNECT, "at_reply", query):
            self.assertEqual(watcher.run(), 130)
        summary = json.loads((watcher.directory / "summary.json").read_text())
        self.assertEqual(summary["shutdown"]["status"], "completed")
        self.assertEqual(self.network.modems[list(self.network.modems)[1]][2], "disabled")
        self.assertEqual(self.network.modems[next(iter(self.network.modems))][2], "registered")
        self.assertIn("CANCELLED", self.console.getvalue())


if __name__ == "__main__":
    unittest.main()
