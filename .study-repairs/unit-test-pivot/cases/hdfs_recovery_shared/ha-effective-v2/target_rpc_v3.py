#!/usr/bin/env python3
"""Resume the original HA JUnit with unseen, same-root pre-HDFS28 RPC seeds.

This successor starts only after the previous controller naturally reaches its
320-attempt checkpoint. It keeps every old attempt, queue entry and seen ID.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import hashlib
import json
from pathlib import Path
import time

import audit_raw
import campaign as C
import focus28_v2 as V2
import successor

HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
INTENT = HERE / "target-rpc-v3-intent.json"
RECEIPT = HERE / "target-rpc-v3-receipt.json"
PREDECESSOR_LOG = HERE / "focus28-v2.log"
OLD_SOURCE_SHA = "80a9f8b365cb228d4c042fbca1a870b0c1d19437dae8c5c476e7f02e0ce74ac7"
POLICY = "effective_trace_unseen_hdfs_rpc_then_ipc_singletons_four_rpc_one_file_v3"
CASE = "HDFS-28"
MARKERS = ("FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY", "FAULT:HADOOP_IPC:REQUEST")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover(state: dict) -> list[dict]:
    """New selectors occur before the same physical owner's later HDFS28 guard."""
    found: dict[str, dict] = {}
    seen = set(state["seen"])
    for number, trial in enumerate(state["completed"], 1):
        if not trial["exact_order_applied"] or not trial["post_fault_target_checks"][CASE]:
            continue
        directory = Path(trial["run"])
        raw = directory / "runtime_trace.jsonl"
        if sha(raw) != trial["raw_trace_sha256"]:
            raise RuntimeError(f"trial {number} raw trace SHA changed")
        events = C.trace(directory)
        for event in events:
            if (event.get("event") != "FAULT_POINT_OBSERVED"
                    or event.get("marker") not in MARKERS
                    or not C.identity_verified(events, event)
                    or CASE not in C.later_targets(event, events)):
                continue
            for kind in C.RPC_ERRORS:
                point = C.point(event, kind)
                ident = C.identity([point])
                if ident not in seen and ident not in found:
                    found[ident] = {
                        "id": ident, "sequence": [point], "source_trial": number,
                        "source_raw_trace_sha256": trial["raw_trace_sha256"],
                        "source_io_seq": event["seq"],
                        "physical_owner": C.origin(event),
                        "recovery_root": C.root(event),
                        "block_id": event.get("blockId"),
                        "recovery_id": event.get("recoveryId"),
                    }
    return sorted(found.values(), key=lambda row: (
        MARKERS.index(row["sequence"][0]["marker"]), row["source_trial"],
        row["source_io_seq"], row["sequence"][0]["faultType"]))


def migrate(state: dict, candidates: list[dict], *, preview: bool = False) -> tuple[dict, list[dict]]:
    if (state.get("schema") != 2 or tuple(state.get("cases", ())) != C.CASES
            or state.get("test") != V2.SOURCE_TEST
            or state.get("focus28_scheduler", {}).get("policy") != V2.POLICY
            or state.get("target_rpc_v3")
            or len(C.effective(state)[CASE]) >= state["goals"][CASE]):
        raise RuntimeError("unexpected predecessor state or no HDFS28 deficit")
    if state["attempt_cap"] != 320 or (not preview and (
            state.get("stop_reason") != "attempt_cap_inconclusive"
            or len(state["completed"]) != 320 or state["active"] is not None)):
        raise RuntimeError("predecessor has not naturally stopped at HDFS28 deficit")
    if not candidates:
        raise RuntimeError("no new pretarget actor-bound RPC selectors")
    next_state = json.loads(json.dumps(state))
    before = {key: successor.sha(successor.encoded(state[key])) for key in
              ("completed", "queue", "seen", "coverage", "io_families")}
    inserted = []
    for row in candidates:
        original = len(next_state["seen"])
        C.add(next_state, row["sequence"], priority=12, eligible=(CASE,))
        if len(next_state["seen"]) > original:
            next_state["queue"][-1]["created"] = 320 + len(inserted) / 1000
            inserted.append(row)
    if len(inserted) != len(candidates):
        raise RuntimeError("discovered plan collided with old seen ledger")
    next_state["target_rpc_v3"] = {
        "policy": POLICY, "anchor_attempt": len(state["completed"]),
        "new_ids": [row["id"] for row in inserted],
        "new_by_marker": dict(Counter(row["sequence"][0]["marker"]
                                      for row in inserted)),
        "attempt_cap_reason": "HDFS28 remains below 80 effective; new exact owner/root pretarget RPC selectors were observed in prior effective original-JUnit traces",
        "prior_prefix_sha256": before,
    }
    next_state["attempt_cap"] = 512
    next_state["stop_reason"] = None
    for key in ("completed", "coverage", "io_families", "active"):
        if key == "active":
            if next_state[key] != state[key]:
                raise RuntimeError("migration changed active plan")
            continue
        if successor.sha(successor.encoded(next_state[key])) != before[key]:
            raise RuntimeError("migration changed " + key)
    for key in ("queue", "seen"):
        if next_state[key][:len(state[key])] != state[key]:
            raise RuntimeError("migration changed old " + key)
    if len(set(next_state["seen"])) != len(next_state["seen"]):
        raise RuntimeError("migration duplicated a seen selector")
    return next_state, inserted


def choose(state: dict) -> int:
    queue = state["queue"]
    ordinal = len(state["completed"]) - state["successor_scheduler"]["anchor_completed"]
    if ordinal % 5 == 4:
        return V2.choose(state)  # Preserve the FILE exploration slot.
    preferred = set(state["target_rpc_v3"]["new_ids"])
    for marker in MARKERS:
        indices = [i for i, item in enumerate(queue)
                   if item["id"] in preferred and len(item["sequence"]) == 1
                   and item["sequence"][0]["marker"] == marker
                   and CASE in item["eligible"]]
        if indices:
            subset = {**state, "queue": [queue[i] for i in indices]}
            return indices[successor.choose(subset)]
    return V2.choose(state)


def handoff() -> dict:
    if sha(HERE / "focus28_v2.py") != OLD_SOURCE_SHA:
        raise RuntimeError("predecessor source SHA changed")
    if RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text())
        state = json.loads(STATE.read_text())
        if (receipt["new_source_sha256"] != sha(Path(__file__))
                or state.get("target_rpc_v3", {}).get("policy") != POLICY
                or len(state["completed"]) < receipt["anchor_attempt"]):
            raise RuntimeError("existing v3 handoff conflicts with checkpoint")
        return receipt
    old = STATE.read_bytes()
    state = json.loads(old)
    if not PREDECESSOR_LOG.is_file() or not PREDECESSOR_LOG.read_text().rstrip().endswith(
            "terminal attempt_cap_inconclusive"):
        raise RuntimeError("predecessor has no natural terminal log")
    if audit_raw.main() != 0:
        raise RuntimeError("independent raw audit rejected old checkpoint")
    audit = json.loads((HERE / "raw-audit.json").read_text())
    if (audit["errors"] or audit["checkpoint_sha256"] != successor.sha(old)
            or audit["completed_attempts"] != len(state["completed"])
            or STATE.read_bytes() != old):
        raise RuntimeError("raw audit and old checkpoint differ")
    changed, inserted = migrate(state, discover(state))
    new = successor.encoded(changed)
    receipt = {
        "schema": 1, "policy": POLICY,
        "old_source_sha256": OLD_SOURCE_SHA,
        "new_source_sha256": sha(Path(__file__)),
        "old_checkpoint_sha256": successor.sha(old),
        "new_checkpoint_sha256": successor.sha(new),
        "raw_audit_sha256": sha(HERE / "raw-audit.json"),
        "anchor_attempt": len(state["completed"]),
        "old_queue": len(state["queue"]), "old_seen": len(state["seen"]),
        "new_selectors": inserted, "attempt_cap_before_after": [320, 512],
        "old_prefix_sha256": changed["target_rpc_v3"]["prior_prefix_sha256"],
    }
    if INTENT.exists():
        if json.loads(INTENT.read_text()) != receipt:
            raise RuntimeError("pending intent conflicts with deterministic migration")
    else:
        successor.durable_json(INTENT, receipt)
    successor.durable_json(STATE, changed)
    if successor.sha(STATE.read_bytes()) != receipt["new_checkpoint_sha256"]:
        raise RuntimeError("new checkpoint SHA mismatch")
    successor.durable_json(RECEIPT, receipt)
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
        migrated, inserted = migrate(state, found, preview=True)
        next_id = migrated["queue"][choose(migrated)]["id"]
        if migrated["completed"] != state["completed"] or migrated["active"] != state["active"]:
            raise RuntimeError("preview altered an old trial or reserved plan")
        print(json.dumps({"attempts": len(state["completed"]),
                          "effective28": len(C.effective(state)[CASE]),
                          "queue": len(state["queue"]), "seen": len(state["seen"]),
                          "new_unique_rpc": dict(Counter(row["sequence"][0]["marker"]
                                                         for row in found)),
                          "would_add": len(inserted), "first_new_id": found[0]["id"] if found else None,
                          "hypothetical_next_id_after_reserved": next_id,
                          "predecessor_source_matches": sha(HERE / "focus28_v2.py") == OLD_SOURCE_SHA},
                         sort_keys=True))
        return
    if not args.run:
        parser.error("choose --preview or --run")
    with C.LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = handoff()
        C.MIN_FREE_BYTES = 10 * 1024**3
        C.choose = choose
        state = json.loads(STATE.read_text())
        print(json.dumps({"anchor": receipt["anchor_attempt"],
                          "new": len(receipt["new_selectors"]),
                          "cap": state["attempt_cap"], "policy": POLICY}), flush=True)
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
        print("v3 wall cap reached; resume unchanged checkpoint", flush=True)


if __name__ == "__main__":
    main()
