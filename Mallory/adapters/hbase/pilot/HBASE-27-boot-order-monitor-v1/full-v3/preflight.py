#!/usr/bin/env python3
"""JVM-free admission check for the isolated HBASE-27 exploratory campaign."""

import argparse
import gzip
import hashlib
import json
import socket
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[5]
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
PRIOR = REPO / "data/mallory/calibration_hbase27_tracker_identity_v2/HBASE-27"
RELEASE_ID = "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
SOURCE_PINS = {
    "hbase-server/src/main/java/org/apache/hadoop/hbase/regionserver/HRegionServer.java":
        "c8a345ad34d12767d0277302ab705b9429626f0e8d7689fd493b2f81f8059023",
    "hbase-zookeeper/src/main/java/org/apache/hadoop/hbase/zookeeper/ZKNodeTracker.java":
        "c30ebadfb0e12252ff9c0d6fcf056dd53dea7253744e230eddfefaad9a1dc1c3",
    "hbase-server/src/test/java/org/apache/hadoop/hbase/TestClusterBootOrder.java":
        "7ac0843f5cc522b4494fa2570f91ba334b70492da8bf73c58ea4d3baf9f0c630",
}
PRIOR_PINS = {
    "result.json": "744bb62aee42d0f920564749a9fde7468cfa97341588ee3900acaedc2b9dc946",
    "trials/r0000/result.json": "e1758d7d6d3bfd9ff00f6269453a23a6a115a6b6161fd78b04fb59f918acb106",
    "trials/r0000/events.jsonl.gz": "b761f08ee5fa07e778af64cb6fba425d357bbd7370fc4eaa954812c5bdcb2014",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    require(path.is_file(), f"missing pinned file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(path, expected):
    actual = digest(path)
    require(actual == expected, f"SHA mismatch for {path}: {actual}")


def preflight(node1=False):
    config = json.loads((HERE / "config.json").read_text())
    stage = json.loads((HERE / "stage-receipt.json").read_text())
    require(stage["status"] == "staged_no_jvm" and stage["case_id"] == "HBASE-27",
            "wrong stage receipt")
    for name in ("config.json", "run_full_node1.sh", "verify_terminal.py", "preflight.py"):
        check(HERE / name, stage["stage_files_sha256"][name])
    require(config["case_id"] == "HBASE-27" and config["system"] == "hbase" and
            config["cluster_test"] ==
            "org.apache.hadoop.hbase.TestClusterBootOrder#testBootRegionServerFirst",
            "wrong case or cluster test")
    require(config["budget"] == {"trials": 80, "seconds": 3600,
                                 "max_faults_per_trial": 3,
                                 "trial_timeout_seconds": 600}, "wrong budget")
    require(config["calibration_only"] is False and
            config["auto_promote_if_healthy"] is True and
            config["require_event_time_paths"] is False and
            config["reject_coarse_roots"] is True and
            config["allow_local_timeline_doors"] is True,
            "exploration or graph-quality policy changed")
    require(config["target"]["check_sites"] == [
        "org.apache.hadoop.hbase.regionserver.HRegionServer#blockAndCheckIfStopped"
        "(Lorg/apache/hadoop/hbase/zookeeper/ZKNodeTracker;)V@1052:branch:2"] and
            config["target"]["throw_site"].endswith("@1053:throw:1") and
            config["target"]["exception_class"] == "java.io.IOException",
            "wrong exact target")
    require(config["expected_target_class_sha256"] ==
            "c1a746ab4b1aeac4744da76363b330c950b03fbfda9dfdcac7f57f64eb76270b",
            "target class pin changed")
    require(config["core_release"]["release_id"] == RELEASE_ID,
            "core release changed")
    release = REPO / "Mallory/dispatch/releases" / RELEASE_ID
    check(release / "manifest.json", config["core_release"]["manifest_sha256"])
    manifest = json.loads((release / "manifest.json").read_text())
    require(manifest["release_id"] == RELEASE_ID, "core manifest release changed")
    for name, expected in manifest["files"].items():
        check(release / name, expected)
    for name, expected in SOURCE_PINS.items():
        check(SOURCE / name, expected)
    server = (SOURCE / next(name for name in SOURCE_PINS if name.endswith("HRegionServer.java"))).read_text()
    tracker = (SOURCE / next(name for name in SOURCE_PINS if name.endswith("ZKNodeTracker.java"))).read_text()
    require('abortable.abort("Unexpected exception during initialization, aborting", e);'
            in tracker and 'if (isStopped()) {\n      LOG.info("Skipping run; stopped");'
            in server and 'blockAndCheckIfStopped(this.masterAddressTracker);' in server and
            'blockAndCheckIfStopped(this.clusterStatusTracker);' in server,
            "source fault or target path changed")
    compiled = REPO.parent / ".baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar"
    check(compiled, "27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696")
    with zipfile.ZipFile(compiled) as jar:
        target_class = jar.read("org/apache/hadoop/hbase/regionserver/HRegionServer.class")
    require(hashlib.sha256(target_class).hexdigest() ==
            config["expected_target_class_sha256"], "target bytecode changed")
    local_jar = REPO / "Mallory/adapters/hbase/overlays/zk-tracker-monitor-v1/releases/fb2835d2b2bcd3d3/adapter.jar"
    check(local_jar, "fb2835d2b2bcd3d338011f0120685e51c6c28e2f7c87b3f0284c9465726e021e")
    site = REPO / "Mallory/adapters/hbase/overlays/zk-tracker-monitor-v1/HBASE-27-monitor-v1.sites.json"
    check(site, "04a3b1ffe92c8fe35bb7d24e275dc8b0973cd9f284eef4840eaffa25543ca69c")
    require(any(row.get("clazz") == "org.apache.hadoop.hbase.zookeeper.ZKNodeTracker"
                and row.get("method") == "start" and row.get("line") == 75
                for row in json.loads(site.read_text())["doors"]),
            "typed startup door missing")

    if node1:
        require(socket.gethostname().split(".")[0] == "node1", "wrong host")
        require(Path(config["cwd"]).is_dir(), "missing runtime cwd")
        for item in config["runtime_artifacts"]:
            check(Path(item["path"]), item["sha256"])
        for name, expected in PRIOR_PINS.items():
            check(PRIOR / name, expected)
        prior = json.loads((PRIOR / "result.json").read_text())
        require(prior["status"] == "calibration_complete" and
                prior["healthy_seed_valid"] is True and
                prior["runtime_attestation"]["bound_nodes"] == ["rs0"] and
                prior["healthy_junit_validation"]["tests"] == 1 and
                prior["healthy_junit_validation"]["failures"] == 0 and
                prior["healthy_junit_validation"]["errors"] == 0 and
                prior["healthy_eligible_doors"] == 4,
                "fresh healthy JUnit/actor/door gate failed")
        events = [json.loads(row) for row in
                  gzip.open(PRIOR / "trials/r0000/events.jsonl.gz", "rt")]
        by_seq = {row["seq"]: row for row in events}
        for seq in (5, 6):
            row = by_seq[seq]
            require(row["type"] == "DOOR_OBSERVED" and row["node"] == "master0"
                    and "ZKNodeTracker#start()V@75" in row["site"] and
                    row["exception_class"] ==
                    "org.apache.zookeeper.KeeperException$ConnectionLossException",
                    "source-backed master0 startup door missing")
        require(by_seq[7]["type"] == "TARGET_CHECK" and by_seq[7]["node"] == "rs0",
                "named rs0 check did not follow master0 startup door")
    print("PASS HBASE-27 full-v3 JVM-free preflight: pinned source/runtime, "
          "80/3600/max3 and fresh healthy actor/typed-door gate")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--node1", action="store_true")
    parser.add_argument("--outcome", type=Path)
    args = parser.parse_args()
    try:
        preflight(args.node1)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        if args.outcome:
            args.outcome.parent.mkdir(parents=True, exist_ok=True)
            args.outcome.write_text(json.dumps({"schema_version": 1,
                "case_id": "HBASE-27", "kind": "static_preflight_gap",
                "status": "source_or_path_gap", "reason": str(exc),
                "jvm_started": False}, indent=2) + "\n")
        raise SystemExit(f"HBASE-27 full-v3 static preflight gap: {exc}")
