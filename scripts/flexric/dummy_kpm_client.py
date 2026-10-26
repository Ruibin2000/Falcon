#!/usr/bin/env python3
"""Independent standard-library client for the base5 local KPM interface."""
import argparse
import json
import math
import re
import select
import socket
import sys
import time

NAMES = ("DRB.RlcSduDelayDl", "DRB.UEThpDl", "DRB.UEThpUl", "RRU.PrbTotDl", "RRU.PrbTotUl")
UNITS = ("0.1 ms", "kbit/s", "kbit/s", "%", "%")
UINT = re.compile(r"0|[1-9][0-9]*", re.ASCII)


def uint(value, maximum=2**64-1):
    if not isinstance(value, str) or UINT.fullmatch(value) is None or int(value) > maximum:
        raise ValueError(f"Invalid unsigned decimal string: {value!r}")
    return int(value)


def validate_key(row):
    node, ue = row["node"], row["ue"]
    if (not isinstance(node["mcc"], str) or re.fullmatch(r"[0-9]{3}", node["mcc"]) is None
            or not isinstance(node["mnc"], str) or re.fullmatch(r"[0-9]{2,3}", node["mnc"]) is None
            or node["node_type"] != "ngran_gNB_DU" or ue["id_type"] != "gnb_du"
            or type(node["gnb_id_bits"]) is not int or not 22 <= node["gnb_id_bits"] <= 32):
        raise ValueError("Invalid complete DU/UE identity")
    uint(node["gnb_id"], 2**node["gnb_id_bits"]-1)
    uint(node["du_id"], 2**36-1)
    uint(ue["gnb_cu_ue_f1ap_id"], 2**32-1)
    if ue.get("ran_ue_id") is not None:
        uint(ue["ran_ue_id"])


def validate_row(row, registration, previous_delivery):
    if (row["version"] != 1 or row["type"] != "kpm" or row["metric_profile"] != "base5"
            or row["broker_instance_id"] != registration["broker_instance_id"]
            or row["subscription_id"] != registration["subscription_id"]
            or row["data_source"] != registration["data_source"]):
        raise ValueError("Changed protocol, instance, subscription, source, or profile")
    seq = uint(row["delivery_seq"])
    if seq != previous_delivery + 1:
        raise ValueError("Nonconsecutive delivery sequence")
    if uint(row["report_seq"]) <= uint(registration["registration_cutoff_report_seq"]):
        raise ValueError("Pre-registration callback leaked through cutoff")
    for field in ("header_time_us", "received_at_unix_us", "published_at_unix_us", "ingress_dropped_total"):
        uint(row[field])
    if type(row["sample_idx"]) is not int or row["sample_idx"] < 0:
        raise ValueError("Invalid sample index")
    if row["incomplete"] is not None and type(row["incomplete"]) is not bool:
        raise ValueError("Invalid incomplete flag")
    validate_key(row)
    if set(row["metrics"]) != set(NAMES):
        raise ValueError("Expected exactly the five baseline metrics")
    for name, unit in zip(NAMES, UNITS):
        m = row["metrics"][name]
        if m["unit"] != unit:
            raise ValueError(f"Wrong unit for {name}")
        kind, status, value = m["kpm_type"], m["status"], m["value"]
        if status == "ok":
            if kind == "integer":
                if type(value) is not int or not 0 <= value <= 2**32-1:
                    raise ValueError("Invalid KPM INTEGER")
            elif kind == "real":
                if type(value) not in (float, int) or not math.isfinite(value):
                    raise ValueError("Invalid KPM REAL")
            else:
                raise ValueError("Unsupported valid KPM type")
        elif value is not None or (kind, status) not in {
                ("absent", "not_reported"), ("noValue", "no_value"),
                ("real", "invalid"), ("integer", "invalid"), ("unsupported", "invalid")}:
            raise ValueError("Invalid metric absence state")
        if status == "invalid" and not m.get("reason"):
            raise ValueError("Invalid metric needs a reason")
    return seq


class Connection:
    def __init__(self, host, port):
        self.socket = socket.create_connection((host, port), timeout=5)
        self.socket.setblocking(False)
        self.buffer = bytearray()

    def send(self, obj):
        data = memoryview((json.dumps(obj, separators=(",", ":"), allow_nan=False) + "\n").encode())
        deadline = time.monotonic() + 2
        while data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.socket], [], remaining)[1]:
                raise TimeoutError("Request write timeout")
            try:
                n = self.socket.send(data)
            except BlockingIOError:
                continue
            if not n:
                raise EOFError("Connection closed while sending request")
            data = data[n:]

    def receive(self, timeout):
        deadline = time.monotonic() + max(0, timeout)
        while True:
            pos = self.buffer.find(b"\n")
            if pos >= 0:
                if pos + 1 > 16384:
                    raise ValueError("Oversized server frame")
                line = bytes(self.buffer[:pos])
                del self.buffer[:pos+1]
                return json.loads(line, parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
            if len(self.buffer) >= 16384:
                raise ValueError("Oversized server frame")
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.socket], [], [], remaining)[0]:
                raise TimeoutError("Response timeout")
            try:
                data = self.socket.recv(16384)
            except BlockingIOError:
                continue
            if not data:
                raise EOFError("Unexpected server EOF")
            self.buffer.extend(data)

    def close(self):
        self.socket.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--app-id", required=True)
    filters = parser.add_mutually_exclusive_group(required=True)
    filters.add_argument("--all-links", action="store_true")
    filters.add_argument("--links-file")
    parser.add_argument("--reports", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--expected-profile", choices=["base5"], default="base5")
    parser.add_argument("--jsonl-output")
    args = parser.parse_args()
    if args.reports < 1 or args.timeout <= 0:
        parser.error("reports and timeout must be positive")
    output = None
    connection = None
    registration = None
    interrupted = False
    try:
        if args.jsonl_output:
            output = open(args.jsonl_output, "x", encoding="utf-8")
        if args.all_links:
            filter_spec = {"mode": "all_du_ues"}
        else:
            with open(args.links_file, encoding="utf-8") as f:
                links = json.load(f)
            filter_spec = {"mode": "links", "links": links}
        connection = Connection(args.host, args.port)

        def receive(timeout):
            obj = connection.receive(timeout)
            if output:
                output.write(json.dumps(obj, separators=(",", ":"), allow_nan=False) + "\n")
                output.flush()
            return obj

        connection.send({"version": 1, "type": "register", "request_id": "reg-1", "app_id": args.app_id, "filter": filter_spec})
        registration = receive(5)
        if (registration.get("version") != 1 or registration.get("type") != "registration_status"
                or registration.get("status") != "registered" or registration.get("request_id") != "reg-1"
                or registration.get("app_id") != args.app_id or registration.get("metric_profile") != args.expected_profile
                or registration.get("metric_names") != list(NAMES) or registration.get("data_source") not in ("e2", "fixture")
                or not registration.get("broker_instance_id") or not registration.get("subscription_id")):
            raise ValueError(f"Registration rejected or inconsistent: {registration}")
        deadline = time.monotonic() + args.timeout
        ping_at = time.monotonic() + 10
        pending_ping = None
        received = delivery = 0
        try:
            while received < args.reports:
                now = time.monotonic()
                if now >= deadline:
                    raise TimeoutError("Timed out waiting for requested reports")
                if now >= ping_at:
                    if pending_ping:
                        raise TimeoutError("Missing pong")
                    pending_ping = f"ping-{received}"
                    connection.send({"version": 1, "type": "ping", "request_id": pending_ping})
                    ping_at = now + 10
                try:
                    row = receive(min(deadline, ping_at) - time.monotonic())
                except TimeoutError:
                    continue
                if row.get("type") == "pong":
                    if row.get("request_id") != pending_ping or row.get("broker_instance_id") != registration["broker_instance_id"]:
                        raise ValueError("Unexpected pong")
                    pending_ping = None
                    continue
                delivery = validate_row(row, registration, delivery)
                received += 1
                node, ue = row["node"], row["ue"]
                values = "; ".join(f"{name}={m['value']!r} {m['unit']} ({m['status']})" for name, m in row["metrics"].items())
                print(f"PLMN={node['mcc']}-{node['mnc']} node={node['node_type']} gNB={node['gnb_id']}/{node['gnb_id_bits']} "
                      f"DU={node['du_id']} UE={ue['gnb_cu_ue_f1ap_id']} header_us={row['header_time_us']} {values}", flush=True)
        except KeyboardInterrupt:
            interrupted = True
        connection.send({"version": 1, "type": "unregister", "request_id": "unreg-1", "subscription_id": registration["subscription_id"]})
        drain = time.monotonic() + 2
        while True:
            reply = receive(drain - time.monotonic())
            if reply.get("type") == "kpm":
                delivery = validate_row(reply, registration, delivery)
                continue
            if reply.get("type") == "pong" and reply.get("request_id") == pending_ping:
                continue
            if (reply.get("version") == 1 and reply.get("type") == "unregistration_status"
                    and reply.get("status") == "unregistered" and reply.get("request_id") == "unreg-1"
                    and reply.get("subscription_id") == registration["subscription_id"]
                    and reply.get("broker_instance_id") == registration["broker_instance_id"]):
                break
            raise ValueError(f"Unexpected unregister response: {reply}")
        try:
            connection.receive(2)
        except EOFError:
            pass
        else:
            raise ValueError("Frame received after unregister acknowledgment")
        return 130 if interrupted else 0
    except (OSError, ValueError, KeyError, TypeError, TimeoutError, EOFError) as exc:
        print(f"dummy failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if connection:
            connection.close()
        if output:
            output.close()


if __name__ == "__main__":
    sys.exit(main())
