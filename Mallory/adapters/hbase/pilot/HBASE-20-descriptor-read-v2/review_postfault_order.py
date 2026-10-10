#!/usr/bin/env python3
"""Describe postfault target order without inferring a causal graph edge."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path


BASE = Path("/users/ZhenyuLi/baseline")
TERMINAL = {"budget_exhausted", "queue_exhausted"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def review_trial(directory: Path, check_sites: set[str], throw_site: str) -> dict:
    trial_path = directory / "result.json"
    trial = json.loads(trial_path.read_text())
    trace_path = directory / "events.jsonl.gz"
    evidence = trial["events_evidence"]
    if sha(trace_path) != evidence["gzip_sha256"]:
        raise ValueError(f"trial gzip SHA mismatch: {directory.name}")
    raw_sha = hashlib.sha256()
    faults, checks, throws = [], [], []
    with gzip.open(trace_path, "rb") as trace:
        for line in trace:
            raw_sha.update(line)
            event = json.loads(line)
            if event.get("type") == "FAULT_APPLIED":
                faults.append(event)
            elif event.get("type") == "TARGET_CHECK" and event.get("site") in check_sites:
                checks.append(event)
            elif event.get("type") == "TARGET_THROW" and event.get("site") == throw_site:
                throws.append(event)
    if raw_sha.hexdigest() != evidence["raw_sha256"]:
        raise ValueError(f"trial raw SHA mismatch: {directory.name}")
    applied = set(trial["feedback"].get("applied_fault_ids", []))
    if {event.get("fault_id") for event in faults} != applied:
        raise ValueError(f"applied-fault IDs differ: {directory.name}")
    last_fault_seq = max((event["seq"] for event in faults), default=None)
    later = ([check for check in checks if check["seq"] > last_fault_seq]
             if last_fault_seq is not None else [])
    same_node = [check for check in later if any(
        (check.get("node"), check.get("epoch")) ==
        (fault.get("node"), fault.get("epoch")) for fault in faults)]
    same_occurrence = [check for check in same_node if any(
        (check.get("node"), check.get("epoch"), check.get("occurrence"),
         check.get("thread_id")) ==
        (fault.get("node"), fault.get("epoch"), fault.get("occurrence"),
         fault.get("thread_id")) for fault in faults)]
    return {
        "trial_id": int(directory.name[1:]),
        "trial_result_sha256": sha(trial_path),
        "trace_gzip_sha256": sha(trace_path),
        "applied_fault_count": len(faults),
        "exact_check_count": len(checks),
        "exact_throw_count": len(throws),
        "last_fault_seq": last_fault_seq,
        "postfault_exact_check_ids": [event["id"] for event in later],
        "same_node_postfault_check_ids": [event["id"] for event in same_node],
        "same_occurrence_postfault_check_ids": [event["id"] for event in same_occurrence],
    }


def review(number: int) -> dict:
    case = f"HBASE-{number}"
    campaign = BASE / "data/mallory" / case / "campaigns/descriptor-read-v2-full"
    result_path = campaign / "result.json"
    result = json.loads(result_path.read_text())
    config_path = campaign / "config.json"
    config = json.loads(config_path.read_text())
    if (result.get("case_id") != case or result.get("status") not in TERMINAL or
            result.get("calibration_only") is not False):
        raise ValueError("campaign has no natural full terminal")
    count = result["fault_trials_completed"]
    sites = set(config["target"]["check_sites"])
    throw_site = config["target"]["throw_site"]
    rows = [review_trial(campaign / "trials" / f"r{trial_id:04d}", sites, throw_site)
            for trial_id in range(1, count + 1)]
    summary = {
        "schema_version": 1,
        "case_id": case,
        "scope": "event_time_order_only_no_causal_graph_claim",
        "status": result["status"],
        "campaign_result_sha256": sha(result_path),
        "campaign_config_sha256": sha(config_path),
        "reviewer_sha256": sha(Path(__file__)),
        "fault_trials_completed": count,
        "trials_with_applied_fault": sum(row["applied_fault_count"] > 0 for row in rows),
        "trials_with_postfault_exact_check": sum(
            bool(row["postfault_exact_check_ids"]) for row in rows),
        "trials_with_same_node_postfault_check": sum(
            bool(row["same_node_postfault_check_ids"]) for row in rows),
        "trials_with_same_occurrence_postfault_check": sum(
            bool(row["same_occurrence_postfault_check_ids"]) for row in rows),
        "trials_with_exact_throw": sum(row["exact_throw_count"] > 0 for row in rows),
        "trials": rows,
    }
    path = campaign / "postfault-order-review.json"
    if path.exists():
        if json.loads(path.read_text()) != summary:
            raise ValueError("existing postfault order review differs")
    else:
        temporary = path.with_name(".postfault-order-review.json.tmp")
        with temporary.open("w") as output:
            json.dump(summary, output, sort_keys=True, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=int, choices=(19, 20))
    args = parser.parse_args()
    print(json.dumps({key: value for key, value in review(args.case).items()
                      if key != "trials"}, sort_keys=True))
