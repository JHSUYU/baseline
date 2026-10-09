#!/usr/bin/env python3
"""Pin the single-fault HDFS-12 node2 diagnostic before JVM launch."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys


BASE = Path("/users/ZhenyuLi/baseline")
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs12-key-update-v2"
CONFIG = HERE / "HDFS-12-v2-one-fault-pilot.json"
OUTPUT = Path("/tmp/mallory-hdfs12-key-update-v2-pilot")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG_SHA = "95aabb9d975a3918fecac5367f1ca943de5c10e05a2048920906f379f43b8c1f"
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
    if (config.get("case_id") != "HDFS-12" or config.get("calibration_only") or
            config.get("auto_promote_if_healthy") is not True or
            config.get("cluster_test") !=
            "org.apache.hadoop.hdfs.TestEncryptedTransfer#testLongLivedClient[0]" or
            config.get("cwd") != str(SOURCE) or
            config.get("source_equivalent_root") != str(SOURCE) or
            config.get("budget", {}).get("trials") != 1 or
            config.get("budget", {}).get("max_faults_per_trial") != 1 or
            config.get("explore_outside_closure") is not False or
            config.get("target", {}).get("nodes") != ["hdfs-cluster-2/dn0"] or
            config.get("mapping", {}).get("status") !=
            "runtime_attested_bounded_pilot_only"):
        raise RuntimeError("not the exact one-fault HDFS-12 pilot config")
    if OUTPUT.exists():
        raise RuntimeError(f"pilot output already exists: {OUTPUT}")
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
        raise RuntimeError(f"node2 disk below pilot reserve: {free}")
    print(json.dumps({"status": "preflight_pass", "case_id": "HDFS-12",
                      "config_sha256": CONFIG_SHA, "source_digest": SOURCE_DIGEST,
                      "output": str(OUTPUT), "free_disk_bytes": free}, sort_keys=True))


if __name__ == "__main__":
    main()
