#!/usr/bin/env python3
"""Audit supplementary equal-branch HDFS-43 original-JUnit trials."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

from campaign import COVERAGE, GROUPS, SITES, atomic_json, checks, events

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE / "evidence"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=GROUPS, required=True)
    args = parser.parse_args()
    case_id = GROUPS[args.group][0]
    state = json.loads((EVIDENCE / "campaign-state.json").read_text())
    result_path = HERE / "equal-result.json"
    result = json.loads(result_path.read_text())
    budget = state["budget"]["max_trials"]
    if result["fault_trials"] < budget:
        raise SystemExit("Supplementary phase has not reached its trial budget")
    healthy = EVIDENCE / "healthy"
    healthy_manifest = json.loads((healthy / "manifest.json").read_text())
    healthy_trace = events(healthy / "runtime_trace.jsonl")
    if healthy_manifest["returncode"] != 0 or len(checks(healthy_trace, case_id)) != 4:
        raise SystemExit("Original equal-branch JUnit calibration changed")
    if any(r.get("caseId") == case_id and r["event"] == "TARGET_THROW"
           for r in healthy_trace):
        raise SystemExit("Original equal-branch JUnit has a target throw")

    outcomes = {site: {"equal": 0, "different": 0} for site in SITES[case_id]}
    for trial in result["trial_results"]:
        root = Path(trial["manifest"]).parent.parent
        attempts = [json.loads(p.read_text())["elapsed_seconds"]
                    for p in sorted(root.glob("attempt-*/manifest.json"))]
        if not attempts:
            raise SystemExit("Missing attempt manifest: " + str(root))
        trial["attempt_elapsed_seconds"] = attempts
        trial["elapsed_seconds"] = round(sum(attempts), 3)
        trial["target_exception_classification"] = (
            "candidate_needs_replay_source_review"
            if trial["valid_for_feedback"] and trial["target_exception_after_fault"]
            else "none")
        trial["bug_mark"] = trial["target_exception_classification"]
        if not trial["valid_for_feedback"]:
            continue
        trace = events(Path(trial["trace"]))
        applied = [r for r in trace if r["event"] == "FAULT_APPLIED"]
        if not applied:
            raise SystemExit("Valid trial lacks fault event: " + trial["trace"])
        for row in checks(trace, case_id):
            if row["seq"] <= applied[-1]["seq"]:
                continue
            outcomes[row["siteId"]]["equal" if row["equal"] else "different"] += 1

    candidate = any(t["bug_mark"] != "none" for t in result["trial_results"])
    result["bug_mark"] = "candidate_needs_replay_source_review" if candidate else "none"
    result["elapsed_seconds"] = round(
        healthy_manifest["elapsed_seconds"] +
        sum(t["elapsed_seconds"] for t in result["trial_results"]), 3)
    novelty = any(t["new_io_families"] or any(t["coverage_gain"].values())
                  for t in result["trial_results"][-8:])
    extension = novelty and budget < 128 and not candidate
    result["status"] = ("pending_candidate_replay_source_review" if candidate
                        else "pending_budget_extension" if extension
                        else "quality_complete_supplementary")
    result["extension_decision"] = {
        "last_chronological_trials": min(8, result["fault_trials"]),
        "new_production_coverage_or_stable_io_family": novelty,
        "next_budget_if_needed": {"max_trials": 128, "max_faults": 10} if extension else None,
        "budget_ceiling_reached": budget >= 128}
    result["healthy_target_branch_outcomes"] = {
        site: {"equal": sum(bool(r["equal"]) for r in checks(healthy_trace, case_id)
                            if r["siteId"] == site),
               "different": sum(not bool(r["equal"]) for r in checks(healthy_trace, case_id)
                                if r["siteId"] == site)}
        for site in SITES[case_id]}
    result["post_fault_target_branch_outcomes"] = outcomes
    result["coverage_gain_detail"] = {
        k: result["coverage"][k] - len(set(
            (healthy / ("covered_" + k + ".txt")).read_text().splitlines()))
        for k in COVERAGE}
    result["tested_sequence_depths"] = dict(sorted(Counter(
        len(t["sequence"]) for t in result["trial_results"]).items()))
    result["target_retaining_sequence_depths"] = dict(sorted(Counter(
        len(t["sequence"]) for t in result["trial_results"]
        if t["valid_for_feedback"]).items()))
    result["elapsed_seconds_semantics"] = "Healthy equal-branch JUnit plus all actual fault-trial JUnit attempts."
    result["supplementary_phase"] = "same_length_idempotence_original_junit"
    result["source_review"] = (
        "FSDirTruncateOp.truncate returns an idempotent result when a second request "
        "matches the length already being truncated. The unchanged TestFileTruncate#"
        "testMultipleTruncate reaches that equal branch four times and never throws "
        "AlreadyBeingCreatedException. A post-fault target throw is a candidate only; "
        "its requested and in-progress lengths and recovery state need replay and review.")
    result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_json(result_path, result)

    fields = ("trial", "attempts", "faults", "last_marker", "last_source", "last_ordinal",
              "exact_order_applied", "target_after_fault", "post_fault_target_checks",
              "target_exception_after_fault", "target_exception_classification",
              "junit_exit", "elapsed_seconds", "new_methods", "new_branches",
              "new_probes", "new_io_families", "manifest")
    temp = HERE / "trial-ledger.csv.tmp"
    with temp.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, trial in enumerate(result["trial_results"], 1):
            last = trial["sequence"][-1]
            writer.writerow({
                "trial": index, "attempts": len(trial["attempt_elapsed_seconds"]),
                "faults": len(trial["sequence"]), "last_marker": last["marker"],
                "last_source": last["sourceKey"], "last_ordinal": last["hitOrdinal"],
                "exact_order_applied": trial["exact_order_applied"],
                "target_after_fault": trial["target_after_fault"],
                "post_fault_target_checks": trial["post_fault_target_checks"],
                "target_exception_after_fault": trial["target_exception_after_fault"],
                "target_exception_classification": trial["target_exception_classification"],
                "junit_exit": trial["junit_exit"], "elapsed_seconds": trial["elapsed_seconds"],
                "new_methods": trial["coverage_gain"]["methods"],
                "new_branches": trial["coverage_gain"]["branch_counts"],
                "new_probes": trial["coverage_gain"]["probes"],
                "new_io_families": trial["new_io_families"],
                "manifest": trial["manifest"]})
    temp.replace(HERE / "trial-ledger.csv")

    readme = (
        "# HDFS-43 supplementary equal-branch campaign\n\n"
        "Original Hadoop 3.4.3 `TestFileTruncate#testMultipleTruncate` is the workload. "
        "Its healthy run has four exact `FSDirTruncateOp.truncate#L113-IFNE` visits, "
        "all equal, and zero target exceptions.\n\n"
        f"The supplementary phase completed {result['fault_trials']} trials in "
        f"{result['elapsed_seconds']:.3f} attributed JUnit seconds; "
        f"{result['strict_injections']} strict injections and "
        f"{result['target_after_fault']} target-retaining trials. "
        f"Post-fault target exceptions: {result['target_exception_after_fault']}; "
        f"bug mark: `{result['bug_mark']}`; status: `{result['status']}`.\n\n"
        f"Post-fault equal/different branch outcomes: `{json.dumps(outcomes, sort_keys=True)}`. "
        f"Coverage gain: `{json.dumps(result['coverage_gain_detail'], sort_keys=True)}`.\n\n"
        "This phase has its own healthy seed, atomic checkpoint, raw trace, JaCoCo "
        "coverage, and per-trial ledger. It supplements the HDFS-43 checklist entry; "
        "it does not count as another completed check. The same case-local ASM overlay "
        "and unchanged original MiniDFSCluster JUnit are used. No GraphChecker graph, "
        "closure, or Docker workload is involved.\n\n"
        f"Source review: {result['source_review']}\n\n"
        "Evidence: [result](equal-result.json), [trial ledger](trial-ledger.csv), "
        "[checkpoint](evidence/campaign-state.json), "
        "[healthy manifest](evidence/healthy/manifest.json).\n")
    temp = HERE / "README.md.tmp"
    temp.write_text(readme)
    temp.replace(HERE / "README.md")
    atomic_json(EVIDENCE / "campaign-summary.json", {
        "case_id": case_id, "phase": "equal_branch_supplementary",
        "fault_trials": result["fault_trials"], "strict_injections": result["strict_injections"],
        "target_after_fault": result["target_after_fault"],
        "target_exception_after_fault": result["target_exception_after_fault"],
        "bug_mark": result["bug_mark"], "status": result["status"],
        "extension_decision": result["extension_decision"]})
    print(json.dumps({"case_id": case_id, "phase": "equal_branch_supplementary",
                      "trials": result["fault_trials"], "status": result["status"],
                      "bug_mark": result["bug_mark"]}))


if __name__ == "__main__":
    main()
