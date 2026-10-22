"""Independently audit captured live CU/DU/Core data; no services or replay."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TTL = 3_000_000
UNITS = {"DRB.RlcSduDelayDl": "0.1 ms", "DRB.UEThpDl": "kbit/s",
         "DRB.UEThpUl": "kbit/s", "RRU.PrbTotDl": "%", "RRU.PrbTotUl": "%"}
ROLES = {"1": ("imsi-001010000000101", "10.45.0.2", "internet", 6733824),
         "2": ("imsi-001010000000102", "10.46.0.2", "internet2", 6733825)}


def edt(us):
    whole, fraction = divmod(int(us), 1_000_000)
    return datetime.fromtimestamp(whole, timezone.utc).replace(microsecond=fraction).astimezone(
        ZoneInfo("America/New_York")).isoformat()


def guami(value):
    return tuple(str(value[name]) for name in ("mcc", "mnc", "amf_region_id", "amf_set_id", "amf_pointer"))


def core_signature(amf, pdu):
    return (str(amf["gnb"]["amf_ue_ngap_id"]), str(amf["gnb"]["ran_ue_ngap_id"]),
            amf["supi"], str(pdu["psi"]), pdu["dnn"], pdu["ipv4"])


def chain(row):
    binding = row["binding"]
    return {"f1ap_id": row["row"]["ue"]["gnb_cu_ue_f1ap_id"],
            **{key: binding[key] for key in ("supi", "amf_ue_ngap_id", "ran_ue_ngap_id", "dnn", "pdu_session_id")},
            "ue_ipv4": row["ue_ipv4"]}


def consecutive(rows):
    best = current = 0
    previous = None
    for row in rows:
        header = int(row["header_time_us"])
        current = current + 1 if previous is not None and 0 < header - previous < 1_500_000 else 1
        best, previous = max(best, current), header
    return best


def main():
    events = [json.loads(line) for line in (ROOT / "inputs.ndjson").read_text().splitlines()]
    rows = [json.loads(line) for line in (ROOT / "rows.ndjson").read_text().splitlines()]
    operator = json.loads((ROOT / "operator_run.json").read_text())
    config = json.loads((ROOT / "local.json").read_text())
    assert operator["xapp_exit"] == 0 and operator["duration_seconds"] == 360
    assert operator["cli_overrides"] == ["--observed-unique", "--fresh-only"]
    assert config["independent_links"] is True
    assert len({row["app_instance"] for row in rows}) == 1
    core, core_mono, core_since = None, None, {}
    cu, cu_since, cu_history, du_seen, du_keys, scopes = {}, {}, defaultdict(set), {}, {}, {}
    proofs, source_ages, independent = {}, [], []
    checked = 0
    for event in events:
        mono = event["received_at_mono_us"]
        kind = event["kind"]
        assert kind in ("core_snapshot", "kpm_report"), f"unexpected source error/loss: {kind}"
        if kind == "core_snapshot":
            core, core_mono = event, mono
            current, connected = {}, set()
            for amf in core["amf"]:
                if amf["cm_state"] != "connected":
                    continue
                connected.add((str(amf["gnb"]["amf_ue_ngap_id"]),
                               str(amf["gnb"]["ran_ue_ngap_id"]), amf["supi"]))
                smf = next(item for item in core["smf"] if item["supi"] == amf["supi"])
                for pdu in smf["pdu"]:
                    signature = core_signature(amf, pdu)
                    current[signature] = core_since.get(signature, event["received_at_us"])
            core_since = current
            scopes = {key: value for key, value in scopes.items()
                      if (value[0][1], value[2], value[1]) in connected}
            continue
        assert int(event["ingress_dropped_total"]) == 0
        node = event["node"]
        assert node["mcc"] == "001" and node["mnc"] == "01" and str(node["gnb_id"]) == "411"
        if node["node_type"] != "ngran_gNB_DU":
            assert node["node_type"] == "ngran_gNB"
            for row in event["rows"]:
                ue = row["ue"]
                identity = (guami(ue["guami"]), ue["amf_ue_ngap_id"])
                assert identity[0] == ("001", "01", "2", "1", "0")
                assert not row.get("incomplete")
                assert row["metrics"]["FALCON.UE.RRCState"] == {"type": "integer", "value": 1}
                for f1 in ue["f1ap_ids"]:
                    cu.setdefault(f1, {})[identity] = mono
                    cu_since.setdefault((f1, identity), event["received_at_us"])
                    cu_history[f1].add(identity)
            continue
        du = node["du_id"]
        assert du in ROLES
        du_seen[du] = mono
        for source in event["rows"]:
            du_keys[(du, source["ue"]["gnb_cu_ue_f1ap_id"])] = mono
        for source in event["rows"]:
            result = rows[checked]
            checked += 1
            assert result["sequence"] == checked
            for key in ("header_time_us", "callback_at_us"):
                assert result[key] == event[key]
            assert result["received_at_us"] == str(event["received_at_us"])
            assert all(result["node"][key] == value for key, value in node.items())
            assert result["node"]["gnb_id_bits"] == 22
            copied = json.loads(json.dumps(result["row"]))
            assert set(copied["metrics"]) == set(UNITS)
            for name, metric in copied["metrics"].items():
                assert metric.pop("unit") == UNITS[name]
            assert copied == source, f"DU payload changed: record {checked}"
            f1, header = source["ue"]["gnb_cu_ue_f1ap_id"], int(result["header_time_us"])
            all_current = all(0 <= mono - du_seen.get(key, -TTL) < TTL for key in ROLES)
            if result["binding_status"] != "matched":
                assert result["binding_status"] == "unresolved" and result["ue_ipv4"] is None and "binding" not in result
                if result["reason"] == "not all admitted DU sources are current":
                    assert not all_current
                else:
                    assert result["reason"] == "report predates independently observed identity relation"
                    candidates = list(cu[f1])
                    assert len(candidates) == 1 and header < cu_since[(f1, candidates[0])]
                continue
            binding = result["binding"]
            identity = (tuple(binding["guami"]), binding["amf_ue_ngap_id"])
            candidates = {key: seen for key, seen in cu[f1].items() if 0 <= mono - seen < TTL}
            assert set(candidates) == {identity} and len(cu_history[f1]) == 1
            assert {d for (d, key), seen in du_keys.items() if key == f1 and mono - seen < TTL} == {du}
            assert not source.get("incomplete") and -1_000_000 <= int(event["received_at_us"]) - header < TTL
            assert 0 <= mono - core_mono < TTL
            owner, ip, dnn, nci = ROLES[du]
            assert binding["supi"] == owner and result["ue_ipv4"] == ip and binding["dnn"] == dnn
            amf = next(item for item in core["amf"] if item["supi"] == owner)
            assert amf["cm_state"] == "connected" and str(amf["gnb"]["gnb_id"]) == "411"
            assert str(amf["gnb"]["amf_ue_ngap_id"]) == binding["amf_ue_ngap_id"]
            assert str(amf["gnb"]["ran_ue_ngap_id"]) == binding["ran_ue_ngap_id"]
            assert amf["location"]["nr_cgi"]["nci"] == nci
            sessions = next(item for item in core["smf"] if item["supi"] == owner)["pdu"]
            assert len(sessions) == 1 and sessions[0]["ipv4"] == ip and sessions[0]["dnn"] == dnn
            assert str(sessions[0]["psi"]) == binding["pdu_session_id"] == "1"
            first_core, first_cu = core_since[core_signature(amf, sessions[0])], cu_since[(f1, identity)]
            assert header >= max(first_core, first_cu)
            radio = (identity, owner, binding["ran_ue_ngap_id"])
            if all_current:
                assert binding["assurance"] == "observed_unique_current_context"
            else:
                assert scopes[(du, f1)] == radio
                assert binding["assurance"] == "established_du_scope_current_context"
                independent.append(checked)
            scopes[(du, f1)] = radio
            proofs[checked] = {"all_du_current": all_current, "core_first_us": first_core, "cu_first_us": first_cu}
            source_ages.append({"core_us": mono - core_mono, "cu_us": mono - candidates[identity]})
    assert checked == len(rows) == 648
    assert Counter(row["binding_status"] for row in rows) == {"matched": 645, "unresolved": 3}
    assert len(independent) == 59

    text = (ROOT / "bindings.txt").read_text()
    blocks = [part for part in text.split("\n\n") if part.startswith("record=")]
    assert len(blocks) == 648 and "input_mode=live" in text
    for block, row in zip(blocks, rows):
        assert block.startswith(f"record={row['sequence']} status={row['binding_status']} ")
        assert f"DU_ID={row['node']['du_id']} UE(gNB-CU UE F1AP ID)={row['row']['ue']['gnb_cu_ue_f1ap_id']}" in block
        if row["binding_status"] == "matched":
            assert f"UE_IPv4={row['ue_ipv4']}" in block
            assert f"SUPI={row['binding']['supi']} AMF_UE_NGAP_ID={row['binding']['amf_ue_ngap_id']} RAN_UE_NGAP_ID={row['binding']['ran_ue_ngap_id']}" in block
            assert f"assurance={row['binding']['assurance']}" in block
        else:
            assert "UE_IPv4=unknown" in block and "SUPI=unknown" in block
        for name, metric in row["row"]["metrics"].items():
            line = next(line for line in block.splitlines() if line.startswith(f"    {name} = "))
            value = line.split(" = ", 1)[1].split(" [", 1)[0]
            assert (value == "no_value" if metric["type"] == "no_value" else json.loads(value) == metric["value"])
            assert line.endswith(f"[{metric['unit']}] ({metric['type']})")

    episodes, transitions = [], []
    for du, (owner, ip, dnn, _) in ROLES.items():
        previous, opened = None, None
        for event in (event for event in events if event["kind"] == "core_snapshot"):
            amf = next(item for item in event["amf"] if item["supi"] == owner)
            smf = next(item for item in event["smf"] if item["supi"] == owner)
            signature = (amf["cm_state"], amf["gnb"].get("amf_ue_ngap_id"), amf["gnb"].get("ran_ue_ngap_id"))
            if signature != previous:
                transitions.append({"ue": du, "time_edt": edt(event["received_at_us"]), "state_amf_ran": signature})
            if previous is not None and previous[0] == "connected" and signature[0] == "idle":
                opened = {"ue": du, "start_us": event["received_at_us"]}
            if opened is not None:
                assert len(smf["pdu"]) == 1 and smf["pdu"][0]["ipv4"] == ip
                assert smf["pdu"][0]["dnn"] == dnn and smf["pdu"][0]["psi"] == 1
                if signature[0] == "connected":
                    opened["end_us"] = event["received_at_us"]
                    episodes.append(opened)
                    opened = None
                else:
                    assert smf["pdu"][0]["pdu_state"] == "inactive"
            previous = signature
        assert opened is None
    assert len(episodes) == 2
    for episode in episodes:
        du, start, end = episode["ue"], episode["start_us"], episode["end_us"]
        peer = "2" if du == "1" else "1"
        peers = [row for row in rows if row["node"]["du_id"] == peer and start <= int(row["received_at_us"]) < end]
        own_before = [row for row in rows if row["node"]["du_id"] == du and row["binding_status"] == "matched" and int(row["received_at_us"]) < start]
        own_after = [row for row in rows if row["node"]["du_id"] == du and row["binding_status"] == "matched" and int(row["received_at_us"]) >= end]
        assert (end - start) >= 10_000_000 and len(peers) == consecutive(peers) == 30
        assert all(row["binding_status"] == "matched" for row in peers)
        assert consecutive(own_before) >= 5 and consecutive(own_after) >= 5
        first = own_after[0]
        proof = proofs[first["sequence"]]
        latency = int(first["emitted_at_us"]) - max(proof["core_first_us"], proof["cu_first_us"])
        assert 0 <= latency <= 3_000_000
        episode.update(start_edt=edt(start), end_edt=edt(end), duration_s=(end-start)/1e6,
                       before=chain(own_before[-1]), after=chain(first),
                       peer_du=peer, peer_matched_rows=len(peers),
                       peer_rows_with_idle_du_stale=sum(not proofs[row["sequence"]]["all_du_current"] for row in peers),
                       peer_positive_ul_rows=sum(row["row"]["metrics"]["DRB.UEThpUl"]["value"] > 0 for row in peers),
                       resume_first_matched_sequence=first["sequence"], resume_first_matched_edt=edt(first["emitted_at_us"]),
                       resume_from_later_prerequisite_us=latency)

    log = (ROOT / "xapp.log").read_text()
    assert "Registered E2 Nodes = 3" in log and "3 KPM subscriptions, duration=360" in log
    assert log.count("Successfully subscribed") == log.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == 3
    assert "Sucessfully stopped" in log
    assert operator["laptop_status"] == "completed" and len(operator["jobs"]) == 4
    assert all(job["exit"] == 0 for job in operator["jobs"])
    truth_path = ROOT / "laptop_identity_result.json"
    laptop_truth = "pending current Laptop identity/IP output; prior verified role ledger used"
    if truth_path.exists():
        truth = json.loads(truth_path.read_text())
        assert truth["status"] == "completed" and len(truth["links"]) == 2
        for link in truth["links"]:
            owner, ip, dnn, _ = ROLES[str(link["ue"])]
            assert "imsi-" + link["imsi"] == owner and link["source"] == ip and link["apn"] == dnn
            assert link["imei"] == {1: "863305041978437", 2: "863305041980706"}[link["ue"]]
            assert link["prefix"] == 30
        laptop_truth = "passed: current Laptop preflight matches SUPI/IP/DNN"
    summary = {"audit": "passed", "data_origin": "operator-started live run; no replay",
               "app_instance": rows[0]["app_instance"], "xapp_exit": operator["xapp_exit"],
               "effective_options": {"du_scope_mode": "observed_unique", "binding_policy": "fresh_only", "independent_links": True},
               "capture_window_edt": [edt(events[0]["received_at_us"]), edt(events[-1]["received_at_us"])],
               "events": dict(Counter(event["kind"] for event in events)),
               "kpm_reports_by_node": dict(Counter(event["node"]["node_type"] + "/DU=" + str(event["node"]["du_id"])
                                                    for event in events if event["kind"] == "kpm_report")),
               "rows": 648, "statuses": dict(Counter(row["binding_status"] for row in rows)),
               "du_statuses": {du: dict(Counter(row["binding_status"] for row in rows if row["node"]["du_id"] == du)) for du in ROLES},
               "unresolved": [{"sequence": row["sequence"], "du": row["node"]["du_id"], "reason": row["reason"]} for row in rows if row["binding_status"] != "matched"],
               "metric_payloads_checked": checked, "current_core_cu_du_cell_matches_checked": len(proofs),
               "matched_with_other_du_stale": len(independent), "independent_sequences": independent,
               "max_source_age_us_on_match": {key: max(item[key] for item in source_ages) for key in ("core_us", "cu_us")},
               "core_transitions": transitions, "idle_resume": episodes,
               "laptop_identity_check": laptop_truth, "registered_nodes": 3, "successful_subscriptions": 3,
               "deletion_responses": 3, "sdk_stopped_normally": True, "ingress_dropped_totals": [0],
               "boundary": "One live round per UE; initial scope and strict DU/generation, exact reuse, restart and repeated/performance gates remain open",
               "sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in ROOT.iterdir()
                          if path.is_file() and path.name != "audit.json"}}
    (ROOT / "audit.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: summary[key] for key in ("audit", "rows", "statuses", "du_statuses", "matched_with_other_du_stale", "idle_resume", "laptop_identity_check")}, indent=2))


if __name__ == "__main__":
    main()
