#!/usr/bin/env python3
"""Rebuild the ZK06 case ledger from immutable trial results and archives."""

import collections
import datetime
import gzip
import hashlib
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
METHOD = "<org.apache.zookeeper.server.quorum.Leader: void waitForEpochAck(long,org.apache.zookeeper.server.quorum.StateSummary)>"
GUARD = METHOD + "#u14"
CAMPAIGNS = ("fuzz", "fuzz-r3", "fuzz-response", "fuzz-response-retry",
             "fuzz-ackepoch")


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def target_addresses(plan):
    if not plan or not plan.exists():
        return set()
    found = set()
    for line in plan.open():
        row = json.loads(line)
        if row.get("kind") == "CONCOLIC_REGION_PLAN" and row.get("targetMethod") == METHOD:
            if any(goal.get("kind") == "TARGET_REACH_CLOSURE"
                   for goal in row.get("closureGoals", [])):
                found.add(row["occurrenceId"])
    return found


def after_fault_guards(trace, addresses):
    if not addresses:
        return []
    calls = set()
    branches = []
    last_fault = -1
    with gzip.open(trace, "rt") as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("event") == "FAULT_APPLIED":
                last_fault = max(last_fault, event.get("seq", -1))
            elif (event.get("event") == "METHOD_ENTER"
                    and event.get("method") == METHOD
                    and event.get("occurrenceAddress") in addresses):
                calls.add(event["callId"])
            elif (event.get("event") == "BRANCH"
                    and event.get("siteId") == GUARD):
                branches.append(event)
    return [event["outcome"] for event in branches
            if event.get("callId") in calls and event.get("seq", -1) > last_fault >= 0]


def main():
    correction = {row["trial"]: row for row in json.loads(
        (HERE / "reanalysis-r3/summary.json").read_text())}
    ledger = []
    for campaign in CAMPAIGNS:
        directory = HERE / campaign / "ZOOKEEPER-06"
        for result_path in sorted(directory.glob("trials/*/result.json")):
            trial = result_path.parent
            result = json.loads(result_path.read_text())
            faults = json.loads((trial / "fault-trial.json").read_text())["faults"]
            corrected = correction.get(trial.name) if campaign == "fuzz-r3" else None
            kept = bool(corrected["targetAfterFault"] if corrected and
                        corrected.get("aggregateExit") == 0 else
                        result.get("target_reached_after_fault", False))
            if campaign == "fuzz-r3":
                plan = HERE / "reanalysis-r3" / trial.name / "plan.jsonl"
            else:
                plan = trial / "aggregate/plan.jsonl"
            recorded_trace = Path(result["trace"])
            trace = recorded_trace.with_name(recorded_trace.name + ".gz")
            outcomes = after_fault_guards(trace, target_addresses(plan)) if kept else []
            aggregate = result.get("aggregate") or {}
            runtime = float(result.get("elapsed_seconds", 0))
            aggregation = float(aggregate.get("elapsed_seconds", 0))
            ledger.append({
                "case_id": "ZOOKEEPER-06",
                "campaign": campaign,
                "trial": trial.name,
                "completed_at_utc": datetime.datetime.fromtimestamp(
                    result["completed_at"], datetime.timezone.utc).isoformat(),
                "faults": faults,
                "selected_fault_count": len(faults),
                "matched_fault_count": result.get("matched_count", 0),
                "applied_fault_count": result.get("applied_count", 0),
                "all_selectors_matched": bool(result.get("selector_matched")),
                "target_check_after_fault": kept,
                "target_guard_outcomes_after_fault": outcomes,
                "target_fatal_exception_count": result.get(
                    "target_fatal_exception_count", 0),
                "oracle_candidate": bool(result.get("oracle")),
                "dynamic_target_closure": kept and bool(
                    corrected.get("aggregateExit") == 0 if corrected else
                    result.get("dynamic_graph")),
                "blocking_graph_gap_count": (
                    corrected.get("blockingGaps", 0) if corrected and kept else
                    len(result.get("blocking_graph_gaps") or [])),
                "junit_execution_seconds": round(runtime, 3),
                "graph_aggregation_seconds": round(aggregation, 3),
                "measured_trial_seconds": round(runtime + aggregation, 3),
                "trace_archive": str(trace.relative_to(HERE)),
                "trial_result": str(result_path.relative_to(HERE)),
                "corrected_reanalysis": (str((HERE / "reanalysis-r3" /
                    trial.name / "summary.json").relative_to(HERE))
                    if corrected else None),
            })
    (HERE / "trial-ledger.jsonl").write_text("".join(
        json.dumps(row, sort_keys=True) + "\n" for row in ledger))
    families = collections.defaultdict(lambda: {"selected": 0, "applied": 0,
                                                 "unique_selected": set(),
                                                 "unique_applied": set(),
                                                 "target_retained_trials": 0})
    for row in ledger:
        markers = set()
        for fault in row["faults"]:
            marker = fault["marker"]
            family = families[marker]
            identity = tuple(fault.get(key) for key in
                             ("marker", "siteId", "occurrence", "hitOrdinal", "sourceKey"))
            family["selected"] += 1
            family["unique_selected"].add(identity)
            if row["all_selectors_matched"]:
                family["applied"] += 1
                family["unique_applied"].add(identity)
            markers.add(marker)
        if row["target_check_after_fault"]:
            for marker in markers:
                families[marker]["target_retained_trials"] += 1
    family_rows = {}
    for marker, item in sorted(families.items()):
        family_rows[marker] = {key: value for key, value in item.items()
                               if not key.startswith("unique_")}
        family_rows[marker]["unique_selected"] = len(item["unique_selected"])
        family_rows[marker]["unique_applied"] = len(item["unique_applied"])
    archive = json.loads((HERE / "artifact-manifest.json").read_text())
    case_started_at = (HERE / "adapter/zookeeper/zk06").stat().st_mtime
    case_finished_at = time.time()
    result = {
        "schema_version": 1,
        "case_id": "ZOOKEEPER-06",
        "system": "ZooKeeper",
        "version": "3.8.7",
        "status": "pending_graph_precision",
        "quality_complete": False,
        "bug_mark": "none",
        "cluster_test": "org.apache.zookeeper.test.QuorumRestartTest#testRollingRestart",
        "cluster": "original JUnit three-peer in-JVM QuorumUtil; rolling restart of peers 1, 2, 3",
        "target_file": "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Leader.java",
        "target_function": METHOD,
        "target_condition_line": 1471,
        "target_throw_lines": [1472, 1475],
        "target_code": "if (ss.isMoreRecentThan(leaderStateSummary)) throw new IOException(\"Follower is ahead of the leader...\")",
        "target_site_id": GUARD,
        "target_throw_site_id": METHOD + "#u29",
        "target_region_id": "REGION.b3eb0be6-3e8d-3adf-81c3-07d7060c0e07",
        "healthy_target_check_reached": True,
        "healthy_guard_outcome": True,
        "fault_trials": len(ledger),
        "selected_fault_events": sum(row["selected_fault_count"] for row in ledger),
        "applied_fault_events": sum(row["applied_fault_count"] for row in ledger),
        "fully_matched_fault_sequences": sum(row["all_selectors_matched"] for row in ledger),
        "unmatched_fault_sequences": sum(not row["all_selectors_matched"] for row in ledger),
        "target_check_after_fault_trials": sum(row["target_check_after_fault"] for row in ledger),
        "target_exception_after_fault_trials": sum(row["target_fatal_exception_count"] > 0 for row in ledger),
        "oracle_candidates": sum(row["oracle_candidate"] for row in ledger),
        "elapsed_seconds": round(sum(row["measured_trial_seconds"] for row in ledger), 3),
        "elapsed_scope": "sum of measured JUnit fault execution and GraphChecker aggregation time for 32 trials; excludes static preparation, healthy seeds and manual reanalysis",
        "total_elapsed_seconds": round(case_finished_at - case_started_at, 3),
        "total_elapsed_scope": "wall-clock span from creation of the first case-local ZK06 adapter to report finalization; includes static preparation, healthy seeds, fault trials, trace reanalysis, source review and idle time",
        "case_started_at_utc": datetime.datetime.fromtimestamp(
            case_started_at, datetime.timezone.utc).isoformat(),
        "case_finished_at_utc": datetime.datetime.fromtimestamp(
            case_finished_at, datetime.timezone.utc).isoformat(),
        "junit_execution_seconds": round(sum(row["junit_execution_seconds"] for row in ledger), 3),
        "graph_aggregation_seconds": round(sum(row["graph_aggregation_seconds"] for row in ledger), 3),
        "fault_families": family_rows,
        "coverage_feedback": "method-entry and branch-outcome signatures collected each run; gains within builds: r2=3, r3 response=5, r4 ACKEPOCH=7; raw site IDs cannot be unioned across different woven builds",
        "graph_blocking_gaps_for_selected_healthy_target": 0,
        "graph_edge_evidence": "UNAVAILABLE",
        "remaining_gap": "Leader.leaderStateSummary receives LeaderZooKeeperServer.getLastProcessedZxid() via call-return, but the frozen candidate dataflow graph has no FileTxnLog/FileSnap state-producer edge; full persisted-zxid backward closure is unproven. One late response IOException selector remained unmatched after retry.",
        "source_review": "LearnerHandler constructs StateSummary from ACKEPOCH epoch bytes and zxid, then calls waitForEpochAck; Leader compares against currentEpoch and lastProcessedZxid loaded before new epoch proposal. A read failure before ACKEPOCH decoding can abort that handler, so trials that erase the check are not negative evidence.",
        "graphchecker_commits": ["4837827c6", "08bbfb78e", "b9e73d006"],
        "graphchecker_system_head": "a8bc916b7",
        "graphchecker_jar_sha256": archive["graphchecker_jars"],
        "evidence": ["trial-ledger.jsonl", "artifact-manifest.json",
                     "producer-gap.json",
                     "run-r4/candidate_dataflow_edges.jsonl.gz",
                     "run-r4/selected/plan.jsonl", "reanalysis-r3/summary.json"],
    }
    (HERE / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "fault_trials", "selected_fault_events", "applied_fault_events",
        "fully_matched_fault_sequences", "unmatched_fault_sequences",
        "target_check_after_fault_trials", "target_exception_after_fault_trials",
        "elapsed_seconds", "total_elapsed_seconds")}, indent=2))


if __name__ == "__main__":
    main()
