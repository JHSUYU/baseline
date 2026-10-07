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
V2_STATE = CASE / "actor-v2/evidence/campaign/state.json"
V2_RAW_AUDIT = CASE / "actor-v2/evidence/campaign/raw-audit.json"
V2_COVERAGE_SUMMARY = CASE / "actor-v2/evidence/campaign/coverage-summary.json"
V2_ROLE_REPLAY = CASE / "actor-v2/evidence/replay-role-trial059/summary.json"
V2_ACTUAL_REPLAY = CASE / "actor-v2/evidence/replay-actual-zk/summary.json"
V2_MAP_REPLAY = CASE / "actor-v2/evidence/replay-map-state/summary.json"
V2_TIMEOUT_REPLAY = CASE / "actor-v2/evidence/replay-timeout/summary.json"
V2_FRESH_CONTROL = CASE / "actor-v2/evidence/replay-fresh-state-control/summary.json"
V2_LOW_LOAD_REPLAY = CASE / "actor-v2/evidence/replay-low-load/summary.json"
PAUSE_REQUEST = STAGE2 / "evidence/campaign/pause-request.json"
PAUSE_ACK = STAGE2 / "evidence/campaign/pause-ack.json"
OUTPUT = CASE / "result.json"


def main() -> None:
    with (CASE / ".merge-results.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        merge_locked()


def merge_locked() -> None:
    phase1 = json.loads(STAGE1_RESULT.read_text())
    phase2 = json.loads(STAGE2_RESULT.read_text())
    phase3 = json.loads(V2_RESULT.read_text()) if V2_RESULT.exists() else None
    v2_state = json.loads(V2_STATE.read_text()) if V2_STATE.exists() else None
    raw_audit = json.loads(V2_RAW_AUDIT.read_text()) if V2_RAW_AUDIT.exists() else None
    coverage_summary = (json.loads(V2_COVERAGE_SUMMARY.read_text())
                        if V2_COVERAGE_SUMMARY.exists() else None)
    role_replay = json.loads(V2_ROLE_REPLAY.read_text()) if V2_ROLE_REPLAY.exists() else None
    actual_replay = json.loads(V2_ACTUAL_REPLAY.read_text()) if V2_ACTUAL_REPLAY.exists() else None
    map_replay = json.loads(V2_MAP_REPLAY.read_text()) if V2_MAP_REPLAY.exists() else None
    timeout_replay = json.loads(V2_TIMEOUT_REPLAY.read_text()) if V2_TIMEOUT_REPLAY.exists() else None
    fresh_control = json.loads(V2_FRESH_CONTROL.read_text()) if V2_FRESH_CONTROL.exists() else None
    low_load_replay = (json.loads(V2_LOW_LOAD_REPLAY.read_text())
                       if V2_LOW_LOAD_REPLAY.exists() else None)
    legacy_pause = (json.loads(PAUSE_ACK.read_text()) if
                    PAUSE_REQUEST.exists() and PAUSE_ACK.exists() else None)
    if phase1["case_id"] != "SOLR-09" or phase2["case_id"] != "SOLR-09":
        raise AssertionError("Cannot merge results for different selected checks")
    if phase1["status"] not in ("quality_complete", "candidate_needs_source_review"):
        raise AssertionError("The ZooKeeper-only phase must be audited first")
    legacy_candidates = (phase1["target_exception_candidates"] +
                         phase2["target_exception_candidates"])
    candidates = phase3["target_exception_candidates"] if phase3 else 0
    role_reproductions = sum(r["strict"] and r["target_after"] and r["target_exception"]
                             for r in role_replay["runs"]) if role_replay else 0
    actual_state_reproductions = sum(
        r["strict"] and r["target_after"] and r["target_exception"] and
        any(e["kind"] == "ZK_ACTUAL_STATE" and
            "replica_present=false" in e["parts"] for e in r["actual_state_events"])
        for r in actual_replay["runs"]) if actual_replay else 0
    map_reproductions = sum(
        r["strict"] and r["target_after"] and r["target_exception"] and
        any(e["kind"] == "ZK_ACTUAL_STATE" and
            "replica_present=false" in e["parts"] for e in r["actual_state_events"])
        for r in map_replay["runs"]) if map_replay else 0
    timeout_reproductions = sum(
        r["strict"] and r["target_after"] and r["target_exception"] and
        sum(e["kind"] == "PRE_TIMEOUT_READER_STATE" and
            "watch_present=true" in e["parts"] and
            "cached_present=false" in e["parts"]
            for e in r["diagnostic_events"]) >= 2 and
        any(e["kind"] == "ZK_ACTUAL_STATE" and
            "replica_present=false" in e["parts"]
            for e in r["diagnostic_events"])
        for r in timeout_replay["runs"]) if timeout_replay else 0
    fresh_control_successes = sum(
        r["strict"] and r["junit_exit"] == 0 and bool(r["fresh_state_markers"])
        for r in fresh_control["runs"]) if fresh_control else 0
    low_load_reproductions = sum(
        r["strict"] and r["target_after"] and r["target_exception"]
        for r in low_load_replay["runs"]) if low_load_replay else 0
    quality_complete = bool(
        phase3 and phase3["status"] in ("quality_complete", "pending_result_review")
        and phase3["valid_trials"] >= phase3["budget"]["max_valid_trials"]
        and raw_audit and not raw_audit["errors"]
        and raw_audit["attempts"] == phase3["fault_trials"]
        and raw_audit["strict_from_raw"] == phase3["strict_injections"]
        and raw_audit["valid_from_raw"] == phase3["valid_trials"]
        and raw_audit["target_exceptions_from_raw"] == candidates
        and coverage_summary and coverage_summary["valid_trials"] == phase3["valid_trials"])
    if phase3 and phase3["status"] == "running":
        status = "actor_v2_running"
    elif quality_complete:
        status = "quality_complete"
    elif phase3:
        status = "actor_v2_pending_review"
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
        "evidence": "cases/SOLR-09/actor-v2/evidence/campaign/state.json" if phase3 else None,
        "budget": phase3["budget"] if phase3 else None,
        "extension_reason": v2_state.get("extension_reason") if v2_state else None,
        "coverage_note": "Top-level metrics count actor-aware V2 only. Earlier ZK phases lack concrete actor identity and are exploratory only.",
        "raw_audit": "cases/SOLR-09/actor-v2/evidence/campaign/raw-audit.json" if raw_audit else None,
        "raw_audit_errors": len(raw_audit["errors"]) if raw_audit else None,
        "production_branch_coverage": coverage_summary if quality_complete else None,
        "bug_mark": ("actor_aware_reproduced_known_overlap_novelty_unresolved" if
                     timeout_reproductions >= 1 else
                     "actor_aware_reproduced_candidate_source_review" if
                     role_reproductions >= 2 and actual_state_reproductions >= 1 else
                     "unconfirmed_actor_v2_candidate" if candidates else
                     "legacy_coarse_unconfirmed_candidate" if legacy_candidates else "none"),
        "actor_aware_nonbudget_replays": {
            "role_relative_strict_target_exceptions": role_reproductions,
            "strict_target_exceptions_with_server_replica_absent": actual_state_reproductions,
            "strict_map_replays_with_server_replica_absent": map_reproductions,
            "strict_precleanup_watch_present_cache_absent_replays": timeout_reproductions,
            "strict_fresh_state_control_junit_passes": fresh_control_successes,
            "lower_load_replay_attempts": len(low_load_replay["runs"]) if low_load_replay else 0,
            "lower_load_strict_target_exceptions": low_load_reproductions,
            "counted_in_top_level_fuzz_trials": False,
            "role_summary": "cases/SOLR-09/actor-v2/evidence/replay-role-trial059/summary.json",
            "actual_state_summary": "cases/SOLR-09/actor-v2/evidence/replay-actual-zk/summary.json",
            "map_summary": "cases/SOLR-09/actor-v2/evidence/replay-map-state/summary.json",
            "timeout_summary": "cases/SOLR-09/actor-v2/evidence/replay-timeout/summary.json",
            "fresh_state_control_summary": "cases/SOLR-09/actor-v2/evidence/replay-fresh-state-control/summary.json",
            "lower_load_summary": "cases/SOLR-09/actor-v2/evidence/replay-low-load/summary.json",
        },
        "legacy_coarse": {
            "fault_trials": phase1["fault_trials"] + phase2["fault_trials"],
            "strict_injections": phase1["strict_injections"] + phase2["strict_injections"],
            "valid_trials_path_callsite_only": phase1["valid_trials"] + phase2["valid_trials"],
            "target_after_fault_path_callsite_only": phase1["target_after_fault"] + phase2["target_after_fault"],
            "target_exception_candidates": legacy_candidates,
            "elapsed_seconds": round(phase1["elapsed_seconds"] + phase2["elapsed_seconds"], 3),
            "identity_limitation": "ZK client/Overseer reader actor absent from selectors",
            "paused_at_atomic_checkpoint": legacy_pause["checkpoint_trial_count"] if legacy_pause else None,
            "next_jvm_started": legacy_pause["jvm_started"] if legacy_pause else None,
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
