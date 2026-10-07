#!/usr/bin/env python3
"""Versioned coverage-guided scheduler for a quiescent V3 checkpoint.

The original controller must have exited. A reserved active plan is allowed
only before its runner or JUnit has started; it is resumed unchanged. This
handoff never rewrites completed trials, seen IDs, or queued plans.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import audit_v3
import campaign

HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
INTENT = HERE / "coverage-handoff-intent.json"
RECEIPT = HERE / "coverage-handoff-receipt.json"
POLICY = "parent_production_coverage_then_io_and_family_balance_v1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def durable(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as output:
        output.write(encoded(value))
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def gain_score(item: dict, by_id: dict[str, dict]) -> int:
    parent = by_id.get(item.get("parent"))
    if not parent or not parent.get("post_fault_target"):
        return 0
    gains = parent["coverage_gain"]
    probes = len(gains["probes"])
    methods = len(gains["methods"])
    branches = len(gains["branch_counts"])
    if not (probes or methods or branches):
        return 0
    # Bounded bins reward distinct recovery code without letting one large
    # JUnit perturbation monopolize the queue indefinitely.
    return min(3, probes.bit_length()) + bool(methods) + bool(branches)


def choose(state: dict) -> int:
    by_id = {row["id"]: row for row in state["completed"]}
    tested = Counter((row["sequence"][-1]["marker"],
                      row["sequence"][-1]["api"])
                     for row in state["completed"])
    return max(range(len(state["queue"])), key=lambda i: (
        gain_score(state["queue"][i], by_id) > 0,
        state["queue"][i]["priority"],
        -tested[(state["queue"][i]["sequence"][-1]["marker"],
                 state["queue"][i]["sequence"][-1]["api"])],
        gain_score(state["queue"][i], by_id),
        min(len(state["queue"][i]["sequence"]), 6),
        -state["queue"][i]["created"], -i))


def snapshot(state: dict) -> dict:
    by_id = {row["id"]: row for row in state["completed"]}
    old = campaign.choose(state)
    new = choose(state)
    return {"attempts": len(state["completed"]),
            "effective": len(campaign.effective(state)),
            "queue": len(state["queue"]), "seen": len(state["seen"]),
            "active_plan": state["active"]["id"] if state["active"] else None,
            "old_next_id": state["queue"][old]["id"],
            "coverage_next_id": state["queue"][new]["id"],
            "coverage_next_parent_gain_score": gain_score(state["queue"][new], by_id),
            "queue_sha256": sha(encoded(state["queue"])),
            "seen_sha256": sha(encoded(state["seen"])),
            "completed_sha256": sha(encoded(state["completed"]))}


def verify_active(state: dict) -> None:
    if state["active"] is None:
        return
    number = len(state["completed"]) + 1
    directory = HERE / "runs" / f"trial-{number:04d}"
    for name in ("driver.log", "junit.log", "runtime_trace.jsonl", "manifest.json"):
        if (directory / name).exists():
            raise RuntimeError("active trial has already started: " + str(directory / name))
    plan = directory / "fault-plan.tsv"
    if plan.exists():
        expected = "".join("\t".join(p[key] for key in
                   ("marker", "api", "actor", "service", "ordinal", "exception")) + "\n"
                   for p in state["active"]["sequence"])
        if plan.read_text() != expected:
            raise RuntimeError("reserved active plan differs from checkpoint")


def verify_checkpoint(state: dict, expected_old: str) -> None:
    if sha((HERE / "campaign.py").read_bytes()) != expected_old:
        raise RuntimeError("original controller SHA changed")
    if state.get("schema") != 1 or state.get("case") != "HDFS-32":
        raise RuntimeError("unexpected checkpoint schema or case")
    if state.get("coverage_scheduler") is not None:
        raise RuntimeError("coverage scheduler already installed")
    if state.get("stop_reason") is not None:
        raise RuntimeError("original controller has terminal stop reason")
    if not state["queue"]:
        raise RuntimeError("no queued plans remain")
    verify_active(state)
    if audit_v3.main() != 0:
        raise RuntimeError("independent raw audit rejected checkpoint")
    audit = json.loads((HERE / "audit-v3.json").read_text())
    if audit["attempts"] != len(state["completed"]) or audit["errors"]:
        raise RuntimeError("audit disagrees with checkpoint")


def handoff(expected_old: str) -> dict:
    if RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text())
        state = json.loads(STATE.read_text())
        anchor = receipt["attempts_before_after"][0]
        if (receipt["old_controller_sha256"] != expected_old
                or receipt["successor_sha256"] != sha(Path(__file__).read_bytes())
                or state.get("coverage_scheduler", {}).get("policy") != POLICY
                or state["coverage_scheduler"]["anchor_attempt"] != anchor
                or sha(encoded(state["completed"][:anchor])) != receipt["completed_prefix_sha256"]):
            raise RuntimeError("existing handoff receipt conflicts with checkpoint")
        return receipt
    previous_intent = None
    if INTENT.exists():
        previous_intent = json.loads(INTENT.read_text())
        if (previous_intent["old_controller_sha256"] != expected_old
                or previous_intent["successor_sha256"] != sha(Path(__file__).read_bytes())):
            raise RuntimeError("pending handoff intent has different source SHA")
        current = sha(STATE.read_bytes())
        if current == previous_intent["new_checkpoint_sha256"]:
            durable(RECEIPT, previous_intent)
            return previous_intent
        if current != previous_intent["old_checkpoint_sha256"]:
            raise RuntimeError("pending handoff intent conflicts with checkpoint")
    old_raw = STATE.read_bytes()
    state = json.loads(old_raw)
    verify_checkpoint(state, expected_old)
    before = snapshot(state)
    changed = json.loads(json.dumps(state))
    changed["coverage_scheduler"] = {"policy": POLICY,
                                     "anchor_attempt": len(state["completed"]),
                                     "old_next_id": before["old_next_id"],
                                     "coverage_next_id": before["coverage_next_id"]}
    if any(changed[key] != state[key] for key in ("completed", "queue", "seen", "active")):
        raise RuntimeError("handoff altered ledger, queue, seen, or active plan")
    receipt = {"schema": 1, "policy": POLICY,
               "old_controller_sha256": expected_old,
               "successor_sha256": sha(Path(__file__).read_bytes()),
               "old_checkpoint_sha256": sha(old_raw),
               "new_checkpoint_sha256": sha(encoded(changed)),
               "attempts_before_after": [len(state["completed"]), len(changed["completed"])],
               "queue_before_after": [len(state["queue"]), len(changed["queue"])],
               "seen_before_after": [len(state["seen"]), len(changed["seen"])],
               "active_before_after": [state["active"], changed["active"]],
               "completed_prefix_sha256": before["completed_sha256"],
               "old_next_id": before["old_next_id"],
               "coverage_next_id": before["coverage_next_id"],
               "independent_audit_sha256": sha((HERE / "audit-v3.json").read_bytes())}
    if previous_intent is not None:
        if previous_intent != receipt:
            raise RuntimeError("pending handoff intent differs from recomputed transition")
    else:
        durable(INTENT, receipt)
    durable(STATE, changed)
    if sha(STATE.read_bytes()) != receipt["new_checkpoint_sha256"]:
        raise RuntimeError("checkpoint SHA mismatch after handoff")
    durable(RECEIPT, receipt)
    return receipt


def run(args: argparse.Namespace) -> None:
    with campaign.LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = handoff(args.expected_old_sha256)
        campaign.choose = choose
        state = json.loads(STATE.read_text())
        campaign.write_summary(state)
        print(json.dumps({"handoff": receipt}, sort_keys=True), flush=True)
        deadline = time.monotonic() + args.wall_seconds
        while time.monotonic() < deadline:
            reason = campaign.stop_reason(state)
            if reason:
                state["stop_reason"] = reason
                campaign.atomic_json(STATE, state)
                campaign.write_summary(state)
                print("terminal " + reason, flush=True)
                return
            if not campaign.trial_run(state):
                time.sleep(min(args.poll_seconds, max(0, deadline - time.monotonic())))
        print("coverage successor wall cap reached at atomic checkpoint; resume", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--expected-old-sha256", required=True)
    parser.add_argument("--wall-seconds", type=int, default=43200)
    parser.add_argument("--poll-seconds", type=int, default=20)
    args = parser.parse_args()
    if args.preview:
        state = json.loads(STATE.read_text())
        before = encoded(state)
        if sha((HERE / "campaign.py").read_bytes()) != args.expected_old_sha256:
            raise RuntimeError("controller source SHA mismatch")
        print(json.dumps(snapshot(state), sort_keys=True))
        if encoded(state) != before:
            raise RuntimeError("preview mutated checkpoint")
    elif args.run:
        run(args)
    else:
        parser.error("choose --preview or --run")


if __name__ == "__main__":
    main()
