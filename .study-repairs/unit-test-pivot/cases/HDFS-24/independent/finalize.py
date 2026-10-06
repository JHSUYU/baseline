#!/usr/bin/env python3
"""Freeze separate HDFS-24/26/27 checklist entries after the trial budget."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from campaign import BASE, COVERAGE, GROUPS, SITES, TARGET, atomic_json, checks, events

HERE = Path(__file__).resolve().parent
SIGNATURES = {
    "HDFS-24": "doTransition(StorageDirectory,NamespaceInfo,StartupOption,List<Callable<StorageDirectory>>,Configuration)",
    "HDFS-26": "doRollback(StorageDirectory,NamespaceInfo)",
    "HDFS-27": "doUpgrade(String,StorageDirectory,NamespaceInfo,File,File,File,int,Configuration)",
}


def version_signature(event: dict) -> tuple[str, str, str, str] | None:
    match = re.fullmatch(
        r"Datanode state: LV = (-?\d+) CTime = (\d+) is newer than "
        r"the namespace state: LV = (-?\d+) CTime = (\d+)",
        event.get("message", ""))
    if not match:
        return None
    # Namespace creation time varies across fresh MiniDFSCluster runs.
    return (event.get("exception", ""), match.group(1), match.group(2), match.group(3))


def audit_target_exceptions(results: dict[str, dict], cases: tuple[str, ...]) -> None:
    healthy_trace = events(BASE / cases[0] / "independent/evidence/healthy/runtime_trace.jsonl")
    healthy_hdfs24 = {version_signature(row) for row in healthy_trace
                      if row["event"] == "TARGET_THROW" and row.get("caseId") == "HDFS-24"}
    for case_id, result in results.items():
        for trial in result["trial_results"]:
            # Include a retry's first JUnit in the time spent on this selector.
            root = Path(trial["manifest"]).parent.parent
            attempts = [json.loads(p.read_text())["elapsed_seconds"]
                        for p in sorted(root.glob("attempt-*/manifest.json"))]
            if not attempts:
                raise SystemExit("Missing trial manifests: " + str(root))
            trial["attempt_elapsed_seconds"] = attempts
            trial["elapsed_seconds"] = round(sum(attempts), 3)
            thrown = trial["target_exception_events"]
            if not trial["valid_for_feedback"] or not thrown:
                trial["target_exception_classification"] = "none"
                trial["bug_mark"] = "none"
            elif case_id == "HDFS-24" and all(version_signature(row) in healthy_hdfs24
                                               for row in thrown):
                trial["target_exception_classification"] = "expected_version_guard_response"
                trial["bug_mark"] = "none"
            else:
                trial["target_exception_classification"] = "candidate_needs_replay_source_review"
                trial["bug_mark"] = "candidate_needs_replay_source_review"
        result["expected_guard_response_trials"] = sum(
            t["target_exception_classification"] == "expected_version_guard_response"
            for t in result["trial_results"])
        result["bug_mark"] = ("candidate_needs_replay_source_review"
                              if any(t["bug_mark"] != "none" for t in result["trial_results"])
                              else "none")
        result["elapsed_seconds"] = round(
            result["healthy"]["elapsed_seconds"] +
            sum(t["elapsed_seconds"] for t in result["trial_results"]), 3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=GROUPS, required=True)
    args = parser.parse_args()
    cases = GROUPS[args.group]
    anchor = BASE / cases[0] / "independent"
    state = json.loads((anchor / "evidence/campaign-state.json").read_text())
    results = {c: json.loads((BASE / c / "result.json").read_text()) for c in cases}
    audit_target_exceptions(results, cases)
    budget = state["budget"]["max_trials"]
    if any(r["fault_trials"] < budget for r in results.values()):
        raise SystemExit("Trial budget not yet complete")
    novelty = any(t["new_io_families"] or any(t["coverage_gain"].values())
                  for c in cases for t in results[c]["trial_results"][-8:])
    extension = novelty and budget < 128 and not any(r["bug_mark"] != "none"
                                                     for r in results.values())
    summaries = {}
    for case_id, result in results.items():
        case = BASE / case_id
        source, function, line, code = TARGET[case_id]
        result["target_method_signature"] = SIGNATURES[case_id]
        branch_outcomes = {site: {"true": 0, "false": 0} for site in SITES[case_id]}
        for trial in result["trial_results"]:
            if not trial["valid_for_feedback"]:
                continue
            trace = events(Path(trial["trace"]))
            applied = [r for r in trace if r["event"] == "FAULT_APPLIED"]
            if not applied:
                raise SystemExit("Missing applied fault trace: " + trial["trace"])
            for row in checks(trace, case_id):
                if row["seq"] <= applied[-1]["seq"]:
                    continue
                outcome = (row["equal"] if case_id == "HDFS-27" else
                           row["reject"] if case_id == "HDFS-26" else row["upgrade"])
                branch_outcomes[row["siteId"]]["true" if outcome else "false"] += 1
        result["post_fault_target_branch_outcomes"] = branch_outcomes
        own_healthy = case / "independent/evidence/healthy"
        own_trace = events(own_healthy / "runtime_trace.jsonl")
        if case_id == "HDFS-27":
            result["own_mapped_junit_healthy"] = {
                "cluster_test": "org.apache.hadoop.hdfs.TestDatanodeLayoutUpgrade#testUpgradeToIdBasedLayout",
                "manifest": str(own_healthy / "manifest.json"),
                "target_checks": len(checks(own_trace, case_id)),
                "target_exceptions": sum(r["event"] == "TARGET_THROW"
                    and r.get("caseId") == case_id for r in own_trace),
                "shared_workload_rationale": (
                    "Original TestDFSUpgrade#testUpgrade reaches the exact HDFS-27 bytecode guard "
                    "six times and exposes more observed relevant I/O points. Its fault trials "
                    "are scored separately for HDFS-24 and HDFS-27.")}
        result["status"] = ("pending_candidate_replay_source_review"
                            if result["bug_mark"] != "none" else
                            "pending_budget_extension" if extension else "quality_complete")
        result["extension_decision"] = {
            "last_chronological_trials": min(8, result["fault_trials"]),
            "new_production_coverage_or_stable_io_family": novelty,
            "next_budget_if_needed": {"max_trials": 128, "max_faults": 10} if extension else None,
            "budget_ceiling_reached": budget >= 128}
        result["elapsed_seconds_semantics"] = (
            "One healthy JUnit plus each actual fault-trial JUnit; the upgrade run is "
            "attributed separately to HDFS-24 and HDFS-27, never added together.")
        healthy = BASE / cases[0] / "independent/evidence/healthy"
        result["coverage_gain_detail"] = {
            k: result["coverage"][k] - len(set(
                (healthy / ("covered_" + k + ".txt")).read_text().splitlines()))
            for k in COVERAGE}
        result["tested_sequence_depths"] = dict(sorted(Counter(
            len(t["sequence"]) for t in result["trial_results"]).items()))
        result["target_retaining_sequence_depths"] = dict(sorted(Counter(
            len(t["sequence"]) for t in result["trial_results"]
            if t["valid_for_feedback"]).items()))
        result["applied_fault_type_counts"] = dict(sorted(Counter(
            fault["faultType"] for t in result["trial_results"]
            if t["exact_order_applied"] for fault in t["sequence"]).items()))
        result["applied_io_marker_counts"] = dict(sorted(Counter(
            fault["marker"] for t in result["trial_results"]
            if t["exact_order_applied"] for fault in t["sequence"]).items()))
        result["coverage_metric_note"] = (
            "JaCoCo probe identities and production method/line coverage are exact; "
            "branch_counts are per-method covered branch counts, used as monotone feedback. "
            "Runtime-generated Mockito mock classes are excluded.")
        if case_id == "HDFS-24":
            review = ("doTransition compares on-disk DataNode layout version and cTime with "
                      "NameNode NamespaceInfo. Its IOException explicitly rejects storage newer "
                      "than the namespace. TestDFSUpgrade intentionally includes incompatible "
                      "upgrade variants; a matching rejection alone is expected behavior.")
        elif case_id == "HDFS-26":
            review = ("doRollback reads the previous VERSION and checks layout version and "
                      "cTime against the running software and NamespaceInfo. The explicit "
                      "InconsistentFSStateException rejects rollback to a newer state; a "
                      "matching rejection alone is expected behavior.")
        else:
            review = ("doUpgrade links blocks, sets the current layout version, then asserts "
                      "that stored namespaceID equals NamespaceInfo.namespaceID before writing "
                      "VERSION. A post-fault AssertionError at this guard requires exact replay "
                      "and source-state review before any new-bug claim.")
        result["source_review"] = review
        result["candidate_semantic_classification"] = {
            "label": "storage_version_compatibility_or_upgrade_identity_guard",
            "assessment": "Direct storage/namespace identity or version check; dynamic multi-hop coordination is not established by this source alone.",
            "basis": code}
        result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        atomic_json(case / "result.json", result)
        prefix = "independent" if case_id == cases[0] else f"../{cases[0]}/independent"
        instrumentation_prefix = "../HDFS-24/independent" if case_id == "HDFS-26" else prefix
        detail = result["coverage_gain_detail"]
        readme = (
            f"# {case_id} independent original-JUnit fault campaign\n\n"
            f"- Target: `{result['target_source_file']}:{line}` in "
            f"`BlockPoolSliceStorage.{SIGNATURES[case_id]}`; "
            f"guard `{code}`. Exact bytecode sites: {', '.join('`'+s+'`' for s in SITES[case_id])}.\n"
            f"- Workload: unchanged Hadoop 3.4.3 `{result['cluster_test']}` (MiniDFSCluster).\n"
            f"- Healthy run: {result['healthy']['target_checks']} exact branch events, "
            f"{result['healthy']['target_exceptions']} target exceptions.\n"
            f"- Fault campaign: {result['fault_trials']} trials in {result['elapsed_seconds']:.3f} "
            f"attributed JUnit seconds; {result['strict_injections']} exact ordered injections; "
            f"{result['target_after_fault']} target-retaining trials.\n"
            f"- Post-fault target exceptions: {result['target_exception_after_fault']}; "
            f"{result['expected_guard_response_trials']} trials matched the expected version "
            f"guard. Bug mark: `{result['bug_mark']}`.\n"
            f"- New production coverage with target retained: {detail['methods']} methods, "
            f"{detail['branch_counts']} covered-branch counts, {detail['probes']} probes, "
            f"{detail['lines']} lines.\n"
            f"- Post-fault target branch outcomes by exact bytecode site: "
            f"`{json.dumps(branch_outcomes, sort_keys=True)}`.\n"
            f"- Status: `{result['status']}`; budget {budget} trials / "
            f"{result['budget']['max_faults']} ordered faults.\n\n"
            f"- Tested sequence depths: `{result['tested_sequence_depths']}`; "
            f"target-retaining depths: `{result['target_retaining_sequence_depths']}`; "
            f"applied fault types: `{result['applied_fault_type_counts']}`.\n\n"
            + (f"Own mapped JUnit healthy probe: "
               f"`{result['own_mapped_junit_healthy']['cluster_test']}` reaches the exact guard "
               f"{result['own_mapped_junit_healthy']['target_checks']} time(s). "
               f"{result['own_mapped_junit_healthy']['shared_workload_rationale']}\n\n"
               if case_id == "HDFS-27" else "")
            + "The case-local ASM 9.6 overlay instruments original Hadoop classes; JaCoCo 0.8.15 "
            "records production coverage. Fault selection uses only observed RPC/VERSION-file I/O "
            "and production coverage feedback. No GraphChecker prewoven classes, runtime jar, "
            "region skeleton, static I/O map, causal graph, closure, Docker cluster, or handwritten "
            "workload is used. Target-lost trials count toward the budget but provide no feedback.\n\n"
            f"Source review: {review}\n\n"
            "Evidence: [result](result.json), [trial ledger](trial-ledger.csv), "
            f"[checkpoint]({prefix}/evidence/campaign-state.json), "
            f"[healthy manifest]({prefix}/evidence/healthy/manifest.json), "
            f"[ASM probe]({instrumentation_prefix}/src/HdfsStorageProbe.java), "
            f"[patcher]({instrumentation_prefix}/src/PatchHdfsStorage.java).\n")
        tmp = case / "README.md.tmp"
        tmp.write_text(readme)
        tmp.replace(case / "README.md")
        ledger = case / "trial-ledger.csv"
        temp = ledger.with_suffix(".csv.tmp")
        fields = ("trial", "attempts", "faults", "last_marker", "last_source", "last_ordinal",
                  "exact_order_applied", "target_after_fault", "post_fault_target_checks",
                  "target_exception_after_fault", "target_exception_classification",
                  "junit_exit", "elapsed_seconds", "new_methods", "new_branches",
                  "new_probes", "new_io_families", "manifest")
        with temp.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for index, trial in enumerate(result["trial_results"], 1):
                last = trial["sequence"][-1]
                writer.writerow({
                    "trial": index, "attempts": len(trial["attempt_elapsed_seconds"]),
                    "faults": len(trial["sequence"]),
                    "last_marker": last["marker"], "last_source": last["sourceKey"],
                    "last_ordinal": last["hitOrdinal"],
                    "exact_order_applied": trial["exact_order_applied"],
                    "target_after_fault": trial["target_after_fault"],
                    "post_fault_target_checks": trial["post_fault_target_checks"],
                    "target_exception_after_fault": trial["target_exception_after_fault"],
                    "target_exception_classification": trial["target_exception_classification"],
                    "junit_exit": trial["junit_exit"],
                    "elapsed_seconds": trial["elapsed_seconds"],
                    "new_methods": trial["coverage_gain"]["methods"],
                    "new_branches": trial["coverage_gain"]["branch_counts"],
                    "new_probes": trial["coverage_gain"]["probes"],
                    "new_io_families": trial["new_io_families"],
                    "manifest": trial["manifest"]})
        temp.replace(ledger)
        summaries[case_id] = {k: result[k] for k in (
            "case_id", "status", "budget", "fault_trials", "fully_applied_trials",
            "target_after_fault", "target_exception_after_fault",
            "expected_guard_response_trials", "coverage_gain_detail", "elapsed_seconds",
            "bug_mark", "extension_decision")}
    atomic_json(anchor / "evidence/campaign-summary.json", summaries)
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
