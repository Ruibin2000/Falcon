"""Offline collision tests; synthetic serials do not identify physical radios."""

import copy
import importlib.util
from pathlib import Path
import unittest


REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_config", REPO / "scripts/dual_fr1/check_config.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class DualConfigTest(unittest.TestCase):
    def setUp(self):
        self.cu = {"cu_cp": {"f1ap": {"bind_addrs": "127.0.10.1"}}}
        self.du1 = checker.load(REPO / "configs/ocudu/dual_fr1/du1_b210_n78_3660mhz.yml")
        self.du2 = checker.merge(
            checker.load(REPO / "configs/ocudu/dual_fr1/du2_b210_n78_40mhz.yml"),
            checker.load(REPO / "configs/ocudu/dual_fr1/du2_flexric.yml"))
        # Avoid dependence on an operator-owned /tmp log file's permissions.
        self.du1["log"]["filename"] = "/tmp/falcon-config-fixture-du1.log"
        self.du2["log"]["filename"] = "/tmp/falcon-config-fixture-du2.log"

    def use_synthetic_radio(self):
        self.du2["ru_sdr"]["device_args"] = "type=b200,serial=FIXTURE0002"

    def errors(self):
        return checker.validate(self.cu, self.du1, self.du2)[0]

    def test_template_cannot_pass_before_hardware_binding(self):
        self.du2["ru_sdr"]["device_args"] = "type=b200,serial=REPLACE_WITH_ACTUAL_DU2_SERIAL"
        self.assertTrue(any("actual B210 serial" in error for error in self.errors()))

    def test_split_e2_overlay_and_distinct_cell_identity(self):
        self.use_synthetic_radio()
        errors, rows = checker.validate(self.cu, self.du1, self.du2)
        self.assertEqual(errors, [])
        self.assertEqual([row["cgi"][1] for row in rows], [6733824, 6733825])

    def test_different_du_id_and_pci_do_not_prevent_duplicate_cgi(self):
        self.use_synthetic_radio()
        del self.du2["cell_cfg"]["sector_id"]
        self.assertIn("Duplicate cgi across DU1 and DU2", self.errors())

    def test_radio_and_f1u_collisions_are_rejected(self):
        self.du2["ru_sdr"]["device_args"] = self.du1["ru_sdr"]["device_args"]
        self.du2["f1u"] = copy.deepcopy(self.du1["f1u"])
        errors = self.errors()
        self.assertIn("Duplicate serial across DU1 and DU2", errors)
        self.assertIn("Duplicate f1u across DU1 and DU2", errors)

    def test_shared_gnb_and_ric_are_valid_but_mismatched_gnb_is_rejected(self):
        self.use_synthetic_radio()
        self.du2["gnb_id"] = 412
        self.assertTrue(any("gNB identity differs from CU" in error for error in self.errors()))

    def test_overlapping_and_out_of_range_channels_are_rejected(self):
        self.use_synthetic_radio()
        self.du2["cell_cfg"]["dl_arfcn"] = 643000
        self.assertIn("Nominal DU channels overlap", self.errors())
        self.du2["cell_cfg"]["dl_arfcn"] = 650000
        self.assertTrue(any("outside 3550-3700" in error for error in self.errors()))

    def test_missing_metric_overlay_and_shared_log_are_rejected(self):
        self.use_synthetic_radio()
        del self.du2["metrics"]
        self.du2["log"] = copy.deepcopy(self.du1["log"])
        errors = self.errors()
        self.assertTrue(any("scheduler/RLC" in error for error in errors))
        self.assertIn("Duplicate log across DU1 and DU2", errors)

    def test_old_one_second_source_cannot_pass_the_100ms_preflight(self):
        self.du2["metrics"]["periodicity"]["du_report_period"] = 1000
        self.assertIn("DU2: scheduler/RLC metrics and 100-ms reporting are required", self.errors())

    def test_stale_20mhz_du2_config_cannot_pass_current_preflight(self):
        self.du2["cell_cfg"]["channel_bandwidth_MHz"] = 20
        self.assertIn("DU2: expected explicit n78 / 40 MHz / 30 kHz", self.errors())

    def test_old_sampling_rate_cannot_pass_for_40mhz_du2(self):
        self.du2["ru_sdr"]["srate"] = 23.04
        self.assertIn("DU2: expected sample rate 46.08 MS/s", self.errors())

    def test_40mhz_channel_edges_are_used_for_overlap_detection(self):
        # At 3635.01 MHz, the old 20-MHz interval would not overlap DU1.
        self.du2["cell_cfg"]["dl_arfcn"] = 642334
        self.assertIn("Nominal DU channels overlap", self.errors())


if __name__ == "__main__":
    unittest.main()
