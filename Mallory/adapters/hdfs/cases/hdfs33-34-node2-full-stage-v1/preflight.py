#!/usr/bin/env python3
"""Read-only, SHA-pinned HDFS-33/34 full-stage preflight. Never starts Java."""

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
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs33-34-node2-full-stage-v1"
HEALTHY = BASE / "Mallory/adapters/hdfs/cases/hdfs33-34-node2-stage-v1"
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
LOCAL_SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
RELEASE_MANIFEST_SHA = "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
CONFIG_SHA = {
    "HDFS-33": "8f4a1b51b6345f64a6683b5145f756178c9c762b3616c3472cb41d8732f125c5",
    "HDFS-34": "ba793f8a0028dbc662dc727f2466fc41618e5507f75781b716daf8d76417c97c",
}
TEST = {
    "HDFS-33": "org.apache.hadoop.hdfs.server.datanode.TestDataNodeHotSwapVolumes#testAddOneNewVolume",
    "HDFS-34": "org.apache.hadoop.hdfs.TestDFSUpgradeFromImage#testUpgradeFromRel22Image",
}
TIMEOUT = {"HDFS-33": 480, "HDFS-34": 720}
OUTPUT = {
    "HDFS-33": Path("/tmp/mallory-hdfs33-node2-full-v1"),
    "HDFS-34": Path("/tmp/mallory-hdfs34-node2-full-v1"),
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
            raise RuntimeError(f"source file missing: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=tuple(CONFIG_SHA))
    parser.add_argument("--static", action="store_true", help="use the node0 equivalent source tree")
    args = parser.parse_args()
    case = args.case
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("runtime preflight must run on node2")

    manifest = json.loads((HERE / "package-manifest.json").read_text())
    if manifest.get("cases") != ["HDFS-33", "HDFS-34"] or manifest.get("stage") != "node2_full_pending_healthy_admission":
        raise RuntimeError("package manifest changed")
    for name, expected in manifest["files"].items():
        require_hash(HERE / name, expected)

    config_path = HERE / f"{case}-node2-full-v1.json"
    require_hash(config_path, CONFIG_SHA[case])
    config = json.loads(config_path.read_text())
    budget = config["budget"]
    gate = config["healthy_gate"]
    if (config.get("case_id") != case or config.get("cluster_test") != TEST[case] or
            config.get("calibration_only") is not False or
            config.get("auto_promote_if_healthy") is not True or
            (budget["trials"], budget["seconds"], budget["max_faults_per_trial"], budget["trial_timeout_seconds"]) !=
            (80, 3600, 3, TIMEOUT[case]) or
            gate.get("minimum_healthy_observed_path_doors") != 0 or
            gate.get("require_nonempty_observed_graph_path") is not False or
            gate.get("require_offline_audit_report_gate") is not False or
            gate.get("require_exact_target_reached") is not True or
            gate.get("require_named_target_node") is not True or
            gate.get("require_target_exception_absent") is not True or
            (gate.get("required_junit_tests"), gate.get("required_junit_errors"), gate.get("required_junit_failures")) != (1, 0, 0) or
            config.get("reject_coarse_roots") is not True or
            config.get("require_event_time_paths") is not True or
            config.get("cwd") != str(SOURCE) or
            config.get("source_equivalent_root") != str(SOURCE) or
            config.get("mapping", {}).get("healthy_seed_verified") is not False):
        raise RuntimeError(f"not the pinned {case} full config")

    require_hash(RELEASE / "manifest.json", RELEASE_MANIFEST_SHA)
    for name, expected in json.loads((RELEASE / "manifest.json").read_text())["files"].items():
        require_hash(RELEASE / name, expected)
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if args.static and path.is_relative_to(SOURCE):
            path = LOCAL_SOURCE / path.relative_to(SOURCE)
        require_hash(path, artifact["sha256"])

    healthy_handoff = json.loads((HEALTHY / "handoff.json").read_text())
    require_hash(HEALTHY / "handoff.json", "516f6ae03de342abe28c4479754d6afb3145ea0e9ef32fa46bd384d091ada29d")
    healthy_row = next(row for row in healthy_handoff["healthy_cases"] if row["case_id"] == case)
    for key in ("config", "original_config", "source_review"):
        row = healthy_row[key]
        require_hash(Path(row["path"]), row["sha256"])
    if config["expected_target_class_sha256"] != healthy_row["target_class"]["sha256"]:
        raise RuntimeError("compiled target pin differs from healthy candidate")

    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    root = LOCAL_SOURCE if args.static else SOURCE
    if pinned["digest"] != SOURCE_DIGEST or source_digest(root, pinned) != SOURCE_DIGEST:
        raise RuntimeError(f"HDFS source fingerprint changed: {root}")

    sys.path.insert(0, str(RELEASE))
    sys.path.insert(1, str(BASE))
    from Mallory.core.campaign import load_static_frontier, validate_config

    validation_copy = dict(config)
    if args.static:
        validation_copy["cwd"] = str(LOCAL_SOURCE)
    validate_config(validation_copy)
    load_static_frontier(validation_copy)

    output = OUTPUT[case]
    if not args.static:
        if output.exists():
            require_hash(output / "config.json", CONFIG_SHA[case])
            if not (output / "checkpoint.json").is_file():
                raise RuntimeError("existing output has no resumable checkpoint")
        free = shutil.disk_usage(BASE).free
        if free < 6_000_000_000:
            raise RuntimeError(f"node2 disk below campaign reserve: {free}")
    print(json.dumps({"status": "static_preflight_pass" if args.static else "preflight_pass",
                      "case_id": case, "config_sha256": CONFIG_SHA[case],
                      "source_digest": SOURCE_DIGEST, "source_root": str(root),
                      "output": str(output), "resuming": output.exists() if not args.static else False,
                      "fresh_named_healthy_admitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
