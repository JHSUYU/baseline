#!/usr/bin/env python3
"""Attest the observed client-to-leader REQUEST path for ZK02/03."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


DOORS = {"ZOOKEEPER-02": "zookeeper.client.request.read",
         "ZOOKEEPER-03": "zookeeper.client.connect.read"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attest(campaign: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    result_path, audit_path, config_path = (
        campaign / name for name in
        ("result.json", "offline-causal-audit.json", "config.json"))
    result, audit, config = map(read, (result_path, audit_path, config_path))
    case = config["case_id"]
    if (case not in DOORS or not (result["case_id"] == audit["case_id"] == case)
            or result["status"] != "calibration_complete"
            or result["healthy_junit_validation"]["status"] != "passed"
            or result["runtime_attestation"]["valid"] is not True
            or result["runtime_attestation"]["observed_target_class_sha256"] !=
                config["expected_target_class_sha256"]
            or audit["report_gate_passed"] is not True
            or audit["campaign_result_sha256"] != sha(result_path)
            or audit.get("healthy_observed_path_doors", 0) < 1
            or not config.get("reject_coarse_roots")
            or not config.get("require_event_time_paths")
            or sha(Path(config["source_overlay_receipt"])) !=
                config["source_overlay_receipt_sha256"]):
        raise ValueError("healthy JUnit, loaded class, source, or path is not attested")
    trial = campaign / "trials/r0000"
    trial_result = read(trial / "result.json")
    trace = trial / "events.jsonl.gz"
    if (sha(trace) != trial_result["events_evidence"]["gzip_sha256"] or
            hashlib.sha256(gzip.decompress(trace.read_bytes())).hexdigest() !=
            trial_result["events_evidence"]["raw_sha256"]):
        raise ValueError("healthy trace bytes differ from trial receipt")
    events = [json.loads(line) for line in gzip.open(trace, "rt", encoding="utf-8")]
    by_id = {event["id"]: event for event in events if event.get("id")}
    samples = [row for row in audit["healthy_event_time_path_sample"]
               if by_id[row["door_event_id"]]["site"] == DOORS[case]]
    if len(samples) != 1:
        raise ValueError("expected one exact client door path")
    sample = samples[0]
    door, check = by_id[sample["door_event_id"]], by_id[sample["target_check_event_id"]]
    edges = sample["edges"]
    rpc = [edge for edge in edges if edge["kind"] == "rpc"]
    if (len(rpc) != 1 or check["site"] not in config["target"]["check_sites"]
            or door["node"] == check["node"] or not door["node"].startswith("zk")
            or not check["node"].startswith("zk")
            or door["seq"] >= check["seq"]):
        raise ValueError("client door or target identity/path is ambiguous")
    send, recv = by_id[rpc[0]["producer_event"]], by_id[rpc[0]["consumer_event"]]
    if (send["type"] != "SEND" or recv["type"] != "RECV"
            or (send["transport"], send["correlation"], send["port"]) !=
               (recv["transport"], recv["correlation"], recv["port"])
            or recv["context"] != recv["correlation"]
            or recv["correlation"] not in recv["occurrence"]
            or not (door["seq"] < send["seq"] < recv["seq"] < check["seq"])):
        raise ValueError("physical packet pairing or RECEIVE context is not observed")
    parents = [edge for edge in edges if edge["kind"] == "region_parent"
               and edge["producer_event"] == recv["id"]]
    if len(parents) != 1:
        raise ValueError("leader request region has no unique RECV parent")
    region = by_id[parents[0]["consumer_event"]]
    if (region["type"] != "REGION_ENTER" or
            region["site"] != "zookeeper.leader.request" or
            region["parent_id"] != recv["correlation"] or
            (region["node"], region["epoch"], region["thread_id"]) !=
            (recv["node"], recv["epoch"], recv["thread_id"]) or
            not (recv["seq"] < region["seq"] < check["seq"])):
        raise ValueError("leader region is not a same-thread packet continuation")
    record = {
        "schema_version": 1, "case_id": case,
        "status": "observed_request_packet_path_healthy",
        "campaign_result_sha256": sha(result_path),
        "offline_audit_sha256": sha(audit_path),
        "config_sha256": sha(config_path),
        "trace_raw_sha256": trial_result["events_evidence"]["raw_sha256"],
        "source_overlay_receipt_sha256": config["source_overlay_receipt_sha256"],
        "loaded_target_class_sha256": config["expected_target_class_sha256"],
        "target_source_sha256": config["mapping"]["target_source_sha256"],
        "test_source_sha256": config["mapping"]["test_source_sha256"],
        "observed_graph_path_doors": audit["healthy_observed_path_doors"],
        "door_event_id": door["id"], "door_site": door["site"],
        "packet_send_event_id": send["id"],
        "packet_receive_event_id": recv["id"],
        "packet_correlation": recv["correlation"],
        "leader_request_region_event_id": region["id"],
        "target_check_event_id": check["id"],
        "target_check_site": check["site"],
        "event_time_path": sample,
        "scope_limit": "Healthy path only; postfault affected-actor target retention is unproven",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(attest(args.campaign.resolve(), args.output.resolve())["status"])
