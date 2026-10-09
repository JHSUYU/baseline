#!/usr/bin/env python3
"""Attest exact ZK04 readBool IOException door before its named guard."""

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
    if (config["case_id"] != "ZOOKEEPER-04" or
            result["case_id"] != audit["case_id"] or
            result["status"] != "calibration_complete" or
            result["healthy_junit_validation"]["status"] != "passed" or
            not runtime.get("valid") or
            runtime.get("observed_target_class_sha256") !=
                config["expected_target_class_sha256"] or
            audit.get("report_gate_passed") is not True or
            audit.get("campaign_result_sha256") != sha(result_path) or
            audit.get("healthy_target_nonthrowing") is not True or
            audit.get("healthy_local_timeline_doors", 0) < 1 or
            "observed_local_timeline" not in
                audit.get("healthy_closure_evidence_types", []) or
            not config.get("allow_local_timeline_doors") or
            not config.get("reject_coarse_roots") or
            not config.get("require_event_time_paths") or
            sha(Path(config["source_overlay_receipt"])) !=
                config["source_overlay_receipt_sha256"]):
        raise ValueError("healthy JUnit, loaded class, source, or timeline is not attested")

    trial = campaign / "trials/r0000"
    trial_result = read(trial / "result.json")
    trace, catalog = trial / "events.jsonl.gz", trial / "sites.jsonl"
    evidence = trial_result["events_evidence"]
    if (sha(trace) != evidence["gzip_sha256"] or
            hashlib.sha256(gzip.decompress(trace.read_bytes())).hexdigest() !=
                evidence["raw_sha256"] or
            sha(catalog) != trial_result["site_catalog_sha256"]):
        raise ValueError("healthy trace or site catalog SHA mismatch")
    events = [json.loads(line) for line in gzip.open(trace, "rt", encoding="utf-8")]
    by_id = {row["id"]: row for row in events if row.get("id")}
    sites = [json.loads(line) for line in catalog.read_text(encoding="utf-8").splitlines()
             if line]
    door_site = ("org.apache.zookeeper.server.ZooKeeperServer#processConnectRequest"
                 "(Lorg/apache/zookeeper/server/ServerCnxn;Ljava/nio/ByteBuffer;)V@1420:door:1")
    matches = [row for row in sites if row.get("site") == door_site and
               row.get("exception_class") == "java.io.IOException"]
    if len(matches) != 1:
        raise ValueError("exact readBool callsite IOException metadata missing or ambiguous")
    witnesses = []
    for sample in audit["healthy_local_timeline_evidence_sample"]:
        door = by_id[sample["door_event_id"]]
        check = by_id[sample["target_check_event_id"]]
        if door.get("site") != door_site:
            continue
        if (door.get("type") != "DOOR_OBSERVED" or
                check.get("type") != "TARGET_CHECK" or
                check.get("site") not in config["target"]["check_sites"] or
                door.get("node") != "zk2" or
                any(door.get(key) != check.get(key) for key in
                    ("node", "epoch", "occurrence", "thread_id")) or
                door["seq"] >= check["seq"] or
                sample.get("kind") != "observed_local_timeline" or
                sample.get("node") != door["node"] or
                sample.get("epoch") != door["epoch"] or
                sample.get("occurrence") != door["occurrence"]):
            raise ValueError("readBool door and target are not one exact local occurrence")
        witnesses.append({
            "door_event_id": door["id"], "door_seq": door["seq"],
            "target_check_event_id": check["id"], "target_check_seq": check["seq"],
            "node": door["node"], "epoch": door["epoch"],
            "thread_id": door["thread_id"], "occurrence": door["occurrence"],
            "site": door_site, "exception_class": "java.io.IOException",
        })
    if len(witnesses) != 1:
        raise ValueError("expected one exact zk2 reconnect readBool witness")
    record = {
        "schema_version": 1, "case_id": "ZOOKEEPER-04",
        "status": "observed_same_occurrence_readbool_healthy",
        "campaign_result_sha256": sha(result_path),
        "offline_audit_sha256": sha(audit_path),
        "config_sha256": sha(config_path),
        "trace_raw_sha256": evidence["raw_sha256"],
        "site_catalog_sha256": sha(catalog),
        "source_overlay_receipt_sha256": config["source_overlay_receipt_sha256"],
        "loaded_target_class_sha256": config["expected_target_class_sha256"],
        "target_source_sha256": config["mapping"]["target_source_sha256"],
        "test_source_sha256": config["mapping"]["test_source_sha256"],
        "witness": witnesses[0],
        "scope_limit": "Same-occurrence healthy order only; injected IOException and zxid behavior untested",
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
