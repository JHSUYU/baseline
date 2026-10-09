"""Read-only node2 admission checks for one HDFS-29 healthy JUnit seed."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[5]
CONFIG = Path(__file__).with_name("HDFS-29-lease-recovery-healthy-v16-node2.json")
OUTPUT = REPO / "data/mallory/calibration_v16_node2/HDFS-29"
LOCK = Path("/tmp/mallory-lanes/hdfs-identity-v8-node2.lock")
MIN_FREE_BYTES = 6 * 1024**3


def digest(path: Path) -> str:
    state = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            state.update(chunk)
    return state.hexdigest()


def main() -> int:
    errors: list[str] = []
    checks: dict[str, object] = {}
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    mapping = config["mapping"]
    source = Path(config["cwd"])
    checks["host"] = socket.gethostname()
    checks["config_sha256"] = digest(CONFIG)
    checks["output_fresh"] = not OUTPUT.exists()
    if OUTPUT.exists():
        errors.append("HDFS-29 node2 output already exists")
    checks["source_tree_exists"] = source.is_dir()
    if not source.is_dir():
        errors.append("pinned node2 source copy missing")
    git_head = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    checks["source_git_head"] = git_head.stdout.strip() if git_head.returncode == 0 else None
    checks["source_commit_verification"] = (
        "git_head_and_content_hashes" if git_head.returncode == 0
        else "content_hashes_only_incomplete_git_metadata"
    )

    pinned = {
        "agent": (Path(config["agent_jar"]), mapping["agent_sha256"]),
        "adapter": (Path(config["agent_properties"]["adapter.jar"]),
                    mapping["adapter_sha256"]),
        "site_catalog": (Path(config["site_file"]),
                         next(item["sha256"] for item in config["runtime_artifacts"]
                              if item["path"] == config["site_file"])),
        "target_source": (
            source / mapping["target_source_path"] if "target_source_path" in mapping else
            source / config["target"]["source_path"],
            mapping["target_source_sha256"]),
        "test_source": (
            source / "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/ha/TestPipelinesFailover.java",
            mapping["test_source_sha256"]),
        "target_class": (
            source / "hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.class",
            mapping["compiled_class_sha256"]),
        "test_class": (
            source / "hadoop-hdfs-project/hadoop-hdfs/target/test-classes/org/apache/hadoop/hdfs/server/namenode/ha/TestPipelinesFailover.class",
            config["source_equivalence"]["compiled_test_class_sha256"]),
        "distribution_jar": (Path(mapping["compiled_jar"]),
                             mapping["compiled_jar_sha256"]),
        "core_release_manifest": (
            REPO / "Mallory/dispatch/releases" / mapping["core_release_id"] / "manifest.json",
            mapping["core_release_manifest_sha256"]),
    }
    artifact_checks: dict[str, object] = {}
    for name, (path, expected) in pinned.items():
        actual = digest(path) if path.is_file() else None
        artifact_checks[name] = {"path": str(path), "expected_sha256": expected,
                                 "actual_sha256": actual, "match": actual == expected}
        if actual != expected:
            errors.append(f"{name} missing or SHA-256 mismatch")
    checks["artifacts"] = artifact_checks

    disk = os.statvfs(REPO)
    available = disk.f_bavail * disk.f_frsize
    checks["free_bytes"] = available
    checks["minimum_free_bytes"] = MIN_FREE_BYTES
    if available <= MIN_FREE_BYTES:
        errors.append("node2 disk below 6 GiB launch reserve")
    try:
        with LOCK.open("rb") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            checks["hdfs_source_lock_free"] = True
            fcntl.flock(handle, fcntl.LOCK_UN)
    except (FileNotFoundError, BlockingIOError):
        checks["hdfs_source_lock_free"] = False
        errors.append("node2 HDFS source lock absent or held")

    checks["admitted_by_local_gate"] = not errors
    checks["errors"] = errors
    print(json.dumps(checks, indent=2, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
