"""Bytewise Hadoop identity, independent of local Git metadata."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
REFERENCE = BASE / "Mallory/dispatch/source_reference.json"
REFERENCE_ROOT = "/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3"
ORIGINAL_COMMIT = "9d50c6884666e794e45102260a4017bb31802e1b"
FULL_DIGEST = "825878fdb546b98f0c1c17339d83625e62fa0aadd5b76284a2640fac3926bef7"
REFERENCE_SHA = "e600ce9827adc7fdc9baf8cef1fca70bfcb616f39310a7053a50feab0d0b613d"
SELECTED = {
    "original_test_source_sha256": "hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/namenode/snapshot/TestRenameWithSnapshots.java",
    "original_test_class_sha256": "hadoop-hdfs-project/hadoop-hdfs/target/test-classes/org/apache/hadoop/hdfs/server/namenode/snapshot/TestRenameWithSnapshots.class",
    "target_source_sha256": "hadoop-hdfs-project/hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/INodeDirectory.java",
    "target_class_sha256": "hadoop-hdfs-project/hadoop-hdfs/target/classes/org/apache/hadoop/hdfs/server/namenode/INodeDirectory.class",
    "client_source_sha256": "hadoop-common-project/hadoop-common/src/main/java/org/apache/hadoop/ipc/Client.java",
    "client_class_sha256": "hadoop-common-project/hadoop-common/target/classes/org/apache/hadoop/ipc/Client.class",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def full_source_digest(root: Path) -> str:
    if sha(REFERENCE) != REFERENCE_SHA:
        raise RuntimeError("established full-source reference changed")
    reference = json.loads(REFERENCE.read_text())["roots"][REFERENCE_ROOT]
    if (reference["commit"] != ORIGINAL_COMMIT or reference["digest"] != FULL_DIGEST or
            reference["files"] != len(reference["paths"])):
        raise RuntimeError("established Hadoop source reference identity changed")
    digest = hashlib.sha256()
    for relative in reference["paths"]:
        path = root / relative
        if path.is_symlink():
            payload = b"L" + os.fsencode(os.readlink(path))
        elif path.is_file():
            payload = b"F" + bytes.fromhex(sha(path))
        else:
            raise RuntimeError(f"missing referenced source path: {path}")
        digest.update(os.fsencode(relative) + b"\0" + payload + b"\0")
    return digest.hexdigest()


def verify_original(root: Path, receipt: dict) -> None:
    if not root.is_dir() or receipt.get("source_full_digest_sha256") != FULL_DIGEST or \
            receipt.get("source_reference_sha256") != REFERENCE_SHA:
        raise RuntimeError("original source receipt mismatch")
    for key, relative in SELECTED.items():
        path = root / relative
        if not path.is_file() or sha(path) != receipt[key]:
            raise RuntimeError(f"selected Hadoop source/class changed: {path}")
    if full_source_digest(root) != FULL_DIGEST:
        raise RuntimeError(f"full Hadoop source digest differs: {root}")
