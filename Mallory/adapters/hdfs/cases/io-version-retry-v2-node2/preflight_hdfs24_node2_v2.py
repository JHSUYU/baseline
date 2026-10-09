#!/usr/bin/env python3
"""Read-only provenance and resource check for one HDFS-24 node2 healthy run."""

import hashlib
import json
import os
from pathlib import Path
import shutil


ROOT = Path("/users/ZhenyuLi/baseline")
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
HERE = ROOT / "Mallory/adapters/hdfs/cases/io-version-retry-v2-node2"
CONFIG = HERE / "HDFS-24-healthy-only-node2-v2.json"
OUT = ROOT / "data/mallory/calibration_io_version_retry_v2_node2/HDFS-24"
REFERENCE = ROOT / "Mallory/dispatch/source_reference.json"
RELEASE = ROOT / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
ORIGINAL = "/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"
EXPECTED_SOURCE = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
EXPECTED_CONFIG = "26bad317f404fb4a98ac816fc2c5c46f6c7e1861f8ade65fa9b33ea794e8390a"
EXPECTED_RELEASE_MANIFEST = "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"
MIN_FREE_BYTES = 7_000_000_000


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_hash(path, expected):
    path = Path(path)
    if not path.is_file() or sha256(path) != expected:
        raise RuntimeError("missing or changed artifact: " + str(path))


def source_fingerprint(paths):
    result = hashlib.sha256()
    for relative in paths:
        path = SOURCE / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha256(path))
        else:
            raise RuntimeError("source file missing: " + str(path))
        result.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return result.hexdigest()


def main():
    require_hash(CONFIG, EXPECTED_CONFIG)
    config = json.loads(CONFIG.read_text())
    if config["case_id"] != "HDFS-24" or not config.get("calibration_only") or config.get("auto_promote_if_healthy"):
        raise RuntimeError("not the HDFS-24 healthy-only configuration")
    if config["cwd"] != str(SOURCE) or config["source_equivalent_root"] != str(SOURCE):
        raise RuntimeError("HDFS source root changed")
    if config["budget"]["trials"] != 1 or config["budget"]["max_faults_per_trial"] != 1:
        raise RuntimeError("healthy-only budget changed")
    for artifact in config["runtime_artifacts"]:
        require_hash(artifact["path"], artifact["sha256"])
    require_hash(RELEASE / "manifest.json", EXPECTED_RELEASE_MANIFEST)
    for relative, expected in json.loads((RELEASE / "manifest.json").read_text())["files"].items():
        require_hash(RELEASE / relative, expected)
    reference = json.loads(REFERENCE.read_text())["roots"][ORIGINAL]
    if reference["digest"] != EXPECTED_SOURCE or source_fingerprint(reference["paths"]) != EXPECTED_SOURCE:
        raise RuntimeError("full tracked HDFS source fingerprint changed")
    if OUT.exists():
        raise RuntimeError("healthy output path is not fresh: " + str(OUT))
    free = shutil.disk_usage(ROOT).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError("disk reserve below 7 GB: " + str(free))
    print(json.dumps({"status": "preflight_pass", "case_id": "HDFS-24",
                      "config_sha256": EXPECTED_CONFIG, "source_digest": EXPECTED_SOURCE,
                      "free_disk_bytes": free, "output": str(OUT)}, sort_keys=True))


if __name__ == "__main__":
    main()
