#!/usr/bin/env python3
"""One-time, fail-closed HBASE-22 queue-priority migration at a JVM-free checkpoint."""
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAMPAIGN = HERE / "campaigns/HBASE-22"
EVIDENCE = HERE / "evidence/HBASE-22"
CHECKPOINT = CAMPAIGN / "checkpoint.json"
INFLIGHT = CAMPAIGN / "inflight.json"
PAUSE = CAMPAIGN / "PAUSE"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not PAUSE.is_file():
        raise RuntimeError("PAUSE gate must be active")
    state = json.loads(CHECKPOINT.read_text())
    inflight = json.loads(INFLIGHT.read_text())
    if state.get("loss_priority_policy") or inflight["id"] != "r%03d" % (len(state["trials"]) + 1):
        raise RuntimeError("Unexpected migration state")
    if sum(item["plan"] == inflight["plan"] for item in state["queue"]) != 1:
        raise RuntimeError("Selected plan not exactly once in queue")
    if (HERE / "runs" / ("table-HBASE-22-" + inflight["id"])).exists():
        raise RuntimeError("Selected trial already has a run directory")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    before_path = EVIDENCE / "checkpoint-before-loss-priority.json"
    inflight_path = EVIDENCE / "unstarted-inflight-before-loss-priority.json"
    if before_path.exists() or inflight_path.exists():
        raise RuntimeError("Migration evidence already exists")
    shutil.copyfile(CHECKPOINT, before_path)
    shutil.copyfile(INFLIGHT, inflight_path)
    before = {key: digest(state[key]) for key in ("queue", "seen")}
    budget = {key: state[key] for key in ("max_effective", "max_faults", "max_attempts")}
    state["loss_priority_policy"] = "same_site_target_loss_v1"
    state["loss_priority_migrated_after_attempt"] = len(state["trials"])
    state["priority_policy"] = "healthy_guard_distance_with_periodic_exploration_and_same_site_loss_v2"
    tmp = CHECKPOINT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, CHECKPOINT)
    INFLIGHT.unlink()
    after = json.loads(CHECKPOINT.read_text())
    if before != {key: digest(after[key]) for key in before} or budget != {key: after[key] for key in budget}:
        raise RuntimeError("Queue, seen, or budget unexpectedly changed")
    if state["trials"] != after["trials"] or state["effective"] != after["effective"]:
        raise RuntimeError("Completed-trial ledger changed")
    receipt = {
        "time_unix": time.time(), "completed_attempts": len(after["trials"]),
        "effective": after["effective"], "queue_length": len(after["queue"]),
        "inflight_unstarted_id": inflight["id"],
        "inflight_plan_count_retained": sum(x["plan"] == inflight["plan"] for x in after["queue"]),
        "queue_sha256": before["queue"], "seen_sha256": before["seen"],
        "budget_unchanged": budget,
        "before_checkpoint_sha256": file_digest(before_path),
        "after_checkpoint_sha256": file_digest(CHECKPOINT),
        "unstarted_inflight_sha256": file_digest(inflight_path),
        "controller_sha256": file_digest(HERE / "controller.py"),
        "runner_sha256": file_digest(HERE / "run.sh"),
        "agent_sha256": file_digest(HERE / "agent.jar"),
    }
    (EVIDENCE / "loss-priority-migration-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
