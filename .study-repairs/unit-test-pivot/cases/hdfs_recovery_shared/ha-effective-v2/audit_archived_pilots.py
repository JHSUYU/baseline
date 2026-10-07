#!/usr/bin/env python3
"""Recompute three historical HA feasibility pilots; do not count them."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import campaign


HERE = Path(__file__).resolve().parent
OLD = HERE.parent / "phase-v4"
PLANS = HERE / "fixtures"
PILOTS = (
    ("ha-two-file-pilot-node1-01", "ha-two-file-pilot.tsv", 0, 0,
     {"HDFS-28": 0, "HDFS-29": 0, "HDFS-30": 0}),
    ("ha-two-file-pilot-node1-02", "ha-two-file-pilot.tsv", 0, 2,
     {"HDFS-28": 0, "HDFS-29": 1, "HDFS-30": 1}),
    ("ha-two-remote-pilot-node1-03", "ha-two-remote-pilot.tsv", 1, 0,
     {"HDFS-28": 0, "HDFS-29": 0, "HDFS-30": 0}),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    healthy = OLD / "healthy-ha-failover-resources"
    healthy_trace = campaign.verify_healthy(healthy)
    baseline = {metric: sorted(campaign.covered(healthy, metric))
                for metric in campaign.COVERAGE}
    initial_io = sorted({campaign.family(event) for event in healthy_trace
                         if event.get("event") == "FAULT_POINT_OBSERVED"
                         and event.get("marker", "").startswith("FAULT:")})
    state = {"coverage": {case: baseline for case in campaign.CASES},
             "io_families": {case: initial_io for case in campaign.CASES}}
    report = {"schema": 1, "counted_in_new_budget": False,
              "original_healthy_sha256": sha(healthy / "runtime_trace.jsonl"),
              "old_probe_source_sha256": sha(OLD / "RecoveryProbe.java"),
              "node1_old_probe_overlay_class_sha256":
              "f263504ff3dc85a8aac70b2029ae68c29c9b0f75befe16b34ed6751990bd08e4",
              "pilots": []}
    for name, plan_name, expected_exit, expected_applied, expected_post in PILOTS:
        directory = OLD / name
        plan = PLANS / plan_name
        manifest = json.loads((directory / "manifest.json").read_text())
        events = campaign.trace(directory)
        matched = [event for event in events if event.get("event") == "FAULT_MATCHED"]
        applied = [event for event in events if event.get("event") == "FAULT_APPLIED"]
        requested = len(plan.read_text().splitlines())
        if (requested != 2 or manifest["returncode"] != expected_exit
                or len(matched) != expected_applied or len(applied) != expected_applied
                or manifest["test"] !=
                "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization"):
            raise RuntimeError("historical HA pilot changed: " + name)
        post = {case: 0 for case in campaign.CASES}
        exact = False
        if expected_applied:
            selected = [campaign.point(event, event["faultType"]) for event in applied]
            evaluated = campaign.evaluate(directory, selected, state)
            exact = evaluated["exact_order_applied"]
            post = evaluated["post_fault_target_checks"]
            if not exact or any(evaluated["target_exceptions_after_fault"].values()):
                raise RuntimeError("historical HA two-fault validity changed")
        if post != expected_post:
            raise RuntimeError("postfault owner/check mismatch: " + name)
        if name.endswith("03") and "test timed out after 60000 milliseconds" not in (
                directory / "junit.log").read_text():
            raise RuntimeError("third pilot timeout cause changed")
        report["pilots"].append({
            "run": str(directory), "plan": str(plan),
            "requested_faults": requested, "matched": len(matched),
            "applied": len(applied), "strict_same_owner": exact,
            "postfault_targets": post, "junit_exit": manifest["returncode"],
            "junit_seconds": manifest["elapsed_seconds"],
            "junit_timeout_annotation": name.endswith("03"),
            "bug_candidate": False,
            "raw_sha256": {leaf: sha(directory / leaf) for leaf in
                           ("manifest.json", "runtime_trace.jsonl", "junit.log", "jacoco.exec")},
            "plan_sha256": sha(plan),
        })
    temporary = HERE / "archived-pilot-receipt.json.tmp"
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temporary.replace(HERE / "archived-pilot-receipt.json")
    print(json.dumps({"pilots": len(report["pilots"]),
                      "matched": [row["applied"] for row in report["pilots"]],
                      "postfault": [row["postfault_targets"] for row in report["pilots"]]}))


if __name__ == "__main__":
    main()
