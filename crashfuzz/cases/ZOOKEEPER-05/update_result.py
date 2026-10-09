#!/usr/bin/env python3
"""Publish the combined, case-local GraphChecker checkpoint."""

import json
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
CORE = HERE / "fuzzer-r2" / "ZOOKEEPER-05" / "result.json"
V2 = HERE / "fuzzer-v2-single" / "ZOOKEEPER-05" / "result.json"
REVIEW = HERE / "final-review.json"
DEST = HERE / "result.json"


def main():
    result = json.loads(CORE.read_text())
    if V2.exists():
        v2 = json.loads(V2.read_text())
        for key in ("fault_trials", "strict_injections",
                    "post_fault_target_reach_trials", "lost_target_trials",
                    "target_exception_after_fault_trials", "oracle_candidates",
                    "fault_seconds", "aggregate_seconds"):
            result[key] = round(result.get(key, 0) + v2.get(key, 0), 3)
        coverage_path = HERE / "coverage-summary.json"
        if coverage_path.exists():
            coverage = json.loads(coverage_path.read_text())
            result["coverage_gain"] = coverage["new_coverage_count"]
            result["coverage_kind"] = coverage["kind"]
            result["new_branch_outcome_count"] = coverage["new_branch_outcome_count"]
            result["new_target_closure_branch_outcome_count"] = coverage[
                "new_target_closure_branch_outcome_count"]
        result["graph_blocking_gaps"] += v2.get("graph_blocking_gaps", 0)
        result["graph_edges_unavailable"] = bool(
            result.get("graph_edges_unavailable") or v2.get("graph_edges_unavailable"))
        # The first exploratory aggregator command failed only because it
        # lacked the loop bound property. Its workload/repair are preserved.
        invalid_attempt_seconds = 67.313 + 46.724
        v2_build_seconds = 21.0
        v2_seed_seconds = 66.0
        result["elapsed_breakdown_seconds"] = {
            "setup": result["setup_seconds"],
            "first_graphchecker_build": result["build_seconds"],
            "first_healthy_record": result["seed_seconds"],
            "exploratory_discarded_attempt": invalid_attempt_seconds,
            "first_checked_fault_workloads": json.loads(CORE.read_text())["fault_seconds"],
            "first_checked_fault_aggregates": json.loads(CORE.read_text())["aggregate_seconds"],
            "explicit_throw_build": v2_build_seconds,
            "explicit_throw_healthy_record": v2_seed_seconds,
            "explicit_throw_fault_workloads": v2.get("fault_seconds", 0),
            "explicit_throw_fault_aggregates": v2.get("aggregate_seconds", 0),
        }
        result["elapsed_seconds"] = round(sum(result["elapsed_breakdown_seconds"].values()), 3)
        result["total_elapsed_seconds"] = result["elapsed_seconds"]
        result["status"] = ("fuzzing" if v2.get("status") == "fuzzing" else
                            v2.get("status", "fuzzing"))
    result["target_after_fault"] = result.get("post_fault_target_reach_trials", 0)
    result["target_guard_site_id"] = "<org.apache.zookeeper.server.quorum.Follower: void followLeader()>#u52"
    result["target_guard_fatal_outcome"] = False
    result["target_exception_constructor_site_id"] = "<org.apache.zookeeper.server.quorum.Follower: void followLeader()>#u67"
    result["selected_throw_has_runtime_event"] = bool(
        V2.exists() and v2.get("target_exception_after_fault_trials", 0))
    result["explicit_throw_hook_woven"] = V2.exists()
    result["caught_throw_oracle"] = (
        "same selected callId: #u52=false then EXPLICIT_THROW #u68 "
        "with java.io.IOException after the last applied fault") if V2.exists() else (
        "same-call #u52=false followed by #u67 IOException constructor "
        "with exact message; source bytecode then ATHROW #u68, caught locally")
    if V2.exists():
        result["target_throw_event"] = "EXPLICIT_THROW"
        result["target_explicit_throw_site_id"] = result["target_throw_site_id"]
    result["evidence"] = str(HERE / "README.md")
    result["source_inventory_only"] = False
    if REVIEW.exists() and result["status"] == "budget_or_queue_complete":
        review = json.loads(REVIEW.read_text())
        if review.get("case_id") != result["case_id"]:
            raise ValueError("final review has a different case ID")
        result.update({key: value for key, value in review.items()
                       if key != "case_id"})
    temp = DEST.with_suffix(".json.tmp")
    temp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    os.replace(temp, DEST)


if __name__ == "__main__":
    main()
