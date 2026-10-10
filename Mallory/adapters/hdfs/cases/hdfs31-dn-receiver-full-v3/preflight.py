#!/usr/bin/env python3
"""SHA-pinned no-JVM preflight for the HDFS-31 receiver fault campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
MIRROR = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
ADAPTER = BASE / "Mallory/adapters/hdfs/cases/hdfs31-dn-receiver-v2/releases/c53142b7d7197fd43f1420a8ff498f8c2b147bc8d86828a9b3cf8e27b9a49b42/adapter.jar"
CONFIG = HERE / "HDFS-31-node2-full-v3.json"
SITE = HERE / "HDFS-31.sites.json"
OUTPUT = Path("/tmp/mallory-hdfs-31-node2-full-v3")
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
TARGET = ("org.apache.hadoop.hdfs.server.datanode.DataNode#"
          "getBPOSForBlock(Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;)"
          "Lorg/apache/hadoop/hdfs/server/datanode/BPOfferService;@1833:branch:1")
HEARTBEAT = ("org.apache.hadoop.hdfs.server.datanode.BPServiceActor#"
             "sendHeartBeat(Z)Lorg/apache/hadoop/hdfs/server/protocol/HeartbeatResponse;@563:door:1")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(path: Path, digest: str) -> None:
    if not path.is_file() or sha(path) != digest:
        raise RuntimeError(f"missing or changed artifact: {path}")


def source_digest(root: Path, reference: dict) -> str:
    digest = hashlib.sha256()
    for relative in reference["paths"]:
        path = root / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"missing source path: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true")
    args = parser.parse_args()
    host = socket.gethostname().split(".")[0]
    if not args.static and host != "node2":
        raise RuntimeError("runtime preflight must run on node2")
    root = MIRROR if args.static and host != "node2" else SOURCE
    manifest = json.loads((HERE / "manifest.json").read_text())
    if manifest.get("status") != "full_staged_no_jvm" or manifest.get("case_id") != "HDFS-31":
        raise RuntimeError("stage manifest changed")
    for relative, expected in manifest["files"].items():
        require(HERE / relative, expected)
    require(ADAPTER, "c53142b7d7197fd43f1420a8ff498f8c2b147bc8d86828a9b3cf8e27b9a49b42")
    cfg = json.loads(CONFIG.read_text())
    sites = json.loads(SITE.read_text())
    if (cfg["case_id"] != "HDFS-31"
            or cfg["cluster_test"] != "org.apache.hadoop.hdfs.server.datanode.TestDiskError#testDataTransferWhenBytesPerChecksumIsZero"
            or cfg["cwd"] != str(SOURCE)
            or cfg["site_file"] != str(SITE)
            or cfg["agent_properties"]["adapter.jar"] != str(ADAPTER)
            or cfg["target"]["check_sites"] != [TARGET]
            or cfg["budget"]["trials"] != 80
            or cfg["budget"]["seconds"] != 3600
            or cfg["budget"]["max_faults_per_trial"] != 3
            or cfg["calibration_only"] is not False
            or cfg["auto_promote_if_healthy"] is not True
            or cfg["healthy_gate"]["require_named_target_node"] is not True
            or cfg["healthy_gate"]["require_exact_target_reached"] is not True
            or cfg["mapping"]["node_identity_binding_verified"] is not True
            or cfg["mapping"]["receiver_actor_fix"]["runtime_verified"] is not True
            or sites["doors"][0]["method"] != "sendHeartBeat"
            or sites["doors"][0]["line"] != 563):
        raise RuntimeError("HDFS-31 full fault config changed")
    healthy_root = BASE / "data/mallory/healthy_observations/HDFS-31-dn-receiver-healthy-v2"
    require(healthy_root / "result.json", cfg["mapping"]["healthy_v2_result_sha256"])
    require(healthy_root / "trials/r0000/events.jsonl.gz", cfg["mapping"]["healthy_v2_events_sha256"])
    healthy = json.loads((healthy_root / "result.json").read_text())
    trace = json.loads((healthy_root / "trials/r0000/result.json").read_text())
    target_instances = trace["feedback"]["target_instances"]
    doors = trace["feedback"]["doors"]
    if (healthy["healthy_junit_validation"]["status"] != "passed"
            or healthy["target_binding"]["nodes"] != ["hdfs-cluster-1/dn0"]
            or not any(x.get("node") == "hdfs-cluster-1/dn0"
                       for x in target_instances)
            or not any(d.get("site") == HEARTBEAT
                       and d.get("point", {}).get("node") == "hdfs-cluster-1/dn0"
                       and d.get("event_seq", 999999) < 139 for d in doors)):
        raise RuntimeError("v2 healthy target or typed heartbeat witness changed")

    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    frozen = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if frozen["digest"] != SOURCE_DIGEST or source_digest(root, frozen) != SOURCE_DIGEST:
        raise RuntimeError(f"HDFS source fingerprint changed: {root}")
    for row in cfg["runtime_artifacts"]:
        path = Path(row["path"])
        if args.static and path.is_relative_to(SOURCE):
            path = root / path.relative_to(SOURCE)
        require(path, row["sha256"])
    release_manifest = json.loads((RELEASE / "manifest.json").read_text())
    for relative, expected in release_manifest["files"].items():
        require(RELEASE / relative, expected)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(RELEASE))
    from Mallory.core.campaign import load_static_frontier, validate_config
    validation_copy = dict(cfg)
    if args.static:
        validation_copy["cwd"] = str(root)
    validate_config(validation_copy)
    load_static_frontier(validation_copy)
    if not args.static and not OUTPUT.exists() and shutil.disk_usage("/tmp").free < 6_000_000_000:
        raise RuntimeError("node2 scratch below reserve")
    print(json.dumps({"status": "static_preflight_pass" if args.static else "preflight_pass",
                      "case_id": "HDFS-31", "config_sha256": sha(CONFIG),
                      "source_digest": SOURCE_DIGEST,
                      "fresh_or_resumable_output": str(OUTPUT), "jvm_started": False}, sort_keys=True))


if __name__ == "__main__":
    main()
