#!/usr/bin/env python3
"""Seal the HDFS-12 H1/H2 diagnostic without inferring a bug from target reach."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    args = parser.parse_args()
    root = args.archive.resolve()
    result = json.loads((root / "result.json").read_text())
    trial = json.loads((root / "trials/r0001/result.json").read_text())
    if (result["case_id"] != "HDFS-12" or
            result["status"] != "diagnostic_complete" or
            result["all_faults_effective"] is not True or
            result["fault_identity_valid"] is not True or
            result["target_exception_candidate"] is not False or
            (result["junit_tests"], result["junit_errors"], result["junit_failures"]) != (1, 0, 0)):
        raise RuntimeError("two-fault trial result is not the expected negative")
    with gzip.open(root / "trials/r0001/events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream]
    by_seq = {event["seq"]: event for event in events}
    if len(by_seq) != len(events):
        raise RuntimeError("duplicate event sequence")
    for seq, typ in ((265, "HDFS12_KEY"), (270, "FAULT_APPLIED"),
                     (275, "HDFS12_KEY"), (280, "FAULT_APPLIED"),
                     (325, "DOOR_OBSERVED"), (346, "HDFS12_KEY"),
                     (347, "HDFS12_KEY_STATE"), (385, "HDFS12_KEY"),
                     (401, "HDFS12_KEY"), (402, "HDFS12_KEY_STATE"),
                     (404, "TARGET_CHECK")):
        if by_seq[seq]["type"] != typ:
            raise RuntimeError(f"unexpected event at seq {seq}")
    faults = [by_seq[270], by_seq[280]]
    third_door = by_seq[325]
    key_write, key_mint, key_lookup, key_read, target = (
        by_seq[347], by_seq[385], by_seq[401], by_seq[402], by_seq[404])
    expected_node = "hdfs-cluster-2/dn0"
    if ([f["door_ordinal"] for f in faults] != [5, 6] or
            [f["fault_id"] for f in faults] !=
            ["hdfs12-h1-ordinal5", "hdfs12-h2-ordinal6"] or
            any(f["node"] != expected_node or f["epoch"] != 0 or
                f["exception_class"] != "java.io.IOException" for f in faults) or
            third_door["door_ordinal"] != 7 or
            third_door["node"] != expected_node or third_door["epoch"] != 0 or
            third_door["thread_id"] != faults[0]["thread_id"] or
            key_write["node"] != expected_node or
            key_lookup["node"] != expected_node or
            key_read["node"] != expected_node or
            target["node"] != expected_node or
            key_mint["key_id"] != key_lookup["key_id"] or
            key_write["key_id"] != key_lookup["key_id"] or
            key_read["key_id"] != key_lookup["key_id"] or
            key_read["manager_id"] != key_write["manager_id"] or
            key_read["state_token"] != "manager:1:key:741424758:version:2" or
            key_read["matched"] is not True or
            not (265 < 270 < 275 < 280 < 325 < 347 < 385 < 401 < 402 < 404) or
            any(e["type"] == "TARGET_THROW" for e in events)):
        raise RuntimeError("H1/H2 recovery and selected key-read chronology changed")
    # The first update at 347 is replaced by another successful heartbeat at 380.
    last_write = max((e for e in events if e["type"] == "HDFS12_KEY_STATE"
                      and e.get("phase") == "write"
                      and e.get("node") == expected_node
                      and e.get("manager_id") == key_read["manager_id"]
                      and e.get("key_id") == key_lookup["key_id"]
                      and e["seq"] < key_read["seq"]), key=lambda e: e["seq"])
    if (last_write["seq"] != 380 or
            (last_write["value_id"], last_write["version"]) !=
            (key_read["value_id"], key_read["version"])):
        raise RuntimeError("lookup did not read the last installed key")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and "hdfs-data" not in path.parts and path.name != ".diagnostic.lock":
            files[str(path.relative_to(root))] = sha(path)
    manifest = {"schema_version": 1, "root": str(root), "files": files}
    write_json(args.manifest_out, manifest)
    receipt = {
        "schema_version": 1, "case_id": "HDFS-12", "status": "two_fault_negative",
        "bug_claim": False, "full_campaign_admitted": False,
        "raw_archive_path": str(root), "raw_file_count": len(files),
        "raw_manifest_sha256": sha(args.manifest_out),
        "result_sha256": sha(root / "result.json"),
        "trial_result_sha256": sha(root / "trials/r0001/result.json"),
        "events_gzip_sha256": sha(root / "trials/r0001/events.jsonl.gz"),
        "config_sha256": result["config_sha256"],
        "duration_seconds": result["duration_seconds"],
        "effective_injections": len(faults),
        "junit_fault_trial": {"tests": 1, "errors": 0, "failures": 0},
        "selected_throw_trials": 0,
        "faults": [{"event_id": f["id"], "door_ordinal": f["door_ordinal"],
                    "node": f["node"], "epoch": f["epoch"],
                    "thread_id": f["thread_id"]} for f in faults],
        "source_backed_timeline": {
            "R1_next_key": by_seq[265]["id"],
            "H1_fault": faults[0]["id"],
            "R2_next_key": by_seq[275]["id"],
            "H2_fault": faults[1]["id"],
            "next_successful_heartbeat_door": third_door["id"],
            "DN_addKeys": by_seq[346]["id"],
            "DN_first_map_write": key_write["id"],
            "DN_last_map_write": last_write["id"],
            "NN_token_mint": key_mint["id"],
            "DN_lookup": key_lookup["id"],
            "DN_map_read": key_read["id"],
            "target_check": target["id"],
            "key_id": key_lookup["key_id"],
            "state_token": key_read["state_token"],
            "value_id": key_read["value_id"],
        },
        "causal_explanation": (
            "The exact fifth and sixth DN heartbeat IOException faults delayed key delivery. "
            "The seventh heartbeat then succeeded and delivered key IDs 741424757 and "
            "741424758. A later heartbeat rewrote 741424758 before the selected DN "
            "lookup. The lookup read that installed key on the same manager, value, "
            "and version; the selected missing-key guard did not throw. NN minted "
            "741424757 tokens between the faults and recovery, but this test did "
            "not execute the selected DN lookup for those tokens in that interval."
        ),
        "source_locations": [
            "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java:703",
            "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java:224",
            "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java:501",
        ],
    }
    write_json(args.receipt_out, receipt)
    print(json.dumps({"status": receipt["status"], "receipt_sha256": sha(args.receipt_out),
                      "raw_manifest_sha256": receipt["raw_manifest_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
