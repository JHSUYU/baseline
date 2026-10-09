#!/usr/bin/env python3
"""Recompute every SOLR-01 trial claim from its original event trace."""

import json

import campaign
from feedback import atomic_json, events, sequence_applied_in_order


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    trials = state["trials"]
    if [t["number"] for t in trials] != list(range(1, len(trials) + 1)):
        raise AssertionError("Trial numbering is discontinuous")
    strict_count = valid_count = candidate_count = 0
    for trial in trials:
        trace = events(campaign.CAMPAIGN / f"trial-{trial['number']:03d}" / "events.tsv")
        matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
        applied = [e for e in trace if e["kind"] == "IO_APPLIED"]
        strict = sequence_applied_in_order(trial["plan"], applied, matched, trace)
        last = max((e["seq"] for e in applied), default=-1)
        after, exception = campaign.after_target(trace, last)
        if (strict != trial["all_faults_applied"] or
                after != trial["target_after_fault"] or
                exception != trial["target_exception"] or
                len(matched) != trial["faults_matched"] or
                len(applied) != trial["faults_applied"] or
                campaign.target_counts(trace) != trial["target_checks"]):
            raise AssertionError(f"Trial {trial['number']} differs from raw trace")
        strict_count += strict
        valid_count += strict and after
        candidate_count += strict and after and exception
    report = {
        "audited_trials": len(trials), "strict_injections": strict_count,
        "valid_trials": valid_count, "target_after_fault": valid_count,
        "target_exception_candidates": candidate_count,
        "max_applied_faults": max((t["faults_applied"] for t in trials), default=0),
        "audit": "all saved trial claims match raw events",
    }
    atomic_json(campaign.CAMPAIGN / "audit.json", report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
