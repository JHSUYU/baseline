#!/usr/bin/env python3
"""Resume an exhausted alternate JUnit queue with observed, target-before RPC points.

No existing attempt, queue entry, or seen identity is rewritten. The new
single-fault points are selected only from original-JUnit traces with a
physical recovery owner and a later HDFS-28 guard on that same recovery root.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time

import audit_campaign
import campaign_v1

HERE = Path(__file__).resolve().parent
C = campaign_v1.campaign
STATE = HERE / "checkpoint.json"
RECEIPT = HERE / "successor-v2-receipt.json"
INTENT = HERE / "successor-v2-intent.json"
SOURCE_SHA = "eb086e62aa536a4a778f59382c6f1f56a5f776a6d5dda435aadbde795dff945d"
POLICY = "target_before_hdfs_rpc_singleton_then_same_actor_descendant_4rpc_1other_v2"
MAX_NEW_SINGLETON = 64


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def durable(path: Path, data: bytes) -> None:
    pending = path.with_name(path.name + ".tmp")
    with pending.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def discover(state: dict, trials: list[tuple[int, dict]] | None = None) -> list[dict]:
    """Return never-tested singleton selectors, with original trace provenance."""
    seen = set(state["seen"])
    found = {}
    source = trials if trials is not None else list(enumerate(state["completed"], 1))
    for number, trial in source:
        if not (trial["exact_order_applied"] and
                trial["post_fault_target_checks"]["HDFS-28"]):
            continue
        events = C.trace(Path(trial["run"]))
        for event in events:
            if (event.get("event") != "FAULT_POINT_OBSERVED"
                    or event.get("marker") != "FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY"
                    or not C.identity_verified(events, event)
                    or "HDFS-28" not in C.later_targets(event, events)):
                continue
            for kind in C.RPC_ERRORS:
                point = C.point(event, kind)
                ident = C.identity([point])
                if ident not in seen and ident not in found:
                    found[ident] = {"id": ident, "sequence": [point],
                                    "source_trial": number, "io_seq": event["seq"],
                                    "physical_owner": C.origin(event),
                                    "recovery_root": C.root(event)}
    return sorted(found.values(), key=lambda x: (x["source_trial"], x["io_seq"],
                                                 x["sequence"][0]["faultType"]))


def add_singletons(state: dict, candidates: list[dict]) -> list[dict]:
    inserted = []
    budget = MAX_NEW_SINGLETON - state["scheduler_v2"]["new_singletons_added"]
    for candidate in candidates[:max(0, budget)]:
        before = len(state["seen"])
        C.add(state, candidate["sequence"], priority=12, eligible=("HDFS-28",))
        if len(state["seen"]) > before:
            state["queue"][-1]["created"] = (
                state["scheduler_v2"]["anchor_attempt"] +
                (state["scheduler_v2"]["new_singletons_added"] + len(inserted)) / 1000)
            inserted.append(candidate)
    state["scheduler_v2"]["new_singletons_added"] += len(inserted)
    return inserted


base_admit = C.admit
base_choose = C.choose


def admit(state: dict, trial: dict) -> None:
    base_admit(state, trial)
    if (not trial["exact_order_applied"] or
            not trial["post_fault_target_checks"]["HDFS-28"]):
        return
    if state["scheduler_v2"]["new_singletons_added"] < MAX_NEW_SINGLETON:
        add_singletons(state, discover(state, [(len(state["completed"]), trial)]))


def choose(state: dict) -> int:
    queue = state["queue"]
    ordinal = len(state["completed"]) - state["scheduler_v2"]["anchor_attempt"]
    want_rpc = ordinal % 5 < 4
    rpc = [i for i, item in enumerate(queue)
           if item["sequence"][-1]["marker"] == "FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY"]
    other = [i for i in range(len(queue)) if i not in rpc]
    lane = (rpc if want_rpc else other) or (other if want_rpc else rpc)
    singleton = [i for i in lane if i in rpc and len(queue[i]["sequence"]) == 1]
    descendants = [i for i in lane if i in rpc and len(queue[i]["sequence"]) > 1]
    choices = singleton or descendants or lane
    subset = {**state, "queue": [queue[i] for i in choices]}
    return choices[base_choose(subset)]


def handoff() -> dict:
    if sha((HERE / "campaign_v1.py").read_bytes()) != SOURCE_SHA:
        raise RuntimeError("original alternate controller SHA changed")
    if RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text())
        state = json.loads(STATE.read_text())
        if (state.get("scheduler_v2", {}).get("policy") != POLICY
                or receipt.get("successor_source_sha256") != sha(Path(__file__).read_bytes())
                or len(state["completed"]) < receipt["anchor_attempt"]):
            raise RuntimeError("existing successor receipt disagrees with checkpoint")
        return receipt
    if INTENT.exists():
        pending = json.loads(INTENT.read_text())
        current = sha(STATE.read_bytes())
        if (pending.get("successor_source_sha256") != sha(Path(__file__).read_bytes())
                or pending.get("original_source_sha256") != SOURCE_SHA):
            raise RuntimeError("pending successor intent has different source SHA")
        if current == pending["new_checkpoint_sha256"]:
            durable(RECEIPT, encoded(pending))
            return pending
        if current != pending["old_checkpoint_sha256"]:
            raise RuntimeError("pending successor intent conflicts with checkpoint")
    old = STATE.read_bytes()
    state = json.loads(old)
    if (state.get("test") != campaign_v1.TEST or state.get("scheduler_v2")
            or state.get("stop_reason") != "queue_exhausted_inconclusive"
            or state["queue"] or state["active"] is not None
            or len(state["completed"]) >= state["attempt_cap"]):
        raise RuntimeError("alternate controller has not reached natural queue exhaustion")
    if audit_campaign.main() != 0:
        raise RuntimeError("independent raw auditor rejected pre-handoff checkpoint")
    audit_path = HERE / "raw-audit.json"
    audit = json.loads(audit_path.read_text())
    if (audit.get("checkpoint_sha256") != sha(old) or audit.get("errors")
            or audit.get("completed_attempts") != len(state["completed"])):
        raise RuntimeError("pre-handoff raw audit/checkpoint mismatch")
    found = discover(state)
    if not found:
        raise RuntimeError("no unseen target-before physical HDFS_RPC singleton")
    before = {key: sha(encoded(state[key])) for key in
              ("completed", "seen", "queue", "coverage", "io_families")}
    next_state = json.loads(json.dumps(state))
    next_state["scheduler_v2"] = {"policy": POLICY,
                                   "anchor_attempt": len(state["completed"]),
                                   "new_singletons_added": 0,
                                   "max_new_singletons": MAX_NEW_SINGLETON}
    inserted = add_singletons(next_state, found)
    if not inserted or next_state["completed"] != state["completed"]:
        raise RuntimeError("handoff failed to preserve completed denominator")
    next_state["stop_reason"] = None
    receipt = {"schema": 1, "policy": POLICY,
               "original_source_sha256": SOURCE_SHA,
               "successor_source_sha256": sha(Path(__file__).read_bytes()),
               "old_checkpoint_sha256": sha(old),
               "new_checkpoint_sha256": sha(encoded(next_state)),
               "anchor_attempt": len(state["completed"]),
               "completed_sha256_before_after": [before["completed"],
                                                   sha(encoded(next_state["completed"]))],
               "seen_sha256_before": before["seen"],
               "queue_sha256_before": before["queue"],
               "coverage_sha256_before_after": [before["coverage"],
                                                 sha(encoded(next_state["coverage"]))],
               "io_sha256_before_after": [before["io_families"],
                                           sha(encoded(next_state["io_families"]))],
               "new_singletons": inserted,
               "independent_audit_sha256": sha(audit_path.read_bytes())}
    if INTENT.exists():
        if json.loads(INTENT.read_text()) != receipt:
            raise RuntimeError("pending successor intent differs from recomputed handoff")
    else:
        durable(INTENT, encoded(receipt))
    durable(STATE, encoded(next_state))
    if sha(STATE.read_bytes()) != receipt["new_checkpoint_sha256"]:
        raise RuntimeError("new checkpoint SHA mismatch")
    durable(RECEIPT, encoded(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--wall-seconds", type=int, default=43200)
    parser.add_argument("--poll-seconds", type=int, default=20)
    args = parser.parse_args()
    if args.preview:
        state = json.loads(STATE.read_text())
        found = discover(state)
        simulated = json.loads(json.dumps(state))
        simulated["scheduler_v2"] = {"policy": POLICY,
                                      "anchor_attempt": len(state["completed"]),
                                      "new_singletons_added": 0,
                                      "max_new_singletons": MAX_NEW_SINGLETON}
        inserted = add_singletons(simulated, found)
        if (simulated["completed"] != state["completed"]
                or simulated["queue"][:len(state["queue"])] != state["queue"]
                or simulated["seen"][:len(state["seen"])] != state["seen"]
                or len(simulated["seen"]) != len(set(simulated["seen"]))):
            raise RuntimeError("dry-run changed old ledger/queue/seen or duplicated an ID")
        print(json.dumps({"completed": len(state["completed"]),
                          "effective": len(C.effective(state)["HDFS-28"]),
                          "queue": len(state["queue"]), "seen": len(state["seen"]),
                          "stop_reason": state["stop_reason"],
                          "fresh_target_before_rpc_singletons": len(found),
                          "dry_run_added": len(inserted),
                          "dry_run_queue_after": len(simulated["queue"]),
                          "dry_run_seen_after": len(simulated["seen"]),
                          "dry_run_next_id": simulated["queue"][choose(simulated)]["id"],
                          "first_ids": [item["id"] for item in found[:8]],
                          "old_source_matches":
                          sha((HERE / "campaign_v1.py").read_bytes()) == SOURCE_SHA},
                         sort_keys=True))
        return
    if not args.run:
        parser.error("choose --preview or --run")
    with C.LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = handoff()
        C.choose, C.admit = choose, admit
        state = json.loads(STATE.read_text())
        C.write_summary(state)
        print(json.dumps({"handoff_anchor": receipt["anchor_attempt"],
                          "new_singletons": len(receipt["new_singletons"])}), flush=True)
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
                time.sleep(args.poll_seconds)
        print("successor wall cap reached; resume unchanged checkpoint", flush=True)


if __name__ == "__main__":
    main()
