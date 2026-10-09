#!/usr/bin/env python3
"""Attest the existing write/restart/reconnect ZooKeeper cluster test."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


SELECTOR = "org.apache.zookeeper.test.WatchEventWhenAutoResetTest#testNodeDataChanged"
DOOR = ("org.apache.zookeeper.server.ZooKeeperServer#processConnectRequest"
        "(Lorg/apache/zookeeper/server/ServerCnxn;Ljava/nio/ByteBuffer;)V@1420:door:1")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def attest(campaign: Path, source_review: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    config_path = campaign / "config.json"
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    config, result, audit, review = map(read, (config_path, result_path, audit_path, source_review))
    runtime = result.get("runtime_attestation") or {}
    if (config["case_id"] != "ZOOKEEPER-04" or
            config["cluster_test"] != SELECTOR or
            config["target"]["nodes"] != ["zk1"] or
            config["mapping"]["test_source_sha256"] != review["test_source_sha256"] or
            digest(config_path) != review["config_sha256"] or
            digest(Path(config["source_overlay_receipt"])) !=
                config["source_overlay_receipt_sha256"] or
            result["status"] != "calibration_complete" or
            result["healthy_junit_validation"]["status"] != "passed" or
            result["healthy_junit_validation"]["tests"] != 1 or
            result["exact_exception_trials"] != 0 or
            not runtime.get("valid") or
            runtime.get("bound_nodes") != ["zk1"] or
            runtime.get("observed_target_class_sha256") !=
                config["expected_target_class_sha256"] or
            audit.get("campaign_result_sha256") != digest(result_path) or
            audit.get("report_gate_passed") is not True or
            audit.get("healthy_target_nonthrowing") is not True or
            "observed_local_timeline" not in
                audit.get("healthy_closure_evidence_types", [])):
        raise ValueError("JUnit, target class, site, or source review is not attested")

    trial = campaign / "trials/r0000"
    trial_result = read(trial / "result.json")
    trace_path = trial / "events.jsonl.gz"
    site_path = trial / "sites.jsonl"
    trace_evidence = trial_result["events_evidence"]
    raw_trace = gzip.decompress(trace_path.read_bytes())
    if (digest(trace_path) != trace_evidence["gzip_sha256"] or
            hashlib.sha256(raw_trace).hexdigest() != trace_evidence["raw_sha256"] or
            digest(site_path) != trial_result["site_catalog_sha256"]):
        raise ValueError("raw trace or site catalog differs from trial receipt")
    events = [json.loads(line) for line in raw_trace.splitlines() if line]
    by_id = {event["id"]: event for event in events if event.get("id")}
    catalog = [json.loads(line) for line in site_path.read_text(encoding="utf-8").splitlines()
               if line]
    if len([row for row in catalog if row.get("site") == DOOR and
            row.get("exception_class") == "java.io.IOException"]) != 1:
        raise ValueError("the exact readBool IOException door is absent or ambiguous")

    witnesses = []
    for item in audit["healthy_local_timeline_evidence_sample"]:
        door = by_id[item["door_event_id"]]
        check = by_id[item["target_check_event_id"]]
        if door.get("site") != DOOR:
            continue
        if (door.get("type") != "DOOR_OBSERVED" or
                check.get("type") != "TARGET_CHECK" or
                check.get("site") not in config["target"]["check_sites"] or
                any(door.get(key) != check.get(key) for key in
                    ("node", "epoch", "occurrence", "thread_id")) or
                door.get("node") != "zk1" or
                door["seq"] >= check["seq"] or
                item.get("kind") != "observed_local_timeline"):
            raise ValueError("door and guard do not share one named occurrence")
        witnesses.append({
            "door_event_id": door["id"], "door_seq": door["seq"],
            "target_check_event_id": check["id"], "target_check_seq": check["seq"],
            "node": door["node"], "epoch": door["epoch"],
            "thread_id": door["thread_id"], "occurrence": door["occurrence"],
            "evidence_type": "observed_local_timeline",
        })
    if len(witnesses) != 2 or [w["epoch"] for w in witnesses] != [0, 1]:
        raise ValueError("expected exact peer1 guard before and after peer1 restart")
    record = {
        "schema_version": 1,
        "case_id": "ZOOKEEPER-04",
        "status": "healthy_write_reconnect_target_observed",
        "selected_junit": SELECTOR,
        "duration_seconds": result["duration_seconds"],
        "config_sha256": digest(config_path),
        "result_sha256": digest(result_path),
        "offline_audit_sha256": digest(audit_path),
        "trace_gzip_sha256": digest(trace_path),
        "trace_raw_sha256": trace_evidence["raw_sha256"],
        "site_catalog_sha256": digest(site_path),
        "source_review_sha256": digest(source_review),
        "target_source_sha256": config["mapping"]["target_source_sha256"],
        "test_source_sha256": config["mapping"]["test_source_sha256"],
        "loaded_target_class_sha256": runtime["observed_target_class_sha256"],
        "post_restart_witness": witnesses[1],
        "initial_connection_witness": witnesses[0],
        "scope_limit": ("Existing JUnit writes before reconnect and reaches the nonthrowing "
                        "zk1 guard after restart. This is local temporal evidence; no "
                        "fault outcome or zxid value-flow has been established."),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("source_review", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(attest(args.campaign.resolve(), args.source_review.resolve(),
                 args.output.resolve())["status"])
