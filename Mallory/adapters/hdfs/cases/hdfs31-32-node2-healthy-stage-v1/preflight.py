#!/usr/bin/env python3
"""No-JVM SHA and source preflight for HDFS-31/32 healthy admission."""

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
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs31-32-node2-healthy-stage-v1"
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
MIRROR = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
RELEASE_MANIFEST_SHA = "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
CONFIG_SHA = {
    "HDFS-31": "04544f739cda7fe97974bbeccf2df578b42870c3649b5d153aa3305da5a2bd71",
    "HDFS-32": "de2e10671adbb42ab24e94f8571625f83ff0722694751804f5bc662e9ecc26cf",
}
TEST = {
    "HDFS-31": "org.apache.hadoop.hdfs.server.datanode.TestDiskError#testDataTransferWhenBytesPerChecksumIsZero",
    "HDFS-32": "org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool#testDfsAdminDeleteBlockPool",
}
CHECK = {
    "HDFS-31": ("org.apache.hadoop.hdfs.server.datanode.DataNode#getBPOSForBlock(Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;)Lorg/apache/hadoop/hdfs/server/datanode/BPOfferService;@1833:branch:1", 240, 600),
    "HDFS-32": ("org.apache.hadoop.hdfs.server.datanode.DataNode#deleteBlockPool(Ljava/lang/String;Z)V@3819:branch:1", 360, 900),
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


def require_line(path: Path, number: int, expected: str) -> None:
    lines = path.read_text().splitlines()
    if len(lines) < number or expected not in lines[number - 1]:
        raise RuntimeError(f"source operation moved: {path}:{number}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=tuple(CONFIG_SHA), required=True)
    parser.add_argument("--static", action="store_true", help="check local equivalent source without Java")
    args = parser.parse_args()
    host = socket.gethostname().split(".")[0]
    if not args.static and host != "node2":
        raise RuntimeError("runtime preflight must run on node2")
    root = SOURCE if host == "node2" else MIRROR
    if not args.static:
        root = SOURCE

    manifest = json.loads((HERE / "manifest.json").read_text())
    if manifest.get("case_ids") != list(CONFIG_SHA) or manifest.get("status") != "healthy_only_staged_no_jvm":
        raise RuntimeError("healthy package manifest changed")
    for name, expected in manifest["files"].items():
        require_hash(HERE / name, expected)
    case = args.case
    config_path = HERE / f"{case}-node2-healthy-v1.json"
    require_hash(config_path, CONFIG_SHA[case])
    config = json.loads(config_path.read_text())
    site = json.loads((HERE / f"{case}.sites.json").read_text())
    check, timeout, seconds = CHECK[case]
    budget = config["budget"]
    gate = config["healthy_gate"]
    if (config.get("case_id") != case or config.get("cluster_test") != TEST[case] or
            config.get("target", {}).get("check_sites") != [check] or
            config.get("target", {}).get("exception_class") != "java.io.IOException" or
            config.get("calibration_only") is not True or
            config.get("auto_promote_if_healthy") is not False or
            (budget["trials"], budget["seconds"], budget["max_faults_per_trial"], budget["trial_timeout_seconds"]) !=
            (1, seconds, 1, timeout) or
            gate.get("require_exact_target_reached") is not True or
            gate.get("require_named_target_node") is not True or
            gate.get("require_target_exception_absent") is not True or
            (gate.get("required_junit_tests"), gate.get("required_junit_errors"), gate.get("required_junit_failures")) != (1, 0, 0) or
            config.get("cwd") != str(SOURCE) or config.get("source_equivalent_root") != str(SOURCE) or
            config.get("site_file") != str(HERE / f"{case}.sites.json") or
            config.get("expected_target_class_sha256") != "9adbbabe330f09303c5fab84997b68879055cb4f97a9377b4da03a87bc1250cf" or
            config.get("mapping", {}).get("healthy_seed_verified") is not False):
        raise RuntimeError("healthy candidate differs from pinned case")
    if len(site["targets"]) != 2 or len(site["doors"]) < 2 or any(
            d.get("exception_class") != "java.io.IOException" for d in site["doors"]):
        raise RuntimeError("typed I/O catalog changed")

    require_hash(RELEASE / "manifest.json", RELEASE_MANIFEST_SHA)
    for name, expected in json.loads((RELEASE / "manifest.json").read_text())["files"].items():
        require_hash(RELEASE / name, expected)
    for row in config["runtime_artifacts"]:
        path = Path(row["path"])
        if args.static and path.is_relative_to(SOURCE):
            path = root / path.relative_to(SOURCE)
        require_hash(path, row["sha256"])
    old_path = Path(config["mapping"]["prior_full_config"])
    require_hash(old_path, config["mapping"]["prior_full_config_sha256"])

    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if pinned["digest"] != SOURCE_DIGEST or source_digest(root, pinned) != SOURCE_DIGEST:
        raise RuntimeError(f"HDFS source fingerprint changed: {root}")
    hdfs = root / "hadoop-hdfs-project/hadoop-hdfs"
    dn = hdfs / "src/main/java/org/apache/hadoop/hdfs/server/datanode/DataNode.java"
    actor = hdfs / "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java"
    require_line(actor, 563, "bpNamenode.sendHeartbeat")
    if case == "HDFS-31":
        require_line(dn, 1833, "if (bpos == null)")
        test = hdfs / "src/test/java/org/apache/hadoop/hdfs/server/datanode/TestDiskError.java"
        require_line(test, 259, "raFile.writeByte(0)")
        require_line(test, 260, "raFile.writeInt(0)")
        require_line(test, 277, "dn0.transferBlock(block")
    else:
        require_line(dn, 3819, "if (blockPoolManager.get(blockPoolId) != null)")
        admin = hdfs / "src/main/java/org/apache/hadoop/hdfs/tools/DFSAdmin.java"
        require_line(admin, 2702, "dnProxy.deleteBlockPool(argv[i+1], force)")
        if config["target_semantic_identity"].get("runtime_verified") is not False:
            raise RuntimeError("HDFS-32 request force flag not yet attested")

    sys.dont_write_bytecode = True
    sys.path.insert(0, str(RELEASE))
    from Mallory.core.campaign import load_static_frontier, validate_config
    validation_copy = dict(config)
    if args.static:
        validation_copy["cwd"] = str(root)
    validate_config(validation_copy)
    load_static_frontier(validation_copy)

    output = Path(f"/tmp/mallory-{case.lower()}-node2-healthy-v1")
    if not args.static:
        if output.exists():
            raise RuntimeError(f"fresh healthy output already exists: {output}")
        free = shutil.disk_usage("/tmp").free
        if free < 6_000_000_000:
            raise RuntimeError(f"node2 scratch below reserve: {free}")
    print(json.dumps({"status": "static_preflight_pass" if args.static else "preflight_pass",
                      "case_id": case, "config_sha256": CONFIG_SHA[case],
                      "source_digest": SOURCE_DIGEST, "source_root": str(root),
                      "output": str(output), "jvm_started": False,
                      "healthy_admitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
