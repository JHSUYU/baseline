#!/usr/bin/env python3
"""Stage source-pinned, healthy-only ZooKeeper preflights; never run a JVM."""

import copy
import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
ADAPTER = BASE / "Mallory/adapters/zookeeper"
AGENT = BASE / ("Mallory/instrumentation/releases/"
                "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
                "mallory-agent.jar")
CORE = BASE / ("Mallory/dispatch/releases/"
               "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def receipt_for(name):
    path = ADAPTER / name
    receipt = read(path)
    assert receipt["base_commit"] == "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae"
    return path, receipt


def artifact_sha(receipt, relative):
    matches = [a["sha256"] for a in receipt["compiled_artifacts"]
               if a["path"].endswith(relative)]
    assert len(matches) == 1, (relative, matches)
    return matches[0]


def stage(case, template, receipt_name, selector, site_transform,
          max_seconds, max_trial_seconds):
    original = read(BASE / template)
    assert original["case_id"] == case
    receipt_path, receipt = receipt_for(receipt_name)
    config = copy.deepcopy(original)
    source_root = Path(receipt["patched_root"])
    relative_class = config["mapping"].get("target_class_relative")
    if not relative_class:
        relative_class = ("zookeeper-server/target/classes/"
                          + config["agent_include"][0].replace(".", "/") + ".class")
    source_path = config["target"]["source_path"]
    test_path = config["mapping"].get("test_source_path")
    if not test_path:
        test_class = original["cluster_test"].split("#", 1)[0]
        test_path = "zookeeper-server/src/test/java/" + test_class.replace(".", "/") + ".java"
    assert source_path in receipt["modified_files"]
    assert test_path in receipt["test_sources"]

    sites = read(original["site_file"])
    site_transform(sites, config)
    sites_path = HERE / (case + ".sites.json")
    config_path = HERE / (case + ".healthy-only.json")
    write(sites_path, sites)

    agent_sha = digest(AGENT)
    config.update(
        cwd=str(source_root),
        command=["mvn", "-pl", "zookeeper-server", "-am",
                 "-Dtest=" + selector, "-Dsurefire.failIfNoSpecifiedTests=false",
                 "-Dmallory.test.dir={trial_dir}/test-data", "test"],
        cluster_test=selector,
        agent_jar=str(AGENT),
        core_release=str(CORE),
        site_file=str(sites_path),
        source_overlay_receipt=str(receipt_path),
        source_overlay_receipt_sha256=digest(receipt_path),
        expected_target_class_sha256=artifact_sha(receipt, relative_class),
        calibration_only=True,
        auto_promote_if_healthy=False,
        require_event_time_paths=True,
    )
    config["agent_properties"]["auto.io.doors"] = True
    config["budget"] = {"trials": 1, "seconds": max_seconds,
                        "max_faults_per_trial": 1,
                        "trial_timeout_seconds": max_trial_seconds,
                        "trial_timeout_basis": "source_only_preflight_ceiling"}
    config["mapping"].update(
        status="source_pinned_healthy_only_preflight_not_executed",
        source_root=str(source_root),
        target_class_relative=relative_class,
        test_source_path=test_path,
        compiled_artifact=str(source_root / "zookeeper-server/target/classes"),
        compiled_class_sha256=config["expected_target_class_sha256"],
        target_source_sha256=receipt["modified_files"][source_path],
        test_source_sha256=receipt["test_sources"][test_path],
        agent_sha256=agent_sha,
        healthy_seed_verified=False,
        node_identity_binding_verified=False,
    )
    config["mapping"].pop("verified_healthy_probe", None)
    config["mapping"].pop("agent_build", None)
    config["runtime_artifacts"] = [
        {"path": str(AGENT), "sha256": agent_sha},
        {"path": str(sites_path), "sha256": digest(sites_path)},
    ]
    write(config_path, config)
    return {"case_id": case, "config": str(config_path),
            "config_sha256": digest(config_path), "sites": str(sites_path),
            "sites_sha256": digest(sites_path),
            "receipt": str(receipt_path), "receipt_sha256": digest(receipt_path)}


def zk05(sites, config):
    # Retry-v3 inserts one statement before the original guard in followLeader.
    for target in sites["targets"]:
        assert target["line"] in (99, 104)
        target["line"] += 1
    config["target"]["check_sites"] = [
        "org.apache.zookeeper.server.quorum.Follower#followLeader()V@100:branch:2"]
    config["target"]["throw_site"] = (
        "org.apache.zookeeper.server.quorum.Follower#followLeader()V@105:throw:1")
    config["target"]["source_line"] = 105


def zk10(sites, config):
    assert [t["line"] for t in sites["targets"]] == [368, 374]
    config["target"]["nodes"] = ["zk1", "zk2"]


def zk06(sites, config):
    assert [t["line"] for t in sites["targets"]] == [1475, 1479]
    config["target"]["nodes"] = ["zk1", "zk2", "zk3"]


def zk12(sites, config):
    assert [t["line"] for t in sites["targets"]] == [1193, 1197]
    sites["doors"] = [{
        "class": "org.apache.zookeeper.server.quorum.QuorumPeer",
        "method": "readLongFromFile", "descriptor": "(Ljava/lang/String;)J",
        "line": 2190,
        "callee": "java.io.BufferedReader#readLine()Ljava/lang/String;",
        "exception_class": "java.io.FileNotFoundException",
    }]
    config["target"]["nodes"] = ["zk0"]


def main():
    assert AGENT.is_file() and CORE.is_dir()
    staged = [
        stage("ZOOKEEPER-05", "Mallory/adapters/zookeeper/cases/ZOOKEEPER-05-5820-healthy.json",
              "zookeeper-3.8.7-following-retry-v3-overlay.json",
              "QuorumRestartTest#testRollingRestart", zk05, 300, 180),
        stage("ZOOKEEPER-06", "Mallory/cases/ZOOKEEPER-06.json",
              "zookeeper-3.8.7-ackepoch-lane2-overlay.json",
              "QuorumRestartTest#testRollingRestart", zk06, 300, 180),
        stage("ZOOKEEPER-10", "Mallory/cases/ZOOKEEPER-10.json",
              "zookeeper-3.8.7-ackepoch-lane2-overlay.json",
              "ObserverMasterTest#testObserver", zk10, 900, 600),
        stage("ZOOKEEPER-12", "Mallory/adapters/zookeeper/cases/ZOOKEEPER-12-5a-healthy.json",
              "zookeeper-3.8.7-ackepoch-lane2-overlay.json",
              "CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile",
              zk12, 300, 180),
    ]
    write(HERE / "prepared.json", {"schema_version": 1, "healthy_only": True,
                                    "no_jvm_launched": True, "staged": staged})


if __name__ == "__main__":
    main()
