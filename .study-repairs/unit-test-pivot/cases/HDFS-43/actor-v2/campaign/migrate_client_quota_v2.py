#!/usr/bin/env python3
"""Increase the bounded truncate quota at a complete trial-40 boundary."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path

from run_campaign import CAMP, STATE, atomic_json, now


PAUSE = CAMP / "pause.request"
BEFORE = CAMP / "checkpoint.before-client-quota-v2.json"
AFTER = CAMP / "checkpoint.after-client-quota-v2.json"
RECEIPT = CAMP / "client-quota-v2-migration.json"
RAW = CAMP / "raw-artifact-manifest.before-client-quota-v2.json"


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


def artifact_manifest() -> dict[str, str]:
    files = [CAMP / "trial-ledger.csv"]
    for number in range(1, 41):
        trial = CAMP / f"trial-{number:03d}"
        files.extend((trial / "trial-result.json", trial / "manifest.json",
                      trial / "trace/runtime_trace.jsonl",
                      CAMP / "plans" / f"trial-{number:03d}.tsv"))
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        raise RuntimeError(f"trial-40 artifact set incomplete: {missing}")
    return {str(path.relative_to(CAMP)): sha(path.read_bytes()) for path in files}


def main() -> None:
    if any(path.exists() for path in (BEFORE, AFTER, RECEIPT, RAW)):
        raise RuntimeError("HDFS-43 client quota V2 migration already recorded")
    if not PAUSE.is_file():
        raise RuntimeError("campaign must pause at a complete trial boundary")
    before_bytes = STATE.read_bytes()
    state = json.loads(before_bytes)
    completed = state["completed"]
    old_policy = state.get("selection_policy")
    if (len(completed) != 40 or state["active"] is not None or
            state["stop_reason"] != "paused_by_case_owner" or
            not old_policy or old_policy.get("name") != "api_diversity_v1" or
            old_policy.get("start_after_completed") != 18 or
            old_policy.get("client_every_nth_selection") != 4 or
            [row["id"] for row in completed] !=
            [f"trial-{number:03d}" for number in range(1, 41)]):
        raise RuntimeError("not the reviewed HDFS-43 trial-40 checkpoint")
    prior_hash = preserved(state)
    artifacts = artifact_manifest()
    artifacts_hash = sha(json.dumps(artifacts, sort_keys=True,
                                   separators=(",", ":")).encode())
    strict = sum(row["strict_injection"] for row in completed)
    effective = sum(row["strict_injection"] and
                    row["target_after_fault_same_actor"] for row in completed)
    write_bytes(BEFORE, before_bytes)
    atomic_json(RAW, {"case_id": "HDFS-43", "trial_count": 40,
                      "files": artifacts, "manifest_sha256": artifacts_hash})
    state["selection_policy"] = {
        "name": "api_diversity_v2",
        "start_after_completed": 40,
        "client_every_nth_selection": 2,
        "forced_api": "truncate",
        "fallback": "coverage_io_score_if_no_client_plan",
        "other_slots": "original_coverage_io_score",
    }
    state["stop_reason"] = None
    atomic_json(STATE, state)
    after_bytes = STATE.read_bytes()
    write_bytes(AFTER, after_bytes)
    if preserved(state) != prior_hash or artifact_manifest() != artifacts:
        raise RuntimeError("completed, queue, seen, ledger, or raw trials changed")
    receipt = {
        "case_id": "HDFS-43", "migrated_at_utc": now(),
        "before_checkpoint_sha256": sha(before_bytes),
        "after_checkpoint_sha256": sha(after_bytes),
        "preserved_queue_seen_completed_sha256": prior_hash,
        "preserved_raw_artifact_manifest_sha256": artifacts_hash,
        "completed_trials_preserved": 40,
        "strict_trials_preserved": strict,
        "post_last_fault_same_actor_trials_preserved": effective,
        "completed_last_api_counts": dict(Counter(
            row["sequence"][-1]["api"] for row in completed)),
        "queued_last_api_counts": dict(Counter(
            item["sequence"][-1]["api"] for item in state["queue"])),
        "previous_selection_policy": old_policy,
        "selection_policy": state["selection_policy"],
        "target_oracle_injection_and_coverage_rules_changed": False,
    }
    atomic_json(RECEIPT, receipt)
    PAUSE.unlink()
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
