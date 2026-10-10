#!/usr/bin/env python3
"""Case-local exact retry-path and invalid-plan novelty policy."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
CORE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
sys.path[:0] = [str(CORE), str(BASE)]
from Mallory.core import campaign  # noqa: E402
from Mallory.core.audit import _load_archived_trace  # noqa: E402
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

DOOR = "hdfs:client-send-rpc-request:rename"
SEND = "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest"
NN = "hdfs-cluster-1/nn0"


def actor(event: dict) -> tuple:
    return event.get("node"), event.get("epoch"), event.get("thread_id"), event.get("occurrence")


def matching(events: list[dict], kind: str, **properties) -> list[dict]:
    return [e for e in events if e.get("type") == kind and
            all(e.get(key) == value for key, value in properties.items())]


def _one(events: list[dict], kind: str, **properties) -> dict | None:
    rows = matching(events, kind, **properties)
    return rows[0] if len(rows) == 1 else None


def strict_path(events: list[dict], plan: list[dict], target: dict) -> dict:
    """Demand every failed local send and one exact final retry RPC to nn0."""
    if not 1 <= len(plan) <= 3:
        return {"classification": "fault_count_out_of_scope"}
    if len(matching(events, "FAULT_APPLIED")) != len(plan):
        return {"classification": "unexpected_or_missing_applied_fault"}
    fault_rows = []
    for index, fault in enumerate(plan, 1):
        point = {"site": DOOR, "node": "hdfs-client", "epoch": 0,
                 "door_ordinal": index}
        if (fault.get("point") != point or fault.get("fault_type") != "EXCEPTION" or
                fault.get("exception_class") != "java.io.IOException"):
            return {"classification": "wrong_typed_fault_or_ordinal", "index": index}
        door = _one(events, "DOOR_OBSERVED", **point)
        matched = _one(events, "FAULT_MATCHED", fault_id=fault.get("fault_id"))
        applied = _one(events, "FAULT_APPLIED", fault_id=fault.get("fault_id"))
        if not all((door, matched, applied)):
            return {"classification": "fault_receipt_missing_or_ambiguous", "index": index}
        if not (all(all(e.get(k) == v for k, v in point.items()) and
                    e.get("exception_class") == "java.io.IOException"
                    for e in (door, matched, applied)) and
                actor(door) == actor(matched) == actor(applied) and
                isinstance(door.get("thread_id"), int) and
                door["seq"] < matched["seq"] < applied["seq"]):
            return {"classification": "fault_identity_or_order_mismatch", "index": index}
        fault_rows.append((door, matched, applied))
    first_actor = actor(fault_rows[0][0])
    if any(actor(row[0]) != first_actor or
           (i and fault_rows[i - 1][2]["seq"] >= row[0]["seq"])
           for i, row in enumerate(fault_rows)):
        return {"classification": "fault_chain_actor_or_order_mismatch"}
    retry = _one(events, "DOOR_OBSERVED", site=DOOR, node="hdfs-client", epoch=0,
                 door_ordinal=len(plan) + 1)
    if retry is None or actor(retry) != first_actor or retry["seq"] <= fault_rows[-1][2]["seq"]:
        return {"classification": "postfault_retry_door_missing"}
    doors = [row[0] for row in fault_rows] + [retry]
    for before, after in zip(doors, doors[1:]):
        if any(e.get("type") == "SEND" and e.get("site") == SEND and
               actor(e) == first_actor and before["seq"] < e["seq"] < after["seq"]
               for e in events):
            return {"classification": "failed_presend_attempt_emitted_request"}
    sends = [e for e in events if e.get("type") == "SEND" and
             e.get("site") == SEND and e.get("transport") == "hadoop-ipc" and
             e.get("port") == "request" and actor(e) == first_actor and
             e["seq"] > retry["seq"]]
    if not sends:
        return {"classification": "retry_request_send_missing"}
    send = min(sends, key=lambda e: e["seq"])
    token = send.get("correlation")
    if not isinstance(token, str) or not token or token == "unknown":
        return {"classification": "retry_token_unknown"}
    nn_recv = _one(events, "RECV", node=NN, transport="hadoop-ipc",
                   port="request", correlation=token)
    nn_send = _one(events, "SEND", node=NN, transport="hadoop-ipc",
                   port="response", correlation=token)
    client_recv = _one(events, "RECV", node="hdfs-client", transport="hadoop-ipc",
                       port="response", correlation=token)
    if (not all((nn_recv, nn_send, client_recv)) or
            not send["seq"] < nn_recv["seq"] < nn_send["seq"] < client_recv["seq"] or
            actor(nn_recv)[:3] != actor(nn_send)[:3] or
            actor(client_recv)[:3] != first_actor[:3] or
            nn_recv.get("context") != token or nn_send.get("context") != token):
        return {"classification": "retry_rpc_roundtrip_missing", "rpc_token": token}
    graph = OccurrenceGraph(tuple(events), reject_coarse_roots=True)
    candidates = []
    for check in events:
        if (check.get("type") != "TARGET_CHECK" or
                check.get("site") not in target["check_sites"] or
                check.get("node") != NN or check.get("epoch") != nn_recv.get("epoch") or
                check.get("context") != token or
                not nn_recv["seq"] < check["seq"] < nn_send["seq"]):
            continue
        path = graph.event_path(retry, check, require_edge=True)
        if path and any(edge.kind == "rpc" and edge.producer_event == send["id"] and
                        edge.consumer_event == nn_recv["id"] for edge in path):
            candidates.append((check, path))
    if len(candidates) != 1:
        return {"classification": "same_token_nn0_target_path_missing_or_ambiguous",
                "rpc_token": token, "path_count": len(candidates),
                "graph_gaps": dict(graph.gaps)}
    check, path = candidates[0]
    throws = [e for e in events if e.get("type") == "TARGET_THROW" and
              e.get("site") == target["throw_site"] and
              e.get("exception_class") == target["exception_class"] and
              e.get("node") == NN and e.get("context") == token and
              e["seq"] > check["seq"]]
    return {"classification": "exact_throw_source_review" if throws else
            "strict_multifault_retry_rpc_target", "fault_count": len(plan),
            "fault_event_ids": [row[2]["id"] for row in fault_rows],
            "retry_door_id": retry["id"], "request_send_id": send["id"],
            "request_recv_id": nn_recv["id"], "target_check_id": check["id"],
            "rpc_token": token, "target_throw_ids": [e["id"] for e in throws],
            "rpc_edge_ids": [[edge.producer_event, edge.consumer_event] for edge in path
                             if edge.kind == "rpc"]}


def trial_path(out: Path, result: dict, target: dict) -> dict:
    if result.get("trial_id") == 0:
        return {"classification": "healthy_seed"}
    trace, evidence = _load_archived_trace(
        out / "trials" / f"r{result['trial_id']:04d}", result)
    path = strict_path(list(trace.events), result.get("plan", []), target)
    path["trace_receipt"] = evidence
    return path


def qualifies(result: dict, path: dict) -> bool:
    junit = result.get("junit_validation", {})
    feedback = result.get("feedback", {})
    return (path.get("classification") == "strict_multifault_retry_rpc_target" and
            result.get("return_code") == 0 and result.get("timed_out") is False and
            junit.get("status") == "passed" and junit.get("tests") == 1 and
            junit.get("failures") == junit.get("errors") == 0 and
            feedback.get("all_faults_effective") is True and
            feedback.get("fault_identity_valid") is True and
            feedback.get("target_reached") is True)


def install_policy() -> None:
    """Prevent invalid results from affecting the derivative campaign state."""
    if getattr(campaign._apply_result, "_hdfs48_v6_policy", False):
        return
    original = campaign._apply_result

    def apply(state: dict, config: dict, result: dict, item: dict | None) -> None:
        if result.get("trial_id") == 0:
            original(state, config, result, item)
            return
        out = Path(state["out"])
        try:
            proof = trial_path(out, result, config["target"])
        except (OSError, ValueError) as exc:
            proof = {"classification": "trace_unverifiable", "detail": str(exc)}
        good = qualifies(result, proof)
        candidate = result if good else copy.deepcopy(result)
        if not good:
            feedback = candidate["feedback"]
            feedback["coverage_ids"] = []
            feedback["closure_coverage_ids"] = []
            feedback["closure_edges"] = []
            feedback["target_reached"] = False
            feedback["target_exception_candidate"] = False
        original(state, config, candidate, item)
        result["novelty"] = candidate["novelty"]
        result["selection_reason"] = candidate["selection_reason"]
        result["v6_strict_policy"] = {"qualified": good, "proof": proof,
                                      "novelty_credited": candidate["novelty"]}
        campaign.atomic_json(out / "trials" / f"r{result['trial_id']:04d}" / "result.json", result)

    apply._hdfs48_v6_policy = True
    campaign._apply_result = apply


def run(config: Path, out: Path) -> dict:
    install_policy()
    return campaign.run(config, out)
