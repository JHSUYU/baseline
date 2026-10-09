#!/usr/bin/env python3
"""Audit the finished independent campaign and publish its selected-check result."""

import json
from pathlib import Path

import audit
import campaign
import coverage_summary
from feedback import atomic_json, events, feedback_identity


WORK = Path(__file__).resolve().parents[1]
CASE_ID = WORK.parent.name
BASELINE = WORK.parents[4]


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    if ("finished_at" not in state or
            len(state["trials"]) < state["budget"]["max_trials"] and state["queue"]):
        raise RuntimeError("Campaign has not exhausted its configured budget")
    audit.main()
    coverage_summary.main()
    checked = json.loads((campaign.CAMPAIGN / "audit.json").read_text())
    covered = json.loads((campaign.CAMPAIGN / "coverage-summary.json").read_text())
    result_path = WORK.parent / "result.json"
    result = json.loads(result_path.read_text())
    if (result["fault_trials"] != checked["audited_trials"] or
            result["strict_injections"] != checked["strict_injections"] or
            result["target_after_fault"] != checked["target_after_fault"][CASE_ID] or
            result["target_exception_candidates"] != checked["target_exception_candidates"][CASE_ID]):
        raise AssertionError("Result disagrees with raw trace audit")
    sites = set()
    for trial in state["trials"]:
        trace = events(campaign.CAMPAIGN / f"trial-{trial['number']:03d}" / "events.tsv")
        for event in trace:
            if event["kind"] != "IO_APPLIED_CONNECTION_LOSS":
                continue
            parts = event["parts"]
            caller = next((part[7:] for part in parts if part.startswith("caller=")), "<unknown>")
            sites.add(caller + "|" + feedback_identity((parts[0], parts[1])))
    result.update({
        "status": ("candidate_needs_source_review" if result["target_exception_candidates"]
                   else "quality_complete" if result["target_after_fault"]
                   else "no_post_fault_target"),
        "max_applied_faults": checked["max_applied_faults"],
        "unique_applied_callsite_operation_resource": len(sites),
        "production_methods_gained": covered["new_covered_methods"],
        "production_branches_gained": covered["new_covered_branches"],
        "unmodified_production_methods_gained": covered["new_unmodified_covered_methods"],
        "unmodified_production_branches_gained": covered["new_unmodified_covered_branches"],
        "target_guard_branch_taken": covered["target_guard_taken"],
        "raw_trace_audit": str((campaign.CAMPAIGN / "audit.json").relative_to(BASELINE)),
        "production_coverage_summary": str((campaign.CAMPAIGN / "coverage-summary.json").relative_to(BASELINE)),
        "conclusion": ("target exception candidate requires replay and source review"
                       if result["target_exception_candidates"] else
                       "no selected target exception observed within this I/O scope and budget"),
    })
    atomic_json(result_path, result)


if __name__ == "__main__":
    main()
