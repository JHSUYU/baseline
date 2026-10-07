#!/usr/bin/env python3
"""Review target throws against the original getAliases fallback condition."""

import json
import re

import campaign
from feedback import atomic_json, events


CALL = re.compile(r"^call=(\d+)$")
NODES = re.compile(r"^live_nodes=\[(.*)\]$")


def field(parts, pattern):
    matches = [match for part in parts if (match := pattern.match(part))]
    if len(matches) != 1:
        raise AssertionError(f"Expected one field matching {pattern.pattern}: {parts}")
    return matches[0].group(1)


def review_trial(trial):
    trace = events(campaign.CAMPAIGN / f"trial-{trial['number']:03d}" / "events.tsv")
    throws = [event for event in trace if event["kind"] == "TARGET_EXCEPTION"]
    if not trial["target_exception"]:
        if throws:
            raise AssertionError(f"Trial {trial['number']}: unexpected target throw in trace")
        return []
    if not trial["all_faults_applied"] or not trial["target_after_fault"]:
        raise AssertionError(f"Trial {trial['number']}: target throw lacks valid injection")
    reports = []
    for thrown in throws:
        invocation = field(thrown["parts"], CALL)
        starts = [event for event in trace if event["kind"] == "TARGET_ENTER"
                  and event["seq"] < thrown["seq"]
                  and field(event["parts"], CALL) == invocation]
        if len(starts) != 1:
            raise AssertionError(f"Trial {trial['number']}: invocation {invocation} has {len(starts)} enters")
        start = starts[0]
        nodes = [node.strip() for node in field(start["parts"], NODES).split(",")]
        checks = [event for event in trace if event["kind"] == "TARGET_CHECK"
                  and start["seq"] < event["seq"] < thrown["seq"]
                  and event["parts"][0] == "missing"]
        if len(checks) != 1:
            raise AssertionError(f"Trial {trial['number']}: no exact missing guard outcome")
        # The probe counts all getAliases invocations and only HTTP fetches
        # separately. The throw uses the former; I/O and guard use the latter.
        fetch_call = field(checks[0]["parts"], CALL)
        io = [event for event in trace if event["kind"] == "IO_OBSERVED"
              and start["seq"] < event["seq"] < thrown["seq"]
              and field(event["parts"], CALL) == fetch_call]
        applied = [event for event in trace if event["kind"] == "IO_APPLIED"
                   and start["seq"] < event["seq"] < thrown["seq"]
                   and field(event["parts"], CALL) == fetch_call]
        if len(nodes) != len(io) or len(io) != len(applied):
            raise AssertionError(f"Trial {trial['number']}: not every live endpoint faulted")
        actual = [next(part[9:] for part in event["parts"]
                       if part.startswith("endpoint=")) for event in io]
        faulted = [next(part[9:] for part in event["parts"]
                        if part.startswith("endpoint=")) for event in applied]
        expected = ["http://" + node.replace("_", "/", 1) for node in nodes]
        if len(set(actual)) != len(nodes) or set(actual) != set(expected) or actual != faulted:
            raise AssertionError(f"Trial {trial['number']}: actual endpoint set differs from live nodes")
        reports.append({"trial": trial["number"], "invocation": int(invocation),
                        "fetch_call": int(fetch_call),
                        "live_nodes": len(nodes), "faulted_endpoints": len(applied),
                        "fault_kinds": [next(part[11:] for part in event["parts"]
                                        if part.startswith("fault_kind=")) for event in applied],
                        "disposition": "expected_all_live_nodes_failed"})
    return reports


def main():
    state = json.loads(campaign.STATE.read_text())
    reviews = [report for trial in state["trials"] for report in review_trial(trial)]
    counted = sum(trial["all_faults_applied"] and trial["target_after_fault"]
                  and trial["target_exception"] for trial in state["trials"])
    if len(reviews) != counted:
        raise AssertionError(f"Reviewed {len(reviews)} target throws but counted {counted} trials")
    report = {"reviewed_trials": len(state["trials"]), "target_throws": len(reviews),
              "source": "original BaseHttpClusterStateProvider.getAliases at line 267",
              "disposition": "expected_all_live_nodes_failed", "throws": reviews}
    atomic_json(campaign.CAMPAIGN / "candidate-review.json", report)
    print(json.dumps({key: value for key, value in report.items() if key != "throws"}, sort_keys=True))


if __name__ == "__main__":
    main()
