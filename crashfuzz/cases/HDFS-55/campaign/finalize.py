#!/usr/bin/env python3
"""Archive exact-plan evidence and atomically summarize HDFS-55 results."""

import hashlib
import json
from pathlib import Path
import tarfile
import campaign

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
STATE = HERE / "state.json"
ARCHIVE = HERE / "exact-plan-evidence.tar.gz"
RESULT = CASE / "result.json"
QUALIFICATION = HERE / "qualification.json"
RAW_FILES = ("manifest.json", "junit.log", "jacoco.exec", "covered_probes.txt",
             "covered_methods.txt", "covered_branch_counts.txt", "covered_lines.txt")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def qualified_pair(state):
    if not QUALIFICATION.is_file():
        return None
    proposed = json.loads(QUALIFICATION.read_text())
    trial = next((row for row in state["trials"]
                  if row["id"] == proposed["exact_trial"]), None)
    if trial is None or not (trial["harness_complete"] and trial["fully_applied"]
                             and trial["in_plan_order"] and trial["identity_coherent"]
                             and trial["target_after_final_fault"]
                             and trial["operation_failed"]):
        raise SystemExit("qualification lacks ordered, target-retaining Balancer failure")
    fixed = HERE / "fixed-replays" / proposed["fixed_replay_id"]
    manifest = json.loads((fixed / "manifest.json").read_text())
    log = (fixed / "junit.log").read_text(errors="replace")
    if (manifest["returncode"] != 0 or "CONTROL original_junit_failures=0" not in log
            or "CASE55 balancer_key_cache_cleared=true" not in log
            or "CASE55 fault_matched=" not in log
            or "Successfully moved blk_" not in log
            or not proposed.get("source_audit")):
        raise SystemExit("fixed replay or source audit does not establish the known bug")
    return proposed


def main():
    state = json.loads(STATE.read_text())
    if state["status"] not in ("trial_budget_exhausted", "queue_exhausted",
                                "time_budget_exhausted"):
        raise SystemExit("campaign has not reached a budget or queue stop")
    pair = qualified_pair(state)
    selected = {STATE, HERE / "trial-ledger.csv"}
    for row in state["trials"]:
        for name in RAW_FILES:
            path = HERE / "runs" / row["id"] / name
            if path.is_file():
                selected.add(path)
        selected.add(HERE / "plans" / ("p" + "_".join(map(str, row["sequence"])) + ".tsv"))
    for name in RAW_FILES:
        path = HERE / "harness-timeout/p3" / name
        if path.is_file():
            selected.add(path)
    if pair:
        selected.add(QUALIFICATION)
        for name in RAW_FILES:
            path = HERE / "fixed-replays" / pair["fixed_replay_id"] / name
            if path.is_file():
                selected.add(path)
    with tarfile.open(ARCHIVE, "w:gz") as archive:
        for path in sorted(selected):
            archive.add(path, arcname=str(path.relative_to(CASE)))

    completed = [row for row in state["trials"] if row.get("harness_complete")]
    full = [row for row in completed if row["fully_applied"]]
    target = [row for row in full if row["target_after_final_fault"]]
    candidates = [row for row in state["trials"] if row["oracle_candidate"]]
    previous = json.loads(RESULT.read_text())
    assert previous["fault_policy"].startswith("All observed Balancer outbound")
    differential_seconds = sum(item["elapsed_seconds"]
                               for item in previous["known_bug_reproduction"].values())
    exact_seconds = round(sum(row["elapsed_seconds"] for row in state["trials"]), 3)
    admitted_coverage = campaign.cumulative_coverage(state)
    healthy_coverage = {kind: campaign.ids(campaign.HEALTHY, kind)
                        for kind in campaign.KINDS}
    previous.setdefault("stateful_control_coverage_gain", previous["coverage_gain"])
    previous.update({
        "status": ("quality_complete_known_HDFS-17899" if pair else
                   "exact_fuzz_budget_complete_synthetic_control"),
        "bug_mark": ("known_HDFS-17899_reproduced" if pair else
                     "known_HDFS-17899_synthetic_control"),
        "new_bug": False,
        "coverage_gain": {
            "probes": len(admitted_coverage["probes"] - healthy_coverage["probes"]),
            "production_methods": len(admitted_coverage["methods"] - healthy_coverage["methods"]),
            "branch_count_slots": len(admitted_coverage["branch_counts"]
                                      - healthy_coverage["branch_counts"]),
        },
        "coverage_gain_provenance": (
            "Cumulative complete ordered exact-plan trials retaining one manager/key "
            "and the target after final fault; healthy seed subtracted. "
            "Stateful synthetic control gain is separate."),
        "fault_trials": 1 + len(state["trials"]),
        "fully_applied_trials": 1 + len(full),
        "target_after_fault": 1 + len(target),
        "elapsed_seconds": round(differential_seconds + exact_seconds, 3),
        "stateful_differential_trial_count": 1,
        "stateful_differential_injected_events": previous["injected_fault_events"],
        "stateful_differential_elapsed_seconds": round(differential_seconds, 3),
        "stateful_differential_limitation": (
            "Its first injected event followed a fresh KeyManager key fetch "
            "(refresh=true); this calibrates clear/retry response only."),
        "detection_qualification": (pair if pair else
            "No ordered exact cached-reuse Balancer failure with a passing fixed "
            "replay has been source-audited; the known-bug label remains synthetic control."),
        "exact_plan_campaign_status": state["status"],
        "exact_plan_campaign": {
            "fault_policy": "ordered outbound SASL ordinals, cached-reuse predicate, same manager/key ID",
            "status": state["status"], "budget": state["budget"],
            "fault_trials_attempted": len(state["trials"]),
            "complete_trials": len(completed),
            "harness_incomplete_trials": [row["id"] for row in state["trials"]
                                          if not row.get("harness_complete")],
            "fully_applied_trials": len(full),
            "target_after_final_fault_trials": len(target),
            "oracle_candidates": [row["id"] for row in candidates],
            "matched_fault_events": sum(row["matched_fault_count"] for row in state["trials"]),
            "applied_fault_events": sum(row["applied_fault_count"] for row in state["trials"]),
            "planned_fault_events": sum(row["planned_fault_count"] for row in state["trials"]),
            "elapsed_seconds": exact_seconds,
            "checkpoint": "cases/HDFS-55/campaign/state.json",
            "trial_ledger": "cases/HDFS-55/campaign/trial-ledger.csv",
            "evidence_archive": "cases/HDFS-55/campaign/exact-plan-evidence.tar.gz",
            "evidence_archive_sha256": sha(ARCHIVE),
            "evidence_archive_bytes": ARCHIVE.stat().st_size,
            "trials": [{key: row.get(key) for key in (
                "id", "sequence", "result", "planned_fault_count", "matched_fault_count",
                "applied_fault_count", "matched_observed_order", "applied_observed_order",
                "in_plan_order", "identity_coherent", "fully_applied", "target_after_final_fault",
                "target_reuse_after_final_fault", "operation_failed", "oracle_candidate",
                "successful_block_moves", "elapsed_seconds", "coverage_complete",
                "admitted_for_coverage_feedback", "coverage_gain_vs_cumulative",
                "matched_runtime_identity", "timeout_evidence")}
                for row in state["trials"]],
        },
    })
    atomic(RESULT, previous)
    print(json.dumps({key: previous[key] for key in
                      ("case_id", "status", "bug_mark", "fault_trials",
                       "fully_applied_trials", "target_after_fault", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
