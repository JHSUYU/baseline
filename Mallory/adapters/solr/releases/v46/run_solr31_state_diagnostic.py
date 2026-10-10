#!/usr/bin/env python3
"""Run a bounded, exact one-fault SOLR-31 watcher diagnosis.

This bypasses automatic graph-frontier mutation because the proposed cache
dependency crosses threads and is not an observed Mallory graph edge.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path

from Mallory.core.campaign import _run_trial, validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    validate_config(config)
    verify_runtime_artifacts(config)
    candidate = config["source_backed_state_candidate"]
    plan_spec = config["diagnostic_plan"]
    receipt = Path(plan_spec["healthy_receipt"])
    assert sha(receipt) == plan_spec["healthy_receipt_sha256"]
    healthy = json.loads(receipt.read_text())
    assert healthy["status"] == "state_timeline_admitted"
    assert healthy["evidence_kind"] == "observed_state_timeline_not_graph_edge"
    assert plan_spec["node"] == healthy["target"]["node"]
    assert plan_spec["epoch"] == healthy["target"]["epoch"]
    assert plan_spec["site"] == candidate["door_site"]
    qualified = [row for row in healthy["qualified_watches_before_target"]
                 if row["door_ordinal"] == plan_spec["door_ordinal"] and
                 row["before"]["leader_state"] == "active" and
                 row["after"]["leader_state"] != "active"]
    assert len(qualified) == 1, qualified
    assert config["budget"]["max_faults_per_trial"] == 1
    assert 1 <= config["budget"]["trials"] <= 6
    assert not args.out.exists(), "diagnostic output must be fresh"
    args.out.mkdir(parents=True)
    lock_fd = os.open(args.out / ".diagnostic.lock", os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        write_json(args.out / "config.json", config)
        result = {"schema_version": 1, "case_id": "SOLR-31", "status": "running",
                  "healthy_receipt_sha256": sha(receipt), "trial_ids": [],
                  "plan": plan_spec}
        write_json(args.out / "result.json", result)
        point = {"site": plan_spec["site"], "node": plan_spec["node"],
                 "epoch": plan_spec["epoch"], "door_ordinal": plan_spec["door_ordinal"]}
        for trial_id in range(1, config["budget"]["trials"] + 1):
            fault = {"fault_id": f"solr31-v46p-r{trial_id:04d}", "point": point,
                     "fault_type": "EXCEPTION",
                     "exception_class": candidate["exception_class"]}
            trial = _run_trial(config, args.out, trial_id, [fault], lambda _pid: None, None)
            assert trial["case_id"] == "SOLR-31"
            result["trial_ids"].append(trial_id)
            result["last_trial_status"] = trial["feedback"]["status"]
            write_json(args.out / "result.json", result)
        result["status"] = "diagnostic_budget_complete"
        write_json(args.out / "result.json", result)
        print(json.dumps({"status": result["status"], "trial_ids": result["trial_ids"]}))
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


if __name__ == "__main__":
    main()
