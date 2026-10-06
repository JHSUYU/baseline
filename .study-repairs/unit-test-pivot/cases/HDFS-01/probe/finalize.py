#!/usr/bin/env python3
"""Freeze the completed HDFS-01 campaign as a reviewable checklist result."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

CASE = Path(__file__).resolve().parent.parent
RESULT = CASE / "result.json"
EVIDENCE = CASE / "evidence"


def atomic_json(path: Path, value: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main() -> None:
    result = json.loads(RESULT.read_text())
    budget = result["budget"]
    trials = result["trial_results"]
    if result["fault_trials"] != len(trials) or len(trials) < budget["max_trials"]:
        raise SystemExit("Campaign budget not yet complete")
    if any(trial["bug_mark"] != "none" for trial in trials):
        result["status"] = "pending_candidate_replay_source_review"
        extension = False
    else:
        recent = trials[-8:]
        near_limit_novelty = any(trial["new_io_families"] or any(trial["coverage_gain"].values())
                                 for trial in recent)
        extension = near_limit_novelty and budget["max_trials"] < 128
        result["status"] = "pending_budget_extension" if extension else "quality_complete"
    result["extension_decision"] = {
        "near_limit_window_trials": min(8, len(trials)),
        "new_production_coverage_or_io_family": near_limit_novelty if not any(
            trial["bug_mark"] != "none" for trial in trials) else None,
        "next_budget_if_needed": {"max_trials": 128, "max_faults": 10} if extension else None,
        "budget_ceiling_reached": budget["max_trials"] >= 128,
    }
    result["elapsed_seconds_semantics"] = "sum of two healthy JUnit durations and fault-trial JUnit durations; excludes instrumentation build and coverage postprocessing"
    result["coverage_gain_detail"] = {
        name: result["coverage"][name] - len(set((EVIDENCE / "healthy" / ("covered_" + name + ".txt")).read_text().splitlines()))
        for name in ("probes", "methods", "branch_counts", "lines")
    }
    result["coverage_metric_note"] = (
        "JaCoCo probe IDs are exact; branch_counts uses per-method covered branch "
        "counts as a stable monotone feedback proxy, not individual branch IDs."
    )
    result["source_review"] = (
        "DFSInputStream.fetchBlockAt line 518 validates the NameNode getBlockLocations "
        "response against the client stream's cached file metadata. The unchanged "
        "TestPread test restarts DataNodes but does not concurrently truncate/delete "
        "the file; see README.md for the bounded semantic assessment."
    )
    result["candidate_semantic_classification"] = {
        "label": "direct_rpc_response_validation",
        "assessment": "weaker ad hoc coordination candidate under this unchanged JUnit",
        "basis": "the guard checks an immediate NameNode block-location RPC response; the test has no concurrent truncate/delete operation changing block availability",
    }
    result["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_json(RESULT, result)

    summary = {
        "case_id": "HDFS-01", "status": result["status"], "budget": budget,
        "fault_trials": len(trials), "fully_applied_trials": result["fully_applied_trials"],
        "target_after_fault": result["target_after_fault"],
        "target_eof_after_fault": sum(t["target_eof_after_fault"] for t in trials),
        "coverage_gain_branch_counts": result["coverage_gain"],
        "coverage_gain_detail": result["coverage_gain_detail"],
        "elapsed_seconds": result["elapsed_seconds"],
        "extension_decision": result["extension_decision"],
        "bug_mark": result["bug_mark"],
    }
    families = {}
    for trial in trials:
        fault = trial["sequence"][-1]
        key = fault["marker"] + "|" + fault["sourceKey"]
        row = families.setdefault(key, {"trials": 0, "fully_applied": 0, "target_after_fault": 0})
        row["trials"] += 1
        row["fully_applied"] += bool(trial["exact_order_applied"])
        row["target_after_fault"] += bool(trial["target_after_fault"])
    summary["last_fault_family"] = families
    atomic_json(EVIDENCE / "campaign-summary.json", summary)

    ledger = CASE / "trial-ledger.csv"
    temporary = ledger.with_suffix(".csv.tmp")
    with temporary.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=[
            "trial", "faults", "last_marker", "last_source", "last_ordinal",
            "exact_order_applied", "target_after_fault", "target_eof_after_fault",
            "junit_exit", "elapsed_seconds", "new_methods", "new_branches",
            "new_probes", "new_io_families", "manifest"])
        writer.writeheader()
        for index, trial in enumerate(trials, 1):
            fault = trial["sequence"][-1]
            writer.writerow({"trial": index, "faults": len(trial["sequence"]),
                             "last_marker": fault["marker"], "last_source": fault["sourceKey"],
                             "last_ordinal": fault["hitOrdinal"],
                             "exact_order_applied": trial["exact_order_applied"],
                             "target_after_fault": trial["target_after_fault"],
                             "target_eof_after_fault": trial["target_eof_after_fault"],
                             "junit_exit": trial["junit_exit"], "elapsed_seconds": trial["elapsed_seconds"],
                             "new_methods": trial["coverage_gain"]["methods"],
                             "new_branches": trial["coverage_gain"]["branch_counts"],
                             "new_probes": trial["coverage_gain"]["probes"],
                             "new_io_families": trial["new_io_families"],
                             "manifest": trial["manifest"]})
    temporary.replace(ledger)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
