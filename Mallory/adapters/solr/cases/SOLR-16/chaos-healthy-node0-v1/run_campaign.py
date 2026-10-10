#!/usr/bin/env python3
"""Pinned, dispatch-gated SOLR-16 chaos JUnit healthy observation on node0."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
SOLR = HERE.parents[2]
RELEASE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
RESOURCE_AGENT = ROOT / ("Mallory/instrumentation/releases/"
                         "b4bb6493699d87dceb966ff63b6f727455e5afdbbe1ddce4cd2247faab17eae4")
OUT = ROOT / "data/mallory/solr16_chaos_healthy_node0_v1/healthy"
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402

SELECTOR = "org.apache.solr.cloud.api.collections.ShardSplitTest#testSplitWithChaosMonkey"
REGION = ("org.apache.solr.cloud.api.collections.SplitShardCmd#split("
          "Lorg/apache/solr/common/cloud/ClusterState;"
          "Lorg/apache/solr/common/cloud/ZkNodeProps;"
          "Lorg/apache/solr/common/util/NamedList;)Z")
CHECK = REGION + "@539:branch:41"
THROW = REGION + "@543:throw:1"
FIRST = REGION + "@164:door:2"
SECOND = REGION + "@523:door:3"
NATIVE = ("org.apache.solr.common.cloud.SolrZkClient#lambda$exists$2("
          "Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)"
          "Lorg/apache/zookeeper/data/Stat;@301:door:1")
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def preflight() -> dict:
    manifest = read(HERE / "sha-manifest.json")
    config_path = HERE / "config-healthy-node0.json"
    config = read(config_path)
    if (manifest.get("case_id") != "SOLR-16"
            or manifest.get("cluster_test") != SELECTOR
            or manifest.get("exact_check_site") != CHECK
            or manifest.get("exact_throw_site") != THROW
            or manifest.get("typed_door_site") != NATIVE
            or manifest.get("typed_exception_class") != EXCEPTION
            or sha(RELEASE / "manifest.json") != manifest.get("core_manifest_sha256")):
        raise ValueError("wrong case, target, workload, or core release")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local file changed: {name}")
    for name, expected in read(RELEASE / "manifest.json")["files"].items():
        if sha(RELEASE / name) != expected:
            raise ValueError(f"core release changed: {name}")
    if not Path(campaign.__file__).resolve().is_relative_to(RELEASE):
        raise ValueError("campaign was not loaded from the pinned core release")

    source = Path(config["cwd"])
    source_revision = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    source_dirty = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain"], text=True).strip()
    inventory = read(HERE / "inventory.json")["cases"][0]
    workload = inventory["workload"]
    sites = read(HERE / "sites.json")
    resource_agent = read(RESOURCE_AGENT / "manifest.json")
    if (resource_agent.get("release_id") != RESOURCE_AGENT.name
            or resource_agent.get("agent_sha256") != sha(RESOURCE_AGENT / "mallory-agent.jar")
            or resource_agent.get("test_results", {}).get("tests", 0) < 26
            or resource_agent.get("test_results", {}).get("failures") != 0
            or resource_agent.get("test_results", {}).get("errors") != 0
            or not any("lambda$exists$2 first String path" in feature
                       for feature in resource_agent.get("features", []))):
        raise ValueError("resource-aware agent release is unverified")
    if (config.get("case_id") != "SOLR-16"
            or config.get("cluster_test") != SELECTOR
            or config.get("command", [None, None, None])[1:3] !=
            [str(HERE / "run_pilot.py"), "SOLR-16"]
            or config.get("site_file") != str(HERE / "sites.json")
            or config.get("target", {}).get("check_sites") != [CHECK]
            or config["target"].get("throw_site") != THROW
            or config.get("exact_check_location") !=
            "solr/core/src/java/org/apache/solr/cloud/api/collections/SplitShardCmd.java:543"
            or config.get("budget") != {"trials": 1, "seconds": 600,
                                        "max_faults_per_trial": 1,
                                        "trial_timeout_seconds": 480}
            or config.get("calibration_only") is not True
            or config.get("auto_promote_if_healthy") is not False
            or config.get("fault_types") != ["EXCEPTION"]
            or config.get("env", {}).get("MALLORY_SOLR_NIGHTLY") != "1"
            or config.get("agent_jar") != str(RESOURCE_AGENT / "mallory-agent.jar")
            or config.get("env", {}).get("MALLORY_SOLR_AGENT_JAR") !=
            str(RESOURCE_AGENT / "mallory-agent.jar")
            or config.get("core_release") != str(RELEASE)
            or config.get("target_absent_bootstrap", {}).get("door_sites") !=
            [FIRST, SECOND, NATIVE]
            or inventory.get("case_id") != "SOLR-16"
            or workload.get("selected_selector") != SELECTOR
            or source_revision != config["mapping"]["source_git_revision"]
            or source_dirty):
        raise ValueError("isolated healthy configuration or source revision changed")
    if (config["target_absent_bootstrap"]["max_trials"] != 1
            or config["target_absent_bootstrap"]["max_faults_per_trial"] != 1
            or not any(row.get("class") == "org.apache.solr.common.cloud.SolrZkClient"
                       and row.get("method") == "lambda$exists$2"
                       and row.get("line") == 301
                       and row.get("callee") ==
                       "org.apache.solr.common.cloud.SolrZooKeeper#exists("
                       "Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)"
                       "Lorg/apache/zookeeper/data/Stat;"
                       and row.get("exception_class") == EXCEPTION
                       for row in sites["doors"])
            or {539, 543} != {row["line"] for row in sites["targets"]}
            or not {"org.apache.solr.cloud.api.collections.SplitShardCmd",
                    "org.apache.solr.common.cloud.SolrZkClient"}.issubset(
                        set(config["agent_include"]))):
        raise ValueError("typed native exists door or exact target changed")
    for row in config["runtime_artifacts"]:
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    test_source = source / workload["test_source_path"]
    target_source = source / config["target"]["source_path"]
    solrj_source = source / "solr/solrj/src/java/org/apache/solr/common/cloud/SolrZkClient.java"
    if (sha(test_source) != workload["candidates"][0]["source_sha256"]
            or sha(test_source) != manifest["test_source_sha256"]
            or sha(target_source) != config["mapping"]["target_source_sha256"]
            or sha(solrj_source) != config["mapping"]["solr_zk_client_source_sha256"]
            or "keeper.exists(" not in solrj_source.read_text().splitlines()[300]
            or "getZkClient().exists(" not in target_source.read_text().splitlines()[163]
            or "getZkClient().exists(" not in target_source.read_text().splitlines()[522]):
        raise ValueError("pinned JUnit or leader lookup source changed")
    with zipfile.ZipFile(config["mapping"]["compiled_jar"]) as archive:
        target_hash = hashlib.sha256(archive.read(
            "org/apache/solr/cloud/api/collections/SplitShardCmd.class")).hexdigest()
    with zipfile.ZipFile(config["mapping"]["solrj_compiled_jar"]) as archive:
        solrj_hash = hashlib.sha256(archive.read(
            "org/apache/solr/common/cloud/SolrZkClient.class")).hexdigest()
    if (target_hash != config["expected_target_class_sha256"]
            or target_hash != manifest["target_class_sha256"]
            or solrj_hash != config["mapping"]["solr_zk_client_class_sha256"]):
        raise ValueError("pinned target or native-door bytecode changed")
    campaign.validate_config(config)
    request = read(HERE / "admission-request.json")
    if (request.get("go") is not False or request.get("execution_status") != "not_launched"
            or request.get("case_id") != "SOLR-16" or request.get("host") != "node0"
            or request.get("mode") != "healthy"
            or request.get("config_sha256") != sha(config_path)
            or request.get("runner_sha256") != sha(Path(__file__))
            or request.get("intended_output") != str(OUT)):
        raise ValueError("staged admission request changed")
    return {"case_id": "SOLR-16", "mode": "healthy",
            "config_sha256": sha(config_path), "runner_sha256": sha(Path(__file__)),
            "manifest_sha256": sha(HERE / "sha-manifest.json"),
            "source_revision": source_revision, "intended_output": str(OUT)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("healthy",), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight()
    if args.preflight_only:
        print(json.dumps({"preflight": "passed", "go": False, **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("case-local dispatch GO receipt required before starting a JVM")
    receipt_path = (HERE / "admission-healthy-node0.json").resolve()
    if args.admission_receipt.resolve() != receipt_path:
        raise ValueError("wrong dispatch GO receipt path")
    receipt = read(receipt_path)
    if (receipt.get("go") is not True or receipt.get("host") != "node0"
            or receipt.get("case_id") != "SOLR-16" or receipt.get("mode") != "healthy"
            or receipt.get("config_sha256") != metadata["config_sha256"]
            or receipt.get("runner_sha256") != metadata["runner_sha256"]
            or receipt.get("intended_output") != str(OUT)):
        raise ValueError("dispatch GO receipt absent or mismatched")
    if socket.gethostname().split(".", 1)[0] != "node0" or OUT.exists():
        raise ValueError("node0 and fresh output are required")
    lock_root = Path("/tmp/mallory-lanes")
    lock_root.mkdir(parents=True, exist_ok=True)
    locks = []
    try:
        for name in ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_root / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locks.append(handle)
        if OUT.exists():
            raise ValueError("healthy output appeared while acquiring locks")
        state = campaign.run(HERE / "config-healthy-node0.json", OUT)
    finally:
        for handle in reversed(locks):
            handle.close()
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return subprocess.run([sys.executable, str(HERE / "audit_healthy.py"), str(OUT)],
                          check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
