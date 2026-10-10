#!/usr/bin/env python3
"""Verify or apply the HDFS-37 test-only normal-phase extraction."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BASE = Path("/users/ZhenyuLi/baseline")
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs37-normal-phase-v2"
RELATIVE = Path("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestDFSRollback.java")
ORIGINAL = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3") / RELATIVE
DEDICATED_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs37-normal-v2")
BEFORE = '''      cluster.shutdown();
      UpgradeUtilities.createEmptyDirs(nameNodeDirs);
      UpgradeUtilities.createEmptyDirs(dataNodeDirs);
      
      log("Normal BlockPool rollback", numDirs);'''
AFTER = '''      cluster.shutdown();
      UpgradeUtilities.createEmptyDirs(nameNodeDirs);
      UpgradeUtilities.createEmptyDirs(dataNodeDirs);
      if (Boolean.getBoolean("mallory.hdfs37.normalDataNodeRollbackOnly")) {
        LOG.info("MALLORY_HDFS37_NORMAL_DATANODE_ROLLBACK_COMPLETE numDirs={}", numDirs);
        return;
      }
      
      log("Normal BlockPool rollback", numDirs);'''


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render(source: bytes, receipt: dict) -> bytes:
    if sha(source) != receipt["original_source_sha256"]:
        raise RuntimeError("original TestDFSRollback source SHA changed")
    text = source.decode()
    if text.count(BEFORE) != 1:
        raise RuntimeError("normal DataNode rollback phase anchor is not unique")
    patched = text.replace(BEFORE, AFTER).encode()
    if sha(patched) != receipt["patched_source_sha256"]:
        raise RuntimeError("patched test source SHA changed")
    return patched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write only to the dedicated HDFS-37 source root")
    args = parser.parse_args()
    receipt = json.loads((HERE / "source-overlay-receipt.json").read_text())
    if sha((HERE / "normal-phase.patch").read_bytes()) != receipt["patch_sha256"]:
        raise RuntimeError("patch SHA changed")
    patched = render(ORIGINAL.read_bytes(), receipt)
    if args.apply:
        destination = DEDICATED_ROOT / RELATIVE
        if not destination.is_file():
            raise RuntimeError("dedicated worktree and original source must be prepared first")
        before = destination.read_bytes()
        if sha(before) == receipt["patched_source_sha256"]:
            print("already_applied", destination)
            return
        if sha(before) != receipt["original_source_sha256"]:
            raise RuntimeError("dedicated worktree test file is not pristine")
        destination.write_bytes(patched)
        if sha(destination.read_bytes()) != receipt["patched_source_sha256"]:
            raise RuntimeError("written test source hash mismatch")
        print("applied", destination)
    else:
        print(json.dumps({"status": "patch_preflight_pass",
                          "original_sha256": receipt["original_source_sha256"],
                          "patched_sha256": receipt["patched_source_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
