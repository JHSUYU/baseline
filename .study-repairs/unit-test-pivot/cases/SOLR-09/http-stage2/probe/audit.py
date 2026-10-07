#!/usr/bin/env python3
"""Verify every saved fault and per-target result against raw events."""

import json

import campaign
from feedback import events, sequence_applied_in_order, atomic_json


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    trials = state["trials"]
    if [t["number"] for t in trials] != list(range(1, len(trials) + 1)):
        raise AssertionError("trial numbers are not continuous")
    strict_count = 0
    retained = {cid: 0 for cid in campaign.CASES}
    candidates = {cid: 0 for cid in campaign.CASES}
    for trial in trials:
        trace = events(campaign.CAMPAIGN / f"trial-{trial['number']:03d}" / "events.tsv")
        applied = [e for e in trace if e["kind"].startswith("IO_APPLIED_")]
        matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
        strict = sequence_applied_in_order(trial["plan"], applied, matched, trace)
        last = max((e["seq"] for e in applied), default=-1)
        after, exception = campaign.after_target(trace, last)
        if (strict != trial["all_faults_applied"] or
                after != trial["target_after_fault"] or
                exception != trial["target_exception"] or
                len(applied) != trial["faults_applied"] or
                len(matched) != trial["faults_matched"] or
                campaign.target_counts(trace) != trial["target_checks"]):
            raise AssertionError(f"trial {trial['number']} differs from raw trace")
        strict_count += strict
        for cid in campaign.CASES:
            retained[cid] += bool(strict and after[cid])
            candidates[cid] += bool(strict and after[cid] and exception[cid])
    report = {"audited_trials": len(trials), "strict_injections": strict_count,
              "target_after_fault": retained, "target_exception_candidates": candidates,
              "max_applied_faults": max((t["faults_applied"] for t in trials), default=0),
              "audit": "all saved trial claims match raw trace"}
    atomic_json(campaign.CAMPAIGN / "audit.json", report)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
