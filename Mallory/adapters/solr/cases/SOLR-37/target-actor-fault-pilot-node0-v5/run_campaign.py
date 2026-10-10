#!/usr/bin/env python3
"""GO-gated bounded SOLR-37 pilot with strict per-trial receipt auditing."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import gzip
import hashlib
import json
import re
import shutil
import socket
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
OUT = ROOT / "data/mallory/solr37_target_actor_fault_pilot_v5_node0/SOLR-37/pilot"
sys.path.insert(0, str(RELEASE))
from Mallory.core import campaign, scheduler  # noqa: E402
from audit_exact_path import DOOR, REGION, RESOURCE, audit_trial  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def preflight() -> dict:
    manifest = read(HERE / "sha-manifest.json")
    if manifest.get("case_id") != "SOLR-37":
        raise ValueError("wrong case package")
    for name, record in manifest["files"].items():
        path = HERE / name
        if (not path.is_file() or path.stat().st_size != record["bytes"]
                or sha(path) != record["sha256"]):
            raise ValueError(f"case-local file changed: {name}")
    config_path = HERE / "config-pilot-node0.json"
    config = read(config_path)
    qualifier = {"site": DOOR, "actor_selection": "healthy_exact_target_actor",
                 "resource": RESOURCE, "region": REGION,
                 "occurrence_kind": "watcher_region",
                 "reference": "latest_instrumented_clusterState"}
    if (config.get("case_id") != "SOLR-37" or
            config.get("strict_fault_qualifier") != qualifier or
            config.get("site_file") != str(HERE / "sites.json") or
            config.get("core_release") != str(RELEASE) or
            not Path(campaign.__file__).resolve().is_relative_to(RELEASE)):
        raise ValueError("case, qualifier or graph core changed")
    if config.get("budget") != {"trials": 6, "seconds": 1800,
                                "max_faults_per_trial": 3,
                                "trial_timeout_seconds": 360}:
        raise ValueError("bounded pilot budget changed")
    if (config.get("calibration_only") is not False or
            config.get("auto_promote_if_healthy") is not True or
            config.get("explore_outside_closure") is not False or
            config.get("fault_types") != ["EXCEPTION"] or
            config.get("require_event_time_paths") is not True or
            config.get("reject_coarse_roots") is not True or
            config.get("agent_properties", {}).get("auto.io.doors") is not False):
        raise ValueError("strict pilot mode changed")
    if (config.get("agent_jar") != str(HERE.parent / "strict-fault-pilot-node0-v4/agent/release/mallory-agent.jar") or
            config.get("agent_properties", {}).get("adapter.jar") !=
            str(HERE / "adapter/release/adapter.jar")):
        raise ValueError("case-local agent or adapter missing")
    if (config.get("command", [None, None])[1] !=
            str(ROOT / "Mallory/adapters/solr/releases/v46/run_pilot.py") or
            config.get("command", [])[-1] != "300"):
        raise ValueError("direct JUnit wrapper changed")
    sites = read(HERE / "sites.json")
    if (len(sites.get("doors", [])) != 1 or len(sites.get("targets", [])) != 2 or
            not any(row.get("clazz") == "org.apache.solr.common.cloud.ZkStateReader$StateWatcher"
                    and row.get("method") == "refreshAndWatch"
                    for row in sites.get("regions", []))):
        raise ValueError("source sites changed")
    seed = config["v3_healthy_seed"]
    receipt = read(Path(seed["receipt"]))
    if (receipt.get("case_id") != "SOLR-37" or
            receipt.get("strict_witness_count") != 188 or
            receipt.get("candidate_state_edges") != 0 or
            receipt.get("exact_target_checks") != 188 or
            receipt.get("eligible_for_separate_fault_pilot_review") is not True or
            sha(Path(seed["archive"])) != seed["archive_sha256"] or
            receipt.get("archive_sha256") != seed["archive_sha256"]):
        raise ValueError("sealed v3 healthy seed changed")
    prior = config["v4_actor_drift_observation"]
    prior_receipt = read(Path(prior["receipt"]))
    if (prior_receipt.get("status") != "healthy_seed_invalid" or
            prior_receipt.get("exact_target_checks") != 160 or
            prior_receipt.get("qualified_watcher_doors") != 18 or
            prior_receipt.get("candidate_state_edges") != 0 or
            sha(Path(prior["archive"])) != prior["archive_sha256"] or
            prior_receipt.get("archive_sha256") != prior["archive_sha256"]):
        raise ValueError("sealed v4 actor-drift evidence changed")
    for row in config["runtime_artifacts"]:
        path = Path(row["path"])
        if not path.is_file() or sha(path) != row["sha256"]:
            raise ValueError(f"runtime artifact changed: {path}")
    source = Path(config["cwd"])
    if (not source.is_dir() or config.get("source_equivalent_root") != str(source)
            or subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                       text=True).strip() !=
            "e27f44e3d78dfcec230c97e0a1240e3751daeff9"
            or subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"],
                                       text=True).strip()):
        raise ValueError("Solr source revision or cleanliness changed")
    target = source / config["target"]["source_path"]
    if sha(target) != config["mapping"]["target_source_sha256"]:
        raise ValueError("target source changed")
    watcher = source / "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java"
    if sha(watcher) != config["mapping"]["watcher_source_sha256"]:
        raise ValueError("watcher source changed")
    lines = watcher.read_text().splitlines()
    if ("fetchCollectionState(coll, this, collectionPath)" not in lines[1383] or
            "zkClient.getData(collectionPath, watcher, stat, true)" not in lines[1640]):
        raise ValueError("watcher source callsite moved")
    jar = Path(config["mapping"]["compiled_jar"])
    if sha(jar) != config["mapping"]["compiled_jar_sha256"]:
        raise ValueError("compiled Solr JAR changed")
    member = "org/apache/solr/update/processor/DistributedZkUpdateProcessor.class"
    with zipfile.ZipFile(jar) as archive:
        if hashlib.sha256(archive.read(member)).hexdigest() != config["mapping"]["compiled_class_sha256"]:
            raise ValueError("compiled target class changed")
    campaign.validate_config(config)
    request = read(HERE / "admission-request.json")
    if (request.get("go") is not False or request.get("execution_status") != "not_launched"
            or request.get("host") != "node0" or request.get("case_id") != "SOLR-37"
            or request.get("mode") != "pilot" or
            request.get("runner_sha256") != sha(Path(__file__)) or
            request.get("config_sha256") != sha(config_path) or
            request.get("intended_output") != str(OUT)):
        raise ValueError("admission request changed")
    return {"config_sha256": sha(config_path), "runner_sha256": sha(Path(__file__)),
            "agent_sha256": sha(Path(config["agent_jar"])),
            "adapter_sha256": sha(Path(config["agent_properties"]["adapter.jar"]))}


def install_strict_runtime() -> None:
    original_replay = scheduler._replay_point
    original_mutate = campaign.mutate
    original_apply = campaign._apply_result

    def replay(door: dict) -> dict | None:
        point = original_replay(door)
        if (point is None or point.get("site") != DOOR or
                not isinstance(point.get("node"), str) or
                not re.fullmatch(r"shard-[0-9]+", point["node"]) or
                not isinstance(point.get("epoch"), int) or point["epoch"] < 0):
            return None
        return {**point, "resource": RESOURCE, "region": REGION,
                "occurrence_kind": "watcher_region"}

    def mutate(parent: list, feedback: dict, config: dict) -> list:
        target_actors = {(row.get("node"), row.get("epoch"))
                         for row in feedback.get("target_instances", [])}
        if parent:
            parent_point = parent[0].get("point", {})
            parent_actor = (parent_point.get("node"), parent_point.get("epoch"))
            target_actors &= {parent_actor}
        strict_points = {(row["node"], row["epoch"], row["door_ordinal"])
                         for row in feedback.get("strict_qualified_points", [])}
        selected = [door for door in feedback.get("doors", [])
                    if (door.get("site") == DOOR and
                        (door.get("point", {}).get("node"),
                         door.get("point", {}).get("epoch")) in target_actors and
                        (parent or (door.get("point", {}).get("node"),
                                    door.get("point", {}).get("epoch"),
                                    door.get("point", {}).get("door_ordinal")) in strict_points))]
        return original_mutate(parent, {**feedback, "doors": selected}, config)

    def apply(state: dict, config: dict, result: dict, item: dict | None) -> None:
        trial_id = result["trial_id"]
        trial = Path(state["out"]) / "trials" / f"r{trial_id:04d}"
        path = trial / "events.jsonl.gz"
        try:
            if path.is_file():
                with gzip.open(path, "rt", encoding="utf-8") as source:
                    events = tuple(json.loads(line) for line in source if line.strip())
                audit = audit_trial(events, result["plan"])
            else:
                audit = {"valid": False, "reason": "missing_compressed_trace"}
        except Exception as failure:
            audit = {"valid": False, "reason": "audit_error",
                     "error_type": type(failure).__name__, "error": str(failure)[:512]}
        campaign.atomic_json(trial / "strict-audit.json", audit)
        result["strict_audit"] = audit
        if audit["valid"] and not result["plan"]:
            result["feedback"]["strict_qualified_points"] = audit["qualified_points"]
        if not audit["valid"]:
            result["feedback"].update(
                status="strict_" + audit["reason"], target_reached=False,
                all_faults_effective=False, target_exception_candidate=False,
                doors=[])
        original_apply(state, config, result, item)

    scheduler._replay_point = replay
    campaign.mutate = mutate
    campaign._apply_result = apply


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    metadata = preflight()
    if args.preflight_only:
        print(json.dumps({"preflight": "passed", **metadata}, sort_keys=True))
        return 0
    if args.admission_receipt is None or args.admission_receipt.resolve() != HERE / "admission-pilot-node0.json":
        parser.error("case-local dispatch GO receipt required before starting a JVM")
    go = read(args.admission_receipt)
    if (go.get("go") is not True or go.get("host") != "node0" or
            go.get("case_id") != "SOLR-37" or go.get("mode") != "pilot" or
            go.get("config_sha256") != metadata["config_sha256"] or
            go.get("runner_sha256") != metadata["runner_sha256"] or
            go.get("intended_output") != str(OUT)):
        raise ValueError("dispatch GO receipt absent or mismatched")
    if socket.gethostname().split(".", 1)[0] != "node0":
        raise ValueError("node0 execution only")
    if OUT.exists() and not (OUT / "checkpoint.json").is_file():
        raise ValueError("existing output has no resumable checkpoint")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    locks = []
    try:
        for name in ("zookeeper-node0-source.lock", "solr-node0-v1.lock",
                     "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locks.append(handle)
        if shutil.disk_usage(ROOT).free < 7_650_410_496:
            raise ValueError("insufficient free disk")
        available_kib = next(int(row.split()[1]) for row in
                             Path("/proc/meminfo").read_text().splitlines()
                             if row.startswith("MemAvailable:"))
        if available_kib < 8_388_608:
            raise ValueError("insufficient available RAM")
        processes = subprocess.check_output(["ps", "-eo", "user=,comm="], text=True)
        if any(row.split() == [getpass.getuser(), "java"] for row in processes.splitlines()):
            raise ValueError("another user JVM is running on node0")
        install_strict_runtime()
        state = campaign.run(HERE / "config-pilot-node0.json", OUT)
    finally:
        for handle in reversed(locks):
            handle.close()
    print(json.dumps({"status": state["status"],
                      "completed_trials": state["completed_trials"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
