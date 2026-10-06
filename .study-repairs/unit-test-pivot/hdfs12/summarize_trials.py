"""Refresh the HDFS-12 checklist row from recorded original-JUnit trials."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECORD = HERE / "server-door/record"
RESULT = HERE.parent / "cases/HDFS-12/result.json"
GUARD = ("<org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager: "
         "byte[] retrievePassword(org.apache.hadoop.hdfs.security.token.block."
         "BlockTokenIdentifier)>#u25")


def rows(path: Path):
    with path.open() as stream:
        for line in stream:
            yield json.loads(line)


def branch_pairs(path: Path) -> set[tuple[str, bool]]:
    return {(row["siteId"], row["outcome"])
            for row in rows(path) if row.get("event") == "BRANCH"}


def main() -> None:
    result = json.loads(RESULT.read_text())
    healthy = RECORD / "healthy"
    healthy_manifest = json.loads((healthy / "manifest.json").read_text())
    healthy_trace = healthy / "trace/runtime_trace.jsonl"
    baseline_pairs = branch_pairs(healthy_trace)
    all_pairs = set(baseline_pairs)
    trials = []
    for directory in sorted(RECORD.iterdir()):
        if not directory.is_dir() or directory.name == "healthy":
            continue
        manifest = json.loads((directory / "manifest.json").read_text())
        trace = directory / "trace/runtime_trace.jsonl"
        trial_rows = list(rows(trace))
        summary, = [row for row in trial_rows
                    if row.get("event") == "FAULT_TRIAL_SUMMARY"]
        outcomes = [row["outcome"] for row in trial_rows
                    if row.get("event") == "BRANCH"
                    and row.get("siteId") == GUARD]
        trial = {
            "sequence": directory.name,
            "elapsed_seconds": round(manifest["runtime"]["seconds"]
                                     + manifest["aggregate"]["seconds"], 3),
            "junit_exit": manifest["runtime"]["exit"],
            "requested_faults": summary["requested"],
            "matched_faults": summary["matched"],
            "applied_faults": summary["applied"],
            "target_after_fault": summary["targetAfterFault"],
            "target_guard_outcomes": outcomes,
            "target_fatal_exceptions": len(json.loads(
                (directory / "trace/summary.json").read_text())
                ["targets"]["HDFS-12"]["fatalOccurrences"]),
            "evidence": str(trace.relative_to(HERE.parents[2])),
        }
        trials.append(trial)
        all_pairs.update(branch_pairs(trace))
    build = json.loads((HERE / "server-door/manifest.json").read_text())
    runtime_seconds = sum(t["elapsed_seconds"] for t in trials)
    healthy_seconds = (healthy_manifest["runtime"]["seconds"]
                       + healthy_manifest["aggregate"]["seconds"])
    result.update({
        "status": "target_reached_pending_key_state_coverage",
        "cluster_test": healthy_manifest["test"],
        "cluster_nodes": "Original MiniDFSCluster, one NameNode and one DataNode by builder default",
        "healthy_target_guard_hits": 2,
        "healthy_target_branch_outcomes": [True, True],
        "healthy_target_fatal": False,
        "target_region_id": "REGION.61e62f41-34c6-3a5d-b610-b639dc3f4838",
        "graph_gap": "Stable distinct DataXceiver request addresses and no BLOCKING gap. Four real SASL SERVER_READ selectors are exact members of two target occurrences. The NN key-update response and DN addKeys/allKeys producer path are not yet in target closure with runtime identity; its shared-state read-from edge remains CANDIDATE/UNAVAILABLE.",
        "observed_fault_points": healthy_manifest["trace"]["observedFaultPoints"],
        "healthy_target_occurrence_count": 2,
        "healthy_target_closure_server_read_fault_selectors": 4,
        "fault_trials": len(trials),
        "strict_injections": sum(t["applied_faults"] for t in trials),
        "target_after_fault": sum(bool(t["target_after_fault"]) for t in trials),
        "lost_target_trials": sum(not t["target_after_fault"] for t in trials),
        "target_exception_count": sum(t["target_fatal_exceptions"] for t in trials),
        "target_fatal_branch_count": sum(t["target_guard_outcomes"].count(False) for t in trials),
        "coverage_gain": len(all_pairs - baseline_pairs),
        "coverage_gain_definition": "Distinct observed instrumented BRANCH (site,outcome) pairs across eight faulted traces versus healthy; zero new method-entry signatures. The delta is observational and may include timing effects.",
        "bug_mark": "none",
        "elapsed_seconds": round(build["seed"]["seconds"]
                                 + build["weave"]["seconds"]
                                 + healthy_seconds + runtime_seconds, 3),
        "elapsed_breakdown_seconds": {
            "static_seed": build["seed"]["seconds"],
            "region_state_weave": build["weave"]["seconds"],
            "healthy_junit_and_aggregate": round(healthy_seconds, 3),
            "eight_fault_jvms_and_aggregates": round(runtime_seconds, 3),
        },
        "timing_note": "Measured process durations for the final 23-class SERVER_READ campaign; earlier feasibility probes and source review excluded.",
        "status_scope": "Eight exact SERVER_READ trials complete; full check pending producer-side block-key export/import identity and key-state fault coverage.",
        "stop_reason": "SERVER_READ one- and two-fault subqueue exhausted; keep checklist open because post-rotation key-update response and DN addKeys are not yet proven target-closure members.",
        "remaining_work": "Carry stable DataNode identity through BPServiceActor heartbeat response and command-processing handoff, establish runtime-exact producer-to-target key-state closure, then test eligible producer fault points using the unmodified long-lived-client JUnit test.",
        "trial_results": trials,
        "evidence": ".study-repairs/unit-test-pivot/hdfs12/server-door/manifest.json; .study-repairs/unit-test-pivot/hdfs12/server-door/record/healthy/trace/concolic_region_plan.jsonl; .study-repairs/unit-test-pivot/hdfs12/server-door/record; .study-repairs/unit-test-pivot/hdfs12/server-door/long-lived/healthy",
    })
    RESULT.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in
                      ("status", "fault_trials", "strict_injections",
                       "target_after_fault", "coverage_gain",
                       "elapsed_seconds", "bug_mark")}, indent=2))


if __name__ == "__main__":
    from summarize_all import main as summarize_all

    summarize_all()
