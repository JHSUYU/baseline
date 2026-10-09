#!/usr/bin/env python3
"""Pinned, resumable preflight for the HDFS-24 v3 full campaign on node2."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil


BASE = Path("/users/ZhenyuLi/baseline")
HERE = BASE / "Mallory/adapters/hdfs/cases/io-version-retry-v3-owner-binding"
CONFIG = HERE / "HDFS-24-v3-full.json"
OUTPUT = Path("/tmp/mallory-hdfs24-v3-full")
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
RELEASE = BASE / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
CONFIG_SHA = "f8cf3c0f58559f66c52d1b734534f0438d8046acc8f2b1c0031c3f5ec0331884"
RELEASE_SHA = "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
SOURCE_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
MANIFEST_SHA = "0af9e3ba5240bda3f0e875eea130e0c7cfa658b8f51b7ef909cc0c6a253c18e2"
PILOT_RECEIPT_SHA = "e05bc0537a7a96a4918c3100688ad7588100bd81c0619ae41c8898752138876b"
MIN_FREE_BYTES = 5_500_000_000


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require_hash(path: Path, expected: str) -> None:
    if not path.is_file() or sha(path) != expected:
        raise RuntimeError(f"missing or changed artifact: {path}")


def source_digest(reference: dict) -> str:
    h = hashlib.sha256()
    for relative in reference["paths"]:
        path = SOURCE / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"source file missing: {path}")
        h.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return h.hexdigest()


def main() -> None:
    require_hash(CONFIG, CONFIG_SHA)
    config = json.loads(CONFIG.read_text())
    budget = config["budget"]
    if (config.get("case_id") != "HDFS-24" or config.get("calibration_only") or
            not config.get("auto_promote_if_healthy") or
            (budget["trials"], budget["seconds"], budget["max_faults_per_trial"]) !=
            (80, 3600, 3) or config.get("reject_coarse_roots") is not True or
            config.get("require_event_time_paths") is not True):
        raise RuntimeError("not the strict HDFS-24 v3 full configuration")
    if config["cwd"] != str(SOURCE) or config["source_equivalent_root"] != str(SOURCE):
        raise RuntimeError("HDFS source root changed")
    require_hash(RELEASE / "manifest.json", RELEASE_SHA)
    for name, expected in json.loads((RELEASE / "manifest.json").read_text())["files"].items():
        require_hash(RELEASE / name, expected)
    for row in config["runtime_artifacts"]:
        require_hash(Path(row["path"]), row["sha256"])
    require_hash(BASE / "data/mallory/pilots/HDFS-24-v3-exact-retry/archive-manifest.json", MANIFEST_SHA)
    require_hash(HERE / "HDFS-24-v3-pilot-receipt.json", PILOT_RECEIPT_SHA)
    reference = json.loads((BASE / "Mallory/dispatch/source_reference.json").read_text())
    pinned = reference["roots"]["/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"]
    if pinned["digest"] != SOURCE_DIGEST or source_digest(pinned) != SOURCE_DIGEST:
        raise RuntimeError("full tracked HDFS source fingerprint changed")
    if OUTPUT.exists():
        existing = OUTPUT / "config.json"
        require_hash(existing, CONFIG_SHA)
        if not (OUTPUT / "checkpoint.json").is_file():
            raise RuntimeError("existing output has no resumable checkpoint")
    free = shutil.disk_usage(BASE).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError(f"disk reserve below {MIN_FREE_BYTES}: {free}")
    print(json.dumps({"status": "preflight_pass", "case_id": "HDFS-24",
                      "config_sha256": CONFIG_SHA, "source_digest": SOURCE_DIGEST,
                      "free_disk_bytes": free, "output": str(OUTPUT),
                      "resuming": OUTPUT.exists()}, sort_keys=True))


if __name__ == "__main__":
    main()
