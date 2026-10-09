#!/usr/bin/env python3
"""One-time, trial-boundary HDFS-43 selector diversity migration."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path

from run_campaign import CAMP, STATE, atomic_json, now

PAUSE = CAMP / "pause.request"
BEFORE = CAMP / "checkpoint.before-api-diversity.json"
AFTER = CAMP / "checkpoint.after-api-diversity.json"
RECEIPT = CAMP / "selection-policy-migration.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def preserved(state: dict) -> str:
    body = {key: state[key] for key in ("completed", "queue", "seen")}
    return sha(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())


def main() -> None:
    if any(path.exists() for path in (BEFORE, AFTER, RECEIPT)):
        raise RuntimeError("HDFS-43 API diversity migration already recorded")
    if not PAUSE.is_file():
        raise RuntimeError("campaign must be paused at a complete trial boundary")
    before_bytes = STATE.read_bytes()
    state = json.loads(before_bytes)
    completed = state["completed"]
    if (len(completed) != 18 or state["active"] is not None or
            state["stop_reason"] != "paused_by_case_owner" or
            state.get("selection_policy") or
            sum(row["strict_injection"] for row in completed) != 14 or
            sum(row["target_after_fault_same_actor"] for row in completed) != 11):
        raise RuntimeError("not the reviewed HDFS-43 trial-18 checkpoint")
    prior_hash = preserved(state)
    last_apis = Counter(row["sequence"][-1]["api"] for row in completed)
    queued_apis = Counter(item["sequence"][-1]["api"] for item in state["queue"])
    write_bytes(BEFORE, before_bytes)
    state["selection_policy"] = {
        "name": "api_diversity_v1",
        "start_after_completed": 18,
        "client_every_nth_selection": 4,
        "forced_api": "truncate",
        "fallback": "coverage_io_score_if_no_client_plan",
        "other_slots": "original_coverage_io_score",
    }
    state["stop_reason"] = None
    atomic_json(STATE, state)
    after_bytes = STATE.read_bytes()
    write_bytes(AFTER, after_bytes)
    if preserved(state) != prior_hash:
        raise RuntimeError("queue, seen selectors, or completed trials changed")
    receipt = {
        "case_id": "HDFS-43", "migrated_at_utc": now(),
        "before_checkpoint_sha256": sha(before_bytes),
        "after_checkpoint_sha256": sha(after_bytes),
        "preserved_queue_seen_completed_sha256": prior_hash,
        "completed_trials_preserved": len(completed),
        "strict_trials_preserved": 14,
        "post_fault_same_actor_trials_preserved": 11,
        "completed_last_api_counts": dict(last_apis),
        "queued_last_api_counts": dict(queued_apis),
        "selection_policy": state["selection_policy"],
        "target_oracle_injection_and_coverage_rules_changed": False,
    }
    atomic_json(RECEIPT, receipt)
    PAUSE.unlink()
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
