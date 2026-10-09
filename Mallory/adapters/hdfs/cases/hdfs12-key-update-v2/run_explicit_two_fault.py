#!/usr/bin/env python3
"""Run one SHA-pinned HDFS-12 H1/H2 diagnostic through the frozen core trial runner."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

from Mallory.core.campaign import (_alive_process_group, _run_trial, atomic_json,
                                   load_static_frontier, validate_config)


HERE = Path(__file__).resolve().parent
CONFIG = HERE / "HDFS-12-v2-two-fault-diagnostic.json"
OUTPUT = Path("/tmp/mallory-hdfs12-key-update-v2-two-fault")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    config = json.loads(CONFIG.read_text())
    validate_config(config)
    load_static_frontier(config)
    plan = config["manual_sequence"]
    expected = config["pilot_gate"]["expected_healthy_doors"]
    if (len(plan) != 2 or [fault["point"] for fault in plan] != expected or
            [fault["point"]["door_ordinal"] for fault in plan] != [5, 6] or
            any(fault["fault_type"] != "EXCEPTION" or
                fault["exception_class"] != "java.io.IOException" for fault in plan)):
        raise RuntimeError("diagnostic plan is not the exact H1/H2 IOException sequence")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(OUTPUT / ".diagnostic.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        checkpoint_path = OUTPUT / "checkpoint.json"
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text())
            if checkpoint.get("config_sha256") != sha(CONFIG):
                raise RuntimeError("diagnostic config changed; use a new output directory")
            if checkpoint["status"] == "diagnostic_complete":
                print(json.dumps({"status": "diagnostic_complete", "output": str(OUTPUT),
                                  "trial_id": checkpoint["completed_trial"]}, sort_keys=True))
                return
            old_pid = checkpoint.get("running_pid")
            if old_pid and _alive_process_group(old_pid):
                raise RuntimeError(f"prior diagnostic JVM process group still alive: {old_pid}")
            trial_id = int(checkpoint["next_trial"])
            previous = OUTPUT / "trials" / f"r{trial_id:04d}"
            if previous.exists():
                interrupted = OUTPUT / "interrupted"
                interrupted.mkdir(exist_ok=True)
                previous.rename(interrupted / f"r{trial_id:04d}-{int(time.time())}")
                trial_id += 1
        else:
            trial_id = 1
            atomic_json(OUTPUT / "config.json", config)
        checkpoint = {"schema_version": 1, "case_id": "HDFS-12",
                      "status": "running", "config_sha256": sha(CONFIG),
                      "one_fault_negative_receipt_sha256":
                          config["pilot_gate"]["one_fault_negative_receipt_sha256"],
                      "next_trial": trial_id, "running_pid": None,
                      "plan": plan, "updated_at": time.time()}
        atomic_json(checkpoint_path, checkpoint)

        def save_running(pid: int) -> None:
            checkpoint["running_pid"] = pid
            checkpoint["updated_at"] = time.time()
            atomic_json(checkpoint_path, checkpoint)

        try:
            trial = _run_trial(config, OUTPUT, trial_id, plan, save_running,
                               {"nodes": ["hdfs-cluster-2/dn0"]})
        except BaseException as error:
            checkpoint["status"] = "controller_error"
            checkpoint["error"] = repr(error)
            checkpoint["updated_at"] = time.time()
            atomic_json(checkpoint_path, checkpoint)
            raise
        feedback = trial["feedback"]
        summary = {"schema_version": 1, "case_id": "HDFS-12",
                   "status": "diagnostic_complete", "trial_id": trial_id,
                   "config_sha256": sha(CONFIG),
                   "trial_result_sha256": sha(OUTPUT / "trials" / f"r{trial_id:04d}" / "result.json"),
                   "duration_seconds": trial["elapsed_seconds"],
                   "junit_status": trial["junit_validation"]["status"],
                   "junit_tests": trial["junit_validation"].get("tests"),
                   "junit_errors": trial["junit_validation"].get("errors"),
                   "junit_failures": trial["junit_validation"].get("failures"),
                   "all_faults_effective": feedback.get("all_faults_effective"),
                   "fault_identity_valid": feedback.get("fault_identity_valid"),
                   "target_reached": feedback.get("target_reached"),
                   "target_exception_candidate": feedback.get("target_exception_candidate"),
                   "one_fault_negative_receipt_sha256":
                       config["pilot_gate"]["one_fault_negative_receipt_sha256"],
                   "quality_status": "diagnostic_only_pending_timeline_review"}
        atomic_json(OUTPUT / "result.json", summary)
        checkpoint.update({"status": "diagnostic_complete", "running_pid": None,
                           "completed_trial": trial_id, "next_trial": trial_id + 1,
                           "updated_at": time.time()})
        atomic_json(checkpoint_path, checkpoint)
        print(json.dumps({"status": summary["status"], "trial_id": trial_id,
                          "all_faults_effective": summary["all_faults_effective"],
                          "target_reached": summary["target_reached"],
                          "target_exception_candidate":
                              summary["target_exception_candidate"]}, sort_keys=True))
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    main()
