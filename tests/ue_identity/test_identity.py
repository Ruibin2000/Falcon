"""Independent lifecycle/API fixtures; no RIC, Core or radio processes required."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/ue_identity"))
from core import InfoAPI, guami_key, integer, normalize
from mapping import Mapper
from xapp_ue_identity import BoundedEvents


def config():
    value = json.loads((ROOT / "configs/ue_identity/local.json").read_text())
    value["du_scope_mode"] = "observed_unique"
    value["binding_policy"] = "fresh_only"
    return value


def core_event():
    return {"kind": "core_snapshot", "received_at_us": 10_000_000,
            "amf": [{"supi": f"imsi-00101000000010{i}", "cm_state": "connected",
                     "gnb": {"amf_ue_ngap_id": 9000 + i, "ran_ue_ngap_id": 300 + i, "gnb_id": 411}}
                    for i in (1, 2)],
            "smf": [{"supi": f"imsi-00101000000010{i}",
                     "pdu": [{"psi": 1, "dnn": "internet" if i == 1 else "internet2",
                              "ipv4": f"10.{44+i}.0.10", "pdu_state": "inactive"}]}
                    for i in (1, 2)]}


def cu_event(f1s=(1007, 2007)):
    return {"kind": "kpm_report", "received_at_us": 10_500_000, "header_time_us": "10400000",
            "node": {"mcc": "001", "mnc": "01", "gnb_id": "411", "node_type": "ngran_gNB", "du_id": None},
            "rows": [{"ue": {"id_type": "gnb", "amf_ue_ngap_id": str(9000+i),
                             "guami": config()["amf"]["guami"], "f1ap_ids": [str(f1)]},
                      "sample_idx": 0, "incomplete": None,
                      "metrics": {"FALCON.UE.RRCState": {"type": "integer", "value": 1}}}
                     for i, f1 in zip((1, 2), f1s)]}


def du_event(du=1, f1=None, stamp=11_000_000):
    f1 = f1 if f1 is not None else (1007 if du == 1 else 2007)
    return {"kind": "kpm_report", "received_at_us": stamp + 100_000, "header_time_us": str(stamp),
            "node": copy.deepcopy(config()["du_nodes"][du-1]),
            "rows": [{"ue": {"id_type": "gnb_du", "gnb_cu_ue_f1ap_id": str(f1)},
                      "sample_idx": 0, "incomplete": None,
                      "metrics": {"DRB.RlcSduDelayDl": {"type": "real", "value": 13.8},
                                  "DRB.UEThpDl": {"type": "integer", "value": 0},
                                  "DRB.UEThpUl": {"type": "real", "value": 1234.5},
                                  "RRU.PrbTotDl": {"type": "integer", "value": 0},
                                  "RRU.PrbTotUl": {"type": "integer", "value": 86}}}]}


def ingest(mapper, event):
    return mapper.ingest(event, event["received_at_us"])


def ready():
    mapper = Mapper(config())
    ingest(mapper, core_event())
    ingest(mapper, cu_event())
    ingest(mapper, du_event(1))
    ingest(mapper, du_event(2))
    return mapper


class AssociationTests(unittest.TestCase):
    def test_two_paths_preserve_values_units_and_do_not_modify_input(self):
        mapper = ready()
        for du, ip in ((1, "10.45.0.10"), (2, "10.46.0.10")):
            event = du_event(du, stamp=12_000_000)
            original = copy.deepcopy(event)
            row = ingest(mapper, event)[0]
            self.assertEqual((row["binding_status"], row["ue_ipv4"]), ("matched", ip))
            self.assertEqual(row["binding"]["supi"], f"imsi-00101000000010{du}")
            self.assertEqual(row["binding"]["ran_ue_ngap_id"], str(300 + du))
            self.assertEqual(row["row"]["metrics"]["DRB.RlcSduDelayDl"]["value"], 13.8)
            self.assertEqual(row["row"]["metrics"]["DRB.RlcSduDelayDl"]["unit"], "0.1 ms")
            self.assertEqual(row["row"]["metrics"]["DRB.UEThpDl"]["value"], 0)
            self.assertEqual(event, original)

    def test_ran_context_change_does_not_relabel_earlier_sample(self):
        mapper = ready()
        event = core_event()
        event["received_at_us"] = 11_500_000
        event["amf"][0]["gnb"]["ran_ue_ngap_id"] = 999
        ingest(mapper, event)
        self.assertIsNone(ingest(mapper, du_event(1, stamp=11_400_000))[0]["ue_ipv4"])
        row = ingest(mapper, du_event(1, stamp=12_000_000))[0]
        self.assertEqual(row["binding"]["ran_ue_ngap_id"], "999")

    def test_strict_mode_never_claims_du_scope_from_standard_ueid(self):
        mapper = ready()
        mapper.config["du_scope_mode"] = "strict"
        row = ingest(mapper, du_event())[0]
        self.assertEqual(row["binding_status"], "unresolved")
        self.assertIsNone(row["ue_ipv4"])

    def test_first_du_waits_for_other_admitted_source(self):
        mapper = Mapper(config())
        ingest(mapper, core_event())
        ingest(mapper, cu_event())
        self.assertIsNone(ingest(mapper, du_event())[0]["ue_ipv4"])

    def test_du_before_cu_is_not_retroactively_relabelled(self):
        mapper = Mapper(config())
        ingest(mapper, core_event())
        ingest(mapper, du_event(2))
        self.assertIsNone(ingest(mapper, du_event(1))[0]["ue_ipv4"])
        later = cu_event()
        later["received_at_us"] = 12_000_000
        later["header_time_us"] = "11900000"
        ingest(mapper, later)
        self.assertIsNone(ingest(mapper, du_event(1, stamp=11_800_000))[0]["ue_ipv4"])

    def test_different_report_rates_reuse_valid_relation(self):
        mapper = ready()
        for stamp in range(11_200_000, 12_900_000, 100_000):
            row = ingest(mapper, du_event(1, stamp=stamp))[0]
            self.assertEqual(row["ue_ipv4"], "10.45.0.10")

    def test_core_error_immediately_withholds_identity(self):
        mapper = ready()
        mapper.ingest({"kind": "core_error", "reason": "timeout"}, 11_500_000)
        row = ingest(mapper, du_event(1, stamp=12_000_000))[0]
        self.assertEqual(row["binding_status"], "stale")
        self.assertIsNone(row["ue_ipv4"])

    def test_cu_stale_despite_fresh_du_and_core(self):
        mapper = ready()
        core = core_event()
        core["received_at_us"] = 14_000_000
        ingest(mapper, core)
        ingest(mapper, du_event(2, stamp=14_100_000))
        row = ingest(mapper, du_event(1, stamp=14_200_000))[0]
        self.assertEqual(row["binding_status"], "stale")

    def test_missing_cu_row_does_not_imply_release(self):
        mapper = ready()
        event = cu_event()
        event.update(rows=[], header_time_us="11000000")
        ingest(mapper, event)
        self.assertEqual(ingest(mapper, du_event())[0]["ue_ipv4"], "10.45.0.10")

    def test_explicit_cu_unavailable_state_withdraws_candidate(self):
        for state in ({"type": "integer", "value": 2}, {"type": "no_value", "value": None}):
            mapper = ready()
            event = cu_event()
            event["header_time_us"] = "11000000"
            event["rows"][0]["metrics"]["FALCON.UE.RRCState"] = state
            ingest(mapper, event)
            self.assertIsNone(ingest(mapper, du_event())[0]["ue_ipv4"])

    def test_sixty_four_current_contexts_remain_separate(self):
        mapper = Mapper(config())
        core, cu = core_event(), cu_event()
        core["amf"], core["smf"], cu["rows"] = [], [], []
        rows = {1: [], 2: []}
        for index in range(64):
            du = index % 2 + 1
            owner = f"imsi-00101{index:010d}"
            ip = f"10.{44+du}.0.{index+1}"
            core["amf"].append({"supi": owner, "cm_state": "connected",
                                "gnb": {"gnb_id": 411, "amf_ue_ngap_id": 5000+index, "ran_ue_ngap_id": 100+index}})
            core["smf"].append({"supi": owner, "pdu": [{"psi": 1, "dnn": "internet",
                                                       "ipv4": ip, "pdu_state": "active"}]})
            row = copy.deepcopy(cu_event()["rows"][0])
            row["ue"].update(amf_ue_ngap_id=str(5000+index), f1ap_ids=[str(1000+index)])
            cu["rows"].append(row)
            rows[du].extend(du_event(du, f1=1000+index)["rows"])
        ingest(mapper, core)
        ingest(mapper, cu)
        for stamp in (11_000_000, 12_000_000):
            for du in (1, 2):
                event = du_event(du, stamp=stamp)
                event["rows"] = rows[du]
                output = ingest(mapper, event)
                if stamp == 12_000_000:
                    self.assertEqual(len(output), 32)
                    for row in output:
                        index = int(row["row"]["ue"]["gnb_cu_ue_f1ap_id"]) - 1000
                        self.assertEqual(row["ue_ipv4"], f"10.{44+du}.0.{index+1}")

    def test_same_f1_id_in_two_cu_contexts_is_ambiguous(self):
        mapper = ready()
        event = cu_event((1007, 1007))
        event["header_time_us"] = "11000000"
        ingest(mapper, event)
        self.assertEqual(ingest(mapper, du_event())[0]["binding_status"], "ambiguous")

    def test_same_f1_id_seen_on_two_dus_is_ambiguous(self):
        mapper = ready()
        ingest(mapper, du_event(2, f1=1007))
        self.assertEqual(ingest(mapper, du_event())[0]["binding_status"], "ambiguous")

    def test_reused_key_does_not_recover_after_timer(self):
        mapper = ready()
        changed = cu_event()
        changed["header_time_us"] = "11000000"
        changed["rows"][0]["ue"]["amf_ue_ngap_id"] = "9999"
        ingest(mapper, changed)
        core = core_event()
        core["received_at_us"] = 30_000_000
        ingest(mapper, core)
        ingest(mapper, du_event(2, stamp=30_100_000))
        self.assertEqual(ingest(mapper, du_event(1, stamp=30_200_000))[0]["binding_status"], "ambiguous")

    def test_multiple_sessions_do_not_duplicate_ue_metrics(self):
        mapper = ready()
        event = core_event()
        pdu = copy.deepcopy(event["smf"][0]["pdu"][0])
        pdu.update(psi=2, ipv4="10.45.0.11")
        event["smf"][0]["pdu"].append(pdu)
        event["received_at_us"] = 11_500_000
        ingest(mapper, event)
        rows = ingest(mapper, du_event(1, stamp=12_000_000))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["binding_status"], "ambiguous")

    def test_wrong_guami_or_gnb_never_matches(self):
        mapper = ready()
        event = core_event()
        event["amf"][0]["gnb"]["gnb_id"] = 412
        ingest(mapper, event)
        self.assertIsNone(ingest(mapper, du_event())[0]["ue_ipv4"])

    def test_idle_session_retained_but_idle_amf_not_radio_context(self):
        event = core_event()
        self.assertEqual(len(normalize(config(), event["amf"], event["smf"])), 2)
        event["amf"][0]["cm_state"] = "idle"
        self.assertEqual(len(normalize(config(), event["amf"], event["smf"])), 1)

    def test_no_value_and_incomplete_preserved(self):
        mapper = ready()
        event = du_event()
        event["rows"][0]["incomplete"] = True
        event["rows"][0]["metrics"]["DRB.UEThpUl"] = {"type": "no_value", "value": None}
        row = ingest(mapper, event)[0]
        self.assertIsNone(row["ue_ipv4"])
        self.assertIsNone(row["row"]["metrics"]["DRB.UEThpUl"]["value"])

    def test_ingress_loss_latches_until_verified_restart(self):
        mapper = ready()
        mapper.ingest({"kind": "ingress_loss"}, 11_000_000)
        ingest(mapper, cu_event())
        self.assertIsNone(ingest(mapper, du_event())[0]["ue_ipv4"])

    def test_invalid_identifiers_and_plmn(self):
        for value in (True, -1, "01", "", None, 1 << 40):
            with self.assertRaises(ValueError):
                integer(value, 40)
        self.assertEqual(integer(0, 40), "0")
        self.assertEqual(integer(1 << 39, 40), str(1 << 39))
        with self.assertRaises(ValueError):
            guami_key(dict(config()["amf"]["guami"], mnc="1"))

    def test_expiry_uses_monotonic_clock(self):
        mapper = ready()
        # Wall time advanced; monotonic age remains healthy.
        row = mapper.ingest(du_event(1, stamp=99_000_000), 99_100_000, 12_000_000)[0]
        self.assertEqual(row["ue_ipv4"], "10.45.0.10")

    def test_delayed_du_header_cannot_refresh_a_match(self):
        mapper = ready()
        event = du_event()
        event["received_at_us"] = 20_000_000
        self.assertEqual(ingest(mapper, event)[0]["binding_status"], "stale")

    def test_delayed_cu_header_cannot_refresh_identity(self):
        mapper = ready()
        event = cu_event()
        event["received_at_us"] = 14_000_000
        ingest(mapper, event)
        core = core_event()
        core["received_at_us"] = 14_100_000
        ingest(mapper, core)
        ingest(mapper, du_event(2, stamp=14_100_000))
        self.assertEqual(ingest(mapper, du_event(1, stamp=14_200_000))[0]["binding_status"], "stale")

    def test_encoded_queue_byte_and_item_limits(self):
        events = BoundedEvents(max_items=2, max_bytes=5)
        self.assertTrue(events.put(b"1234"))
        self.assertFalse(events.put(b"12"))
        self.assertTrue(events.put(b"1"))
        self.assertFalse(events.put(b""))
        self.assertEqual(events.get(0), b"1234")
        self.assertTrue(events.put(b"1234"))


class Response:
    status = 200
    def __init__(self, body):
        self.body = json.dumps(body).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self, limit):
        return self.body[:limit]


class Opener:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.urls = []
    def open(self, url, timeout):
        self.urls.append(url)
        return Response(next(self.pages))


class InfoAPITests(unittest.TestCase):
    def test_complete_paginated_snapshot(self):
        client = InfoAPI()
        client.opener = Opener([
            {"items": [{}] * 100, "pager": {"page": 0, "page_size": 100, "count": 101}},
            {"items": [{}], "pager": {"page": 1, "page_size": 100, "count": 101}}])
        self.assertEqual(len(client.fetch("http://127.0.0.5:9090/ue-info")), 101)
        self.assertIn("page=1", client.opener.urls[-1])

    def test_partial_or_changed_page_is_not_an_empty_snapshot(self):
        for second in ({"items": [], "pager": {"page": 1, "page_size": 100, "count": 101}},
                       {"items": [{}], "pager": {"page": 1, "page_size": 100, "count": 102}}):
            client = InfoAPI()
            client.opener = Opener([
                {"items": [{}] * 100, "pager": {"page": 0, "page_size": 100, "count": 101}}, second])
            with self.assertRaises(ValueError):
                client.fetch("http://127.0.0.5:9090/ue-info")

    def test_missing_pager_and_bad_session_rejected(self):
        client = InfoAPI()
        client.opener = Opener([{"items": []}])
        with self.assertRaises(ValueError):
            client.fetch("http://127.0.0.5:9090/ue-info")
        event = core_event()
        event["smf"][0]["pdu"][0]["psi"] = 0
        with self.assertRaises(ValueError):
            normalize(config(), event["amf"], event["smf"])

    def test_unknown_pdu_state_and_expired_poll_rejected(self):
        event = core_event()
        event["smf"][0]["pdu"][0]["pdu_state"] = "released"
        with self.assertRaises(ValueError):
            normalize(config(), event["amf"], event["smf"])
        client = InfoAPI()
        client.opener = Opener([])
        with self.assertRaises(ValueError):
            client.fetch("http://127.0.0.5:9090/ue-info", deadline=0)
        for amf, smf in (([None], []), ([], [None]), ([], [{"supi": "imsi-001010000000001", "pdu": [None]}])):
            with self.assertRaises(ValueError):
                normalize(config(), amf, smf)


if __name__ == "__main__":
    unittest.main()
