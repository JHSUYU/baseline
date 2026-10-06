#!/usr/bin/env python3
"""Checkpointed, graph-independent fuzzing of the original expired-key JUnit.

The healthy test deliberately makes one stale-key lookup fail, then retries.
Only target exceptions beyond that expected one become selected-check candidates.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parent.parent
spec = importlib.util.spec_from_file_location("hdfs11_base_campaign", HERE.parent / "campaign.py")
assert spec and spec.loader
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

base.HERE = HERE
base.CASE = CASE
base.STATE = HERE / "campaign-state.json"
base.LOCK = HERE / "campaign.lock"
base.RESULT = CASE / "expiry-result.json"
base.LEDGER = CASE / "expiry-trial-ledger.csv"
base.RUNNER = HERE / "run_expiry.py"
base.HEALTHY = HERE / "healthy-01"
base.SMOKE = HERE / "smoke-heartbeat-03"

healthy_trace = base.rows(base.HEALTHY)
EXPECTED_STALE_KEY_THROWS = sum(event["event"] == "TARGET_THROW"
                                and event.get("siteId") == base.THROW
                                for event in healthy_trace)
if EXPECTED_STALE_KEY_THROWS != 1:
    raise RuntimeError("expired-key JUnit must have exactly one expected target throw")

original_evaluate = base.evaluate


def evaluate(directory: Path, sequence: list[dict], state: dict) -> dict:
    trial = original_evaluate(directory, sequence, state)
    trace = base.rows(directory)
    throws = [event for event in trace if event["event"] == "TARGET_THROW"
              and event.get("siteId") == base.THROW]
    trial["total_target_exceptions"] = len(throws)
    trial["healthy_expected_exceptions"] = EXPECTED_STALE_KEY_THROWS
    unexpected = max(0, len(throws) - EXPECTED_STALE_KEY_THROWS)
    trial["target_exception_after_fault"] = unexpected if trial["valid_for_feedback"] else 0
    trial["bug_mark"] = ("candidate_needs_replay_source_review"
                         if trial["target_exception_after_fault"] else "none")
    trial["expected_stale_key_exception_seen"] = bool(throws)
    return trial


def eligible(event: dict) -> bool:
    # A checked smoke showed an IOException at the already received key-update
    # command kills the command processor and removes the selected check.
    return (event["event"] == "FAULT_POINT_OBSERVED"
            and event.get("marker") != "FAULT:HDFS_KEY_UPDATE:RPC")


def initial_queue(state: dict) -> None:
    trace = base.rows(base.HEALTHY)
    last_target = max(event["seq"] for event in trace
                      if event["event"] == "TARGET_CHECK"
                      and event.get("siteId") == base.TARGET)
    for event in trace:
        if eligible(event) and event["seq"] < last_target:
            for kind in base.KINDS:
                base.enqueue(state, [base.point(event, kind)])


def extend(state: dict, trial: dict) -> None:
    sequence = trial["sequence"]
    if not trial["valid_for_feedback"] or len(sequence) >= state["budget"]["max_faults"]:
        return
    trace = base.rows(Path(trial["run"]))
    later = [event["seq"] for event in trace
             if event["event"] == "TARGET_CHECK"
             and event.get("siteId") == base.TARGET
             and event["seq"] > trial["last_applied_seq"]]
    if not later:
        return
    for event in trace:
        if eligible(event) and trial["last_applied_seq"] < event["seq"] < max(later):
            for kind in base.KINDS:
                selected = base.point(event, kind)
                if selected in sequence:
                    continue
                priority = (10 * trial["coverage_gain"]["methods"]
                            + 5 * trial["coverage_gain"]["branch_counts"]
                            + 50 * bool(trial["new_io_families"])
                            + 3 * len(sequence))
                base.enqueue(state, sequence + [selected], priority)


def write_result(state: dict) -> None:
    completed = state["completed"]
    valid = [trial for trial in completed if trial["valid_for_feedback"]]
    candidates = [trial for trial in valid if trial["target_exception_after_fault"]]
    result = {
        "case_id": "HDFS-11",
        "system": "HDFS 3.4.3",
        "source_file": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java",
        "function": "retrieveDataEncryptionKey(int, byte[])",
        "check_code": "key = allKeys.get(keyId); if (key == null) throw new InvalidEncryptionKeyException(...) then client retry",
        "cluster_test": "org.apache.hadoop.hdfs.TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey[0]",
        "methodology": "coverage_io_case_local_asm_jacoco_original_junit_expected_key_expiry",
        "graphchecker_runtime_used": False,
        "status": "running" if len(completed) < state["budget"]["max_trials"] and state["queue"] else "pending_source_review",
        "target_reached": True,
        "fault_trials": len(completed),
        "strict_injections": sum(trial["exact_order_applied"] for trial in completed),
        "target_after_fault": len(valid),
        "target_exception_after_fault_trials": len(candidates),
        "expected_stale_key_exceptions_per_run": EXPECTED_STALE_KEY_THROWS,
        "bug_mark": "candidate_needs_replay_source_review" if candidates else "none",
        "coverage_gain": {category: len(state["coverage"][category])
                          - len(state["healthy_coverage"][category])
                          for category in base.COVERAGE},
        "elapsed_seconds": round(state["healthy_seconds"]
                                 + sum(trial["elapsed_seconds"] for trial in completed), 3),
        "independent_campaign": {
            "budget": state["budget"], "checkpoint": str(base.STATE),
            "healthy": str(base.HEALTHY),
            "completed_sequence_ids": [trial["id"] for trial in completed],
            "strict_target_trials": len(valid),
            "unexpected_target_exception_candidates": len(candidates),
        },
    }
    base.atomic_json(base.RESULT, result)
    with base.LEDGER.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("trial", "sequence_id", "faults", "seconds", "junit_exit",
                         "exact", "target_after_fault", "total_target_exceptions",
                         "unexpected_target_exceptions", "methods_gain", "branches_gain",
                         "new_io_families", "run"))
        for index, trial in enumerate(completed, 1):
            writer.writerow((index, trial["id"], len(trial["sequence"]),
                             trial["elapsed_seconds"], trial["junit_exit"],
                             trial["exact_order_applied"], trial["target_after_fault"],
                             trial["total_target_exceptions"],
                             trial["target_exception_after_fault"],
                             trial["coverage_gain"]["methods"],
                             trial["coverage_gain"]["branch_counts"],
                             len(trial["new_io_families"]), trial["run"]))


base.evaluate = evaluate
base.initial_queue = initial_queue
base.extend = extend
base.write_result = write_result

if __name__ == "__main__":
    base.main()
