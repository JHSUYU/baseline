#!/usr/bin/env python3
"""SHA-pinned, JVM-free preflight for the HBASE-27 boot-order campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
CONFIG = HERE / "config.json"
STAGE = HERE / "stage-receipt.json"
OVERLAY = REPO / "Mallory/adapters/hbase/overlays/zk-tracker-monitor-v1"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
DIST = Path("/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib")
LANE = Path("/users/ZhenyuLi/.mallory-worktrees/hbase/lane2-v2")
OUTPUT = REPO / "data/mallory/cases/HBASE-27/campaigns/boot-order-monitor-v1-full"
RELEASE_ID = "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
RELEASE = REPO / "Mallory/dispatch/releases" / RELEASE_ID
TARGET_SOURCE = "hbase-server/src/main/java/org/apache/hadoop/hbase/regionserver/HRegionServer.java"
TEST_SOURCE = "hbase-server/src/test/java/org/apache/hadoop/hbase/TestClusterBootOrder.java"
TRACKER_SOURCE = "hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/ZKNodeTracker.java"
SOURCE_PINS = {
    TARGET_SOURCE: "c8a345ad34d12767d0277302ab705b9429626f0e8d7689fd493b2f81f8059023",
    TEST_SOURCE: "7ac0843f5cc522b4494fa2570f91ba334b70492da8bf73c58ea4d3baf9f0c630",
    TRACKER_SOURCE: "c30ebadfb0e12252ff9c0d6fcf056dd53dea7253744e230eddfefaad9a1dc1c3",
}


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(path: Path, expected: str) -> None:
    require(path.is_file(), f"missing pinned file: {path}")
    actual = sha(path)
    require(actual == expected, f"SHA mismatch for {path}: {actual}")


def preflight(on_node1: bool) -> None:
    config = json.loads(CONFIG.read_text())
    stage = json.loads(STAGE.read_text())
    healthy = json.loads((OVERLAY / "HBASE-27-monitor-v1-healthy.json").read_text())
    check(CONFIG, stage["config_sha256"])
    check(HERE / "run_full_node1.sh", stage["runner_sha256"])
    check(HERE / "verify_terminal.py", stage["verifier_sha256"])
    check(HERE / "preflight.py", stage["preflight_sha256"])
    require(stage["status"] == "staged_no_jvm" and stage["case_id"] == "HBASE-27",
            "wrong stage receipt")
    require(stage["output_path"] == str(OUTPUT) and stage["target_host"] == "node1",
            "wrong output or host")
    require(config["case_id"] == "HBASE-27" and config["system"] == "hbase" and
            config["cluster_test"] == "org.apache.hadoop.hbase.TestClusterBootOrder#testBootRegionServerFirst",
            "wrong selected JUnit")
    require(config["budget"] == {"trials": 80, "seconds": 3600,
                                 "max_faults_per_trial": 3,
                                 "trial_timeout_seconds": 600}, "wrong full budget")
    require(config["calibration_only"] is False and
            config["auto_promote_if_healthy"] is True and
            config["require_event_time_paths"] is True and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is False,
            "fault admission or graph path policy changed")
    for key in ("target", "command", "cwd", "site_file", "agent_jar",
                "agent_include", "agent_properties", "runtime_artifacts"):
        require(config[key] == healthy[key], f"{key} changed from staged overlay")
    require(config["target"]["check_sites"] == [
        "org.apache.hadoop.hbase.regionserver.HRegionServer#blockAndCheckIfStopped"
        "(Lorg/apache/hadoop/hbase/zookeeper/ZKNodeTracker;)V@1052:branch:2"] and
            config["target"]["throw_site"].endswith("@1053:throw:1") and
            config["target"]["exception_class"] == "java.io.IOException",
            "wrong exact target sites")

    check(OVERLAY / "HBASE-27-monitor-v1-healthy.json", stage["healthy_config_sha256"])
    check(OVERLAY / "HBASE-27-monitor-v1.sites.json", stage["site_sha256"])
    check(REPO / "Mallory/adapters/hbase/pilot/HBASE-27-boot-order-source-review-v1.json",
          stage["source_review_sha256"])
    site = json.loads((OVERLAY / "HBASE-27-monitor-v1.sites.json").read_text())
    require(any(d.get("clazz") == "org.apache.hadoop.hbase.zookeeper.ZKNodeTracker" and
                d.get("method") == "nodeCreated" and d.get("line") == 199
                for d in site["doors"]), "same-tracker callback read door missing")
    require(site["targets"][0]["line"] == 1052 and site["targets"][1]["line"] == 1053,
            "target site catalog changed")
    for relative, digest in SOURCE_PINS.items():
        check(SOURCE / relative, digest)
    guard = (SOURCE / TARGET_SOURCE).read_text()
    require("while (tracker.blockUntilAvailable(this.msgInterval, false) == null) {\n"
            "      if (this.stopped) {\n"
            "        throw new IOException(\"Received the shutdown message while waiting.\");"
            in guard, "exact stopped guard changed")
    test = (SOURCE / TEST_SOURCE).read_text()
    require("public void testBootRegionServerFirst() throws Exception {\n"
            "    startRegionServer();\n    startMaster();" in test,
            "selected test sequence changed")
    tracker = (SOURCE / TRACKER_SOURCE).read_text()
    require("boolean nodeExistsChecked = (!refresh || data != null);" in tracker and
            "abortable.abort(\"Unexpected exception handling nodeCreated event\", e);" in tracker,
            "tracker wait or callback semantics changed")
    check(DIST / "hbase-server-2.6.6.jar",
          "27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696")
    with zipfile.ZipFile(DIST / "hbase-server-2.6.6.jar") as jar:
        cls = jar.read("org/apache/hadoop/hbase/regionserver/HRegionServer.class")
    require(hashlib.sha256(cls).hexdigest() == config["expected_target_class_sha256"],
            "compiled target class changed")
    check(RELEASE / "manifest.json", config["core_release"]["manifest_sha256"])
    require(config["core_release"]["release_id"] == RELEASE_ID, "wrong core release")
    manifest = json.loads((RELEASE / "manifest.json").read_text())
    require(manifest["release_id"] == RELEASE_ID, "release manifest changed")
    for relative, digest in manifest["files"].items():
        check(RELEASE / relative, digest)
    check(REPO / "Mallory/instrumentation/releases/38658059f36552f513c78087db1c0b21caa97b48c599b886a15b124c9f4a41b9/mallory-agent.jar",
          config["runtime_artifacts"][0]["sha256"])
    check(OVERLAY / "releases/6705bdf484607cd5/adapter.jar",
          config["runtime_artifacts"][-1]["sha256"])
    check(REPO / "data/mallory/calibration_v2/HBASE-27/result.json",
          stage["prior_healthy_result_sha256"])
    check(REPO / "data/mallory/calibration_v2/HBASE-27/offline-causal-audit.json",
          stage["prior_healthy_audit_sha256"])
    prior = json.loads((REPO / "data/mallory/calibration_v2/HBASE-27/result.json").read_text())
    require(prior["status"] == "healthy_no_injectable_door" and
            prior["healthy_eligible_doors"] == 0 and
            prior["healthy_junit_validation"]["status"] == "passed",
            "prior path gap was overstated")
    if on_node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        require(Path(config["cwd"]).is_dir(), f"missing runtime cwd: {config['cwd']}")
        for artifact in config["runtime_artifacts"]:
            check(Path(artifact["path"]), artifact["sha256"])
        for relative, digest in SOURCE_PINS.items():
            check(Path(config["source_equivalent_root"]) / relative, digest)
    print("PASS HBASE-27 JVM-free preflight: source guard, selected JUnit, overlay, "
          "core and artifact SHAs, 80/3600/max3")


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
                "case_id": "HBASE-27", "kind": "static_preflight_gap",
                "status": "source_or_path_gap", "reason": str(exc),
                "jvm_started": False}, indent=2) + "\n")
        raise SystemExit(f"HBASE-27 static preflight gap: {exc}")


if __name__ == "__main__":
    main()
