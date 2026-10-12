"""Pin HDFS-29/30 source-only, fault-free calibration proposals.

This reads existing source and artifacts and writes only this directory. It
never starts Hadoop, Maven, a JVM, or a Mallory campaign.
"""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3")
BUILD = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-lane2")
COMPILED = BUILD / "hadoop-hdfs-project/hadoop-hdfs/target/classes"
TEST_CLASS = BUILD / ("hadoop-hdfs-project/hadoop-hdfs/target/test-classes/"
                      "org/apache/hadoop/hdfs/server/namenode/ha/TestPipelinesFailover.class")
TARGET_CLASS = COMPILED / "org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.class"
ACTOR_CLASS = COMPILED / "org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class"
TEST_SOURCE = SOURCE / ("hadoop-hdfs-project/hadoop-hdfs/src/test/java/"
                        "org/apache/hadoop/hdfs/server/namenode/ha/TestPipelinesFailover.java")
TARGET_SOURCE = SOURCE / ("hadoop-hdfs-project/hadoop-hdfs/src/main/java/"
                          "org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker.java")
ACTOR_SOURCE = SOURCE / ("hadoop-hdfs-project/hadoop-hdfs/src/main/java/"
                         "org/apache/hadoop/hdfs/server/datanode/BPServiceActor.java")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pin(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def prepare() -> None:
    subprocess.run([sys.executable, str(HERE / "verify_bytecode.py")],
                   check=True, stdout=subprocess.DEVNULL)
    assert subprocess.check_output(["git", "-C", str(BUILD), "rev-parse", "HEAD"],
                                   text=True).strip() == "9d50c6884666e794e45102260a4017bb31802e1b"
    assert sha(TEST_CLASS) == "a6459e0fcf46aa304ef1569a36789dd6df21d21ca064d7fccb6e3d209662f943"
    assert sha(TEST_SOURCE) == "5815550fb06429b227cd7c632bf0fe1523d0417c7da0c37105ff1c43db5ec49a"
    assert sha(TARGET_SOURCE) == "928a3e6d159a47a2f8c88e1720211ddf7af62129a5ed2d5a9f133f7ada60499b"
    agent = REPO / ("Mallory/instrumentation/releases/"
                    "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
                    "mallory-agent.jar")
    adapter = Path("/users/ZhenyuLi/.mallory-worktrees/hdfs-adapter-next/"
                   "mallory-hdfs-adapter-v11-recovery-task.jar")
    core = REPO / ("Mallory/dispatch/releases/"
                   "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f/"
                   "manifest.json")
    assert sha(agent) == agent.parent.name
    assert sha(adapter) == "d210764e9b7f812a52a56235794677047318648b35c659fe9fb0bf014c4670e7"
    assert sha(core) == "30aab0d0694bf92cc4267b4ca0832d01db7cf00a8737815920a3b6904698cde8"

    door_rules = {
        "HDFS-29": {
            "clazz": "org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker",
            "method": "callInitReplicaRecovery",
            "descriptor": "(Lorg/apache/hadoop/hdfs/server/protocol/InterDatanodeProtocol;Lorg/apache/hadoop/hdfs/server/protocol/BlockRecoveryCommand$RecoveringBlock;)Lorg/apache/hadoop/hdfs/server/protocol/ReplicaRecoveryInfo;",
            "line": 561,
            "callee": "org.apache.hadoop.hdfs.server.protocol.InterDatanodeProtocol#initReplicaRecovery(Lorg/apache/hadoop/hdfs/server/protocol/BlockRecoveryCommand$RecoveringBlock;)Lorg/apache/hadoop/hdfs/server/protocol/ReplicaRecoveryInfo;",
            "exception_class": "java.io.IOException",
        },
        "HDFS-30": {
            "clazz": "org.apache.hadoop.hdfs.server.datanode.BPServiceActor",
            "method": "sendHeartBeat",
            "descriptor": "(Z)Lorg/apache/hadoop/hdfs/server/protocol/HeartbeatResponse;",
            "line": 563,
            "callee": "org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB#sendHeartbeat(Lorg/apache/hadoop/hdfs/server/protocol/DatanodeRegistration;[Lorg/apache/hadoop/hdfs/server/protocol/StorageReport;JJIIILorg/apache/hadoop/hdfs/server/protocol/VolumeFailureSummary;ZLorg/apache/hadoop/hdfs/server/protocol/SlowPeerReports;Lorg/apache/hadoop/hdfs/server/protocol/SlowDiskReports;)Lorg/apache/hadoop/hdfs/server/protocol/HeartbeatResponse;",
            "exception_class": "java.io.IOException",
        },
    }
    receipt = {
        "status": "source_only_pending_healthy_admission",
        "hadoop_git_head": "9d50c6884666e794e45102260a4017bb31802e1b",
        "artifacts": [pin(p) for p in (agent, adapter, core, TEST_CLASS,
                                        TARGET_CLASS, ACTOR_CLASS, TEST_SOURCE,
                                        TARGET_SOURCE, ACTOR_SOURCE,
                                        HERE / "prepare.py",
                                        HERE / "verify_bytecode.py")],
        "cases": [],
    }
    for case_id, rule in door_rules.items():
        old_config = REPO / f"Mallory/adapters/hdfs/cases/pending-triage-v1/{case_id}-healthy-only.json"
        config = copy.deepcopy(json.loads(old_config.read_text()))
        old_site = Path(config["site_file"])
        site = copy.deepcopy(json.loads(old_site.read_text()))
        site["doors"] = [rule]
        site_path = HERE / f"{case_id}.sites.json"
        dump(site_path, site)
        config["site_file"] = str(site_path)
        config["agent_properties"]["auto.io.doors"] = False
        if case_id == "HDFS-30":
            config["agent_include"].append(rule["clazz"])
        config["mapping"]["calibration_revision"] = "pending_29_30_v2_source_only"
        config["mapping"]["selected_door"] = rule
        config["mapping"]["selected_door_verified"] = "compiled_call_site_only"
        config["mapping"]["healthy_seed_verified"] = False
        config["mapping"]["fault_retains_target_verified"] = False
        config["mapping"]["candidate_door_case"] = (
            "Per-replica initReplicaRecovery IOException is caught by "
            "RecoveryTaskContiguous.recover; another replica must succeed "
            "before syncBlock reaches the selected check."
            if case_id == "HDFS-29" else
            "Heartbeat IOException is caught by BPServiceActor.offerService "
            "and skips updateActorStatesFromHeartbeat for that response; a "
            "pre-existing recovery task may still reach the selected check "
            "during failover, subject to observed timing and causal audit.")
        config["mapping"]["original_test_reach"] = (
            "Both original-test guards were observed without selected throw "
            "in the archived identity-invalid healthy seed; v15 reached "
            "HDFS-29 on dn1 but JUnit timed out in DelayAnswer.waitForCall."
        )
        config["runtime_artifacts"] = [
            pin(agent), pin(adapter), pin(site_path), pin(TEST_CLASS),
            pin(TARGET_CLASS), pin(ACTOR_CLASS),
        ]
        config["calibration_only"] = True
        config["auto_promote_if_healthy"] = False
        config_path = HERE / f"{case_id}-healthy-only.json"
        dump(config_path, config)
        receipt["cases"].append({
            "case_id": case_id,
            "config": pin(config_path),
            "site_file": pin(site_path),
            "source_template": pin(old_config),
            "original_site_file": pin(old_site),
            "selected_door": rule,
            "original_calibration_result": pin(REPO / f"data/mallory/calibration/{case_id}/trials/r0000/result.json"),
            "original_calibration_stdout": pin(REPO / f"data/mallory/calibration/{case_id}/trials/r0000/stdout.log"),
            "fault_retains_target_verified": False,
            "healthy_seed_verified": False,
        })
    receipt["later_hdfs29_junit_failure"] = pin(
        REPO / "data/mallory/calibration_v15/HDFS-29/trials/r0000/junit-receipt.json")
    dump(HERE / "preflight.json", receipt)


if __name__ == "__main__":
    prepare()
