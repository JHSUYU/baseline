#!/usr/bin/env python3
"""Static, no-JVM admission check for the pinned HBASE-32 discovery package."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
CORE = ROOT / "Mallory/dispatch/releases/815cba9b-target-absent-v1"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
PRIOR = ROOT / "data/mallory/calibration_v19/HBASE-32/result.json"
EXPECTED_COMMIT = "d5f63f523c065f963992ea4e74db268d17816631"
DOOR = ("org.apache.hadoop.hbase.client.FlushRegionCallable#call"
        "(Lorg/apache/hadoop/hbase/ipc/HBaseRpcController;)"
        "Lorg/apache/hadoop/hbase/shaded/protobuf/generated/"
        "AdminProtos$FlushRegionResponse;@81:door:1")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_zip_member(jar: Path, member: str, digest: str) -> None:
    with zipfile.ZipFile(jar) as archive:
        actual = hashlib.sha256(archive.read(member)).hexdigest()
    require(actual == digest, f"class changed: {jar}!{member}")


def preflight(mode: str) -> dict:
    manifest = load(HERE / "sha-manifest.json")
    require(manifest["case_id"] == "HBASE-32", "wrong case manifest")
    require(manifest["source_commit"] == EXPECTED_COMMIT, "source revision changed")
    require(manifest["bootstrap_door"] == DOOR, "bootstrap door changed")
    for name, digest in manifest["case_files"].items():
        require(sha(HERE / name) == digest, f"case file changed: {name}")

    commit = subprocess.check_output(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    require(commit == EXPECTED_COMMIT, "HBase source checkout moved")
    for name, digest in manifest["source_files"].items():
        require(sha(SOURCE / name) == digest, f"source changed: {name}")

    core_manifest = CORE / "manifest.json"
    require(sha(core_manifest) == manifest["core_manifest_sha256"],
            "frozen target-absent core changed")
    for name, digest in load(core_manifest)["files"].items():
        require(sha(CORE / name) == digest, f"frozen core changed: {name}")
    sys.path.insert(0, str(CORE))
    from Mallory.core.campaign import validate_config

    config = load(HERE / f"config-{mode}.json")
    validate_config(config)
    require(config["calibration_only"] == (mode == "healthy"),
            "calibration mode changed")
    require(config["auto_promote_if_healthy"] == (mode == "full"),
            "promotion mode changed")
    require(config["core_release"] == str(CORE), "campaign core path changed")
    require(config["cwd"] == str(SOURCE), "source root changed")
    require(config["site_file"] == str(HERE / "sites.json"), "site file changed")
    require(config["target_absent_bootstrap"]["door_sites"] == [DOOR],
            "exact bootstrap door changed")
    require(config["agent_properties"]["auto.io.doors"] is False,
            "explicit door numbering changed")
    require(config["expected_target_class_sha256"] ==
            manifest["target_class_sha256"], "target class pin changed")
    require(config["cluster_test"] ==
            "org.apache.hadoop.hbase.regionserver.TestRegionReplicaFailover#testSecondaryRegionKill",
            "unchanged cluster JUnit changed")
    require(config["budget"] == {
        "trials": 80, "seconds": 3600, "max_faults_per_trial": 3,
        "trial_timeout_seconds": 480}, "discovery budget changed")
    require(config["target"]["check_sites"] == [manifest["target_check"]],
            "target check changed")
    require(config["target"]["throw_site"] == manifest["target_throw"],
            "target throw changed")
    require(config["agent_properties"]["adapter.transformer"].split(",") == [
        "edu.uva.liftlab.mallory.hbase.HBaseAdapterTransformer",
        "edu.uva.liftlab.mallory.hbase32.HBase32ActorTransformer"],
        "actor overlay missing")
    for item in config["runtime_artifacts"]:
        require(sha(Path(item["path"])) == item["sha256"],
                f"runtime artifact changed: {item['path']}")

    sites = load(HERE / "sites.json")
    require(len(sites["doors"]) == 1 and
            sites["doors"][0]["clazz"] == "org.apache.hadoop.hbase.client.FlushRegionCallable" and
            sites["doors"][0]["method"] == "call" and
            sites["doors"][0]["line"] == 81 and
            sites["doors"][0]["callee"] == manifest["rpc_callee"] and
            sites["doors"][0]["exception_class"] ==
            "org.apache.hadoop.hbase.DoNotRetryIOException",
            "the exact flushRegion exception door changed")
    require(any(row["line"] == 130 for row in sites["targets"]) and
            any(row["line"] == 136 for row in sites["targets"]),
            "target check/throw rules missing")

    for label, item in manifest["compiled"].items():
        jar = Path(item["jar"])
        require(sha(jar) == item["jar_sha256"], f"{label} jar changed")
        verify_zip_member(jar, item["member"], item["class_sha256"])
    # The class hash pins the bytecode reviewed with javap. These extra checks
    # reject an accidental pin to an unrelated class without invoking a JVM.
    with zipfile.ZipFile(manifest["compiled"]["flush_callable"]["jar"]) as archive:
        bytecode = archive.read(manifest["compiled"]["flush_callable"]["member"])
    for name in (b"flushRegion", b"BlockingInterface", b"LineNumberTable"):
        require(name in bytecode, "pinned flush RPC class is not recognizable")

    require(sha(PRIOR) == manifest["prior_negative_sha256"],
            "prior healthy negative receipt changed")
    old = load(PRIOR)
    require(old["healthy_junit_validation"]["status"] == "passed" and
            old["fault_trials_completed"] == 0 and
            old["cluster_test"] == config["cluster_test"] and
            old["target_reached_trials"] == 0 and
            old["healthy_seed_valid"] is False,
            "prior healthy negative receipt no longer matches")
    return {"case_id": "HBASE-32", "mode": mode,
            "static_preflight": "passed", "healthy_runtime_attested": False,
            "source_commit": commit, "bootstrap_door": DOOR,
            "prior_healthy_exact_check_count": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("healthy", "full", "both"), default="both")
    args = parser.parse_args()
    modes = ("healthy", "full") if args.mode == "both" else (args.mode,)
    for mode in modes:
        print(json.dumps(preflight(mode), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
