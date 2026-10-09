#!/usr/bin/env python3
"""Verify ZK12 full-trial evidence and exact postfault target continuation.

This is a case-level review. It does not replace the pinned core's offline
causal audit and does not classify an exception as a new bug by itself.
"""

import gzip
import hashlib
import json
from pathlib import Path


BASE = Path("/users/ZhenyuLi/baseline")
CAMPAIGN = BASE / "data/mallory/campaigns/ZOOKEEPER-12-fnf-v1"
REVIEW = BASE / "data/mallory/admissions/ZOOKEEPER-12-fa5f-filenotfound-v1-full-review.json"
DOOR = "org.apache.zookeeper.server.quorum.QuorumPeer#readLongFromFile(Ljava/lang/String;)J@2190:door:1"
CHECK = "org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V@1193:branch:3"
THROW = "org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V@1197:throw:1"
CONFIG_SHA = "7a559292dd1f3ddbf949417f1b633786046481fe098a7dad59d235fba933af55"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def events(directory: Path, trial: dict) -> tuple[list[dict], str]:
    evidence = trial["events_evidence"]
    path = directory / evidence["gzip_path"]
    assert path.name == evidence["gzip_path"]
    compressed_sha = sha(path)
    assert compressed_sha == evidence["gzip_sha256"]
    raw = gzip.decompress(path.read_bytes())
    assert hashlib.sha256(raw).hexdigest() == evidence["raw_sha256"]
    assert len(raw) == evidence["raw_bytes"]
    return [json.loads(line) for line in raw.splitlines()], compressed_sha


def same_actor_later(fault: dict, event: dict) -> bool:
    return (event["node"] == fault["node"]
            and event["epoch"] == fault["epoch"]
            and event["occurrence"] == fault["occurrence"]
            and event["thread_id"] == fault["thread_id"]
            and event["seq"] > fault["seq"]
            and event["ts"] > fault["ts"])


def main() -> None:
    config_path = CAMPAIGN / "config.json"
    result_path = CAMPAIGN / "result.json"
    audit_path = CAMPAIGN / "offline-causal-audit.json"
    config, result, audit = map(read, (config_path, result_path, audit_path))
    assert sha(config_path) == CONFIG_SHA
    assert result["status"] in {"budget_exhausted", "queue_exhausted"}
    assert audit["campaign_result_sha256"] == sha(result_path)
    assert audit["report_gate_passed"] is True
    assert config["target"]["check_sites"] == [CHECK]
    assert config["target"]["throw_site"] == THROW
    rows = []
    for trial_id in range(1, result["fault_trials_completed"] + 1):
        directory = CAMPAIGN / "trials" / f"r{trial_id:04d}"
        path = directory / "result.json"
        trial = read(path)
        assert trial["trial_id"] == trial_id
        trace, trace_sha = events(directory, trial)
        plan = trial["plan"]
        applied = [event for event in trace if event["type"] == "FAULT_APPLIED"]
        valid_chain = len(applied) == len(plan) and all(
            event["fault_id"] == intended["fault_id"]
            and event["site"] == DOOR
            and event["exception_class"] == "java.io.FileNotFoundException"
            and event["node"] == intended["point"]["node"]
            and event["epoch"] == intended["point"]["epoch"]
            and event["door_ordinal"] == intended["point"]["door_ordinal"]
            for event, intended in zip(applied, plan))
        if valid_chain:
            valid_chain = all(left["seq"] < right["seq"]
                              for left, right in zip(applied, applied[1:]))
        final_fault = applied[-1] if valid_chain and applied else None
        checks = ([event for event in trace
                   if event["type"] == "TARGET_CHECK" and event["site"] == CHECK
                   and same_actor_later(final_fault, event)]
                  if final_fault else [])
        throws = ([event for event in trace
                   if event["type"] == "TARGET_THROW" and event["site"] == THROW
                   and same_actor_later(final_fault, event)]
                  if final_fault else [])
        rows.append({
            "trial_id": trial_id,
            "trial_result_sha256": sha(path),
            "trace_gzip_sha256": trace_sha,
            "trace_raw_sha256": trial["events_evidence"]["raw_sha256"],
            "planned_faults": len(plan),
            "valid_applied_chain": valid_chain,
            "applied_fault_event_ids": [event["id"] for event in applied],
            "last_fault_event_id": final_fault["id"] if final_fault else None,
            "same_actor_same_occurrence_postfault_check_ids": [event["id"] for event in checks],
            "same_actor_same_occurrence_postfault_throw_ids": [event["id"] for event in throws],
            "junit_status": trial["junit_validation"]["status"],
            "core_feedback_status": trial["feedback"]["status"],
        })
    receipt = {
        "schema_version": 1,
        "case_id": "ZOOKEEPER-12",
        "status": "terminal_case_review_candidate_not_bug_classification",
        "campaign_result_sha256": sha(result_path),
        "offline_audit_sha256": sha(audit_path),
        "config_sha256": sha(config_path),
        "healthy_closure_evidence_types": audit.get("healthy_closure_evidence_types"),
        "fault_trials": len(rows),
        "strict_fault_chain_trials": sum(row["valid_applied_chain"] for row in rows),
        "same_actor_same_occurrence_postfault_check_trials": sum(
            bool(row["same_actor_same_occurrence_postfault_check_ids"]) for row in rows),
        "same_actor_same_occurrence_postfault_throw_trials": sum(
            bool(row["same_actor_same_occurrence_postfault_throw_ids"]) for row in rows),
        "trial_evidence": rows,
        "interpretation_limit": "The trace records readLine door ordinals, not filenames or numeric epoch operands; exact operand and bug review must use source and replay evidence.",
    }
    REVIEW.parent.mkdir(parents=True, exist_ok=True)
    REVIEW.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(REVIEW), "sha256": sha(REVIEW),
                      "fault_trials": len(rows), "postfault_check_trials":
                      receipt["same_actor_same_occurrence_postfault_check_trials"],
                      "postfault_throw_trials":
                      receipt["same_actor_same_occurrence_postfault_throw_trials"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
