#!/usr/bin/env python3
"""Optional, checkpoint-only V5 queue ordering for the original HDFS-28 JUnit.

This successor does not add fault plans or change the trial evaluator.  Its
preview is read-only; --run refuses a live V4 controller or an active trial.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import fcntl
import hashlib
import json
from pathlib import Path
import time

import audit_campaign
import campaign_v1
import file_successor_v4 as V4

HERE = Path(__file__).resolve().parent
C = V4.C
STATE = HERE / "checkpoint.json"
RECEIPT = HERE / "feedback-v5-receipt.json"
V4_SHA = "d45c88f9473ac19b28191c175f664a03f5c6a78124e3d412892bb023716ab61a"
POLICY = "fixed_4_to_1_lanes_parent_target_coverage_io_feedback_v5"
CASE = campaign_v1.CASE


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encoded(value: object) -> bytes:
    return V4.encoded(value)


def group_key(row: dict) -> tuple[str, int, str]:
    point = row["sequence"][-1]
    return (point["marker"], len(row["sequence"]), point["originSourceKey"])


def evidence(state: dict) -> tuple[dict[str, dict], dict[tuple[str, int, str], tuple[int, int]]]:
    parents: dict[str, dict] = {}
    groups: dict[tuple[str, int, str], list[int]] = defaultdict(lambda: [0, 0])
    for trial in state["completed"]:
        parents[trial["id"]] = trial
        group = groups[group_key(trial)]
        group[0] += 1
        group[1] += int(bool(trial["exact_order_applied"] and
                             trial["post_fault_target_checks"][CASE]))
    return parents, {key: tuple(value) for key, value in groups.items()}


def rank(row: dict, parents: dict[str, dict],
         groups: dict[tuple[str, int, str], tuple[int, int]]) -> tuple:
    sequence = row["sequence"]
    parent = parents.get(C.identity(sequence[:-1])) if len(sequence) > 1 else None
    retained_parent = bool(parent and parent["exact_order_applied"] and
                           parent["post_fault_target_checks"][CASE])
    untried = row["retries"] == 0
    # Depth-two descendants of a retained target run are tested first.  A
    # retry remains available, but an untried descendant wins within a tier.
    tier = (4 if len(sequence) == 2 and retained_parent and untried else
            3 if len(sequence) == 2 and retained_parent else
            2 if len(sequence) > 2 and retained_parent and untried else
            1 if untried else 0)
    target_gain = (sum(parent.get("target_related_coverage_gain", {}).values()) +
                   len(parent.get("stable_actor_io_gain", []))) if retained_parent else 0
    global_gain = (sum(parent.get("coverage_gain", {}).get(CASE, {}).values()) +
                   len(parent.get("new_io_families", {}).get(CASE, []))) if retained_parent else 0
    n, wins = groups.get(group_key(row), (0, 0))
    # Smoothed actor/family/depth feedback only breaks ties; unsampled groups
    # retain a nonzero chance, and no queue item is discarded.
    rate = (wins + 1) / (n + 2)
    return (tier, bool(target_gain), target_gain, bool(global_gain),
            global_gain, rate, -row["retries"])


def choose(state: dict) -> int:
    queue = state["queue"]
    if not queue:
        raise ValueError("cannot select from an empty queue")
    offset = len(state["completed"]) - state["file_v4"]["anchor_attempt"]
    rpc = [i for i, row in enumerate(queue)
           if not row["sequence"][-1]["marker"].startswith("FAULT:HDFS_FILE:")]
    file = [i for i, row in enumerate(queue)
            if row["sequence"][-1]["marker"].startswith("FAULT:HDFS_FILE:")]
    want_rpc = offset % 5 < 4
    lane = (rpc if want_rpc else file) or (file if want_rpc else rpc)
    parents, groups = evidence(state)
    best_rank = max(rank(queue[i], parents, groups) for i in lane)
    tied = [i for i in lane if rank(queue[i], parents, groups) == best_rank]
    subset = {**state, "queue": [queue[i] for i in tied]}
    return tied[campaign_v1.base_choose(subset)]


def preview(path: Path) -> dict:
    if sha(HERE / "file_successor_v4.py") != V4_SHA:
        raise RuntimeError("V4 predecessor source SHA changed")
    frozen = path.read_bytes()
    state = json.loads(frozen)
    if state.get("file_v4", {}).get("policy") != V4.POLICY:
        raise RuntimeError("checkpoint is not the V4 original-JUnit ledger")
    if len({row["id"] for row in state["queue"]}) != len(state["queue"]):
        raise RuntimeError("queue contains duplicate IDs")
    old_next = (state["queue"][V4.choose(state)]["id"] if state["queue"] else None)
    new_next = (state["queue"][choose(state)]["id"] if state["queue"] else None)
    if path.read_bytes() != frozen:
        raise RuntimeError("checkpoint changed during preview")
    return {
        "policy": POLICY, "new_source_sha256": sha(Path(__file__)),
        "old_source_sha256": V4_SHA,
        "checkpoint_sha256": hashlib.sha256(frozen).hexdigest(),
        "attempts": len(state["completed"]), "queue": len(state["queue"]),
        "seen": len(state["seen"]), "effective": len(C.effective(state)[CASE]),
        "active": state["active"] is not None, "attempt_cap": state["attempt_cap"],
        "queue_ids_sha256": hashlib.sha256(encoded([x["id"] for x in state["queue"]])).hexdigest(),
        "seen_ids_sha256": hashlib.sha256(encoded(state["seen"])).hexdigest(),
        "completed_ids_sha256": hashlib.sha256(encoded([x["id"] for x in state["completed"]])).hexdigest(),
        "v4_next_id": old_next, "v5_next_id": new_next,
        "checkpoint_unchanged": True,
    }


def handoff() -> dict:
    state = json.loads(STATE.read_text())
    if state["attempt_cap"] != 512 or sha(HERE / "file_successor_v4.py") != V4_SHA:
        raise RuntimeError("V4 ledger or predecessor source changed")
    if RECEIPT.exists():
        existing = json.loads(RECEIPT.read_text())
        if (existing["new_source_sha256"] != sha(Path(__file__)) or
                existing["old_source_sha256"] != V4_SHA or
                existing["policy"] != POLICY or
                len(state["completed"]) < existing["attempts"]):
            raise RuntimeError("existing V5 policy receipt conflicts with ledger")
        # A later V5 restart may have an active reserved plan.  The original
        # runner resumes it through run_trial; only the first handoff must be
        # at an empty complete boundary.
        return existing
    if state["active"] is not None:
        raise RuntimeError("first V5 handoff is not at an idle complete checkpoint")
    if C.stop_reason(state) is not None:
        raise RuntimeError("V4 already reached a natural terminal condition")
    next_dir = HERE / "runs" / ("trial-%04d" % (len(state["completed"]) + 1))
    if next_dir.exists() and any(next_dir.iterdir()):
        raise RuntimeError("next trial already has a plan, driver, or trace")
    for number in (len(state["completed"]), len(state["completed"]) + 1):
        if C.child_java_started(HERE / "runs" / ("trial-%04d" % number)):
            raise RuntimeError("case JUnit still alive")
    prior = STATE.read_bytes()
    if audit_campaign.main() != 0:
        raise RuntimeError("full independent raw audit rejected V4 checkpoint")
    audit_file = HERE / "raw-audit.json"
    audit = json.loads(audit_file.read_text())
    if (audit["errors"] or audit["checkpoint_sha256"] != hashlib.sha256(prior).hexdigest()
            or audit["completed_attempts"] != len(state["completed"])
            or STATE.read_bytes() != prior):
        raise RuntimeError("raw audit and frozen checkpoint disagree")
    frozen_preview = preview(STATE)
    receipt = {**frozen_preview, "raw_audit_sha256": sha(audit_file),
               "activated_at_utc": C.utc(), "receipt_schema": 1}
    V4.V3.V2.durable(RECEIPT, encoded(receipt))
    if STATE.read_bytes() != prior:
        raise RuntimeError("handoff changed checkpoint")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--checkpoint", type=Path, default=STATE)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--wall-seconds", type=int, default=43200)
    parser.add_argument("--poll-seconds", type=int, default=20)
    args = parser.parse_args()
    if args.preview:
        print(json.dumps(preview(args.checkpoint), sort_keys=True))
        return
    if not args.run or args.checkpoint != STATE:
        parser.error("--run requires the live default checkpoint")
    with C.LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = handoff()
        C.MIN_FREE_BYTES = 10 * 1024**3
        C.choose, C.admit = choose, V4.V3.admit
        state = json.loads(STATE.read_text())
        C.write_summary(state)
        print(json.dumps({"policy": POLICY, "handoff_sha256": receipt["checkpoint_sha256"],
                          "attempt_cap": state["attempt_cap"]}), flush=True)
        deadline = time.monotonic() + args.wall_seconds
        while time.monotonic() < deadline:
            reason = C.stop_reason(state)
            if reason:
                state["stop_reason"] = reason
                C.atomic_json(STATE, state)
                C.write_summary(state)
                print("terminal " + reason, flush=True)
                return
            if not C.run_trial(state):
                time.sleep(min(args.poll_seconds, max(0, deadline - time.monotonic())))
        print("feedback V5 wall cap reached; resume unchanged checkpoint", flush=True)


if __name__ == "__main__":
    main()
