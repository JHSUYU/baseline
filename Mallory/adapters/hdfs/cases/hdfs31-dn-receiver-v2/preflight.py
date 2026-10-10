#!/usr/bin/env python3
"""No-JVM SHA and configuration preflight for HDFS-31 receiver actor repair."""

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
NODE2_SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
NODE0_MIRROR = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
CONFIG = HERE / "HDFS-31-node2-healthy-v2.json"
SITE = HERE / "HDFS-31.sites.json"
JAR_SHA = "c53142b7d7197fd43f1420a8ff498f8c2b147bc8d86828a9b3cf8e27b9a49b42"
JAR = HERE / "releases" / JAR_SHA / "adapter.jar"
OUTPUT = Path("/tmp/mallory-hdfs-31-node2-healthy-v2")
TARGET_SITE = (
    "org.apache.hadoop.hdfs.server.datanode.DataNode#"
    "getBPOSForBlock(Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;)"
    "Lorg/apache/hadoop/hdfs/server/datanode/BPOfferService;@1833:branch:1"
)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
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
    parser.add_argument("--static", action="store_true", help="check node0 mirror without Java")
    args = parser.parse_args()
    host = socket.gethostname().split(".")[0]
    if not args.static and host != "node2":
        raise RuntimeError("runtime preflight must run on node2")
    root = NODE0_MIRROR if args.static and host != "node2" else NODE2_SOURCE
    manifest = json.loads((HERE / "manifest.json").read_text())
    if manifest.get("status") != "isolated_healthy_only_no_jvm" or manifest.get("case_id") != "HDFS-31":
        raise RuntimeError("receiver package manifest changed")
    for relative, expected in manifest["files"].items():
        require(HERE / relative, expected)
    require(JAR, JAR_SHA)
    cfg = json.loads(CONFIG.read_text())
    sites = json.loads(SITE.read_text())
    gate = cfg["healthy_gate"]
    mapping = cfg["mapping"]
    if (cfg["case_id"] != "HDFS-31"
            or cfg["cluster_test"] != "org.apache.hadoop.hdfs.server.datanode.TestDiskError#testDataTransferWhenBytesPerChecksumIsZero"
            or cfg["cwd"] != str(NODE2_SOURCE)
            or cfg["source_equivalent_root"] != str(NODE2_SOURCE)
            or cfg["site_file"] != str(SITE)
            or cfg["agent_properties"]["adapter.jar"] != str(JAR)
            or cfg["target"]["check_sites"] != [TARGET_SITE]
            or cfg["expected_target_class_sha256"] != "9adbbabe330f09303c5fab84997b68879055cb4f97a9377b4da03a87bc1250cf"
            or cfg["calibration_only"] is not True
            or cfg["auto_promote_if_healthy"] is not False
            or cfg["budget"]["trials"] != 1
            or gate["require_exact_target_reached"] is not True
            or gate["require_named_target_node"] is not True
            or gate["require_target_exception_absent"] is not True
            or (gate["required_junit_tests"], gate["required_junit_errors"], gate["required_junit_failures"]) != (1, 0, 0)
            or mapping["healthy_seed_verified"] is not False
            or mapping["node_identity_binding_verified"] is not False
            or mapping["receiver_actor_fix"]["patched_adapter_jar_sha256"] != JAR_SHA
            or mapping["receiver_actor_fix"]["runtime_verified"] is not False):
        raise RuntimeError("HDFS-31 receiver healthy gate changed")
    if len(sites["targets"]) != 2 or not sites["doors"]:
        raise RuntimeError("HDFS-31 site catalog changed")

    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    frozen = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if frozen["digest"] != SOURCE_DIGEST or source_digest(root, frozen) != SOURCE_DIGEST:
        raise RuntimeError(f"HDFS source fingerprint changed: {root}")
    data_node = root / "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java"
    lines = data_node.read_text().splitlines()
    if "if (bpos == null)" not in lines[1832] or "BPOfferService bpos =" not in lines[1831]:
        raise RuntimeError("exact DataNode target moved")

    for row in cfg["runtime_artifacts"]:
        path = Path(row["path"])
        if args.static and path.is_relative_to(NODE2_SOURCE):
            path = root / path.relative_to(NODE2_SOURCE)
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

    if not args.static:
        if OUTPUT.exists():
            raise RuntimeError(f"fresh output already exists: {OUTPUT}")
        if shutil.disk_usage("/tmp").free < 6_000_000_000:
            raise RuntimeError("node2 scratch below reserve")
    print(json.dumps({
        "status": "static_preflight_pass" if args.static else "preflight_pass",
        "case_id": "HDFS-31", "config_sha256": sha(CONFIG),
        "adapter_sha256": JAR_SHA, "source_digest": SOURCE_DIGEST,
        "verified_source_root": str(root), "fresh_output": str(OUTPUT),
        "jvm_started": False, "healthy_admitted": False,
        "fault_campaign_admitted": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
