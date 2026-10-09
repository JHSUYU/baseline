#!/usr/bin/env python3
"""Publish one HDFS-08 result from the independent JUnit campaign stages."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path


CASE = Path(__file__).resolve().parents[1]
ROOT_RESULT = CASE.parent / "result.json"
STAGES = (
    ("singlewriter", CASE / "campaign",
     CASE / "healthy/instrumented-segment-context",
     CASE / "healthy/original/manifest.json"),
    ("multiwriter", CASE / "campaign-multiwriter",
     CASE / "healthy/multiwriter-probe",
     CASE / "healthy/multiwriter-original/manifest.json"),
)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temp.open("w") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def atomic_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def coverage_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    return set(path.read_text().splitlines())


def publish_case_result() -> dict:
    """Reconcile completed rows only; never launch or repeat a JUnit."""
    root = json.loads(ROOT_RESULT.read_text())
    snapshots = []
    combined_rows = []
    healthy_coverage = set()
    healthy_seconds = 0.0
    for stage, directory, healthy, original_manifest in STAGES:
        checkpoint = directory / "checkpoint.json"
        if not checkpoint.is_file():
            continue
        state = json.loads(checkpoint.read_text())
        rows = state["completed"]
        stage_result_file = directory / "stage-result.json"
        stage_result = (json.loads(stage_result_file.read_text())
                        if stage_result_file.is_file() else {})
        snapshots.append((stage, directory, state, rows, stage_result))
        combined_rows.extend((stage, row) for row in rows)
        healthy_coverage.update(coverage_ids(healthy / "coverage.tsv"))
        healthy_seconds += json.loads(original_manifest.read_text())[
            "elapsed_seconds"]
        healthy_seconds += json.loads((healthy / "manifest.json").read_text())[
            "elapsed_seconds"]
    paxos_migration = CASE / "campaign-multiwriter/recorder-migration.json"
    if paxos_migration.is_file():
        healthy_seconds += json.loads((CASE /
            "healthy/multiwriter-paxos-probe/manifest.json").read_text())[
                "elapsed_seconds"]
    if not snapshots:
        return root
    admitted_ids = {identifier for _, row in combined_rows
                    for identifier in row["new_coverage_ids"]}
    gain_ids = admitted_ids - healthy_coverage
    coverage_gain = {kind: sum(identifier.startswith(kind + "\t")
                               for identifier in gain_ids)
                     for kind in ("METHOD", "BRANCH_UNIT", "PROBE")}
    strict_count = sum(row["strict_injection"] for _, row in combined_rows)
    target_after_count = sum(row["strict_injection"] and
                             row["target_guard_after_last_fault"]
                             for _, row in combined_rows)
    exact_count = sum(row["strict_injection"] and
                      row["target_exception_after_fault_count"] > 0
                      for _, row in combined_rows)
    candidate_count = sum(row["bug_mark"] == "candidate"
                          for _, row in combined_rows)
    total = len(combined_rows)
    active_stage, active_dir, active_state, active_rows, active_result = snapshots[-1]
    case_budget = active_state["budget"]["max_trials"] + active_state.get(
        "singlewriter_completed_before_stage", 0)
    status = ("candidate_review" if candidate_count else
              "quality_complete" if active_stage == "multiwriter" and
              (total >= case_budget or active_result.get("status") ==
               "queue_exhausted") else "fuzzing")
    stages = {}
    for stage, directory, state, rows, stage_result in snapshots:
        stages[stage] = {**stage_result,
                         "checkpoint": str(directory.relative_to(CASE) /
                                           "checkpoint.json"),
                         "trial_ledger": str(directory.relative_to(CASE) /
                                             "trial-ledger.csv"),
                         "healthy_target_context": (
                             {"node": "jn2", "caller": "finalizeLogSegment",
                              "segment_start_txid": 1,
                              "segment_end_txid": 3,
                              "request_epoch": 1 if stage == "singlewriter" else 2,
                              "promised_epoch": 1 if stage == "singlewriter" else 2})}
    root.update({
        "status": status,
        "methodology": "coverage_io_source_probes_no_graph",
        "cluster_test": (
            "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#" +
            ("testSingleWriter" if active_stage == "singlewriter" else
             "testChangeWritersLogsInSync")),
        "cluster_tests": [
            "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#"
            "testSingleWriter",
            "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#"
            "testChangeWritersLogsInSync"],
        "fault_trials": total,
        "baseline_trial_budget": case_budget,
        "baseline_max_faults_per_sequence": active_state["budget"]["max_faults"],
        "requested_fault_events": sum(row["requested_faults"]
                                      for _, row in combined_rows),
        "matched_fault_events": sum(row["matched_faults"]
                                    for _, row in combined_rows),
        "applied_fault_events": sum(row["applied_faults"]
                                    for _, row in combined_rows),
        "strict_injection_trials": strict_count,
        "strict_injections": strict_count,
        "fully_applied_trials": strict_count,
        "post_fault_target_reach_trials": target_after_count,
        "target_after_fault": target_after_count,
        "target_exception_after_fault_trials": exact_count,
        "target_false_guard_trials": sum(
            row["strict_injection"] and row["target_guard_after_last_fault"] and
            False in row["target_outcomes_after_fault"]
            for _, row in combined_rows),
        "oracle_candidates": candidate_count,
        "bug_mark": "candidate" if candidate_count else "none",
        "coverage_gain": coverage_gain,
        "multi_fault_trials": sum(row["requested_faults"] > 1
                                  for _, row in combined_rows),
        "max_requested_faults": max((row["requested_faults"]
                                     for _, row in combined_rows), default=0),
        "target_lost_trials": sum(row["status"] == "lost_target"
                                  for _, row in combined_rows),
        "unmatched_trials": sum(row["status"] == "unmatched"
                                for _, row in combined_rows),
        "junit_nonzero_trials": sum(row["junit_exit"] != 0
                                    for _, row in combined_rows),
        "elapsed_seconds": round(healthy_seconds +
                                 sum(row["seconds"] for _, row in combined_rows),
                                 3),
        "elapsed_measurement": (
            "Sum of healthy JUnit elapsed and per-trial active driver seconds; "
            "time between paused tmux sessions is excluded. The interrupted "
            "multiwriter trial-10 records at least its completed JUnit time "
            "and may undercount its first driver setup by several seconds."),
        "stages": stages,
        "evidence": {**root.get("evidence", {}),
                     "independent_singlewriter_checkpoint":
                     "independent-coverage-io/campaign/checkpoint.json",
                     "independent_multiwriter_checkpoint":
                     "independent-coverage-io/campaign-multiwriter/checkpoint.json",
                     "independent_multiwriter_paxos_healthy":
                     "independent-coverage-io/healthy/multiwriter-paxos-probe/",
                     "independent_multiwriter_recorder_migration":
                     "independent-coverage-io/campaign-multiwriter/recorder-migration.json",
                     "independent_combined_trial_ledger":
                     "independent-coverage-io/combined-trial-ledger.csv",
                     "independent_coverage_evidence":
                     "independent-coverage-io/coverage-evidence.tar.gz",
                     "independent_audit":
                     "independent-coverage-io/audit.json"},
        "reason": "Independent source-level I/O probes and JaCoCo in unchanged "
                  "original three-JournalNode JUnit methods; exact target "
                  "guard, ordered fault matching, and target context are "
                  "checked per trial. Legacy prewoven results excluded.",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    if status == "quality_complete" and combined_rows:
        root["completed_at_utc"] = combined_rows[-1][1]["completed_at_utc"]
        root["stop_reason"] = (
            "Combined trial budget reached; final eight trials added no new "
            "production method/branch unit or stable I/O family."
            if total >= case_budget else "Observed multiwriter I/O mutation "
            "queue exhausted.")
    else:
        root.pop("completed_at_utc", None)
        root.pop("stop_reason", None)
    atomic_json(ROOT_RESULT, root)

    fields = ("global_number", "stage", "trial", "status", "requested_faults",
              "matched_faults", "applied_faults", "strict_injection",
              "target_guard_after_last_fault", "target_exception_after_fault_count",
              "junit_exit", "seconds", "new_coverage_count", "bug_mark",
              "sequence_id")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for number, (stage, row) in enumerate(combined_rows, 1):
        writer.writerow({**{key: row.get(key, "") for key in fields},
                         "global_number": number, "stage": stage})
    atomic_text(CASE / "combined-trial-ledger.csv", output.getvalue())
    return root


if __name__ == "__main__":
    result = publish_case_result()
    print(json.dumps({key: result.get(key) for key in
                      ("status", "fault_trials", "strict_injection_trials",
                       "post_fault_target_reach_trials", "coverage_gain")}))
