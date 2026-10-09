#!/usr/bin/env python3
"""Write a SHA-bound sidecar for exact ZooKeeper FOLLOWING fault continuations."""

import argparse
import json
from pathlib import Path

from Mallory.adapters.zookeeper.audit_following_retry import (
    verified_retry_edges, verified_retry_target_paths,
)
from Mallory.adapters.zookeeper.audit_postfault_actor import read, sha, trace


def audit(campaign: Path, output: Path) -> dict:
    result_path = campaign / "result.json"
    offline_path = campaign / "offline-causal-audit.json"
    config_path = campaign / "config.json"
    result, offline, config = (read(result_path), read(offline_path), read(config_path))
    if (result["case_id"] != config["case_id"] or
            offline["campaign_result_sha256"] != sha(result_path)):
        raise ValueError("campaign or frozen offline audit does not match")
    checks = set(config["target"]["check_sites"])
    rows = []
    for item in result["trials"]:
        ident = item["trial_id"]
        trial_dir = campaign / "trials" / f"r{ident:04d}"
        trial_result_path = trial_dir / "result.json"
        trial_result = read(trial_result_path)
        events = trace(trial_dir, trial_result)
        edges = verified_retry_edges(events)
        paths = verified_retry_target_paths(events, checks)
        rows.append({
            "trial_id": ident,
            "trial_result_sha256": sha(trial_result_path),
            "trace_raw_sha256": trial_result["events_evidence"]["raw_sha256"],
            "applied_fault_event_ids": [event["id"] for event in events
                                        if event.get("type") == "FAULT_APPLIED"],
            "verified_retry_edges": edges,
            "postfault_retry_target_paths": paths,
        })
    record = {
        "schema_version": 1,
        "case_id": config["case_id"],
        "status": "postfault_retry_target_proven" if any(
            row["postfault_retry_target_paths"] for row in rows) else
                  "no_proven_postfault_retry_target_path",
        "campaign_result": str(result_path.resolve()),
        "campaign_result_sha256": sha(result_path),
        "offline_audit": str(offline_path.resolve()),
        "offline_audit_sha256": sha(offline_path),
        "config": str(config_path.resolve()),
        "config_sha256": sha(config_path),
        "source_overlay_receipt": config["source_overlay_receipt"],
        "source_overlay_receipt_sha256": config["source_overlay_receipt_sha256"],
        "verified_retry_edge_trials": sum(bool(row["verified_retry_edges"]) for row in rows),
        "proven_postfault_path_trials": sum(bool(row["postfault_retry_target_paths"]) for row in rows),
        "trials": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(args.campaign.resolve(), args.output.resolve())
