#!/usr/bin/env python3
"""No-JVM SHA and source preflight for the original HDFS-31/32 JUnit campaigns."""

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
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs31-32-node2-full-stage-v1"
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
MIRROR = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
RELEASE_MANIFEST_SHA = "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
MIN_FREE_BYTES = 6_000_000_000
TARGET = {
    "HDFS-31": (
        "org.apache.hadoop.hdfs.server.datanode.DataNode#getBPOSForBlock(Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;)Lorg/apache/hadoop/hdfs/server/datanode/BPOfferService;@1833:branch:1",
        "org.apache.hadoop.hdfs.server.datanode.DataNode#getBPOSForBlock(Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;)Lorg/apache/hadoop/hdfs/server/datanode/BPOfferService;@1835:throw:1",
        "TestDiskError#testDataTransferWhenBytesPerChecksumIsZero",
        240),
    "HDFS-32": (
        "org.apache.hadoop.hdfs.server.datanode.DataNode#deleteBlockPool(Ljava/lang/String;Z)V@3819:branch:1",
        "org.apache.hadoop.hdfs.server.datanode.DataNode#deleteBlockPool(Ljava/lang/String;Z)V@3822:throw:1",
        "TestDeleteBlockPool#testDfsAdminDeleteBlockPool",
        360),
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_hash(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed artifact: {path}")


def reference_digest(root: Path, reference: dict) -> str:
    digest = hashlib.sha256()
    for relative in reference["paths"]:
        path = root / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"source reference file missing: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def require_line(path: Path, number: int, expected: str) -> None:
    lines = path.read_text().splitlines()
    if len(lines) < number or expected not in lines[number - 1]:
        raise RuntimeError(f"source operation moved: {path}:{number}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=tuple(TARGET), required=True)
    parser.add_argument("--static", action="store_true",
                        help="check the local byte-identical mirror; never start Java")
    args = parser.parse_args()
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("runtime preflight must run on node2")
    root = MIRROR if args.static else SOURCE
    manifest = json.loads((HERE / "manifest.json").read_text())
    if manifest.get("schema_version") != 1 or manifest.get("case_ids") != list(TARGET):
        raise RuntimeError("HDFS-31/32 manifest changed")
    for relative, expected in manifest["files"].items():
        require_hash(HERE / relative, expected)
    require_hash(RELEASE / "manifest.json", RELEASE_MANIFEST_SHA)
    for relative, expected in json.loads((RELEASE / "manifest.json").read_text())["files"].items():
        require_hash(RELEASE / relative, expected)

    config_path = HERE / f"{args.case}-node2-full-v1.json"
    config = json.loads(config_path.read_text())
    site = json.loads((HERE / f"{args.case}.sites.json").read_text())
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(RELEASE))
    from Mallory.core.campaign import validate_config

    validation_copy = dict(config)
    if args.static:
        validation_copy["cwd"] = str(MIRROR)
    validate_config(validation_copy)
    check, throw, selector, timeout = TARGET[args.case]
    budget = config["budget"]
    if (config["case_id"] != args.case or config["cluster_test"].split(".")[-1] != selector or
            config["target"]["check_sites"] != [check] or
            config["target"]["throw_site"] != throw or
            config["target"]["exception_class"] != "java.io.IOException" or
            f"-Dtest={selector}" not in config["command"] or
            "-Dtest.build.data={trial_dir}/hdfs-data" not in config["command"] or
            config.get("calibration_only") is not False or
            config.get("auto_promote_if_healthy") is not True or
            config.get("explore_outside_closure") is not True or
            config.get("core_release") != str(RELEASE) or
            config.get("cwd") != str(SOURCE) or
            config.get("source_equivalent_root") != str(SOURCE) or
            config["agent_properties"].get("auto.io.doors") is not True or
            config.get("fault_types") != ["EXCEPTION"] or
            (budget["trials"], budget["seconds"], budget["max_faults_per_trial"],
             budget["trial_timeout_seconds"]) != (80, 3600, 3, timeout)):
        raise RuntimeError("full campaign config differs from selected original JUnit or budget")
    if len(site["targets"]) != 2 or len(site["doors"]) < 2:
        raise RuntimeError("case-local target or I/O catalog missing")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if args.static and path.is_relative_to(SOURCE):
            path = MIRROR / path.relative_to(SOURCE)
        require_hash(path, artifact["sha256"])

    ref = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = ref["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if pinned["digest"] != SOURCE_DIGEST or reference_digest(root, pinned) != SOURCE_DIGEST:
        raise RuntimeError(f"HDFS released source fingerprint changed: {root}")
    hdfs = root / "hadoop-hdfs-project/hadoop-hdfs"
    require_line(hdfs / "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java",
                 563, "bpNamenode.sendHeartbeat")
    if args.case == "HDFS-31":
        test = hdfs / "src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDiskError.java"
        require_line(test, 259, "raFile.writeByte(0)")
        require_line(test, 260, "raFile.writeInt(0)")
        require_line(hdfs / "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java",
                     1833, "if (bpos == null)")
    else:
        require_line(hdfs / "src/main/java/org/apache/hadoop/hdfs/tools/DFSAdmin.java",
                     2702, "dnProxy.deleteBlockPool(argv[i+1], force)")
        require_line(hdfs / "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java",
                     3819, "if (blockPoolManager.get(blockPoolId) != null)")
        if config["target_semantic_identity"].get("runtime_verified") is not False:
            raise RuntimeError("HDFS-32 force flag has not been runtime attested")

    output = Path(f"/tmp/mallory-{args.case.lower()}-node2-full-v1")
    if not args.static:
        if output.exists():
            prior_config = output / "config.json"
            if not prior_config.is_file() or json.loads(prior_config.read_text()) != config:
                raise RuntimeError("existing output has different config")
            if not (output / "checkpoint.json").is_file():
                raise RuntimeError("existing output has no resumable checkpoint")
        free = shutil.disk_usage("/tmp").free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(f"node2 scratch below reserve: {free}")
    print(json.dumps({"status": "static_preflight_pass" if args.static else "preflight_pass",
                      "case_id": args.case, "config_sha256": sha(config_path),
                      "source_digest": SOURCE_DIGEST, "source_root": str(root),
                      "output": str(output), "resuming": output.exists() if not args.static else False,
                      "jvm_started": False}, sort_keys=True))


if __name__ == "__main__":
    main()
