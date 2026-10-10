#!/usr/bin/env python3
"""Prepare an isolated, pinned HDFS test tree after dispatch admits node2."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket

from source_identity import verify_original


HERE = Path(__file__).resolve().parent
SOURCE = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-identity-v8")
DEST = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs48-rename-presend-v4")
TEST_SOURCE = Path("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/"
                   "hdfs/server/namenode/snapshot/TestRenameWithSnapshots.java")
TEST_CLASS = Path("hadoop-hdfs-project/hadoop-hdfs/target/test-classes/org/apache/"
                  "hadoop/hdfs/server/namenode/snapshot/TestRenameWithSnapshots.class")
TARGET_CLASS = Path("hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/"
                    "hadoop/hdfs/server/namenode/INodeDirectory.class")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path, receipt: dict) -> None:
    for relative, expected in ((TEST_SOURCE, receipt["patched_test_source_sha256"]),
                               (TEST_CLASS, receipt["patched_test_class_sha256"]),
                               (TARGET_CLASS, receipt["target_class_sha256"])):
        if not (root / relative).is_file() or sha(root / relative) != expected:
            raise RuntimeError(f"source/class identity mismatch: {root / relative}")
    marker = root / ".mallory-hdfs48-v4-source-receipt.json"
    expected = {"source_full_digest_sha256": receipt["source_full_digest_sha256"],
                "source_reference_sha256": receipt["source_reference_sha256"],
                "original_test_source_sha256": receipt["original_test_source_sha256"],
                "patched_test_class_sha256": receipt["patched_test_class_sha256"]}
    if not marker.is_file() or json.loads(marker.read_text()) != expected:
        raise RuntimeError(f"isolated source receipt missing or changed: {marker}")


def main() -> None:
    if os.environ.get("MALLORY_DISPATCH_ADMITTED") != "1" or socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("node2 dispatch GO is required before source preparation")
    receipt = json.loads((HERE / "build-receipt.json").read_text())
    if DEST.exists():
        verify(DEST, receipt)
        print("isolated HDFS-48 source already prepared and pinned")
        return
    verify_original(SOURCE, receipt)
    for name, key in (("TestRenameWithSnapshots.class", "patched_test_class_sha256"),
                      ("mallory-hdfs-adapter.jar", "adapter_jar_sha256")):
        if sha(HERE / "release" / name) != receipt[key]:
            raise RuntimeError(f"case-local release changed: {name}")
    if sha(HERE / "patched-test" / TEST_SOURCE.name) != receipt["patched_test_source_sha256"]:
        raise RuntimeError("patched test source changed")
    required = sum(p.stat().st_size for p in SOURCE.rglob("*") if p.is_file()) + 3_000_000_000
    if shutil.disk_usage(DEST.parent).free < required:
        raise RuntimeError("node2 lacks reserved space for isolated source copy")
    temporary = DEST.with_name(DEST.name + f".partial-{os.getpid()}")
    if temporary.exists():
        raise RuntimeError(f"stale partial source needs manual review: {temporary}")
    shutil.copytree(SOURCE, temporary, symlinks=True,
                    ignore=shutil.ignore_patterns(".git"))
    shutil.copy2(HERE / "patched-test" / TEST_SOURCE.name, temporary / TEST_SOURCE)
    shutil.copy2(HERE / "release" / TEST_SOURCE.with_suffix(".class").name,
                 temporary / TEST_CLASS)
    marker = {"source_full_digest_sha256": receipt["source_full_digest_sha256"],
              "source_reference_sha256": receipt["source_reference_sha256"],
              "original_test_source_sha256": receipt["original_test_source_sha256"],
              "patched_test_class_sha256": receipt["patched_test_class_sha256"]}
    (temporary / ".mallory-hdfs48-v4-source-receipt.json").write_text(
        json.dumps(marker, indent=2, sort_keys=True) + "\n")
    verify(temporary, receipt)
    temporary.rename(DEST)
    print(f"prepared pinned isolated HDFS-48 source: {DEST}")


if __name__ == "__main__":
    main()
