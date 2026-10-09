#!/usr/bin/env python3
"""Optional original-JUnit HDFS-28 successor from unseen pretarget file I/O.

This code only runs after IPC V3 naturally exhausts. The --preview mode reads
and validates source evidence without starting a JVM or changing checkpoint.
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
import ipc_successor_v3 as V3

HERE = Path(__file__).resolve().parent
C = V3.C
STATE = HERE / "checkpoint.json"
INTENT = HERE / "file-v4-intent.json"
RECEIPT = HERE / "file-v4-receipt.json"
PREDECESSOR_LOG = HERE / "ipc-v3.log"
OLD_SOURCE_SHA = "92f8811fe73fef899d746a02dbc984cf019e203208dfdefc7f962e89ed922264"
POLICY = "unseen_same_owner_pretarget_file_singleton_local_then_remote_v4"
CASE = campaign_v1.CASE


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encoded(value: object) -> bytes:
    return V3.V2.encoded(value)


def discover(state: dict) -> list[dict]:
    seen = set(state["seen"])
    sources: list[tuple[str, Path, str]] = []
    for healthy in state["healthy"]:
        directory = Path(healthy["run"])
        sources.append((directory.name, directory, healthy["trace_sha256"]))
    for number, trial in enumerate(state["completed"], 1):
        if trial["exact_order_applied"] and trial["post_fault_target_checks"][CASE]:
            sources.append(("trial-%04d" % number, Path(trial["run"]),
                            trial["raw_trace_sha256"]))
    found: dict[str, dict] = {}
    for label, directory, expected_sha in sources:
        raw = directory / "runtime_trace.jsonl"
        if sha(raw) != expected_sha:
            raise RuntimeError("raw trace SHA changed: " + label)
        events = C.trace(directory)
        for event in events:
            if (event.get("event") != "FAULT_POINT_OBSERVED"
                    or not event.get("marker", "").startswith("FAULT:HDFS_FILE:")
                    or not C.identity_verified(events, event)
                    or CASE not in C.later_targets(event, events)):
                continue
            for kind in C.FILE_ERRORS:
                point = C.point(event, kind)
                ident = C.identity([point])
                if ident in seen or ident in found:
                    continue
                found[ident] = {
                    "id": ident, "sequence": [point], "source": label,
                    "source_raw_trace_sha256": expected_sha,
                    "source_io_seq": event["seq"],
                    "physical_owner": C.origin(event),
                    "recovery_root": C.root(event),
                    "block_id": event.get("blockId"),
                    "recovery_id": event.get("recoveryId"),
                    "local_file": event.get("sourceKey") == C.origin(event),
                }
    return sorted(found.values(), key=lambda row: (
        not row["local_file"], row["source"], row["source_io_seq"],
        row["sequence"][0]["faultType"]))


def migrate(state: dict, candidates: list[dict]) -> tuple[dict, list[dict]]:
    if (state.get("schema") != 2 or state.get("test") != campaign_v1.TEST
            or state.get("ipc_v3", {}).get("policy") != V3.POLICY
            or state.get("file_v4") or state.get("stop_reason") !=
            "queue_exhausted_inconclusive" or state["active"] is not None
            or state["queue"] or state["attempt_cap"] != 320
            or len(C.effective(state)[CASE]) >= state["goals"][CASE]
            or not candidates):
        raise RuntimeError("IPC V3 is not at an incomplete natural boundary")
    result = json.loads(json.dumps(state))
    prefix = {key: sha_value(encoded(state[key])) for key in
              ("completed", "seen", "queue", "coverage", "io_families",
               "target_related_coverage", "stable_actor_io_families")}
    inserted = []
    for candidate in candidates:
        before = len(result["seen"])
        C.add(result, candidate["sequence"],
              priority=14 if candidate["local_file"] else 8,
              eligible=(CASE,))
        if len(result["seen"]) > before:
            result["queue"][-1]["created"] = len(state["completed"]) + len(inserted) / 1000
            inserted.append(candidate)
    if len(inserted) != len(candidates):
        raise RuntimeError("new file selector collided with seen ledger")
    result["file_v4"] = {
        "policy": POLICY, "anchor_attempt": len(state["completed"]),
        "new_ids": [row["id"] for row in inserted],
        "local": sum(row["local_file"] for row in inserted),
        "remote": sum(not row["local_file"] for row in inserted),
        "prior_prefix_sha256": prefix,
        "attempt_cap_reason": "same selected HDFS-28 guard has conditional 128 aggregate target; actor-bound file singleton queue is newly observed and prior IPC V3 queue naturally exhausted",
    }
    result["attempt_cap"] = 512
    result["stop_reason"] = None
    for key in ("completed", "coverage", "io_families", "target_related_coverage",
                "stable_actor_io_families", "active"):
        if result[key] != state[key]:
            raise RuntimeError("migration changed predecessor " + key)
    for key in ("seen", "queue"):
        if result[key][:len(state[key])] != state[key]:
            raise RuntimeError("migration changed predecessor " + key)
    if len(set(result["seen"])) != len(result["seen"]):
        raise RuntimeError("migration duplicated a seen selector")
    return result, inserted


def sha_value(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def choose(state: dict) -> int:
    queue = state["queue"]
    offset = len(state["completed"]) - state["file_v4"]["anchor_attempt"]
    rpc = [i for i, row in enumerate(queue)
           if not row["sequence"][-1]["marker"].startswith("FAULT:HDFS_FILE:")]
    if offset % 5 < 4 and rpc:
        subset = {**state, "queue": [queue[i] for i in rpc]}
        return rpc[V3.V2.base_choose(subset)]
    selected_ids = set(state["file_v4"]["new_ids"])
    for local in (True, False):
        indices = [i for i, row in enumerate(queue)
                   if row["id"] in selected_ids and len(row["sequence"]) == 1
                   and (row["sequence"][0]["sourceKey"] ==
                        row["sequence"][0]["originSourceKey"]) == local]
        if indices:
            subset = {**state, "queue": [queue[i] for i in indices]}
            return indices[V3.V2.base_choose(subset)]
    return V3.choose(state)


def handoff() -> dict:
    if sha(HERE / "ipc_successor_v3.py") != OLD_SOURCE_SHA:
        raise RuntimeError("IPC V3 predecessor source SHA changed")
    if RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text())
        state = json.loads(STATE.read_text())
        if (receipt["new_source_sha256"] != sha(Path(__file__))
                or state.get("file_v4", {}).get("policy") != POLICY
                or len(state["completed"]) < receipt["anchor_attempt"]):
            raise RuntimeError("existing file V4 receipt conflicts with checkpoint")
        return receipt
    old = STATE.read_bytes()
    state = json.loads(old)
    if (not PREDECESSOR_LOG.is_file() or
            not PREDECESSOR_LOG.read_text().rstrip().endswith(
                "terminal queue_exhausted_inconclusive")):
        raise RuntimeError("IPC V3 lacks natural terminal log")
    if audit_campaign.main() != 0:
        raise RuntimeError("independent raw audit rejected IPC V3 predecessor")
    audit_path = HERE / "raw-audit.json"
    audit = json.loads(audit_path.read_text())
    if (audit["errors"] or audit["checkpoint_sha256"] != sha_value(old)
            or audit["completed_attempts"] != len(state["completed"])
            or STATE.read_bytes() != old):
        raise RuntimeError("raw audit and frozen checkpoint disagree")
    changed, inserted = migrate(state, discover(state))
    new = encoded(changed)
    receipt = {
        "schema": 1, "policy": POLICY,
        "old_source_sha256": OLD_SOURCE_SHA,
        "new_source_sha256": sha(Path(__file__)),
        "old_checkpoint_sha256": sha_value(old),
        "new_checkpoint_sha256": sha_value(new),
        "raw_audit_sha256": sha(audit_path),
        "anchor_attempt": len(state["completed"]),
        "old_queue": len(state["queue"]), "old_seen": len(state["seen"]),
        "new_selectors": inserted,
        "old_prefix_sha256": changed["file_v4"]["prior_prefix_sha256"],
        "attempt_cap_before_after": [320, 512],
        "max_faults_before_after": [state["max_faults"], changed["max_faults"]],
    }
    if INTENT.exists():
        if json.loads(INTENT.read_text()) != receipt:
            raise RuntimeError("pending V4 intent differs from deterministic migration")
    else:
        V3.V2.durable(INTENT, encoded(receipt))
    V3.V2.durable(STATE, new)
    if sha(STATE) != receipt["new_checkpoint_sha256"]:
        raise RuntimeError("new checkpoint SHA mismatch")
    V3.V2.durable(RECEIPT, encoded(receipt))
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
        simulated, inserted = migrate(state, found)
        print(json.dumps({
            "old_checkpoint_sha256": sha(STATE),
            "old_source_sha256": sha(HERE / "ipc_successor_v3.py"),
            "old_attempts": len(state["completed"]),
            "old_effective": len(C.effective(state)[CASE]),
            "old_queue": len(state["queue"]), "old_seen": len(state["seen"]),
            "new_count": len(inserted),
            "new_local": sum(row["local_file"] for row in inserted),
            "new_remote": sum(not row["local_file"] for row in inserted),
            "new_by_site": dict(Counter(row["sequence"][0]["siteId"]
                                        for row in inserted)),
            "new_selectors": inserted,
            "hypothetical_new_checkpoint_sha256": sha_value(encoded(simulated)),
            "hypothetical_next_id": simulated["queue"][choose(simulated)]["id"],
            "predecessor_source_matches": sha(HERE / "ipc_successor_v3.py") == OLD_SOURCE_SHA,
        }, sort_keys=True))
        return
    if not args.run:
        parser.error("choose --preview or --run")
    with C.LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = handoff()
        C.MIN_FREE_BYTES = 10 * 1024**3
        C.choose = choose
        C.admit = V3.admit
        state = json.loads(STATE.read_text())
        C.write_summary(state)
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
        print("file V4 wall cap reached; resume unchanged checkpoint", flush=True)


if __name__ == "__main__":
    main()
