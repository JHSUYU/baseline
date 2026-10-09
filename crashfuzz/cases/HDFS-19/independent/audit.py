#!/usr/bin/env python3
"""Independently audit HDFS-19 fault identity and finalize-pool assertion."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
TARGET = "BPOfferService.processCommandFromActive#L768"
THROW = "BPOfferService.processCommandFromActive#L769"
IDENTITY = ("marker", "siteId", "sourceKey", "occurrence",
            "hitOrdinal", "faultType")


def main() -> None:
    state = json.loads((HERE / "campaign-state.json").read_text())
    findings = []
    for trial in state["completed"]:
        run = Path(trial["run"])
        trace = [json.loads(line) for line in
                 (run / "runtime_trace.jsonl").read_text().splitlines() if line]
        manifest = json.loads((run / "manifest.json").read_text())
        matched = [event for event in trace if event["event"] == "FAULT_MATCHED"]
        applied = [event for event in trace if event["event"] == "FAULT_APPLIED"]
        planned = trial["sequence"]
        exact = (len(matched) == len(applied) == len(planned)
                 and all(all(matched[i].get(field) == planned[i].get(field)
                             and applied[i].get(field) == planned[i].get(field)
                             for field in IDENTITY)
                         and matched[i].get("planIndex") == i
                         and applied[i].get("planIndex") == i
                         and matched[i]["seq"] < applied[i]["seq"]
                         for i in range(len(planned)))
                 and all(applied[i]["seq"] < matched[i + 1]["seq"]
                         for i in range(len(planned) - 1)))
        last = applied[-1]["seq"] if exact else None
        post = [event for event in trace if event["event"] == "TARGET_CHECK"
                and event.get("siteId") == TARGET
                and last is not None and event["seq"] > last]
        throws = [event for event in trace if event["event"] == "TARGET_THROW"
                  and event.get("siteId") == THROW
                  and last is not None and event["seq"] > last]
        mismatch = [event for event in post
                    if event["localBlockPoolId"] != event["commandBlockPoolId"]
                    or not event["poolMatches"]]
        discrepancies = []
        if exact != trial["exact_order_applied"]:
            discrepancies.append("strictness")
        if bool(post) != trial["target_after_fault"]:
            discrepancies.append("post_fault_target")
        if len(throws) != trial["target_exception_after_fault"]:
            discrepancies.append("selected_exception_count")
        if manifest["returncode"] != trial["junit_exit"]:
            discrepancies.append("junit_exit")
        findings.append({"id": trial["id"], "run": str(run), "exact": exact,
                         "post_target": bool(post), "checks": len(post),
                         "throws": len(throws), "pool_mismatches": len(mismatch),
                         "junit_exit": manifest["returncode"],
                         "elapsed_seconds": manifest["elapsed_seconds"],
                         "discrepancies": discrepancies})
    valid = [row for row in findings if row["exact"] and row["post_target"]]
    recent = state["completed"][-8:]
    summary = {
        "case_id": "HDFS-19", "completed": len(findings),
        "budget": state["budget"], "exact": sum(row["exact"] for row in findings),
        "valid": len(valid),
        "valid_junit_exit_codes": dict(Counter(row["junit_exit"] for row in valid)),
        "selected_exception_trials": sum(bool(row["throws"]) for row in valid),
        "post_fault_pool_mismatches": sum(row["pool_mismatches"] for row in valid),
        "deepest_sequence": max((len(t["sequence"]) for t in state["completed"]),
                                default=0),
        "last_eight_valid_novel": sum(bool(t["valid_for_feedback"] and (
            t["coverage_gain"]["methods"] or t["coverage_gain"]["branch_counts"]
            or t["new_io_families"])) for t in recent),
        "discrepancies": [row for row in findings if row["discrepancies"]],
        "candidate_runs": [row for row in valid if row["throws"] or row["pool_mismatches"]],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
