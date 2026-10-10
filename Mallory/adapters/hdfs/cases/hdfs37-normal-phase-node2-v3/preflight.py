#!/usr/bin/env python3
"""Verify HDFS-37 source, artifact, and target pins without starting Java."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
ORIGINAL = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs37-normal-node2-v3")
REFERENCE = BASE / "Mallory/dispatch/source_reference.json"
V2 = HERE.parent / "hdfs37-normal-phase-v2"
TEST_RELATIVE = Path("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestDFSRollback.java")
TEST_CLASS = Path("hadoop-hdfs-project/hadoop-hdfs/target/test-classes/org/apache/hadoop/hdfs/TestDFSRollback.class")
TARGET_CLASS = Path("hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/DataStorage.class")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed pinned artifact: {path}")


def source_digest(root: Path, paths: list[str], patch: bytes | None = None) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        path = root / relative
        if patch is not None and relative == str(TEST_RELATIVE):
            payload = b"F" + hashlib.sha256(patch).digest()
        elif path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"missing source file in frozen snapshot: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def materialize_config(template: dict, test_sha: str) -> dict:
    config = json.loads(json.dumps(template))
    config["mapping"]["compiled_test_class_sha256"] = test_sha
    config["mapping"]["status"] = "node2_compiled_healthy_pending"
    config["runtime_artifacts"].append({
        "path": str(SOURCE / TEST_CLASS), "sha256": test_sha,
    })
    config.pop("offline_blocked_reason", None)
    return config


def preflight(runtime: bool) -> dict:
    if runtime and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("HDFS-37 runtime package is scoped to node2")
    pins = json.loads((HERE / "package-manifest.json").read_text())
    for name, expected in pins["package_files"].items():
        require(HERE / name, expected)
    for name, expected in pins["external_files"].items():
        require(BASE / name, expected)

    ref = json.loads(REFERENCE.read_text())["roots"][str(ORIGINAL)]
    if (ref["commit"] != pins["source_commit"] or
            ref["digest"] != pins["original_full_source_digest"]):
        raise RuntimeError("frozen Hadoop source reference differs from package")
    commit = subprocess.check_output(
        ["git", "-C", str(ORIGINAL), "rev-parse", "HEAD"], text=True).strip()
    if commit != pins["source_commit"]:
        raise RuntimeError("pristine Hadoop checkout commit changed")
    if source_digest(ORIGINAL, ref["paths"]) != pins["original_full_source_digest"]:
        raise RuntimeError("original Hadoop source snapshot changed")
    sys.path.insert(0, str(V2))
    from prepare_overlay import render  # noqa: E402
    overlay = json.loads((V2 / "source-overlay-receipt.json").read_text())
    patched_test = render((ORIGINAL / TEST_RELATIVE).read_bytes(), overlay)
    if source_digest(ORIGINAL, ref["paths"], patched_test) != pins["patched_full_source_digest"]:
        raise RuntimeError("adapted Hadoop source snapshot pin is wrong")

    config_path = HERE / "HDFS-37-node2-healthy-BLOCKED.json"
    config = json.loads(config_path.read_text())
    sites = json.loads((V2 / "HDFS-37.sites.json").read_text())
    if (config["case_id"] != "HDFS-37" or
            config["cluster_test"] != "org.apache.hadoop.hdfs.TestDFSRollback#testRollback" or
            config["cwd"] != str(SOURCE) or
            config["source_equivalent_root"] != str(SOURCE) or
            config["target"]["nodes"] != ["hdfs-cluster-1/dn0"] or
            config["target"]["source_line"] != 947 or
            config["target"]["exception_class"] != "org.apache.hadoop.hdfs.server.common.InconsistentFSStateException" or
            config["target"]["check_sites"] != [
                "org.apache.hadoop.hdfs.server.datanode.DataStorage#doRollback(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;)V@940:branch:3",
                "org.apache.hadoop.hdfs.server.datanode.DataStorage#doRollback(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;)V@941:branch:4",
            ] or
            config["calibration_only"] is not True or
            config["auto_promote_if_healthy"] is not False or
            config["mapping"]["full_admission"] is not False or
            config["mapping"]["healthy_seed_verified"] is not False or
            config["mapping"]["compiled_test_class_sha256"] is not None or
            config["budget"]["trials"] != 1 or
            config["budget"]["max_faults_per_trial"] != 1 or
            config["healthy_gate"]["required_junit_tests"] != 1 or
            config["healthy_gate"]["required_junit_errors"] != 0 or
            config["healthy_gate"]["required_junit_failures"] != 0 or
            config["healthy_gate"]["require_named_target_node"] is not True or
            config["healthy_gate"]["require_target_exception_absent"] is not True or
            not any(d["method"] == "readPropertiesFile" and d["line"] == 272
                    for d in sites["doors"])):
        raise RuntimeError("HDFS-37 healthy template or selected I/O frontier changed")
    if not runtime and SOURCE.exists():
        raise RuntimeError("dedicated source root already exists; use --runtime")

    release = Path(config["core_release"])
    require(release / "manifest.json", pins["core_release_manifest_sha256"])
    for relative, expected in json.loads((release / "manifest.json").read_text())["files"].items():
        require(release / relative, expected)
    sys.path.insert(0, str(release))
    from Mallory.core.campaign import load_static_frontier, validate_config  # noqa: E402
    candidate = json.loads(json.dumps(config))
    if runtime:
        receipt_path = SOURCE / "mallory-hdfs37-compiled-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get("case_id") != "HDFS-37" or
                receipt.get("source_commit") != pins["source_commit"] or
                receipt.get("patched_full_source_digest") != pins["patched_full_source_digest"] or
                receipt.get("target_class_sha256") != pins["target_class_sha256"] or
                receipt.get("full_admitted") is not False):
            raise RuntimeError("compiled receipt differs from staged package pins")
        require(SOURCE / TEST_RELATIVE, pins["patched_test_source_sha256"])
        if source_digest(SOURCE, ref["paths"]) != pins["patched_full_source_digest"]:
            raise RuntimeError("dedicated patched source snapshot changed")
        require(SOURCE / TARGET_CLASS, pins["target_class_sha256"])
        require(SOURCE / TEST_CLASS, receipt["compiled_test_class_sha256"])
        if receipt["compiled_test_class_sha256"] == pins["original_test_class_sha256"]:
            raise RuntimeError("test class was not rebuilt from adapted source")
        runtime_config = SOURCE / "mallory-hdfs37-healthy-node2-v3.json"
        require(runtime_config, receipt["runtime_config_sha256"])
        candidate = json.loads(runtime_config.read_text())
        if candidate != materialize_config(config, receipt["compiled_test_class_sha256"]):
            raise RuntimeError("compiled runtime config is not a healthy-only candidate")
        for artifact in candidate["runtime_artifacts"]:
            require(Path(artifact["path"]), artifact["sha256"])
    else:
        candidate["cwd"] = str(ORIGINAL)
        candidate["source_equivalent_root"] = str(ORIGINAL)
        candidate["runtime_artifacts"] = [
            item for item in candidate["runtime_artifacts"]
            if not Path(item["path"]).is_relative_to(SOURCE)
        ]
        for artifact in candidate["runtime_artifacts"]:
            require(Path(artifact["path"]), artifact["sha256"])
    validate_config(candidate)
    load_static_frontier(candidate)
    return {"case_id": "HDFS-37", "status": "runtime_preflight_pass" if runtime else "static_preflight_pass",
            "source_digest": pins["patched_full_source_digest"], "healthy_run_admitted": False,
            "full_admitted": False, "jvm_started": False}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true", help="verify compiled isolated node2 source and runtime config")
    args = parser.parse_args()
    print(json.dumps(preflight(args.runtime), sort_keys=True))


if __name__ == "__main__":
    main()
