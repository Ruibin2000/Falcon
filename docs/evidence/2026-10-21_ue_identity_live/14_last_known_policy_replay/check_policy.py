"""File-only regression on captured live input; this is NOT a new live test."""

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


def main():
    events = [json.loads(line) for line in (SOURCE / "inputs.ndjson").read_text().splitlines()]
    original = [json.loads(line) for line in (SOURCE / "rows.ndjson").read_text().splitlines()]
    config = json.loads((SOURCE / "local.json").read_text())
    config["du_scope_mode"] = "observed_unique"
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
            if policy == "fresh_only" or before["binding_status"] == "matched":
                for key in ("binding_status", "reason", "ue_ipv4", "binding"):
                    assert before.get(key) == after.get(key)
            elif after["binding_status"] == "cached":
                assert before["binding_status"] == "unresolved"
                assert before["reason"] == "not all admitted DU sources are current"
                assert after["node"]["du_id"] == "1" and after["ue_ipv4"] == "10.45.0.2"
                assert after["binding"]["amf_ue_ngap_id"] == "74"
                previous = next(row for row in reversed(original[:after["sequence"] - 1])
                                if row["node"] == after["node"] and row["binding_status"] == "matched")
                assert after["binding"]["last_verified_at_us"] == previous["received_at_us"]
                for key, value in previous["binding"].items():
                    if key != "assurance":
                        assert after["binding"][key] == value
                assert after["binding"]["assurance"] == "last_known_observed_context"
            else:
                assert before["binding_status"] == after["binding_status"]
                assert before["reason"] == after["reason"]
        policies[policy] = output
    cached = [row for row in policies["last_known"] if row["binding_status"] == "cached"]
    assert len(cached) == 29
    text = report_header(SOURCE / "inputs.ndjson") + "".join(map(format_record, policies["last_known"]))
    (HERE / "replayed_bindings.txt").write_text(text)
    output = {"validation": "passed", "kind": "captured-input policy regression; not live acceptance",
              "live_source": "13_ue2_idle_resume", "rows_each_policy": len(original),
              "policies": {key: dict(Counter(row["binding_status"] for row in rows)) for key, rows in policies.items()},
              "preserved_original_matched_rows": 581, "preserved_du_payloads_each_policy": 637,
              "cached_sequences": [row["sequence"] for row in cached],
              "example_cached_record": cached[0],
              "unknown_remaining": "26 startup rows without a verified history; 1 new-DU2-context row before CU identity",
              "services_started": False,
              "source_sha256": {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
                                for name in ("inputs.ndjson", "rows.ndjson", "local.json")},
              "implementation_sha256": {str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                                        for path in [REPO / "scripts/ue_identity/mapping.py",
                                                     REPO / "scripts/ue_identity/text_report.py",
                                                     REPO / "scripts/ue_identity/xapp_ue_identity.py"]}}
    (HERE / "comparison.json").write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps({key: output[key] for key in ("validation", "kind", "policies", "unknown_remaining")}))


if __name__ == "__main__":
    main()
