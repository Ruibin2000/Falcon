"""Human-readable view of the same correlated DU samples emitted as NDJSON."""

from datetime import datetime, timezone
import json


def display(value):
    if value is None:
        return "unknown"
    if isinstance(value, str) and all(char.isprintable() for char in value):
        return value
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def utc_time(microseconds):
    if microseconds is None:
        return "unknown"
    try:
        seconds, fraction = divmod(int(microseconds), 1_000_000)
        return datetime.fromtimestamp(seconds, timezone.utc).replace(
            microsecond=fraction).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return f"{display(microseconds)} Unix us (outside UTC display range)"


def report_header(replay=None):
    mode = f"captured-input replay; source={display(str(replay))}" if replay else "live"
    return ("Falcon UE identity + KPM diagnostic report\n"
            f"input_mode={mode}\n"
            "UE ID below means gNB-CU UE F1AP ID; gNB identifies the CU/gNB scope.\n"
            "Matched records use current inputs; cached records carry a labelled last-verified binding.\n"
            "Unknown fields are not inferred; cached does not prove the binding is still current.\n"
            "KPM values and units are preserved; collection_time is the report header, not a per-sample time.\n\n")


def format_record(record):
    """Expose current or explicitly labelled historical bindings only."""
    node, row = record["node"], record["row"]
    bound = record.get("binding_status") in ("matched", "cached")
    binding = record.get("binding", {}) if bound else {}
    guami = binding.get("guami")
    amf_scope = (f"PLMN={display(guami[0])}/{display(guami[1])} "
                 f"region={display(guami[2])} set={display(guami[3])} pointer={display(guami[4])}"
                 if guami else "unknown")
    lines = [
        f"record={display(record.get('sequence'))} status={display(record.get('binding_status'))} "
        f"collection_time={utc_time(record.get('header_time_us'))}",
        f"  app_instance={display(record.get('app_instance'))} header_time_us={display(record.get('header_time_us'))}",
        f"  RAN: PLMN={display(node.get('mcc'))}/{display(node.get('mnc'))} "
        f"gNB={display(node.get('gnb_id'))} ({display(node.get('gnb_id_bits'))} bits) "
        f"DU_ID={display(node.get('du_id'))} "
        f"UE(gNB-CU UE F1AP ID)={display(row.get('ue', {}).get('gnb_cu_ue_f1ap_id'))}",
        f"  Core: SUPI={display(binding.get('supi'))} "
        f"AMF_UE_NGAP_ID={display(binding.get('amf_ue_ngap_id'))} "
        f"RAN_UE_NGAP_ID={display(binding.get('ran_ue_ngap_id'))}",
        f"  AMF(GUAMI): {amf_scope}",
        f"  Session: PDU_SESSION_ID={display(binding.get('pdu_session_id'))} "
        f"DNN={display(binding.get('dnn'))} UE_IPv4={display(record.get('ue_ipv4') if bound else None)}",
        f"  Mapping: method={display(binding.get('method'))} assurance={display(binding.get('assurance'))}",
        f"  Reason: {display(record.get('reason'))}",
        f"  KPM: sample_idx={display(row.get('sample_idx'))} "
        f"granularity_ms={display(row.get('granularity_ms'))} "
        f"incomplete={'absent' if row.get('incomplete') is None else display(row['incomplete'])}",
    ]
    if record.get("binding_status") == "cached":
        lines.insert(7, f"  History: last_verified={utc_time(binding.get('last_verified_at_us'))} "
                     f"age_ms={display(binding.get('age_ms'))} validity=last_known_unverified")
    if "serving_du_id" in binding:
        lines.insert(7, f"  CU scope: serving_DU_ID={display(binding['serving_du_id'])} "
                     f"CU_UE_index={display(binding.get('cu_ue_index'))}")
    for name, metric in row.get("metrics", {}).items():
        kind = metric.get("type")
        value = kind if kind == "no_value" else display(metric.get("value"))
        lines.append(f"    {display(name)} = {value} [{display(metric.get('unit'))}] ({display(kind)})")
    return "\n".join(lines) + "\n\n"
