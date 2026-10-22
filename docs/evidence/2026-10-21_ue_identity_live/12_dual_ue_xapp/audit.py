"""Audit retained real live events and outputs; never starts Core, E2 or traffic."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UNITS = {"DRB.RlcSduDelayDl": "0.1 ms", "DRB.UEThpDl": "kbit/s",
         "DRB.UEThpUl": "kbit/s", "RRU.PrbTotDl": "%", "RRU.PrbTotUl": "%"}
TTL = 3_000_000


def guami(value):
    return [value["mcc"], value["mnc"], str(value["amf_region_id"]),
            str(value["amf_set_id"]), str(value["amf_pointer"])]


def utc(value):
    seconds, fraction = divmod(int(value), 1_000_000)
    return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=fraction).isoformat()


def main():
    events = [json.loads(line) for line in (ROOT / "inputs.ndjson").read_text().splitlines()]
    rows = [json.loads(line) for line in (ROOT / "rows.ndjson").read_text().splitlines()]
    laptop = json.loads((ROOT / "laptop_operator_result.json").read_text())
    roles = {str(link["ue"]): link for link in laptop["links"]}
    core, core_mono, core_error, loss = None, None, False, False
    cu, du_seen, identities = {}, {}, defaultdict(set)
    checked = matched = 0
    ages = defaultdict(list)
    for event in events:
        kind = event["kind"]
        mono = event.get("received_at_mono_us", int(event["received_at_us"]))
        if kind == "core_snapshot":
            core, core_mono, core_error = event, mono, False
        elif kind == "core_error":
            core_error = True
        elif kind == "ingress_loss":
            loss = True
        elif kind == "kpm_report":
            loss |= int(event.get("ingress_dropped_total", 0)) != 0
            node = event["node"]
            if node["node_type"] != "ngran_gNB_DU":
                assert node["mcc"] == "001" and node["mnc"] == "01" and str(node["gnb_id"]) == "411"
                for source_row in event["rows"]:
                    ue = source_row["ue"]
                    identity = (tuple(guami(ue["guami"])), str(ue["amf_ue_ngap_id"]))
                    for f1 in ue["f1ap_ids"]:
                        candidates = cu.setdefault(str(f1), {})
                        if not source_row.get("incomplete") and source_row["metrics"]["FALCON.UE.RRCState"] == {"type": "integer", "value": 1}:
                            candidates[identity] = mono
                        else:
                            candidates.pop(identity, None)
                continue
            du = str(node["du_id"])
            assert du in roles
            du_seen[du] = mono
            for source_row in event["rows"]:
                if source_row["ue"]["id_type"] != "gnb_du":
                    continue
                result = rows[checked]
                checked += 1
                assert result["sequence"] == checked
                assert result["header_time_us"] == event["header_time_us"]
                assert result["callback_at_us"] == event["callback_at_us"]
                assert result["received_at_us"] == str(event["received_at_us"])
                for key, value in node.items():
                    assert result["node"][key] == value
                assert result["node"]["gnb_id_bits"] == 22
                copied = json.loads(json.dumps(result["row"]))
                assert set(copied["metrics"]) == set(UNITS)
                for name, metric in copied["metrics"].items():
                    assert metric.pop("unit") == UNITS[name]
                assert copied == source_row, f"DU payload changed at output {checked}"
                if result["binding_status"] != "matched":
                    assert result["ue_ipv4"] is None and "binding" not in result
                    continue
                matched += 1
                assert not core_error and not loss and not source_row.get("incomplete")
                assert core is not None and mono - core_mono < TTL
                assert all(0 <= mono - du_seen.get(key, -TTL) < TTL for key in roles)
                assert -1_000_000 <= int(event["received_at_us"]) - int(event["header_time_us"]) < TTL
                binding = result["binding"]
                role = roles[du]
                f1 = source_row["ue"]["gnb_cu_ue_f1ap_id"]
                candidates = {key: seen for key, seen in cu[str(f1)].items() if mono - seen < TTL}
                expected_identity = (tuple(binding["guami"]), binding["amf_ue_ngap_id"])
                assert set(candidates) == {expected_identity}, f"CU identity mismatch at output {checked}"
                amfs = [ue for ue in core["amf"] if ue["supi"] == binding["supi"] and ue["cm_state"] == "connected"]
                assert len(amfs) == 1
                amf = amfs[0]
                assert binding["supi"] == "imsi-" + role["imsi"]
                assert str(amf["gnb"]["amf_ue_ngap_id"]) == binding["amf_ue_ngap_id"]
                assert str(amf["gnb"]["ran_ue_ngap_id"]) == binding["ran_ue_ngap_id"]
                assert str(amf["gnb"]["gnb_id"]) == "411"
                # Independent lab-cell check from AMF's reported NCI, not an IP-subnet join.
                assert amf["location"]["nr_cgi"]["nci"] == 6733823 + int(du)
                sessions = [pdu for ue in core["smf"] if ue["supi"] == binding["supi"] for pdu in ue["pdu"]
                            if str(pdu["psi"]) == binding["pdu_session_id"] and pdu["dnn"] == binding["dnn"]]
                assert len(sessions) == 1
                assert result["ue_ipv4"] == sessions[0]["ipv4"] == role["source"]
                assert binding["dnn"] == ("internet" if du == "1" else "internet2")
                assert binding["assurance"] == "observed_unique_current_context"
                identities[du].add((str(f1), binding["amf_ue_ngap_id"], binding["ran_ue_ngap_id"], binding["supi"], result["ue_ipv4"]))
                ages["core_us"].append(mono - core_mono)
                ages["cu_us"].append(mono - candidates[expected_identity])
    assert checked == len(rows) == 223 and matched == 221
    text = (ROOT / "bindings.txt").read_text()
    blocks = [block for block in text.split("\n\n") if block.startswith("record=")]
    assert len(blocks) == len(rows)
    for block, row in zip(blocks, rows):
        assert block.startswith(f"record={row['sequence']} status={row['binding_status']} ")
        assert f"DU_ID={row['node']['du_id']} UE(gNB-CU UE F1AP ID)={row['row']['ue']['gnb_cu_ue_f1ap_id']}" in block
        if row["binding_status"] == "matched":
            assert f"UE_IPv4={row['ue_ipv4']}" in block
            assert f"AMF_UE_NGAP_ID={row['binding']['amf_ue_ngap_id']} RAN_UE_NGAP_ID={row['binding']['ran_ue_ngap_id']}" in block
        else:
            assert "UE_IPv4=unknown" in block and "SUPI=unknown" in block
        for name, metric in row["row"]["metrics"].items():
            line = next(line for line in block.splitlines() if line.startswith(f"    {name} = "))
            value = line.split(" = ", 1)[1].split(" [", 1)[0]
            assert (value == "no_value" if metric["type"] == "no_value" else json.loads(value) == metric["value"])
            assert line.endswith(f"[{metric['unit']}] ({metric['type']})")
    assert "input_mode=live" in text and "core_snapshot" not in text and "[xApp]" not in text
    stats = {}
    for du in roles:
        selected = [row for row in rows if str(row["node"]["du_id"]) == du]
        positive = [row for row in selected if (row["row"]["metrics"]["DRB.UEThpUl"]["value"] or 0) > 0]
        stats[du] = {"rows": len(selected), "statuses": dict(Counter(row["binding_status"] for row in selected)),
                     "identities_f1_amf_ran_supi_ip": sorted(identities[du]), "positive_ul_rows": len(positive),
                     "positive_matched_ul_rows": sum(row["binding_status"] == "matched" for row in positive),
                     "positive_ul_header_window_utc": [utc(positive[0]["header_time_us"]), utc(positive[-1]["header_time_us"])],
                     "positive_ul_row_mean_kbit_s": sum(row["row"]["metrics"]["DRB.UEThpUl"]["value"] for row in positive) / len(positive),
                     "ul_peak_kbit_s": max(row["row"]["metrics"]["DRB.UEThpUl"]["value"] or 0 for row in selected),
                     "ul_prb_peak_percent": max(row["row"]["metrics"]["RRU.PrbTotUl"]["value"] or 0 for row in selected)}
    log = (ROOT / "xapp.log").read_text()
    assert "Registered E2 Nodes = 3" in log and "3 KPM subscriptions" in log
    assert log.count("Successfully subscribed") == log.count("E42 SUBSCRIPTION DELETE RESPONSE rx") == 3
    output = {"audit": "passed", "app_instance": rows[0]["app_instance"],
              "header_window_utc": [utc(min(int(row["header_time_us"]) for row in rows)),
                                    utc(max(int(row["header_time_us"]) for row in rows))],
              "events": dict(Counter(event["kind"] for event in events)),
              "kpm_reports_by_node": dict(Counter(event["node"]["node_type"] + "/DU=" + str(event["node"].get("du_id"))
                                                   for event in events if event["kind"] == "kpm_report")),
              "rows": len(rows), "statuses": dict(Counter(row["binding_status"] for row in rows)),
              "unresolved": [{"sequence": row["sequence"], "du_id": row["node"]["du_id"], "reason": row["reason"]}
                             for row in rows if row["binding_status"] != "matched"],
              "du": stats, "max_source_age_us_on_match": {key: max(values) for key, values in ages.items()},
              "metric_payloads_preserved": checked, "matched_core_cu_du_cell_checks": matched,
              "registered_nodes": 3, "successful_subscriptions": 3, "deletion_responses": 3,
              "sdk_stopped_normally": "Sucessfully stopped" in log,
              "ingress_dropped_totals": sorted({int(event.get("ingress_dropped_total", 0)) for event in events if event["kind"] == "kpm_report"}),
              "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                         for name in ("inputs.ndjson", "rows.ndjson", "bindings.txt", "xapp.log", "local.json",
                                      "laptop_operator_result.json", "audit.py")}}
    (ROOT / "audit.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
