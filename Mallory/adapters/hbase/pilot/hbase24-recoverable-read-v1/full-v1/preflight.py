#!/usr/bin/env python3
"""Offline checks for the frozen HBASE-24 full campaign; starts no JVM."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
REPO = HERE.parents[5]
CONFIG = HERE / "config.json"
RELEASE_ID = "dc5ee9f0a9cb8dec77813d84389b36759068eabecee4bf74bc45c25afe2b0857"
RELEASE = REPO / "Mallory/dispatch/releases" / RELEASE_ID
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
DIST = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib")
LANE = Path("/users/ZhenyuLi/.mallory-worktrees/hbase/lane9")
OUTPUT = REPO / "data/mallory/cases/HBASE-24/campaigns/recoverable-read-v1-full"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def check(path: Path, expected: str) -> None:
    require(path.is_file(), f"missing pinned file: {path}")
    actual = sha(path)
    require(actual == expected, f"SHA mismatch for {path}: {actual}")


def main(on_node1: bool = False) -> None:
    config = json.loads(CONFIG.read_text())
    healthy = json.loads((BASE / "healthy.json").read_text())
    stage = json.loads((HERE / "stage-receipt.json").read_text())
    for filename, key in ((CONFIG, "config_sha256"),
                          (HERE / "run_full_node1.sh", "runner_sha256"),
                          (HERE / "verify_terminal.py", "verifier_sha256"),
                          (HERE / "preflight.py", "preflight_sha256")):
        check(filename, stage[key])
    require(stage["case_id"] == "HBASE-24" and stage["status"] == "staged_no_jvm",
            "wrong stage receipt")
    require(config["budget"] == {"trials": 80, "seconds": 3600,
                                 "max_faults_per_trial": 3,
                                 "trial_timeout_seconds": 600}, "wrong full budget")
    require(config["case_id"] == "HBASE-24" and config["system"] == "hbase"
            and config["cluster_test"] ==
            "org.apache.hadoop.hbase.procedure.TestZKProcedure#testMultipleMembers",
            "wrong selected check or JUnit")
    require(config["calibration_only"] is False and
            config["auto_promote_if_healthy"] is True and
            config["allow_local_timeline_doors"] is True and
            config["agent_properties"]["auto.io.doors"] is False,
            "wrong fault or path policy")
    require(config["target"] == healthy["target"] and
            config["site_file"] == healthy["site_file"] and
            config["command"] == healthy["command"] and
            config["agent_include"] == healthy["agent_include"] and
            config["agent_jar"] == healthy["agent_jar"] and
            config["runtime_artifacts"] == healthy["runtime_artifacts"],
            "selected check, typed door, or runtime changed from admitted healthy config")
    require(config["target"]["check_sites"] == [
        "org.apache.hadoop.hbase.procedure.ZKProcedureMemberRpcs#startNewSubprocedure"
        "(Ljava/lang/String;)V@205:branch:2"] and
            config["target"]["throw_site"].endswith("@210:throw:1"),
            "wrong target bytecode sites")

    site = json.loads((BASE / "sites.json").read_text())
    require(len(site["doors"]) == 1 and site["doors"][0] == {
        "clazz": "org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper",
        "method": "getData",
        "descriptor": "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                      "Lorg/apache/zookeeper/data/Stat;)[B",
        "line": 405,
        "callee": "org.apache.zookeeper.ZooKeeper#getData"
                  "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                  "Lorg/apache/zookeeper/data/Stat;)[B",
        "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException",
    }, "typed I/O selector changed")
    check(BASE / "sites.json", stage["source_site_sha256"])
    check(BASE / "healthy-v1-receipt.json", stage["healthy_receipt_sha256"])
    receipt = json.loads((BASE / "healthy-v1-receipt.json").read_text())
    require(receipt["junit"]["tests"] == receipt["junit"]["succeeded"] == 1
            and receipt["junit"]["failures"] == receipt["junit"]["errors"] == 0
            and len(receipt["named_same_occurrence_door_check_pairs"]) == 4
            and receipt["audit"]["healthy_local_timeline_doors"] == 4
            and receipt["audit"]["healthy_observed_path_doors"] == 0
            and receipt["strict_graph_path_proven"] is False,
            "healthy evidence interpretation changed")
    att = config["calibration_attestation"]
    for label in ("healthy_receipt", "healthy_result", "healthy_audit",
                  "healthy_trace_gzip"):
        check(Path(att[label + "_path"]), att[label + "_sha256"])
    require(att["named_same_occurrence_door_check_pairs"] == 4 and
            att["observed_graph_path_doors"] == 0 and
            att["strict_graph_path_proven"] is False and
            att["evidence_type"] == "observed_local_timeline",
            "healthy evidence overstated")
    check(RELEASE / "manifest.json", config["core_release"]["manifest_sha256"])
    require(config["core_release"]["release_id"] == RELEASE_ID,
            "wrong immutable core release")
    manifest = json.loads((RELEASE / "manifest.json").read_text())
    require(manifest["release_id"] == RELEASE_ID, "core release identity changed")
    for relative, digest in manifest["files"].items():
        check(RELEASE / relative, digest)

    source_pins = {
        "hbase-server/src/main/java/org/apache/hadoop/hbase/procedure/"
        "ZKProcedureMemberRpcs.java": "ba0ee569fccf2a69057860800bc05a2fe1db0d5a4b368c490485ee542b0c55b2",
        "hbase-server/src/test/java/org/apache/hadoop/hbase/procedure/"
        "TestZKProcedure.java": "0cc57f0c0d21b679997580cc8169e1b8f70ed0bb77e8bbb6bb6d41e5bca8a2b2",
        "hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/"
        "RecoverableZooKeeper.java": "f946cd3195c5969b55ce5d079c272a7b12d673c5406a98ef026dc8fcea18fa88",
        "hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/"
        "ZKUtil.java": "413a0487863e7b7c8c5299f939eaec45ac33321fec8af2c5d160b64c7cf04b40",
    }
    for relative, digest in source_pins.items():
        check(SOURCE / relative, digest)
    check(DIST / "hbase-server-2.6.6.jar",
          "27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696")
    check(DIST / "hbase-zookeeper-2.6.6.jar",
          "6ad67305af4910e61e324034cab9ce0f50b966ce203c195581daeff552a8b957")
    check(DIST / "zookeeper-3.8.6.jar",
          "a00943a87b9c83379267ebda487be1ddb83e9997a03e59f9199338a033b71ed7")
    with zipfile.ZipFile(DIST / "hbase-server-2.6.6.jar") as jar:
        target = jar.read("org/apache/hadoop/hbase/procedure/ZKProcedureMemberRpcs.class")
    require(hashlib.sha256(target).hexdigest() == config["expected_target_class_sha256"],
            "target class changed")
    require(OUTPUT.as_posix() == stage["output_path"], "output destination changed")
    if on_node1:
        require(socket.gethostname().split(".")[0] == "node1", "node1 preflight on wrong host")
        for artifact in config["runtime_artifacts"]:
            check(Path(artifact["path"]), artifact["sha256"])
        check(Path(config["site_file"]), stage["staged_site_sha256"])
        for relative, digest in source_pins.items():
            check(LANE / "source" / relative, digest)
        check(LANE / "source-equivalence.json",
              "4f3c0ba3dece475ef8be18294e770cf63a0a3df52444aa814f5d92c6e1b3b5db")
    print("PASS HBASE-24 full-v1 offline preflight: selected typed read, four temporal "
          "healthy pairs, immutable pins, 80/3600/max3; JVM runs=0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--node1", action="store_true")
    main(parser.parse_args().node1)
