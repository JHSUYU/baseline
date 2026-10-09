#!/usr/bin/env python3
"""Pin the single HDFS-26 MiniDFSCluster healthy calibration on node2."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


BASE = Path("/users/ZhenyuLi/baseline")
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs26-retry-io-admission-v2"
CONFIG = HERE / "HDFS-26-node2-healthy-only.json"
OUTPUT = Path("/tmp/mallory-hdfs26-v2-healthy")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG_SHA = "1268ee8a8685a6720c8a113322bffb375254c1db5c7866cc83cb01686096cd9b"
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


def source_digest(reference: dict) -> str:
    digest = hashlib.sha256()
    for relative in reference["paths"]:
        path = SOURCE / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"source file missing: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def main() -> None:
    require_hash(CONFIG, CONFIG_SHA)
    config = json.loads(CONFIG.read_text())
    sys.path.insert(0, str(RELEASE))
    sys.path.insert(1, str(BASE))
    from Mallory.core.campaign import load_static_frontier, validate_config

    validate_config(config)
    load_static_frontier(config)
    if (config.get("case_id") != "HDFS-26" or
            config.get("calibration_only") is not True or
            config.get("auto_promote_if_healthy") is not False or
            config.get("cluster_test") != "org.apache.hadoop.hdfs.TestDFSRollback#testRollback" or
            config.get("cwd") != str(SOURCE) or
            config.get("source_equivalent_root") != str(SOURCE) or
            config.get("budget", {}).get("trials") != 1 or
            config.get("budget", {}).get("max_faults_per_trial") != 1 or
            config.get("mapping", {}).get("status") !=
            "source_and_bytecode_attested_pending_fresh_healthy"):
        raise RuntimeError("not the exact bounded HDFS-26 healthy config")
    if OUTPUT.exists():
        raise RuntimeError(f"healthy output already exists: {OUTPUT}")
    require_hash(RELEASE / "manifest.json", RELEASE_MANIFEST_SHA)
    for name, expected in json.loads((RELEASE / "manifest.json").read_text())["files"].items():
        require_hash(RELEASE / name, expected)
    for artifact in config["runtime_artifacts"]:
        require_hash(Path(artifact["path"]), artifact["sha256"])
    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if pinned["digest"] != SOURCE_DIGEST or source_digest(pinned) != SOURCE_DIGEST:
        raise RuntimeError("full HDFS source fingerprint changed")
    free = shutil.disk_usage(BASE).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError(f"node2 disk below healthy reserve: {free}")
    print(json.dumps({"status": "preflight_pass", "case_id": "HDFS-26",
                      "config_sha256": CONFIG_SHA, "source_digest": SOURCE_DIGEST,
                      "output": str(OUTPUT), "free_disk_bytes": free}, sort_keys=True))


if __name__ == "__main__":
    main()
