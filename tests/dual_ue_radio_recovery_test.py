#!/usr/bin/env python3
"""Guarded radio recovery against simulated modems and a real pseudo-terminal."""

import contextlib
import json
import os
from pathlib import Path
import select
import signal
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
    def __init__(self, ue=2, wrong_identity=None, reject=None, wrong_lock=False, correct_settings=False):
        self.role = CONNECT.ROLES[ue]
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
            response = '+QENG: "servingcell","SEARCH"'
        elif command == "AT+C5GREG?":
            response = "+C5GREG: 0,2"
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


class RadioRecoveryTest(unittest.TestCase):
    setUp = fixture.ReconnectTest.setUp
    watcher = fixture.ReconnectTest.watcher
    connect = fixture.ReconnectTest.connect
    disconnects = fixture.ReconnectTest.disconnects

    def auto(self, ue=2, **kwargs):
        return self.watcher(ue=ue, extra=("--auto-cell-lock", "--at-port", "owned-at-port"), **kwargs)

    def wrong_cell(self, ue=2):
        self.network.settings[ue]["cell"] = fixture.cell_text(3 - ue)

    def test_cli_requires_owned_port_and_valid_cooldown(self):
        for options in (("--auto-cell-lock",), ("--cell-lock-cooldown", "0"),
                        ("--cell-lock-cooldown", "nan")):
            with self.subTest(options=options), self.assertRaises(SystemExit):
                WATCH.arguments(["--ue", "2", *options])
        self.assertFalse(WATCH.arguments(["--ue", "2"]).auto_cell_lock)

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

    def test_saved_preferences_are_not_rewritten_but_failed_radio_gets_fresh_lock(self):
        with FakeAT(correct_settings=True).port():
            evidence = {}
            WATCH.restore_cell_lock("owned-at-port", {}, CONNECT.ROLES[2], evidence)
        self.assertEqual(evidence["writes"], ['AT+QNWLOCK="common/5g",2,639648,30,78'])

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
            self.assertFalse(any(cmd.startswith("AT+QNWLOCK=") for cmd in modem.commands))

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
            if command[-1] == "--3gpp-register-in-operator=00101":
                with open(WATCH.SHARED_LOCK, "a") as lock:
                    CONNECT.fcntl.flock(lock, CONNECT.fcntl.LOCK_EX | CONNECT.fcntl.LOCK_NB)
                self.network.changes.append(command)
                self.network.modems[modem_path] = (imei, interface, "registered")
            else:
                original_change(*command)
        with FakeAT().port(), patch.object(CONNECT, "change", change):
            watcher.attempt()
        self.assertIn(("mmcli", "-m", modem_path, "--3gpp-register-in-operator=00101"), self.network.changes)
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
