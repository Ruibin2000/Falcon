"""First expanded profile: numeric fidelity, missing data, derived values and SDK decoding."""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_identity import ROOT, du_event, ingest, ready
from metrics import EXPANDED, SEVEN, STAGE1, derive_failure_ratios
from text_report import format_record

COLLECTOR = Path(os.environ.get("FALCON_IDENTITY_COLLECTOR", "/tmp/falcon-xapp-ue-identity"))
PLUGIN = Path(os.environ.get("FALCON_IDENTITY_PLUGIN", "/tmp/falcon-ue-identity-sm/libkpm_sm.so"))


def expanded_event(du=1):
    event = du_event(du, stamp=12_000_000)
    row = event["rows"][0]
    row["granularity_ms"] = 100
    row["metrics"].update({
        "PUSCH.RSRP.dBFS": {"type": "real", "value": -13.125},
        "PUSCH.SNR.dB": {"type": "real", "value": 21.75},
        **{name: {"type": kind, "value": 0 if kind == "integer" else 0.0}
           for name, (_, kind) in STAGE1.items()},
    })
    row["metrics"]["UL.PHR.dB"]["value"] = -4.0
    row["metrics"]["UL.BSR.Bytes"]["value"] = (1 << 32) - 1
    row["metrics"]["DL.HARQ.Ok"]["value"] = 7
    row["metrics"]["DL.HARQ.Nok"]["value"] = 1
    row["metrics"]["UL.CRC.Ok"]["value"] = 3
    row["metrics"]["UL.CRC.Nok"]["value"] = 2
    return event


class ExpansionTests(unittest.TestCase):
    def test_both_ip_bindings_all_27_fields_signed_power_and_uint32_are_preserved(self):
        mapper = ready()
        for du in (1, 2):
            event = expanded_event(du)
            original = copy.deepcopy(event)
            result = ingest(mapper, event)[0]
            self.assertEqual(result["binding_status"], "matched")
            self.assertEqual(result["ue_ipv4"], f"10.{44+du}.0.10")
            metrics = result["row"]["metrics"]
            self.assertEqual(set(metrics), set(EXPANDED))
            for name, (unit, kind) in STAGE1.items():
                self.assertEqual(metrics[name]["unit"], unit)
                self.assertEqual(metrics[name]["type"], kind)
                self.assertEqual(metrics[name]["value"], original["rows"][0]["metrics"][name]["value"])
            self.assertEqual(event, original)
            self.assertEqual(result["derived_metrics"]["DL.HARQ.FailureRatio"]["value"], 12.5)
            self.assertEqual(result["derived_metrics"]["UL.CRC.FailureRatio"]["value"], 40.0)
            self.assertNotIn("DL.HARQ.FailureRatio", metrics)
            text = format_record(result)
            self.assertIn("UL.PHR.dB = -4.0 [dB] (real)", text)
            self.assertIn("UL.BSR.Bytes = 4294967295 [bytes] (integer)", text)
            self.assertIn("xApp-derived values (separate from E2 measurements):", text)

    def test_real_prb_fractional_values_keep_units_and_integer_fields_separate(self):
        event = expanded_event()
        metrics = event["rows"][0]["metrics"]
        metrics["RRU.PrbTotDl"]["value"] = 0
        metrics["PRB.UsageDl.Percent"]["value"] = 100.0 / 520.0
        metrics["PRB.UsageUl.Percent"]["value"] = 2.5
        result = ingest(ready(), event)[0]
        output = result["row"]["metrics"]
        self.assertEqual(output["PRB.UsageDl.Percent"],
                         {"type": "real", "value": 100.0 / 520.0, "unit": "%"})
        self.assertEqual(output["PRB.UsageUl.Percent"], {"type": "real", "value": 2.5, "unit": "%"})
        self.assertEqual(output["RRU.PrbTotDl"], {"type": "integer", "value": 0, "unit": "%"})
        self.assertIn("PRB.UsageUl.Percent = 2.5 [%] (real)", format_record(result))

    def test_no_value_and_measured_zero_remain_distinct(self):
        for name in STAGE1:
            event = expanded_event()
            event["rows"][0]["metrics"][name] = {"type": "no_value", "value": None}
            result = ingest(ready(), event)[0]
            self.assertEqual(result["row"]["metrics"][name],
                             {"type": "no_value", "value": None, "unit": STAGE1[name][0]})

    def test_failure_ratios_require_counts_and_a_nonzero_denominator(self):
        for counts in (
            {}, {"UL.CRC.Ok": {"type": "integer", "value": 0}},
            {"UL.CRC.Ok": {"type": "integer", "value": 0},
             "UL.CRC.Nok": {"type": "integer", "value": 0}},
            {"UL.CRC.Ok": {"type": "no_value", "value": None},
             "UL.CRC.Nok": {"type": "integer", "value": 1}},
            {"UL.CRC.Ok": {"type": "integer", "value": -1},
             "UL.CRC.Nok": {"type": "integer", "value": 1}},
        ):
            result = derive_failure_ratios(counts)
            if result:
                self.assertEqual(result["UL.CRC.FailureRatio"]["type"], "no_value")
                self.assertIsNone(result["UL.CRC.FailureRatio"]["value"])
            else:
                self.assertEqual(counts, {})

    def test_preserved_seven_metric_profile_adds_no_derived_fields(self):
        event = expanded_event()
        event["rows"][0]["metrics"] = {n: m for n, m in event["rows"][0]["metrics"].items() if n in SEVEN}
        result = ingest(ready(), event)[0]
        self.assertEqual(len(result["row"]["metrics"]), 7)
        self.assertNotIn("derived_metrics", result)


@unittest.skipUnless(COLLECTOR.is_file() and PLUGIN.is_file(), "build the collector and isolated plugin first")
class ExpandedCodecTests(unittest.TestCase):
    def test_actual_ocudu_aper_to_flexric_preserves_all_27_fields(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/du_expanded_codec.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            header, message = (Path(temporary) / n for n in ("header.asn", "message.asn"))
            header.write_bytes(bytes.fromhex(fixture["header_hex"]))
            message.write_bytes(bytes.fromhex(fixture["message_hex"]))
            run = subprocess.run([str(COLLECTOR), "--decode-fixture", str(header), str(message), str(PLUGIN)],
                                 check=True, capture_output=True, text=True, timeout=10)
        rows = json.loads(run.stdout)["rows"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(set(row["metrics"]), set(EXPANDED))
            self.assertEqual(row["granularity_ms"], 100)
            self.assertEqual(row["metrics"]["CQI"], {"type": "integer", "value": 11})
            self.assertEqual(row["metrics"]["CQI.Samples"], {"type": "integer", "value": 3})
            self.assertEqual(row["metrics"]["UL.MCS"], {"type": "integer", "value": 0})
            self.assertEqual(row["metrics"]["UL.PHR.dB"], {"type": "real", "value": -4})
            self.assertAlmostEqual(row["metrics"]["DL.MAC.Throughput"]["value"], 0.08, places=7)
            self.assertAlmostEqual(row["metrics"]["UL.MAC.Throughput"]["value"], 1234.56, places=3)
            self.assertEqual(row["metrics"]["RRU.PrbTotDl"]["value"], 3)
            self.assertEqual(row["metrics"]["PRB.UsageDl.Percent"]["type"], "real")
            self.assertAlmostEqual(row["metrics"]["PRB.UsageDl.Percent"]["value"], 1900.0 / 520.0, places=6)
            self.assertEqual(row["metrics"]["PRB.UsageUl.Percent"], {"type": "real", "value": 2.5})
            self.assertEqual(row["metrics"]["UL.BSR.Bytes"]["value"],
                             (1 << 32) - 1 if row["ue"]["gnb_cu_ue_f1ap_id"] == "7" else 25000)
