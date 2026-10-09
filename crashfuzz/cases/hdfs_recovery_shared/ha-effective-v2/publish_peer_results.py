#!/usr/bin/env python3
"""Update only HDFS-29/30 result records from their audited peer80 receipt."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIVOT = HERE.parents[2]
RECEIPT = HERE / "audits" / "hdfs29-30-peer80-terminal.json"
RAW_AUDIT = HERE / "audits" / "hdfs29-30-peer80-raw-audit.json"
CURRENT_TEST = ("org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover"
                "#testFailoverRightBeforeCommitSynchronization")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    receipt = json.loads(RECEIPT.read_text())
    audit = json.loads(RAW_AUDIT.read_text())
    if (receipt["test"] != CURRENT_TEST or receipt["first_80_prefix_attempts"] != 203
            or receipt["prefix_exact_full_sequence"] != 80
            or receipt["audit_sha256"] != sha(RAW_AUDIT)
            or audit["errors"] or audit["completed_attempts"] < 203):
        raise RuntimeError("peer80 source/audit evidence invalid")
    total_seconds = round(receipt["healthy_junit_seconds"] +
                          receipt["prefix_fault_junit_seconds"], 3)
    for case in ("HDFS-29", "HDFS-30"):
        details = receipt["cases"][case]
        if (details["effective"] != details["goal"] or details["goal"] != 80
                or details["80th_effective_attempt"] != 203
                or details["last_eight_novelty"] is not False
                or details["target_exception_candidates"] != 0):
            raise RuntimeError(case + " lacks terminal effective evidence")
        path = PIVOT / "cases" / case / "result.json"
        result = json.loads(path.read_text())
        if result["case_id"] != case:
            raise RuntimeError("wrong case result path")
        prior = dict(result.get("ha_effective_campaign", {}))
        result["status"] = "quality_complete"
        result["cluster_test"] = CURRENT_TEST
        result["cluster_tests"] = list(dict.fromkeys(
            ["org.apache.hadoop.hdfs.server.datanode.TestBlockRecovery2#testRecoveryTimeout",
             CURRENT_TEST]))
        result["fault_trials"] = 203
        result["strict_injections"] = 80
        result["fully_applied_trials"] = 80
        result["target_after_fault"] = 80
        result["elapsed_seconds"] = total_seconds
        result["coverage_gain"] = details["production_coverage_gain"]["probes"]
        result["coverage_scope"] = "current_HA_original_JUnit_production_JaCoCo; historical_JUnits_separate"
        result["bug_mark"] = "none"
        result["new_bug"] = False
        result["target_reached"] = True
        result["target_exception_after_fault_trials"] = 0
        result["conclusion"] = (
            "First 80 strict same-owner postfault visits to the selected guard "
            "completed without its selected IOException. The last eight effective "
            "trials added no production method/branch or I/O family coverage, "
            "so the protocol did not extend this case to 128. This is a bounded "
            "negative result for this original JUnit, not a proof of absence of bugs.")
        result["evidence"] = (str(RECEIPT.relative_to(PIVOT)) + "; " +
                              str(RAW_AUDIT.relative_to(PIVOT)) +
                              "; raw per-trial JUnit/trace/JaCoCo on node1 under " +
                              str(HERE / "runs"))
        result["ha_effective_campaign"] = {
            **prior,
            "workload": CURRENT_TEST,
            "state": "quality_complete_for_case_at_first80_prefix",
            "scope": "first 203 HA attempts; subsequent shared HDFS-28 exploration excluded",
            "attempts": 203, "attempt_cap": 320, "effective_trials": 80,
            "effective_goal": 80, "exact_full_sequence": 80,
            "max_faults": 8, "selected_target_exceptions": 0,
            "healthy_seconds_shared": receipt["healthy_junit_seconds"],
            "fault_junit_seconds_shared": receipt["prefix_fault_junit_seconds"],
            "elapsed_seconds_shared": total_seconds,
            "first_80_prefix_completed_sha256": receipt["prefix_completed_sha256"],
            "terminal_receipt": str(RECEIPT.relative_to(PIVOT)),
            "independent_raw_audit": str(RAW_AUDIT.relative_to(PIVOT)),
            "independent_raw_audit_completed_prefix": receipt["audit_completed_attempts"],
            "independent_raw_audit_sha256": receipt["audit_sha256"],
            "independent_raw_audit_errors": 0,
            "last_eight_novelty": False,
            "last_eight_effective_attempts": details["last_eight_attempts"],
            "production_coverage_gain": details["production_coverage_gain"],
            "stop_reason": "per_case_effective_budget_met_without_extension",
            "snapshot_at_utc": datetime.now(timezone.utc).isoformat(),
            "separate_from_historical_v4_counts": True,
        }
        result["ha_effective_campaign"].pop("pending_queue", None)
        result["ha_effective_campaign"].pop("snapshot_path", None)
        result["ha_effective_campaign"].pop("checkpoint_sha256", None)
        if "quality_review" in result:
            result["quality_review"]["resolution"] = (
                "Actor-bound original HA JUnit reached 80 effective visits; "
                "the last-eight novelty gate did not extend the budget.")
        if case == "HDFS-30":
            result["historical_trial_count_scope"] = result.pop("trial_count_scope", None)
            result["historical_total_elapsed_seconds"] = result.pop("total_elapsed_seconds", None)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        temp.replace(path)
        print(json.dumps({"case": case, "status": result["status"],
                          "test": result["cluster_test"],
                          "attempts": result["fault_trials"],
                          "effective": result["target_after_fault"],
                          "seconds": result["elapsed_seconds"],
                          "bug_mark": result["bug_mark"]}, sort_keys=True))


if __name__ == "__main__":
    main()
