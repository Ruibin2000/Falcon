"""Independent OCUDU -> FlexRIC codec checks using explicitly synthetic bytes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_identity import ROOT, config, core_event, du_event, ingest
from mapping import Mapper

FIXTURES = Path(__file__).parent / "fixtures"
COLLECTOR = Path(os.environ.get("FALCON_IDENTITY_COLLECTOR", "/tmp/falcon-xapp-ue-identity"))
PLUGIN = Path(os.environ.get("FALCON_IDENTITY_PLUGIN", "/tmp/falcon-ue-identity-sm/libkpm_sm.so"))


@unittest.skipUnless(COLLECTOR.is_file() and PLUGIN.is_file(), "build the standalone collector/plugin first")
class CodecTests(unittest.TestCase):
    def test_real_sdk_config_and_plugin_directory_load_without_network(self):
        for name in ("xapp_ue_identity.conf", "ric_ue_identity.conf"):
            subprocess.run([str(COLLECTOR), "--check-config", str(ROOT / "configs/flexric" / name)],
                           check=True, capture_output=True, text=True, timeout=10)

    def test_independent_decoder_and_large_id_core_join(self):
        fixture = json.loads((FIXTURES / "cu_codec.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            header, message = (Path(temporary) / name for name in ("header.asn", "message.asn"))
            header.write_bytes(bytes.fromhex(fixture["header_hex"]))
            message.write_bytes(bytes.fromhex(fixture["message_hex"]))
            run = subprocess.run([str(COLLECTOR), "--decode-fixture", str(header), str(message), str(PLUGIN)],
                                 check=True, capture_output=True, text=True, timeout=10)
        event = json.loads(run.stdout)
        self.assertEqual(event["header_time_us"], "100000000")
        self.assertEqual(len(event["rows"]), 2)
        for index, row in enumerate(event["rows"]):
            self.assertEqual(row["ue"]["amf_ue_ngap_id"], str((1 << 39) + index))
            self.assertEqual(row["ue"]["f1ap_ids"], [str(1007 + index)])
            self.assertEqual(row["ue"]["guami"], config()["amf"]["guami"])
            self.assertEqual(row["metrics"]["FALCON.UE.RRCState"], {"type": "integer", "value": 1})
        mapper = Mapper(config())
        core = core_event()
        core["received_at_us"] = 100_000_000
        for index, ue in enumerate(core["amf"]):
            ue["gnb"]["amf_ue_ngap_id"] = str((1 << 39) + index)
        ingest(mapper, core)
        event["received_at_us"] = 100_100_000
        ingest(mapper, event)
        for du in (1, 2):
            ingest(mapper, du_event(du, f1=1006 + du, stamp=101_000_000))
        for du, ip in ((1, "10.45.0.10"), (2, "10.46.0.10")):
            result = ingest(mapper, du_event(du, f1=1006 + du, stamp=102_000_000))[0]
            self.assertEqual(result["ue_ipv4"], ip)
            self.assertEqual(result["binding"]["assurance"], "observed_unique_current_context")


class ReplayTests(unittest.TestCase):
    def test_launcher_strict_and_explicit_experimental_modes(self):
        command = [sys.executable, str(ROOT / "scripts/ue_identity/xapp_ue_identity.py"),
                   "--replay", str(FIXTURES / "dual_replay.ndjson")]
        strict = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
        strict_rows = [json.loads(line) for line in strict.stdout.splitlines()]
        self.assertEqual(len(strict_rows), 4)
        self.assertTrue(all(row["ue_ipv4"] is None for row in strict_rows))
        observed = subprocess.run(command + ["--observed-unique"], check=True,
                                  capture_output=True, text=True, timeout=10)
        rows = [json.loads(line) for line in observed.stdout.splitlines()]
        self.assertEqual([row["ue_ipv4"] for row in rows[-2:]], ["10.45.0.10", "10.46.0.10"])
        self.assertEqual(rows[-1]["row"]["metrics"]["DRB.RlcSduDelayDl"]["value"], 13.8)


if __name__ == "__main__":
    unittest.main()
