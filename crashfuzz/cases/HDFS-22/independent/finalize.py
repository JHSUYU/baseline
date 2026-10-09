#!/usr/bin/env python3
"""Freeze five separate storage-version checklist rows from shared JUnit runs."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path

from campaign import CASES, COVERAGE, EVIDENCE, HEALTHY, atomic_json


def main() -> None:
    results = {case_id: json.loads((case["directory"] / "result.json").read_text())
               for case_id, case in CASES.items()}
    budgets = {result["budget"]["max_trials"] for result in results.values()}
    if len(budgets) != 1:
        raise SystemExit("Shared campaign budgets diverged")
    trial_budget = budgets.pop()
    if any(result["fault_trials"] < trial_budget for result in results.values()
           if result["target_reached"]):
        raise SystemExit("Shared campaign budget not yet complete")
    any_candidate = any(result["bug_mark"] != "none" for result in results.values())
    novelty = any(trial["new_io_families"] or any(trial["coverage_gain"].values())
                  for result in results.values() for trial in result["trial_results"][-8:])
    extension = not any_candidate and novelty and trial_budget < 128
    summaries = {}
    for case_id, case in CASES.items():
        result = results[case_id]
        result["status"] = ("target_not_reached_in_original_junit" if not result["target_reached"]
                            else "pending_candidate_replay_source_review" if result["bug_mark"] != "none"
                            else "pending_budget_extension" if extension else "quality_complete")
        result["extension_decision"] = {
            "shared_near_limit_window_trials": min(8, result["fault_trials"]),
            "new_production_coverage_or_io_family_on_either_check": novelty,
            "next_budget_if_needed": {"max_trials": 128, "max_faults": 10} if extension else None,
            "budget_ceiling_reached": trial_budget >= 128,
        }
        result["elapsed_seconds_semantics"] = (
            "Shared original JUnit: one healthy duration plus each actual shared fault-trial JUnit "
            "duration; the same run is attributed separately to all five checks, not summed five times.")
        result["coverage_gain_detail"] = {
            name: result["coverage"][name] - len(set(
                (HEALTHY / ("covered_" + name + ".txt")).read_text().splitlines()))
            for name in COVERAGE}
        result["coverage_metric_note"] = (
            "JaCoCo probe IDs are exact; branch_counts uses per-method covered branch counts "
            "as monotone feedback rather than individual branch outcomes; generated Mockito classes excluded.")
        result["source_review"] = (
            "TestDFSStartupVersions.testVersions intentionally starts DataNodes with 20 VERSION "
            "variants. The selected storage guards compare VERSION namespaceID, blockpoolID, "
            "clusterID, or CTime with NameNode NamespaceInfo. The original test expects many "
            "incompatibilities and checks whether each DataNode starts; a matching version "
            "rejection alone is not a new bug.")
        result["candidate_semantic_classification"] = {
            "label": "simple_storage_version_compatibility_guard",
            "assessment": (
                "DataNode on-disk VERSION fields are compared directly with NameNode "
                "NamespaceInfo. This is a simple cross-component compatibility check; "
                "the source and original test do not show a multi-hop coordination chain."),
            "basis": case["code"]}
        result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_json(case["directory"] / "result.json", result)
        evidence_prefix = "independent" if case_id == "HDFS-22" else "../HDFS-22/independent"
        detail = result["coverage_gain_detail"]
        readme = (
            f"# {case_id} independent original-JUnit fault campaign\n\n"
            f"- Target: `{result['target_source_file']}:{result['target_source_line']}` "
            f"in `{result['target_function']}`; guard `{result['target_code']}`.\n"
            f"- Workload: unchanged Hadoop 3.4.3 "
            f"`{result['cluster_test']}` (20 VERSION variants, MiniDFSCluster).\n"
            f"- Healthy run: {result['healthy']['target_checks']} exact target checks; "
            f"{result['healthy']['target_exceptions']} target IOExceptions.\n"
            f"- Fault campaign: {result['fault_trials']} trials in "
            f"{result['elapsed_seconds']:.3f} attributed JUnit seconds; "
            f"{result['strict_injections']} exact ordered injections; "
            f"{result['target_after_fault']} target-retaining trials.\n"
            f"- Post-fault target IOExceptions: {result['target_exception_after_fault']}; "
            f"{result['expected_guard_response_trials']} trials matched the expected "
            f"incompatible VERSION guard response. New-bug mark: `{result['bug_mark']}`.\n"
            f"- New production coverage on target-retaining trials: "
            f"{detail['methods']} methods, {detail['branch_counts']} covered-branch counts, "
            f"{detail['probes']} probes, {detail['lines']} lines.\n"
            f"- Final status: `{result['status']}`; budget "
            f"{result['budget']['max_trials']} trials / "
            f"{result['budget']['max_faults']} ordered faults.\n\n"
            "The probe is a case-local ASM 9.6 overlay on the original Hadoop jars. "
            "JaCoCo 0.8.15 records production coverage. Runtime fault selection uses "
            "observed RPC and VERSION-file I/O identities plus coverage feedback. "
            "No GraphChecker prewoven classes, runtime jar, region skeleton, static "
            "I/O map, causal graph, closure, Docker cluster, or handwritten workload "
            "is used. A fault that prevents the exact target from executing is "
            "counted as a trial but contributes no fuzz feedback.\n\n"
            f"Source review: {result['source_review']}\n\n"
            "Evidence: [machine-readable result](result.json), "
            "[per-trial ledger](trial-ledger.csv), "
            f"[shared campaign state]({evidence_prefix}/evidence/campaign-state.json), "
            f"[healthy manifest]({evidence_prefix}/evidence/healthy/manifest.json), "
            f"[ASM probe]({evidence_prefix}/src/Hdfs22Probe.java), "
            f"[patcher]({evidence_prefix}/src/PatchHdfs22.java).\n"
        )
        readme_path = case["directory"] / "README.md"
        temporary_readme = readme_path.with_suffix(".md.tmp")
        temporary_readme.write_text(readme)
        temporary_readme.replace(readme_path)
        summary = {"case_id": case_id, "status": result["status"], "budget": result["budget"],
                   "fault_trials": result["fault_trials"],
                   "fully_applied_trials": result["fully_applied_trials"],
                   "target_after_fault": result["target_after_fault"],
                   "target_exception_after_fault": result["target_exception_after_fault"],
                   "expected_guard_response_trials": result["expected_guard_response_trials"],
                   "coverage_gain_detail": result["coverage_gain_detail"],
                   "elapsed_seconds": result["elapsed_seconds"], "bug_mark": result["bug_mark"],
                   "extension_decision": result["extension_decision"]}
        summaries[case_id] = summary
        ledger = case["directory"] / "trial-ledger.csv"
        temporary = ledger.with_suffix(".csv.tmp")
        with temporary.open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=[
                "trial", "faults", "last_marker", "last_source", "last_ordinal",
                "exact_order_applied", "target_after_fault", "target_exception_after_fault",
                "target_exception_classification", "junit_exit", "elapsed_seconds",
                "new_methods", "new_branches", "new_probes", "new_io_families", "manifest"])
            writer.writeheader()
            for index, trial in enumerate(result["trial_results"], 1):
                fault = trial["sequence"][-1]
                writer.writerow({"trial": index, "faults": len(trial["sequence"]),
                                 "last_marker": fault["marker"], "last_source": fault["sourceKey"],
                                 "last_ordinal": fault["hitOrdinal"],
                                 "exact_order_applied": trial["exact_order_applied"],
                                 "target_after_fault": trial["target_after_fault"],
                                 "target_exception_after_fault": trial["target_exception_after_fault"],
                                 "target_exception_classification": trial["target_exception_classification"],
                                 "junit_exit": trial["junit_exit"], "elapsed_seconds": trial["elapsed_seconds"],
                                 "new_methods": trial["coverage_gain"]["methods"],
                                 "new_branches": trial["coverage_gain"]["branch_counts"],
                                 "new_probes": trial["coverage_gain"]["probes"],
                                 "new_io_families": trial["new_io_families"],
                                 "manifest": trial["manifest"]})
        temporary.replace(ledger)
    atomic_json(EVIDENCE / "campaign-summary.json", summaries)
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
