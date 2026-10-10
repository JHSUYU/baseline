#!/usr/bin/env python3
"""GO-gated unchanged SOLR-34 JUnit, with a pinned path-aware healthy seed."""

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
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
RELEASE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
CONFIG = HERE / "config-healthy-node1.json"
SITES = HERE / "sites.json"
REQUEST = HERE / "admission-request.json"
GO = HERE / "admission-healthy-node1.json"
OUT = ROOT / "data/mallory/solr34_healthy_path_node1_v4/SOLR-34"
REGION = ("org.apache.solr.servlet.CoordinatorHttpSolrCall"
          "#getCore(Lorg/apache/solr/servlet/CoordinatorHttpSolrCall$Factory;"
          "Lorg/apache/solr/servlet/HttpSolrCall;Ljava/lang/String;Z)"
          "Lorg/apache/solr/core/SolrCore;")
CHECK = REGION + "@139:branch:6"
THROW = REGION + "@143:throw:1"
NATIVE = ("org.apache.solr.common.cloud.SolrZkClient#lambda$getData$6"
          "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
          "Lorg/apache/zookeeper/data/Stat;)[B@349:door:1")
AGENT_RELEASE = ROOT / "Mallory/instrumentation/releases/b4bb6493699d87dceb966ff63b6f727455e5afdbbe1ddce4cd2247faab17eae4"
PILOT = HERE / "run_pilot.py"
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def preflight() -> dict:
    manifest = read(HERE / "sha-manifest.json")
    if manifest.get("case_id") != "SOLR-34":
        raise ValueError("wrong package case")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local package changed: {name}")
    config, sites, request = read(CONFIG), read(SITES), read(REQUEST)
    if (request.get("go") is not False or request.get("execution_status") != "not_launched"
            or request.get("case_id") != "SOLR-34" or request.get("host") != "node1"
            or request.get("mode") != "healthy"
            or request.get("config_sha256") != sha(CONFIG)
            or request.get("runner_sha256") != sha(Path(__file__))
            or request.get("intended_output") != str(OUT)):
        raise ValueError("healthy dispatch request changed")
    if (config.get("case_id") != "SOLR-34"
            or config.get("cluster_test") != "org.apache.solr.search.TestCoordinatorRole#testSimple"
            or config["target"]["check_sites"] != [CHECK]
            or config["target"]["throw_site"] != THROW
            or config.get("site_file") != str(SITES)
            or config.get("core_release") != str(RELEASE)
            or not Path(campaign.__file__).resolve().is_relative_to(RELEASE)):
        raise ValueError("exact target, JUnit, or frozen core changed")
    if (config["budget"] != {"trials": 1, "seconds": 600,
                             "max_faults_per_trial": 1, "trial_timeout_seconds": 480}
            or config.get("calibration_only") is not True
            or config.get("auto_promote_if_healthy") is not False
            or config["agent_properties"]["auto.io.doors"] is not False
            or config.get("fault_types") != ["EXCEPTION"]
            or config.get("target_absent_bootstrap") != {
                "door_sites": [NATIVE], "max_trials": 1,
                "max_doors_per_trial": 1, "max_faults_per_trial": 1}
            or config.get("require_site_catalog") is not True
            or config.get("agent_jar") != str(AGENT_RELEASE / "mallory-agent.jar")
            or config.get("command", [None, None])[1] != str(PILOT)
            or config.get("env", {}).get("MALLORY_SOLR_AGENT_JAR") != str(AGENT_RELEASE / "mallory-agent.jar")
            or config.get("cwd") != str(SOURCE)
            or config.get("source_equivalent_root") != str(SOURCE)):
        raise ValueError("healthy path-aware scope changed")
    if (len(sites["doors"]) != 1 or sites["doors"][0] != {
            "callee": "org.apache.solr.common.cloud.SolrZooKeeper#getData"
                      "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                      "Lorg/apache/zookeeper/data/Stat;)[B",
            "class": "org.apache.solr.common.cloud.SolrZkClient",
            "descriptor": "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                          "Lorg/apache/zookeeper/data/Stat;)[B",
            "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException",
            "line": 349, "method": "lambda$getData$6"}
            or {(x["clazz"], x["method"], x["line"]) for x in sites["targets"]} != {
                ("org.apache.solr.servlet.CoordinatorHttpSolrCall", "getCore", 139),
                ("org.apache.solr.servlet.CoordinatorHttpSolrCall", "getCore", 143)}):
        raise ValueError("typed native path door or exact target catalog changed")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if not path.is_file() or sha(path) != artifact["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    if (not any(row["path"] == str(PILOT) and row["sha256"] == sha(PILOT)
                for row in config["runtime_artifacts"])
            or not any(row["path"] == str(AGENT_RELEASE / "mallory-agent.jar")
                       and row["sha256"] == config["mapping"]["agent_sha256"]
                       for row in config["runtime_artifacts"])):
        raise ValueError("case-local pilot or path-aware agent not pinned")
    # Importing the pilot is safe offline; its validator refuses the old v38 agent.
    import run_pilot
    if (run_pilot.AGENT != AGENT_RELEASE / "mallory-agent.jar"
            or run_pilot.SITES != SITES):
        raise ValueError("case-local pilot does not bind the typed path door")
    if (subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                                text=True).strip() !=
            "e27f44e3d78dfcec230c97e0a1240e3751daeff9"
            or subprocess.check_output(["git", "-C", str(SOURCE), "status", "--porcelain"],
                                       text=True).strip()):
        raise ValueError("Solr source revision or cleanliness changed")
    target = SOURCE / config["target"]["source_path"]
    test = SOURCE / "solr/core/src/test/org/apache/solr/search/TestCoordinatorRole.java"
    client = SOURCE / "solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java"
    if (sha(target) != config["mapping"]["target_source_sha256"]
            or sha(test) != config["mapping"]["test_source_sha256"]
            or sha(client) != config["mapping"]["solr_zk_client_source_sha256"]):
        raise ValueError("selected target, JUnit, or native door source changed")
    lines = target.read_text(encoding="utf-8").splitlines()
    if ("if (syntheticColl == null)" not in lines[137]
            or "if (createException != null)" not in lines[138]
            or "throw createException" not in lines[139]
            or "throw new SolrException" not in lines[142]
            or "keeper.getData(" not in client.read_text(encoding="utf-8").splitlines()[348]
            or "public void testSimple()" not in test.read_text(encoding="utf-8")):
        raise ValueError("selected source structure changed")
    for jar_key, member, expected_key in (
            ("compiled_jar", "org/apache/solr/servlet/CoordinatorHttpSolrCall.class",
             "compiled_class_sha256"),
            ("solrj_compiled_jar", "org/apache/solr/common/cloud/SolrZkClient.class",
             "solr_zk_client_class_sha256")):
        jar = Path(config["mapping"][jar_key])
        jar_hash_key = "compiled_jar_sha256" if jar_key == "compiled_jar" else "solrj_compiled_jar_sha256"
        if sha(jar) != config["mapping"][jar_hash_key]:
            raise ValueError(f"compiled JAR changed: {jar}")
        with zipfile.ZipFile(jar) as archive:
            if hashlib.sha256(archive.read(member)).hexdigest() != config["mapping"][expected_key]:
                raise ValueError(f"compiled class changed: {member}")
    campaign.validate_config(config)
    return {"config_sha256": sha(CONFIG), "runner_sha256": sha(Path(__file__)),
            "site_sha256": sha(SITES), "core_manifest_sha256": sha(RELEASE / "manifest.json"),
            "intended_output": str(OUT)}


def check_go(path: Path, metadata: dict) -> str:
    if path.resolve() != GO:
        raise ValueError("case-local node1 GO receipt required")
    receipt = read(path)
    expected = {"go": True, "host": "node1", "case_id": "SOLR-34",
                "mode": "healthy", "config_sha256": metadata["config_sha256"],
                "runner_sha256": metadata["runner_sha256"],
                "intended_output": str(OUT)}
    if any(receipt.get(key) != value for key, value in expected.items()):
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
        print(json.dumps({"preflight": "passed_static_only", "case_id": "SOLR-34",
                          "mode": "healthy", "go": False, **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    metadata["admission_sha256"] = check_go(args.admission_receipt, metadata)
    if socket.gethostname().split(".", 1)[0] != "node1" or OUT.exists():
        raise ValueError("node1 and fresh output required")
    lock_root = Path("/tmp/mallory-lanes")
    lock_root.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("zookeeper-node1-source.lock", "solr-node1-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_root / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        if OUT.exists() or shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("fresh output and 7,650,410,496 free bytes required")
        available = next(int(row.split()[1]) for row in Path("/proc/meminfo").read_text().splitlines()
                         if row.startswith("MemAvailable:"))
        if available < 8_388_608:
            raise ValueError("8,388,608 KiB MemAvailable required")
        processes = subprocess.check_output(["ps", "-eo", "user=,comm="], text=True)
        if any(row.split() == [getpass.getuser(), "java"] for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node1")
        print(json.dumps({"preflight": "passed", "case_id": "SOLR-34",
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
