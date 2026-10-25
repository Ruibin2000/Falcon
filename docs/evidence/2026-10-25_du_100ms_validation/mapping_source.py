"""Current-context association; no traffic heuristics or retrospective guessing."""

import copy
import json
import re
import uuid

from core import guami_key, integer, normalize, supi

UNITS = {"DRB.RlcSduDelayDl": "0.1 ms", "DRB.UEThpDl": "kbit/s",
         "DRB.UEThpUl": "kbit/s", "RRU.PrbTotDl": "%", "RRU.PrbTotUl": "%",
         "FALCON.UE.RRCState": "enum",
         "PUSCH.RSRP.dBFS": "dBFS", "PUSCH.SNR.dB": "dB"}


def node_key(node):
    # SDK's raw gNB padding is preserved separately; bit length comes from admitted configuration.
    return (node["mcc"], node["mnc"], integer(node["gnb_id"], 32), node["node_type"],
            None if node.get("du_id") is None else integer(node["du_id"], 36))


class Mapper:
    def __init__(self, config):
        self.config = config
        self.binding_policy = config.get("binding_policy", "fresh_only")
        if self.binding_policy not in ("fresh_only", "last_known"):
            raise ValueError("invalid binding policy")
        self.independent_links = config.get("independent_links", False)
        if type(self.independent_links) is not bool:
            raise ValueError("independent_links must be a boolean")
        self.app_instance = str(uuid.uuid4())
        self.sequence = 0
        self.ttl = int(config.get("source_ttl_s", 3) * 1_000_000)
        if not 0 < self.ttl <= 60_000_000 or config.get("du_scope_mode", "strict") not in ("strict", "observed_unique"):
            raise ValueError("invalid TTL/DU scope mode")
        for n in config["du_nodes"]:
            if not isinstance(n["gnb_id_bits"], int) or not 22 <= n["gnb_id_bits"] <= 32:
                raise ValueError("invalid configured gNB ID bit length")
            integer(n["gnb_id"], n["gnb_id_bits"])
        self.allowed = {node_key(n): n for n in config["du_nodes"]}
        if len(self.allowed) != len(config["du_nodes"]) or not self.allowed:
            raise ValueError("invalid/duplicate admitted DU nodes")
        self.cu = config["cu"]
        self.ran_ue_id_format = self.cu.get("ran_ue_id_format")
        if self.ran_ue_id_format not in (None, "du36-cuue28-v1"):
            raise ValueError("unsupported CU RAN UE identity allocation")
        self.core = {}
        self.core_seen = {}
        self.core_received = None
        self.core_error = "Core has not been queried"
        self.identities = {}
        self.history = {}
        self.tainted_keys = set()
        self.scoped_identities = {}
        self.scoped_history = {}
        self.scoped_tainted_keys = set()
        self.du_seen = {}
        self.du_keys = {}
        self.dropped = 0
        self.ingress_loss = False
        self.last_cu_header = None
        # Radio scope survives a session/IP update; historical IP reuse is a
        # separate policy. Both are keyed by the full admitted DU/F1 identity.
        self.radio_scopes = {}
        self.last_bindings = {}

    def retire_link(self, key):
        self.radio_scopes.pop(key, None)
        self.last_bindings.pop(key, None)

    def retire_f1(self, f1):
        for key in list(self.radio_scopes):
            if key[1] == f1 and key not in self.scoped_identities:
                self.retire_link(key)

    def ingest(self, event, now_us, monotonic_us=None):
        mono = now_us if monotonic_us is None else monotonic_us
        kind = event.get("kind")
        if kind == "core_error":
            self.core_error = event.get("reason", "Core query failed")
            return []
        if kind == "core_snapshot":
            updated = normalize(self.config, event["amf"], event["smf"])
            connected = {(guami_key(self.config["amf"]["guami"]), integer(ue["gnb"]["gnb_id"]),
                          integer(ue["gnb"]["amf_ue_ngap_id"], 40), integer(ue["gnb"]["ran_ue_ngap_id"], 32),
                          supi(ue["supi"]))
                         for ue in event["amf"] if ue.get("cm_state") == "connected"}
            for key, scope in list(self.radio_scopes.items()):
                identity = scope["identity"]
                if (identity[0], key[0][2], identity[1], scope["ran_ue_ngap_id"], scope["supi"]) not in connected:
                    self.retire_link(key)
            # A complete successful snapshot can disprove an old context. RRC
            # idle retires its F1 relation; SMF inactive alone does not release IP.
            for key, cached in list(self.last_bindings.items()):
                binding = cached["binding"]
                candidates = updated.get((tuple(binding["guami"]), key[0][2], binding["amf_ue_ngap_id"]), [])
                expected = {name: binding[name] for name in ("supi", "ran_ue_ngap_id", "pdu_session_id", "dnn")}
                expected["ue_ipv4"] = cached["ue_ipv4"]
                if candidates != [expected]:
                    del self.last_bindings[key]
            seen = {}
            for key, candidates in updated.items():
                signature = json.dumps(candidates, sort_keys=True)
                previous = self.core.get(key)
                seen[key] = self.core_seen.get(key, now_us) if previous == candidates else now_us
                # Changes cannot retrospectively relabel older DU samples.
                if previous is not None and json.dumps(previous, sort_keys=True) != signature:
                    seen[key] = now_us
            self.core, self.core_seen = updated, seen
            self.core_received, self.core_error = mono, None
            return []
        if kind == "ingress_loss":
            self.ingress_loss = True
            self.radio_scopes.clear()
            self.last_bindings.clear()
            return []
        if kind != "kpm_report":
            return []
        dropped = int(integer(event.get("ingress_dropped_total", 0)))
        if dropped != self.dropped:
            self.ingress_loss = True
            self.radio_scopes.clear()
            self.last_bindings.clear()
            self.dropped = dropped
        node = event["node"]
        key = node_key(node)
        rows = event.get("rows")
        if not isinstance(rows, list) or len(rows) > 4096:
            raise ValueError("invalid/oversized KPM row list")
        header = int(integer(event["header_time_us"]))
        if header > now_us + 1_000_000:
            raise ValueError("future KPM header: verify repaired timestamp plugin and clocks")
        if (node["mcc"], node["mnc"], integer(node["gnb_id"])) == (
                self.cu["mcc"], self.cu["mnc"], integer(self.cu["gnb_id"])) and node["node_type"] in self.cu["node_types"]:
            if self.ingress_loss:
                return []
            if now_us - header >= self.ttl:
                return []
            if self.last_cu_header is not None and header < self.last_cu_header:
                return []
            self.last_cu_header = header
            for row in rows:
                ue = row.get("ue", {})
                state = row.get("metrics", {}).get("FALCON.UE.RRCState", {})
                if ue.get("id_type") != "gnb":
                    continue
                identity = (guami_key(ue["guami"]), integer(ue["amf_ue_ngap_id"], 40))
                ids = ue.get("f1ap_ids", [])
                if not 1 <= len(ids) <= 4:
                    raise ValueError("invalid CU F1AP ID list")
                active_ids = {integer(f1, 32) for f1 in ids}
                connected = (not row.get("incomplete") and state.get("type") == "integer"
                             and type(state.get("value")) is int and state["value"] == 1)
                scope = self.cu_scope(ue)
                if scope is not None:
                    self.update_scoped_identity(scope, active_ids, identity, connected, now_us, mono)
                    continue
                # A current per-UE F1 list supersedes this identity's old
                # entries; retaining those until TTL could resurrect a scope.
                for previous_f1, candidates in self.identities.items():
                    if not connected or previous_f1 not in active_ids:
                        candidates.pop(identity, None)
                for scope_key, scope in list(self.radio_scopes.items()):
                    if scope["identity"] == identity and (not connected or scope_key[1] not in active_ids):
                        self.retire_link(scope_key)
                for f1 in ids:
                    f1 = integer(f1, 32)
                    if row.get("incomplete") or state.get("type") != "integer" or type(state.get("value")) is not int or state["value"] != 1:
                        # Explicit unavailable/non-connected state withdraws this
                        # candidate; absence of an ordinary filtered row does not.
                        self.identities.get(f1, {}).pop(identity, None)
                        continue
                    if f1 not in self.history and len(self.history) >= 256:
                        self.ingress_loss = True
                        continue
                    old = self.history.setdefault(f1, set())
                    if len(old) >= 4 and identity not in old:
                        self.ingress_loss = True
                        continue
                    old.add(identity)
                    if len(old) > 1:
                        self.tainted_keys.add(f1)
                        self.retire_f1(f1)
                    cached = self.identities.setdefault(f1, {})
                    valid_after = cached.get(identity, (now_us, now_us))[0]
                    cached[identity] = (valid_after, mono)
            if len(self.identities) > 256:
                self.ingress_loss = True
                self.identities.clear()
            return []
        if key not in self.allowed:
            raise ValueError("unconfigured E2 node")
        self.du_seen[key] = mono
        for row in rows:
            ue = row.get("ue", {})
            if ue.get("id_type") == "gnb_du":
                f1 = integer(ue["gnb_cu_ue_f1ap_id"], 32)
                self.du_keys[(key, f1)] = mono
        # These caches are bounded; history cannot be discarded and silently reused.
        if len(self.du_keys) > 256:
            self.ingress_loss = True
            self.du_keys.clear()
        for row in rows:
            ue = row.get("ue", {})
            if ue.get("id_type") != "gnb_du":
                continue
            f1 = integer(ue["gnb_cu_ue_f1ap_id"], 32)
            sources = {source for (source, value), seen in self.du_keys.items()
                       if value == f1 and mono - seen < self.ttl}
            if len(sources) > 1:
                self.tainted_keys.add(f1)
                self.retire_f1(f1)
        output = []
        for row in rows:
            if row.get("ue", {}).get("id_type") != "gnb_du":
                continue
            self.sequence += 1
            result = {"schema": "falcon.ue_identity.experimental.v1", "app_instance": self.app_instance,
                      "sequence": self.sequence, "node": copy.deepcopy(node), "row": copy.deepcopy(row),
                      "header_time_us": str(header), "received_at_us": str(now_us),
                      "callback_at_us": event.get("callback_at_us"),
                      "binding_status": "unresolved", "reason": "CU identity missing", "ue_ipv4": None}
            result["node"]["gnb_id_bits"] = self.allowed[key]["gnb_id_bits"]
            for name, metric in result["row"].get("metrics", {}).items():
                metric["unit"] = UNITS.get(name)
            result.update(self.resolve(key, row, header, now_us, mono))
            result.update(self.remember_or_reuse(key, row, header, now_us, mono, result))
            output.append(result)
        return output

    def remember_or_reuse(self, node, row, header, now, mono, result):
        if self.config.get("du_scope_mode", "strict") != "observed_unique":
            return {}
        key = (node, integer(row["ue"]["gnb_cu_ue_f1ap_id"], 32))
        if result["binding_status"] == "matched":
            binding = result["binding"]
            self.radio_scopes[key] = {"identity": (tuple(binding["guami"]), binding["amf_ue_ngap_id"]),
                                      "ran_ue_ngap_id": binding["ran_ue_ngap_id"], "supi": binding["supi"]}
            self.last_bindings[key] = {"binding": copy.deepcopy(result["binding"]),
                                       "ue_ipv4": result["ue_ipv4"],
                                       "last_verified_at_us": now, "verified_mono": mono,
                                       "first_header_us": header}
            return {}
        if self.binding_policy != "last_known":
            return {}
        cached = self.last_bindings.get(key)
        # Missing updates may reuse history. Contradictions, loss and samples
        # older than the established context must never become cached matches.
        allowed_reason = (result["reason"] in (
            "not all admitted DU sources are current", "CU identity stale", "Core snapshot stale",
            "incomplete DU measurement") or bool(self.core_error))
        if (cached is None or not allowed_reason or self.ingress_loss or
                result["binding_status"] == "ambiguous" or
                (key in self.scoped_tainted_keys if key in self.scoped_identities else key[1] in self.tainted_keys) or
                now - header >= self.ttl or header < cached["first_header_us"]):
            return {}
        binding = copy.deepcopy(cached["binding"])
        binding.update(assurance="last_known_observed_context",
                       last_verified_assurance=cached["binding"]["assurance"],
                       last_verified_at_us=str(cached["last_verified_at_us"]),
                       age_ms=max(0, mono - cached["verified_mono"]) / 1000)
        return {"binding_status": "cached", "reason": "using last verified binding: " + result["reason"],
                "ue_ipv4": cached["ue_ipv4"], "binding": binding}

    def resolve(self, node, row, header, now, mono):
        def failure(reason, status="unresolved"):
            return {"binding_status": status, "reason": reason, "ue_ipv4": None}
        f1 = integer(row["ue"]["gnb_cu_ue_f1ap_id"], 32)
        if self.ingress_loss:
            return failure("ingress loss/capacity exceeded; restart with a verified source boundary")
        if row.get("incomplete"):
            return failure("incomplete DU measurement")
        if now - header >= self.ttl:
            return failure("DU report header is stale", "stale")
        scoped_key = (node, f1)
        if scoped_key in self.scoped_identities:
            return self.resolve_scoped(scoped_key, header, now, mono)
        if f1 in self.tainted_keys:
            return failure("F1AP ID conflict/reuse; DU context generation cannot be proved", "ambiguous")
        all_du_current = all(mono - self.du_seen.get(key, -self.ttl) < self.ttl for key in self.allowed)
        established = self.radio_scopes.get((node, f1)) if self.independent_links else None
        if not all_du_current and established is None:
            return failure("not all admitted DU sources are current")
        active_du = {key for (key, value), seen in self.du_keys.items() if value == f1 and mono - seen < self.ttl}
        if len(active_du) != 1:
            return failure("same F1AP ID observed on multiple DUs", "ambiguous")
        candidates = [(identity, times) for identity, times in self.identities.get(f1, {}).items()
                      if mono - times[1] < self.ttl]
        if not candidates:
            return failure("CU identity stale" if f1 in self.identities else "CU identity missing",
                           "stale" if f1 in self.identities else "unresolved")
        if len(candidates) != 1:
            return failure("multiple CU identities for F1AP ID", "ambiguous")
        identity, (cu_start, _) = candidates[0]
        core_key = (identity[0], node[2], identity[1])
        if self.core_error or self.core_received is None or mono - self.core_received >= self.ttl:
            return failure(self.core_error or "Core snapshot stale", "stale")
        sessions = self.core.get(core_key, [])
        if len(sessions) != 1:
            return failure("multiple eligible Core sessions" if sessions else "no matching Core session",
                           "ambiguous" if sessions else "unresolved")
        if header < max(cu_start, self.core_seen[core_key]):
            return failure("report predates independently observed identity relation")
        # Standard UEID lacks an explicit DU ID. This mode is deliberately experimental.
        if self.config.get("du_scope_mode", "strict") != "observed_unique":
            return failure("standard CU UEID does not prove explicit serving-DU scope")
        assurance = "observed_unique_current_context"
        reason = "unique among current admitted observations"
        if not all_du_current:
            # Recompute from this UE's fresh CU and Core inputs; only its
            # previously established DU scope is retained. This is distinct
            # from a historical IP fallback, which never reaches this branch.
            current = sessions[0]
            same_context = (established["identity"] == identity and
                            established["supi"] == current["supi"] and
                            established["ran_ue_ngap_id"] == current["ran_ue_ngap_id"])
            if not same_context:
                return failure("established DU association does not match current UE context")
            assurance = "established_du_scope_current_context"
            reason = "current UE CU/Core relation matches its established DU/F1 association"
        return {"binding_status": "matched", "reason": reason,
                "ue_ipv4": sessions[0]["ue_ipv4"],
                "binding": {"method": "core_infoapi_cu_e2", "assurance": assurance,
                            "amf_ue_ngap_id": identity[1], "guami": list(identity[0]),
                            "supi": sessions[0]["supi"], "ran_ue_ngap_id": sessions[0]["ran_ue_ngap_id"],
                            "pdu_session_id": sessions[0]["pdu_session_id"], "dnn": sessions[0]["dnn"]}}

    def cu_scope(self, ue):
        """Interpret only the explicitly admitted CU's local RAN UE allocation.

        Standard RAN UE IDs are opaque. No prefix guessing, role/subnet mapping
        or interpretation of a third-party CU's arbitrary RAN UE ID is allowed.
        The low 28 bits are a CU index, not a lifecycle generation proof.
        """
        if self.ran_ue_id_format is None or "ran_ue_id_hex" not in ue:
            return None
        raw = ue["ran_ue_id_hex"]
        if not isinstance(raw, str) or re.fullmatch(r"[0-9a-fA-F]{16}", raw) is None:
            raise ValueError("invalid CU RAN UE identity octets")
        value = int(raw, 16)
        du = str(value >> 28)
        nodes = [node for node in self.allowed if node[4] == du]
        if len(nodes) != 1:
            raise ValueError("CU RAN UE identity refers to an unconfigured DU")
        return nodes[0], str(value & ((1 << 28) - 1))

    def update_scoped_identity(self, scope, active_ids, identity, connected, now, mono):
        node, context = scope
        # Current per-UE CU state supersedes its previous DU/F1 relation. An
        # absent filtered row alone does not prove a release, as in legacy mode.
        for key, candidates in self.scoped_identities.items():
            if not connected or key[0] != node or key[1] not in active_ids:
                if identity in candidates:
                    del candidates[identity]
                    self.retire_link(key)
        for f1 in active_ids:
            key = (node, f1)
            if key not in self.scoped_identities and len(self.scoped_identities) >= 256:
                self.ingress_loss = True
                return
            candidates = self.scoped_identities.setdefault(key, {})
            if not connected:
                candidates.pop(identity, None)
                self.retire_link(key)
                continue
            history = self.scoped_history.setdefault(key, set())
            # Cross-DU equality is allowed. Genuine reuse of the SAME scoped
            # F1 key remains quarantined: a CU index is not a shared DU/CU
            # generation token and must not justify relabelling delayed data.
            if (identity, context) not in history and history:
                self.scoped_tainted_keys.add(key)
                self.retire_link(key)
            if len(history) >= 4 and (identity, context) not in history:
                self.ingress_loss = True
                return
            history.add((identity, context))
            valid_after = candidates.get(identity, (now, mono, context))[0]
            candidates[identity] = (valid_after, mono, context)

    def resolve_scoped(self, key, header, now, mono):
        def failure(reason, status="unresolved"):
            return {"binding_status": status, "reason": reason, "ue_ipv4": None}
        if key in self.scoped_tainted_keys:
            return failure("scoped F1AP ID reused; shared DU/CU context generation cannot be proved", "ambiguous")
        all_candidates = self.scoped_identities[key]
        candidates = [(identity, times) for identity, times in all_candidates.items()
                      if mono - times[1] < self.ttl]
        if not candidates:
            return failure("CU identity stale" if all_candidates else "CU identity withdrawn",
                           "stale" if all_candidates else "unresolved")
        if len(candidates) != 1:
            return failure("multiple CU identities for scoped DU/F1AP ID", "ambiguous")
        identity, (cu_start, _, context) = candidates[0]
        core_key = (identity[0], key[0][2], identity[1])
        if self.core_error or self.core_received is None or mono - self.core_received >= self.ttl:
            return failure(self.core_error or "Core snapshot stale", "stale")
        sessions = self.core.get(core_key, [])
        if len(sessions) != 1:
            return failure("multiple eligible Core sessions" if sessions else "no matching Core session",
                           "ambiguous" if sessions else "unresolved")
        if header < max(cu_start, self.core_seen[core_key]):
            return failure("report predates independently observed identity relation")
        current = sessions[0]
        return {"binding_status": "matched", "reason": "serving DU explicitly identified by admitted CU RAN UE allocation",
                "ue_ipv4": current["ue_ipv4"],
                "binding": {"method": "core_infoapi_cu_e2", "assurance": "cu_reported_du_scope",
                            "serving_du_id": key[0][4], "cu_ue_index": context,
                            "amf_ue_ngap_id": identity[1], "guami": list(identity[0]),
                            "supi": current["supi"], "ran_ue_ngap_id": current["ran_ue_ngap_id"],
                            "pdu_session_id": current["pdu_session_id"], "dnn": current["dnn"]}}
