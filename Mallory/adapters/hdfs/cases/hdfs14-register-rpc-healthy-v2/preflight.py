#!/usr/bin/env python3
"""Validate the isolated HDFS-14 healthy seed before any JUnit launch."""

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
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs14-register-rpc-healthy-v2"
CONFIG = HERE / "HDFS-14-register-rpc-healthy-v2.json"
REMOTE_SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
LOCAL_SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
OUTPUT = Path("/tmp/mallory-hdfs14-register-rpc-v2-node2-healthy")
CORE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
RELEASE = BASE / "Mallory/adapters/hdfs/cases/hdfs12-key-update-v2/releases/a94622fbb95d37c316c4c8f78727706b88859cc1a1dd04e00355d17c98a0d5e7"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
CORE_MANIFEST_SHA = "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
RELEASE_MANIFEST_SHA = "e91e849e3635c1547f0d9e8ecc5902844ba3903db6845692f2a203dae6a44a22"
MIN_FREE_BYTES = 6_000_000_000


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
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
    parser.add_argument("--static", action="store_true")
    args = parser.parse_args()
    if not args.static and socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("HDFS-14 runtime preflight must run on node2")

    manifest = json.loads((HERE / "package-manifest.json").read_text())
    if manifest.get("case_id") != "HDFS-14" or manifest.get("stage") != "node2_healthy_pending_dispatch":
        raise RuntimeError("unexpected HDFS-14 package manifest")
    for name, expected in manifest["files"].items():
        require_hash(HERE / name, expected)

    config = json.loads(CONFIG.read_text())
    source = LOCAL_SOURCE if args.static else REMOTE_SOURCE
    validation = dict(config)
    validation["cwd"] = str(source)
    sys.path[:0] = [str(CORE), str(BASE)]
    from Mallory.core.campaign import validate_config
    validate_config(validation)

    budget = config["budget"]
    if (config.get("case_id") != "HDFS-14" or
            config.get("calibration_only") is not True or
            config.get("auto_promote_if_healthy") is not False or
            (budget["trials"], budget["seconds"], budget["max_faults_per_trial"],
             budget["trial_timeout_seconds"]) != (1, 900, 1, 600) or
            "-Dtest=TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite*"
            not in config.get("command", []) or
            config.get("healthy_gate", {}).get("required_junit_tests") != 2 or
            config.get("healthy_gate", {}).get("minimum_healthy_observed_path_doors") != 1 or
            config.get("healthy_gate", {}).get("require_nonempty_observed_graph_path") is not True or
            config.get("cwd") != str(REMOTE_SOURCE) or
            config.get("site_file") != str(HERE / "HDFS-14.sites.json") or
            config.get("agent_jar") != str(RELEASE / "mallory-agent.jar") or
            config.get("agent_properties", {}).get("adapter.jar") != str(RELEASE / "mallory-hdfs-adapter.jar") or
            config.get("core_release") != str(CORE) or
            config.get("allow_local_timeline_doors") is not False or
            config.get("reject_coarse_roots") is not True or
            config.get("require_event_time_paths") is not True):
        raise RuntimeError("not the isolated HDFS-14 healthy config")

    require_hash(CORE / "manifest.json", CORE_MANIFEST_SHA)
    require_hash(RELEASE / "manifest.json", RELEASE_MANIFEST_SHA)
    core_manifest = json.loads((CORE / "manifest.json").read_text())
    for name, expected in core_manifest["files"].items():
        require_hash(CORE / name, expected)
    release_manifest = json.loads((RELEASE / "manifest.json").read_text())
    require_hash(RELEASE / "mallory-agent.jar", release_manifest["agent_sha256"])
    require_hash(RELEASE / "mallory-hdfs-adapter.jar", release_manifest["adapter_sha256"])
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if args.static and path.is_relative_to(REMOTE_SOURCE):
            path = LOCAL_SOURCE / path.relative_to(REMOTE_SOURCE)
        require_hash(path, artifact["sha256"])

    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if pinned["digest"] != SOURCE_DIGEST or source_digest(source, pinned) != SOURCE_DIGEST:
        raise RuntimeError(f"HDFS source fingerprint changed: {source}")

    if not args.static:
        if OUTPUT.exists():
            require_hash(OUTPUT / "config.json", sha(CONFIG))
            if not (OUTPUT / "checkpoint.json").is_file():
                raise RuntimeError("existing output has no resumable checkpoint")
        free = shutil.disk_usage(BASE).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(f"node2 disk below campaign reserve: {free}")

    print(json.dumps({"status": "static_preflight_pass" if args.static else "preflight_pass",
                      "case_id": "HDFS-14", "config_sha256": sha(CONFIG),
                      "site_sha256": sha(HERE / "HDFS-14.sites.json"),
                      "source_digest": SOURCE_DIGEST, "source_root": str(source),
                      "output": str(OUTPUT)}, sort_keys=True))


if __name__ == "__main__":
    main()
