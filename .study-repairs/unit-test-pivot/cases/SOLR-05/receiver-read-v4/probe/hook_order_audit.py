#!/usr/bin/env python3
"""Verify V4 overlays hook the intended original operations in the right order."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

CASE = Path(__file__).resolve().parents[1]
SOURCE = CASE.parent / "solr-source"
OUT = CASE / "generated"
CHECKS = {
    "solr/core/src/java/org/apache/solr/cloud/overseer/ZkStateWriter.java": (
        "FeedbackProbe.upstreamWrite(this",
        "Stat stat = reader.getZkClient().setData(path, data, c.getZNodeVersion(), true);",
        "FeedbackProbe.upstreamWriteDone(this",
        "stat.getVersion());"),
    "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java": (
        "byte[] data = zkClient.getData(collectionPath, watcher, stat, true);",
        "ClusterState state = ClusterState.load (stat.getVersion(), data,",
        "DocCollection loaded = collectionRef == null ? null : collectionRef.get();",
        "FeedbackProbe.receiverRead(zkClient, this, coll, collectionPath, stat.getVersion(), loaded);",
        "return loaded;"),
    "solr/core/src/java/org/apache/solr/cloud/ZkController.java": (
        "FeedbackProbe.targetCheck(replica == null",
        "if (replica == null) {"),
    "solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java": (
        "FeedbackProbe.io(\"GET_DATA\", path, this);",
        "return zkCmdExecutor.retryOperation(() -> keeper.getData(path, wrapWatcher(watcher), stat));"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    evidence = []
    for relative, markers in CHECKS.items():
        original, overlay = SOURCE / relative, OUT / relative
        plain, changed = original.read_text(), overlay.read_text()
        offsets = [changed.find(marker) for marker in markers]
        if any(offset < 0 for offset in offsets) or offsets != sorted(offsets):
            raise AssertionError(f"hook order or marker missing: {relative}: {offsets}")
        if "baseline.solr05v4.FeedbackProbe" in plain:
            raise AssertionError(f"original source changed: {relative}")
        evidence.append({"source": relative, "original_sha256": sha(original),
                         "overlay_sha256": sha(overlay), "marker_offsets": offsets})
    original_test = CASE / "classes-original/org/apache/solr/cloud/AddReplicaTest.class"
    instrumented_test = CASE / "classes/org/apache/solr/cloud/AddReplicaTest.class"
    if sha(original_test) != sha(instrumented_test):
        raise AssertionError("original JUnit bytecode differs")
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                            cwd=SOURCE, text=True).strip()
    result = {"source_commit": source_commit, "test":
              "AddReplicaTest.testAddMultipleReplicas",
              "unchanged_original_junit_sha256": sha(original_test),
              "hook_order_pass": True, "overlays": evidence}
    destination = CASE / "evidence/hook-order-audit.json"
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"hook_order_pass": True, "source_commit": source_commit,
                      "overlays": len(evidence)}))


if __name__ == "__main__":
    main()
