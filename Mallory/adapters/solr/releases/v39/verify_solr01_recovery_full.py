#!/usr/bin/env python3
"""Check faulted ListAliases retries against the exact SOLR-01 guard."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

SITE = ("org.apache.solr.client.solrj.impl.BaseHttpClusterStateProvider"
        "#getAliases(Z)Ljava/util/Map;@247:door:1")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def checked_events(trial_dir: Path, result: dict) -> tuple[list[dict], dict]:
    evidence = result["events_evidence"]
    packed_path = trial_dir / evidence["gzip_path"]
    packed = packed_path.read_bytes()
    assert sha(packed) == evidence["gzip_sha256"]
    raw = gzip.decompress(packed)
    assert sha(raw) == evidence["raw_sha256"]
    assert len(raw) == evidence["raw_bytes"]
    return ([json.loads(line) for line in raw.splitlines() if line.strip()],
            {"gzip_sha256": sha(packed), "raw_sha256": sha(raw),
             "raw_bytes": len(raw)})


def witness(events: list[dict], fault: dict, checks: set[str]) -> list[dict]:
    if (fault.get("site") != SITE or fault.get("fault_type") != "EXCEPTION" or
            fault.get("exception_class") != "java.io.IOException" or
            fault.get("node") != "client" or
            not isinstance(fault.get("thread_id"), int)):
        return []
    door = next((event for event in reversed(events)
                 if event.get("type") == "DOOR_OBSERVED" and
                 event.get("site") == SITE and
                 event.get("door_ordinal") == fault.get("door_ordinal") and
                 event.get("node") == fault.get("node") and
                 event.get("epoch") == fault.get("epoch") and
                 event.get("thread_id") == fault.get("thread_id") and
                 event.get("occurrence") == fault.get("occurrence") and
                 event["seq"] < fault["seq"]), None)
    if door is None:
        return []
    exits = [event["seq"] for event in events
             if event.get("type") == "REGION_EXIT" and
             event.get("node") == fault.get("node") and
             event.get("epoch") == fault.get("epoch") and
             event.get("thread_id") == fault.get("thread_id") and
             event.get("occurrence") == fault.get("occurrence") and
             event["seq"] > fault["seq"]]
    limit = min(exits) if exits else float("inf")
    return [{"door_id": door["id"], "fault_id": fault["id"],
             "target_check_id": event["id"], "door_seq": door["seq"],
             "fault_seq": fault["seq"], "target_seq": event["seq"],
             "node": fault["node"], "epoch": fault["epoch"],
             "thread_id": fault["thread_id"], "occurrence": fault["occurrence"],
             "door_ordinal": fault["door_ordinal"]}
            for event in events if event.get("type") == "TARGET_CHECK" and
            event.get("site") in checks and
            event.get("node") == fault.get("node") and
            event.get("epoch") == fault.get("epoch") and
            event.get("thread_id") == fault.get("thread_id") and
            event.get("occurrence") == fault.get("occurrence") and
            fault["seq"] < event["seq"] < limit]


def inspect(root: Path, source: Path) -> dict:
    config_path, result_path = root / "config.json", root / "result.json"
    audit_path, sync_path = root / "offline-causal-audit.json", root / "sync-receipt.json"
    config, result = json.loads(config_path.read_text()), json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    assert config["case_id"] == result["case_id"] == "SOLR-01"
    assert result["status"] in {"budget_exhausted", "queue_exhausted"}
    assert config["budget"]["trials"] == 80
    assert config["budget"]["max_faults_per_trial"] == 3
    assert [row["site"] for row in config["validated_recovery_sites"]] == [SITE]
    assert file_sha(source) == config["mapping"]["target_source_sha256"]
    assert audit["campaign_result_sha256"] == file_sha(result_path)
    assert audit["archive_integrity_valid"] and audit["guidance_consistent"]
    assert json.loads(sync_path.read_text())["result_sha256"] == file_sha(result_path)
    rows = []
    checks = set(config["target"]["check_sites"])
    for trial_id in range(1, result["fault_trials_completed"] + 1):
        trial_dir = root / "trials" / f"r{trial_id:04d}"
        result_file = trial_dir / "result.json"
        trial = json.loads(result_file.read_text())
        events, event_hashes = checked_events(trial_dir, trial)
        plan = trial.get("plan", [])
        applied = [event for event in events if event.get("type") == "FAULT_APPLIED"]
        exact_faults = [event for event in applied if event.get("site") == SITE]
        exact_plan = [fault for fault in plan if fault["point"]["site"] == SITE]
        found = []
        for fault in exact_faults:
            matching = [item for item in exact_plan if item["fault_id"] == fault.get("fault_id")]
            if len(matching) != 1 or matching[0].get("exception_class") != "java.io.IOException":
                continue
            if fault.get("door_ordinal") != matching[0]["point"].get("door_ordinal"):
                continue
            found.extend(witness(events, fault, checks))
        rows.append({"trial_id": trial_id, "trial_result_sha256": file_sha(result_file),
                     **event_hashes, "plan_size": len(plan),
                     "all_faults_effective": trial["feedback"]["all_faults_effective"],
                     "target_reached": trial["feedback"]["target_reached"],
                     "target_threw": trial["feedback"]["target_threw"],
                     "target_exception_candidate": trial["feedback"]["target_exception_candidate"],
                     "junit_status": trial.get("junit_validation", {}).get("status"),
                     "exact_listaliases_applied": len(exact_faults),
                     "same_invocation_retry_witnesses": found})
    positives = [row["trial_id"] for row in rows
                 if row["all_faults_effective"] and row["same_invocation_retry_witnesses"]]
    return {"schema_version": 1, "case_id": "SOLR-01",
            "classification": ("terminal_recovery_precision_proven" if positives else
                               "terminal_recovery_precision_unproven"),
            "canonical_quality_claim": False, "new_bug_confirmed": False,
            "evidence_kind": "observed_local_timeline",
            "campaign_result_sha256": file_sha(result_path),
            "offline_audit_sha256": file_sha(audit_path),
            "offline_audit_gate": audit["report_gate_passed"],
            "sync_receipt_sha256": file_sha(sync_path),
            "config_sha256": file_sha(config_path),
            "source_snapshot_sha256": file_sha(source),
            "fault_trials_completed": len(rows),
            "strict_same_invocation_retry_trials": positives,
            "exact_target_exception_candidate_trials": [row["trial_id"] for row in rows
                                                        if row["target_exception_candidate"]],
            "trials": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    receipt = inspect(args.campaign, args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": receipt["classification"],
                      "positive_trials": receipt["strict_same_invocation_retry_trials"],
                      "exact_target_exception_candidate_trials":
                          receipt["exact_target_exception_candidate_trials"]}, sort_keys=True))


if __name__ == "__main__":
    main()
