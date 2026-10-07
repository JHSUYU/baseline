#!/usr/bin/env python3
"""Continue exhausted original-JUnit HDFS28 seed with unseen actor-bound IPC RPC.

The predecessor's completed/seen/queue prefix remains untouched. IPC points
come only from exact postfault HDFS28-effective original-JUnit traces.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import hashlib
import json
from pathlib import Path
import time

import audit_campaign
import campaign_v1
import successor_v2 as V2

HERE = Path(__file__).resolve().parent
C = V2.C
STATE = HERE / "checkpoint.json"
INTENT = HERE / "ipc-v3-intent.json"
RECEIPT = HERE / "ipc-v3-receipt.json"
PREDECESSOR_LOG = HERE / "successor-v2.log"
OLD_SOURCE_SHA = "e516f99ef46b9c12ad41497ff3d509df34a953026aeb648dd41722bf775e70a3"
POLICY = "effective_trace_pretarget_same_root_ipc_singleton_four_rpc_one_file_v3"
MARKER = "FAULT:HADOOP_IPC:REQUEST"
MAX_NEW_IPC = 64


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover(state: dict, trials: list[tuple[int, dict]] | None = None) -> list[dict]:
    seen = set(state["seen"])
    source = trials if trials is not None else list(enumerate(state["completed"], 1))
    found: dict[str, dict] = {}
    for number, trial in source:
        if (not trial["exact_order_applied"]
                or not trial["post_fault_target_checks"][campaign_v1.CASE]):
            continue
        raw = Path(trial["run"]) / "runtime_trace.jsonl"
        if sha(raw) != trial["raw_trace_sha256"]:
            raise RuntimeError(f"trial {number} raw trace SHA changed")
        events = C.trace(Path(trial["run"]))
        for event in events:
            if (event.get("event") != "FAULT_POINT_OBSERVED"
                    or event.get("marker") != MARKER
                    or not C.identity_verified(events, event)
                    or campaign_v1.CASE not in C.later_targets(event, events)):
                continue
            for kind in C.RPC_ERRORS:
                point = C.point(event, kind)
                ident = C.identity([point])
                if ident not in seen and ident not in found:
                    found[ident] = {"id": ident, "sequence": [point],
                                    "source_trial": number,
                                    "raw_trace_sha256": trial["raw_trace_sha256"],
                                    "source_io_seq": event["seq"],
                                    "physical_owner": C.origin(event),
                                    "recovery_root": C.root(event),
                                    "block_id": event.get("blockId"),
                                    "recovery_id": event.get("recoveryId")}
    return sorted(found.values(), key=lambda row: (
        row["source_trial"], row["source_io_seq"],
        row["sequence"][0]["faultType"]))


def add(state: dict, candidates: list[dict]) -> list[dict]:
    inserted = []
    budget = MAX_NEW_IPC - state["ipc_v3"]["new_ipc_added"]
    for row in candidates[:max(0, budget)]:
        before = len(state["seen"])
        C.add(state, row["sequence"], priority=12,
              eligible=(campaign_v1.CASE,))
        if len(state["seen"]) > before:
            state["queue"][-1]["created"] = (
                state["ipc_v3"]["anchor_attempt"] +
                (state["ipc_v3"]["new_ipc_added"] + len(inserted)) / 1000)
            inserted.append(row)
    state["ipc_v3"]["new_ipc_added"] += len(inserted)
    return inserted


def migrate(state: dict, *, preview: bool = False) -> tuple[dict, list[dict]]:
    if (state.get("test") != campaign_v1.TEST
            or state.get("scheduler_v2", {}).get("policy") != V2.POLICY
            or state.get("ipc_v3")
            or len(C.effective(state)[campaign_v1.CASE]) >= state["goals"][campaign_v1.CASE]
            or state["attempt_cap"] != 320):
        raise RuntimeError("unexpected predecessor or no HDFS28 deficit")
    if not preview and (state.get("stop_reason") != "queue_exhausted_inconclusive"
                        or state["queue"] or state["active"] is not None):
        raise RuntimeError("predecessor has not naturally exhausted its queue")
    candidates = discover(state)
    if not candidates:
        raise RuntimeError("no unseen actor-bound pretarget IPC selector")
    output = json.loads(json.dumps(state))
    output["ipc_v3"] = {"policy": POLICY, "anchor_attempt": len(state["completed"]),
                         "new_ipc_added": 0, "max_new_ipc": MAX_NEW_IPC}
    inserted = add(output, candidates)
    if (not inserted or output["completed"] != state["completed"]
            or output["queue"][:len(state["queue"])] != state["queue"]
            or output["seen"][:len(state["seen"])] != state["seen"]
            or output["coverage"] != state["coverage"]
            or output["io_families"] != state["io_families"]
            or output["active"] != state["active"]
            or len(set(output["seen"])) != len(output["seen"])):
        raise RuntimeError("migration changed or duplicated predecessor evidence")
    output["stop_reason"] = None
    return output, inserted


def choose(state: dict) -> int:
    queue = state["queue"]
    ordinal = len(state["completed"]) - state["scheduler_v2"]["anchor_attempt"]
    rpc = [i for i, row in enumerate(queue) if row["sequence"][-1]["marker"] in
           ("FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY", MARKER)]
    file = [i for i in range(len(queue)) if i not in rpc]
    pool = (rpc if ordinal % 5 < 4 else file) or (file if ordinal % 5 < 4 else rpc)
    hdfs_single = [i for i in pool if len(queue[i]["sequence"]) == 1
                   and queue[i]["sequence"][-1]["marker"] ==
                   "FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY"]
    ipc_single = [i for i in pool if len(queue[i]["sequence"]) == 1
                  and queue[i]["sequence"][-1]["marker"] == MARKER]
    selected = hdfs_single or ipc_single or pool
    subset = {**state, "queue": [queue[i] for i in selected]}
    return selected[V2.base_choose(subset)]


def admit(state: dict, trial: dict) -> None:
    V2.admit(state, trial)
    if (trial["exact_order_applied"]
            and trial["post_fault_target_checks"][campaign_v1.CASE]
            and state["ipc_v3"]["new_ipc_added"] < MAX_NEW_IPC):
        add(state, discover(state, [(len(state["completed"]), trial)]))


def handoff() -> dict:
    if sha(HERE / "successor_v2.py") != OLD_SOURCE_SHA:
        raise RuntimeError("predecessor source SHA changed")
    if RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text())
        state = json.loads(STATE.read_text())
        if (receipt["new_source_sha256"] != sha(Path(__file__))
                or state.get("ipc_v3", {}).get("policy") != POLICY
                or len(state["completed"]) < receipt["anchor_attempt"]):
            raise RuntimeError("existing IPC v3 handoff conflicts with checkpoint")
        return receipt
    old = STATE.read_bytes()
    state = json.loads(old)
    if not PREDECESSOR_LOG.is_file() or not PREDECESSOR_LOG.read_text().rstrip().endswith(
            "terminal queue_exhausted_inconclusive"):
        raise RuntimeError("predecessor has no natural exhaustion log")
    if audit_campaign.main() != 0:
        raise RuntimeError("independent raw audit rejected old checkpoint")
    audit_file = HERE / "raw-audit.json"
    audit = json.loads(audit_file.read_text())
    if (audit["errors"] or audit["checkpoint_sha256"] != V2.sha(old)
            or audit["completed_attempts"] != len(state["completed"])
            or STATE.read_bytes() != old):
        raise RuntimeError("predecessor raw audit/checkpoint mismatch")
    changed, inserted = migrate(state)
    new = V2.encoded(changed)
    receipt = {"schema": 1, "policy": POLICY,
               "old_source_sha256": OLD_SOURCE_SHA,
               "new_source_sha256": sha(Path(__file__)),
               "old_checkpoint_sha256": V2.sha(old),
               "new_checkpoint_sha256": V2.sha(new),
               "raw_audit_sha256": sha(audit_file),
               "anchor_attempt": len(state["completed"]),
               "old_completed_sha256": V2.sha(V2.encoded(state["completed"])),
               "old_seen": len(state["seen"]), "old_queue": len(state["queue"]),
               "new_selectors": inserted}
    if INTENT.exists():
        if json.loads(INTENT.read_text()) != receipt:
            raise RuntimeError("pending intent conflicts with deterministic migration")
    else:
        V2.durable(INTENT, V2.encoded(receipt))
    V2.durable(STATE, new)
    if V2.sha(STATE.read_bytes()) != receipt["new_checkpoint_sha256"]:
        raise RuntimeError("new checkpoint SHA mismatch")
    V2.durable(RECEIPT, V2.encoded(receipt))
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
        simulated, found = migrate(state, preview=True)
        print(json.dumps({"old_completed": len(state["completed"]),
                          "old_effective": len(C.effective(state)[campaign_v1.CASE]),
                          "old_queue": len(state["queue"]), "old_seen": len(state["seen"]),
                          "new_ipc_singletons": len(found),
                          "new_ipc_by_exception": dict(Counter(
                              row["sequence"][0]["faultType"] for row in found)),
                          "hypothetical_next_id": simulated["queue"][choose(simulated)]["id"],
                          "predecessor_source_matches":
                          sha(HERE / "successor_v2.py") == OLD_SOURCE_SHA},
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
        print(json.dumps({"anchor": receipt["anchor_attempt"],
                          "new_ipc": len(receipt["new_selectors"]),
                          "policy": POLICY}), flush=True)
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
        print("IPC v3 wall cap reached; resume unchanged checkpoint", flush=True)


if __name__ == "__main__":
    main()
