#!/usr/bin/env python3
"""Read-only HDFS-29 source/JUnit admission and fault-model gap check."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))

from Mallory.core.campaign import validate_config
from Mallory.dispatch.scheduler import verify_runtime_artifacts


HDFS = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2/hadoop-hdfs-project/hadoop-hdfs")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    receipt = json.loads((HERE / "source-receipt.json").read_text())
    config = json.loads((HERE / "HDFS-29-healthy-only.json").read_text())
    sites = json.loads((HERE / "HDFS-29.sites.json").read_text())
    assert receipt["source_commit"] == subprocess.run(
        ["git", "-C", str(HDFS.parents[1]), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True).stdout.strip()
    for record in receipt["artifacts"]:
        path = Path(record["path"])
        assert path.is_file() and sha(path) == record["sha256"], path
    validate_config(config)
    verify_runtime_artifacts(config)
    assert config["case_id"] == "HDFS-29"
    assert config["cluster_test"] == (
        "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover"
        "#testLeaseRecoveryAfterFailover")
    assert config["calibration_only"] is True
    assert config["auto_promote_if_healthy"] is False
    assert config["mapping"]["healthy_seed_verified"] is False
    assert config["mapping"]["fault_retains_target_verified"] is False
    assert config["mapping"]["verified_healthy_probe"] is None
    assert config["mapping"]["node_identity_binding_verified"] is False
    assert config["mapping"]["status"] == "diagnostic_healthy_only_fault_model_gap"
    assert config["agent_properties"]["auto.io.doors"] is False
    assert config["reject_coarse_roots"] and config["require_event_time_paths"]
    assert not config["healthy_gate"]["allow_local_timeline_doors"]
    assert config["healthy_gate"]["require_target_exception_absent"]
    assert len(sites["doors"]) == 1
    door = sites["doors"][0]
    assert door["clazz"] == "org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker"
    assert door["method"] == "callInitReplicaRecovery" and door["line"] == 561
    assert door["callee"].startswith(
        "org.apache.hadoop.hdfs.server.protocol.InterDatanodeProtocol#initReplicaRecovery(")
    assert door["exception_class"] == "java.io.IOException"
    assert config["target"]["check_sites"][0].endswith("@577:branch:1")
    assert config["target"]["throw_site"].endswith("@578:throw:1")

    source = (HDFS / "src/main/java/org/apache/hadoop/hdfs/server/datanode/"
              "BlockRecoveryWorker.java").read_text()
    recovery = source[source.index("protected void recover() throws IOException"):
                      source.index("/** Block synchronization. */")]
    assert recovery.index("getDatanodeID(bpid)") < recovery.index(
        "callInitReplicaRecovery(proxyDN, rBlock)")
    assert recovery.index("callInitReplicaRecovery(proxyDN, rBlock)") < recovery.index(
        "catch (IOException e)") < recovery.index("syncBlock(syncList)")
    assert "if (errorCount == locs.length)" in recovery
    assert "if (bpos == null)" in source[source.index("getActiveNamenodeForBP("):
                                            source.index("public Daemon recoverBlocks(")]
    assert "if (bpos == null)" in source[source.index("private DatanodeID getDatanodeID("):
                                            source.index("private static void logRecoverBlock(")]
    test = (HDFS / "src/test/java/org/apache/hadoop/hdfs/server/namenode/ha/"
            "TestPipelinesFailover.java").read_text()
    selected = test[test.index("void testLeaseRecoveryAfterFailover()"):
                    test.index("void testFailoverRightBeforeCommitSynchronization()")]
    assert "newMiniCluster(conf, 3)" in selected
    assert "cluster.transitionToActive(1)" in selected
    assert "loopRecoverLease(fsOtherUser, TEST_PATH)" in selected
    assert "DelayAnswer" not in selected
    subprocess.run([sys.executable, "-B", str(HERE / "verify_bytecode.py")],
                   check=True, capture_output=True, text=True)
    print("HDFS-29 diagnostic source/JUnit, bytecode, config, and SHA preflight: PASS")


if __name__ == "__main__":
    main()
