#!/usr/bin/env python3
"""Expose both independent SOLR-09 phases in the one-check checklist row."""

import json
import fcntl
from pathlib import Path

from feedback import atomic_json


STAGE2 = Path(__file__).resolve().parents[1]
CASE = STAGE2.parent
STAGE1_RESULT = CASE / "independent/result.json"
STAGE2_RESULT = STAGE2 / "result.json"
V2_RESULT = CASE / "actor-v2/result.json"
OUTPUT = CASE / "result.json"


def main() -> None:
    with (CASE / ".merge-results.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        merge_locked()


def merge_locked() -> None:
    phase1 = json.loads(STAGE1_RESULT.read_text())
    phase2 = json.loads(STAGE2_RESULT.read_text())
    phase3 = json.loads(V2_RESULT.read_text()) if V2_RESULT.exists() else None
    if phase1["case_id"] != "SOLR-09" or phase2["case_id"] != "SOLR-09":
        raise AssertionError("Cannot merge results for different selected checks")
    if phase1["status"] not in ("quality_complete", "candidate_needs_source_review"):
        raise AssertionError("The ZooKeeper-only phase must be audited first")
    legacy_candidates = (phase1["target_exception_candidates"] +
                         phase2["target_exception_candidates"])
    candidates = phase3["target_exception_candidates"] if phase3 else 0
    if phase3 and phase3["status"] == "running":
        status = "actor_v2_running"
    elif phase3 and phase3["status"] not in ("quality_complete", "pending_result_review"):
        status = "actor_v2_pending_review"
    elif candidates or legacy_candidates:
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
        "methodology": "independent_graph_free_coarse_phases_then_actor_aware_v2",
        "fault_trials": phase3["fault_trials"] if phase3 else 0,
        "strict_injections": phase3["strict_injections"] if phase3 else 0,
        "valid_trials": phase3["valid_trials"] if phase3 else 0,
        "qualified_actor_v2_valid_trials": phase3["valid_trials"] if phase3 else 0,
        "target_after_fault": phase3["target_after_fault"] if phase3 else 0,
        "target_exception_candidates": candidates,
        "elapsed_seconds": phase3["elapsed_seconds"] if phase3 else 0,
        "coverage_gain": phase3["coverage_gain"] if phase3 else 0,
        "new_io_identities": phase3["new_io_identities"] if phase3 else 0,
        "coverage_note": "Top-level metrics count actor-aware V2 only. Earlier ZK phases lack concrete actor identity and are exploratory only.",
        "bug_mark": ("unconfirmed_actor_v2_candidate" if candidates else
                     "legacy_coarse_unconfirmed_candidate" if legacy_candidates else "none"),
        "legacy_coarse": {
            "fault_trials": phase1["fault_trials"] + phase2["fault_trials"],
            "strict_injections": phase1["strict_injections"] + phase2["strict_injections"],
            "valid_trials_path_callsite_only": phase1["valid_trials"] + phase2["valid_trials"],
            "target_after_fault_path_callsite_only": phase1["target_after_fault"] + phase2["target_after_fault"],
            "target_exception_candidates": legacy_candidates,
            "elapsed_seconds": round(phase1["elapsed_seconds"] + phase2["elapsed_seconds"], 3),
            "identity_limitation": "ZK client/Overseer reader actor absent from selectors",
        },
        "phase_results": {
            "zk": "cases/SOLR-09/independent/result.json",
            "http_coreadmin_zk": "cases/SOLR-09/http-stage2/result.json",
            "actor_v2": "cases/SOLR-09/actor-v2/result.json",
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
            "actor_v2": {key: phase3.get(key) for key in (
                "status", "fault_trials", "strict_injections", "valid_trials",
                "target_after_fault", "target_exception_candidates", "elapsed_seconds",
                "coverage_gain", "new_io_identities", "budget")} if phase3 else None,
        },
        "non_target_replay": phase1.get("non_target_replay"),
    })
    atomic_json(OUTPUT, result)
    print(json.dumps({key: result[key] for key in (
        "status", "fault_trials", "valid_trials", "target_after_fault",
        "target_exception_candidates", "elapsed_seconds")}, sort_keys=True))


if __name__ == "__main__":
    main()
