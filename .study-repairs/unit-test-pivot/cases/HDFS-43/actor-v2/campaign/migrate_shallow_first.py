#!/usr/bin/env python3
"""Prefer observed, shallower pending fault plans after a complete trial."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path

from run_campaign import CAMP, STATE, atomic_json, now


PAUSE = CAMP / "pause.request"
BEFORE = CAMP / "checkpoint.before-shallow-first.json"
AFTER = CAMP / "checkpoint.after-shallow-first.json"
RECEIPT = CAMP / "shallow-first-migration.json"
RAW = CAMP / "raw-artifact-manifest.before-shallow-first.json"


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


def artifact_manifest(count: int) -> dict[str, str]:
    files = [CAMP / "trial-ledger.csv"]
    for number in range(1, count + 1):
        trial = CAMP / f"trial-{number:03d}"
        files.extend((trial / "trial-result.json", trial / "manifest.json",
                      trial / "trace/runtime_trace.jsonl",
                      CAMP / "plans" / f"trial-{number:03d}.tsv"))
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError(f"completed artifact set incomplete: {missing}")
    return {str(path.relative_to(CAMP)): sha(path.read_bytes()) for path in files}


def coverage_stats(completed: list[dict]) -> dict:
    novel = {identifier for row in completed
             if row["strict_injection"] and row["target_after_fault_same_actor"]
             for identifier in row["new_coverage_ids"]}
    return {
        "effective_trials_with_production_gain": sum(
            bool(row["new_coverage_ids"]) for row in completed
            if row["strict_injection"] and row["target_after_fault_same_actor"]),
        "new_production_coverage_ids_by_kind": dict(Counter(
            identifier.split("\t", 1)[0] for identifier in novel)),
        "new_stable_io_family_ids": len({identifier for row in completed
            if row["strict_injection"] and row["target_after_fault_same_actor"]
            for identifier in row["new_io_family_ids"]}),
    }


def main() -> None:
    if any(path.exists() for path in (BEFORE, AFTER, RECEIPT, RAW)):
        raise RuntimeError("HDFS-43 shallow-first migration already recorded")
    if not PAUSE.is_file():
        raise RuntimeError("campaign must pause at a complete trial boundary")
    before_bytes = STATE.read_bytes()
    state = json.loads(before_bytes)
    completed = state["completed"]
    count = len(completed)
    old_policy = state.get("selection_policy")
    queue = state["queue"]
    if (count < 108 or state["active"] is not None or
            state["stop_reason"] != "paused_by_case_owner" or
            not old_policy or old_policy.get("name") != "api_diversity_v2" or
            not queue or any(item["sequence"][-1]["api"] != "truncate"
                             for item in queue) or
            [row["id"] for row in completed] !=
            [f"trial-{number:03d}" for number in range(1, count + 1)]):
        raise RuntimeError("not the reviewed all-client HDFS-43 checkpoint")
    prior_hash = preserved(state)
    artifacts = artifact_manifest(count)
    artifacts_hash = sha(json.dumps(artifacts, sort_keys=True,
                                   separators=(",", ":")).encode())
    strict = sum(row["strict_injection"] for row in completed)
    effective = sum(row["strict_injection"] and
                    row["target_after_fault_same_actor"] for row in completed)
    write_bytes(BEFORE, before_bytes)
    atomic_json(RAW, {"case_id": "HDFS-43", "trial_count": count,
                      "files": artifacts, "manifest_sha256": artifacts_hash})
    state["selection_policy"] = {
        "name": "observed_io_shallow_first_v1",
        "start_after_completed": count,
        "prefer_min_depth": True,
        "within_depth": "original_coverage_io_score_and_waiting_age",
        "remaining_depths": "all_queued_depths_retained_for_later_selection",
    }
    state["stop_reason"] = None
    atomic_json(STATE, state)
    after_bytes = STATE.read_bytes()
    write_bytes(AFTER, after_bytes)
    if preserved(state) != prior_hash or artifact_manifest(count) != artifacts:
        raise RuntimeError("completed, queue, seen, ledger, or raw trials changed")
    receipt = {
        "case_id": "HDFS-43", "migrated_at_utc": now(),
        "before_checkpoint_sha256": sha(before_bytes),
        "after_checkpoint_sha256": sha(after_bytes),
        "preserved_queue_seen_completed_sha256": prior_hash,
        "preserved_raw_artifact_manifest_sha256": artifacts_hash,
        "completed_trials_preserved": count,
        "strict_trials_preserved": strict,
        "post_last_fault_same_actor_trials_preserved": effective,
        "completed_coverage_and_io": coverage_stats(completed),
        "queued_fault_depth_counts": dict(Counter(
            len(item["sequence"]) for item in queue)),
        "queued_last_api_counts": dict(Counter(
            item["sequence"][-1]["api"] for item in queue)),
        "previous_selection_policy": old_policy,
        "selection_policy": state["selection_policy"],
        "target_oracle_injection_and_coverage_rules_changed": False,
    }
    atomic_json(RECEIPT, receipt)
    PAUSE.unlink()
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
