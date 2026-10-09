#!/usr/bin/env python3
"""Seal the exact HDFS-12 H1/H2/H3 key-read negative with raw SHA pins."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", type=Path, required=True)
    ap.add_argument("--manifest-out", type=Path, required=True)
    ap.add_argument("--receipt-out", type=Path, required=True)
    args = ap.parse_args()
    root = args.archive.resolve()
    result = json.loads((root / "result.json").read_text())
    if (result.get("case_id") != "HDFS-12" or
            result.get("status") != "diagnostic_complete" or
            result.get("all_faults_effective") is not True or
            result.get("fault_identity_valid") is not True or
            result.get("target_exception_candidate") is not False or
            (result.get("junit_tests"), result.get("junit_errors"),
             result.get("junit_failures")) != (1, 0, 0)):
        raise RuntimeError("result fails strict negative gate")
    with gzip.open(root / "trials/r0001/events.jsonl.gz", "rt") as stream:
        events = [json.loads(line) for line in stream]
    by_seq = {event["seq"]: event for event in events}
    if len(by_seq) != len(events):
        raise RuntimeError("duplicate event seq")
    node = "hdfs-cluster-2/dn0"
    faults = [e for e in events if e["type"] == "FAULT_APPLIED"]
    matched = [e for e in events if e["type"] == "FAULT_MATCHED"]
    if (len(faults) != 3 or len(matched) != 3 or
            [(e["seq"], e["door_ordinal"], e["fault_id"]) for e in faults] !=
            [(274, 5, "hdfs12-h1-ordinal5"),
             (284, 6, "hdfs12-h2-ordinal6"),
             (326, 7, "hdfs12-h3-ordinal7")] or
            any(e["node"] != node or e["epoch"] != 0 or
                e["exception_class"] != "java.io.IOException" for e in faults) or
            len({e["thread_id"] for e in faults}) != 1 or
            any(e["type"] == "TARGET_THROW" for e in events)):
        raise RuntimeError("three exact faults or selected throw differ")
    for seq, typ, phase in ((269, "HDFS12_KEY", "nn_rotation_next"),
                            (279, "HDFS12_KEY", "nn_rotation_next"),
                            (323, "HDFS12_KEY", "dn_heartbeat_attempt"),
                            (349, "HDFS12_KEY", "dn_heartbeat_attempt"),
                            (367, "HDFS12_KEY", "dn_add_keys"),
                            (393, "HDFS12_KEY", "nn_rotation_next"),
                            (413, "HDFS12_KEY", "dn_add_keys"),
                            (414, "HDFS12_KEY_STATE", "write"),
                            (429, "HDFS12_KEY", "nn_token_mint"),
                            (445, "HDFS12_KEY", "dn_lookup"),
                            (446, "HDFS12_KEY_STATE", "read"),
                            (448, "TARGET_CHECK", None),
                            (490, "HDFS12_KEY", "dn_lookup"),
                            (491, "HDFS12_KEY_STATE", "read"),
                            (493, "TARGET_CHECK", None)):
        e = by_seq[seq]
        if e["type"] != typ or (phase is not None and e.get("phase") != phase):
            raise RuntimeError(f"unexpected event seq {seq}")
    key_id = by_seq[445]["key_id"]
    if (key_id != by_seq[414]["key_id"] or
            key_id != by_seq[429]["key_id"] or
            by_seq[445].get("token_id") != by_seq[429].get("token_id") or
            by_seq[490]["key_id"] != key_id):
        raise RuntimeError("minted token and selected lookup key IDs differ")
    observations = []
    for lookup_seq, read_seq, target_seq in ((445, 446, 448), (490, 491, 493)):
        lookup, read, target = (by_seq[lookup_seq], by_seq[read_seq], by_seq[target_seq])
        prior = [e for e in events if e["type"] == "HDFS12_KEY_STATE"
                 and e.get("phase") in ("write", "remove") and e.get("node") == node
                 and e.get("manager_id") == read["manager_id"]
                 and e.get("key_id") == key_id and e["seq"] < read_seq]
        if not prior:
            raise RuntimeError("no preceding key state")
        last = max(prior, key=lambda e: e["seq"])
        if (last["phase"] != "write" or read["matched"] is not True or
                (read["value_id"], read["version"], read["state_token"]) !=
                (last["value_id"], last["version"], last["state_token"]) or
                lookup["node"] != node or read["node"] != node or
                target["node"] != node or
                target["occurrence"] != read["occurrence"] or
                not (last["seq"] < lookup_seq < read_seq < target_seq)):
            raise RuntimeError("selected target did not read last installed key")
        observations.append({"lookup_event_id": lookup["id"],
                             "map_read_event_id": read["id"],
                             "target_event_id": target["id"],
                             "last_map_write_event_id": last["id"],
                             "key_id": key_id,
                             "manager_id": read["manager_id"],
                             "state_token": read["state_token"],
                             "value_id": read["value_id"]})
    if observations[0]["last_map_write_event_id"] != by_seq[414]["id"] or \
            observations[1]["last_map_write_event_id"] != by_seq[480]["id"]:
        raise RuntimeError("unexpected postfault key delivery order")
    files = {str(path.relative_to(root)): sha(path)
             for path in sorted(root.rglob("*"))
             if path.is_file() and "hdfs-data" not in path.parts
             and path.name != ".diagnostic.lock"}
    save(args.manifest_out, {"schema_version": 1, "root": str(root), "files": files})
    receipt = {
        "schema_version": 1, "case_id": "HDFS-12", "status": "three_fault_negative",
        "bug_claim": False, "full_campaign_admitted": False,
        "raw_archive_path": str(root), "raw_file_count": len(files),
        "raw_manifest_sha256": sha(args.manifest_out),
        "result_sha256": sha(root / "result.json"),
        "trial_result_sha256": sha(root / "trials/r0001/result.json"),
        "events_gzip_sha256": sha(root / "trials/r0001/events.jsonl.gz"),
        "config_sha256": result["config_sha256"],
        "duration_seconds": result["duration_seconds"],
        "effective_injections": 3,
        "junit_fault_trial": {"tests": 1, "errors": 0, "failures": 0},
        "selected_throw_trials": 0,
        "faults": [{"event_id": e["id"], "door_ordinal": e["door_ordinal"],
                    "node": e["node"], "epoch": e["epoch"],
                    "thread_id": e["thread_id"]} for e in faults],
        "source_backed_timeline": {
            "R1_next_key": by_seq[269]["id"],
            "R2_next_key": by_seq[279]["id"],
            "H3_fault": by_seq[326]["id"],
            "H4_successful_heartbeat": by_seq[349]["id"],
            "H4_first_addKeys": by_seq[367]["id"],
            "R4_next_key": by_seq[393]["id"],
            "H5_selected_key_addKeys": by_seq[413]["id"],
            "H5_selected_key_map_write": by_seq[414]["id"],
            "NN_selected_token_mint": by_seq[429]["id"],
            "selected_key_id": key_id,
            "lookups": observations,
        },
        "causal_explanation": (
            "All three exact DN heartbeat IOException faults delayed key delivery. "
            "The next heartbeats succeeded, and the DN installed the later "
            "selected key before the test's DN block-token lookup. Both selected "
            "lookups read the last installed manager/key/value/version and the "
            "missing-key guard did not throw. Additional consecutive heartbeat "
            "faults on this delayed-read workload are not justified by this trace."
        ),
        "source_locations": [
            "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestEncryptedTransfer.java:300",
            "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java:703",
            "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java:224",
            "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java:501",
        ],
    }
    save(args.receipt_out, receipt)
    print(json.dumps({"status": receipt["status"], "receipt_sha256": sha(args.receipt_out),
                      "raw_manifest_sha256": receipt["raw_manifest_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
