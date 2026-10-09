#!/usr/bin/env python3
"""Independently recheck selected HDFS token guards in original-JUnit trials."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "cases"
TARGETS = {
    "HDFS-11": ("BlockTokenSecretManager.retrieveDataEncryptionKey#L552",
                "BlockTokenSecretManager.retrieveDataEncryptionKey#L553"),
    "HDFS-12": ("BlockTokenSecretManager.retrievePassword#L511",
                "BlockTokenSecretManager.retrievePassword#L514"),
    "HDFS-14": ("BlockTokenSecretManager.checkAccess#L411",
                "BlockTokenSecretManager.checkAccess#L412"),
}


def events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def same_fault(observed: dict, planned: dict, index: int) -> bool:
    return observed.get("planIndex") == index and all(
        observed.get(field) == planned.get(field)
        for field in ("marker", "siteId", "sourceKey", "occurrence",
                      "hitOrdinal", "faultType"))


def audit(case_id: str) -> dict:
    directory = ROOT / case_id / "independent"
    state = json.loads((directory / "campaign-state.json").read_text())
    target, selected_throw = TARGETS[case_id]
    findings = []
    for trial in state["completed"]:
        run = Path(trial["run"])
        trace = events(run / "runtime_trace.jsonl")
        manifest = json.loads((run / "manifest.json").read_text())
        matched = [event for event in trace if event["event"] == "FAULT_MATCHED"]
        applied = [event for event in trace if event["event"] == "FAULT_APPLIED"]
        sequence = trial["sequence"]
        exact = (len(matched) == len(applied) == len(sequence)
                 and all(same_fault(matched[i], selected, i)
                         and same_fault(applied[i], selected, i)
                         and matched[i]["seq"] < applied[i]["seq"]
                         for i, selected in enumerate(sequence))
                 and all(applied[i]["seq"] < matched[i + 1]["seq"]
                         for i in range(len(sequence) - 1)))
        last = applied[-1]["seq"] if exact else None
        post = [event for event in trace if event["event"] == "TARGET_CHECK"
                and event.get("siteId") == target
                and last is not None and event["seq"] > last]
        throws = [event for event in trace if event["event"] == "TARGET_THROW"
                  and event.get("siteId") == selected_throw
                  and last is not None and event["seq"] > last]
        key_ids = {event.get("keyId") for event in post}
        discrepancies = []
        if exact != trial["exact_order_applied"]:
            discrepancies.append("strictness")
        if bool(post) != trial["target_after_fault"]:
            discrepancies.append("post_fault_target")
        if len(throws) != trial["target_exception_after_fault"]:
            discrepancies.append("selected_exception_count")
        if manifest["returncode"] != trial["junit_exit"]:
            discrepancies.append("junit_exit")
        findings.append({
            "id": trial["id"], "run": str(run), "faults": len(sequence),
            "exact": exact, "post_fault_target": bool(post),
            "post_fault_checks": len(post), "selected_throws": len(throws),
            "post_fault_key_ids": len(key_ids),
            "junit_exit": manifest["returncode"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "discrepancies": discrepancies,
        })
    valid = [row for row in findings if row["exact"] and row["post_fault_target"]]
    recent = state["completed"][-8:]
    return {
        "case_id": case_id, "budget": state["budget"],
        "completed": len(findings),
        "exact": sum(row["exact"] for row in findings),
        "valid": len(valid),
        "valid_junit_exit_codes": dict(Counter(row["junit_exit"] for row in valid)),
        "valid_post_fault_key_id_counts": dict(Counter(
            row["post_fault_key_ids"] for row in valid)),
        "selected_exception_trials": sum(bool(row["selected_throws"]) for row in valid),
        "deepest_sequence": max((row["faults"] for row in findings), default=0),
        "last_eight_valid_novel": sum(
            bool(trial["valid_for_feedback"] and (
                trial["coverage_gain"]["methods"]
                or trial["coverage_gain"]["branch_counts"]
                or trial["new_io_families"])) for trial in recent),
        "discrepancies": [row for row in findings if row["discrepancies"]],
        "candidate_runs": [row for row in valid if row["selected_throws"]],
        "trials": findings,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id", choices=sorted(TARGETS))
    args = parser.parse_args()
    print(json.dumps(audit(args.case_id), indent=2))
