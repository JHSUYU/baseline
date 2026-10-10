#!/usr/bin/env python3
"""Pinned, GO-gated runner for original-102 Solr target-discovery campaigns."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
RELEASE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def preflight(here: Path, mode: str) -> dict:
    case = here.parent.name
    package = read(here / "sha-manifest.json")
    if package["case_id"] != case or package["core_source_commit"] != "815cba9b":
        raise ValueError("case or bootstrap core pin changed")
    for name, record in package["files"].items():
        path = here / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local file changed: {name}")
    core_manifest = read(RELEASE / "manifest.json")
    if core_manifest["source_commit"] != "815cba9b":
        raise ValueError("wrong target-absent core release")
    for name, expected in core_manifest["files"].items():
        if sha(RELEASE / name) != expected:
            raise ValueError(f"core release changed: {name}")
    if sha(RELEASE / "manifest.json") != package["core_manifest_sha256"]:
        raise ValueError("core manifest changed")
    if not Path(campaign.__file__).resolve().is_relative_to(RELEASE):
        raise ValueError("campaign core was not loaded from pinned release")

    config_path = here / f"config-{mode}-node2.json"
    config = read(config_path)
    budget = {"trials": 80, "seconds": 3600, "max_faults_per_trial": 3,
              "trial_timeout_seconds": 480}
    if (config["case_id"] != case or config["budget"] != budget
            or config["cluster_test"] != package["cluster_test"]
            or config["site_file"] != str(here / "sites.json")
            or config["target"]["check_sites"] != [package["exact_check_site"]]
            or config["target"]["throw_site"] != package["exact_throw_site"]
            or config.get("expected_target_class_sha256") != package["target_class_sha256"]
            or config.get("fault_types") != ["EXCEPTION"]
            or config.get("require_site_catalog") is not True
            or config.get("allow_local_timeline_doors") is not True
            or config.get("require_event_time_paths") is not False
            or config.get("core_release") != str(RELEASE)):
        raise ValueError("case, workload, exact target, or fault policy changed")
    if bool(config["calibration_only"]) != (mode == "healthy"):
        raise ValueError("healthy/full calibration policy changed")
    if bool(config["auto_promote_if_healthy"]) != (mode == "full"):
        raise ValueError("healthy/full promotion policy changed")
    policy = config["target_absent_bootstrap"]
    if (policy["door_sites"] != package["bootstrap_door_sites"]
            or policy["max_trials"] != 80
            or policy["max_doors_per_trial"] != 16
            or policy["max_faults_per_trial"] != 3):
        raise ValueError("bounded discovery policy changed")
    sites = read(here / "sites.json")
    check = package["exact_check_site"]
    clazz, line = check.split("#", 1)[0], int(check.rsplit("@", 1)[1].split(":", 1)[0])
    if not any(t["clazz"] == clazz and t["line"] == line for t in sites["targets"]):
        raise ValueError("selected check absent from the site catalog")
    if not sites["doors"] or not sites["regions"]:
        raise ValueError("I/O or target region missing from the site catalog")
    if case in {"SOLR-15", "SOLR-16"}:
        split = "org.apache.solr.cloud.api.collections.SplitShardCmd"
        if (split not in config["agent_include"] or
                not any(row.get("class") == split and
                        row.get("callee", "").startswith(
                            "org.apache.solr.common.cloud.SolrZkClient#exists")
                        for row in sites["doors"]) or
                not any(site.startswith(split + "#split(") and
                        site.endswith("@523:door:3")
                        for site in policy["door_sites"])):
            raise ValueError("selected split leader-znode I/O door is not configured")
    if case == "SOLR-34":
        reader = "org.apache.solr.common.cloud.ZkStateReader"
        if (reader not in config["agent_include"] or
                not any(row.get("class") == reader and
                        row.get("callee", "").startswith(
                            "org.apache.solr.common.cloud.SolrZkClient#getData")
                        for row in sites["doors"]) or
                not any(site.startswith(reader + "#fetchCollectionState(")
                        and site.endswith("@1641:door:1")
                        for site in policy["door_sites"])):
            raise ValueError("coordinator collection-state getData I/O is not configured")
    for row in config["runtime_artifacts"]:
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")

    source = Path(config["cwd"])
    if (not source.is_dir() or config["source_equivalent_root"] != str(source)
            or sha(source / package["test_source_path"]) != package["test_source_sha256"]
            or sha(source / config["target"]["source_path"]) !=
            config["mapping"]["target_source_sha256"]):
        raise ValueError("pinned Solr JUnit or target source missing/changed")
    if case in {"SOLR-15", "SOLR-16"}:
        split_source = (source / config["target"]["source_path"]).read_text().splitlines()
        if ("getZkClient().exists(" not in split_source[163] or
                "getZkClient().exists(" not in split_source[522]):
            raise ValueError("leader-znode read locations changed")
    if case == "SOLR-34":
        reader_source = (source / "solr/solrj/src/java/org/apache/solr/common/cloud/"
                         "ZkStateReader.java").read_text().splitlines()
        if ("zkClient.getData(" not in reader_source[310] or
                "zkClient.getData(" not in reader_source[1640]):
            raise ValueError("collection-state getData locations changed")
    compiled = Path(config["mapping"]["compiled_jar"])
    if sha(compiled) != config["mapping"]["compiled_jar_sha256"]:
        raise ValueError("compiled Solr JAR changed")
    member = clazz.replace(".", "/") + ".class"
    with zipfile.ZipFile(compiled) as archive:
        class_hash = hashlib.sha256(archive.read(member)).hexdigest()
    if class_hash != package["target_class_sha256"]:
        raise ValueError("compiled target class changed")
    campaign.validate_config(config)
    return {"case_id": case, "mode": mode, "config_sha256": sha(config_path),
            "core_manifest_sha256": sha(RELEASE / "manifest.json"),
            "target_class_sha256": class_hash,
            "configured_bootstrap_door_sites": len(policy["door_sites"])}


def admit_healthy(here: Path, out_root: Path) -> dict:
    case = here.parent.name
    healthy = out_root / "healthy" / case
    result_path = healthy / "result.json"
    trial_path = healthy / "trials/r0000/result.json"
    if (not result_path.is_file() or not trial_path.is_file()
            or not (healthy / "config.json").is_file()):
        raise ValueError("fresh healthy bootstrap result missing")
    if sha(healthy / "config.json") != sha(here / "config-healthy-node2.json"):
        raise ValueError("healthy bootstrap config differs")
    result, trial = read(result_path), read(trial_path)
    if (result.get("status") != "calibration_complete"
            or result.get("case_id") != case
            or not result.get("bootstrap_seed_valid")
            or result.get("target_discovered_trial") is not None
            or result.get("healthy_junit_validation", {}).get("status") != "passed"
            or result.get("healthy_junit_validation", {}).get("tests") != 1
            or result.get("healthy_junit_validation", {}).get("failures") != 0
            or result.get("healthy_junit_validation", {}).get("errors") != 0
            or not result.get("runtime_attestation", {}).get("valid")
            or result.get("bootstrap_seed_doors", 0) <= 0
            or trial.get("feedback", {}).get("status") != "healthy_target_missing"
            or trial.get("site_catalog_validation", {}).get("valid") is not True
            or trial.get("site_catalog_validation", {}).get("class_hash_match") is not True):
        raise ValueError("healthy JUnit, exact class/site, or named replayable door gate failed")
    policy = read(here / "config-full-node2.json")["target_absent_bootstrap"]
    admitted = [door for door in trial["feedback"].get("doors", [])
                if door.get("site") in policy["door_sites"]
                and door.get("point", {}).get("node") not in (None, "unknown", "")]
    if not admitted:
        raise ValueError("healthy run has no configured named I/O door")
    return {"healthy_result_sha256": sha(result_path),
            "healthy_trial_sha256": sha(trial_path),
            "named_configured_io_doors": len(admitted)}


def check_go(receipt_path: Path, case: str, mode: str, config_sha: str,
             out: Path, runner: Path) -> str:
    receipt = read(receipt_path)
    if (receipt.get("go") is not True or receipt.get("host") != "node2"
            or receipt.get("case_id") != case or receipt.get("mode") != mode
            or receipt.get("config_sha256") != config_sha
            or receipt.get("runner_sha256") != sha(runner)
            or receipt.get("intended_output") != str(out)):
        raise ValueError("dispatch GO receipt missing or mismatched")
    return sha(receipt_path)


def main(here: Path, runner: Path) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("healthy", "full"), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    case = here.parent.name
    out_root = ROOT / "data/mallory/solr_fault_discovery_node2_v1"
    out = out_root / args.mode / case
    metadata = preflight(here, args.mode)
    if args.mode == "full" and not args.preflight_only:
        metadata.update(admit_healthy(here, out_root))
    if args.preflight_only:
        print(json.dumps({"preflight": "passed", **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    metadata["admission_sha256"] = check_go(args.admission_receipt, case,
                                             args.mode, metadata["config_sha256"],
                                             out, runner)
    print(json.dumps({"preflight": "passed", **metadata}, sort_keys=True), flush=True)
    state = campaign.run(here / f"config-{args.mode}-node2.json", out)
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"],
                      "elapsed_seconds": state["elapsed_seconds"]}, sort_keys=True))
    return 0
