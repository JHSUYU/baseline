#!/usr/bin/env python3
"""Expose both independent SOLR-09 phases in the one-check checklist row."""

import json
from pathlib import Path

from feedback import atomic_json


STAGE2 = Path(__file__).resolve().parents[1]
CASE = STAGE2.parent
STAGE1_RESULT = CASE / "independent/result.json"
STAGE2_RESULT = STAGE2 / "result.json"
OUTPUT = CASE / "result.json"


def main() -> None:
    phase1 = json.loads(STAGE1_RESULT.read_text())
    phase2 = json.loads(STAGE2_RESULT.read_text())
    if phase1["case_id"] != "SOLR-09" or phase2["case_id"] != "SOLR-09":
        raise AssertionError("Cannot merge results for different selected checks")
    if phase1["status"] not in ("quality_complete", "candidate_needs_source_review"):
        raise AssertionError("The ZooKeeper-only phase must be audited first")
    candidates = (phase1["target_exception_candidates"] +
                  phase2["target_exception_candidates"])
    if candidates:
        status = "candidate_needs_source_review"
    elif phase2["status"] == "running":
        status = "stage2_running"
    elif phase2["status"] == "quality_complete":
        status = "quality_complete"
    elif phase2["status"] == "limited_budget_or_queue_exhaustion":
        status = "quality_complete_limited_http_followup"
    else:
        status = "pending_result_review"
    result = {key: phase1[key] for key in (
        "case_id", "system", "source_file", "source_line", "function",
        "check_code", "cluster_test", "target_reached")}
    result.update({
        "status": status,
        "methodology": "independent_graph_free_zk_then_http_coreadmin_zk",
        "fault_trials": phase1["fault_trials"] + phase2["fault_trials"],
        "strict_injections": (phase1["strict_injections"] +
                              phase2["strict_injections"]),
        "valid_trials": phase1["valid_trials"] + phase2["valid_trials"],
        "target_after_fault": (phase1["target_after_fault"] +
                               phase2["target_after_fault"]),
        "target_exception_candidates": candidates,
        "elapsed_seconds": round(phase1["elapsed_seconds"] +
                                 phase2["elapsed_seconds"], 3),
        "coverage_gain": {
            "ZK phase": phase1["coverage_gain"],
            "HTTP+ZK phase": phase2["coverage_gain"],
        },
        "new_io_identities": {
            "ZK phase": phase1["new_io_identities"],
            "HTTP+ZK phase": phase2["new_io_identities"],
        },
        "coverage_note": "Separate phase baselines and instrumented classes; coverage gains are not summed.",
        "bug_mark": "candidate_needs_source_review" if candidates else "none",
        "phase_results": {
            "zk": "cases/SOLR-09/independent/result.json",
            "http_coreadmin_zk": "cases/SOLR-09/http-stage2/result.json",
        },
        "phases": {
            "zk": {key: phase1.get(key) for key in (
                "status", "fault_trials", "strict_injections", "valid_trials",
                "target_after_fault", "target_exception_candidates", "elapsed_seconds",
                "coverage_gain", "new_io_identities", "budget")},
            "http_coreadmin_zk": {key: phase2.get(key) for key in (
                "status", "fault_trials", "strict_injections", "valid_trials",
                "target_after_fault", "target_exception_candidates", "elapsed_seconds",
                "coverage_gain", "new_io_identities", "budget")},
        },
        "non_target_replay": phase1.get("non_target_replay"),
    })
    atomic_json(OUTPUT, result)
    print(json.dumps({key: result[key] for key in (
        "status", "fault_trials", "valid_trials", "target_after_fault",
        "target_exception_candidates", "elapsed_seconds")}, sort_keys=True))


if __name__ == "__main__":
    main()
