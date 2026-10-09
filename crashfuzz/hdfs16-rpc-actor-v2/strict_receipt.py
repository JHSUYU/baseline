#!/usr/bin/env python3
"""Validate HDFS-16 V2 sender, NN peer, ordered faults, and target context."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def audit(events: list[dict], plan: list[list[str]], context: dict) -> dict:
    nn_ports: set[int] = set()
    roles: dict[str, str] = {}
    bound: dict[int, tuple[str, str] | None] = {}
    matched: list[dict] = []
    applied: list[dict] = []
    errors: list[str] = []
    if (context.get("caller") not in
            {"BlockManager.updateLastBlock", "BlockInfo.commitBlock"} or
            context.get("block_role") != "original_test_file_block" or
            set(context) != {"caller", "block_role"}):
        errors.append("selected target is not the original single-file update-pipeline phase")
    for event in events:
        kind = event.get("event")
        thread = event.get("threadId")
        if kind == "NN_ENDPOINT_REGISTER":
            port = event.get("peerPort")
            if not isinstance(port, int) or port <= 0:
                errors.append("invalid NN endpoint registration")
            else:
                nn_ports.add(port)
        elif kind == "DN_ROLE_REGISTER":
            role, uuid = event.get("senderRole"), event.get("dnUuid")
            if (role not in {"dn0", "dn1"} or not isinstance(uuid, str) or
                    not uuid or role in roles and roles[role] != uuid or
                    uuid in roles.values() and roles.get(role) != uuid):
                errors.append("ambiguous DN list-position to UUID registration")
            else:
                roles[role] = uuid
        elif kind == "DN_ROLE_CONFLICT":
            errors.append("runtime DataNode role was ambiguous")
        elif kind == "DN_RPC_BIND":
            raw, role = event.get("senderActor"), event.get("senderRole")
            uuid, bp = event.get("senderDnUuid"), event.get("blockPoolId")
            if not isinstance(thread, int):
                errors.append("DN RPC binding lacks numeric thread identity")
            elif not role:
                # BP workers may register before the original JUnit retrieves
                # MiniDFSCluster.getDataNodes(). These calls are uninjectible.
                bound[thread] = None
            elif (roles.get(role) != uuid or not bp or
                    raw != f"dn:{uuid}|bp:{bp}"):
                errors.append("DN RPC binding lacks role/UUID/BP/thread proof")
            else:
                bound[thread] = (raw, role)
        elif kind == "DN_RPC_UNBIND":
            raw, role = event.get("senderActor"), event.get("senderRole")
            bound[thread] = (raw, role) if raw and role else None
        elif kind in {"FAULT_MATCHED", "FAULT_APPLIED"}:
            if kind == "FAULT_MATCHED":
                matched.append(event)
                continue
            index = len(applied)
            if index >= len(plan):
                errors.append("more applied faults than requested")
                continue
            expected = plan[index]
            if (len(expected) != 5 or len(matched) <= index or
                    matched[index].get("seq", -1) >= event.get("seq", -1) or
                    any(matched[index].get(key) != event.get(key) for key in
                        ("marker", "api", "senderActor", "senderRole", "ordinal", "threadId"))):
                errors.append(f"fault {index} lacks matching earlier selector")
            actual = [event.get("marker"), event.get("api"), event.get("senderRole"),
                      str(event.get("ordinal")), event.get("exception")]
            if actual != expected:
                errors.append(f"fault {index} selector mismatch: {actual} != {expected}")
            if event.get("marker") == "RPC_RESPONSE":
                if (not isinstance(thread, int) or bound.get(thread) !=
                        (event.get("senderActor"), event.get("senderRole"))):
                    errors.append(f"fault {index} has no same-thread DN binding")
                if event.get("peerPort") not in nn_ports:
                    errors.append(f"fault {index} has no registered NN endpoint")
            elif event.get("marker") == "FILE_FLUSH":
                if event.get("senderActor") != "nn-editlog" or event.get("senderRole") != "nn-editlog":
                    errors.append(f"fault {index} has no sole-NN edit-log identity")
            else:
                errors.append(f"fault {index} unknown marker")
            applied.append(event)
    if set(roles) != {"dn0", "dn1"}:
        errors.append("two distinct DataNode roles not registered")
    if len(matched) != len(plan) or len(applied) != len(plan):
        errors.append(f"matched/applied {len(matched)}/{len(applied)} of {len(plan)}")
    final_seq = max((event.get("seq", -1) for event in applied), default=-1)
    target = [event for event in events if event.get("event") == "TARGET_GUARD"
              and event.get("seq", -1) > final_seq
              and event.get("site") == "BlockInfo.setGenerationStampAndVerifyReplicas:428"
              and event.get("caller") == context["caller"]
              and isinstance(event.get("blockId"), int)
              and isinstance(event.get("proposedGenerationStamp"), int)]
    if not target:
        errors.append("original-test target caller absent after final fault")
    if len({event["blockId"] for event in target}) > 1:
        errors.append("postfault target spans more than one concrete block")
    target_contexts = [{"block_id": event["blockId"], "caller": event["caller"],
                        "proposed_generation_stamp": event["proposedGenerationStamp"]}
                       for event in target]
    exceptions = [event for event in events if event.get("event") == "TARGET_EXCEPTION"
                  and event.get("seq", -1) > final_seq
                  and event.get("site") == "BlockInfo.setGenerationStampAndVerifyReplicas:428"
                  and event.get("caller") == context["caller"]
                  and event.get("type") == "java.lang.IllegalStateException"
                  and any(event.get("blockId") == guard["blockId"] and
                          event.get("proposedGenerationStamp") == guard["proposedGenerationStamp"]
                          and event.get("threadId") == guard.get("threadId")
                          and event.get("seq", -1) > guard.get("seq", -1)
                          for guard in target)]
    return {"pass": not errors, "requested": len(plan), "matched": len(matched),
            "applied": len(applied),
            "last_fault_seq": final_seq, "same_context_postfault_targets": len(target),
            "same_context_postfault_exceptions": len(exceptions),
            "concrete_postfault_target_contexts": target_contexts, "errors": errors}


def self_test() -> None:
    plan = [["RPC_RESPONSE", "DatanodeProtocolClientSideTranslatorPB.registerDatanode",
             "dn0", "2", "EOFException"]]
    context = {"caller": "BlockManager.updateLastBlock",
               "block_role": "original_test_file_block"}
    events = [
        {"seq": 1, "event": "NN_ENDPOINT_REGISTER", "peerPort": 19001},
        {"seq": 2, "event": "DN_ROLE_REGISTER", "senderRole": "dn0", "dnUuid": "dn-one"},
        {"seq": 3, "event": "DN_ROLE_REGISTER", "senderRole": "dn1", "dnUuid": "dn-two"},
        {"seq": 4, "event": "DN_RPC_BIND", "threadId": 11, "senderActor": "dn:dn-one|bp:bp-one",
         "senderRole": "dn0", "senderDnUuid": "dn-one", "blockPoolId": "bp-one"},
        {"seq": 5, "event": "FAULT_MATCHED", "threadId": 11, "marker": "RPC_RESPONSE",
         "api": plan[0][1], "senderActor": "dn:dn-one|bp:bp-one", "senderRole": "dn0", "ordinal": 2,
         "peerPort": 19001},
        {"seq": 6, "event": "FAULT_APPLIED", "threadId": 11, "marker": "RPC_RESPONSE",
         "api": plan[0][1], "senderActor": "dn:dn-one|bp:bp-one", "senderRole": "dn0", "ordinal": 2,
         "exception": "EOFException", "peerPort": 19001},
        {"seq": 7, "event": "DN_RPC_UNBIND", "threadId": 11},
        {"seq": 8, "event": "TARGET_GUARD", "threadId": 12, "site": "BlockInfo.setGenerationStampAndVerifyReplicas:428", "blockId": 7,
         "caller": "BlockManager.updateLastBlock", "proposedGenerationStamp": 1002},
    ]
    assert audit(events, plan, context)["pass"]
    early = [{"seq": 0, "event": "DN_RPC_BIND", "threadId": 99,
              "senderActor": "dn:startup|bp:bp-one", "senderRole": "",
              "senderDnUuid": "startup", "blockPoolId": "bp-one"}] + events
    assert audit(early, plan, context)["pass"]
    wrong = [dict(e) for e in events]
    wrong[5]["senderActor"] = "dn:dn-two|bp:bp-one"
    assert not audit(wrong, plan, context)["pass"]
    wrong = [dict(e) for e in events]
    wrong[-1]["caller"] = "other"
    assert not audit(wrong, plan, context)["pass"]
    exception = {"seq": 9, "event": "TARGET_EXCEPTION", "threadId": 12,
                 "site": "BlockInfo.setGenerationStampAndVerifyReplicas:428",
                 "blockId": 7, "caller": "BlockManager.updateLastBlock",
                 "proposedGenerationStamp": 1002,
                 "type": "java.lang.IllegalStateException"}
    assert audit(events + [exception], plan, context)["same_context_postfault_exceptions"] == 1
    wrong = dict(exception, proposedGenerationStamp=1003)
    assert audit(events + [wrong], plan, context)["same_context_postfault_exceptions"] == 0
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
