#!/usr/bin/env python3
"""Audit the finished shared campaign and publish three independent check results."""

import json

import audit
import campaign
import coverage_summary
from feedback import atomic_json, events, feedback_identity


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    if ("finished_at" not in state or
            len(state["trials"]) < state["budget"]["max_trials"] and state["queue"]):
        raise RuntimeError("Campaign has not exhausted its configured budget")
    audit.main()
    coverage_summary.main()
    checked = json.loads((campaign.CAMPAIGN / "audit.json").read_text())
    coverage = json.loads((campaign.CAMPAIGN / "coverage-summary.json").read_text())
    sites = set()
    for trial in state["trials"]:
        trace = events(campaign.CAMPAIGN / f"trial-{trial['number']:03d}" / "events.tsv")
        for event in trace:
            if event["kind"] != "IO_APPLIED_CONNECTION_LOSS":
                continue
            parts = event["parts"]
            caller = next((part[7:] for part in parts if part.startswith("caller=")), "<unknown>")
            sites.add(caller + "|" + feedback_identity((parts[0], parts[1])))
    for cid in campaign.CASES:
        path = campaign.ROOT / cid / "result.json"
        result = json.loads(path.read_text())
        if (result["fault_trials"] != checked["audited_trials"] or
                result["strict_injections"] != checked["strict_injections"] or
                result["target_after_fault"] != checked["target_after_fault"][cid] or
                result["target_exception_candidates"] != checked["target_exception_candidates"][cid]):
            raise AssertionError(f"{cid} result disagrees with independent trace audit")
        branch = coverage["cases"][cid]
        result.update({
            "status": ("candidate_needs_source_review" if result["target_exception_candidates"]
                       else "quality_complete" if result["target_after_fault"]
                       else "no_post_fault_target"),
            "max_applied_faults": checked["max_applied_faults"],
            "unique_applied_callsite_operation_resource": len(sites),
            "production_methods_gained": branch["new_covered_methods"],
            "production_branches_gained": branch["new_covered_branches"],
            "target_guard_branch_taken": branch["target_guard_taken"],
            "raw_trace_audit": str((campaign.CAMPAIGN / "audit.json").relative_to(campaign.ROOT.parents[2])),
            "production_coverage_summary": str((campaign.CAMPAIGN / "coverage-summary.json").relative_to(campaign.ROOT.parents[2])),
            "conclusion": ("target exception candidate requires replay and source review"
                           if result["target_exception_candidates"] else
                           "no selected target exception observed within this I/O scope and budget"),
        })
        atomic_json(path, result)


if __name__ == "__main__":
    main()
