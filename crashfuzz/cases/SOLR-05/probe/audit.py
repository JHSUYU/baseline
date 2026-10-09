#!/usr/bin/env python3
"""Independently verify saved SOLR-05 fault and target trace claims."""

import json
from pathlib import Path

import campaign


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    trials = state["trials"]
    if [t["number"] for t in trials] != list(range(1, len(trials) + 1)):
        raise AssertionError("trial numbers are not continuous")
    strict_count = 0
    target_after_count = 0
    exception_count = 0
    for trial in trials:
        trace = campaign.events(campaign.CAMPAIGN / f"trial-{trial['number']:03d}" / "events.tsv")
        applied = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
        strict = campaign.sequence_applied_in_order(trial["plan"], applied, matched, trace)
        last_fault = max((e["seq"] for e in applied), default=-1)
        target_after = last_fault >= 0 and any(
            e["kind"] == "TARGET_CHECK" and e["seq"] > last_fault for e in trace)
        target_exception = last_fault >= 0 and any(
            e["kind"] == "TARGET_EXCEPTION" and e["seq"] > last_fault for e in trace)
        if (strict != trial["all_faults_applied"] or
                target_after != trial["target_after_fault"] or
                target_exception != trial["target_exception"] or
                len(applied) != trial["faults_applied"] or
                (strict and target_after) != trial["eligible_feedback"]):
            raise AssertionError(f"trial {trial['number']} differs from its raw trace")
        strict_count += strict
        target_after_count += bool(strict and target_after)
        exception_count += bool(strict and target_after and target_exception)
    result = {
        "case_id": "SOLR-05", "audited_trials": len(trials),
        "strict_injections": strict_count, "target_after_fault": target_after_count,
        "target_exception_candidates": exception_count,
        "max_applied_faults": max((t["faults_applied"] for t in trials), default=0),
        "audit": "all saved trial claims match raw trace",
    }
    output = campaign.CAMPAIGN / "audit.json"
    campaign.atomic_json(output, result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
