#!/usr/bin/env python3
"""Verify the typed Get fault and same relocateRegion invocation in HBASE-02."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph


DOOR = ("org.apache.hadoop.hbase.ipc.RpcServer#call"
        "(Lorg/apache/hadoop/hbase/ipc/RpcCall;"
        "Lorg/apache/hadoop/hbase/monitoring/MonitoredRPCHandler;)"
        "Lorg/apache/hadoop/hbase/util/Pair;@447:door:1:rpc:"
        "hbase.pb.ClientService.Get")
TARGET = ("org.apache.hadoop.hbase.client.ConnectionImplementation#relocateRegion"
          "(Lorg/apache/hadoop/hbase/TableName;[BI)"
          "Lorg/apache/hadoop/hbase/RegionLocations;@910:branch:2")
PORT = "hbase.pb.ClientService.Get"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def unique(events: list[dict], predicate, label: str) -> dict:
    matches = [event for event in events if predicate(event)]
    require(len(matches) == 1, f"{label}: expected one event, got {len(matches)}")
    return matches[0]


def event_record(event: dict) -> dict:
    return {key: event.get(key) for key in
            ("id", "seq", "type", "site", "node", "epoch", "occurrence",
             "thread_id", "context", "correlation", "port", "outcome")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    root = args.campaign.resolve()
    result_bytes = (root / "result.json").read_bytes()
    audit_bytes = (root / "offline-causal-audit.json").read_bytes()
    result, audit = json.loads(result_bytes), json.loads(audit_bytes)
    require(result["case_id"] == audit["case_id"] == "HBASE-02", "case changed")
    require(result["status"] == "queue_exhausted" and
            result["fault_trials_completed"] == 1 and
            result["strict_injected_trials"] == 1 and
            result["strict_target_trials"] == 1 and
            result["exact_exception_trials"] == 0, "pilot outcome changed")
    require(audit["campaign_result_sha256"] == sha(result_bytes) and
            audit["report_gate_passed"] and audit["reject_coarse_roots"] and
            audit["require_event_time_paths"], "causal audit failed")
    trial_dir = root / "trials" / "r0001"
    trial_bytes = (trial_dir / "result.json").read_bytes()
    trial = json.loads(trial_bytes)
    plan_bytes = (trial_dir / "plan.json").read_bytes()
    plan = json.loads(plan_bytes)
    require(len(plan["faults"]) == 1 and
            plan["faults"][0]["point"]["site"] == DOOR and
            plan["faults"][0]["point"]["node"] == "rs0" and
            plan["faults"][0]["exception_class"] == "java.io.IOException",
            "typed Get fault plan changed")
    require(trial["junit_validation"]["status"] == "passed" and
            all(trial["feedback"][key] for key in
                ("all_faults_matched", "all_faults_applied", "all_faults_effective")),
            "fault or JUnit did not complete")
    gzip_bytes = (trial_dir / "events.jsonl.gz").read_bytes()
    raw = gzip.decompress(gzip_bytes)
    require(sha(gzip_bytes) == trial["events_evidence"]["gzip_sha256"] and
            sha(raw) == trial["events_sha256"], "raw trace hash mismatch")
    events = [json.loads(line) for line in raw.splitlines() if line]
    applied = unique(events, lambda e: e["type"] == "FAULT_APPLIED", "applied fault")
    require(applied["site"] == DOOR and applied["node"] == "rs0" and
            applied["epoch"] == 0 and isinstance(applied.get("thread_id"), int) and
            applied["fault_id"] == plan["faults"][0]["fault_id"],
            "applied fault identity changed")
    token = applied["context"]
    require(token.startswith("HBASE-02-r0001:task:"), "invalid request token")
    request = unique(events, lambda e: e["type"] == "SEND" and
                     e.get("correlation") == token and e.get("port") == PORT and
                     e.get("transport") == "hbase-rpc", "faulted Get request")
    server_recv = unique(events, lambda e: e["type"] == "RECV" and
                         e.get("correlation") == token and e.get("port") == PORT and
                         e.get("node") == "rs0" and e.get("transport") == "hbase-rpc",
                         "faulted Get server receive")
    response = unique(events, lambda e: e["type"] == "SEND" and
                      e.get("correlation") == token and e.get("port") == PORT and
                      e.get("transport") == "hbase-rpc-response" and
                      e.get("node") == "rs0", "faulted Get response")
    client_recv = unique(events, lambda e: e["type"] == "RECV" and
                         e.get("correlation") == token and e.get("port") == PORT and
                         e.get("transport") == "hbase-rpc-response" and
                         e.get("node") == "client", "faulted Get client receive")
    submit = unique(events, lambda e: e["type"] == "TASK_SUBMIT" and
                    e.get("parent_id") == token and e.get("node") == "client" and
                    e["seq"] > client_recv["seq"], "faulted response handoff")
    claim = unique(events, lambda e: e["type"] == "TASK_CLAIM" and
                   e.get("correlation") == submit["correlation"] and
                   e.get("node") == "client", "response claim")
    check = unique(events, lambda e: e["type"] == "TARGET_CHECK" and
                   e.get("site") == TARGET and e.get("node") == "client" and
                   e["seq"] > applied["seq"], "later exact target check")
    enter = unique(events, lambda e: e["type"] == "REGION_ENTER" and
                   e.get("occurrence") == check["occurrence"], "target invocation enter")
    precheck = unique(events, lambda e: e["type"] == "TARGET_CHECK" and
                      e.get("occurrence") == check["occurrence"] and
                      e.get("site", "").endswith("@910:branch:1"),
                      "same-invocation first condition")
    retry = [e for e in events if e["type"] == "SEND" and e.get("port") == PORT and
             e.get("transport") == "hbase-rpc" and
             e.get("occurrence") == check["occurrence"] and
             client_recv["seq"] < e["seq"] < check["seq"]]
    require(len(retry) == 1 and retry[0]["correlation"] != token,
            "same-invocation Get retry missing or ambiguous")
    require(request["node"] == "client" and
            request["occurrence"] == check["occurrence"] == claim["occurrence"] and
            enter["seq"] < precheck["seq"] < request["seq"] < server_recv["seq"] <
            applied["seq"] < response["seq"] < client_recv["seq"] < submit["seq"] <
            claim["seq"] < retry[0]["seq"] < check["seq"] and
            check["thread_id"] == request["thread_id"] == claim["thread_id"],
            "same-invocation temporal witness invalid")
    path = OccurrenceGraph(events, reject_coarse_roots=True).event_path(
        applied, check, require_edge=True)
    require(path is not None and len(path) >= 2 and
            all(edge.certainty == "observed" for edge in path),
            "no strict postfault event-time path")
    edge_records = [{"kind": edge.kind, "producer_event": edge.producer_event,
                     "consumer_event": edge.consumer_event} for edge in path]
    require(any(edge["kind"] == "rpc" and edge["producer_event"] == response["id"] and
                edge["consumer_event"] == client_recv["id"] for edge in edge_records) and
            any(edge["kind"] == "task" and edge["producer_event"] == submit["id"] and
                edge["consumer_event"] == claim["id"] for edge in edge_records),
            "exact response edges missing")
    review = {
        "schema_version": 1,
        "case_id": "HBASE-02",
        "status": "bounded_typed_get_pilot_strict_path_no_selected_exception",
        "campaign_result_sha256": sha(result_bytes),
        "campaign_audit_sha256": sha(audit_bytes),
        "trial_result_sha256": sha(trial_bytes),
        "trial_plan_sha256": sha(plan_bytes),
        "events_gzip_sha256": sha(gzip_bytes),
        "events_raw_sha256": sha(raw),
        "duration_seconds": result["duration_seconds"],
        "fault_trials_completed": 1,
        "exact_exception_trials": 0,
        "source_interpretation": "The selected TableNotEnabledException requires a non-meta table and isTableDisabled(tableName); reaching branch:2 alone is not an exception or bug.",
        "faulted_request_token": token,
        "retry_request_token": retry[0]["correlation"],
        "observed_path_edges": edge_records,
        "events": {name: event_record(event) for name, event in (
            ("region_enter", enter), ("first_target_check", precheck),
            ("faulted_request", request), ("server_receive", server_recv),
            ("fault_applied", applied), ("server_response", response),
            ("client_receive", client_recv), ("task_submit", submit),
            ("task_claim", claim), ("retry_request", retry[0]),
            ("later_target_check", check))},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        require(json.loads(args.out.read_text()) == review, "stored review changed")
    else:
        args.out.write_text(json.dumps(review, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"review_sha256": sha(args.out.read_bytes()),
                      "fault_trials": 1, "strict_path": True}, sort_keys=True))


if __name__ == "__main__":
    main()
