#!/usr/bin/env python3
"""Verify HDFS-32's isolated heartbeat package without starting Java."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sys


BASE = Path("/users/ZhenyuLi/baseline")
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs32-heartbeat-node2-full-v2"
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
MIRROR = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
RELEASE_SHA = "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
CHECK = "org.apache.hadoop.hdfs.server.datanode.DataNode#deleteBlockPool(Ljava/lang/String;Z)V@3819:branch:1"
THROW = "org.apache.hadoop.hdfs.server.datanode.DataNode#deleteBlockPool(Ljava/lang/String;Z)V@3822:throw:1"
DOOR_CLASS = "org.apache.hadoop.hdfs.server.datanode.BPServiceActor"
DOOR_SITE = "org.apache.hadoop.hdfs.server.datanode.BPServiceActor#sendHeartBeat(Z)Lorg/apache/hadoop/hdfs/server/protocol/HeartbeatResponse;@563:door:1"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require_hash(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed artifact: {path}")


def reference_digest(root: Path, reference: dict) -> str:
    h = hashlib.sha256()
    for relative in reference["paths"]:
        path = root / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"source reference missing: {path}")
        h.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return h.hexdigest()


def require_line(path: Path, number: int, fragment: str) -> None:
    lines = path.read_text().splitlines()
    if len(lines) < number or fragment not in lines[number - 1]:
        raise RuntimeError(f"source operation moved: {path}:{number}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true")
    args = parser.parse_args()
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("runtime preflight is reserved for node2")
    root = MIRROR if args.static else SOURCE
    manifest = json.loads((HERE / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        require_hash(HERE / name, expected)
    require_hash(RELEASE / "manifest.json", RELEASE_SHA)
    for name, expected in json.loads((RELEASE / "manifest.json").read_text())["files"].items():
        require_hash(RELEASE / name, expected)

    config_path = HERE / "HDFS-32-node2-full-v2.json"
    config = json.loads(config_path.read_text())
    site = json.loads((HERE / "HDFS-32.sites.json").read_text())
    budget = config["budget"]
    if (config["case_id"] != "HDFS-32" or
            config["cluster_test"] != "org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool#testDfsAdminDeleteBlockPool" or
            config["target"]["check_sites"] != [CHECK] or
            config["target"]["throw_site"] != THROW or
            config["target"]["exception_class"] != "java.io.IOException" or
            config["agent_properties"].get("auto.io.doors") is not False or
            config.get("explore_outside_closure") is not True or
            config.get("auto_promote_if_healthy") is not True or
            config.get("calibration_only") is not False or
            (budget["trials"], budget["seconds"], budget["max_faults_per_trial"],
             budget["trial_timeout_seconds"]) != (80, 3600, 3, 360) or
            config["site_file"] != str(HERE / "HDFS-32.sites.json") or
            config["cwd"] != str(SOURCE) or config["source_equivalent_root"] != str(SOURCE) or
            site["doors"] != [{"clazz": DOOR_CLASS, "method": "sendHeartBeat",
                                "descriptor": "(Z)Lorg/apache/hadoop/hdfs/server/protocol/HeartbeatResponse;",
                                "line": 563,
                                "callee": "org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB#sendHeartbeat(Lorg/apache/hadoop/hdfs/server/protocol/DatanodeRegistration;[Lorg/apache/hadoop/hdfs/server/protocol/StorageReport;JJIIILorg/apache/hadoop/hdfs/server/protocol/VolumeFailureSummary;ZLorg/apache/hadoop/hdfs/server/protocol/SlowPeerReports;Lorg/apache/hadoop/hdfs/server/protocol/SlowDiskReports;)Lorg/apache/hadoop/hdfs/server/protocol/HeartbeatResponse;",
                                "exception_class": "java.io.IOException"}]):
        raise RuntimeError("HDFS-32 source-backed fault scope changed")
    if (site["targets"][0]["line"], site["targets"][1]["line"]) != (3819, 3822):
        raise RuntimeError("target catalog changed")
    review = config["source_review"]
    require_hash(Path(review["path"]), review["sha256"])
    require_hash(BASE / config["mapping"]["prior_healthy_result"],
                 config["mapping"]["prior_healthy_result_sha256"])
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if args.static and path.is_relative_to(SOURCE):
            path = MIRROR / path.relative_to(SOURCE)
        require_hash(path, artifact["sha256"])

    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if pinned["digest"] != SOURCE_DIGEST or reference_digest(root, pinned) != SOURCE_DIGEST:
        raise RuntimeError("Hadoop source digest changed")
    hdfs = root / "hadoop-hdfs-project/hadoop-hdfs"
    require_line(hdfs / "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java",
                 563, "bpNamenode.sendHeartbeat")
    require_line(hdfs / "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java",
                 3819, "if (blockPoolManager.get(blockPoolId) != null)")
    require_line(hdfs / "src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDeleteBlockPool.java",
                 168, "dn1.refreshNamenodes(nn1Conf)")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(RELEASE))
    from Mallory.core.campaign import validate_config
    check_copy = dict(config)
    if args.static:
        check_copy["cwd"] = str(MIRROR)
    validate_config(check_copy)

    out = Path("/tmp/mallory-hdfs32-heartbeat-node2-full-v2")
    if not args.static:
        if out.exists():
            if not (out / "checkpoint.json").is_file() or json.loads((out / "config.json").read_text()) != config:
                raise RuntimeError("existing output has no matching resumable checkpoint")
        if shutil.disk_usage("/tmp").free < 6_000_000_000:
            raise RuntimeError("node2 scratch is below reserve")
    print(json.dumps({"status": "static_preflight_pass" if args.static else "preflight_pass",
                      "case_id": "HDFS-32", "config_sha256": sha(config_path),
                      "source_root": str(root), "output": str(out),
                      "resuming": out.exists() if not args.static else False,
                      "jvm_started": False}, sort_keys=True))


if __name__ == "__main__":
    main()
