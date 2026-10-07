#!/usr/bin/env python3
"""Validate HDFS-16 V2 sender, NN peer, ordered faults, and target context."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def audit(events: list[dict], plan: list[list[str]], context: dict) -> dict:
    nn_ports: set[int] = set()
    bound: dict[str, str | None] = {}
    applied: list[dict] = []
    errors: list[str] = []
    for event in events:
        kind = event.get("event")
        thread = event.get("thread", "")
        if kind == "NN_ENDPOINT_REGISTER":
            nn_ports.add(event.get("peerPort"))
        elif kind == "DN_RPC_BIND":
            bound[thread] = event.get("senderActor")
        elif kind == "DN_RPC_UNBIND":
            bound[thread] = None
        elif kind == "FAULT_APPLIED":
            index = len(applied)
            if index >= len(plan):
                errors.append("more applied faults than requested")
                continue
            expected = plan[index]
            actual = [event.get("marker"), event.get("api"), event.get("senderActor"),
                      str(event.get("ordinal")), event.get("exception")]
            if actual != expected:
                errors.append(f"fault {index} selector mismatch: {actual} != {expected}")
            if event.get("marker") == "RPC_RESPONSE":
                if bound.get(thread) != event.get("senderActor"):
                    errors.append(f"fault {index} has no same-thread DN binding")
                if event.get("peerPort") not in nn_ports:
                    errors.append(f"fault {index} has no registered NN endpoint")
            applied.append(event)
    if len(applied) != len(plan):
        errors.append(f"applied {len(applied)} of {len(plan)} requested faults")
    final_seq = max((event.get("seq", -1) for event in applied), default=-1)
    target = [event for event in events if event.get("event") == "TARGET_GUARD"
              and event.get("seq", -1) > final_seq
              and event.get("blockId") == context["block_id"]
              and event.get("caller") == context["caller"]
              and event.get("proposedGenerationStamp") == context["proposed_generation_stamp"]]
    if not target:
        errors.append("same block/caller/proposed-stamp target absent after final fault")
    exceptions = [event for event in events if event.get("event") == "TARGET_EXCEPTION"
                  and event.get("seq", -1) > final_seq
                  and event.get("blockId") == context["block_id"]
                  and event.get("caller") == context["caller"]
                  and event.get("proposedGenerationStamp") == context["proposed_generation_stamp"]]
    return {"pass": not errors, "requested": len(plan), "applied": len(applied),
            "last_fault_seq": final_seq, "same_context_postfault_targets": len(target),
            "same_context_postfault_exceptions": len(exceptions), "errors": errors}


def self_test() -> None:
    plan = [["RPC_RESPONSE", "DatanodeProtocolClientSideTranslatorPB.registerDatanode",
             "dn:dn-one|bp:bp-one", "2", "EOFException"]]
    context = {"block_id": 7, "caller": "BlockManager.updateLastBlock",
               "proposed_generation_stamp": 1002}
    events = [
        {"seq": 1, "event": "NN_ENDPOINT_REGISTER", "peerPort": 19001},
        {"seq": 2, "event": "DN_RPC_BIND", "thread": "main", "senderActor": "dn:dn-one|bp:bp-one"},
        {"seq": 3, "event": "FAULT_APPLIED", "thread": "main", "marker": "RPC_RESPONSE",
         "api": plan[0][1], "senderActor": plan[0][2], "ordinal": 2,
         "exception": "EOFException", "peerPort": 19001},
        {"seq": 4, "event": "DN_RPC_UNBIND", "thread": "main"},
        {"seq": 5, "event": "TARGET_GUARD", "blockId": 7,
         "caller": "BlockManager.updateLastBlock", "proposedGenerationStamp": 1002},
    ]
    assert audit(events, plan, context)["pass"]
    wrong = [dict(e) for e in events]
    wrong[2]["senderActor"] = "dn:dn-two|bp:bp-one"
    assert not audit(wrong, plan, context)["pass"]
    wrong = [dict(e) for e in events]
    wrong[-1]["proposedGenerationStamp"] = 1003
    assert not audit(wrong, plan, context)["pass"]
    print("HDFS-16 strict actor/context receipt smoke PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--target-context", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if not args.trace or not args.plan or not args.target_context:
            parser.error("--trace, --plan and --target-context are required")
        events = [json.loads(line) for line in args.trace.read_text().splitlines() if line.strip()]
        plan = [line.split("\t") for line in args.plan.read_text().splitlines()
                if line.strip() and not line.startswith("#")]
        context = json.loads(args.target_context.read_text())
        receipt = audit(events, plan, context)
        print(json.dumps(receipt, indent=2))
        raise SystemExit(0 if receipt["pass"] else 1)
