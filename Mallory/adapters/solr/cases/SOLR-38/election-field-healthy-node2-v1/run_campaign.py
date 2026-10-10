#!/usr/bin/env python3
"""Offline preflight and GO-gated SOLR-38 election/field healthy probe."""

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
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
OUT = ROOT / "data/mallory/solr38_election_field_healthy_v1_node2/SOLR-38/healthy"
CONFIG = HERE / "config-healthy-node2.json"
SITES = HERE / "sites.json"
GO = HERE / "admission-healthy-node2.json"
ADAPTER = HERE / "adapter-election-v1/mallory-solr-election-adapter.jar"
FIELD = "org.apache.solr.cloud.CloudDescriptor#isLeader"
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def preflight() -> dict:
    manifest = read(HERE / "sha-manifest.json")
    if manifest.get("case_id") != "SOLR-38":
        raise ValueError("wrong package manifest")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local package changed: {name}")
    config, sites, request = read(CONFIG), read(SITES), read(HERE / "admission-request.json")
    if (request.get("case_id") != "SOLR-38" or request.get("go") is not False
            or request.get("execution_status") != "not_launched"
            or request.get("host") != "node2" or request.get("mode") != "healthy"
            or request.get("config_sha256") != sha(CONFIG)
            or request.get("runner_sha256") != sha(Path(__file__))
            or request.get("intended_output") != str(OUT)):
        raise ValueError("healthy-only admission request changed")
    if (config.get("case_id") != "SOLR-38"
            or config.get("cluster_test") !=
            "org.apache.solr.client.solrj.impl.CloudHttp2SolrClientTest#testAliasHandling"
            or config.get("site_file") != str(SITES)
            or config.get("core_release") != str(RELEASE)
            or not Path(campaign.__file__).resolve().is_relative_to(RELEASE)
            or config["command"][1] !=
            str(ROOT / "Mallory/adapters/solr/releases/v38/run_pilot.py")
            or config["command"][4] != str(SOURCE)
            or config["cwd"] != str(SOURCE)
            or config["source_equivalent_root"] != str(SOURCE)):
        raise ValueError("selected JUnit, source checkout, or core changed")
    if (config["budget"] != {"trials": 1, "seconds": 600,
                             "max_faults_per_trial": 1, "trial_timeout_seconds": 480}
            or config["calibration_only"] is not True
            or config["auto_promote_if_healthy"] is not False
            or config["agent_properties"]["auto.io.doors"] is not False
            or config["agent_properties"]["state.fields"] is not True
            or config["agent_properties"]["adapter.jar"] != str(ADAPTER)
            or config["fault_types"] != ["EXCEPTION"]
            or config["require_event_time_paths"] is not False
            or config["reject_coarse_roots"] is not True):
        raise ValueError("probe scope or healthy-only budget changed")
    expected = [("waitForReplicasToComeUp", 396, "(I)Z"),
                ("areAllReplicasParticipating", 450, "()Z")]
    if ([(row["method"], row["line"], row["descriptor"]) for row in sites["doors"]]
            != expected):
        raise ValueError("election door sites changed")
    for row in sites["doors"]:
        if (row["class"] != "org.apache.solr.cloud.ShardLeaderElectionContext"
                or row["callee"] != "org.apache.solr.common.cloud.SolrZkClient#getChildren"
                "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Z)Ljava/util/List;"
                or row["exception_class"] !=
                "org.apache.zookeeper.KeeperException$ConnectionLossException"):
            raise ValueError("typed election I/O changed")
    if not {"org.apache.solr.cloud.ShardLeaderElectionContext",
            "org.apache.solr.cloud.CloudDescriptor",
            "org.apache.solr.update.processor.DistributedZkUpdateProcessor"}.issubset(
                config["agent_include"]):
        raise ValueError("election, field, or target class missing from instrumentation")
    region_names = {(x["clazz"], x["method"]) for x in sites["regions"]}
    if not {("org.apache.solr.cloud.ShardLeaderElectionContext", "runLeaderProcess"),
            ("org.apache.solr.cloud.CloudDescriptor", "isLeader"),
            ("org.apache.solr.cloud.CloudDescriptor", "setLeader"),
            ("org.apache.solr.update.processor.DistributedZkUpdateProcessor",
             "doDefensiveChecks")}.issubset(region_names):
        raise ValueError("field/target region tracing changed")
    checks = config["target"]["check_sites"]
    if (len(checks) != 4 or any("#doDefensiveChecks" not in row or
                               "@1021:branch:" not in row for row in checks)
            or not config["target"]["throw_site"].endswith("@1025:throw:1")):
        raise ValueError("exact SOLR-38 guard changed")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        if not path.is_file() or sha(path) != artifact["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    agent = Path(config["agent_jar"])
    with zipfile.ZipFile(agent) as archive:
        probe = archive.read("edu/uva/liftlab/mallory/instrumentation/Probe.class")
    if not all(token in probe for token in (b"thread_id", b"stateRead", b"stateWrite")):
        raise ValueError("pinned agent lacks thread identity or field event probes")
    release_manifest = read(Path(config["mapping"]["agent_build"]["release_manifest"]))
    if "numeric_thread_id_on_causal_events" not in release_manifest["features"]:
        raise ValueError("pinned agent release lacks numeric thread identity")
    if (subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"],
                                text=True).strip() !=
            "e27f44e3d78dfcec230c97e0a1240e3751daeff9"
            or subprocess.check_output(["git", "-C", str(SOURCE),
                                        "status", "--porcelain"], text=True).strip()):
        raise ValueError("Solr source revision or cleanliness changed")
    paths = {
        "target_source_sha256": "solr/core/src/java/org/apache/solr/update/processor/DistributedZkUpdateProcessor.java",
        "election_source_sha256": "solr/core/src/java/org/apache/solr/cloud/ShardLeaderElectionContext.java",
        "cloud_descriptor_source_sha256": "solr/core/src/java/org/apache/solr/cloud/CloudDescriptor.java",
        "test_source_sha256": "solr/solrj/src/test/org/apache/solr/client/solrj/impl/CloudHttp2SolrClientTest.java",
    }
    for key, rel in paths.items():
        if sha(SOURCE / rel) != config["mapping"][key]:
            raise ValueError(f"Solr source changed: {key}")
    election = (SOURCE / paths["election_source_sha256"]).read_text().splitlines()
    target = (SOURCE / paths["target_source_sha256"]).read_text().splitlines()
    cloud = (SOURCE / paths["cloud_descriptor_source_sha256"]).read_text().splitlines()
    for line, fragment in {123: "waitForReplicasToComeUp", 264: "setLeader(true)",
                           396: "zkClient.getChildren", 397: "catch (KeeperException",
                           450: "zkClient.getChildren", 451: "catch (KeeperException"}.items():
        if fragment not in election[line - 1]:
            raise ValueError(f"election source site moved: {line}")
    if ("volatile boolean isLeader" not in cloud[42]
            or "return isLeader" not in cloud[96]
            or "this.isLeader = isLeader" not in cloud[100]
            or "cloudDesc.isLeader()" not in target[981]
            or "cloudDesc.isLeader()" not in target[1012]
            or "if ((isLeader && !localIsLeader)" not in target[1020]):
        raise ValueError("leader field/read/guard source sequence changed")
    jar = Path(config["mapping"]["compiled_jar"])
    if sha(jar) != config["mapping"]["compiled_jar_sha256"]:
        raise ValueError("compiled Solr JAR changed")
    with zipfile.ZipFile(jar) as archive:
        for name, expected_hash in {
            "org/apache/solr/update/processor/DistributedZkUpdateProcessor.class":
            config["mapping"]["compiled_class_sha256"],
            "org/apache/solr/cloud/ShardLeaderElectionContext.class":
            config["mapping"]["election_class_sha256"],
            "org/apache/solr/cloud/CloudDescriptor.class":
            config["mapping"]["cloud_descriptor_class_sha256"],
        }.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected_hash:
                raise ValueError(f"compiled class changed: {name}")
    with zipfile.ZipFile(ADAPTER) as archive:
        hooks = archive.read("edu/uva/liftlab/mallory/solr/SolrHooks.class")
        transformer = archive.read("edu/uva/liftlab/mallory/solr/SolrTransformer.class")
    if (b"beginLeaderElection" not in hooks or b"endLeaderElection" not in hooks
            or b"ShardLeaderElectionContext" not in transformer):
        raise ValueError("election actor hook absent from isolated adapter")
    if sha(ADAPTER) != config["mapping"]["election_adapter_sha256"]:
        raise ValueError("election adapter binary changed")
    campaign.validate_config(config)
    return {"case_id": "SOLR-38", "mode": "healthy",
            "config_sha256": sha(CONFIG), "site_sha256": sha(SITES),
            "runner_sha256": sha(Path(__file__)),
            "adapter_sha256": sha(ADAPTER), "intended_output": str(OUT)}


def check_go(path: Path, metadata: dict) -> str:
    if path.resolve() != GO:
        raise ValueError("case-local dispatch GO receipt required")
    receipt = read(path)
    if (receipt.get("go") is not True or receipt.get("host") != "node2"
            or receipt.get("case_id") != "SOLR-38" or receipt.get("mode") != "healthy"
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
        print(json.dumps({"preflight": "passed_static_only", "go": False,
                          **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    metadata["admission_sha256"] = check_go(args.admission_receipt, metadata)
    if socket.gethostname().split(".", 1)[0] != "node2" or OUT.exists():
        raise ValueError("node2 and fresh output required")
    lock_root = Path("/tmp/mallory-lanes")
    lock_root.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("solr-lane3.lock", "solr-source-graphchecker-8.11.4.lock"):
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
            raise ValueError("another user JVM is running on node2")
        print(json.dumps({"preflight": "passed", **metadata}, sort_keys=True), flush=True)
        state = campaign.run(CONFIG, OUT, calibration_only=True)
    finally:
        for handle in reversed(handles):
            handle.close()
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
