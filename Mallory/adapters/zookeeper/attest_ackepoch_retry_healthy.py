#!/usr/bin/env python3
"""Attest an exact follower ACKEPOCH write door and physical packet path."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


DOOR = "zookeeper.quorum.ackepoch.write"
PACKET_DOOR = "zookeeper.quorum.archive.writeRecord"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def attest(campaign: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    config_path = campaign / "config.json"
    result, audit, config = map(load, (result_path, audit_path, config_path))
    runtime = result.get("runtime_attestation") or {}
    junit = result.get("healthy_junit_validation") or {}
    if (config.get("case_id") != "ZOOKEEPER-06" or
            result.get("status") != "calibration_complete" or
            junit.get("status") != "passed" or junit.get("tests") != 1 or
            junit.get("failures") != 0 or junit.get("errors") != 0 or
            runtime.get("valid") is not True or
            runtime.get("observed_target_class_sha256") != config.get("expected_target_class_sha256") or
            audit.get("report_gate_passed") is not True or
            audit.get("campaign_result_sha256") != sha(result_path) or
            audit.get("healthy_observed_path_doors", 0) < 1 or
            "observed_graph_path" not in audit.get("healthy_closure_evidence_types", []) or
            not config.get("reject_coarse_roots") or
            not config.get("require_event_time_paths")):
        raise ValueError("healthy JUnit, exact target, or observed path is unproven")
    receipt_path = Path(config["source_overlay_receipt"])
    receipt = load(receipt_path)
    if (sha(receipt_path) != config["source_overlay_receipt_sha256"] or
            receipt["patched_root"] != config["cwd"]):
        raise ValueError("source overlay receipt differs from healthy config")
    for rel, expected in receipt["modified_files"].items():
        if sha(Path(receipt["patched_root"]) / rel) != expected:
            raise ValueError(f"source changed: {rel}")
    for artifact in receipt["compiled_artifacts"]:
        if sha(Path(artifact["path"])) != artifact["sha256"]:
            raise ValueError(f"compiled artifact changed: {artifact['path']}")

    trial = campaign / "trials/r0000"
    trial_result = load(trial / "result.json")
    evidence = trial_result["events_evidence"]
    trace = trial / "events.jsonl.gz"
    if (sha(trace) != evidence["gzip_sha256"] or
            hashlib.sha256(gzip.decompress(trace.read_bytes())).hexdigest() != evidence["raw_sha256"]):
        raise ValueError("raw healthy trace SHA mismatch")
    events = [json.loads(line) for line in gzip.open(trace, "rt", encoding="utf-8")]
    by_id = {event["id"]: event for event in events if event.get("id")}
    witnesses = []
    for path in audit.get("healthy_event_time_path_sample", []):
        door = by_id[path["door_event_id"]]
        check = by_id[path["target_check_event_id"]]
        if (door.get("type") != "DOOR_OBSERVED" or door.get("site") != DOOR or
                check.get("type") != "TARGET_CHECK" or
                check.get("site") not in config["target"]["check_sites"] or
                not str(door.get("node", "")).startswith("zk") or
                not str(check.get("node", "")).startswith("zk") or
                not isinstance(door.get("thread_id"), int) or
                not isinstance(check.get("thread_id"), int)):
            continue
        edges = path["edges"]
        rpc = [edge for edge in edges if edge["kind"] == "rpc"]
        if len(rpc) != 1:
            continue
        send, recv = (by_id[rpc[0][key]] for key in ("producer_event", "consumer_event"))
        if (send.get("type") != "SEND" or recv.get("type") != "RECV" or
                send.get("site") != PACKET_DOOR or
                not str(send.get("port", "")).startswith("18:") or
                (send.get("transport"), send.get("correlation"), send.get("port")) !=
                (recv.get("transport"), recv.get("correlation"), recv.get("port")) or
                (send.get("node"), send.get("epoch"), send.get("thread_id"), send.get("occurrence")) !=
                (door.get("node"), door.get("epoch"), door.get("thread_id"), door.get("occurrence")) or
                send.get("node") == recv.get("node") or
                not (door["seq"] < send["seq"] < recv["seq"] < check["seq"])):
            continue
        # The source hook precedes the ordinary packet write; ensure that the
        # send is the next physical packet send by the exact peer occurrence.
        intermediate = [event for event in events if
                        door["seq"] < event["seq"] < send["seq"] and
                        (event.get("node"), event.get("epoch"), event.get("thread_id"), event.get("occurrence")) ==
                        (door.get("node"), door.get("epoch"), door.get("thread_id"), door.get("occurrence"))]
        if ([event.get("type") for event in intermediate] != ["DOOR_OBSERVED"] or
                intermediate[0].get("site") != PACKET_DOOR):
            continue
        parents = [edge for edge in edges if edge["kind"] == "region_parent" and
                   edge["producer_event"] == recv["id"]]
        if len(parents) != 1:
            continue
        ack = by_id[parents[0]["consumer_event"]]
        if (ack.get("type") != "REGION_ENTER" or
                ack.get("site") != "zookeeper.leader.ackepoch" or
                ack.get("parent_id") != recv.get("correlation") or
                (ack.get("node"), ack.get("epoch"), ack.get("thread_id")) !=
                (recv.get("node"), recv.get("epoch"), recv.get("thread_id"))):
            continue
        parent_target = [edge for edge in edges if edge["kind"] == "region_parent" and
                         edge["producer_event"] == ack["id"]]
        if len(parent_target) != 1:
            continue
        region = by_id[parent_target[0]["consumer_event"]]
        if (region.get("type") != "REGION_ENTER" or
                region.get("parent_id") != ack.get("occurrence") or
                region.get("occurrence") != check.get("occurrence") or
                (region.get("node"), region.get("epoch"), region.get("thread_id")) !=
                (check.get("node"), check.get("epoch"), check.get("thread_id")) or
                not (recv["seq"] < ack["seq"] < region["seq"] < check["seq"])):
            continue
        witnesses.append({
            "door_event_id": door["id"], "door_seq": door["seq"],
            "door_node": door["node"], "door_epoch": door["epoch"],
            "door_thread_id": door["thread_id"], "door_occurrence": door["occurrence"],
            "packet_send_event_id": send["id"], "packet_receive_event_id": recv["id"],
            "packet_correlation": send["correlation"], "packet_port": send["port"],
            "target_node": check["node"], "target_epoch": check["epoch"],
            "target_occurrence": check["occurrence"],
            "target_region_event_id": region["id"], "target_check_event_id": check["id"],
            "event_time_path": path,
        })
    if not witnesses:
        raise ValueError("no exact ACKEPOCH write door to target packet path")
    record = {
        "schema_version": 1, "case_id": "ZOOKEEPER-06",
        "status": "healthy_exact_ackepoch_write_to_target_path",
        "campaign_result_sha256": sha(result_path), "offline_audit_sha256": sha(audit_path),
        "config_sha256": sha(config_path), "trial_result_sha256": sha(trial / "result.json"),
        "trace_gzip_sha256": evidence["gzip_sha256"],
        "trace_raw_sha256": evidence["raw_sha256"],
        "source_overlay_receipt_sha256": sha(receipt_path),
        "loaded_target_class_sha256": runtime["observed_target_class_sha256"],
        "target_source_sha256": config["mapping"]["target_source_sha256"],
        "test_source_sha256": config["mapping"]["test_source_sha256"],
        "junit_tests": junit["tests"], "witnesses": witnesses,
        "scope_limit": "Healthy packet path only; fault retry and postfault target retention remain unproven.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(attest(args.campaign.resolve(), args.output.resolve())["status"])
