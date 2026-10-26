"""Adapter from the existing mapper output to owned application pushes."""
from mapping import node_key
from subscription_protocol import link_key, mono_us


class BoundReportFeed:
    def __init__(self, mapper, publisher, evidence=None):
        self.mapper = mapper
        self.publisher = publisher
        self.evidence = evidence
        self.latest = {}
        self.wall = None
        self.monotonic = None

    def clock(self):
        now = mono_us()
        return (self.wall + now - self.monotonic if self.wall is not None else 0), now

    def validity(self, record, now, mono):
        mapper = self.mapper
        key = (node_key(record["node"]), record["row"]["ue"]["gnb_cu_ue_f1ap_id"])
        context = mapper.scoped_identities.get(key, mapper.identities.get(key[1], {}))
        identity = (tuple(record["binding"]["guami"]), record["binding"]["amf_ue_ngap_id"])
        seen = context[identity][1]
        return min(mapper.core_received + mapper.ttl, seen + mapper.ttl,
                   mono + mapper.ttl - (now - int(record["header_time_us"])))

    def ingest(self, event):
        received = int(event["received_at_us"])
        arrival = int(event["received_at_mono_us"])
        self.wall, self.monotonic = received, arrival
        records = self.mapper.ingest(event, received, arrival)
        for record in records:
            key = link_key(record["node"], record["row"]["ue"])
            if key not in self.latest and len(self.latest) >= 256:
                self.publisher.source_unavailable("mapper publication context capacity exceeded")
                continue
            self.latest[key] = record
            now, ready = self.clock()
            state = self.mapper.resolve(node_key(record["node"]), record["row"],
                                        int(record["header_time_us"]), now, ready)
            if state["binding_status"] != "matched":
                self.publisher.binding_state(key, "binding_invalid", state["reason"])
                continue
            # Never upgrade a previously unresolved/cached sample after the fact.
            if record["binding_status"] != "matched":
                self.publisher.binding_state(key, "waiting_for_match", record["reason"])
                continue
            record["emitted_at_us"] = str(__import__("time").time_ns() // 1000)
            record["source_instance_id"] = event.get("source_instance_id")
            record["source_indication_seq"] = event.get("source_indication_seq")
            record["ingress_dropped_total"] = event.get("ingress_dropped_total", "0")
            callback = event.get("callback_at_mono_us")
            if callback is None:
                self.publisher.binding_state(key, "source_unavailable", "collector lacks callback monotonic metadata; rebuild collector")
                continue
            until = self.validity(record, now, ready)
            invalid_before = self.publisher.stats().get("invalid_reports", 0)
            admitted = self.publisher.submit(record, callback_mono_us=int(callback), ready_mono_us=ready,
                                             valid_until_mono_us=until)
            if self.evidence:
                self.evidence.offer(record, int(callback), ready, until, admitted)
            if not admitted:
                if self.publisher.stats().get("invalid_reports", 0) > invalid_before:
                    self.publisher.binding_state(key, "binding_invalid", "invalid full 27-metric report")
        self.refresh()
        return records

    def refresh(self):
        if self.wall is None:
            return
        now, mono = self.clock()
        for key, record in self.latest.items():
            result = self.mapper.resolve(node_key(record["node"]), record["row"],
                                         int(record["header_time_us"]), now, mono)
            if result["binding_status"] != "matched":
                state = "source_unavailable" if "stale" in result["reason"] or self.mapper.core_error else "binding_invalid"
                self.publisher.binding_state(key, state, result["reason"])
