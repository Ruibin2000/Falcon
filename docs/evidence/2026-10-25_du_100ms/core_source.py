"""Bounded read-only Open5GS infoAPI adapter. No third-party dependencies."""

import ipaddress
import json
import re
import time
import urllib.parse
import urllib.request

MAX_BODY = 2 * 1024 * 1024
MAX_UES = 256


def integer(value, bits=64):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("identifier must be an integer or decimal string")
    if not re.fullmatch(r"0|[1-9][0-9]*", str(value)):
        raise ValueError("noncanonical identifier")
    number = int(value)
    if number >= 1 << bits:
        raise ValueError("identifier out of range")
    return str(number)


def supi(value):
    if not isinstance(value, str):
        raise ValueError("missing SUPI")
    value = value.removeprefix("imsi-")
    if not re.fullmatch(r"[0-9]{5,15}", value):
        raise ValueError("only IMSI-form SUPI is supported")
    return "imsi-" + value


def guami_key(value):
    mcc, mnc = value["mcc"], value["mnc"]
    if not re.fullmatch(r"[0-9]{3}", mcc) or not re.fullmatch(r"[0-9]{2,3}", mnc):
        raise ValueError("invalid PLMN; preserve MCC/MNC leading zeroes")
    return (mcc, mnc, integer(value["amf_region_id"], 8),
            integer(value["amf_set_id"], 10), integer(value["amf_pointer"], 6))


class InfoAPI:
    def __init__(self, timeout=0.5, max_pages=16):
        if not 0 < timeout <= 5 or not 1 <= max_pages <= 16:
            raise ValueError("invalid bounded HTTP timeout/page limit")
        self.timeout = timeout
        self.max_pages = max_pages
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def fetch(self, url, deadline=None):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
            raise ValueError("infoAPI requires an HTTP(S) endpoint without URL credentials")
        rows = []
        expected_count = None
        for page in range(self.max_pages):
            remaining = self.timeout if deadline is None else deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("poll cycle exceeded deadline")
            params = dict(urllib.parse.parse_qsl(parts.query))
            params.update(page=str(page), page_size="100")
            target = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(params)))
            with self.opener.open(target, timeout=min(self.timeout, remaining)) as response:
                if response.status != 200:
                    raise ValueError("infoAPI returned non-200 status")
                raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise ValueError("infoAPI body exceeds limit")
            if deadline is not None and time.monotonic() > deadline:
                raise ValueError("poll cycle exceeded deadline")
            body = json.loads(raw)
            if not isinstance(body, dict) or not isinstance(body.get("items"), list):
                raise ValueError("expected infoAPI object with items array")
            items = body["items"]
            if len(items) > 100:
                raise ValueError("unexpected page size")
            pager = body.get("pager")
            if not isinstance(pager, dict):
                raise ValueError("missing pager: cannot prove snapshot completeness")
            if int(integer(pager.get("page"))) != page or int(integer(pager.get("page_size"))) != 100:
                raise ValueError("unexpected pagination metadata")
            count = int(integer(pager.get("count")))
            if expected_count is not None and count != expected_count:
                raise ValueError("UE count changed during pagination")
            expected_count = count
            rows.extend(items)
            if len(rows) > MAX_UES or count > MAX_UES:
                raise ValueError("Core UE capacity exceeded")
            if len(rows) == count:
                return rows
            if not items or len(rows) > count:
                raise ValueError("incomplete/inconsistent paginated response")
        raise ValueError("infoAPI page limit exceeded")


def normalize(config, amf_items, smf_items):
    """Join complete poll results. Conflicts survive as multiple candidates."""
    if not isinstance(amf_items, list) or not isinstance(smf_items, list) or len(amf_items) > MAX_UES or len(smf_items) > MAX_UES:
        raise ValueError("Core UE capacity exceeded")
    sessions = {}
    for ue in smf_items:
        if not isinstance(ue, dict):
            raise ValueError("SMF item must be an object")
        owner = supi(ue.get("supi"))
        pdus = ue.get("pdu")
        if not isinstance(pdus, list) or len(pdus) > 8:
            raise ValueError("invalid/oversized PDU session list")
        for pdu in pdus:
            if not isinstance(pdu, dict):
                raise ValueError("PDU item must be an object")
            if pdu.get("pdu_state") not in ("active", "inactive"):
                raise ValueError("unknown/missing PDU session state")
            psi = int(integer(pdu.get("psi"), 8))
            if not 1 <= psi <= 15:
                raise ValueError("invalid PDU Session ID")
            if not isinstance(pdu.get("dnn"), str):
                raise ValueError("missing DNN")
            if config.get("dnns") and pdu["dnn"] not in config["dnns"]:
                continue
            if not pdu.get("ipv4"):
                continue
            ip = ipaddress.IPv4Address(pdu["ipv4"])
            if ip.is_multicast or ip.is_unspecified or int(ip) == 0xFFFFFFFF:
                raise ValueError("invalid unicast UE IPv4")
            candidate = {"supi": owner, "pdu_session_id": str(psi), "ue_ipv4": str(ip), "dnn": pdu["dnn"]}
            candidates = sessions.setdefault(owner, [])
            if candidate in candidates or any(c["pdu_session_id"] == str(psi) for c in candidates):
                raise ValueError("duplicate session in Core snapshot")
            candidates.append(candidate)
    result = {}
    guami = guami_key(config["amf"]["guami"])
    for ue in amf_items:
        if not isinstance(ue, dict):
            raise ValueError("AMF item must be an object")
        owner = supi(ue.get("supi"))
        if ue.get("cm_state") != "connected":
            continue
        gnb = ue.get("gnb")
        if not isinstance(gnb, dict):
            raise ValueError("connected UE missing NGAP context")
        key = (guami, integer(gnb.get("gnb_id"), 32), integer(gnb.get("amf_ue_ngap_id"), 40))
        # Actual AMF context metadata, never inferred from F1 IDs or used as ran-UEID.
        ran_id = integer(gnb.get("ran_ue_ngap_id"), 32)
        result.setdefault(key, []).extend(dict(candidate, ran_ue_ngap_id=ran_id)
                                          for candidate in sessions.get(owner, []))
    return result


def poll(config, publish, stop):
    client = InfoAPI(config.get("http_timeout_s", 0.5))
    period = config.get("poll_period_s", 1.0)
    max_cycle = config.get("max_poll_cycle_s", 2.0)
    if not 0.1 <= period <= 60 or not 0 < max_cycle <= 10:
        publish({"kind": "core_error", "reason": "invalid Core polling bounds"})
        return
    while not stop.is_set():
        started = time.monotonic()
        start_us = time.time_ns() // 1000
        try:
            deadline = started + max_cycle
            amf = client.fetch(config["amf"]["url"], deadline)
            amf_completed_us = time.time_ns() // 1000
            smf = client.fetch(config["smf_url"], deadline)
            if time.monotonic() > deadline:
                raise ValueError("poll cycle exceeded deadline")
            # Validate before publishing either half of the cross-NF view.
            normalize(config, amf, smf)
            publish({"kind": "core_snapshot", "amf": amf, "smf": smf,
                     "query_start_us": start_us, "amf_completed_us": amf_completed_us,
                     "received_at_us": time.time_ns() // 1000})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            publish({"kind": "core_error", "reason": str(exc), "received_at_us": time.time_ns() // 1000})
        stop.wait(max(0.0, period - (time.monotonic() - started)))
