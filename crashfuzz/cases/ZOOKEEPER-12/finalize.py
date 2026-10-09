#!/usr/bin/env python3
"""Refresh the ZK12 checklist item from completed isolated trial evidence."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time

here = Path(__file__).resolve().parent
names = [
    "other_peer_final_accepted_read",
    "target_peer_accepted_read",
    "earlier_target_peer_accepted_write",
    "double_accepted_writes",
    "triple_accepted_writes",
]
trials = []
for name in names:
    trial = json.loads((here / "trials" / name / "summary.json").read_text())
    assert trial["matched"] == trial["applied"] >= 1
    assert trial["target_fatal_after_fault"] is False
    trials.append({key: value for key, value in trial.items() if key != "events"})

def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)

write_json(here / "trials.json", trials)
started = (here / "source" / ".git").stat().st_ctime
now = time.time()
result = {
    "case_id": "ZOOKEEPER-12",
    "status": "pending_persisted_file_edge",
    "system": "ZooKeeper 3.8.7",
    "source_file": "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java",
    "function": "org.apache.zookeeper.server.quorum.QuorumPeer.loadDataBase()",
    "check_code": "if (acceptedEpoch < currentEpoch) throw new IOException(...) with the two epoch values",
    "selection_line": 1197,
    "resolved_check_line": 1193,
    "resolved_throw_source_line": 1194,
    "resolved_target_site": "<org.apache.zookeeper.server.quorum.QuorumPeer: void loadDataBase()>#u76",
    "resolved_guard_site": "<org.apache.zookeeper.server.quorum.QuorumPeer: void loadDataBase()>#u62",
    "fatal_guard_outcome": False,
    "cluster_test": "org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest.testReadCurrentEpochFromAcceptedEpochTmpFile",
    "cluster_nodes": 3,
    "source_checkout_commit": "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae",
    "graphchecker_case_base_commit": "cf74a2e1d8b40cbb73670dd33c646a75fa5ed5e9",
    "graphchecker_case_commit": "3454d6210add68c03c9ef3cf25b4403c2753bc42",
    "graphchecker_jar_sha256": "6e6ff11203dfbe327d7b50466fe280f5a77d6f0c4c1945e037f552e77a1d3408",
    "target_reached": True,
    "healthy_target_guard_hits": 9,
    "healthy_target_fatal": False,
    "pinned_target_source": "zk-peer-0#epoch2",
    "healthy_final_target_epoch_reads": [1, 2, 2],
    "target_region_id": "REGION.e58c435f-888b-30d6-93a4-2078e7f4199b",
    "healthy_exact_target_plan_rows": 1,
    "healthy_candidate_shared_location_plan_rows": 2,
    "healthy_target_plan_blockers": 0,
    "edge_evidence": "UNAVAILABLE",
    "missing_graph_edge": "Earlier zk-peer-0#epoch1 acceptedEpoch successful writer to final zk-peer-0#epoch2 acceptedEpoch read across restart; the JUnit FileUtils currentEpoch writes also lack file-state versions.",
    "fault_trials": len(trials),
    "matched_injections": sum(t["matched"] for t in trials),
    "applied_injections": sum(t["applied"] for t in trials),
    "strict_injections": 1,
    "target_after_fault": sum(t["target_selected_after_fault"] for t in trials),
    "strict_target_after_fault": 0,
    "target_after_fault_fatal": False,
    "coverage_gain": 2,
    "coverage_kind": "new_branch_outcome_pairs_in_target_skeleton_methods_plus_epoch_file_methods_union_of_target_retaining_trials",
    "global_branch_outcome_gain": 30,
    "method_coverage_gain": 1,
    "bug_mark": "none",
    "source_inventory_only": False,
    "stopping_reason": "persistent_file_state_edge_unavailable",
    "elapsed_seconds": round(now - started, 3),
    "started_at_utc": datetime.fromtimestamp(started, timezone.utc).isoformat(),
    "updated_at_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
    "elapsed_breakdown_seconds": {
        "native_maven_build_and_junit": 39.873,
        "native_junit_method": 16.672,
        "static_slice_engine": 24.888,
        "healthy_graph_junit": 20,
        "fault_trials_total": round(sum(t["elapsed_seconds"] for t in trials), 3),
    },
    "timing_note": "elapsed_seconds is full wall time from isolated source worktree creation through this checkpoint, including setup failures, static analysis, recording, aggregation, fault trials, and review. The breakdown has measured substeps and is not an additive partition.",
    "evidence": "crashfuzz/cases/ZOOKEEPER-12/README.md",
    "trial_history": "crashfuzz/cases/ZOOKEEPER-12/trials.json",
    "reason": "The stock three-peer JUnit reaches the selected guard. Five exact-selector trials applied eight IOException faults; four trials retained the pinned target after the final fault, and none took its fatal arm. The only strict target-region fault lost the target and was discarded. A semantically relevant earlier acceptedEpoch writer is missing from the graph's cross-restart file-state closure, so this case cannot yet be marked quality_complete or bug-negative.",
}
write_json(here / "result.json", result)
