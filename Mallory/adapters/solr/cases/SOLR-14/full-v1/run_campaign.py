#!/usr/bin/env python3
"""Preflight and run the isolated SOLR-14 healthy or full campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
sys.path.insert(0, str(RELEASE))

from Mallory.core import campaign  # noqa: E402

CASE = "SOLR-14"
TEST = "org.apache.solr.cloud.SplitShardTest#doTest"
CHECK = ("org.apache.solr.cloud.api.collections.SplitShardCmd"
         "#split(Lorg/apache/solr/common/cloud/ClusterState;"
         "Lorg/apache/solr/common/cloud/ZkNodeProps;"
         "Lorg/apache/solr/common/util/NamedList;)Z@165:branch:5")
DIRECT_DOOR = CHECK.split("@", 1)[0] + "@164:door:2"
OUT_ROOT = ROOT / "data/mallory/full_solr14_split_v1_node2"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def verify_manifest() -> None:
    files = read(HERE / "sha-manifest.json")["files"]
    for name, record in files.items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local package changed: {name}")


def preflight(mode: str) -> dict:
    verify_manifest()
    config_path = HERE / f"config-{mode}-node2.json"
    config = read(config_path)
    if config.get("case_id") != CASE or config.get("cluster_test") != TEST:
        raise ValueError("wrong case or JUnit selector")
    if config["target"]["check_sites"] != [CHECK] or not config["target"]["throw_site"].endswith("@167:throw:1"):
        raise ValueError("exact target changed")
    if config["budget"] != {"trials": 80, "seconds": 3600,
                            "max_faults_per_trial": 3,
                            "trial_timeout_seconds": 480}:
        raise ValueError("budget changed")
    if bool(config["calibration_only"]) != (mode == "healthy"):
        raise ValueError("calibration mode changed")
    if bool(config["auto_promote_if_healthy"]) != (mode == "full"):
        raise ValueError("promotion mode changed")
    if (config.get("site_file") != str(HERE / "sites.json")
            or not config.get("reject_coarse_roots")
            or not config.get("require_event_time_paths")
            or config.get("fault_types") != ["EXCEPTION"]):
        raise ValueError("site or fault constraints changed")
    sites = read(HERE / "sites.json")
    if not any(row.get("class") == "org.apache.solr.cloud.api.collections.SplitShardCmd"
               and row.get("callee", "").startswith("org.apache.solr.common.cloud.SolrZkClient#exists")
               for row in sites["doors"]):
        raise ValueError("real split ZooKeeper I/O door missing")
    if not any(row.get("clazz") == "org.apache.solr.cloud.api.collections.SplitShardCmd"
               and row.get("method") == "split" for row in sites["regions"]):
        raise ValueError("split region missing")
    for row in config["runtime_artifacts"]:
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    if (config["core_release"] != str(RELEASE) or
            not Path(campaign.__file__).resolve().is_relative_to(RELEASE)):
        raise ValueError("pinned graph-order core did not load")
    source = Path(config["cwd"])
    if not source.is_dir() or config["source_equivalent_root"] != str(source):
        raise ValueError("Solr lane3 source checkout absent")
    for field, rel in (("target_source_sha256", "solr/core/src/java/org/apache/solr/cloud/api/collections/SplitShardCmd.java"),
                       ("test_source_sha256", "solr/core/src/test/org/apache/solr/cloud/SplitShardTest.java")):
        if sha(source / rel) != config["mapping"][field]:
            raise ValueError(f"Solr source changed: {field}")
    compiled = Path(config["mapping"]["compiled_jar"])
    if sha(compiled) != config["mapping"]["compiled_jar_sha256"]:
        raise ValueError("compiled Solr JAR changed")
    with zipfile.ZipFile(compiled) as jar:
        class_bytes = jar.read("org/apache/solr/cloud/api/collections/SplitShardCmd.class")
    if hashlib.sha256(class_bytes).hexdigest() != config["mapping"]["compiled_class_sha256"]:
        raise ValueError("compiled split class changed")
    lines = (source / "solr/core/src/java/org/apache/solr/cloud/api/collections/SplitShardCmd.java").read_text().splitlines()
    if ("getZkClient().exists(" not in lines[163] or
            "if (leaderZnodeStat == null)" not in lines[164] or
            "throw new SolrException" not in lines[166]):
        raise ValueError("selected source sequence changed")
    campaign.validate_config(config)
    return {"config_sha256": sha(config_path), "site_sha256": sha(HERE / "sites.json"),
            "core_manifest_sha256": sha(RELEASE / "manifest.json"),
            "agent_sha256": sha(Path(config["agent_jar"])),
            "adapter_sha256": sha(Path(config["agent_properties"]["adapter.jar"]))}


def admit_healthy() -> dict:
    root = OUT_ROOT / "healthy" / CASE
    result_path = root / "result.json"
    trial_path = root / "trials/r0000/result.json"
    if not result_path.is_file() or not trial_path.is_file() or not (root / "config.json").is_file():
        raise ValueError("fresh healthy result missing")
    if sha(root / "config.json") != sha(HERE / "config-healthy-node2.json"):
        raise ValueError("healthy result used a different config")
    result, trial = read(result_path), read(trial_path)
    if (result.get("case_id") != CASE or result.get("status") != "calibration_complete"
            or result.get("calibration_only") is not True
            or not result.get("healthy_seed_valid")
            or result.get("healthy_junit_validation", {}).get("status") != "passed"
            or result.get("healthy_junit_validation", {}).get("tests") != 1
            or not result.get("runtime_attestation", {}).get("valid")
            or not result.get("target_binding", {}).get("nodes")
            or trial.get("case_id") != CASE or trial.get("plan") != []
            or trial.get("junit_validation", {}).get("status") != "passed"):
        raise ValueError("healthy JUnit, target identity, or runtime attestation failed")
    feedback = trial.get("feedback", {})
    targets = feedback.get("target_instances", [])
    if not targets or any(row.get("node") in (None, "unknown") for row in targets):
        raise ValueError("exact target has no named physical actor")
    direct = [row for row in feedback.get("doors", [])
              if row.get("site") == DIRECT_DOOR
              and row.get("fault_type") == "EXCEPTION"
              and row.get("exception_class") == "org.apache.zookeeper.KeeperException$ConnectionLossException"
              and row.get("point", {}).get("node") in result["target_binding"]["nodes"]]
    if not direct or result.get("healthy_eligible_doors", 0) <= 0:
        raise ValueError("healthy run lacks named injectable split ZooKeeper I/O")
    return {"healthy_result_sha256": sha(result_path),
            "healthy_trial_sha256": sha(trial_path),
            "named_target_nodes": result["target_binding"]["nodes"],
            "direct_io_door_count": len(direct)}


def check_go(mode: str, receipt_path: Path, config_sha: str, out: Path) -> str:
    receipt = read(receipt_path)
    if (receipt.get("go") is not True or receipt.get("host") != "node2"
            or receipt.get("case_id") != CASE or receipt.get("mode") != mode
            or receipt.get("config_sha256") != config_sha
            or receipt.get("runner_sha256") != sha(Path(__file__))
            or receipt.get("intended_output") != str(out)):
        raise ValueError("dispatch GO receipt missing or mismatched")
    return sha(receipt_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("healthy", "full"), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight(args.mode)
    out = OUT_ROOT / args.mode / CASE
    if args.mode == "full" and not args.preflight_only:
        metadata.update(admit_healthy())
    if args.preflight_only:
        print(json.dumps({"preflight": "passed", "mode": args.mode, **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    metadata["admission_sha256"] = check_go(args.mode, args.admission_receipt,
                                            metadata["config_sha256"], out)
    print(json.dumps({"preflight": "passed", "mode": args.mode, **metadata}, sort_keys=True), flush=True)
    state = campaign.run(HERE / f"config-{args.mode}-node2.json", out)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"],
                      "elapsed_seconds": state["elapsed_seconds"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
