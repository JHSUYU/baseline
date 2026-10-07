#!/usr/bin/env python3
"""Validate HDFS-39 V2 actor/peer and exact file/block post-fault guard."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def audit(events: list[dict], plan: list[list[str]], context: dict) -> dict:
    nn_port: int | None = None
    pool: str | None = None
    roles: dict[str, str] = {}
    binding: dict[str, tuple[str, str, str] | None] = {}
    matched: list[dict] = []
    applied: list[dict] = []
    errors: list[str] = []
    for event in events:
        kind, thread = event.get("event"), event.get("thread", "")
        if kind == "NN_ENDPOINT_REGISTER":
            port, bp = event.get("peerPort"), event.get("blockPoolId")
            if nn_port is not None and (nn_port != port or pool != bp):
                errors.append("conflicting NN/BP fixture registration")
            nn_port, pool = port, bp
        elif kind == "DN_ROLE_MAP":
            uuid, role = event.get("sourceUuid"), event.get("role")
            if not uuid or not role or uuid in roles and roles[uuid] != role:
                errors.append("ambiguous DataNode UUID/role map")
            roles[uuid] = role
        elif kind == "DN_RPC_BIND":
            binding[thread] = (event.get("sourceUuid"), event.get("blockPoolId"),
                               event.get("sourceRole"))
        elif kind == "DN_RPC_UNBIND":
            binding[thread] = None
        elif kind == "FAULT_MATCHED":
            matched.append(event)
        elif kind == "FAULT_APPLIED":
            index = len(applied)
            if index >= len(plan):
                errors.append("extra applied fault")
                continue
            expected = plan[index]
            actual = [event.get("marker"), event.get("api"), event.get("endpoint"),
                      str(event.get("ordinal")), event.get("exception")]
            if actual != expected:
                errors.append(f"fault {index} selector mismatch: {actual} != {expected}")
            marker, endpoint = event.get("marker", ""), event.get("endpoint", "")
            api = event.get("api", "")
            if marker.startswith("RPC_"):
                if nn_port is None or event.get("peerPort") != nn_port:
                    errors.append(f"fault {index} lacks exact NN peer")
                if endpoint.startswith("nn0<-dn"):
                    current = binding.get(thread)
                    if current is None:
                        errors.append(f"fault {index} lacks same-thread DN binding")
                    else:
                        uuid, bp, role = current
                        if roles.get(uuid) != role or bp != pool or endpoint != "nn0<-" + role:
                            errors.append(f"fault {index} DN UUID/BP/role mismatch")
                        if event.get("sourceUuid") != uuid or event.get("blockPoolId") != bp:
                            errors.append(f"fault {index} raw source identity mismatch")
                    if api.startswith("DatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted"):
                        block_ids = re.fullmatch(
                            r"DatanodeProtocolClientSideTranslatorPB\.blockReceivedAndDeleted"
                            r"\[blockReceivedAndDeleted:blocks=\[([1-9][0-9]*(?:, [1-9][0-9]*)*)\]\]",
                            api)
                        if not block_ids or context["block_id"] not in {
                                int(value) for value in block_ids.group(1).split(", ")}:
                            errors.append(f"fault {index} lacks target block association")
                elif endpoint != "nn0<-client":
                    errors.append(f"fault {index} unknown RPC endpoint")
                elif api.startswith("ClientNamenodeProtocolTranslatorPB.append") and (
                        api != "ClientNamenodeProtocolTranslatorPB.append"
                        f"[append:{context['path']}]"):
                    errors.append(f"fault {index} lacks target path association")
            applied.append(event)
    if len(roles) != 4 or set(roles.values()) != {"dn0", "dn1", "dn2", "dn3"}:
        errors.append("four-DN fixture actor map incomplete")
    if len(applied) != len(plan):
        errors.append(f"applied {len(applied)} of {len(plan)} requested faults")
    if len(matched) != len(applied):
        errors.append(f"matched {len(matched)} differs from applied {len(applied)}")
    final_seq = max((event.get("seq", -1) for event in applied), default=-1)
    targets = [event for event in events if event.get("event") == "TARGET_GUARD"
               and event.get("seq", -1) > final_seq
               and event.get("site") == "FSDirAppendOp.appendFile:131"
               and event.get("path") == context["path"]
               and event.get("blockId") == context["block_id"]]
    if not targets:
        errors.append("same file/block guard absent after final applied fault")
    committed = {(event.get("thread"), event.get("ordinal")) for event in targets
                 if event.get("committed")}
    exceptions = [event for event in events if event.get("event") == "TARGET_EXCEPTION"
                  and event.get("seq", -1) > final_seq
                  and event.get("site") == "FSDirAppendOp.appendFile:131"
                  and event.get("type") == "org.apache.hadoop.ipc.RetriableException"
                  and event.get("path") == context["path"]
                  and event.get("blockId") == context["block_id"]
                  and (event.get("thread"), event.get("ordinal")) in committed]
    return {"pass": not errors, "requested": len(plan), "applied": len(applied),
            "last_fault_seq": final_seq, "postfault_target_checks": len(targets),
            "postfault_committed_checks": sum(bool(t.get("committed")) for t in targets),
            "postfault_target_exceptions": len(exceptions), "errors": errors}


def self_test() -> None:
    plan = [["RPC_SEND", "DatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted"
             "[blockReceivedAndDeleted:blocks=[7]]", "nn0<-dn1", "1", "EOFException"]]
    context = {"path": "/testMultipleAppend/foo", "block_id": 7}
    events = [{"seq": 1, "event": "NN_ENDPOINT_REGISTER", "peerPort": 19001,
               "blockPoolId": "bp1"}]
    events += [{"seq": i + 2, "event": "DN_ROLE_MAP", "sourceUuid": "uuid-" + str(i),
                "role": "dn" + str(i)} for i in range(4)]
    events += [
        {"seq": 6, "event": "DN_RPC_BIND", "thread": "BP", "sourceUuid": "uuid-1",
         "blockPoolId": "bp1", "sourceRole": "dn1"},
        {"seq": 7, "event": "FAULT_MATCHED", "thread": "BP", "marker": "RPC_SEND",
         "api": plan[0][1], "endpoint": "nn0<-dn1", "ordinal": 1},
        {"seq": 8, "event": "FAULT_APPLIED", "thread": "BP", "marker": "RPC_SEND",
         "api": plan[0][1], "endpoint": "nn0<-dn1", "ordinal": 1,
         "exception": "EOFException", "peerPort": 19001,
         "sourceUuid": "uuid-1", "blockPoolId": "bp1"},
        {"seq": 9, "event": "DN_RPC_UNBIND", "thread": "BP"},
        {"seq": 10, "event": "TARGET_GUARD", "thread": "NN",
         "site": "FSDirAppendOp.appendFile:131", "path": context["path"],
         "blockId": 7, "committed": True},
    ]
    assert audit(events, plan, context)["pass"]
    wrong = [dict(e) for e in events]
    wrong[7]["sourceUuid"] = "uuid-0"
    assert not audit(wrong, plan, context)["pass"]
    wrong = [dict(e) for e in events]
    wrong[-1]["blockId"] = 8
    assert not audit(wrong, plan, context)["pass"]
    wrong_plan = [list(value) for value in plan]
    wrong_plan[0][1] = wrong_plan[0][1].replace("blocks=[7]", "blocks=[8]")
    wrong = [dict(e) for e in events]
    for event in wrong:
        if event.get("event") in {"FAULT_MATCHED", "FAULT_APPLIED"}:
            event["api"] = wrong_plan[0][1]
    assert not audit(wrong, wrong_plan, context)["pass"]
    print("HDFS-39 strict actor/file/block receipt smoke PASS")


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
