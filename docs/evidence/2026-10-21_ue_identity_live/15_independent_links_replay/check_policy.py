"""Check independent UE matching on retained real inputs; never starts services."""

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SOURCE = HERE.parent / "13_ue2_idle_resume"
sys.path.insert(0, str(REPO / "scripts/ue_identity"))
from mapping import Mapper
from text_report import format_record, report_header


def verify_new_matches(events, original, output):
    """Check raw current sources and a prior accepted radio scope independently."""
    core, core_mono, cu, du_seen, previously_matched = None, None, {}, {}, {}
    index, checked, ages = 0, [], []
    for event in events:
        mono = event["received_at_mono_us"]
        if event["kind"] == "core_snapshot":
            core, core_mono = event, mono
            continue
        assert event["kind"] == "kpm_report" and int(event["ingress_dropped_total"]) == 0
        if event["node"]["node_type"] != "ngran_gNB_DU":
            for row in event["rows"]:
                for f1 in row["ue"]["f1ap_ids"]:
                    key = (f1, row["ue"]["amf_ue_ngap_id"])
                    if row["metrics"]["FALCON.UE.RRCState"] == {"type": "integer", "value": 1}:
                        cu[key] = (mono, row)
                    else:
                        cu.pop(key, None)
            continue
        du = event["node"]["du_id"]
        du_seen[du] = mono
        for source_row in event["rows"]:
            before, after = original[index], output[index]
            index += 1
            key = (du, source_row["ue"]["gnb_cu_ue_f1ap_id"])
            if before["binding_status"] == "matched":
                previously_matched[key] = before
            if before["binding_status"] == after["binding_status"]:
                continue
            assert before["reason"] == "not all admitted DU sources are current"
            assert after["binding_status"] == "matched" and "last_verified_at_us" not in after["binding"]
            assert du == "1" and key[1] == "50" and after["ue_ipv4"] == "10.45.0.2"
            assert mono - du_seen["2"] >= 3_000_000
            prior = previously_matched[key]
            assert int(prior["header_time_us"]) < int(after["header_time_us"])
            for field, value in prior["binding"].items():
                if field != "assurance":
                    assert after["binding"][field] == value
            binding = after["binding"]
            assert binding["assurance"] == "established_du_scope_current_context"
            amf = next(ue for ue in core["amf"] if ue["supi"] == binding["supi"])
            assert amf["cm_state"] == "connected"
            assert str(amf["gnb"]["amf_ue_ngap_id"]) == binding["amf_ue_ngap_id"] == "74"
            assert str(amf["gnb"]["ran_ue_ngap_id"]) == binding["ran_ue_ngap_id"] == "73"
            assert amf["location"]["nr_cgi"]["nci"] == 6733824
            session = next(ue for ue in core["smf"] if ue["supi"] == binding["supi"])["pdu"]
            assert len(session) == 1 and session[0]["ipv4"] == after["ue_ipv4"]
            assert str(session[0]["psi"]) == binding["pdu_session_id"] and session[0]["dnn"] == binding["dnn"]
            cu_mono, cu_row = cu[(key[1], binding["amf_ue_ngap_id"])]
            assert cu_row["ue"]["f1ap_ids"] == [key[1]]
            guami = cu_row["ue"]["guami"]
            assert [guami["mcc"], guami["mnc"], str(guami["amf_region_id"]),
                    str(guami["amf_set_id"]), str(guami["amf_pointer"])] == binding["guami"]
            assert 0 <= mono - cu_mono < 3_000_000 and 0 <= mono - core_mono < 3_000_000
            ages.append({"cu_us": mono - cu_mono, "core_us": mono - core_mono})
            checked.append(after["sequence"])
    assert index == len(output) and len(checked) == 29
    return checked, {key: max(item[key] for item in ages) for key in ("cu_us", "core_us")}


def main():
    events = [json.loads(line) for line in (SOURCE / "inputs.ndjson").read_text().splitlines()]
    original = [json.loads(line) for line in (SOURCE / "rows.ndjson").read_text().splitlines()]
    config = json.loads((SOURCE / "local.json").read_text())
    config.update(du_scope_mode="observed_unique", independent_links=True)
    policies = {}
    for policy in ("fresh_only", "last_known"):
        settings = copy.deepcopy(config)
        settings["binding_policy"] = policy
        mapper, output = Mapper(settings), []
        for event in events:
            output.extend(mapper.ingest(event, int(event["received_at_us"]), event["received_at_mono_us"]))
        assert len(output) == len(original) == 637
        for before, after in zip(original, output):
            for key in ("node", "row", "sequence", "header_time_us", "received_at_us", "callback_at_us"):
                assert before[key] == after[key]
            if before["binding_status"] == "matched":
                assert before["binding"] == after["binding"] and before["ue_ipv4"] == after["ue_ipv4"]
            elif after["binding_status"] != "matched":
                assert before["binding_status"] == after["binding_status"] and before["reason"] == after["reason"]
        checked, ages = verify_new_matches(events, original, output)
        assert dict(Counter(row["binding_status"] for row in output)) == {"unresolved": 27, "matched": 610}
        policies[policy] = output
    text = report_header(SOURCE / "inputs.ndjson") + "".join(map(format_record, policies["last_known"]))
    (HERE / "replayed_bindings.txt").write_text(text)
    summary = {"validation": "passed", "kind": "captured-input regression, not new live acceptance",
               "live_source": "13_ue2_idle_resume", "independent_links": True, "rows_each_policy": 637,
               "policies": {key: dict(Counter(row["binding_status"] for row in rows)) for key, rows in policies.items()},
               "original_matched_bindings_unchanged": 581, "metric_payloads_preserved_each_policy": 637,
               "newly_matched_sequences": checked, "newly_matched_current_source_age_max_us": ages,
               "example_current_record": policies["last_known"][checked[0] - 1],
               "unknown_remaining": "26 startup rows without established DU scope; 1 new UE2 row before CU identity",
               "scope_limit": "Retained established DU scope; explicit per-UE DU/generation E2 transport remains absent",
               "services_started": False,
               "source_sha256": {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
                                 for name in ("inputs.ndjson", "rows.ndjson", "local.json")},
               "implementation_sha256": {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                                         for path in [REPO / "scripts/ue_identity/mapping.py", Path(__file__).resolve()]}}
    (HERE / "comparison.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: summary[key] for key in ("validation", "kind", "policies", "newly_matched_current_source_age_max_us")}))


if __name__ == "__main__":
    main()
