#!/usr/bin/env python3
"""Reconcile terminal ZK03 phase audits into its shared checklist result."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


CASE = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
RESULT = CASE / "result.json"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    old = read(RESULT)
    supplement = read(CASE / "preio-supplement/evidence/audit-summary.json")
    supplement_stats = read(CASE / "preio-supplement/evidence/sequence-stats.json")
    healthy = read(HERE / "evidence/health-calibration.json")
    pilot = read(HERE / "evidence/pilot-feedback-audit.json")
    child = read(HERE / "evidence/child-independent-audit.json")
    deep = read(HERE / "evidence/deep-independent-audit.json")
    receipt = read(HERE / "evidence/deep-archive-receipt.json")
    if old["case_id"] != "ZOOKEEPER-03" or \
            old["all_stages_selected_fault_trials"] != 713 or \
            old["all_stages_elapsed_seconds"] != 3055.906 or \
            old["post_fault_target_reach_trials"] != 64 or \
            supplement["supplement_selected"] != 63 or \
            supplement_stats["fully_applied"] != 62 or \
            supplement["supplement_effective"] != 8 or \
            healthy["status"] != "healthy_target_calibrated" or \
            pilot["selected"] != 10 or pilot["target_retaining"] != 3 or \
            child["selected"] != 13 or child["target_retaining"] != 7 or \
            deep["source_pilot_effective"] != 3 or \
            deep["source_child_effective"] != 7 or \
            deep["deep_selected"] > 256 or \
            deep["status"] not in (
                "effective_budget_80_reached",
                "selected_cap_before_effective_budget",
                "queue_exhausted_before_effective_budget"):
        raise RuntimeError("nonterminal or changed ZK03 denominator")
    if any(stage["selected_target_throws"] for stage in (supplement, pilot, child, deep)):
        raise RuntimeError("selected target throw requires separate replay/source review")
    if receipt["archive_sha256"] != sha(HERE / "evidence/zk03-upgrade-deep-raw.tar.gz"):
        raise RuntimeError("deep archive SHA mismatch")
    new_seed_effective = deep["new_seed_total_effective"]
    if new_seed_effective != 3 + 7 + deep["deep_target_retaining"]:
        raise RuntimeError("new seed effective denominator changed")
    complete = (deep["status"] == "effective_budget_80_reached" and
                new_seed_effective >= 80)
    old["methodology"] = (
        "original_embedded_cluster_junit_actor_bound_io_exception_"
        "and_asm_source_line_feedback")
    old["trial_results_scope"] = (
        "separate_original_junit_and_fault_family_denominators; "
        "per_stage_effective_budget_80")
    old["budget_denominator"] = (
        "Each original JUnit/fault family has its own 80 effective trials; "
        "a trial is effective only if every ordered fault applies and the "
        "same raw-session/leader/owner target follows the final fault. "
        "The SessionUpgrade seed combines only its own pilot, child, and "
        "deep stages.")
    old["fault_model"] = (
        "Ordered IOException at observed, actor-bound socket I/O; "
        "the QuorumTest post-response fault family is separately counted.")
    old["cluster_test"] = (
        "org.apache.zookeeper.test.QuorumTest#testSessionMoved; "
        "org.apache.zookeeper.test.QuorumTest#testSessionMovedWithMultiOp; "
        "org.apache.zookeeper.test.SessionUpgradeTest#testUpgradeWithEphemeralOnFollower")
    old["pre_io_supplement"] = {
        "status": supplement["status"], "selected_attempts": 63,
        "fully_applied": supplement_stats["fully_applied"],
        "effective": supplement["supplement_effective"],
        "selected_target_throws": 0,
        "elapsed_seconds": supplement["supplement_elapsed_seconds"],
        "raw_archive": "preio-supplement/evidence/zk03-preio-supplement-raw.tar.gz",
        "raw_archive_sha256": sha(CASE / "preio-supplement/evidence/zk03-preio-supplement-raw.tar.gz"),
        "audit": "preio-supplement/evidence/audit-summary.json",
        "sequence_stats": "preio-supplement/evidence/sequence-stats.json",
        "original_junit": "org.apache.zookeeper.test.QuorumTest#testSessionMoved",
        "denominator_note": "separate from historical 480-selected/37-effective pre-I/O stage"}
    old["session_upgrade_original_junit_extension"] = {
        "status": deep["status"],
        "original_junit": "org.apache.zookeeper.test.SessionUpgradeTest#testUpgradeWithEphemeralOnFollower",
        "original_source_commit": "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae",
        "cluster_nodes": 5, "healthy_runs": 2,
        "healthy_global_target_guards_per_run": [
            row["global_target_guards"] for row in healthy["audits"]],
        "expected_local_tracker_guards_ignored_per_run": [
            row["expected_local_tracker_guards_ignored"]
            for row in healthy["audits"]],
        "healthy_elapsed_seconds": round(sum(row["elapsed_seconds"]
                                             for row in healthy["audits"]), 3),
        "pilot_selected": pilot["selected"],
        "pilot_strict_injections": pilot["strict_injections"],
        "pilot_target_retaining": pilot["target_retaining"],
        "pilot_elapsed_seconds": pilot["sum_elapsed_seconds"],
        "child_selected": child["selected"],
        "child_strict_injections": child["strict_two_fault_injections"],
        "child_target_retaining": child["target_retaining"],
        "child_elapsed_seconds": child["sum_elapsed_seconds"],
        "deep_selected": deep["deep_selected"],
        "deep_strict_injections": deep["deep_strict_injections"],
        "deep_target_retaining": deep["deep_target_retaining"],
        "deep_elapsed_seconds": deep["sum_elapsed_seconds"],
        "seed_effective_budget": 80, "seed_effective": new_seed_effective,
        "max_faults": 8, "deep_selected_cap": 256,
        "selected_target_throws": 0,
        "production_line_gain_by_phase": {
            "pilot": pilot["new_target_coverage_lines"],
            "child": child["new_target_coverage_lines"],
            "deep": deep["deep_new_target_coverage_lines"]},
        "target_window_io_family_gain_by_phase": {
            "pilot": pilot["new_target_io_families"],
            "child": child["new_target_io_families"],
            "deep": deep["deep_new_target_io_families"]},
        "raw_health": "session-upgrade-seed/evidence/zk03-upgrade-health-evidence.tar.gz",
        "raw_pilot": "session-upgrade-seed/evidence/zk03-upgrade-pilot-raw.tar.gz",
        "raw_child": "session-upgrade-seed/evidence/zk03-upgrade-recovery-children-raw.tar.gz",
        "raw_deep": "session-upgrade-seed/evidence/zk03-upgrade-deep-raw.tar.gz",
        "raw_deep_sha256": receipt["archive_sha256"],
        "independent_audit": "session-upgrade-seed/evidence/deep-independent-audit.json",
        "method_note": "session-upgrade-seed/README.md",
        "graphchecker_runtime_dependency": False,
        "denominator_note": "new original JUnit seed; not pooled with older QuorumTest stages"}
    old["frontier_audit"]["pre_io_pending_before_supplement"] = 63
    old["frontier_audit"]["pre_io_pending_ordered_plans"] = 0
    old["frontier_audit"]["pre_io_status"] = "queue_exhausted_after_supplement"
    old["frontier_audit"]["historical_audit_scope"] = "snapshot before the 63-plan supplement"
    old["io_family_gain"].update({
        "session_upgrade_pilot": pilot["new_target_io_families"],
        "session_upgrade_child": child["new_target_io_families"],
        "session_upgrade_deep": deep["deep_new_target_io_families"]})
    old["coverage_gain_scope"] = (
        "Top-level legacy value belongs to the historical post-response "
        "stage; SessionUpgrade production-line gains are reported per phase.")
    old["all_stages_selected_fault_trials"] = 713 + 63 + 10 + 13 + deep["deep_selected"]
    old["all_stages_elapsed_seconds"] = round(
        3055.906 + supplement["supplement_elapsed_seconds"] +
        pilot["sum_elapsed_seconds"] + child["sum_elapsed_seconds"] +
        deep["sum_elapsed_seconds"], 3)
    old["total_elapsed_seconds"] = old["all_stages_elapsed_seconds"]
    old["elapsed_seconds"] = old["all_stages_elapsed_seconds"]
    old["elapsed_measurement"] = (
        "sum of original-JUnit elapsed times in phase audits; excludes shared-lock waits "
        "and setup/archival outside measured JUnit processes")
    old["fault_trials"] = old["all_stages_selected_fault_trials"]
    old["strict_injections"] = (663 + 7 + 38 + 62 + 10 + 13 +
                                deep["deep_strict_injections"])
    old["fully_applied_trials"] = old["strict_injections"]
    old["post_fault_target_reach_trials"] = 64 + 22 + 8 + new_seed_effective
    old["target_after_fault"] = old["post_fault_target_reach_trials"]
    old["selected_target_throw_events"] = 0
    old["status"] = "quality_complete" if complete else "inconclusive_budget_unmet"
    old["quality_complete"] = complete
    old["campaign_finished"] = True
    old["stop_reason"] = (
        "session_upgrade_effective_budget_80_reached" if complete else
        "session_upgrade_" + deep["status"])
    old["reason"] = (
        f"All 63 pending pre-I/O plans were tested (8 target-retaining); the independent "
        f"SessionUpgrade seed reached {new_seed_effective}/80 effective actor-bound "
        f"postfault target trials in {10 + 13 + deep['deep_selected']} selected runs. "
        f"No selected target SessionExpiredException occurred. " +
        ("The defined seed budget was met." if complete else
         "The effective budget remains unmet under the bounded observed-I/O search."))
    old["limitations"] = [
        item.replace("The two fault families", "The historical two QuorumTest fault families")
        for item in old["limitations"]]
    old["limitations"].append(
        "The SessionUpgrade seed uses only observed actor-bound socket I/O and ASM "
        "source-line feedback in selected production methods; it does not enumerate "
        "all possible distributed schedules or unbound startup I/O.")
    output = json.dumps(old, sort_keys=True, indent=2) + "\n"
    print(json.dumps({key: old[key] for key in
          ("status", "fault_trials", "strict_injections",
           "post_fault_target_reach_trials", "all_stages_elapsed_seconds",
           "stop_reason")}, sort_keys=True))
    if args.write:
        RESULT.write_text(output)


if __name__ == "__main__":
    main()
