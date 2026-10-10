#!/usr/bin/env python3
"""JVM-free admission preflight for the HBASE-27 tracker identity healthy seed."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
OVERLAY = HERE.parent
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
DIST = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib")
JAR_SHA = "fb2835d2b2bcd3d338011f0120685e51c6c28e2f7c87b3f0284c9465726e021e"
RUNTIME_JAR = Path("/users/ZhenyuLi/.mallory-worktrees/hbase/lane2-v2/runtime"
                   "/zk-tracker-monitor-fb2835d2.jar")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    require(path.is_file(), f"missing pinned file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(path: Path, expected: str) -> None:
    actual = digest(path)
    require(actual == expected, f"SHA mismatch for {path}: {actual}")


def preflight(node1: bool) -> None:
    config = json.loads((HERE / "config.json").read_text())
    receipt = json.loads((HERE / "stage-receipt.json").read_text())
    require(receipt["status"] == "staged_no_jvm" and receipt["case_id"] == "HBASE-27",
            "wrong stage receipt")
    check(HERE / "config.json", receipt["config_sha256"])
    check(HERE / "preflight.py", receipt["preflight_sha256"])
    require(config["case_id"] == "HBASE-27" and config["system"] == "hbase" and
            config["cluster_test"] ==
            "org.apache.hadoop.hbase.TestClusterBootOrder#testBootRegionServerFirst",
            "wrong selected test")
    require(config["calibration_only"] is True and
            config["budget"]["trials"] == 1 and
            config.get("auto_promote_if_healthy") is not True and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False,
            "healthy-only or strict path policy changed")
    require(config["target"]["check_sites"] == [
        "org.apache.hadoop.hbase.regionserver.HRegionServer#blockAndCheckIfStopped"
        "(Lorg/apache/hadoop/hbase/zookeeper/ZKNodeTracker;)V@1052:branch:2"] and
            config["target"]["throw_site"].endswith("@1053:throw:1"),
            "selected target changed")
    require(config["agent_properties"]["adapter.transformers"].endswith(
        "edu.uva.liftlab.mallory.hbase.zkmonitor.TrackerMonitorTransformer") and
            str(RUNTIME_JAR) in config["agent_properties"]["adapter.jars"],
            "tracker overlay is not configured")
    require(config["runtime_artifacts"][-1] ==
            {"path": str(RUNTIME_JAR), "sha256": JAR_SHA},
            "runtime overlay does not match release")
    release = OVERLAY / "releases" / JAR_SHA[:16] / "adapter.jar"
    check(release, JAR_SHA)
    site = OVERLAY / "HBASE-27-monitor-v1.sites.json"
    check(site, receipt["site_sha256"])
    require(config["site_file"] == config["runtime_artifacts"][2]["path"] and
            config["runtime_artifacts"][2]["sha256"] == receipt["site_sha256"],
            "site artifact changed")
    sites = json.loads(site.read_text())
    require(any(d.get("clazz") == "org.apache.hadoop.hbase.zookeeper.ZKNodeTracker"
                and d.get("method") == "nodeCreated" and d.get("line") == 199
                for d in sites["doors"]), "nodeCreated read door missing")
    for relative, sha in receipt["overlay_source_sha256"].items():
        check(OVERLAY / relative, sha)
    for relative, sha in receipt["source_sha256"].items():
        check(SOURCE / relative, sha)
    for jar_name, classes in receipt["class_sha256"].items():
        with zipfile.ZipFile(DIST / jar_name) as jar:
            for class_name, sha in classes.items():
                require(hashlib.sha256(jar.read(class_name)).hexdigest() == sha,
                        f"compiled class changed: {class_name}")
    core = config["core_release"]
    check(REPO / "Mallory/dispatch/releases" / core["release_id"] / "manifest.json",
          core["manifest_sha256"])
    if node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        require(Path(config["cwd"]).is_dir(), "missing runtime cwd")
        for artifact in config["runtime_artifacts"]:
            check(Path(artifact["path"]), artifact["sha256"])
        for relative, sha in receipt["source_sha256"].items():
            check(Path(config["source_equivalent_root"]) / relative, sha)
    print("PASS HBASE-27 healthy-v2 JVM-free preflight: indexed factory, tracker owner, "
          "target, site, source, class and artifact pins")


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
            args.outcome.write_text(json.dumps({"schema_version": 1, "case_id": "HBASE-27",
                "kind": "static_preflight_gap", "status": "source_or_path_gap",
                "reason": str(exc), "jvm_started": False}, indent=2) + "\n")
        raise SystemExit(f"HBASE-27 healthy-v2 preflight gap: {exc}")


if __name__ == "__main__":
    main()
