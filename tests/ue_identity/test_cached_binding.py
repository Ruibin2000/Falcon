"""Historical bindings may bridge missing updates, never known context changes."""

import copy
import unittest

from test_identity import config, core_event, cu_event, du_event, ingest
from mapping import Mapper
from text_report import format_record


def cached_ready():
    settings = config()
    settings["binding_policy"] = "last_known"
    mapper = Mapper(settings)
    for event in (core_event(), cu_event(), du_event(1), du_event(2), du_event(1, stamp=12_000_000)):
        ingest(mapper, event)
    return mapper


def refresh_own_sources(mapper, stamp=14_000_000):
    core, cu = core_event(), cu_event()
    core["received_at_us"] = stamp
    cu.update(received_at_us=stamp + 20_000, header_time_us=str(stamp + 10_000))
    cu["rows"] = cu["rows"][:1]
    ingest(mapper, core)
    ingest(mapper, cu)


class CachedBindingTests(unittest.TestCase):
    def test_other_du_silence_keeps_fresh_own_relation_matched_and_preserves_metrics(self):
        mapper = cached_ready()
        refresh_own_sources(mapper)
        event = du_event(1, stamp=14_200_000)
        original = copy.deepcopy(event)
        result = ingest(mapper, event)[0]
        self.assertEqual(result["binding_status"], "matched")
        self.assertEqual(result["ue_ipv4"], "10.45.0.10")
        self.assertEqual(result["binding"]["supi"], "imsi-001010000000101")
        self.assertEqual(result["binding"]["assurance"], "established_du_scope_current_context")
        self.assertNotIn("last_verified_at_us", result["binding"])
        copied = copy.deepcopy(result["row"])
        for value in copied["metrics"].values():
            value.pop("unit")
        self.assertEqual(copied, original["rows"][0])
        self.assertEqual(event, original)
        text = format_record(result)
        self.assertIn("status=matched", text)
        self.assertIn("UE_IPv4=10.45.0.10", text)
        self.assertNotIn("validity=last_known_unverified", text)

    def test_core_timeout_keeps_history_and_recovery_verifies_again(self):
        mapper = cached_ready()
        mapper.ingest({"kind": "core_error", "reason": "HTTP timeout"}, 12_200_000)
        result = ingest(mapper, du_event(1, stamp=12_300_000))[0]
        self.assertEqual(result["binding_status"], "cached")
        self.assertIn("HTTP timeout", result["reason"])
        refresh_own_sources(mapper, 12_500_000)
        result = ingest(mapper, du_event(1, stamp=12_600_000))[0]
        self.assertEqual(result["binding_status"], "matched")

    def test_fresh_own_relation_does_not_expire_because_other_du_is_idle(self):
        mapper = cached_ready()
        refresh_own_sources(mapper, 300_000_000)
        result = ingest(mapper, du_event(1, stamp=300_100_000))[0]
        self.assertEqual((result["binding_status"], result["ue_ipv4"]), ("matched", "10.45.0.10"))

    def test_actual_own_cu_silence_uses_labelled_history(self):
        mapper = cached_ready()
        # Core remains current; this UE's own CU row has not been refreshed.
        core = core_event()
        core["received_at_us"] = 300_000_000
        ingest(mapper, core)
        result = ingest(mapper, du_event(1, stamp=300_100_000))[0]
        self.assertEqual((result["binding_status"], result["ue_ipv4"]), ("cached", "10.45.0.10"))
        self.assertGreater(result["binding"]["age_ms"], 280_000)
        text = format_record(result)
        self.assertIn("validity=last_known_unverified", text)
        self.assertIn("last_verified=1970-01-01T00:00:12.100000Z", text)

    def test_fresh_only_also_matches_independently_and_never_falls_back(self):
        mapper = cached_ready()
        mapper.binding_policy = "fresh_only"
        refresh_own_sources(mapper)
        self.assertEqual(ingest(mapper, du_event(1, stamp=14_200_000))[0]["binding_status"], "matched")
        mapper.ingest({"kind": "core_error", "reason": "timeout"}, 14_400_000)
        result = ingest(mapper, du_event(1, stamp=14_500_000))[0]
        self.assertEqual(result["binding_status"], "stale")
        self.assertIsNone(result["ue_ipv4"])

    def test_idle_other_ue_does_not_retire_own_binding(self):
        mapper = cached_ready()
        event = core_event()
        event["amf"][1].update(cm_state="idle", gnb={"status": "not-connected"})
        event["received_at_us"] = 14_000_000
        ingest(mapper, event)
        cu = cu_event()
        cu.update(received_at_us=14_020_000, header_time_us="14010000")
        cu["rows"] = cu["rows"][:1]
        ingest(mapper, cu)
        result = ingest(mapper, du_event(1, stamp=14_100_000))[0]
        self.assertEqual((result["binding_status"], result["ue_ipv4"]), ("matched", "10.45.0.10"))
        self.assertFalse(any(key[0][-1] == "2" for key in mapper.last_bindings))

    def test_other_ue_new_context_cannot_downgrade_this_ue(self):
        mapper = cached_ready()
        core = core_event()
        core["received_at_us"] = 14_000_000
        core["amf"][1]["gnb"].update(amf_ue_ngap_id=9102, ran_ue_ngap_id=402)
        ingest(mapper, core)
        cu = cu_event((1007, 2010))
        cu.update(received_at_us=14_020_000, header_time_us="14010000")
        cu["rows"][1]["ue"]["amf_ue_ngap_id"] = "9102"
        ingest(mapper, cu)
        result = ingest(mapper, du_event(1, stamp=14_100_000))[0]
        self.assertEqual((result["binding_status"], result["ue_ipv4"]), ("matched", "10.45.0.10"))
        self.assertEqual(result["binding"]["amf_ue_ngap_id"], "9001")

    def test_current_ip_change_can_match_on_established_radio_scope(self):
        mapper = cached_ready()
        core = core_event()
        core["received_at_us"] = 14_000_000
        core["smf"][0]["pdu"][0]["ipv4"] = "10.45.0.99"
        ingest(mapper, core)
        cu = cu_event()
        cu.update(received_at_us=14_020_000, header_time_us="14010000")
        cu["rows"] = cu["rows"][:1]
        ingest(mapper, cu)
        result = ingest(mapper, du_event(1, stamp=14_200_000))[0]
        self.assertEqual((result["binding_status"], result["ue_ipv4"]), ("matched", "10.45.0.99"))
        self.assertNotIn("last_verified_at_us", result["binding"])

    def test_current_multiple_sessions_cannot_fall_back_to_single_old_ip(self):
        mapper = cached_ready()
        core = core_event()
        core["received_at_us"] = 14_000_000
        core["smf"][0]["pdu"].append(dict(core["smf"][0]["pdu"][0], psi=2, ipv4="10.45.0.99"))
        ingest(mapper, core)
        cu = cu_event()
        cu.update(received_at_us=14_020_000, header_time_us="14010000")
        ingest(mapper, cu)
        result = ingest(mapper, du_event(1, stamp=14_200_000))[0]
        self.assertEqual(result["binding_status"], "ambiguous")
        self.assertIsNone(result["ue_ipv4"])

    def test_new_cu_f1_list_cannot_resurrect_old_scope_with_other_du_fresh(self):
        mapper = cached_ready()
        cu = cu_event((1008, 2007))
        cu.update(received_at_us=12_300_000, header_time_us="12200000")
        ingest(mapper, cu)
        ingest(mapper, du_event(2, stamp=12_400_000))
        result = ingest(mapper, du_event(1, stamp=12_500_000))[0]
        self.assertIsNone(result["ue_ipv4"])
        self.assertNotIn((next(iter(mapper.allowed)), "1007"), mapper.radio_scopes)

    def test_known_core_changes_never_reuse_old_ip_or_ngap_identity(self):
        for change in ("idle", "missing_ue", "missing_session", "ip", "ran_id", "amf_id"):
            with self.subTest(change=change):
                mapper = cached_ready()
                event = core_event()
                if change == "idle":
                    event["amf"][0].update(cm_state="idle", gnb={})
                elif change == "missing_ue":
                    event["amf"].pop(0)
                elif change == "missing_session":
                    event["smf"][0]["pdu"] = []
                elif change == "ip":
                    event["smf"][0]["pdu"][0]["ipv4"] = "10.45.0.99"
                else:
                    event["amf"][0]["gnb"]["ran_ue_ngap_id" if change == "ran_id" else "amf_ue_ngap_id"] = 999
                event["received_at_us"] = 14_000_000
                ingest(mapper, event)
                # The other DU is no longer current; fresh confirmation cannot
                # accidentally hide failure of the historical-binding checks.
                result = ingest(mapper, du_event(1, stamp=14_200_000))[0]
                self.assertIsNone(result["ue_ipv4"])
                self.assertNotEqual(result["binding_status"], "cached")

    def test_explicit_cu_retirement_and_new_f1_do_not_reuse_old_binding(self):
        for change in ("unavailable", "new_f1", "reused_f1"):
            with self.subTest(change=change):
                mapper = cached_ready()
                event = cu_event()
                event.update(header_time_us="12300000", received_at_us=12_400_000)
                if change == "unavailable":
                    event["rows"][0]["metrics"]["FALCON.UE.RRCState"] = {"type": "no_value", "value": None}
                elif change == "new_f1":
                    event["rows"][0]["ue"]["f1ap_ids"] = ["1008"]
                else:
                    event["rows"][0]["ue"]["amf_ue_ngap_id"] = "999"
                ingest(mapper, event)
                # Force a missing-source result that would otherwise allow fallback.
                result = ingest(mapper, du_event(1, stamp=14_200_000))[0]
                self.assertIsNone(result["ue_ipv4"])
                self.assertNotEqual(result["binding_status"], "cached")

    def test_queue_loss_and_du_collision_never_fall_back(self):
        mapper = cached_ready()
        mapper.ingest({"kind": "ingress_loss"}, 12_200_000)
        result = ingest(mapper, du_event(1, stamp=12_300_000))[0]
        self.assertIsNone(result["ue_ipv4"])
        mapper = cached_ready()
        ingest(mapper, du_event(2, f1=1007, stamp=12_200_000))
        self.assertEqual(ingest(mapper, du_event(1, stamp=12_300_000))[0]["binding_status"], "ambiguous")
        refresh_own_sources(mapper, 30_000_000)
        self.assertIsNone(ingest(mapper, du_event(1, stamp=30_100_000))[0]["ue_ipv4"])

    def test_cold_start_and_new_du_key_cannot_borrow_someone_elses_binding(self):
        mapper = cached_ready()
        for event in (du_event(1, f1=1008, stamp=14_200_000), du_event(2, f1=1007, stamp=14_300_000)):
            self.assertIsNone(ingest(mapper, event)[0]["ue_ipv4"])
        settings = config()
        settings["binding_policy"] = "last_known"
        self.assertIsNone(ingest(Mapper(settings), du_event())[0]["ue_ipv4"])

    def test_delayed_sample_before_verification_does_not_borrow_history(self):
        mapper = cached_ready()
        mapper.ingest({"kind": "core_error", "reason": "timeout"}, 12_200_000)
        self.assertIsNone(ingest(mapper, du_event(1, stamp=11_500_000))[0]["ue_ipv4"])


if __name__ == "__main__":
    unittest.main()
