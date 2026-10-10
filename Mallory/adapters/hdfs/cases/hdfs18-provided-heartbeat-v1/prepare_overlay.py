#!/usr/bin/env python3
"""Check or apply the HDFS-18 test-only real-heartbeat adaptation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

BASE = Path("/users/ZhenyuLi/baseline")
HERE = BASE / "Mallory/adapters/hdfs/cases/hdfs18-provided-heartbeat-v1"
RELATIVE = Path("hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/aliasmap/TestSecureAliasMap.java")
ORIGINAL = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3") / RELATIVE
DEDICATED_ROOT = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs18-provided-heartbeat-v1")
IMPORT_ANCHOR = "import org.apache.hadoop.hdfs.server.blockmanagement.BlockManager;\n"
IMPORT_REPLACEMENT = (IMPORT_ANCHOR +
                      "import org.apache.hadoop.hdfs.server.blockmanagement.DatanodeDescriptor;\n")
BODY_ANCHOR = "    DataNode dn = cluster.getDataNodes().get(0);\n\n"
BODY_REPLACEMENT = '''    DataNode dn = cluster.getDataNodes().get(0);

    if (Boolean.getBoolean("mallory.hdfs18.secondProvidedHeartbeat")) {
      DatanodeDescriptor descriptor = blockManager.getDatanodeManager()
          .getDatanode(dn.getDatanodeId());
      assertNotNull("Missing registered DataNode", descriptor);
      assertNotNull("Missing first PROVIDED storage insertion",
          descriptor.getStorageInfo(DFSConfigKeys.DFS_PROVIDER_STORAGEUUID_DEFAULT));
      final long previousHeartbeat = descriptor.getLastUpdateMonotonic();
      Thread.sleep(10);
      cluster.triggerHeartbeats();
      GenericTestUtils.waitFor(
          () -> descriptor.getLastUpdateMonotonic() > previousHeartbeat,
          10, 30000);
      System.out.println("MALLORY_HDFS18_REAL_PROVIDED_HEARTBEAT_COMPLETE "
          + dn.getDatanodeUuid());
    }

'''


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render(source: bytes, receipt: dict) -> bytes:
    if sha(source) != receipt["original_source_sha256"]:
        raise RuntimeError("original TestSecureAliasMap source SHA changed")
    value = source.decode()
    for anchor, replacement in ((IMPORT_ANCHOR, IMPORT_REPLACEMENT),
                                (BODY_ANCHOR, BODY_REPLACEMENT)):
        if value.count(anchor) != 1:
            raise RuntimeError("adaptation anchor is not unique")
        value = value.replace(anchor, replacement)
    patched = value.encode()
    if sha(patched) != receipt["patched_source_sha256"]:
        raise RuntimeError("patched TestSecureAliasMap SHA changed")
    return patched


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write only to the prepared dedicated source root")
    args = parser.parse_args()
    receipt = json.loads((HERE / "source-overlay-receipt.json").read_text())
    if sha((HERE / "real-heartbeat.patch").read_bytes()) != receipt["patch_sha256"]:
        raise RuntimeError("patch SHA changed")
    patched = render(ORIGINAL.read_bytes(), receipt)
    if args.apply:
        destination = DEDICATED_ROOT / RELATIVE
        if not destination.is_file():
            raise RuntimeError("dedicated source root must be prepared first")
        before = destination.read_bytes()
        if sha(before) == receipt["patched_source_sha256"]:
            print("already_applied", destination)
            return
        if sha(before) != receipt["original_source_sha256"]:
            raise RuntimeError("dedicated source file is not pristine")
        destination.write_bytes(patched)
        if sha(destination.read_bytes()) != receipt["patched_source_sha256"]:
            raise RuntimeError("written source hash mismatch")
        print("applied", destination)
    else:
        print(json.dumps({"status": "patch_preflight_pass", "jvm_started": False,
                          "original_sha256": receipt["original_source_sha256"],
                          "patched_sha256": receipt["patched_source_sha256"]},
                         sort_keys=True))


if __name__ == "__main__":
    main()
