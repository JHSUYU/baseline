#!/usr/bin/env python3
"""Read-only source and class-image guard for the isolated heartbeat overlay."""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASELINE = HERE.parents[4]
HDFS = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3/") \
    / "hadoop-hdfs-project/hadoop-hdfs"
CLASSES = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs/") \
    / "hadoop-hdfs-project/hadoop-hdfs/target/classes"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    receipt = json.loads((HERE / "preflight.json").read_text())
    roots = {
        "adapter_base": BASELINE / "Mallory/adapters/hdfs/src/main/java"
        / "edu/uva/liftlab/mallory/adapters/hdfs",
        "adapter_staged_overlay": HERE / "overlay",
        "hadoop_sources": HDFS / "src/main/java",
        "hadoop_compiled_classes": CLASSES,
        "test_sources": HDFS / "src/test/java",
        "site_files": BASELINE / "Mallory/cases",
    }
    for group, records in receipt["sha256"].items():
        if group == "adapter_release_jar":
            assert digest(HERE / "release/mallory-hdfs-adapter.jar") == records
            continue
        if group == "focused_test_source":
            assert digest(HERE / "tests/HdfsHeartbeatBridgeTest.java") == records
            continue
        if group == "focused_test_report":
            path = HERE / "release/HdfsHeartbeatBridgeTest.xml"
            assert digest(path) == records
            continue
        if group == "adapter_compiled_classes":
            directory = HERE / "release/compiled"
            for name, expected in records.items():
                assert digest(directory / name) == expected, name
            continue
        if group == "patch":
            assert digest(HERE / "hdfs19-20-heartbeat-bridge.patch") == records
            continue
        if group == "agent":
            path = Path(receipt["agent_path"])
            assert digest(path) == records, path
            continue
        for name, expected in records.items():
            path = roots[group] / (name + ".sites.json" if group == "site_files" else name)
            assert digest(path) == expected, path
    for cid, test in (
        ("HDFS-19", "org.apache.hadoop.hdfs.TestDFSFinalize#testFinalize"),
        ("HDFS-20", "org.apache.hadoop.hdfs.server.namenode.ha.TestStandbyIsHot#testStandbyIsHot"),
    ):
        case = json.loads((HERE / (cid + "-healthy.json")).read_text())
        assert case["cluster_test"] == test
        assert case["calibration_only"] and case["auto_promote_if_healthy"] is False
        assert {"org.apache.hadoop.hdfs.server.datanode.BPServiceActor$CommandProcessingThread",
                "org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB"} \
            <= set(case["agent_include"])
        assert case["target"]["source_line"] == (769 if cid == "HDFS-19" else 606)
    assert "return new FinalizeCommand(poolId);" in (
        HDFS / "src/main/java/org/apache/hadoop/hdfs/server/namenode/NameNodeRpcServer.java"
    ).read_text()
    assert "Runnable action = queue.take();" in (
        HDFS / "src/main/java/org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java"
    ).read_text()
    print("HDFS-19/20 source, compiled class, config, and overlay SHA preflight: PASS")


if __name__ == "__main__":
    main()
