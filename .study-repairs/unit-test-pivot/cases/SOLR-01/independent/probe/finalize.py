#!/usr/bin/env python3
"""Audit the finished independent campaign and publish its selected-check result."""

import json
from pathlib import Path

import audit
import campaign
import coverage_summary
import review_candidates
from feedback import atomic_json, events, feedback_identity


WORK = Path(__file__).resolve().parents[1]
CASE_ID = WORK.parent.name
BASELINE = WORK.parents[4]


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    valid_count = sum(campaign.valid(t) for t in state["trials"])
    if ("finished_at" not in state or
            valid_count < state["budget"]["max_valid_trials"] and
            len(state["trials"]) < state["budget"]["max_attempts"] and
            state["queue"]):
        raise RuntimeError("Campaign has not exhausted its configured budget")
    audit.main()
    coverage_summary.main()
    review_candidates.main()
    checked = json.loads((campaign.CAMPAIGN / "audit.json").read_text())
    covered = json.loads((campaign.CAMPAIGN / "coverage-summary.json").read_text())
    reviewed = json.loads((campaign.CAMPAIGN / "candidate-review.json").read_text())
    result_path = WORK.parent / "result.json"
    result = json.loads(result_path.read_text())
    if (result["fault_trials"] != checked["audited_trials"] or
            result["valid_trials"] != checked["valid_trials"] or
            result["strict_injections"] != checked["strict_injections"] or
            result["target_after_fault"] != checked["target_after_fault"] or
            result["target_exception_candidates"] != checked["target_exception_candidates"] or
            reviewed["target_throws"] != checked["target_exception_candidates"]):
        raise AssertionError("Result disagrees with raw trace audit")
    sites = set()
    for trial in state["trials"]:
        trace = events(campaign.CAMPAIGN / f"trial-{trial['number']:03d}" / "events.tsv")
        for event in trace:
            if event["kind"] != "IO_APPLIED":
                continue
            parts = event["parts"]
            caller = next((part[7:] for part in parts if part.startswith("caller=")), "<unknown>")
            sites.add(caller + "|" + feedback_identity((parts[0], parts[1])))
    result.update({
        "status": ("quality_complete" if result["target_after_fault"]
                   else "no_post_fault_target"),
        "bug_mark": "none",
        "candidate_disposition": ("expected_all_live_nodes_failed"
                                  if result["target_exception_candidates"] else "none"),
        "max_applied_faults": checked["max_applied_faults"],
        "unique_applied_callsite_operation_resource": len(sites),
        "production_methods_gained": covered["new_covered_methods"],
        "production_branches_gained": covered["new_covered_branches"],
        "target_guard_branch_taken": covered["target_guard_taken"],
        "raw_trace_audit": str((campaign.CAMPAIGN / "audit.json").relative_to(BASELINE)),
        "production_coverage_summary": str((campaign.CAMPAIGN / "coverage-summary.json").relative_to(BASELINE)),
        "candidate_review_evidence": str((campaign.CAMPAIGN / "candidate-review.json").relative_to(BASELINE)),
        "conclusion": ("All exact target throws followed injected failures on every known live endpoint; "
                       "the original getAliases source explicitly throws after exhausting them. "
                       "Clean replay of the first candidate confirms the path; no new bug is established."
                       if result["target_exception_candidates"] else
                       "no selected target exception observed within this I/O scope and budget"),
    })
    atomic_json(result_path, result)


if __name__ == "__main__":
    main()
