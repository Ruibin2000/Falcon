#!/usr/bin/env python3
"""Deferred registration, live connection checks and isolated child cleanup."""

import contextlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/dual_fr1"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dual_ue_reconnect_test as fixture
import dual_ue_radio_recovery_test as radio
import connect_ue as CONNECT
import reconnect_ue as WATCH


class PendingRequest(WATCH.RegistrationRequest):
    def start(self):
        self.data["status"] = "waiting"

    def poll(self):
        return self.data["status"] != "waiting"

    def cancel(self, reason):
        self.data["cancel_reason"] = reason
        self.finish("cancelled", -signal.SIGTERM)


class BackgroundRegistrationTest(unittest.TestCase):
    watcher = fixture.ReconnectTest.watcher
    connect = fixture.ReconnectTest.connect
    disconnects = fixture.ReconnectTest.disconnects

    def setUp(self):
        fixture.ReconnectTest.setUp(self)
        self.clock = [0.0]
        mock = patch.object(WATCH.time, "monotonic", side_effect=lambda: self.clock[0])
        mock.start()
        self.addCleanup(mock.stop)
        self.jobs = []

    def auto(self, grace=10, stop=None, extra=(), level=1, startup=False, ue=2):
        watcher = self.watcher(ue=ue, level=level, stop=stop,
                               extra=("--auto-cell-lock", "--at-port", "owned-at-port",
                                      "--registration-grace", str(grace), *extra))
        def factory(*args):
            job = PendingRequest(*args)
            self.jobs.append(job)
            return job
        watcher.registration_factory = factory
        if not startup:
            watcher.startup_radio = dict(status="completed")  # Model an already-initialized watcher.
        return watcher

    def lose_registration(self):
        path = list(self.network.modems)[1]
        self.network.modems[path] = (*self.network.modems[path][:2], "enabled")
        self.network.settings[2].update(registration="idle", packet="detached", plmn="--", technology="--")
        return path

    def restore_registration(self):
        path = list(self.network.modems)[1]
        self.network.modems[path] = (*self.network.modems[path][:2], "registered")
        self.network.settings[2].update(registration="home", packet="attached", plmn="00101", technology="5gnr")

    def test_defaults_and_grace_validation(self):
        args = WATCH.arguments(["--ue", "2"])
        self.assertEqual((args.registration_grace, args.registration_timeout, args.registration_request_timeout), (10, 0, 5))
        self.assertEqual(WATCH.arguments(["--ue", "2", "--registration-grace", "0"]).registration_grace, 0)
        for option in ("--registration-grace", "--registration-timeout"):
            with self.subTest(option=option), self.assertRaises(SystemExit):
                WATCH.arguments(["--ue", "2", option, "-1"])

    def test_later_radio_failure_observes_ten_seconds_without_forced_changes(self):
        self.lose_registration()
        watcher = self.auto()
        with patch.object(WATCH, "restore_cell_lock") as lock:
            for elapsed in (0, 1, 9):
                self.clock[0] = elapsed
                watcher.attempt()
        lock.assert_not_called()
        self.assertFalse(self.jobs)
        self.assertFalse(self.network.changes)
        records = [json.loads(line) for line in (watcher.directory / "attempts.jsonl").read_text().splitlines()]
        self.assertEqual([r["radio_recovery"]["remaining_seconds"] for r in records], [10, 9, 1])
        self.assertEqual(self.console.getvalue().count("FAIL"), 3)

    def test_startup_restores_lock_and_dispatches_registration_without_grace(self):
        self.connect(1)
        peer = self.network.survivor(2)
        self.network.changes.clear()
        self.lose_registration()
        watcher = self.auto(startup=True)
        with radio.FakeAT().port() as modem:
            watcher.attempt()
        record = json.loads((watcher.directory / "attempts.jsonl").read_text())
        evidence = record["radio_recovery"]
        self.assertEqual(evidence["trigger"], "startup")
        self.assertEqual(evidence["verified_lock"], ["2", "639648", "30", "78"])
        self.assertIn('AT+QNWLOCK="common/5g",2,639648,30,78', modem.commands)
        self.assertEqual(len(self.jobs), 1)
        self.assertIn("--timeout=5", self.jobs[0].command)
        self.assertEqual(watcher.startup_radio["status"], "completed")
        self.assertFalse(watcher.healthy)  # Lock/request completion does not prove registration or ping.
        self.assertEqual(self.network.survivor(2), peer)
        self.assertFalse(any("--simple-connect=" in argument for cmd in self.network.changes for argument in cmd))
        self.restore_registration()
        self.clock[0] = 1
        with patch.object(WATCH, "restore_cell_lock") as lock:
            watcher.attempt()
        lock.assert_not_called()
        self.assertTrue(watcher.healthy)
        self.assertEqual(len(self.jobs), 1)
        self.assertEqual(self.jobs[0].data["status"], "waiting")

    def test_healthy_startup_checks_serial_once_and_preserves_each_roles_pdu(self):
        for ue in (1, 2):
            with self.subTest(ue=ue):
                self.connect(ue)
                peer = self.network.survivor(ue)
                self.network.changes.clear()
                watcher = self.auto(startup=True, ue=ue)
                with radio.FakeAT(ue, correct_settings=True, registered=True).port() as modem:
                    watcher.attempt()
                    self.assertTrue(watcher.healthy)
                    self.assertIn('AT+QNWLOCK="common/5g"', modem.commands)
                    self.assertFalse(any(command.startswith('AT+QNWLOCK="common/5g",') for command in modem.commands))
                    commands = list(modem.commands)
                    watcher.attempt()
                    WATCH.probe(watcher.session())
                    self.assertEqual(modem.commands, commands)
                self.assertFalse(self.jobs)
                self.assertFalse(self.network.changes)
                self.assertEqual(self.network.survivor(ue), peer)

    def test_startup_repairs_missing_lock_even_when_modem_is_already_registered(self):
        self.connect(2)
        self.network.changes.clear()
        watcher = self.auto(startup=True)
        with radio.FakeAT(registered=True).port() as modem:
            watcher.attempt()
        self.assertTrue(watcher.healthy)
        self.assertIn('AT+QNWLOCK="common/5g",2,639648,30,78', modem.commands)
        self.assertFalse(self.jobs)
        self.assertFalse(self.network.changes)  # Serial repair alone needs no PDU or host reset.

    def test_failed_startup_cannot_skip_serial_check_and_retries_after_cooldown(self):
        self.connect(2)
        self.network.changes.clear()
        watcher = self.auto(startup=True)
        with patch.object(WATCH, "restore_cell_lock", side_effect=OSError("AT port busy")) as lock:
            watcher.attempt()
            self.assertFalse(watcher.healthy)
            self.clock[0] = 1
            watcher.attempt()
            self.assertFalse(watcher.healthy)
        lock.assert_called_once()
        self.assertFalse(self.jobs)
        self.assertFalse(self.network.changes)
        self.clock[0] = 30
        with radio.FakeAT(correct_settings=True, registered=True).port():
            watcher.attempt()
        self.assertTrue(watcher.healthy)

    def test_wrong_startup_serial_identity_prevents_radio_writes_and_registration(self):
        self.connect(2)
        self.network.changes.clear()
        watcher = self.auto(startup=True)
        with radio.FakeAT(wrong_identity="AT+CGSN").port() as modem:
            watcher.attempt()
        self.assertEqual(modem.commands, ["AT+CGSN"])
        self.assertFalse(watcher.healthy)
        self.assertFalse(self.jobs)
        self.assertFalse(self.network.changes)

    def test_later_radio_loss_still_gets_grace_after_successful_startup(self):
        watcher = self.auto(startup=True)
        with radio.FakeAT(correct_settings=True, registered=True).port():
            watcher.attempt()
        self.assertTrue(watcher.healthy)
        self.clock[0] = 100
        self.lose_registration()
        with patch.object(WATCH, "restore_cell_lock") as lock:
            watcher.attempt()
        lock.assert_not_called()
        self.assertFalse(self.jobs)
        record = json.loads((watcher.directory / "attempts.jsonl").read_text().splitlines()[-1])
        self.assertEqual(record["radio_recovery"]["trigger"], "radio_failure")
        self.assertEqual(record["radio_recovery"]["remaining_seconds"], 10)

    def test_ctrl_c_during_startup_serial_work_still_shuts_down_selected_ue(self):
        self.connect(1)
        peer = self.network.survivor(2)
        watcher = self.auto(startup=True)
        with patch.object(WATCH, "restore_cell_lock", side_effect=CONNECT.StopRequested(signal.SIGINT)):
            self.assertEqual(watcher.run(), 130)
        summary = json.loads((watcher.directory / "summary.json").read_text())
        self.assertEqual(summary["shutdown"]["status"], "completed")
        self.assertEqual(summary["startup_radio"]["status"], "interrupted")
        self.assertEqual(self.network.modems[list(self.network.modems)[1]][2], "disabled")
        self.assertFalse(self.jobs)
        self.assertEqual(self.network.survivor(2), peer)

    def test_automatic_recovery_during_grace_reuses_pdu_without_registration(self):
        self.connect(2)
        self.network.settings[2].update(registration="searching", packet="detached")
        self.network.changes.clear()
        watcher = self.auto()
        watcher.attempt()
        self.assertFalse(self.network.changes)
        self.clock[0] = 3
        self.network.settings[2].update(registration="home", packet="attached")
        watcher.attempt()
        self.assertTrue(watcher.healthy)
        self.assertFalse(self.jobs)
        self.assertFalse(self.network.changes)
        self.assertIsNone(watcher.radio_failure_since)

    def test_grace_expiry_starts_one_child_and_attempts_continue_without_rewrites(self):
        self.lose_registration()
        watcher = self.auto()
        watcher.attempt()
        self.clock[0] = 10
        with radio.FakeAT(correct_settings=True).port():
            watcher.attempt()
        self.assertEqual(len(self.jobs), 1)
        self.assertIn("--timeout=5", self.jobs[0].command)
        with patch.object(WATCH, "restore_cell_lock") as lock:
            for elapsed in (11, 12, 13):
                self.clock[0] = elapsed
                watcher.attempt()
        lock.assert_not_called()
        self.assertEqual(len(self.jobs), 1)
        self.assertEqual(watcher.attempts, 5)
        self.assertEqual(self.console.getvalue().splitlines()[-1], "UE2 / FR3 attempt 5 ... FAIL")
        result = json.loads((watcher.directory / "attempts.jsonl").read_text().splitlines()[-1])
        self.assertEqual(result["radio_recovery"]["status"], "registration_pending")

    def test_registration_ready_proceeds_to_pdu_and_ping_while_child_still_waits(self):
        self.connect(1)
        peer_before = self.network.survivor(2)
        self.lose_registration()
        watcher = self.auto(grace=0)
        with radio.FakeAT(correct_settings=True).port():
            watcher.attempt()
        self.restore_registration()
        self.clock[0] = 1
        watcher.attempt()
        self.assertTrue(watcher.healthy)
        self.assertEqual(self.jobs[0].data["status"], "waiting")
        self.assertEqual(len(self.jobs), 1)
        self.assertTrue(any(cmd[-1] == "10.46.0.1" for cmd in self.network.pings))
        self.assertEqual(self.network.survivor(2), peer_before)
        self.jobs[0].finish("returned", 0)
        watcher.poll_registration()
        events = [json.loads(line) for line in (watcher.directory / "registration_events.jsonl").read_text().splitlines()]
        self.assertEqual([event["event"] for event in events], ["started", "finished"])

    def test_client_timeout_observes_possible_backend_work_without_duplicate_request(self):
        self.lose_registration()
        watcher = self.auto(grace=0)
        with radio.FakeAT(correct_settings=True).port():
            watcher.attempt()
        self.clock[0] = 5
        self.jobs[0].finish("failed", 1)
        self.jobs[0].data["stderr"] = "Timeout was reached"
        watcher.poll_registration()
        self.clock[0] = 36  # Both 5s client wait and 30s cooldown elapsed.
        watcher.attempt()
        result = json.loads((watcher.directory / "attempts.jsonl").read_text().splitlines()[-1])
        self.assertEqual(result["radio_recovery"]["status"], "backend_observation")
        self.assertEqual(len(self.jobs), 1)
        self.restore_registration()
        watcher.attempt()
        self.assertTrue(watcher.healthy)  # Observation never blocks a verified recovery.
        self.assertEqual(len(self.jobs), 1)

    def test_completed_failed_request_uses_cooldown_then_allows_one_new_child(self):
        self.lose_registration()
        watcher = self.auto(grace=0)
        with radio.FakeAT(correct_settings=True).port():
            watcher.attempt()
        self.clock[0] = 1
        self.jobs[0].finish("failed", 1)
        self.jobs[0].data["stderr"] = "NoNetworkFound"
        watcher.poll_registration()
        self.clock[0] = 30
        watcher.attempt()
        self.assertEqual(len(self.jobs), 1)
        self.clock[0] = 31
        with radio.FakeAT(correct_settings=True).port():
            watcher.attempt()
        self.assertEqual(len(self.jobs), 2)

    def test_ctrl_c_reaps_registration_client_before_modem_shutdown(self):
        self.lose_registration()
        def stop(index):
            raise CONNECT.StopRequested(signal.SIGINT)
        watcher = self.auto(grace=0, stop=fixture.Stop(on_wait=stop))
        original = CONNECT.shutdown_on_interrupt
        def shutdown(*args, **kwargs):
            self.assertEqual(self.jobs[0].data["status"], "cancelled")
            return original(*args, **kwargs)
        with radio.FakeAT(correct_settings=True).port(), patch.object(CONNECT, "shutdown_on_interrupt", shutdown):
            self.assertEqual(watcher.run(), 130)
        self.assertEqual(self.network.modems[list(self.network.modems)[1]][2], "disabled")
        summary = json.loads((watcher.directory / "summary.json").read_text())
        self.assertEqual(summary["last_registration"]["status"], "cancelled")
        self.assertEqual(summary["shutdown"]["status"], "completed")

    def test_bounded_exit_cancels_child_without_disabling_modem(self):
        self.lose_registration()
        watcher = self.auto(grace=0, extra=("--max-attempts", "1"))
        with radio.FakeAT(correct_settings=True).port():
            self.assertEqual(watcher.run(), 1)
        self.assertEqual(self.jobs[0].data["status"], "cancelled")
        self.assertNotEqual(self.network.modems[list(self.network.modems)[1]][2], "disabled")

    def test_bad_sim_cancels_pending_client_and_does_not_mutate_foreign_resources(self):
        self.lose_registration()
        watcher = self.auto(grace=0)
        with radio.FakeAT(correct_settings=True).port():
            watcher.attempt()
        self.network.changes.clear()
        self.network.settings[2]["imsi"] = "foreign"
        watcher.attempt()
        self.assertEqual(self.jobs[0].data["status"], "cancelled")
        self.assertFalse(self.network.changes)

    def test_identity_change_cancels_old_request_and_starts_a_fresh_observation_window(self):
        self.lose_registration()
        watcher = self.auto(grace=10)
        watcher.attempt()
        self.clock[0] = 10
        with radio.FakeAT(correct_settings=True).port():
            watcher.attempt()
        self.clock[0] = 11
        self.network.settings[2]["identity"] = "new-identity-of-selected-UE"
        watcher.attempt()
        self.assertEqual(self.jobs[0].data["status"], "cancelled")
        self.assertEqual(len(self.jobs), 1)
        result = json.loads((watcher.directory / "attempts.jsonl").read_text().splitlines()[-1])
        self.assertEqual(result["radio_recovery"]["status"], "observing")
        self.assertEqual(result["radio_recovery"]["remaining_seconds"], 10)

    def test_registration_cleanup_error_does_not_skip_selected_ue_shutdown(self):
        self.lose_registration()
        def stop(index):
            raise CONNECT.StopRequested(signal.SIGINT)
        watcher = self.auto(grace=0, stop=fixture.Stop(on_wait=stop))
        with radio.FakeAT(correct_settings=True).port(), \
                patch.object(watcher, "cancel_registration", side_effect=OSError("test client cleanup error")):
            self.assertEqual(watcher.run(), 130)
        summary = json.loads((watcher.directory / "summary.json").read_text())
        self.assertEqual(summary["registration_cleanup"]["status"], "failed")
        self.assertEqual(summary["shutdown"]["status"], "completed")
        self.assertIn("Registration client cleanup incomplete", self.console.getvalue())


class RegistrationProcessTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def request(self, code, timeout=20):
        job = WATCH.RegistrationRequest((sys.executable, "-u", "-c", code), timeout, self.root, ("test-owned-modem", "test-device"))
        self.addCleanup(job.cancel, "test cleanup")
        job.start()
        return job

    def wait_file(self, path):
        deadline = time.monotonic() + 3
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(path.exists(), "private test child did not become ready")

    def test_start_and_poll_do_not_wait_for_a_long_registration_reply(self):
        job = self.request("import time; time.sleep(60)")
        self.assertFalse(job.poll())
        peer = self.request("print('other UE request completed')")
        peer.process.wait(timeout=3)
        self.assertTrue(peer.poll())
        self.assertEqual(peer.data["status"], "returned")
        self.assertFalse(job.poll())
        job.cancel("user stop")
        self.assertIsNotNone(job.process.returncode)
        self.assertEqual(job.data["status"], "cancelled")

    def test_large_child_output_does_not_fill_a_pipe_or_block_exit(self):
        job = self.request("print('x' * 200000)")
        job.process.wait(timeout=3)
        self.assertTrue(job.poll())
        self.assertEqual(len(job.data["stdout"]), 65536)
        self.assertGreater(Path(job.data["stdout_file"]).stat().st_size, 200000)

    def test_process_watchdog_kills_and_reaps_without_waiting_in_poll(self):
        job = self.request("import time; time.sleep(60)", timeout=2)
        with patch.object(WATCH.time, "monotonic", return_value=job.started + 8):
            job.poll()
            job.process.wait(timeout=3)
            self.assertTrue(job.poll())
        self.assertEqual(job.data["status"], "process_timeout")
        self.assertEqual(job.data["process_timeout_seconds"], 7)

    def test_spawn_failure_closes_output_files(self):
        job = WATCH.RegistrationRequest(("/missing-falcon-test-executable",), 20, self.root, ("owned", "id"))
        with self.assertRaises(FileNotFoundError):
            job.start()
        self.assertEqual(job.data["status"], "cancelled")
        self.assertFalse(job.files)

    def test_child_does_not_inherit_the_role_lock_descriptor(self):
        lock_path, gate, answer = (self.root / name for name in ("role.lock", "go", "answer"))
        lock = lock_path.open("a")
        try:
            CONNECT.fcntl.flock(lock, CONNECT.fcntl.LOCK_EX | CONNECT.fcntl.LOCK_NB)
            os.set_inheritable(lock.fileno(), True)
            code = ("import fcntl,time\nfrom pathlib import Path\n"
                    f"gate=Path({str(gate)!r})\n"
                    "while not gate.exists(): time.sleep(.01)\n"
                    f"lock=open({str(lock_path)!r},'a')\n"
                    "fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
                    f"Path({str(answer)!r}).write_text('acquired')\n")
            job = self.request(code)
            lock.close()
            gate.touch()
            job.process.wait(timeout=3)
            self.assertTrue(job.poll())
            self.assertEqual(job.data["status"], "returned")
            self.assertEqual(answer.read_text(), "acquired")
        finally:
            lock.close()

    def test_unresponsive_client_is_killed_during_cancel(self):
        ready = self.root / "ready"
        job = self.request("import signal,time\nfrom pathlib import Path\n"
                           "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                           f"Path({str(ready)!r}).touch()\ntime.sleep(60)\n")
        self.wait_file(ready)
        job.cancel("Ctrl+C cleanup")
        self.assertEqual(job.data["status"], "cancelled")
        self.assertEqual(job.process.returncode, -signal.SIGKILL)
        self.assertFalse(job.files)

    def test_ctrl_c_during_spawn_does_not_leave_an_unowned_child(self):
        real_spawn = subprocess.Popen
        children = []
        def spawn(*args, **kwargs):
            process = real_spawn(*args, **kwargs)
            children.append(process)
            os.kill(os.getpid(), signal.SIGINT)
            return process
        job = WATCH.RegistrationRequest((sys.executable, "-c", "import time; time.sleep(60)"),
                                        20, self.root, ("owned", "id"))
        try:
            with CONNECT.StopSignals(), patch.object(WATCH.subprocess, "Popen", spawn):
                with self.assertRaises(CONNECT.StopRequested):
                    job.start()
            self.assertEqual(job.data["status"], "cancelled")
            self.assertIsNotNone(job.process.returncode)
            self.assertFalse(job.files)
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
