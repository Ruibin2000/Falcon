"""Explicit CU DU scope, duplicate per-DU IDs, retirement and reuse guards."""

import copy
import unittest

from test_identity import config, core_event, cu_event, du_event, ingest
from mapping import Mapper


def scoped_cu(f1s=(1, 1), stamp=10_500_000):
    event = cu_event(f1s)
    event.update(received_at_us=stamp, header_time_us=str(stamp - 100_000))
    for du, row in enumerate(event["rows"], 1):
        row["ue"]["ran_ue_id_hex"] = f"{(du << 28) | (40 + du):016x}"
    return event


def ready_scoped(strict=False):
    cfg = config()
    if strict:
        cfg["du_scope_mode"] = "strict"
    mapper = Mapper(cfg)
    ingest(mapper, core_event())
    ingest(mapper, scoped_cu())
    return mapper


class ScopedIdentityTests(unittest.TestCase):
    def test_two_du_f1_id_one_matches_both_even_in_strict_mode(self):
        mapper = ready_scoped(strict=True)
        for du in (1, 2, 1, 2):
            row = ingest(mapper, du_event(du, f1=1))[0]
            self.assertEqual(row["ue_ipv4"], f"10.{44+du}.0.10")
            self.assertEqual(row["binding"]["serving_du_id"], str(du))
            self.assertEqual(row["binding"]["cu_ue_index"], str(40+du))
            self.assertEqual(row["binding"]["assurance"], "cu_reported_du_scope")

    def test_explicit_scope_does_not_wait_for_other_du(self):
        mapper = ready_scoped()
        row = ingest(mapper, du_event(1, f1=1))[0]
        self.assertEqual(row["binding_status"], "matched")

    def test_upgraded_identity_can_resolve_legacy_cross_du_taint(self):
        mapper = Mapper(config())
        ingest(mapper, core_event())
        ingest(mapper, cu_event((1, 1)))
        ingest(mapper, du_event(1, f1=1))
        self.assertEqual(ingest(mapper, du_event(2, f1=1))[0]["binding_status"], "ambiguous")
        ingest(mapper, scoped_cu(stamp=11_500_000))
        for du in (1, 2):
            self.assertEqual(ingest(mapper, du_event(du, f1=1, stamp=12_000_000))[0]["binding_status"], "matched")

    def test_reestablishment_with_new_f1_keeps_peer_binding(self):
        mapper = ready_scoped()
        for du in (1, 2):
            ingest(mapper, du_event(du, f1=1))
        changed = scoped_cu((1, 2), stamp=11_500_000)
        changed["rows"][1]["ue"]["ran_ue_id_hex"] = f"{(2 << 28) | 43:016x}"
        ingest(mapper, changed)
        self.assertIsNone(ingest(mapper, du_event(2, f1=1, stamp=12_000_000))[0]["ue_ipv4"])
        self.assertEqual(ingest(mapper, du_event(1, f1=1, stamp=12_000_000))[0]["ue_ipv4"], "10.45.0.10")
        self.assertEqual(ingest(mapper, du_event(2, f1=2, stamp=12_000_000))[0]["ue_ipv4"], "10.46.0.10")

    def test_report_before_new_relation_is_not_relabelled(self):
        mapper = ready_scoped()
        ingest(mapper, scoped_cu((1, 2), stamp=11_500_000))
        self.assertIsNone(ingest(mapper, du_event(2, f1=2, stamp=11_400_000))[0]["ue_ipv4"])

    def test_same_du_same_f1_new_context_remains_quarantined(self):
        mapper = ready_scoped()
        changed = scoped_cu(stamp=11_500_000)
        changed["rows"][0]["ue"]["ran_ue_id_hex"] = f"{(1 << 28) | 99:016x}"
        ingest(mapper, changed)
        row = ingest(mapper, du_event(1, f1=1, stamp=12_000_000))[0]
        self.assertEqual(row["binding_status"], "ambiguous")
        self.assertIsNone(row["ue_ipv4"])
        self.assertEqual(ingest(mapper, du_event(2, f1=1, stamp=12_000_000))[0]["binding_status"], "matched")

    def test_explicit_release_withdraws_only_own_scope(self):
        mapper = ready_scoped()
        released = scoped_cu(stamp=11_500_000)
        released["rows"][0]["metrics"]["FALCON.UE.RRCState"]["value"] = 0
        ingest(mapper, released)
        self.assertIsNone(ingest(mapper, du_event(1, f1=1, stamp=12_000_000))[0]["ue_ipv4"])
        self.assertEqual(ingest(mapper, du_event(2, f1=1, stamp=12_000_000))[0]["ue_ipv4"], "10.46.0.10")

    def test_stale_cu_is_not_hidden_by_explicit_scope(self):
        mapper = ready_scoped()
        event = core_event()
        event["received_at_us"] = 14_000_000
        ingest(mapper, event)
        self.assertEqual(ingest(mapper, du_event(1, f1=1, stamp=14_100_000))[0]["binding_status"], "stale")

    def test_ingress_loss_still_blocks_explicit_match(self):
        mapper = ready_scoped()
        mapper.ingest({"kind": "ingress_loss"}, 11_000_000)
        self.assertIsNone(ingest(mapper, du_event(1, f1=1))[0]["ue_ipv4"])

    def test_unadmitted_or_malformed_allocation_is_rejected(self):
        for raw in ("0000000030000001", "xyz", 1, "0" * 17):
            mapper = ready_scoped()
            event = scoped_cu()
            event["rows"][0]["ue"]["ran_ue_id_hex"] = raw
            with self.assertRaises(ValueError):
                ingest(mapper, event)

    def test_opaque_ran_id_requires_explicit_allocation_configuration(self):
        cfg = config()
        del cfg["cu"]["ran_ue_id_format"]
        cfg["du_scope_mode"] = "strict"
        mapper = Mapper(cfg)
        ingest(mapper, core_event())
        ingest(mapper, scoped_cu())
        self.assertIsNone(ingest(mapper, du_event(1, f1=1))[0]["ue_ipv4"])

    def test_full_36_bit_du_scope_and_input_immutability(self):
        cfg = config()
        cfg["du_nodes"][0]["du_id"] = str((1 << 36) - 1)
        mapper = Mapper(cfg)
        ingest(mapper, core_event())
        event = scoped_cu()
        event["rows"][0]["ue"]["ran_ue_id_hex"] = f"{(((1 << 36) - 1) << 28) | 41:016x}"
        original = copy.deepcopy(event)
        ingest(mapper, event)
        self.assertEqual(event, original)
        data = du_event(1, f1=1)
        data["node"]["du_id"] = str((1 << 36) - 1)
        self.assertEqual(ingest(mapper, data)[0]["ue_ipv4"], "10.45.0.10")


if __name__ == "__main__":
    unittest.main()
