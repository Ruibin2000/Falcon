"""Audit retained real live events and outputs; never starts Core, E2 or traffic."""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

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


def local(value):
    return datetime.fromisoformat(utc(value)).astimezone(ZoneInfo("America/New_York")).isoformat()


def laptop_result():
    transcript = (ROOT / "laptop_operator_transcript.txt").read_text()
    assert "sleep 150 &&" in transcript
    assert "UE2 sequence exit=0" in transcript and "UE1 exit=0" in transcript
    clients = []
    pattern = (r"\[\s*5\]\s+(\d+\.\d+)-(\d+\.\d+)\s+sec\s+"
               r"([\d.]+)\s+(\w+)\s+([\d.]+)\s+(\w+/sec)")
    for part in re.split(r"(?=\[\s*5\] local )", transcript)[1:]:
        connection = re.match(r"\[\s*5\] local (\S+) port (\d+) connected to (\S+) port (\d+)", part)
        intervals, summaries = [], {}
        for line in part.splitlines():
            match = re.search(pattern, line)
            if not match:
                continue
            start, end, transfer, unit, rate, rate_unit = match.groups()
            item = {"start_s": float(start), "end_s": float(end),
                    "transfer": float(transfer), "transfer_unit": unit,
                    "bitrate": float(rate), "bitrate_unit": rate_unit}
            if line.rstrip().endswith(("sender", "receiver")):
                summaries[line.split()[-1]] = item
            else:
                intervals.append(item)
        assert connection and "sender" in summaries and "receiver" in summaries
        assert all(a["end_s"] == b["start_s"] for a, b in zip(intervals, intervals[1:]))
        assert len(intervals) == int(summaries["sender"]["end_s"])
        clients.append({"source_ip": connection[1], "source_port": int(connection[2]),
                        "server_ip": connection[3], "server_port": int(connection[4]),
                        "intervals": len(intervals), "summaries": summaries,
                        "zero_bitrate_intervals_s": [[x["start_s"], x["end_s"]] for x in intervals if x["bitrate"] == 0]})
    assert [(x["source_ip"], x["server_port"], x["intervals"]) for x in clients] == [
        ("10.46.0.2", 5202, 20), ("10.46.0.2", 5202, 30), ("10.45.0.2", 5201, 300)]
    return {"ue1_exit": 0, "ue2_sequence_exit": 0, "quiet_command_seconds": 150,
            "clients": clients, "cross_host_clock_alignment": "unverified; transcript has no wall timestamps"}


def timeline(events, rows):
    changes, previous = [], {}
    cu_observations = {}
    for event in events:
        if event["kind"] == "core_snapshot":
            for amf in event["amf"]:
                supi = amf["supi"]
                smf = next(item for item in event["smf"] if item["supi"] == supi)
                state = {"cm_state": amf["cm_state"],
                         "amf_ue_ngap_id": amf["gnb"].get("amf_ue_ngap_id"),
                         "ran_ue_ngap_id": amf["gnb"].get("ran_ue_ngap_id"),
                         "sessions": [{key: pdu[key] for key in ("psi", "dnn", "ipv4", "pdu_state")} for pdu in smf["pdu"]]}
                if previous.get(supi) != state:
                    changes.append({"supi": supi, "received_at_us": event["received_at_us"],
                                    "time_edt": local(event["received_at_us"]), **state})
                    previous[supi] = state
        elif event["kind"] == "kpm_report" and event["node"]["node_type"] != "ngran_gNB_DU":
            for row in event["rows"]:
                ue = row["ue"]
                key = (ue["amf_ue_ngap_id"], tuple(ue["f1ap_ids"]))
                item = cu_observations.setdefault(key, {"amf_ue_ngap_id": key[0], "f1ap_ids": list(key[1]),
                    "first_received_at_us": event["received_at_us"], "last_received_at_us": None, "rows": 0})
                item["last_received_at_us"] = event["received_at_us"]
                item["rows"] += 1
    segments = {}
    for du in ("1", "2"):
        groups = []
        for row in (row for row in rows if row["node"]["du_id"] == du):
            key = (row["binding_status"], row["reason"], row["row"]["ue"]["gnb_cu_ue_f1ap_id"],
                   row.get("binding", {}).get("amf_ue_ngap_id"))
            if not groups or groups[-1][0] != key:
                groups.append([key, row, row, 1])
            else:
                groups[-1][2], groups[-1][3] = row, groups[-1][3] + 1
        segments[du] = [{"status": key[0], "reason": key[1], "f1ap_id": key[2], "amf_ue_ngap_id": key[3],
                         "rows": count, "first_sequence": first["sequence"], "last_sequence": last["sequence"],
                         "first_header_edt": local(first["header_time_us"]), "last_header_edt": local(last["header_time_us"])}
                        for key, first, last, count in groups]
    resumed = next(row for row in rows if row["node"]["du_id"] == "2" and
                   row.get("binding", {}).get("amf_ue_ngap_id") == "77")
    cu_start = cu_observations[("77", ("26",))]["first_received_at_us"]
    core_start = next(item["received_at_us"] for item in changes if item["amf_ue_ngap_id"] == 77)
    assert cu_start < int(resumed["header_time_us"]) and core_start < int(resumed["header_time_us"])
    assert all(row.get("binding", {}).get("amf_ue_ngap_id") != "76" for row in rows)
    return {"core_changes": changes, "cu_observations": list(cu_observations.values()), "du_segments": segments,
            "resumed_first_matched_sequence": resumed["sequence"],
            "resumed_first_matched_header_edt": local(resumed["header_time_us"]),
            "resumed_first_matched_emitted_edt": local(resumed["emitted_at_us"]),
            "resumed_emit_after_later_core_cu_observation_us": int(resumed["emitted_at_us"]) - max(cu_start, core_start),
            "boundary": "One ordinary idle/resume round; no same-F1 reuse, PDU reconnect or source restart exercised"}


def main():
    events = [json.loads(line) for line in (ROOT / "inputs.ndjson").read_text().splitlines()]
    rows = [json.loads(line) for line in (ROOT / "rows.ndjson").read_text().splitlines()]
    laptop = laptop_result()
    operator = json.loads((ROOT / "operator_run.json").read_text())
    assert operator["xapp_exit"] == 0 and operator["duration_seconds"] == 360
    assert operator["cli_override"] == "--observed-unique"
    # SIM-to-role assignment from the preceding operator-verified lab ledger.
    # The new transcript independently supplies the actual source IP and endpoint.
    roles = {"1": {"imsi": "001010000000101", "source": "10.45.0.2"},
             "2": {"imsi": "001010000000102", "source": "10.46.0.2"}}
    core, core_mono, core_error, loss = None, None, False, False
    cu, cu_first, du_seen, du_keys, identities = {}, {}, {}, {}, defaultdict(set)
    core_first, prior_core, history = {}, {}, defaultdict(set)
    checked = matched = 0
    ages = defaultdict(list)
    for event in events:
        kind = event["kind"]
        mono = event.get("received_at_mono_us", int(event["received_at_us"]))
        if kind == "core_snapshot":
            core, core_mono, core_error = event, mono, False
            current_core = {}
            for amf in core["amf"]:
                if amf["cm_state"] != "connected":
                    continue
                for smf in core["smf"]:
                    if smf["supi"] != amf["supi"]:
                        continue
                    for pdu in smf["pdu"]:
                        key = (str(amf["gnb"]["amf_ue_ngap_id"]), str(amf["gnb"]["ran_ue_ngap_id"]),
                               amf["supi"], str(pdu["psi"]), pdu["dnn"], pdu["ipv4"])
                        current_core[key] = prior_core.get(key, event["received_at_us"])
            core_first, prior_core = current_core, current_core
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
                            cu_first.setdefault((str(f1), identity), event["received_at_us"])
                            history[str(f1)].add(identity)
                        else:
                            candidates.pop(identity, None)
                continue
            du = str(node["du_id"])
            assert du in roles
            du_seen[du] = mono
            for source_row in event["rows"]:
                du_keys[(du, str(source_row["ue"]["gnb_cu_ue_f1ap_id"]))] = mono
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
                    if result["reason"] == "not all admitted DU sources are current":
                        assert any(mono - du_seen.get(key, -TTL) >= TTL for key in roles)
                    else:
                        assert result["reason"] == "CU identity missing"
                        assert str(source_row["ue"]["gnb_cu_ue_f1ap_id"]) not in cu
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
                assert len(history[str(f1)]) == 1
                assert {d for (d, key), seen in du_keys.items() if key == str(f1) and mono - seen < TTL} == {du}
                assert int(result["header_time_us"]) >= cu_first[(str(f1), expected_identity)]
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
                core_key = (binding["amf_ue_ngap_id"], binding["ran_ue_ngap_id"], binding["supi"],
                            binding["pdu_session_id"], binding["dnn"], result["ue_ipv4"])
                assert int(result["header_time_us"]) >= core_first[core_key]
                assert binding["dnn"] == ("internet" if du == "1" else "internet2")
                assert binding["assurance"] == "observed_unique_current_context"
                identities[du].add((str(f1), binding["amf_ue_ngap_id"], binding["ran_ue_ngap_id"], binding["supi"], result["ue_ipv4"]))
                ages["core_us"].append(mono - core_mono)
                ages["cu_us"].append(mono - candidates[expected_identity])
    assert checked == len(rows) == 637 and matched == 581
    assert len({row["app_instance"] for row in rows}) == 1
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
              "operator_xapp_exit": operator["xapp_exit"], "laptop": laptop, "timeline": timeline(events, rows),
              "du": stats, "max_source_age_us_on_match": {key: max(values) for key, values in ages.items()},
              "metric_payloads_preserved": checked, "matched_core_cu_du_cell_checks": matched,
              "registered_nodes": 3, "successful_subscriptions": 3, "deletion_responses": 3,
              "sdk_stopped_normally": "Sucessfully stopped" in log,
              "ingress_dropped_totals": sorted({int(event.get("ingress_dropped_total", 0)) for event in events if event["kind"] == "kpm_report"}),
              "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                         for name in ("inputs.ndjson", "rows.ndjson", "bindings.txt", "xapp.log", "local.json",
                                      "laptop_operator_transcript.txt", "operator_run.json", "audit.py")}}
    (ROOT / "audit.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
