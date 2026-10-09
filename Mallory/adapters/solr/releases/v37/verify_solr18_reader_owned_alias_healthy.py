#!/usr/bin/env python3
"""Attest named ZooKeeper reader-owned ZooKeeper client handoff and exact SOLR-18 target path."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(root: Path) -> dict:
    result_path = root / "result.json"
    audit_path = root / "offline-causal-audit.json"
    trial = root / "trials/r0000"
    config = json.loads((root / "config.json").read_text())
    result = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    pilot = json.loads((trial / "pilot-result.json").read_text())
    trial_result = json.loads((trial / "result.json").read_text())
    assert config["case_id"] == result["case_id"] == "SOLR-18"
    assert result["status"] == "calibration_complete"
    assert result["healthy_seed_valid"] is True
    assert audit["report_gate_passed"] is True
    assert pilot["junit"] == {"run": 1, "failures": 0, "ignored": 0}
    assert pilot["target_throw_count"] == 0
    assert pilot["adapter_sha256"] == "2fc81200cff69abc93b608484805fe4bdf88ff3074a46fe7142221dfd0b2ce50"
    assert pilot["agent_sha256"] == "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"
    packed_path = trial / trial_result["events_evidence"]["gzip_path"]
    packed = packed_path.read_bytes()
    assert hashlib.sha256(packed).hexdigest() == trial_result["events_evidence"]["gzip_sha256"]
    raw = gzip.decompress(packed)
    assert hashlib.sha256(raw).hexdigest() == trial_result["events_evidence"]["raw_sha256"]
    events = tuple(json.loads(line) for line in raw.splitlines() if line.strip())
    exact = set(config["target"]["check_sites"])
    checks = [event for event in events if event.get("type") == "TARGET_CHECK"
              and event.get("site") in exact]
    named = [event for event in checks if event.get("node") not in (None, "unknown")
             and isinstance(event.get("thread_id"), int)]
    clients = [event for event in named if event["node"] == "client"]
    servers = [event for event in named if event["node"].startswith("node")]
    assert checks and len(named) == len(checks) and clients and servers
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    by_id = {event["id"]: event for event in events if isinstance(event.get("id"), str)}
    doors = [event for event in events if event.get("type") == "DOOR_OBSERVED"
             and event.get("node") not in (None, "unknown")
             and isinstance(event.get("thread_id"), int)]
    path_witness = None
    for target in servers:
        for door in doors:
            if door["seq"] >= target["seq"]:
                continue
            path = graph.event_path(door, target, require_edge=True)
            if path:
                path_witness = {"door_id": door["id"], "target_id": target["id"],
                                "door_node": door["node"], "target_node": target["node"],
                                "edges": [{"kind": edge.kind, "producer_event": edge.producer_event,
                                           "consumer_event": edge.consumer_event,
                                           "certainty": edge.certainty} for edge in path]}
                break
        if path_witness:
            break
    assert path_witness, "no root-free numeric named door-to-server-target path"
    submits = [event for event in events if event.get("type") == "TASK_SUBMIT"
               and event.get("node") not in (None, "unknown")
               and isinstance(event.get("thread_id"), int)]
    claims = [event for event in events if event.get("type") == "TASK_CLAIM"
              and event.get("node") not in (None, "unknown")
              and isinstance(event.get("thread_id"), int)]
    by_correlation = {event.get("correlation"): event for event in claims}
    handoff = None
    for submit in submits:
        claim = by_correlation.get(submit.get("correlation"))
        if not claim or claim.get("node") != submit.get("node"):
            continue
        if claim.get("epoch") != submit.get("epoch") or claim["seq"] <= submit["seq"]:
            continue
        for target in named:
            if target["node"] != claim["node"] or target["seq"] <= claim["seq"]:
                continue
            path = graph.event_path(submit, target, require_edge=True)
            if not path or not any(edge.kind == "task" and
                                   edge.producer_event == submit["id"] and
                                   edge.consumer_event == claim["id"] for edge in path):
                continue
            handoff = {"submit_id": submit["id"], "claim_id": claim["id"],
                       "target_id": target["id"], "node": submit["node"],
                       "epoch": submit["epoch"], "correlation": submit["correlation"]}
            break
        if handoff:
            break
    assert handoff, "no named watcher submit/claim-to-target handoff"
    return {"schema_version": 1, "case_id": "SOLR-18",
            "classification": "healthy_reader_owned_alias_and_target_path_proven",
            "result_sha256": digest(result_path), "offline_audit_sha256": digest(audit_path),
            "trial_result_sha256": digest(trial / "result.json"),
            "events_gzip_sha256": digest(packed_path),
            "events_raw_sha256": hashlib.sha256(raw).hexdigest(),
            "events_raw_bytes": len(raw),
            "named_exact_check_count": len(named),
            "client_registered_manager_check_count": len(clients),
            "server_exact_check_count": len(servers),
            "root_free_door_target_witness": path_witness,
            "named_watcher_handoff_witness": handoff,
            "fault_trials_authorized_by_this_receipt": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = inspect(args.campaign)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": report["classification"],
                      "named_exact_check_count": report["named_exact_check_count"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
