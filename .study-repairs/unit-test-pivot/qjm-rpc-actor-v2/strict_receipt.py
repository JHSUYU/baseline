#!/usr/bin/env python3
"""Fail-closed actor, ordered-fault and exact target receipt for QJM V2."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

RPC = "FAULT:HDFS_QJM_RPC:RESPONSE"
SITES = {"07": "Journal.acceptRecovery#L924-933",
         "09": "Journal.checkRequest#L504-Preconditions",
         "10": "Journal.checkWriteRequest#L517-IFEQ"}
ROOT_ACTOR = re.compile(r"(?:^|[/\\])journalnode-([0-2])(?:[/\\]|$)")


def actor(source: str | None) -> str | None:
    found = ROOT_ACTOR.search(source or "")
    return "journalnode-" + found.group(1) if found else None


def audit(events: list[dict], plan: list[list[str]], case: str,
          target_actor: str) -> dict:
    if case not in SITES or target_actor not in {f"journalnode-{i}" for i in range(3)}:
        raise ValueError("unknown case or target actor")
    registration: dict[int, str] = {}
    storage: dict[str, str] = {}
    last_peer: dict[int, tuple[int, int, str]] = {}
    matched: dict[int, dict] = {}
    applied: dict[int, dict] = {}
    errors: list[str] = []
    last_index = -1
    for event in events:
        kind = event.get("event")
        seq, thread = event.get("seq", -1), event.get("threadId")
        if kind == "NODE_PORT_REGISTER":
            port, key, root = (event.get("port"), event.get("journalNode"),
                               event.get("storageRoot"))
            if (not isinstance(port, int) or port <= 0 or
                    key not in {f"journalnode-{i}" for i in range(3)} or
                    actor(root) != key or
                    port in registration and registration[port] != key or
                    key in storage and storage[key] != root):
                errors.append(f"ambiguous listener/storage registration port={port}")
            else:
                registration[port] = key
                storage[key] = root
        elif kind == "RPC_PEER_RESOLVED":
            port, key = event.get("port"), event.get("journalNode")
            if thread is None or registration.get(port) != key:
                errors.append(f"unregistered RPC peer port={port} actor={key}")
            else:
                last_peer[thread] = (seq, port, key)
        elif kind in {"FAULT_MATCHED", "FAULT_APPLIED"}:
            index = event.get("faultIndex")
            if not isinstance(index, int) or index >= len(plan) or index < 0:
                errors.append(f"unexpected {kind} index={index}")
                continue
            expected = plan[index]
            actual = [event.get("marker"), event.get("siteId"),
                      event.get("sourceKey"), str(event.get("hitOrdinal")),
                      event.get("faultType")]
            if len(expected) != 6 or expected[4] != "pending" or actual != [
                    expected[0], expected[1], expected[2], expected[3], expected[5]]:
                errors.append(f"fault {index} selector differs from requested plan")
            if thread is None:
                errors.append(f"fault {index} lacks JVM thread ID")
            fault_actor = actor(event.get("sourceKey"))
            if fault_actor is None:
                errors.append(f"fault {index} source has no JournalNode actor")
            if event.get("marker") == RPC:
                peer = last_peer.get(thread)
                if (peer is None or peer[2] != event.get("sourceKey") or
                        peer[0] >= seq or registration.get(peer[1]) != peer[2]):
                    errors.append(f"RPC fault {index} lacks same-thread registered peer")
            if kind == "FAULT_MATCHED":
                if index in matched:
                    errors.append(f"fault {index} matched more than once")
                matched[index] = event
            else:
                if index != last_index + 1:
                    errors.append(f"fault {index} applied out of order")
                last_index = index
                if index not in matched or matched[index].get("seq", -1) >= seq:
                    errors.append(f"fault {index} applied without earlier match")
                if index in applied:
                    errors.append(f"fault {index} applied more than once")
                applied[index] = event
    if len(storage) != 3 or set(registration.values()) != {
            "journalnode-0", "journalnode-1", "journalnode-2"}:
        errors.append("three JournalNode storage actors not registered")
    if set(matched) != set(range(len(plan))) or set(applied) != set(range(len(plan))):
        errors.append(f"matched/applied indexes {sorted(matched)}/{sorted(applied)}"
                      f" != plan {list(range(len(plan)))}")
    if plan and actor(plan[-1][2]) != target_actor:
        errors.append("final fault actor differs from selected target actor")
    final_seq = max((event.get("seq", -1) for event in applied.values()), default=-1)
    targets = [event for event in events if event.get("event") == "TARGET_CHECK"
               and event.get("siteId") == SITES[case]
               and event.get("journalNode") == target_actor
               and event.get("journalId") == "test-journal"
               and event.get("seq", -1) > final_seq]
    if not targets:
        errors.append(f"exact {case} target on {target_actor}/test-journal"
                      " absent after final applied fault")
    checked_threads = {(e.get("threadId"), e.get("seq")) for e in targets
                       if e.get("threadId") is not None}
    throws = [event for event in events if event.get("event") == "TARGET_THROW"
              and event.get("siteId") == SITES[case]
              and event.get("journalNode") == target_actor
              and (event.get("journalId") in (None, "test-journal"))
              and event.get("seq", -1) > final_seq
              and any(thread == event.get("threadId") and before < event.get("seq", -1)
                      for thread, before in checked_threads)]
    return {"pass": not errors, "case": "HDFS-" + case,
            "target_actor": target_actor, "target_site": SITES[case],
            "planned": len(plan), "matched": len(matched), "applied": len(applied),
            "last_fault_seq": final_seq,
            "post_fault_target_checks": len(targets),
            "post_fault_target_throws": len(throws),
            "post_fault_target_true_branch": sum(bool(e.get("guardWouldFail") or
                        (e.get("allowed") is False) or
                        (e.get("epochsEqual") is False)) for e in targets),
            "errors": errors}


def self_test() -> None:
    plan = [[RPC, "Client.getRpcResponse", "journalnode-2", "1", "pending", "IOException"]]
    events = [{"event": "NODE_PORT_REGISTER", "port": 21000 + i,
               "journalNode": f"journalnode-{i}",
               "storageRoot": f"/tmp/journalnode-{i}", "seq": i + 1}
              for i in range(3)]
    events += [
        {"event": "RPC_PEER_RESOLVED", "port": 21002,
         "journalNode": "journalnode-2", "threadId": 11, "seq": 4},
        {"event": "FAULT_MATCHED", "marker": RPC, "siteId": "Client.getRpcResponse",
         "sourceKey": "journalnode-2", "hitOrdinal": 1, "faultType": "IOException",
         "faultIndex": 0, "threadId": 11, "seq": 5},
        {"event": "FAULT_APPLIED", "marker": RPC, "siteId": "Client.getRpcResponse",
         "sourceKey": "journalnode-2", "hitOrdinal": 1, "faultType": "IOException",
         "faultIndex": 0, "threadId": 11, "seq": 6},
        {"event": "TARGET_CHECK", "journalNode": "journalnode-2",
         "journalId": "test-journal", "siteId": SITES["09"],
         "threadId": 12, "seq": 7, "allowed": True},
    ]
    assert audit(events, plan, "09", "journalnode-2")["pass"]
    assert not audit(events, plan, "10", "journalnode-2")["pass"]
    assert not audit(events, plan, "09", "journalnode-1")["pass"]
    assert not audit(events[1:], plan, "09", "journalnode-2")["pass"]
    wrong = [dict(e) for e in events]
    wrong[5]["threadId"] = 99
    assert not audit(wrong, plan, "09", "journalnode-2")["pass"]
    print("strict QJM actor/site/journal receipt smoke PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--case", choices=SITES)
    parser.add_argument("--target-actor")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.trace or not args.plan or not args.case or not args.target_actor:
            parser.error("--trace, --plan, --case and --target-actor are required")
        events = [json.loads(line) for line in args.trace.read_text().splitlines() if line.strip()]
        plan = [line.split("\t") for line in args.plan.read_text().splitlines()
                if line.strip() and not line.startswith("#")]
        receipt = audit(events, plan, args.case, args.target_actor)
        print(json.dumps(receipt, indent=2))
        raise SystemExit(0 if receipt["pass"] else 1)
