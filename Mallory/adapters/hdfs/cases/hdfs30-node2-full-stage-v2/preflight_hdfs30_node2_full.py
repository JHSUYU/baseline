#!/usr/bin/env python3
"""Read-only HDFS-30 full-campaign preflight; --static uses node0's source mirror."""

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
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs30-node2-full-stage-v2"
CONFIG = HERE / "HDFS-30-node2-full-v2.json"
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
LOCAL_SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
OUTPUT = Path("/tmp/mallory-hdfs30-original-v2-node2-full")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG_SHA = "29ba954473d182b858a7b1fa1ab5a17f169064cc34af14e8ead0ab166cbefafe"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
RELEASE_MANIFEST_SHA = "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
MIN_FREE_BYTES = 6_000_000_000


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(path: Path, expected: str) -> None:
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
            raise RuntimeError(f"source file missing: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true", help="check package and local source mirror without Java")
    args = parser.parse_args()
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("HDFS-30 runtime preflight must run on node2")

    require_hash(CONFIG, CONFIG_SHA)
    manifest = json.loads((HERE / "package-manifest.json").read_text())
    if manifest.get("case_id") != "HDFS-30":
        raise RuntimeError("HDFS-30 package manifest changed")
    for name, expected in manifest["files"].items():
        require_hash(HERE / name, expected)
    config = json.loads(CONFIG.read_text())
    sys.path.insert(0, str(RELEASE))
    from Mallory.core.campaign import validate_config

    validation_copy = dict(config)
    if args.static:
        validation_copy["cwd"] = str(LOCAL_SOURCE)
    validate_config(validation_copy)
    budget = config["budget"]
    selector = "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization"
    if (config.get("case_id") != "HDFS-30" or config.get("cluster_test") != selector or
            config.get("command", [None])[5] != "-Dtest=TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization" or
            config.get("calibration_only") is not False or
            config.get("auto_promote_if_healthy") is not True or
            (budget["trials"], budget["seconds"], budget["max_faults_per_trial"],
             budget["trial_timeout_seconds"]) != (80, 3600, 3, 600) or
            config.get("healthy_gate", {}).get("minimum_healthy_observed_path_doors") != 0 or
            config.get("healthy_gate", {}).get("require_nonempty_observed_graph_path") is not False or
            config.get("healthy_gate", {}).get("require_offline_audit_report_gate") is not False or
            config.get("healthy_gate", {}).get("require_exact_target_reached") is not True or
            config.get("healthy_gate", {}).get("require_named_target_node") is not True or
            config.get("healthy_gate", {}).get("require_target_exception_absent") is not True or
            config.get("reject_coarse_roots") is not True or
            config.get("require_event_time_paths") is not True or
            config.get("allow_local_timeline_doors") is not False or
            config.get("cwd") != str(SOURCE) or
            config.get("source_equivalent_root") != str(SOURCE)):
        raise RuntimeError("not the pinned HDFS-30 full config")
    site = json.loads(Path(config["site_file"]).read_text())
    door = site["doors"]
    if (len(door) != 1 or door[0]["method"] != "sendHeartBeat" or
            door[0]["line"] != 563 or door[0]["exception_class"] != "java.io.IOException" or
            config["target"]["check_sites"] != [
                "org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker#getActiveNamenodeForBP(Ljava/lang/String;)Lorg/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB;@582:branch:2"]):
        raise RuntimeError("HDFS-30 selected door or target changed")

    require_hash(RELEASE / "manifest.json", RELEASE_MANIFEST_SHA)
    for name, expected in json.loads((RELEASE / "manifest.json").read_text())["files"].items():
        require_hash(RELEASE / name, expected)
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if args.static and path.is_relative_to(SOURCE):
            path = LOCAL_SOURCE / path.relative_to(SOURCE)
        require_hash(path, artifact["sha256"])

    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    root = LOCAL_SOURCE if args.static else SOURCE
    if pinned["digest"] != SOURCE_DIGEST or source_digest(root, pinned) != SOURCE_DIGEST:
        raise RuntimeError(f"HDFS source fingerprint changed: {root}")
    if not args.static:
        if OUTPUT.exists():
            output_config = OUTPUT / "config.json"
            if not output_config.is_file() or json.loads(output_config.read_text()) != config:
                raise RuntimeError("existing output has a different config")
            if not (OUTPUT / "checkpoint.json").is_file():
                raise RuntimeError("existing output has no resumable checkpoint")
        free = shutil.disk_usage(BASE).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(f"node2 disk below campaign reserve: {free}")
    print(json.dumps({"status": "static_preflight_pass" if args.static else "preflight_pass",
                      "case_id": "HDFS-30", "config_sha256": CONFIG_SHA,
                      "source_digest": SOURCE_DIGEST, "source_root": str(root),
                      "output": str(OUTPUT), "resuming": OUTPUT.exists() if not args.static else False},
                     sort_keys=True))


if __name__ == "__main__":
    main()
