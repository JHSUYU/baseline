#!/usr/bin/env python3
"""Verify one real rename request and a strict event-time path to HDFS-48."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
CORE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
DOOR = "hdfs:client-send-rpc-request:rename"
SEND_SITE = "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest"
TARGET_NODE = "hdfs-cluster-1/nn0"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(campaign: Path, output: Path) -> dict:
    sys.path[:0] = [str(CORE), str(BASE)]
    from Mallory.core.audit import _load_archived_trace, audit_campaign
    from Mallory.core.events import event_seq
    from Mallory.core.graph import OccurrenceGraph

    cfg = json.loads((HERE / "HDFS-48-node2-healthy-v3.json").read_text())
    receipt = json.loads((HERE / "build-receipt.json").read_text())
    summary = json.loads((campaign / "result.json").read_text())
    result = json.loads((campaign / "trials/r0000/result.json").read_text())
    junit = result.get("junit_validation", {})
    feedback = result.get("feedback", {})
    catalog = result.get("site_catalog_validation", {})
    errors = []
    if summary.get("status") != "calibration_complete":
        errors.append("campaign_not_terminal_healthy")
    if (junit.get("status"), junit.get("tests"), junit.get("failures"), junit.get("errors")) != ("passed", 1, 0, 0):
        errors.append("junit_not_1_0_0")
    if feedback.get("status") != "observed" or feedback.get("target_reached") is not True or feedback.get("target_threw") is not False:
        errors.append("selected_target_not_healthy_nonthrowing")
    if catalog.get("valid") is not True or catalog.get("observed_target_class_sha256") != receipt["target_class_sha256"]:
        errors.append("loaded_target_class_not_pinned")
    if cfg.get("agent_properties", {}).get("adapter.jar") != str(HERE / "release/mallory-hdfs-adapter.jar") or sha(HERE / "release/mallory-hdfs-adapter.jar") != receipt["adapter_jar_sha256"]:
        errors.append("method_filter_adapter_not_pinned")
    trace, trace_receipt = _load_archived_trace(campaign / "trials/r0000", result)
    events = trace.events
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    target_sites = set(cfg["target"]["check_sites"])
    targets = [e for e in events if e.get("type") == "TARGET_CHECK" and
               e.get("site") in target_sites and e.get("node") == TARGET_NODE]
    direct_setup = [e for e in events if e.get("type") == "TARGET_CHECK" and
                    e.get("site") in target_sites and e.get("node") == "hdfs-client"]
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
             e.get("site") == DOOR and e.get("node") == "hdfs-client" and
             e.get("exception_class") == "java.io.IOException"]
    if not targets:
        errors.append("named_nn0_target_check_absent")
    if not direct_setup:
        errors.append("direct_setup_check_absent")
    if not doors:
        errors.append("exact_named_rename_presend_door_absent")
    witnesses = []
    for door in doors:
        later_doors = [event_seq(other) for other in doors if
                       other.get("thread_id") == door.get("thread_id") and
                       event_seq(other) > event_seq(door)]
        next_door = min(later_doors, default=float("inf"))
        sends = [e for e in events if e.get("type") == "SEND" and
                 e.get("site") == SEND_SITE and e.get("transport") == "hadoop-ipc" and
                 e.get("port") == "request" and e.get("node") == door.get("node") and
                 e.get("epoch") == door.get("epoch") and
                 e.get("occurrence") == door.get("occurrence") and
                 e.get("thread_id") == door.get("thread_id") and
                 event_seq(door) < event_seq(e) < next_door]
        if not sends:
            continue
        send = min(sends, key=event_seq)
        token = send.get("correlation")
        if not isinstance(token, str) or not token or token == "unknown":
            continue
        receives = [e for e in events if e.get("type") == "RECV" and
                    e.get("node") == TARGET_NODE and
                    e.get("transport") == "hadoop-ipc" and
                    e.get("port") == "request" and e.get("correlation") == token and
                    event_seq(e) > event_seq(send)]
        if len(receives) != 1:
            continue
        recv = receives[0]
        for target in targets:
            if event_seq(target) <= event_seq(recv):
                continue
            path = graph.event_path(door, target, require_edge=True)
            if path is None or not any(edge.kind == "rpc" and
                                       edge.producer_event == send.get("id") and
                                       edge.consumer_event == recv.get("id") for edge in path):
                continue
            witnesses.append({"door_event_id": door["id"], "door_seq": event_seq(door),
                              "send_event_id": send["id"], "request_correlation": token,
                              "nn0_recv_event_id": recv["id"],
                              "target_event_id": target["id"], "target_seq": event_seq(target),
                              "edges": [{"kind": edge.kind,
                                         "producer_event": edge.producer_event,
                                         "consumer_event": edge.consumer_event} for edge in path]})
            break
    if not witnesses:
        errors.append("no_exact_correlation_strict_door_to_nn0_target_path")
    offline = audit_campaign(campaign, output)
    if offline.get("report_gate_passed") is not True:
        errors.append("offline_causal_gate_failed")
    return {"case_id": "HDFS-48", "healthy_gate_passed": not errors,
            "errors": errors, "junit": junit,
            "named_nn0_target_checks": len(targets),
            "direct_client_setup_checks": len(direct_setup),
            "exact_named_rename_doors": len(doors),
            "strict_method_correlation_path_witnesses": witnesses,
            "offline_causal_gate_passed": offline.get("report_gate_passed"),
            "trace_receipt": trace_receipt,
            "test_class_sha256": receipt["patched_test_class_sha256"],
            "adapter_jar_sha256": receipt["adapter_jar_sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, default=Path("/tmp/mallory-hdfs48-rename-presend-node2-healthy-v3"))
    parser.add_argument("--out", type=Path, default=Path("/tmp/mallory-hdfs48-rename-presend-node2-healthy-v3/offline-causal-audit.json"))
    args = parser.parse_args()
    report = check(args.campaign, args.out)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["healthy_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
