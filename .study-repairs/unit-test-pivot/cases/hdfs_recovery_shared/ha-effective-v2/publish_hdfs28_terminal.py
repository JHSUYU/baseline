#!/usr/bin/env python3
"""Publish HDFS-28 only after both original-JUnit ledgers are audited."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIVOT = HERE.parents[2]
ALT = HERE / "fallback28-junit-v1"
CASE = "HDFS-28"
SHARED_TEST = ("org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover"
               "#testFailoverRightBeforeCommitSynchronization")
ALT_TEST = ("org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover"
            "#testLeaseRecoveryAfterFailover")
HISTORICAL_TEST = ("org.apache.hadoop.hdfs.server.datanode.TestBlockRecovery2"
                   "#testRecoveryTimeout")
METRICS = ("probes", "methods", "branch_counts")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(PIVOT))


def ledger(state_path: Path, audit_path: Path, receipt_path: Path,
           test: str, attempts: int, effective: int, reason: str) -> tuple[dict, dict, dict]:
    state = json.loads(state_path.read_text())
    audit = json.loads(audit_path.read_text())
    receipt = json.loads(receipt_path.read_text())
    strict = sum(bool(t["exact_order_applied"]) for t in state["completed"])
    valid = sum(bool(t["exact_order_applied"] and
                     t["post_fault_target_checks"][CASE]) for t in state["completed"])
    candidates = sum(bool(t["target_exceptions_after_fault"][CASE])
                     for t in state["completed"])
    if (state.get("test") != test or len(state["completed"]) != attempts or
            state["active"] is not None or state["stop_reason"] != reason or
            valid != effective or candidates or
            audit["errors"] or audit["completed_attempts"] != attempts or
            audit["effective_by_case"][CASE] != effective or
            audit["strict_applied"] != strict or
            audit["target_exception_candidates"] or
            audit["raw_files_retained"] is not True or
            audit["checkpoint_sha256"] != sha(state_path) or
            receipt["checkpoint_sha256"] != sha(state_path) or
            receipt["raw_audit_sha256"] != sha(audit_path) or
            receipt.get("attempts", attempts) != attempts or
            receipt.get("effective_hdfs28", effective) != effective):
        raise RuntimeError("terminal ledger, raw audit, and archive disagree: " + test)
    return state, audit, receipt


def main() -> None:
    shared_state_path = HERE / "terminal-node1-checkpoint.json"
    shared_audit_path = HERE / "terminal-node1-raw-audit.json"
    shared_receipt_path = HERE / "shared-terminal-archive-receipt.json"
    alt_state_path = ALT / "terminal-node2-checkpoint.json"
    alt_audit_path = ALT / "terminal-node2-raw-audit.json"
    alt_receipt_path = ALT / "terminal-archive-receipt.json"
    shared, shared_audit, shared_receipt = ledger(
        shared_state_path, shared_audit_path, shared_receipt_path,
        SHARED_TEST, 512, 49, "attempt_cap_inconclusive")
    alternate, alt_audit, alt_receipt = ledger(
        alt_state_path, alt_audit_path, alt_receipt_path,
        ALT_TEST, 395, 80, "effective_budget_met_pending_independent_audit")
    if (sha(HERE / "campaign.py") !=
            "824df96b2fbbcfeb2d29d444443a837f414d183f90e28fdf2789c8a07a40b93b" or
            sha(HERE / "run_original.py") !=
            "113bda1971e27d9d15eb4d71a54f914d5d1b2c37e0373bdc89af907e8b3a9188" or
            sha(ALT / "file_successor_v4.py") !=
            "d45c88f9473ac19b28191c175f664a03f5c6a78124e3d412892bb023716ab61a" or
            sha(HERE / "shared-terminal-raw.tar.zst") != shared_receipt["archive_sha256"] or
            sha(HERE / "shared-terminal-raw-manifest.json") != shared_receipt["manifest_sha256"] or
            sha(ALT / "terminal-raw.tar.zst") != alt_receipt["archive_sha256"] or
            sha(ALT / "terminal-raw-manifest.json") != alt_receipt["manifest_sha256"]):
        raise RuntimeError("source or dual-host archive provenance changed")
    shared_strict = sum(bool(t["exact_order_applied"]) for t in shared["completed"])
    alt_strict = sum(bool(t["exact_order_applied"]) for t in alternate["completed"])
    if (shared["attempt_cap"] != 512 or alternate["attempt_cap"] != 512 or
            shared_strict + alt_strict != 246 or
            shared["max_faults"] != 8 or alternate["max_faults"] != 8 or
            len(shared["queue"]) != 393 or len(alternate["queue"]) != 98 or
            alternate["extensions"][CASE]["target_related_or_stable_io_novelty"] is not False or
            set(t["id"] for t in shared["completed"]) &
            set(t["id"] for t in alternate["completed"])):
        raise RuntimeError("independent ledgers or budget boundary changed")
    combined_coverage = {}
    for metric in METRICS:
        healthy = set(shared["healthy_coverage"][metric]) | set(alternate["healthy_coverage"][metric])
        final = set(shared["coverage"][CASE][metric]) | set(alternate["coverage"][CASE][metric])
        combined_coverage[metric] = len(final - healthy)
    shared_seconds = round(sum(t["elapsed_seconds"] for t in shared["completed"]), 3)
    alt_seconds = round(sum(t["elapsed_seconds"] for t in alternate["completed"]), 3)
    shared_healthy = round(sum(h["seconds"] for h in shared["healthy"]), 3)
    alt_healthy = round(sum(h["seconds"] for h in alternate["healthy"]), 3)
    total_seconds = round(shared_seconds + alt_seconds + shared_healthy + alt_healthy, 3)
    result_path = PIVOT / "cases" / CASE / "result.json"
    result = json.loads(result_path.read_text())
    if result["case_id"] != CASE:
        raise RuntimeError("wrong case result")
    result.update({
        "status": "quality_complete", "bug_mark": "none", "new_bug": False,
        "target_reached": True, "target_exception_after_fault_trials": 0,
        "cluster_test": ALT_TEST,
        "cluster_tests": [HISTORICAL_TEST, SHARED_TEST, ALT_TEST],
        "fault_trials": 907, "strict_injections": 246,
        "fully_applied_trials": 246, "target_after_fault": 129,
        "elapsed_seconds": total_seconds, "coverage_gain": combined_coverage["probes"],
        "coverage_scope": "two_current_original_HA_JUnit_production_JaCoCo_union; historical_TestBlockRecovery2_excluded",
        "methodology": "original_junit_case_local_asm_jacoco_graph_free_actor_bound",
        "conclusion": (
            "Two independent original HA JUnit workloads reached the same selected "
            "HDFS-28 guard after exact physical-DataNode/recovery-root fault sequences "
            "129 times without the selected IOException. The shared workload stopped "
            "at 512 attempts with 49 effective visits and 393 queued plans, while the "
            "alternate stopped naturally at 80 effective visits. Their aggregate met "
            "the prespecified conditional 128 target; both ledgers tested depth at "
            "most eight. This is a bounded negative result, not proof of bug absence."),
        "evidence": (rel(HERE / "audits" / "hdfs28-shared-terminal-review.md") + "; " +
                     rel(ALT / "terminal-alternate-review.md") + "; " +
                     rel(HERE / "audits" / "hdfs28-shared-archive-mirror-receipt.json") + "; " +
                     rel(ALT / "terminal-archive-mirror-receipt.json") + "; " +
                     "raw JUnit/trace/JaCoCo archived on node0 and source nodes"),
    })
    result["ha_effective_campaign"] = {
        "workload": SHARED_TEST, "state": "attempt_cap_inconclusive_individual",
        "attempts": 512, "attempt_cap": 512, "effective_trials": 49,
        "effective_goal": 80, "exact_full_sequence": 125,
        "max_faults": 8, "selected_target_exceptions": 0,
        "pending_queue": 393, "stop_reason": "attempt_cap_inconclusive",
        "healthy_seconds": shared_healthy, "fault_junit_seconds": shared_seconds,
        "production_coverage_gain": {m: len(set(shared["coverage"][CASE][m]) -
                                           set(shared["healthy_coverage"][m])) for m in METRICS},
        "checkpoint_sha256": sha(shared_state_path),
        "independent_raw_audit_sha256": sha(shared_audit_path),
        "independent_raw_audit_errors": 0,
        "raw_archive_sha256": shared_receipt["archive_sha256"],
        "raw_files": shared_receipt["files"],
        "terminal_review": rel(HERE / "audits" / "hdfs28-shared-terminal-review.md"),
    }
    result["alternate_effective_campaign"] = {
        "workload": ALT_TEST, "state": "effective_budget_met_without_extension",
        "attempts": 395, "attempt_cap": 512, "effective_trials": 80,
        "effective_goal": 80, "exact_full_sequence": 121,
        "max_faults": 8, "selected_target_exceptions": 0,
        "pending_queue": 98,
        "stop_reason": "effective_budget_met_pending_independent_audit",
        "last_eight_novelty": False,
        "healthy_seconds": alt_healthy, "fault_junit_seconds": alt_seconds,
        "production_coverage_gain": {m: len(set(alternate["coverage"][CASE][m]) -
                                           set(alternate["healthy_coverage"][m])) for m in METRICS},
        "checkpoint_sha256": sha(alt_state_path),
        "independent_raw_audit_sha256": sha(alt_audit_path),
        "independent_raw_audit_errors": 0,
        "raw_archive_sha256": alt_receipt["archive_sha256"],
        "raw_files": alt_receipt["files"],
        "terminal_review": rel(ALT / "terminal-alternate-review.md"),
    }
    result["aggregate_effective_campaign"] = {
        "same_static_check": CASE,
        "two_original_JUnit_ledgers_kept_separate": True,
        "selected_attempts": 907, "exact_full_sequences": 246,
        "effective_trials": 129, "conditional_effective_goal": 128,
        "conditional_goal_met": True,
        "maximum_sequence_depth_tested": 8,
        "depth_ten_not_claimed": True,
        "target_exception_candidates": 0,
        "production_coverage_union_gain": combined_coverage,
        "healthy_plus_fault_junit_seconds": total_seconds,
        "historical_TestBlockRecovery2_trials_excluded": True,
    }
    if "quality_review" in result:
        result["quality_review"]["resolution"] = (
            "Two independently audited actor-bound original HA JUnit ledgers yielded "
            "129 effective visits to the same static guard; the historical "
            "TestBlockRecovery2 counters are excluded from the current denominator.")
    encoded_result = json.dumps(result, indent=2, sort_keys=True) + "\n"
    pending = result_path.with_name(result_path.name + ".tmp")
    pending.write_text(encoded_result)
    pending.replace(result_path)
    print(json.dumps({"case": CASE, "status": result["status"],
                      "attempts": result["fault_trials"],
                      "strict": result["strict_injections"],
                      "effective": result["target_after_fault"],
                      "junit_seconds": total_seconds,
                      "coverage_probes": result["coverage_gain"],
                      "bug_mark": result["bug_mark"]}, sort_keys=True))


if __name__ == "__main__":
    main()
