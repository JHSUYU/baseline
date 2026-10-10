#!/usr/bin/env python3
"""Strict identity and postfault path audit; never makes a new-bug claim."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
V4 = HERE.parent / "hdfs48-rename-presend-node2-v4"
DOOR = "hdfs:client-send-rpc-request:rename"
SEND = "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest"
NN = "hdfs-cluster-1/nn0"
CORE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
sys.path[:0] = [str(CORE), str(BASE)]
from Mallory.core.audit import _load_archived_trace, audit_campaign  # noqa: E402
from Mallory.core.graph import OccurrenceGraph  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def point_equal(event: dict, point: dict) -> bool:
    return all(event.get(k) == v for k, v in point.items())


def actor(event: dict) -> tuple:
    return event.get("node"), event.get("epoch"), event.get("thread_id")


def unique(events: list[dict], *, kind: str, token: str, port: str, node: str) -> dict | None:
    rows = [e for e in events if e.get("type") == kind and
            e.get("transport") == "hadoop-ipc" and e.get("port") == port and
            e.get("correlation") == token and e.get("node") == node]
    return rows[0] if len(rows) == 1 else None


def witness(events: list[dict], fault: dict, check_sites: set[str], throw_site: str) -> dict:
    point = fault.get("point", {})
    fid = fault.get("fault_id")
    if (set(point) != {"site", "node", "epoch", "door_ordinal"} or
            point != {"site": DOOR, "node": "hdfs-client", "epoch": 0,
                      "door_ordinal": 1} or
            fault.get("fault_type") != "EXCEPTION" or
            fault.get("exception_class") != "java.io.IOException" or
            not isinstance(fid, str) or not fid):
        return {"classification": "wrong_fault_plan"}
    rows = {}
    for typ in ("DOOR_OBSERVED", "FAULT_MATCHED", "FAULT_APPLIED"):
        selected = [e for e in events if e.get("type") == typ and
                    (point_equal(e, point) if typ == "DOOR_OBSERVED" else
                     e.get("fault_id") == fid)]
        if len(selected) != 1:
            return {"classification": "fault_receipt_missing_or_ambiguous", "event_type": typ}
        rows[typ] = selected[0]
    door, matched, applied = (rows[t] for t in ("DOOR_OBSERVED", "FAULT_MATCHED", "FAULT_APPLIED"))
    if not (all(point_equal(e, point) and e.get("exception_class") == "java.io.IOException"
                for e in (door, matched, applied)) and
            actor(door) == actor(matched) == actor(applied) == ("hdfs-client", 0, door.get("thread_id")) and
            isinstance(door.get("thread_id"), int) and
            door.get("occurrence") == matched.get("occurrence") == applied.get("occurrence") and
            door["seq"] < matched["seq"] < applied["seq"]):
        return {"classification": "fault_actor_epoch_or_occurrence_mismatch"}
    retries = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
               e.get("site") == DOOR and e.get("exception_class") == "java.io.IOException" and
               actor(e) == actor(applied) and e["seq"] > applied["seq"]]
    if len(retries) != 1:
        return {"classification": "retry_door_missing_or_ambiguous", "retry_doors": len(retries)}
    retry = retries[0]
    if retry.get("door_ordinal") != 2 or retry.get("occurrence") != applied.get("occurrence"):
        return {"classification": "retry_door_identity_mismatch"}
    if len([e for e in events if e.get("type") == "FAULT_APPLIED"]) != 1:
        return {"classification": "additional_applied_fault"}
    if any(e.get("type") == "SEND" and e.get("site") == SEND and
           actor(e) == actor(applied) and door["seq"] < e["seq"] < retry["seq"]
           for e in events):
        return {"classification": "faulted_presend_attempt_emitted_request"}
    sends = [e for e in events if e.get("type") == "SEND" and
             e.get("site") == SEND and e.get("port") == "request" and
             e.get("transport") == "hadoop-ipc" and actor(e) == actor(retry) and
             e.get("occurrence") == retry.get("occurrence") and e["seq"] > retry["seq"]]
    if not sends:
        return {"classification": "retry_request_send_missing_or_ambiguous", "sends": 0}
    send = min(sends, key=lambda event: event["seq"])
    token = send.get("correlation")
    if not isinstance(token, str) or not token or token == "unknown":
        return {"classification": "retry_rpc_token_unknown"}
    recv = unique(events, kind="RECV", token=token, port="request", node=NN)
    response = unique(events, kind="SEND", token=token, port="response", node=NN)
    client_recv = unique(events, kind="RECV", token=token, port="response", node="hdfs-client")
    if (not all((recv, response, client_recv)) or
            not retry["seq"] < send["seq"] < recv["seq"] < response["seq"] < client_recv["seq"] or
            actor(client_recv) != actor(retry) or actor(response) != actor(recv) or
            recv.get("context") != token or response.get("context") != token):
        return {"classification": "retry_rpc_roundtrip_missing_or_ambiguous", "rpc_token": token}
    targets = [e for e in events if e.get("type") == "TARGET_CHECK" and
               e.get("site") in check_sites and e.get("node") == NN and
               e.get("context") == token and e.get("epoch") == recv.get("epoch") and
               recv["seq"] < e["seq"] < response["seq"]]
    graph = OccurrenceGraph(tuple(events), reject_coarse_roots=True)
    paths = [(e, graph.event_path(retry, e, require_edge=True)) for e in targets]
    paths = [(e, path) for e, path in paths if path and
             any(edge.kind == "rpc" and edge.producer_event == send.get("id") and
                 edge.consumer_event == recv.get("id") for edge in path)]
    if len(paths) != 1:
        return {"classification": "postfault_nn0_target_path_missing_or_ambiguous",
                "rpc_token": token, "target_count": len(targets), "path_count": len(paths),
                "graph_gaps": dict(graph.gaps)}
    target, path = paths[0]
    throws = [e for e in events if e.get("type") == "TARGET_THROW" and
              e.get("site") == throw_site and e.get("node") == NN and
              e.get("context") == token and e["seq"] > target["seq"]]
    return {"classification": "exact_target_throw_source_review" if throws else
            "strict_postfault_retry_rpc_target", "fault_id": fid,
            "fault_event_ids": {t.lower(): rows[t]["id"] for t in rows},
            "retry_door_id": retry["id"], "retry_request_send_id": send["id"],
            "rpc_token": token, "nn0_request_recv_id": recv["id"],
            "nn0_response_send_id": response["id"], "client_response_recv_id": client_recv["id"],
            "target_check_id": target["id"], "target_throw_ids": [e["id"] for e in throws],
            "graph_edges": [{"kind": e.kind, "producer": e.producer_event,
                             "consumer": e.consumer_event} for e in path],
            "pending_call_source_risk": True}


def healthy_witness(events: list[dict], check_sites: set[str]) -> bool:
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
             e.get("site") == DOOR and e.get("node") == "hdfs-client" and
             e.get("exception_class") == "java.io.IOException"]
    if len(doors) != 1 or any(e.get("type") == "FAULT_APPLIED" for e in events):
        return False
    door = doors[0]
    sends = [e for e in events if e.get("type") == "SEND" and
             e.get("site") == SEND and e.get("transport") == "hadoop-ipc" and
             e.get("port") == "request" and actor(e) == actor(door) and
             e.get("occurrence") == door.get("occurrence") and e["seq"] > door["seq"]]
    if not sends:
        return False
    send = min(sends, key=lambda event: event["seq"])
    token = send.get("correlation")
    recv = unique(events, kind="RECV", token=token, port="request", node=NN)
    if recv is None or recv["seq"] <= send["seq"]:
        return False
    graph = OccurrenceGraph(tuple(events), reject_coarse_roots=True)
    for target in events:
        if (target.get("type") != "TARGET_CHECK" or
                target.get("site") not in check_sites or
                target.get("node") != NN or target.get("context") != token or
                target["seq"] <= recv["seq"]):
            continue
        path = graph.event_path(door, target, require_edge=True)
        if path and any(e.kind == "rpc" and e.producer_event == send["id"] and
                        e.consumer_event == recv["id"] for e in path):
            return True
    return False


def check(campaign: Path) -> dict:
    cfg = json.loads((campaign / "config.json").read_text())
    summary = json.loads((campaign / "result.json").read_text())
    staged = json.loads((HERE / "HDFS-48-node2-one-fault-full-v5.json").read_text())
    errors = []
    if cfg != staged:
        errors.append("campaign_config_not_staged_v5")
    if (summary.get("status") not in {"budget_exhausted", "queue_exhausted"} or
            summary.get("healthy_seed_valid") is not True or
            summary.get("fault_trials_completed") != 1):
        errors.append("not_terminal_one_fault_with_valid_seed")
    results = []
    traces = []
    for i in (0, 1):
        trial = campaign / "trials" / f"r{i:04d}"
        result = json.loads((trial / "result.json").read_text())
        trace, evidence = _load_archived_trace(trial, result)
        results.append(result)
        traces.append((list(trace.events), evidence))
    healthy, faulted = results
    if (healthy.get("junit_validation", {}).get("status") != "passed" or
            healthy.get("junit_validation", {}).get("tests") != 1 or
            healthy.get("junit_validation", {}).get("failures") != 0 or
            healthy.get("junit_validation", {}).get("errors") != 0 or
            healthy.get("feedback", {}).get("target_reached") is not True or
            healthy.get("feedback", {}).get("target_threw") is not False):
        errors.append("fresh_v5_healthy_seed_not_1_0_0_nonthrowing")
    if not healthy_witness(traces[0][0], set(cfg["target"]["check_sites"])):
        errors.append("fresh_v5_healthy_strict_named_path_missing")
    if (faulted.get("return_code") != 0 or faulted.get("timed_out") is not False):
        errors.append("fault_trial_did_not_exit_cleanly")
    if (faulted.get("feedback", {}).get("all_faults_effective") is not True or
            faulted.get("feedback", {}).get("fault_identity_valid") is not True):
        errors.append("fault_effectiveness_or_identity_failed")
    plan = faulted.get("plan", [])
    if len(plan) != 1:
        errors.append("not_one_fault_in_plan")
        path = {"classification": "wrong_fault_count"}
    else:
        path = witness(traces[1][0], plan[0], set(cfg["target"]["check_sites"]),
                       cfg["target"]["throw_site"])
    if path["classification"] not in {"strict_postfault_retry_rpc_target",
                                      "exact_target_throw_source_review"}:
        errors.append(path["classification"])
    # Successful termination proves this JUnit's shutdown returned. The source
    # registers the first call before the hook and does not remove it on send
    # failure; the warning is recorded, never interpreted as map cleanup proof.
    trial = campaign / "trials/r0001"
    logs = "\n".join((trial / name).read_text(errors="replace")
                     for name in ("stdout.log", "stderr.log") if (trial / name).is_file())
    warning = "A connection is closed for no cause and calls are not empty" in logs
    core_audit = audit_campaign(campaign, campaign / "offline-causal-audit.json")
    if core_audit.get("report_gate_passed") is not True:
        errors.append("core_offline_causal_audit_failed")
    return {"schema_version": 1, "case_id": "HDFS-48", "new_bug": False,
            "scope": "one_fault_full_identity_and_source_review",
            "v4_healthy_receipt_sha256": "0fe0af3ad2ac745fc12cadcd0c20237012ddf232db5b0a8f9e94edc55e2c3067",
            "campaign_result_sha256": sha(campaign / "result.json"),
            "fault_trial_result_sha256": sha(trial / "result.json"),
            "fault_trial_trace": traces[1][1], "fault_path": path,
            "fault_trial_return_code": faulted.get("return_code"),
            "fault_trial_timed_out": faulted.get("timed_out"),
            "fault_trial_junit": faulted.get("junit_validation"),
            "pending_call_cleanup_warning_observed": warning,
            "pending_call_map_count_observed": False,
            "core_offline_causal_gate_passed": core_audit.get("report_gate_passed"),
            "source_review_required": path["classification"] == "exact_target_throw_source_review" or warning,
            "strict_gate_passed": not errors, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = check(args.campaign)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"strict_gate_passed": report["strict_gate_passed"],
                      "classification": report["fault_path"]["classification"]}, sort_keys=True))
    return 0 if report["strict_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
