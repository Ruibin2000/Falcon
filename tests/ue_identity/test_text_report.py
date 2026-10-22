"""Text output must preserve missing values and never upgrade an uncertain binding."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_identity import ROOT, ready, du_event, ingest
from text_report import format_record


class TextReportTests(unittest.TestCase):
    def test_same_record_preserves_actual_identifiers_zero_and_no_value(self):
        event = du_event(1, stamp=12_000_000)
        event["rows"][0]["metrics"]["DRB.RlcSduDelayDl"] = {"type": "no_value", "value": None}
        record = ingest(ready(), event)[0]
        original = copy.deepcopy(record)
        text = format_record(record)
        self.assertIn("UE(gNB-CU UE F1AP ID)=1007", text)
        self.assertIn("AMF_UE_NGAP_ID=9001 RAN_UE_NGAP_ID=301", text)
        self.assertIn("SUPI=imsi-001010000000101", text)
        self.assertIn("UE_IPv4=10.45.0.10", text)
        self.assertIn("assurance=observed_unique_current_context", text)
        self.assertIn("DRB.RlcSduDelayDl = no_value [0.1 ms] (no_value)", text)
        self.assertIn("DRB.UEThpDl = 0 [kbit/s] (integer)", text)
        self.assertIn("incomplete=absent", text)
        record["row"]["incomplete"] = False
        self.assertIn("incomplete=false", format_record(record))
        record["row"]["incomplete"] = original["row"]["incomplete"]
        self.assertEqual(record, original)

    def test_unresolved_stale_or_ambiguous_cannot_leak_a_previous_binding(self):
        record = ingest(ready(), du_event())[0]
        for status in ("unresolved", "stale", "ambiguous"):
            record["binding_status"] = status
            text = format_record(record)
            self.assertIn(f"status={status}", text)
            self.assertIn("UE_IPv4=unknown", text)
            self.assertIn("SUPI=unknown AMF_UE_NGAP_ID=unknown RAN_UE_NGAP_ID=unknown", text)
            self.assertNotIn("10.45.0.10", text)
            self.assertNotIn("imsi-001010000000101", text)

    def test_cli_writes_same_number_of_records_and_refuses_overwrite(self):
        command = [sys.executable, str(ROOT / "scripts/ue_identity/xapp_ue_identity.py"),
                   "--replay", str(ROOT / "tests/ue_identity/fixtures/dual_replay.ndjson"),
                   "--observed-unique"]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "bindings.txt"
            capture = Path(directory) / "inputs.ndjson"
            command += ["--text-output", str(target), "--capture-events", str(capture)]
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
            rows = [json.loads(line) for line in result.stdout.splitlines()]
            text = target.read_text()
            self.assertIn("input_mode=captured-input replay", text)
            self.assertEqual(sum(line.startswith("record=") for line in text.splitlines()), len(rows))
            self.assertIn("UE_IPv4=10.45.0.10", text)
            self.assertIn("UE_IPv4=10.46.0.10", text)
            self.assertTrue(capture.read_text())
            result = subprocess.run(command[:-2], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("File exists", result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(target.read_text(), text)


if __name__ == "__main__":
    unittest.main()
