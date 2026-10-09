#!/usr/bin/env python3
"""Bind SOLR-21 same-occurrence witnesses to each immutable trial trace."""

import gzip
import hashlib
import json
from pathlib import Path
import sys


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main():
    campaign = Path(sys.argv[1]).resolve()
    prior = Path(sys.argv[2]).resolve()
    destination = Path(sys.argv[3]).resolve()
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    precision = json.loads(prior.read_text())
    if (result.get("case_id") != "SOLR-21" or result.get("status") != "budget_exhausted"
            or result.get("fault_trials_completed") != 80
            or not audit.get("report_gate_passed")
            or not audit.get("local_timeline_only")
            or audit.get("campaign_result_sha256") != sha256(result_path)
            or precision.get("campaign_result_sha256") != sha256(result_path)
            or precision.get("offline_causal_audit_sha256") != sha256(audit_path)):
        raise ValueError("terminal result, audit, and original precision receipt disagree")
    rows = []
    for item in precision["witnesses"]:
        trial_id = item["trial_id"]
        trial_root = campaign / "trials" / f"r{trial_id:04d}"
        trial_path = trial_root / "result.json"
        archive_path = trial_root / "events.jsonl.gz"
        trial = json.loads(trial_path.read_text())
        evidence = trial["events_evidence"]
        gzip_hash = sha256(archive_path)
        if (gzip_hash != evidence["gzip_sha256"]
                or archive_path.stat().st_size != evidence["gzip_bytes"]):
            raise ValueError(f"r{trial_id:04d}: gzip evidence mismatch")
        wanted = {w[k] for w in item["witnesses"]
                  for k in ("door_event_id", "fault_event_id", "target_check_event_id")}
        found = {}
        raw_hash = hashlib.sha256()
        raw_bytes = 0
        with gzip.open(archive_path, "rb") as stream:
            for line in stream:
                raw_hash.update(line)
                raw_bytes += len(line)
                event = json.loads(line)
                if event.get("id") in wanted:
                    if event["id"] in found:
                        raise ValueError(f"r{trial_id:04d}: duplicate witness event")
                    found[event["id"]] = event
        if (raw_hash.hexdigest() != evidence["raw_sha256"]
                or raw_bytes != evidence["raw_bytes"]
                or found.keys() != wanted):
            raise ValueError(f"r{trial_id:04d}: raw trace or witness mismatch")
        verified = []
        for witness in item["witnesses"]:
            door = found[witness["door_event_id"]]
            fault = found[witness["fault_event_id"]]
            check = found[witness["target_check_event_id"]]
            actor = (witness["node"], witness["epoch"], witness["occurrence"])
            if (door.get("type") != "DOOR_OBSERVED"
                    or fault.get("type") != "FAULT_APPLIED"
                    or check.get("type") != "TARGET_CHECK"
                    or not (door["seq"] < fault["seq"] < check["seq"])
                    or door["site"] != witness["door_site"]
                    or fault["site"] != door["site"]
                    or fault["fault_id"] != witness["fault_id"]
                    or check["site"] != witness["target_check_site"]
                    or any((event.get("node"), event.get("epoch"), event.get("occurrence")) != actor
                           for event in (door, fault, check))
                    or not (door.get("thread") == fault.get("thread") == check.get("thread"))):
                raise ValueError(f"r{trial_id:04d}: actor, site or order mismatch")
            verified.append({
                "node": actor[0], "epoch": actor[1], "occurrence": actor[2],
                "thread": fault["thread"],
                "door": {"id": door["id"], "seq": door["seq"], "site": door["site"]},
                "fault": {"id": fault["id"], "seq": fault["seq"], "site": fault["site"],
                          "fault_id": fault["fault_id"]},
                "target_check": {"id": check["id"], "seq": check["seq"],
                                 "site": check["site"]},
            })
        rows.append({
            "trial_id": trial_id,
            "trial_result_sha256": sha256(trial_path),
            "trace_gzip_sha256": gzip_hash,
            "trace_gzip_bytes": archive_path.stat().st_size,
            "trace_raw_sha256": raw_hash.hexdigest(),
            "trace_raw_bytes": raw_bytes,
            "witnesses": verified,
        })
    if len(rows) != precision["same_actor_same_occurrence_target_trials"]:
        raise ValueError("witness count mismatch")
    report = {
        "schema_version": 1, "case_id": "SOLR-21",
        "evidence_kind": "sha_bound_same_occurrence_local_timeline",
        "campaign_result_sha256": sha256(result_path),
        "offline_causal_audit_sha256": sha256(audit_path),
        "prior_precision_receipt_sha256": sha256(prior),
        "qualifying_trials": len(rows), "trials": rows,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"path": str(destination), "sha256": sha256(destination),
                      "qualifying_trials": len(rows)}, sort_keys=True))


if __name__ == "__main__":
    main()
