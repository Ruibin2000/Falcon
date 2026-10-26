"""Version-2 bound-report protocol shared by service and independent client."""
import json
import math
import re

from core import integer
from metrics import EXPANDED, UNITS

VERSION = 2
PROFILE = "du27_bound_v1"
MAX_REQUEST = 8192
MAX_FRAME = 65536
IDENTIFIER = re.compile(r"[A-Za-z0-9_.-]{1,64}", re.ASCII)


def mono_us():
    import time
    return time.clock_gettime_ns(time.CLOCK_MONOTONIC) // 1000


def decode(line):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    value = json.loads(line, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if type(value) is not dict:
        raise ValueError("expected JSON object")
    return value


def encode(value):
    result = (json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode()
    if len(result) > MAX_FRAME:
        raise ValueError("frame_too_large")
    return result


def identifier(value):
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def link_key(node, ue):
    if not isinstance(node, dict) or not isinstance(ue, dict):
        raise ValueError("invalid identity")
    if (not isinstance(node.get("mcc"), str) or re.fullmatch(r"[0-9]{3}", node["mcc"]) is None
            or not isinstance(node.get("mnc"), str) or re.fullmatch(r"[0-9]{2,3}", node["mnc"]) is None
            or node.get("node_type") != "ngran_gNB_DU" or ue.get("id_type") != "gnb_du"
            or type(node.get("gnb_id_bits")) is not int or not 22 <= node["gnb_id_bits"] <= 32):
        raise ValueError("invalid DU identity")
    # Wire identity fields must be strings, not booleans, lossy floats or padded IDs.
    for obj, name, bits in ((node, "gnb_id", node["gnb_id_bits"]), (node, "du_id", 36),
                            (ue, "gnb_cu_ue_f1ap_id", 32)):
        if not isinstance(obj.get(name), str):
            raise ValueError("identity must be a decimal string")
        integer(obj[name], bits)
    return (node["mcc"], node["mnc"], node["node_type"], node["gnb_id"],
            node["gnb_id_bits"], node["du_id"], ue["id_type"], ue["gnb_cu_ue_f1ap_id"])


def link_id(key):
    return ":".join(map(str, key))


def parse_filter(value):
    if type(value) is not dict:
        raise ValueError("invalid_request")
    if value == {"mode": "all_matched_links"}:
        return None
    if set(value) != {"mode", "links"} or value["mode"] != "links" or type(value["links"]) is not list or not 1 <= len(value["links"]) <= 32:
        raise ValueError("invalid_request")
    keys = []
    for item in value["links"]:
        if type(item) is not dict or set(item) != {"node", "ue"} or set(item["node"]) != {
                "mcc", "mnc", "node_type", "gnb_id", "gnb_id_bits", "du_id"} or set(item["ue"]) != {
                "id_type", "gnb_cu_ue_f1ap_id"}:
            raise ValueError("invalid_request")
        keys.append(link_key(item["node"], item["ue"]))
    if len(set(keys)) != len(keys):
        raise ValueError("invalid_request")
    return frozenset(keys)


def validate_report(record):
    key = link_key(record["node"], record["row"]["ue"])
    incomplete = record["row"].get("incomplete")
    if record.get("binding_status") != "matched" or (incomplete is not None and incomplete is not False):
        raise ValueError("report is not currently matched")
    import ipaddress
    ipaddress.IPv4Address(record["ue_ipv4"])
    binding = record["binding"]
    for name in ("method", "assurance", "supi", "dnn"):
        if not isinstance(binding.get(name), str) or not binding[name] or len(binding[name]) > 128:
            raise ValueError("missing binding metadata")
    from core import supi
    supi(binding["supi"])
    for name, bits in (("amf_ue_ngap_id", 40), ("ran_ue_ngap_id", 32), ("pdu_session_id", 8)):
        integer(binding[name], bits)
    if "serving_du_id" in binding and binding["serving_du_id"] != key[5]:
        raise ValueError("inconsistent serving DU")
    if len(binding["guami"]) != 5:
        raise ValueError("missing GUAMI")
    from core import guami_key
    guami_key(dict(zip(("mcc", "mnc", "amf_region_id", "amf_set_id", "amf_pointer"), binding["guami"])))
    if type(record["row"].get("sample_idx")) is not int or record["row"]["sample_idx"] < 0:
        raise ValueError("invalid sample index")
    if record["row"].get("granularity_ms") != 100:
        raise ValueError("expected 100 ms DU granularity")
    metrics = record["row"]["metrics"]
    if set(metrics) != set(EXPANDED):
        raise ValueError("expected exactly 27 raw KPM names")
    for name in EXPANDED:
        metric = metrics[name]
        if metric.get("unit") != UNITS[name]:
            raise ValueError("invalid metric unit")
        kind, number = metric.get("type"), metric.get("value")
        if kind == "integer":
            if type(number) is not int or not 0 <= number < (1 << 32):
                raise ValueError("invalid KPM INTEGER")
        elif kind == "real":
            if type(number) not in (int, float) or not math.isfinite(number):
                raise ValueError("invalid KPM REAL")
        elif kind != "no_value" or number is not None:
            raise ValueError("invalid metric type/absence")
    return key
