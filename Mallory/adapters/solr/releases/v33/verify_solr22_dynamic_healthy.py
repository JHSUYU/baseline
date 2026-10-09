#!/usr/bin/env python3
"""Attest one runtime-bound physical target actor and an observed HTTP request path."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph


AGENT_SHA256 = "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"
ADAPTER_SHA256 = "08ae3c1a584ae713581f1de5a30eb7df8b0cccd67e2f1147d231aa91a63e9285"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attest(campaign: Path) -> dict:
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    pilot_path = campaign / "trials/r0000/pilot-result.json"
    trace_path = campaign / "trials/r0000/events.jsonl.gz"
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    pilot = json.loads(pilot_path.read_text())
    assert result["case_id"] == "SOLR-22" and result["status"] == "calibration_complete"
    assert result["healthy_seed_valid"] is True and audit["report_gate_passed"] is True
    assert pilot["junit"] == {"run": 1, "failures": 0, "ignored": 0}
    assert pilot["agent_sha256"] == AGENT_SHA256
    assert pilot["adapter_sha256"] == ADAPTER_SHA256
    assert pilot["target_check_count"] > 0 and pilot["target_throw_count"] == 0
    actor_nodes = result["target_binding"]["nodes"]
    assert len(actor_nodes) == 1 and actor_nodes[0] not in ("unknown", "client")
    actor = actor_nodes[0]
    assert pilot["target_nodes"] == [actor]
    raw = gzip.decompress(trace_path.read_bytes())
    events = tuple(json.loads(line) for line in raw.splitlines() if line.strip())
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    by_id = {event["id"]: event for event in events if isinstance(event.get("id"), str)}
    exact = set(json.loads((campaign / "config.json").read_text())["target"]["check_sites"])
    all_checks = [event for event in events if event.get("type") == "TARGET_CHECK"
                  and event.get("site") in exact]
    assert {event.get("node") for event in all_checks} == {actor}
    checks = [event for event in all_checks if isinstance(event.get("thread_id"), int)]
    client_doors = [event for event in events if event.get("type") == "DOOR_OBSERVED"
                    and event.get("node") == "client"
                    and isinstance(event.get("thread_id"), int)
                    and event.get("occurrence", "").startswith(
                        "unscoped:client:0:root:thread:")]
    assert checks and client_doors
    proof = None
    for target in checks:
        for door in client_doors:
            if door["seq"] >= target["seq"]:
                break
            path = graph.event_path(door, target, require_edge=True)
            if not path:
                continue
            rpc = next((edge for edge in path if edge.kind == "rpc"
                        and by_id[edge.producer_event].get("node") == "client"
                        and by_id[edge.consumer_event].get("node") == actor), None)
            if rpc is None:
                continue
            producer, consumer = by_id[rpc.producer_event], by_id[rpc.consumer_event]
            if producer.get("type") != "SEND" or consumer.get("type") != "RECV":
                continue
            if producer.get("thread_id") != door.get("thread_id"):
                continue
            if producer.get("occurrence") != door.get("occurrence"):
                continue
            proof = {
                "client_door": {key: door[key] for key in
                                ("id", "seq", "site", "node", "epoch", "thread_id", "occurrence")},
                "client_send": {key: producer[key] for key in
                                ("id", "seq", "site", "node", "epoch", "thread_id", "occurrence",
                                 "correlation", "transport", "port")},
                "server_recv": {key: consumer[key] for key in
                                ("id", "seq", "site", "node", "epoch", "thread_id", "occurrence",
                                 "correlation", "transport", "port")},
                "target_check": {key: target[key] for key in
                                 ("id", "seq", "site", "node", "epoch", "thread_id", "occurrence")},
                "edges": [{"kind": edge.kind, "producer_event": edge.producer_event,
                           "consumer_event": edge.consumer_event, "certainty": edge.certainty}
                          for edge in path],
            }
            break
        if proof is not None:
            break
    assert proof is not None, "no root-free client door -> observed RPC -> exact target path"
    return {
        "schema_version": 1,
        "case_id": "SOLR-22",
        "classification": "healthy_dynamic_single_actor_request_path_proven",
        "resolved_physical_target_node": actor,
        "result_sha256": digest(result_path),
        "offline_audit_sha256": digest(audit_path),
        "pilot_result_sha256": digest(pilot_path),
        "compressed_trace_sha256": digest(trace_path),
        "raw_trace_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_trace_bytes": len(raw),
        "numeric_client_doors": len(client_doors),
        "numeric_named_target_checks": len(checks),
        "healthy_observed_path_doors": audit["healthy_observed_path_doors"],
        "witness": proof,
        "fault_trials_authorized_by_this_receipt": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = attest(args.campaign)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": report["classification"],
                      "healthy_observed_path_doors": report["healthy_observed_path_doors"],
                      "witness": [report["witness"][key]["id"] for key in
                                  ("client_door", "client_send", "server_recv", "target_check")]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
