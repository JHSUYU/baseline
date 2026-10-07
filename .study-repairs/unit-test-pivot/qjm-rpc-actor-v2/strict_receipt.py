#!/usr/bin/env python3
"""Audit an actor-aware QJM fault trace; never infer actor identity from a thread name."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

RPC = "FAULT:HDFS_QJM_RPC:RESPONSE"


def audit(events: list[dict], plan: list[list[str]], target_actor: str) -> dict:
    registration: dict[int, str] = {}
    last_peer: dict[str, tuple[int, str]] = {}
    applied: dict[int, dict] = {}
    errors: list[str] = []
    for event in events:
        kind = event.get("event")
        if kind == "NODE_PORT_REGISTER":
            port, actor = event.get("port"), event.get("journalNode")
            if actor is None or port in registration and registration[port] != actor:
                errors.append(f"ambiguous registration port={port}")
            else:
                registration[port] = actor
        elif kind == "RPC_PEER_RESOLVED":
            port, actor = event.get("port"), event.get("journalNode")
            if registration.get(port) != actor:
                errors.append(f"peer without matching registration port={port} actor={actor}")
            last_peer[event.get("thread", "")] = (event.get("seq", -1), actor)
        elif kind == "FAULT_APPLIED":
            index = event.get("faultIndex")
            if not isinstance(index, int) or index >= len(plan) or index < 0:
                errors.append(f"unexpected faultIndex={index}")
                continue
            expected = plan[index]
            if len(expected) < 6 or [event.get("marker"), event.get("siteId"),
                                     event.get("sourceKey"), str(event.get("hitOrdinal")),
                                     "planned", event.get("faultType")] != [*expected[:4], "planned", expected[5]]:
                errors.append(f"fault {index} selector differs from requested plan")
            if event.get("marker") == RPC:
                peer = last_peer.get(event.get("thread", ""))
                if peer is None or peer[1] != event.get("sourceKey") or peer[0] >= event.get("seq", -1):
                    errors.append(f"RPC fault {index} lacks same-thread registered peer")
            if index in applied:
                errors.append(f"fault {index} applied more than once")
            applied[index] = event
    if set(applied) != set(range(len(plan))):
        errors.append(f"applied indexes {sorted(applied)} != plan indexes {list(range(len(plan)))}")
    final_seq = max((event.get("seq", -1) for event in applied.values()), default=-1)
    targets = [event for event in events if event.get("event") == "TARGET_CHECK"
               and event.get("journalNode") == target_actor and event.get("seq", -1) > final_seq]
    if not targets:
        errors.append(f"target {target_actor} did not run after final applied fault")
    return {"pass": not errors, "target_actor": target_actor, "planned": len(plan),
            "applied": len(applied), "last_fault_seq": final_seq,
            "post_fault_target_checks": len(targets), "errors": errors}


def self_test() -> None:
    plan = [[RPC, "Client.getRpcResponse", "journalnode-2", "1", "pending", "IOException"]]
    events = [
        {"event": "NODE_PORT_REGISTER", "port": 21002, "journalNode": "journalnode-2", "seq": 1},
        {"event": "RPC_PEER_RESOLVED", "port": 21002, "journalNode": "journalnode-2", "thread": "main", "seq": 2},
        {"event": "FAULT_APPLIED", "marker": RPC, "siteId": "Client.getRpcResponse",
         "sourceKey": "journalnode-2", "hitOrdinal": 1, "faultType": "IOException",
         "faultIndex": 0, "thread": "main", "seq": 3},
        {"event": "TARGET_CHECK", "journalNode": "journalnode-2", "seq": 4},
    ]
    assert audit(events, plan, "journalnode-2")["pass"]
    assert not audit(events, plan, "journalnode-1")["pass"]
    assert not audit(events[1:], plan, "journalnode-2")["pass"]
    print("strict QJM trace receipt smoke PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--target-actor")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.trace or not args.plan or not args.target_actor:
            parser.error("--trace, --plan and --target-actor are required")
        events = [json.loads(line) for line in args.trace.read_text().splitlines() if line.strip()]
        plan = [line.split("\t") for line in args.plan.read_text().splitlines()
                if line.strip() and not line.startswith("#")]
        receipt = audit(events, plan, args.target_actor)
        print(json.dumps(receipt, indent=2))
        raise SystemExit(0 if receipt["pass"] else 1)
