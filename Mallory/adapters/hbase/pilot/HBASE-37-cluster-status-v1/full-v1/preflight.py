#!/usr/bin/env python3
"""JVM-free, SHA-pinned preflight for HBASE-37 cluster status full run."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
DIST = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib")
OUTPUT = REPO / "data/mallory/cases/HBASE-37/campaigns/cluster-status-nonode-v1-full"
RELEASE_ID = "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
RELEASE = REPO / "Mallory/dispatch/releases" / RELEASE_ID
TARGET = "hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/MasterAddressTracker.java"
UTIL = "hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/ZKUtil.java"
WATCHER = "hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/ZKWatcher.java"
TEST = "hbase-server/src/test/java/org/apache/hadoop/hbase/regionserver/http/TestRSStatusPage.java"
MANAGER = "hbase-server/src/main/java/org/apache/hadoop/hbase/master/ActiveMasterManager.java"
PINS = {
    TARGET: "6c32e94e40bf907b6949d26416c472bc014907f52bc47c0a7ce6d8c6537b0987",
    UTIL: "413a0487863e7b7c8c5299f939eaec45ac33321fec8af2c5d160b64c7cf04b40",
    WATCHER: "515e1682fc99944fd823205f0e0b044f3edb71b3617e35396c54b12c2a9be979",
    TEST: "8643f58811d877d807023356c7d23f8f55530d209f53a2367cfb221e95db292b",
    MANAGER: "edcf8ec32db64ceac9147dcb00fefc36ff5b92f499e37e9256f0ec8552252fde",
}


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha(path: Path) -> str:
    require(path.is_file(), f"missing pinned file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(path: Path, expected: str) -> None:
    actual = sha(path)
    require(actual == expected, f"SHA mismatch for {path}: {actual}")


def preflight(on_node1: bool) -> None:
    config = json.loads((HERE / "config.json").read_text())
    stage = json.loads((HERE / "stage-receipt.json").read_text())
    site = json.loads((HERE / "sites.json").read_text())
    require(stage["status"] == "staged_no_jvm" and stage["case_id"] == "HBASE-37",
            "wrong stage receipt")
    for name, key in (("config.json", "config_sha256"),
                      ("sites.json", "site_sha256"),
                      ("preflight.py", "preflight_sha256"),
                      ("run_full_node1.sh", "runner_sha256"),
                      ("verify_terminal.py", "verifier_sha256")):
        check(HERE / name, stage[key])
    require(stage["output_path"] == str(OUTPUT) and stage["target_host"] == "node1",
            "wrong host or output")
    require(config["case_id"] == "HBASE-37" and config["system"] == "hbase" and
            config["cluster_test"] ==
            "org.apache.hadoop.hbase.regionserver.http.TestRSStatusPage#testStatusPage",
            "wrong cluster JUnit")
    require(config["budget"] == {"trials": 80, "seconds": 3600,
                                 "max_faults_per_trial": 3,
                                 "trial_timeout_seconds": 600}, "wrong full budget")
    require(config["calibration_only"] is False and
            config["auto_promote_if_healthy"] is True and
            config["allow_local_timeline_doors"] is True and
            config["require_event_time_paths"] is False and
            config["reject_coarse_roots"] is False and
            config["agent_properties"]["auto.io.doors"] is False,
            "fault/path policy changed")
    require(config["agent_include"] == [
        "org.apache.hadoop.hbase.zookeeper.MasterAddressTracker",
        "org.apache.hadoop.hbase.zookeeper.ZKUtil"], "wrong instrumented classes")
    require(config["site_file"] ==
            "/users/ZhenyuLi/.mallory-worktrees/hbase/lane7/runtime/cases/HBASE-37-nonode-v1/sites.json",
            "wrong runtime site path")
    require(config["runtime_artifacts"][-2] == {
        "path": config["site_file"], "sha256": stage["site_sha256"]},
        "runtime site pin changed")
    require(config["target"]["check_sites"] == [
        "org.apache.hadoop.hbase.zookeeper.MasterAddressTracker#getMasterInfoPort"
        "(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;)I@205:branch:1"] and
            config["target"]["throw_site"].endswith("@206:throw:1") and
            config["target"]["exception_class"] == "java.io.IOException",
            "selected target changed")
    require(site["doors"] == [{
        "clazz": "org.apache.hadoop.hbase.zookeeper.ZKUtil",
        "method": "getData",
        "descriptor": "(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)[B",
        "line": 343,
        "callee": "org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper#getData"
                  "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                  "Lorg/apache/zookeeper/data/Stat;)[B",
        "exception_class": "org.apache.zookeeper.KeeperException$NoNodeException",
    }], "source-backed NoNode I/O selector changed")
    require(site["targets"][0]["line"] == 205 and site["targets"][1]["line"] == 206,
            "target site catalog changed")
    check(REPO / "Mallory/adapters/hbase/pilot/HBASE-37-minicluster-admission-v1/source-gap.json",
          stage["source_review_sha256"])
    check(HERE / "prior-healthy-result.json", stage["prior_healthy_result_sha256"])
    prior = json.loads((HERE / "prior-healthy-result.json").read_text())
    require(prior["status"] == "healthy_node_identity_missing" and
            prior["trials"][0]["target_reached"] is True and
            prior["target_node_named"] is False and
            prior["healthy_eligible_doors"] == 39,
            "prior target/actor/door evidence changed")
    for relative, digest in PINS.items():
        check(SOURCE / relative, digest)
    target = (SOURCE / TARGET).read_text()
    util = (SOURCE / UTIL).read_text()
    test = (SOURCE / TEST).read_text()
    watcher = (SOURCE / WATCHER).read_text()
    manager = (SOURCE / MANAGER).read_text()
    require("data = ZKUtil.getData(zkw, zkw.getZNodePaths().masterAddressZNode);" in target and
            "if (data == null) {\n      throw new IOException(\"Can't get master address from ZooKeeper; znode data == null\");" in target,
            "exact target guard changed")
    require("zkw.getRecoverableZooKeeper().getData(znode, null, null);" in util and
            "catch (KeeperException.NoNodeException e)" in util and
            "zkw.keeperException(e);" in util and
            "throw ke;" in watcher, "NoNode/null-return source route changed")
    require("new LocalHBaseCluster(conf, 1)" in test and
            "int masterPort = master.getActiveMasterInfoPort();" in test and
            "return MasterAddressTracker.getMasterInfoPort(watcher);" in manager,
            "cluster JUnit exact call chain changed")
    check(DIST / "hbase-zookeeper-2.6.6.jar",
          "6ad67305af4910e61e324034cab9ce0f50b966ce203c195581daeff552a8b957")
    with zipfile.ZipFile(DIST / "hbase-zookeeper-2.6.6.jar") as jar:
        cls = jar.read("org/apache/hadoop/hbase/zookeeper/MasterAddressTracker.class")
    require(hashlib.sha256(cls).hexdigest() == config["expected_target_class_sha256"],
            "compiled target class changed")
    check(RELEASE / "manifest.json", config["core_release"]["manifest_sha256"])
    require(config["core_release"]["release_id"] == RELEASE_ID, "wrong frozen core")
    manifest = json.loads((RELEASE / "manifest.json").read_text())
    require(manifest["release_id"] == RELEASE_ID, "core identity changed")
    for relative, digest in manifest["files"].items():
        check(RELEASE / relative, digest)
    check(REPO / "Mallory/instrumentation/releases/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar",
          config["runtime_artifacts"][0]["sha256"])
    if not on_node1:
        check(REPO / "Mallory/adapters/hbase/overlays/master-tracker-binding-v1/releases/ab0d9d13c6dc1073/adapter.jar",
              config["runtime_artifacts"][-1]["sha256"])
    if on_node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        require(Path(config["cwd"]).is_dir(), f"missing runtime cwd: {config['cwd']}")
        for row in config["runtime_artifacts"]:
            check(Path(row["path"]), row["sha256"])
        for relative, digest in PINS.items():
            check(Path(config["source_equivalent_root"]) / relative, digest)
    print("PASS HBASE-37 JVM-free full preflight: cluster JUnit, exact guard, "
          "NoNode door, source/core/artifact SHAs, 80/3600/max3")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node1", action="store_true")
    parser.add_argument("--outcome", type=Path)
    args = parser.parse_args()
    try:
        preflight(args.node1)
    except (ValueError, FileNotFoundError, KeyError, zipfile.BadZipFile) as exc:
        if args.outcome:
            args.outcome.parent.mkdir(parents=True, exist_ok=True)
            args.outcome.write_text(json.dumps({"schema_version": 1,
                "case_id": "HBASE-37", "kind": "static_preflight_gap",
                "status": "source_or_path_gap", "reason": str(exc),
                "jvm_started": False}, indent=2) + "\n")
        raise SystemExit(f"HBASE-37 static preflight gap: {exc}")


if __name__ == "__main__":
    main()
