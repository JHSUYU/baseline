#!/usr/bin/env python3
"""Attest one physical ACKEPOCH packet path into the exact ZK06 guard."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attest(campaign: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    def read(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    result_path, audit_path, config_path = (
        campaign / name for name in
        ("result.json", "offline-causal-audit.json", "config.json"))
    result, audit, config = map(read, (result_path, audit_path, config_path))
    runtime = result.get("runtime_attestation") or {}
    if (config["case_id"] != "ZOOKEEPER-06" or
            result["case_id"] != audit["case_id"] or
            result["status"] != "calibration_complete" or
            result["healthy_junit_validation"]["status"] != "passed" or
            not runtime.get("valid") or
            runtime.get("observed_target_class_sha256") !=
                config["expected_target_class_sha256"] or
            audit.get("report_gate_passed") is not True or
            audit.get("campaign_result_sha256") != sha(result_path) or
            audit.get("healthy_observed_path_doors", 0) < 1 or
            not config.get("reject_coarse_roots") or
            not config.get("require_event_time_paths") or
            sha(Path(config["source_overlay_receipt"])) !=
                config["source_overlay_receipt_sha256"]):
        raise ValueError("JUnit, loaded class, source, or event-time graph is not attested")

    trial = campaign / "trials/r0000"
    trial_result = read(trial / "result.json")
    trace = trial / "events.jsonl.gz"
    evidence = trial_result["events_evidence"]
    if (sha(trace) != evidence["gzip_sha256"] or
            hashlib.sha256(gzip.decompress(trace.read_bytes())).hexdigest() !=
                evidence["raw_sha256"]):
        raise ValueError("healthy trace SHA differs from trial receipt")
    events = [json.loads(line) for line in gzip.open(trace, "rt", encoding="utf-8")]
    by_id = {event["id"]: event for event in events if event.get("id")}
    candidates = []
    for sample in audit["healthy_event_time_path_sample"]:
        door = by_id[sample["door_event_id"]]
        check = by_id[sample["target_check_event_id"]]
        edges = sample["edges"]
        if (door.get("site") != "zookeeper.quorum.archive.writeRecord" or
                check.get("site") not in config["target"]["check_sites"]):
            continue
        rpc = [edge for edge in edges if edge["kind"] == "rpc"]
        if len(rpc) != 1:
            continue
        send = by_id[rpc[0]["producer_event"]]
        recv = by_id[rpc[0]["consumer_event"]]
        if (send.get("type") != "SEND" or recv.get("type") != "RECV" or
                not str(send.get("port", "")).startswith("18:") or
                (send.get("transport"), send.get("correlation"), send.get("port")) !=
                (recv.get("transport"), recv.get("correlation"), recv.get("port")) or
                door["seq"] + 1 != send["seq"] or
                any(door.get(key) != send.get(key) for key in
                    ("site", "node", "epoch", "occurrence", "thread_id")) or
                not (door["seq"] < send["seq"] < recv["seq"] < check["seq"]) or
                send.get("node") == recv.get("node") or
                not str(send.get("node", "")).startswith("zk") or
                not str(recv.get("node", "")).startswith("zk")):
            continue
        parents = [edge for edge in edges if edge["kind"] == "region_parent"
                   and edge["producer_event"] == recv["id"]]
        if len(parents) != 1:
            continue
        ack = by_id[parents[0]["consumer_event"]]
        if (ack.get("type") != "REGION_ENTER" or
                ack.get("site") != "zookeeper.leader.ackepoch" or
                ack.get("parent_id") != recv.get("correlation") or
                (ack.get("node"), ack.get("epoch"), ack.get("thread_id")) !=
                (recv.get("node"), recv.get("epoch"), recv.get("thread_id")) or
                not (recv["seq"] < ack["seq"] < check["seq"])):
            continue
        targets = [edge for edge in edges if edge["kind"] == "region_parent"
                   and edge["producer_event"] == ack["id"]]
        if len(targets) != 1:
            continue
        region = by_id[targets[0]["consumer_event"]]
        if (region.get("type") != "REGION_ENTER" or
                region.get("site") != config["target"]["check_sites"][0].split("@")[0] or
                region.get("parent_id") != ack.get("occurrence") or
                (region.get("node"), region.get("epoch"), region.get("thread_id")) !=
                (check.get("node"), check.get("epoch"), check.get("thread_id")) or
                not (ack["seq"] < region["seq"] < check["seq"])):
            continue
        candidates.append((sample, door, send, recv, ack, region, check))
    if not candidates:
        raise ValueError("no exact physical ACKEPOCH to target event-time path")
    # Different followers may each send an ACKEPOCH. Preserve each witness,
    # but require its individual packet identity and target chronology.
    record = {
        "schema_version": 1, "case_id": "ZOOKEEPER-06",
        "status": "observed_ackepoch_packet_path_healthy",
        "campaign_result_sha256": sha(result_path),
        "offline_audit_sha256": sha(audit_path),
        "config_sha256": sha(config_path),
        "trace_raw_sha256": evidence["raw_sha256"],
        "source_overlay_receipt_sha256": config["source_overlay_receipt_sha256"],
        "loaded_target_class_sha256": config["expected_target_class_sha256"],
        "target_source_sha256": config["mapping"]["target_source_sha256"],
        "test_source_sha256": config["mapping"]["test_source_sha256"],
        "observed_graph_path_doors": audit["healthy_observed_path_doors"],
        "witnesses": [{
            "door_event_id": door["id"], "packet_send_event_id": send["id"],
            "packet_receive_event_id": recv["id"],
            "packet_correlation": recv["correlation"],
            "ackepoch_region_event_id": ack["id"],
            "target_region_event_id": region["id"],
            "target_check_event_id": check["id"],
            "target_check_site": check["site"], "event_time_path": sample,
        } for sample, door, send, recv, ack, region, check in candidates],
        "scope_limit": "Healthy packet path only; affected-actor target retention after a fault is unproven",
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
