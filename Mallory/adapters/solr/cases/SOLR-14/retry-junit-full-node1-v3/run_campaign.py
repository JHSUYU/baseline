#!/usr/bin/env python3
"""GO-gated SOLR-14 retry JUnit campaign with strict runtime retention gates."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import gzip
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
OUT = ROOT / "data/mallory/solr14_retry_junit_full_v3_node1/SOLR-14/full"
CONFIG = HERE / "config-full-node1.json"
SITES = HERE / "sites.json"
REQUEST = HERE / "admission-request.json"
GO = HERE / "admission-full-node1.json"
CHECK = ("org.apache.solr.cloud.api.collections.SplitShardCmd"
         "#split(Lorg/apache/solr/common/cloud/ClusterState;"
         "Lorg/apache/solr/common/cloud/ZkNodeProps;"
         "Lorg/apache/solr/common/util/NamedList;)Z@165:branch:5")
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign  # noqa: E402
from audit_healthy import evaluate as audit_healthy  # noqa: E402
from postfault_gate import evaluate as audit_postfault  # noqa: E402


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
            or request.get("case_id") != "SOLR-14" or request.get("host") != "node1"
            or request.get("mode") != "full"
            or request.get("runner_sha256") != sha(Path(__file__))
            or request.get("config_sha256") != sha(CONFIG)
            or request.get("intended_output") != str(OUT)):
        raise ValueError("full dispatch request changed")
    if (config["case_id"] != "SOLR-14" or config["system"] != "solr"
            or config["cluster_test"] != "org.apache.solr.cloud.api.collections.ShardSplitTest#testSplitAfterFailedSplit"
            or config["target"]["check_sites"] != [CHECK]
            or config["target"]["throw_site"] != CHECK.split("@", 1)[0] + "@167:throw:1"
            or config["site_file"] != str(SITES)
            or config["core_release"] != str(RELEASE)
            or not Path(campaign.__file__).resolve().is_relative_to(RELEASE)):
        raise ValueError("target, JUnit, or frozen core changed")
    if (config["budget"] != {"trials": 80, "seconds": 3600,
                             "max_faults_per_trial": 3, "trial_timeout_seconds": 480}
            or config["calibration_only"] is not False
            or config["auto_promote_if_healthy"] is not True
            or config["agent_properties"]["auto.io.doors"] is not False
            or config["fault_types"] != ["EXCEPTION"]
            or config["allow_local_timeline_doors"] is not True
            or config["require_event_time_paths"] is not False
            or config["reject_coarse_roots"] is not True
            or config["cwd"] != str(SOURCE)
            or config["source_equivalent_root"] != str(SOURCE)
            or config["command"][1] != str(HERE / "run_pilot.py")
            or config["command"][4] != str(SOURCE)):
        raise ValueError("full execution or I/O scope changed")
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
    junit = SOURCE / "solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java"
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
    test_text = junit.read_text(encoding="utf-8")
    if ("class ShardSplitTest extends BasicDistributedZkTest" not in test_text
            or "public void testSplitAfterFailedSplit()" not in test_text
            or "splitAfterFailedSplit();" not in test_text
            or "TestInjection.reset(); // let the split succeed" not in test_text):
        raise ValueError("retrying cluster JUnit changed")
    selector_inventory = read(HERE / "inventory-selector.json")
    if (len(selector_inventory.get("cases", [])) != 1
            or selector_inventory["cases"][0]["case_id"] != "SOLR-14"
            or selector_inventory["cases"][0]["workload"]["selected_selector"] != config["cluster_test"]
            or selector_inventory["cases"][0]["workload"]["test_source_path"] !=
               "solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java"):
        raise ValueError("isolated selected JUnit inventory changed")
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


def events_of(trial: Path) -> list[dict]:
    with gzip.open(trial / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def gate_trial_zero(result: dict, output: Path) -> dict:
    """Require two same-actor typed split paths before scheduling any fault."""
    trial = output / "trials/r0000"
    catalog = result.get("site_catalog_validation", {})
    feedback = result.get("feedback", {})
    summary = {"case_id": "SOLR-14", "cluster_test": read(CONFIG)["cluster_test"],
               "healthy_seed_valid": (feedback.get("status") == "observed"
                                      and feedback.get("target_reached") is True
                                      and not feedback.get("target_threw")),
               "runtime_attestation": {
                   "valid": (catalog.get("valid") is True
                             and catalog.get("class_hash_match") is True
                             and len(catalog.get("target_class_loader_ids", [])) == 1),
                   "observed_target_class_sha256": catalog.get("observed_target_class_sha256")}}
    return audit_healthy(summary, read(trial / "pilot-result.json"),
                         read(trial / "junit-receipt.json"), events_of(trial))


def verify_sealed_seed() -> dict:
    """Pin the earlier node1 healthy output and dispatch GO without starting Java."""
    proof = read(HERE / "healthy-proof.json")
    if proof.get("case_id") != "SOLR-14" or proof.get("host") != "node1":
        raise ValueError("wrong healthy proof")
    receipt_path = Path(proof["admission_receipt"])
    if sha(receipt_path) != proof["admission_sha256"]:
        raise ValueError("sealed healthy GO receipt changed")
    receipt = read(receipt_path)
    if (receipt.get("go") is not True or receipt.get("mode") != "healthy"
            or receipt.get("host") != "node1" or receipt.get("case_id") != "SOLR-14"):
        raise ValueError("sealed healthy admission invalid")
    root = Path(proof["healthy_dir"])
    for name, expected in proof["files"].items():
        if sha(root / name) != expected:
            raise ValueError(f"sealed healthy artifact changed: {name}")
    seed = read(root / "trials/r0000/result.json")
    accepted = gate_trial_zero(seed, root)
    if sha(root / "config.json") != receipt["config_sha256"]:
        raise ValueError("sealed healthy config differs from dispatch GO")
    return {"healthy_result_sha256": proof["files"]["result.json"],
            "healthy_events_sha256": proof["files"]["trials/r0000/events.jsonl.gz"],
            "healthy_actor": accepted["physical_actor"],
            "healthy_retry_target_seq": accepted["retry_target_seq"]}


def install_strict_gate() -> None:
    """Wrap the frozen core's result admission, leaving its code unchanged."""
    original = campaign._apply_result

    def checked_apply(state: dict, config: dict, result: dict, item: dict | None) -> None:
        output = Path(state["out"])
        trial_id = result["trial_id"]
        if trial_id == 0:
            result["strict_retry_seed_gate"] = gate_trial_zero(result, output)
        else:
            seed = read(output / "trials/r0000/result.json")
            actor = gate_trial_zero(seed, output)["physical_actor"]
            feedback = result["feedback"]
            raw_reached = feedback.get("target_reached")
            raw_candidate = feedback.get("target_exception_candidate")
            gate = audit_postfault(events_of(output / "trials" / f"r{trial_id:04d}"),
                                   feedback, actor)
            result["postfault_retry_gate"] = gate
            result["raw_target_reached_before_retry_gate"] = raw_reached
            result["raw_target_exception_candidate_before_retry_gate"] = raw_candidate
            if not gate["valid"]:
                feedback["target_reached"] = False
                feedback["target_exception_candidate"] = False
            elif not gate["target_threw"]:
                feedback["target_exception_candidate"] = False
        original(state, config, result, item)

    campaign._apply_result = checked_apply


def check_go(path: Path, metadata: dict) -> str:
    if path.resolve() != GO:
        raise ValueError("case-local node1 GO receipt required")
    receipt = read(path)
    if (receipt.get("go") is not True or receipt.get("host") != "node1"
            or receipt.get("case_id") != "SOLR-14" or receipt.get("mode") != "full"
            or receipt.get("config_sha256") != metadata["config_sha256"]
            or receipt.get("runner_sha256") != metadata["runner_sha256"]
            or receipt.get("intended_output") != str(OUT)):
        raise ValueError("dispatch GO receipt absent or mismatched")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("full",), required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--verify-seed-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight()
    if args.preflight_only:
        print(json.dumps({"preflight": "passed_static_only", "case_id": "SOLR-14",
                          "mode": "full", "go": False, **metadata}, sort_keys=True))
        return 0
    if socket.gethostname().split(".", 1)[0] != "node1":
        raise ValueError("node1 required for sealed seed and full campaign")
    metadata.update(verify_sealed_seed())
    if args.verify_seed_only:
        print(json.dumps({"preflight": "passed_sealed_seed_only", "case_id": "SOLR-14",
                          "mode": "full", "go": False, **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt required before starting a JVM")
    metadata["admission_sha256"] = check_go(args.admission_receipt, metadata)
    if OUT.exists():
        checkpoint = read(OUT / "checkpoint.json")
        if 0 in checkpoint.get("completed_trials", []):
            gate_trial_zero(read(OUT / "trials/r0000/result.json"), OUT)
    lock_root = Path("/tmp/mallory-lanes")
    lock_root.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("zookeeper-node1-source.lock", "solr-node1-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_root / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        if shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("at least 7,650,410,496 free bytes required")
        available = next(int(row.split()[1]) for row in Path("/proc/meminfo").read_text().splitlines()
                         if row.startswith("MemAvailable:"))
        if available < 8_388_608:
            raise ValueError("at least 8,388,608 KiB MemAvailable required")
        processes = subprocess.check_output(["ps", "-eo", "user=,comm="], text=True)
        if any(row.split() == [getpass.getuser(), "java"] for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node1")
        print(json.dumps({"preflight": "passed", "case_id": "SOLR-14",
                          "mode": "full", **metadata}, sort_keys=True), flush=True)
        install_strict_gate()
        state = campaign.run(CONFIG, OUT)
    finally:
        for handle in reversed(handles):
            handle.close()
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
