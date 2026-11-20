#!/usr/bin/env python3
"""Wired UE2 startup lock/registration ordering with simulated hardware only."""

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/dual_fr1"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dual_ue_background_registration_test as background
import dual_ue_radio_recovery_test as radio
import dual_ue_reconnect_test as fixture
import connect_ue as CONNECT
import reconnect_ue as WATCH
import reconnect_ue2_wired20 as WIRED


class WiredStartupTest(unittest.TestCase):
    setUp = background.BackgroundRegistrationTest.setUp
    connect = fixture.ReconnectTest.connect
    lose_registration = background.BackgroundRegistrationTest.lose_registration

    def run_profile(self, **modem_options):
        original_role = CONNECT.ROLES[2]
        peer_role = CONNECT.ROLES[1]

        def run(argv):
            args = WATCH.arguments(argv)
            self.assertTrue(args.auto_cell_lock)
            self.assertEqual((args.ue, args.at_port), (2, WIRED.UE2_AT_PORT))
            directory = self.root / "wired20"
            directory.mkdir()
            self.wired_watcher = WATCH.Watcher(args, directory, self.log)
            self.modem = radio.FakeAT(**modem_options)

            def factory(*job_args):
                # A PLMN request must follow successful wired lock readback.
                self.assertEqual(self.modem.lock, "2,639648,30,78")
                self.assertIn('AT+QNWLOCK="common/5g"', self.modem.commands)
                job = background.PendingRequest(*job_args)
                self.jobs.append(job)
                return job

            self.wired_watcher.registration_factory = factory
            with self.modem.port():
                self.wired_watcher.attempt()
            return 0

        with patch.object(WATCH, "main", side_effect=run):
            self.assertEqual(WIRED.main(["--registration-timeout", "0", "--verbose", "3"]), 0)
        self.assertIs(CONNECT.ROLES[2], original_role)
        self.assertIs(CONNECT.ROLES[1], peer_role)
        return json.loads((self.wired_watcher.directory / "attempts.jsonl").read_text())

    def test_default_startup_restores_wired_lock_before_requesting_lab_plmn(self):
        self.connect(1)
        peer = self.network.survivor(2)
        self.network.changes.clear()
        self.lose_registration()
        record = self.run_profile()
        self.assertIn('AT+QNWLOCK="common/5g",2,639648,30,78', self.modem.commands)
        self.assertEqual(record["radio_recovery"]["verified_lock"], ["2", "639648", "30", "78"])
        self.assertEqual(len(self.jobs), 1)
        self.assertIn("--3gpp-register-in-operator=00101", self.jobs[0].command)
        self.assertEqual(self.wired_watcher.startup_radio["status"], "completed")
        self.assertFalse(self.wired_watcher.healthy)  # A lock/request alone does not prove access.
        self.assertFalse(any("--simple-connect=" in arg for cmd in self.network.changes for arg in cmd))
        self.assertEqual(self.network.survivor(2), peer)

    def test_ok_with_disabled_readback_cannot_start_registration_or_pdu(self):
        self.connect(1)
        peer = self.network.survivor(2)
        self.network.changes.clear()
        self.lose_registration()
        record = self.run_profile(wrong_lock=True)
        self.assertNotIn("verified_lock", record["radio_recovery"])
        self.assertEqual(record["radio_recovery"]["status"], "failed")
        self.assertFalse(self.jobs)
        self.assertFalse(self.wired_watcher.healthy)
        self.assertFalse(any("--simple-connect=" in arg for cmd in self.network.changes for arg in cmd))
        self.assertEqual(self.modem.cfun, 1)
        self.assertEqual(self.network.survivor(2), peer)

    def test_matching_wired_lock_is_reused_and_connection_checks_still_run(self):
        self.connect(2)
        self.network.changes.clear()
        record = self.run_profile(correct_settings=True, registered=True)
        self.assertEqual(record["radio_recovery"]["verified_lock"], ["2", "639648", "30", "78"])
        self.assertFalse(any(cmd.startswith('AT+QNWLOCK="common/5g",') for cmd in self.modem.commands))
        self.assertFalse(any(cmd.startswith("AT+CFUN=") for cmd in self.modem.commands))
        self.assertFalse(self.jobs)
        self.assertEqual(record["status"], "connected")
        self.assertTrue(self.wired_watcher.healthy)


if __name__ == "__main__":
    unittest.main()
