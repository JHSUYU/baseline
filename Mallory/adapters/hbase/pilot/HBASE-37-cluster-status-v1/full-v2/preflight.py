#!/usr/bin/env python3
"""JVM-free SHA and source preflight for HBASE-37 full-v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import zipfile
from pathlib import Path

from healthy_gate import CHECK, DOOR, EXCEPTION, THROW, require, sha, verify_pair

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
DIST = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6")
PRIOR = REPO / "data/mallory/calibration_hbase37_typed_nonode_healthy_v2/HBASE-37"
OUTPUT = REPO / "data/mallory/cases/HBASE-37/campaigns/cluster-status-nonode-v2-full"
RUNTIME_SITE = Path("/users/ZhenyuLi/.mallory-worktrees/hbase/lane7/runtime/cases"
                    "/HBASE-37-nonode-full-v2/sites.json")
RELEASE_ID = "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected JSON object: {path}")
    return value


def check(path: Path, expected: str) -> None:
    require(sha(path) == expected, f"SHA mismatch: {path}")


def preflight(node1: bool) -> None:
    manifest = read(HERE / "stage-manifest.json")
    config = read(HERE / "config.json")
    sites = read(HERE / "sites.json")
    prior = read(HERE / "prior-healthy-evidence.json")
    require(manifest.get("case_id") == "HBASE-37" and
            manifest.get("status") == "staged_no_jvm" and
            manifest.get("target_host") == "node1" and
            manifest.get("output_path") == str(OUTPUT) and
            manifest.get("prior_collection_receipt_sha256") ==
            prior.get("collection_receipt_sha256"),
            "wrong full-v2 package identity")
    for name, expected in manifest["files"].items():
        check(HERE / name, expected)
    require(config.get("case_id") == "HBASE-37" and
            config.get("system") == "hbase" and
            config.get("cluster_test") ==
            "org.apache.hadoop.hbase.regionserver.http.TestRSStatusPage#testStatusPage" and
            config["command"][-2:] == [
                "org.apache.hadoop.hbase.regionserver.http.TestRSStatusPage",
                "testStatusPage"], "cluster JUnit changed")
    require(config["budget"] == {"trials": 80, "seconds": 3600,
                                 "max_faults_per_trial": 3,
                                 "trial_timeout_seconds": 600} and
            config["calibration_only"] is False and
            config["auto_promote_if_healthy"] is True and
            config["allow_local_timeline_doors"] is True and
            config["require_event_time_paths"] is False and
            config["reject_coarse_roots"] is True and
            config["explore_outside_closure"] is False,
            "full-v2 gate, closure, or budget policy changed")
    require(config["agent_include"] == [
                "org.apache.hadoop.hbase.zookeeper.MasterAddressTracker",
                "org.apache.hadoop.hbase.zookeeper.ZKUtil"] and
            config["agent_properties"]["auto.io.doors"] is False and
            config["site_file"] == str(RUNTIME_SITE),
            "instrumentation or isolated site changed")
    require(config["target"]["check_sites"] == [CHECK] and
            config["target"]["throw_site"] == THROW and
            config["target"]["exception_class"] == "java.io.IOException" and
            sites["doors"] == [{
                "clazz": "org.apache.hadoop.hbase.zookeeper.ZKUtil",
                "method": "getData",
                "descriptor": "(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)[B",
                "line": 343,
                "callee": "org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper#getData"
                          "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                          "Lorg/apache/zookeeper/data/Stat;)[B",
                "exception_class": EXCEPTION}],
            "typed exact check or NoNode door changed")
    require(config["runtime_artifacts"][-2] == {
                "path": str(RUNTIME_SITE), "sha256": sha(HERE / "sites.json")},
            "runtime site pin changed")
    receipt = read(REPO / "Mallory/adapters/hbase/pilot/"
                   "HBASE-37-cluster-status-v1/healthy-v2/stage-receipt.json")
    review = read(REPO / "Mallory/adapters/hbase/pilot/"
                  "HBASE-37-cluster-status-v1/healthy-v2/source-review.json")
    require(receipt["binding_overlay_sha256"] ==
            config["mapping"]["binding_overlay_sha256"] and
            receipt["compiled_jar_sha256"] == config["mapping"]["compiled_jar_sha256"] and
            review["source_version"] == "hbase-2.6.6",
            "healthy-v2 source or artifact mapping changed")
    check(SOURCE / review["source_paths"]["target"],
          review["source_sha256"][review["source_paths"]["target"]])
    for key in ("typed_io", "test", "manager", "watcher"):
        relative = review["source_paths"][key]
        check(SOURCE / relative, review["source_sha256"][relative])
    target = (SOURCE / review["source_paths"]["target"]).read_text()
    util = (SOURCE / review["source_paths"]["typed_io"]).read_text()
    manager = (SOURCE / review["source_paths"]["manager"]).read_text()
    test = (SOURCE / review["source_paths"]["test"]).read_text()
    require("data = ZKUtil.getData(zkw, zkw.getZNodePaths().masterAddressZNode);"
            in target and
            'if (data == null) {\n      throw new IOException("Can\'t get master address '
            'from ZooKeeper; znode data == null");' in target and
            "catch (KeeperException.NoNodeException e)" in util and
            "return null;" in util and
            "return MasterAddressTracker.getMasterInfoPort(watcher);" in manager and
            "return 0;" in manager and
            "new LocalHBaseCluster(conf, 1)" in test,
            "NoNode → null → guard, catch, or unchanged cluster JUnit changed")
    check(DIST / "lib/hbase-zookeeper-2.6.6.jar",
          receipt["compiled_jar_sha256"])
    with zipfile.ZipFile(DIST / "lib/hbase-zookeeper-2.6.6.jar") as jar:
        clazz = jar.read("org/apache/hadoop/hbase/zookeeper/MasterAddressTracker.class")
    require(hashlib.sha256(clazz).hexdigest() ==
            config["expected_target_class_sha256"],
            "compiled exact target class changed")
    release = REPO / "Mallory/dispatch/releases" / RELEASE_ID
    require(config["core_release"]["release_id"] == RELEASE_ID,
            "frozen core release changed")
    check(release / "manifest.json", config["core_release"]["manifest_sha256"])
    core_manifest = read(release / "manifest.json")
    for name, expected in core_manifest["files"].items():
        check(release / name, expected)
    check(REPO / "Mallory/instrumentation/releases/"
          "38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/"
          "mallory-agent.jar", config["runtime_artifacts"][0]["sha256"])
    require(prior["case_id"] == "HBASE-37" and prior["status"] == "admitted" and
            prior["junit"] == "1/0/0" and prior["door_seq"] + 1 == prior["target_seq"] and
            prior["source_path"] == str(PRIOR.relative_to(REPO)) and
            prior["fresh_full_r0000_required"] is True,
            "sealed prior healthy receipt changed")
    if node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        for artifact in config["runtime_artifacts"]:
            check(Path(artifact["path"]), artifact["sha256"])
        for relative, expected in review["source_sha256"].items():
            if (Path(config["source_equivalent_root"]) / relative).is_file():
                check(Path(config["source_equivalent_root"]) / relative, expected)
        check(PRIOR / "node1-collection-receipt.json",
              prior["collection_receipt_sha256"])
        observed = verify_pair(PRIOR, require_local_timeline=False)
        for key in ("result_sha256", "trial_sha256", "trace_gzip_sha256",
                    "door_seq", "target_seq", "occurrence", "thread_id"):
            require(observed[key] == prior[key], f"prior healthy mismatch: {key}")
    print("PASS HBASE-37 full-v2 JVM-free preflight: sealed prior healthy, "
          "typed same-occurrence gate, exact cluster JUnit, pinned core/source/artifacts")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node1", action="store_true")
    args = parser.parse_args()
    try:
        preflight(args.node1)
    except (ValueError, KeyError, FileNotFoundError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"HBASE-37 full-v2 preflight gap: {exc}")


if __name__ == "__main__":
    main()
