#!/usr/bin/env python3
"""Read-only HDFS-48 package and archived admission checks; never starts Java."""

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
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs48-node2-full-stage-v1"
CONFIG = HERE / "HDFS-48-node2-full-v1.json"
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
MIRROR = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
OUTPUT = Path("/tmp/mallory-hdfs48-original-v1-node2-full")
RELEASE = BASE / "Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
RELEASE_MANIFEST_SHA = "101e132c7513ac37650276d858da4b5cb766903e38be06158db2d4c472c0417f"
SELECTOR = "org.apache.hadoop.hdfs.server.namenode.snapshot.TestRenameWithSnapshots#testRenameUndo_1"
TARGET_SITE = "org.apache.hadoop.hdfs.server.namenode.INodeDirectory#replaceChild(Lorg/apache/hadoop/hdfs/server/namenode/INode;Lorg/apache/hadoop/hdfs/server/namenode/INode;Lorg/apache/hadoop/hdfs/server/namenode/INodeMap;)V@356:branch:2"
FAULT_SITE = "org.apache.hadoop.ipc.Server$RpcCall#run()Ljava/lang/Void;@1246:door:1"
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


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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


def check_archived_admission(manifest: dict) -> None:
    for relative, expected in manifest["archive_pins"].items():
        require_hash(BASE / relative, expected)
    healthy = read_json(BASE / "data/mallory/calibration_v14_node0/HDFS-48/result.json")
    trial = read_json(BASE / "data/mallory/calibration_v14_node0/HDFS-48/trials/r0000/result.json")
    audit = read_json(BASE / "data/mallory/calibration_v14_node0/HDFS-48/offline-causal-audit.json")
    pilot = read_json(BASE / "data/mallory/pilots_v14/HDFS-48-nn-only/result.json")
    injected = read_json(BASE / "data/mallory/pilots_v14/HDFS-48-nn-only/trials/r0001/result.json")
    junit = healthy["healthy_junit_validation"]
    feedback = trial["feedback"]
    if (healthy.get("healthy_seed_valid") is not True or
            tuple(junit.get(key) for key in ("tests", "failures", "errors")) != (1, 0, 0) or
            feedback.get("target_reached") is not True or
            feedback.get("target_threw") is not False or
            feedback.get("target_identity_complete") is not True or
            not any(row.get("node") == "hdfs-cluster-1/nn0"
                    for row in feedback.get("target_instances", [])) or
            trial["site_catalog_validation"].get("valid") is not True or
            trial["site_catalog_validation"].get("missing_check_sites") != [] or
            trial["site_catalog_validation"].get("observed_target_class_sha256") !=
            "232f9db67f1b60193619a1c44907f58db0a4877e82d132824a564598c2deabcb"):
        raise RuntimeError("archived healthy exact named target admission failed")
    if (audit.get("report_gate_passed") is not True or
            audit.get("healthy_observed_path_doors", 0) < 1):
        raise RuntimeError("archived healthy causal audit failed")
    if (pilot.get("fault_trials_completed") != 10 or
            pilot.get("strict_injected_trials") != 10 or
            injected["feedback"].get("all_faults_effective") is not True or
            injected["feedback"].get("fault_identity_valid") is not True or
            not any(fault.get("point", {}).get("site") == FAULT_SITE and
                    fault.get("exception_class") == "java.io.IOException"
                    for fault in injected.get("plan", []))):
        raise RuntimeError("archived effective injectable I/O admission failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static", action="store_true", help="verify on node0's source mirror without Java")
    args = parser.parse_args()
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("HDFS-48 runtime preflight must run on node2")

    manifest = read_json(HERE / "package-manifest.json")
    if manifest.get("case_id") != "HDFS-48" or manifest.get("stage") != "node2_full_pending_dispatch":
        raise RuntimeError("unexpected HDFS-48 package manifest")
    for name, expected in manifest["files"].items():
        require_hash(HERE / name, expected)
    require_hash(RELEASE / "manifest.json", RELEASE_MANIFEST_SHA)
    for name, expected in read_json(RELEASE / "manifest.json")["files"].items():
        require_hash(RELEASE / name, expected)

    config = read_json(CONFIG)
    sys.path.insert(0, str(RELEASE))
    from Mallory.core.campaign import validate_config
    validation_copy = dict(config)
    if args.static:
        validation_copy["cwd"] = str(MIRROR)
    validate_config(validation_copy)
    budget = config["budget"]
    if (config.get("case_id") != "HDFS-48" or config.get("cluster_test") != SELECTOR or
            config.get("command", [None] * 6)[5] != "-Dtest=TestRenameWithSnapshots#testRenameUndo_1" or
            config.get("calibration_only") is not False or
            config.get("auto_promote_if_healthy") is not True or
            (budget["trials"], budget["seconds"], budget["max_faults_per_trial"],
             budget["trial_timeout_seconds"]) != (80, 3600, 3, 600) or
            config.get("cwd") != str(SOURCE) or
            config.get("source_equivalent_root") != str(SOURCE) or
            config.get("core_release") != str(RELEASE) or
            config.get("target", {}).get("nodes") != ["hdfs-cluster-1/nn0"] or
            TARGET_SITE not in config.get("target", {}).get("check_sites", [])):
        raise RuntimeError("not the pinned original-selector HDFS-48 full config")

    site = read_json(HERE / "HDFS-48.sites.json")
    if (site.get("doors") != [] or len(site.get("targets", [])) != 3 or
            config["agent_properties"].get("auto.io.doors") is not True):
        raise RuntimeError("HDFS-48 target/automatic I/O instrumentation changed")
    check_archived_admission(manifest)
    root = MIRROR if args.static else SOURCE
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if args.static and path.is_relative_to(SOURCE):
            path = MIRROR / path.relative_to(SOURCE)
        require_hash(path, artifact["sha256"])
    reference = read_json(BASE / "Mallory/dispatch/source_reference.json")
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if pinned["digest"] != SOURCE_DIGEST or source_digest(root, pinned) != SOURCE_DIGEST:
        raise RuntimeError(f"HDFS source fingerprint changed: {root}")
    if not args.static:
        if OUTPUT.exists():
            if read_json(OUTPUT / "config.json") != config or not (OUTPUT / "checkpoint.json").is_file():
                raise RuntimeError("existing output is not a matching resumable campaign")
        free = shutil.disk_usage(BASE).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(f"node2 disk below campaign reserve: {free}")
    print(json.dumps({"status": "static_preflight_pass" if args.static else "preflight_pass",
                      "case_id": "HDFS-48", "config_sha256": manifest["files"][CONFIG.name],
                      "source_digest": SOURCE_DIGEST, "source_root": str(root),
                      "output": str(OUTPUT), "resuming": OUTPUT.exists() if not args.static else False},
                     sort_keys=True))


if __name__ == "__main__":
    main()
