"""Verify byte/timing alignment without a radio or a running DU."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/dual_fr1"))
import extract_du_gain_times as GAINS


class GainTimingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / "startup.log"
        self.timing = Path(str(self.log) + ".timing")

    def recording(self, chunks, delays=None):
        self.log.write_bytes(b'Script started on date [COMMAND="fake"]\n' + b"".join(chunks)
                             + b'\nScript done on date [COMMAND_EXIT_CODE="0"]\n')
        if delays is None:
            delays = ["0"] * len(chunks)
        self.timing.write_text("H 0.000000 START_TIME ignored\n" + "".join(
            f"O {delay} {len(chunk)}\n" for delay, chunk in zip(delays, chunks)))

    def test_split_output_and_non_output_records_preserve_relative_time(self):
        marker = b"FALCON_CONSOLE_CLOCK 2026-10-24T21:00:00.123456789Z\r\n"
        self.recording([marker, b"Tx gain set to 7", b"0 dB for port 0.\r\n"], ["0.4", "1.2", "0.3"])
        self.timing.write_text(self.timing.read_text().replace("O 0.3", "S 0.1 SIGWINCH\nO 0.3"))
        events = GAINS.gain_events(self.log, self.timing)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["time_utc"], "2026-10-24T21:00:01.723456+00:00")
        self.assertEqual((events[0]["direction"], events[0]["gain_db"]), ("tx", 70))

    def test_old_recording_without_clock_marker_is_not_given_invented_times(self):
        self.recording([b"Tx gain set to 70 dB for port 0.\r\n"])
        with self.assertRaisesRegex(ValueError, "No UTC clock marker"):
            GAINS.gain_events(self.log, self.timing)

    def test_partial_live_record_does_not_create_a_gain_event(self):
        marker = b"FALCON_CONSOLE_CLOCK 2026-10-24T21:00:00.123456Z\r\n"
        self.recording([marker, b"Rx gain set to 30 dB for port 0.\r\n"])
        timing = self.timing.read_bytes()
        self.timing.write_bytes(timing[:timing.rfind(b"O ")] + b"O 0.1")
        self.assertEqual(GAINS.gain_events(self.log, self.timing), [])

    def test_missing_output_and_input_logging_are_rejected(self):
        self.recording([b"data"])
        self.timing.write_text("O 0 99999\n")
        with self.assertRaisesRegex(ValueError, "shorter"):
            GAINS.gain_events(self.log, self.timing)
        self.timing.write_text("I 0 10\n")
        with self.assertRaisesRegex(ValueError, "input records"):
            GAINS.gain_events(self.log, self.timing)

    def test_latest_du_does_not_fall_back_to_an_older_timed_run(self):
        older, newer = [self.root / f"falcon-du2-{name}" for name in ("old", "new")]
        for folder in (older, newer):
            folder.mkdir()
            (folder / "startup.log").write_text("console")
        Path(str(older / "startup.log") + ".timing").write_text("timing")
        import os
        os.utime(older / "startup.log", ns=(1000, 1000))
        os.utime(newer / "startup.log", ns=(2000, 2000))
        with patch.object(GAINS, "Path", side_effect=lambda p: self.root if p == "/tmp" else Path(p)):
            self.assertEqual(GAINS.latest_console(2), newer / "startup.log")


if __name__ == "__main__":
    unittest.main()
