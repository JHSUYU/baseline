#!/usr/bin/env python3
"""Recheck dynamic actor binding and exact fault-to-target RPC paths."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def trace(trial_dir: Path, trial: dict) -> tuple[dict, ...]:
    evidence = trial["events_evidence"]
    path = trial_dir / evidence["gzip_path"]
    packed = path.read_bytes()
    assert sha(packed) == evidence["gzip_sha256"]
    raw = gzip.decompress(packed)
    assert sha(raw) == evidence["raw_sha256"]
    assert len(raw) == evidence["raw_bytes"]
    return tuple(json.loads(line) for line in raw.splitlines() if line.strip())


def inspect(campaign: Path) -> dict:
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    config = read(campaign / "config.json")
    result, audit = read(result_path), read(audit_path)
    assert config["case_id"] == result["case_id"] == audit["case_id"] == "SOLR-22"
    assert config["reject_coarse_roots"] is True
    assert config["require_event_time_paths"] is True
    assert config["budget"]["max_faults_per_trial"] == 1
    assert "nodes" not in config["target"]
    assert config["target_actor_binding_policy"]["historical_actor_is_constraint"] is False
    assert audit["report_gate_passed"] is True
    assert result["healthy_seed_valid"] is True
    actor_nodes = result["target_binding"]["nodes"]
    assert len(actor_nodes) == 1 and actor_nodes[0] not in ("unknown", "client")
    actor = actor_nodes[0]
    targets = set(config["target"]["check_sites"])
    healthy_dir = campaign / "trials/r0000"
    healthy_result = read(healthy_dir / "result.json")
    healthy_events = trace(healthy_dir, healthy_result)
    healthy_checks = [event for event in healthy_events if event.get("type") == "TARGET_CHECK"
                      and event.get("site") in targets]
    assert healthy_checks and {event.get("node") for event in healthy_checks} == {actor}
    healthy_pilot = read(healthy_dir / "pilot-result.json")
    assert healthy_pilot["junit"] == {"run": 1, "failures": 0, "ignored": 0}
    assert healthy_pilot["target_throw_count"] == 0
    healthy_graph = OccurrenceGraph(healthy_events, reject_coarse_roots=True)
    healthy_ids = {event["id"]: event for event in healthy_events
                   if isinstance(event.get("id"), str)}
    healthy_doors = [event for event in healthy_events if event.get("type") == "DOOR_OBSERVED"
                     and event.get("node") == "client"
                     and isinstance(event.get("thread_id"), int)
                     and event.get("occurrence", "").startswith("unscoped:client:0:root:thread:")]
    healthy_request_witness = None
    for check in healthy_checks:
        if not isinstance(check.get("thread_id"), int):
            continue
        for door in healthy_doors:
            if door["seq"] >= check["seq"]:
                continue
            path = healthy_graph.event_path(door, check, require_edge=True)
            if not path:
                continue
            for edge in path:
                if edge.kind != "rpc":
                    continue
                sent, received = healthy_ids[edge.producer_event], healthy_ids[edge.consumer_event]
                if (sent.get("type") == "SEND" and received.get("type") == "RECV"
                        and sent.get("node") == "client" and received.get("node") == actor
                        and sent.get("thread_id") == door.get("thread_id")
                        and sent.get("occurrence") == door.get("occurrence")
                        and door["seq"] < sent["seq"] < received["seq"] < check["seq"]):
                    healthy_request_witness = [door["id"], sent["id"],
                                               received["id"], check["id"]]
                    break
            if healthy_request_witness:
                break
        if healthy_request_witness:
            break
    assert healthy_request_witness, "pilot healthy has no numeric root-free request path"
    rows = []
    for trial_dir in sorted((campaign / "trials").glob("r[0-9][0-9][0-9][0-9]")):
        trial_path = trial_dir / "result.json"
        if not trial_path.is_file():
            continue
        trial = read(trial_path)
        if trial["trial_id"] == 0:
            continue
        plan = trial.get("plan") or []
        assert len(plan) == 1
        point = plan[0]["point"]
        feedback = trial.get("feedback") or {}
        events = trace(trial_dir, trial)
        graph = OccurrenceGraph(events, reject_coarse_roots=True)
        ids = {event["id"]: event for event in events if isinstance(event.get("id"), str)}
        faults = [event for event in events if event.get("type") == "FAULT_APPLIED"
                  and event.get("fault_id") == plan[0]["fault_id"]
                  and event.get("node") == point["node"]
                  and event.get("epoch") == point["epoch"]
                  and event.get("site") == point["site"]]
        checks = [event for event in events if event.get("type") == "TARGET_CHECK"
                  and event.get("site") in targets and event.get("node") == actor
                  and isinstance(event.get("thread_id"), int)]
        actual_target_nodes = sorted({event.get("node") for event in events
                                      if event.get("type") == "TARGET_CHECK"
                                      and event.get("site") in targets})
        witnesses = []
        for fault in faults:
            if not isinstance(fault.get("thread_id"), int):
                continue
            for target in checks:
                if target["seq"] <= fault["seq"]:
                    continue
                path = graph.event_path(fault, target, require_edge=True)
                if not path:
                    continue
                rpc = next((edge for edge in path if edge.kind == "rpc"
                            and ids[edge.producer_event].get("type") == "SEND"
                            and ids[edge.consumer_event].get("type") == "RECV"
                            and ids[edge.consumer_event].get("node") == actor
                            and ids[edge.producer_event].get("node") == fault.get("node")
                            and ids[edge.producer_event].get("epoch") == fault.get("epoch")
                            and ids[edge.producer_event].get("thread_id") == fault.get("thread_id")
                            and ids[edge.producer_event].get("occurrence") == fault.get("occurrence")
                            and ids[edge.producer_event].get("seq", -1) > fault.get("seq", -1)
                            and ids[edge.consumer_event].get("seq", -1) < target.get("seq", -1)), None)
                if rpc is None:
                    continue
                witnesses.append({
                    "fault_id": fault["id"], "fault_seq": fault["seq"],
                    "fault_site": fault["site"], "fault_node": fault["node"],
                    "fault_epoch": fault["epoch"], "fault_thread_id": fault["thread_id"],
                    "fault_occurrence": fault["occurrence"],
                    "rpc_send_id": rpc.producer_event, "rpc_recv_id": rpc.consumer_event,
                    "rpc_send_seq": ids[rpc.producer_event]["seq"],
                    "rpc_recv_seq": ids[rpc.consumer_event]["seq"],
                    "target_check_id": target["id"], "target_check_seq": target["seq"],
                    "target_node": target["node"], "target_epoch": target["epoch"],
                    "target_occurrence": target["occurrence"],
                    "path": [{"kind": edge.kind, "producer_event": edge.producer_event,
                              "consumer_event": edge.consumer_event,
                              "certainty": edge.certainty} for edge in path],
                })
                break
            if witnesses:
                break
        rows.append({
            "trial_id": trial["trial_id"], "trial_result_sha256": sha(trial_path.read_bytes()),
            "events_gzip_sha256": trial["events_evidence"]["gzip_sha256"],
            "events_raw_sha256": trial["events_evidence"]["raw_sha256"],
            "events_raw_bytes": trial["events_evidence"]["raw_bytes"],
            "fault_effective": feedback.get("all_faults_effective") is True,
            "fault_identity_valid": feedback.get("fault_identity_valid") is True,
            "target_reached": feedback.get("target_reached") is True,
            "actual_target_nodes": actual_target_nodes,
            "target_actor_unique_and_bound": actual_target_nodes == [actor],
            "exact_fault_event_count": len(faults),
            "numeric_thread_root_free_rpc_target_witness": witnesses[0] if witnesses else None,
        })
    qualified = [row for row in rows if row["fault_effective"]
                 and row["fault_identity_valid"] and row["target_reached"]
                 and row["target_actor_unique_and_bound"]
                 and row["numeric_thread_root_free_rpc_target_witness"]]
    return {
        "schema_version": 1,
        "case_id": "SOLR-22",
        "classification": ("observed_fault_to_rpc_to_target" if qualified
                           else "postfault_causal_path_unverified"),
        "campaign_status": result["status"],
        "campaign_result_sha256": sha(result_path.read_bytes()),
        "offline_audit_sha256": sha(audit_path.read_bytes()),
        "config_sha256": sha((campaign / "config.json").read_bytes()),
        "resolved_physical_target_node": actor,
        "healthy_trial_result_sha256": sha((healthy_dir / "result.json").read_bytes()),
        "healthy_trace_gzip_sha256": healthy_result["events_evidence"]["gzip_sha256"],
        "healthy_numeric_root_free_request_witness_ids": healthy_request_witness,
        "fault_trials_completed": result["fault_trials_completed"],
        "strict_injected_trials": result["strict_injected_trials"],
        "strict_target_trials": result["strict_target_trials"],
        "qualified_root_free_rpc_trial_ids": [row["trial_id"] for row in qualified],
        "trials": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.campaign)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": report["classification"],
                      "qualified_root_free_rpc_trial_ids": report["qualified_root_free_rpc_trial_ids"],
                      "fault_trials_completed": report["fault_trials_completed"]}, sort_keys=True))


if __name__ == "__main__":
    main()
