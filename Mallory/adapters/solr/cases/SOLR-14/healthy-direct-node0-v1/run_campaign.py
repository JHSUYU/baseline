#!/usr/bin/env python3
"""Preflight and GO-gated one-trial SOLR-14 healthy observation on node0."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
OUT = ROOT / "data/mallory/solr14_direct_healthy_v1_node0/SOLR-14/healthy"
CONFIG = HERE / "config-healthy-node0.json"
SITES = HERE / "sites.json"
REQUEST = HERE / "admission-request.json"
GO = HERE / "admission-healthy-node0.json"
CHECK = ("org.apache.solr.cloud.api.collections.SplitShardCmd"
         "#split(Lorg/apache/solr/common/cloud/ClusterState;"
         "Lorg/apache/solr/common/cloud/ZkNodeProps;"
         "Lorg/apache/solr/common/util/NamedList;)Z@165:branch:5")
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def preflight() -> dict:
    manifest = read(HERE / "sha-manifest.json")
    if manifest["case_id"] != "SOLR-14":
        raise ValueError("wrong case-local manifest")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local package changed: {name}")
    config, sites, request = read(CONFIG), read(SITES), read(REQUEST)
    if (request.get("go") is not False or request.get("execution_status") != "not_launched"
            or request.get("case_id") != "SOLR-14" or request.get("host") != "node0"
            or request.get("mode") != "healthy"
            or request.get("runner_sha256") != sha(Path(__file__))
            or request.get("config_sha256") != sha(CONFIG)
            or request.get("intended_output") != str(OUT)):
        raise ValueError("healthy-only dispatch request changed")
    if (config["case_id"] != "SOLR-14" or config["system"] != "solr"
            or config["cluster_test"] != "org.apache.solr.cloud.SplitShardTest#doTest"
            or config["target"]["check_sites"] != [CHECK]
            or config["target"]["throw_site"] != CHECK.split("@", 1)[0] + "@167:throw:1"
            or config["site_file"] != str(SITES)
            or config["core_release"] != str(RELEASE)
            or not Path(campaign.__file__).resolve().is_relative_to(RELEASE)):
        raise ValueError("target, JUnit, or frozen core changed")
    if (config["budget"] != {"trials": 1, "seconds": 600,
                             "max_faults_per_trial": 1, "trial_timeout_seconds": 480}
            or config["calibration_only"] is not True
            or config["auto_promote_if_healthy"] is not False
            or config["agent_properties"]["auto.io.doors"] is not False
            or config["fault_types"] != ["EXCEPTION"]
            or config["allow_local_timeline_doors"] is not True
            or config["require_event_time_paths"] is not False
            or config["reject_coarse_roots"] is not True
            or config["cwd"] != str(SOURCE)
            or config["source_equivalent_root"] != str(SOURCE)
            or config["command"][1] != str(ROOT / "Mallory/adapters/solr/releases/v38/run_pilot.py")
            or config["command"][4] != str(SOURCE)):
        raise ValueError("healthy-only execution or I/O scope changed")
    expected = [
        (130, "org.apache.solr.common.cloud.ZkStateReader#forceUpdateCollection(Ljava/lang/String;)V"),
        (164, "org.apache.solr.common.cloud.SolrZkClient#exists"
              "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Z)Lorg/apache/zookeeper/data/Stat;"),
    ]
    if len(sites["doors"]) != 2 or [(x["line"], x["callee"]) for x in sites["doors"]] != expected:
        raise ValueError("typed pretarget I/O frontier changed")
    if any(x.get("class") != "org.apache.solr.cloud.api.collections.SplitShardCmd"
           or x.get("method") != "split"
           or x.get("exception_class") != "org.apache.zookeeper.KeeperException$ConnectionLossException"
           for x in sites["doors"]):
        raise ValueError("typed I/O rule changed")
    if {(x["clazz"], x["method"], x["line"]) for x in sites["targets"]} != {
            ("org.apache.solr.cloud.api.collections.SplitShardCmd", "split", 165),
            ("org.apache.solr.cloud.api.collections.SplitShardCmd", "split", 167)}:
        raise ValueError("exact target site catalog changed")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if not path.is_file() or sha(path) != artifact["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    if (subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                                text=True).strip() !=
            "e27f44e3d78dfcec230c97e0a1240e3751daeff9"
            or subprocess.check_output(["git", "-C", str(SOURCE), "status", "--porcelain"],
                                       text=True).strip()):
        raise ValueError("Solr source revision or cleanliness changed")
    target = SOURCE / config["target"]["source_path"]
    junit = SOURCE / "solr/core/src/test/org/apache/solr/cloud/SplitShardTest.java"
    if (sha(target) != config["mapping"]["target_source_sha256"]
            or sha(junit) != config["mapping"]["test_source_sha256"]):
        raise ValueError("selected source or JUnit changed")
    lines = target.read_text(encoding="utf-8").splitlines()
    for line, fragment in {130: "forceUpdateCollection(collectionName)",
                           164: "getZkClient().exists(",
                           165: "if (leaderZnodeStat == null)",
                           167: "throw new SolrException"}.items():
        if fragment not in lines[line - 1]:
            raise ValueError(f"selected source line moved: {line}")
    if "configureCluster(1)" not in junit.read_text(encoding="utf-8"):
        raise ValueError("MiniSolrCloudCluster setup changed")
    jar = Path(config["mapping"]["compiled_jar"])
    if sha(jar) != config["mapping"]["compiled_jar_sha256"]:
        raise ValueError("compiled Solr JAR changed")
    with zipfile.ZipFile(jar) as archive:
        member = archive.read("org/apache/solr/cloud/api/collections/SplitShardCmd.class")
    if hashlib.sha256(member).hexdigest() != config["mapping"]["compiled_class_sha256"]:
        raise ValueError("compiled SplitShardCmd changed")
    campaign.validate_config(config)
    return {"config_sha256": sha(CONFIG), "site_sha256": sha(SITES),
            "runner_sha256": sha(Path(__file__)),
            "core_manifest_sha256": sha(RELEASE / "manifest.json"),
            "intended_output": str(OUT)}


def check_go(path: Path, metadata: dict) -> str:
    if path.resolve() != GO:
        raise ValueError("case-local node0 GO receipt required")
    receipt = read(path)
    if (receipt.get("go") is not True or receipt.get("host") != "node0"
            or receipt.get("case_id") != "SOLR-14" or receipt.get("mode") != "healthy"
            or receipt.get("config_sha256") != metadata["config_sha256"]
            or receipt.get("runner_sha256") != metadata["runner_sha256"]
            or receipt.get("intended_output") != str(OUT)):
        raise ValueError("dispatch GO receipt absent or mismatched")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("healthy",), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight()
    if args.preflight_only:
        print(json.dumps({"preflight": "passed_static_only", "case_id": "SOLR-14",
                          "mode": "healthy", "go": False, **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    metadata["admission_sha256"] = check_go(args.admission_receipt, metadata)
    if socket.gethostname().split(".", 1)[0] != "node0" or OUT.exists():
        raise ValueError("node0 and a fresh healthy output are required")
    lock_root = Path("/tmp/mallory-lanes")
    lock_root.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_root / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        if OUT.exists() or shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("fresh output and at least 7,650,410,496 free bytes required")
        available = next(int(row.split()[1]) for row in Path("/proc/meminfo").read_text().splitlines()
                         if row.startswith("MemAvailable:"))
        if available < 8_388_608:
            raise ValueError("at least 8,388,608 KiB MemAvailable required")
        processes = subprocess.check_output(["ps", "-eo", "user=,comm="], text=True)
        if any(row.split() == [getpass.getuser(), "java"] for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node0")
        print(json.dumps({"preflight": "passed", "case_id": "SOLR-14",
                          "mode": "healthy", **metadata}, sort_keys=True), flush=True)
        state = campaign.run(CONFIG, OUT, calibration_only=True)
    finally:
        for handle in reversed(handles):
            handle.close()
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
