#!/usr/bin/env python3
"""JVM-free preflight for the isolated HBASE-37 typed-door healthy seed."""

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
OVERLAY = REPO / "Mallory/adapters/hbase/overlays/master-tracker-binding-v1"
RUNTIME_SITE = Path("/users/ZhenyuLi/.mallory-worktrees/hbase/lane7/runtime/cases"
                    "/HBASE-37-nonode-healthy-v2/sites.json")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    require(path.is_file(), f"missing pinned file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(path: Path, expected: str) -> None:
    actual = sha(path)
    require(actual == expected, f"SHA mismatch for {path}: {actual}")


def preflight(node1: bool) -> None:
    config = json.loads((HERE / "config.json").read_text())
    sites = json.loads((HERE / "sites.json").read_text())
    review = json.loads((HERE / "source-review.json").read_text())
    receipt = json.loads((HERE / "stage-receipt.json").read_text())
    require(receipt["case_id"] == "HBASE-37" and receipt["status"] == "staged_no_jvm",
            "wrong stage receipt")
    for file, key in (("config.json", "config_sha256"),
                      ("sites.json", "site_sha256"),
                      ("source-review.json", "source_review_sha256"),
                      ("preflight.py", "preflight_sha256")):
        check(HERE / file, receipt[key])
    require(config["case_id"] == "HBASE-37" and config["system"] == "hbase" and
            config["cluster_test"] ==
            "org.apache.hadoop.hbase.regionserver.http.TestRSStatusPage#testStatusPage" and
            config["command"][-2:] == [
                "org.apache.hadoop.hbase.regionserver.http.TestRSStatusPage", "testStatusPage"],
            "wrong cluster JUnit")
    require(config["calibration_only"] is True and
            config["auto_promote_if_healthy"] is False and
            config["budget"] == {"trials": 1, "seconds": 600,
                                 "max_faults_per_trial": 1,
                                 "trial_timeout_seconds": 300} and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False,
            "healthy-only strict path policy changed")
    require(config["agent_include"] == [
        "org.apache.hadoop.hbase.zookeeper.MasterAddressTracker",
        "org.apache.hadoop.hbase.zookeeper.ZKUtil"] and
            config["agent_properties"]["auto.io.doors"] is False,
            "typed-door instrumentation changed")
    require(config["site_file"] == str(RUNTIME_SITE) and
            config["runtime_artifacts"][-2] ==
            {"path": str(RUNTIME_SITE), "sha256": receipt["site_sha256"]},
            "isolated site artifact changed")
    require(sites["targets"][0]["line"] == 205 and
            sites["targets"][1]["line"] == 206 and
            sites["doors"] == [{
                "clazz": "org.apache.hadoop.hbase.zookeeper.ZKUtil",
                "method": "getData",
                "descriptor": "(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;)[B",
                "line": 343,
                "callee": "org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper#getData"
                          "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                          "Lorg/apache/zookeeper/data/Stat;)[B",
                "exception_class": "org.apache.zookeeper.KeeperException$NoNodeException",
            }], "exact typed NoNode door changed")
    require(config["target"]["check_sites"] == [review["selected_check"]["site"]] and
            config["target"]["throw_site"] == review["selected_check"]["throw_site"],
            "selected target changed")
    for relative, digest in review["source_sha256"].items():
        check(SOURCE / relative, digest)
    paths = review["source_paths"]
    target = (SOURCE / paths["target"]).read_text()
    util = (SOURCE / paths["typed_io"]).read_text()
    manager = (SOURCE / paths["manager"]).read_text()
    test = (SOURCE / paths["test"]).read_text()
    require("data = ZKUtil.getData(zkw, zkw.getZNodePaths().masterAddressZNode);" in target
            and "if (data == null) {\n      throw new IOException(" in target,
            "selected null guard changed")
    require("zkw.getRecoverableZooKeeper().getData(znode, null, null);" in util and
            "catch (KeeperException.NoNodeException e)" in util and
            "return null;" in util, "NoNode/null-return route changed")
    require("return MasterAddressTracker.getMasterInfoPort(watcher);" in manager and
            "catch (Exception e)" in manager and
            "new LocalHBaseCluster(conf, 1)" in test and
            "int masterPort = master.getActiveMasterInfoPort();" in test,
            "mapped cluster call path changed")
    prior = json.loads((REPO / "data/mallory/calibration/HBASE-37/result.json").read_text())
    require(prior["status"] == "healthy_node_identity_missing" and
            prior["trials"][0]["target_reached"] is True and
            prior["target_node_named"] is False,
            "prior identity gap changed")
    check(DIST / "hbase-zookeeper-2.6.6.jar", receipt["compiled_jar_sha256"])
    with zipfile.ZipFile(DIST / "hbase-zookeeper-2.6.6.jar") as jar:
        for class_name, expected in receipt["compiled_class_sha256"].items():
            require(hashlib.sha256(jar.read(class_name)).hexdigest() == expected,
                    f"compiled class changed: {class_name}")
    require(config["expected_target_class_sha256"] == receipt["compiled_class_sha256"][
        "org/apache/hadoop/hbase/zookeeper/MasterAddressTracker.class"],
        "target class pin changed")
    core = config["core_release"]
    manifest = REPO / "Mallory/dispatch/releases" / core["release_id"] / "manifest.json"
    check(manifest, core["manifest_sha256"])
    for relative, digest in json.loads(manifest.read_text())["files"].items():
        check(manifest.parent / relative, digest)
    check(OVERLAY / "releases/ab0d9d13c6dc1073/adapter.jar",
          receipt["binding_overlay_sha256"])
    check(REPO / "Mallory/instrumentation/releases"
          "/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9"
          "/mallory-agent.jar", config["runtime_artifacts"][0]["sha256"])
    if node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        require(Path(config["cwd"]).is_dir(), "missing runtime cwd")
        for artifact in config["runtime_artifacts"]:
            check(Path(artifact["path"]), artifact["sha256"])
        for relative, digest in review["source_sha256"].items():
            check(Path(config["source_equivalent_root"]) / relative, digest)
    print("PASS HBASE-37 JVM-free healthy-v2 preflight: cluster test, exact guard, "
          "typed NoNode door, source/class/site/core/artifact pins")


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
            args.outcome.write_text(json.dumps({"schema_version": 1, "case_id": "HBASE-37",
                "kind": "static_preflight_gap", "status": "source_or_path_gap",
                "reason": str(exc), "jvm_started": False}, indent=2) + "\n")
        raise SystemExit(f"HBASE-37 healthy-v2 preflight gap: {exc}")


if __name__ == "__main__":
    main()
