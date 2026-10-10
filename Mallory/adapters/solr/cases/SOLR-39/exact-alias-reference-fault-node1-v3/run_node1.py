#!/usr/bin/env python3
"""Dispatch-gated one-fault SOLR-39 MiniSolrCloudCluster pilot on node1."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

from audit_pilot import audit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
OUT = ROOT / "data/mallory/pilots/SOLR-39-exact-alias-reference-node1-v3"
DISK_FLOOR = 7_650_410_496
MEM_FLOOR_KIB = 8_388_608


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def preflight() -> dict:
    pins = read(HERE / "pins.json")
    for name, expected in pins["files"].items():
        path = Path(name) if name.startswith("/") else ROOT / name
        require(path.is_file() and sha(path) == expected, f"missing or changed pin: {path}")
    config = read(HERE / "config.json")
    plan = read(HERE / "fault-plan.json")
    review = read(ROOT / "Mallory/adapters/solr/cases/SOLR-39/"
                  "exact-alias-reference-offline-v2/evidence-review.json")
    require(review["archive_sha256"] == pins["healthy_archive_sha256"] and
            sha(ROOT / review["archive"]) == pins["healthy_archive_sha256"],
            "sealed healthy archive changed")
    with tarfile.open(ROOT / review["archive"], "r:gz") as archive:
        event_stream = archive.extractfile(
            "SOLR-39-aliasref-healthy-node1-v1/trials/r0000/events.jsonl.gz")
        require(event_stream is not None, "sealed healthy event stream missing")
        healthy_events = [json.loads(line) for line in gzip.decompress(
            event_stream.read()).decode("utf-8").splitlines() if line]
    selected_door = [row for row in healthy_events if row.get("seq") == 4593]
    require(len(selected_door) == 1 and
            selected_door[0].get("type") == "DOOR_OBSERVED" and
            selected_door[0].get("node") == "node2" and
            selected_door[0].get("epoch") == 0 and
            selected_door[0].get("door_ordinal") == 1 and
            selected_door[0].get("exception_class") ==
            "org.apache.zookeeper.KeeperException$ConnectionLossException",
            "sealed healthy door identity changed")
    healthy_paths = review["audit"]["candidate_paths"]
    require(len(healthy_paths) == 1 and review["audit"]["paired_field_events"] == 310 and
            review["audit"]["transform_errors"] == 0 and
            not any(review["audit"]["owner_identity_collisions"].values()) and
            review["junit"] == {"tests": 1, "failures": 0, "errors": 0, "status": "passed"},
            "healthy exact-reference admission missing")
    path = healthy_paths[0]
    for label, key in (("healthy_watcher_door_seq", "watcher_door_seq"),
                       ("healthy_cache_write_seq", "cache_write_seq"),
                       ("healthy_constructor_read_seq", "constructor_read_seq"),
                       ("healthy_target_read_seq", "target_read_seq"),
                       ("healthy_target_check_seq", "target_check_seq"),
                       ("healthy_manager_ref", "owner_ref"),
                       ("healthy_aliases_ref", "aliases_ref")):
        require(plan["selection"][label] == path[key], f"healthy selection changed: {label}")
    require(plan["selection"]["healthy_archive_sha256"] == pins["healthy_archive_sha256"],
            "fault plan points to different healthy archive")
    faults = plan["faults"]
    require(len(faults) == 1 and faults[0]["point"] == {
        "site": "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
                "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1",
        "node": path["node"], "epoch": path["epoch"], "door_ordinal": 1} and
        faults[0]["fault_type"] == "EXCEPTION" and
        faults[0]["exception_class"] ==
        "org.apache.zookeeper.KeeperException$ConnectionLossException",
        "fault plan is not the selected typed node2 watcher door")
    require(config["case_id"] == "SOLR-39" and config["system"] == "solr" and
            config["cluster_test"] ==
            "org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#test" and
            config["budget"] == {"trials": 1, "seconds": 900,
                                 "max_faults_per_trial": 1, "trial_timeout_seconds": 480} and
            not config["calibration_only"] and not config["auto_promote_if_healthy"] and
            config["require_event_time_paths"] and config["reject_coarse_roots"] and
            config["fault_types"] == ["EXCEPTION"],
            "pilot config or one-fault budget changed")
    require(config["target"]["check_sites"] == [
        "org.apache.solr.update.processor.RoutedAliasUpdateProcessor"
        "#lookupShardLeadersOfCollections()Ljava/util/List;@246:branch:1"],
        "exact selected check changed")
    require(config["core_release"] == str(RELEASE) and
            config["agent_properties"]["adapter.transformers"].endswith(
                ",edu.uva.liftlab.mallory.solr.aliasref.AliasValueTransformer") and
            config["agent_properties"]["state.fields"] and
            config["env"]["MALLORY_ALIAS_REF_TRACE"] == "1",
            "exact reference telemetry absent")
    release_manifest = read(RELEASE / "manifest.json")
    for name, expected in release_manifest["files"].items():
        release_file = RELEASE / name
        require(release_file.is_file() and sha(release_file) == expected,
                f"pinned core release changed: {name}")
    for row in config["runtime_artifacts"]:
        runtime_path = Path(row["path"])
        require(runtime_path.is_file() and sha(runtime_path) == row["sha256"],
                f"runtime artifact changed: {runtime_path}")
    source = Path(config["cwd"])
    require(source.is_dir() and config["source_equivalent_root"] == str(source),
            "pinned Solr source missing")
    require(sha(source / config["target"]["source_path"]) ==
            config["mapping"]["target_source_sha256"], "selected target source changed")
    test_source = source / "solr/core/src/test/org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.java"
    require(sha(test_source) == config["mapping"]["test_source_sha256"],
            "selected JUnit source changed")
    compiled = Path(config["mapping"]["compiled_jar"])
    require(sha(compiled) == config["mapping"]["compiled_jar_sha256"],
            "compiled Solr core JAR changed")
    with zipfile.ZipFile(compiled) as archive:
        target_class = archive.read("org/apache/solr/update/processor/RoutedAliasUpdateProcessor.class")
    require(hashlib.sha256(target_class).hexdigest() ==
            config["expected_target_class_sha256"], "compiled target class changed")
    with zipfile.ZipFile(HERE / "alias-value-adapter.jar") as archive:
        require({"edu/uva/liftlab/mallory/solr/aliasref/AliasValueTrace.class",
                 "edu/uva/liftlab/mallory/solr/aliasref/AliasValueTransformer.class"}
                <= set(archive.namelist()), "exact reference adapter class missing")
    sys.path.insert(0, str(RELEASE))
    from Mallory.core import campaign
    require(Path(campaign.__file__).resolve().is_relative_to(RELEASE),
            "pinned campaign implementation unavailable")
    campaign.validate_config(config)
    return {"case_id": "SOLR-39", "host": "node1", "mode": "one_fault_pilot",
            "config_sha256": sha(HERE / "config.json"),
            "fault_plan_sha256": sha(HERE / "fault-plan.json"),
            "agent_sha256": sha(Path(config["agent_jar"])),
            "healthy_archive_sha256": pins["healthy_archive_sha256"],
            "healthy_review_sha256": sha(ROOT / "Mallory/adapters/solr/cases/SOLR-39/"
                                         "exact-alias-reference-offline-v2/evidence-review.json"),
            "pins_sha256": sha(HERE / "pins.json"),
            "audit_sha256": sha(HERE / "audit_pilot.py"),
            "runner_sha256": sha(Path(__file__)), "intended_output": str(OUT),
            "preflight": "passed", "jvm_run": False}


def no_competing_jvm() -> None:
    processes = subprocess.check_output(["ps", "-u", str(os.getuid()), "-o", "comm="],
                                        text=True).splitlines()
    require(not any(name.strip() in {"java", "mvn", "javac"} for name in processes),
            "competing user JVM or Maven process")


def check_go(path: Path, evidence: dict) -> dict:
    receipt = read(path)
    required = {key: evidence[key] for key in (
        "case_id", "host", "mode", "config_sha256", "fault_plan_sha256",
        "agent_sha256", "healthy_archive_sha256", "healthy_review_sha256",
        "pins_sha256", "audit_sha256", "runner_sha256", "intended_output")}
    require(receipt.get("go") is True and
            all(receipt.get(key) == value for key, value in required.items()) and
            isinstance(receipt.get("attempt_id"), str) and receipt["attempt_id"],
            "dispatch GO receipt missing or does not pin this pilot")
    return receipt


def live_group(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def run(evidence: dict, receipt: dict) -> dict:
    sys.path.insert(0, str(RELEASE))
    from Mallory.core import campaign
    config = read(HERE / "config.json")
    plan = read(HERE / "fault-plan.json")["faults"]
    OUT.mkdir(parents=True, exist_ok=True)
    saved_config = OUT / "config.json"
    if saved_config.exists():
        require(sha(saved_config) == evidence["config_sha256"],
                "existing pilot output has different config")
    else:
        shutil.copyfile(HERE / "config.json", saved_config)
    trial = OUT / "trials/r0001"
    result_file = trial / "result.json"
    running_file = OUT / "running.json"
    if not result_file.exists():
        prior = read(running_file) if running_file.exists() else {}
        require(not live_group(prior.get("pid")),
                "previous pilot trial process group is still live")
    if not result_file.exists() and trial.exists():
        interrupted = OUT / "interrupted" / f"r0001-{int(time.time())}"
        interrupted.parent.mkdir(parents=True, exist_ok=True)
        trial.rename(interrupted)
    if not result_file.exists():
        os.environ["MALLORY_ATTEMPT_ID"] = receipt["attempt_id"]

        def save_running(pid: int) -> None:
            campaign.atomic_json(running_file, {"pid": pid, "trial_id": 1,
                                                "attempt_id": receipt["attempt_id"],
                                                "fault_plan_sha256": evidence["fault_plan_sha256"]})

        campaign._run_trial(config, OUT, 1, plan, save_running, {"nodes": ["node2"]})
    result = read(result_file)
    require(result.get("case_id") == "SOLR-39" and result.get("trial_id") == 1 and
            result.get("plan") == plan, "fault trial result differs from pinned plan")
    post = audit(trial, plan[0])
    campaign.atomic_json(OUT / "fault-audit.json", post)
    summary = {"schema_version": 1, "case_id": "SOLR-39", "mode": "one_fault_pilot",
               "status": post["qualification"], "duration_seconds": result["elapsed_seconds"],
               "fault_trials_completed": 1,
               "strict_injected_trials": int(post["strict_fault_effective"]),
               "strict_target_trials": int(post["target_retained_same_manager"]),
               "exact_exception_trials": int(post["target_exception_candidate"]),
               "new_bug": None, "fault_audit": "fault-audit.json",
               "trial_result": "trials/r0001/result.json",
               "config_sha256": evidence["config_sha256"],
               "fault_plan_sha256": evidence["fault_plan_sha256"],
               "healthy_archive_sha256": evidence["healthy_archive_sha256"],
               "admission_receipt_sha256": sha(Path(receipt["receipt_path"]))}
    campaign.atomic_json(OUT / "pilot-summary.json", summary)
    campaign.atomic_json(running_file, {"trial_id": 1, "status": "completed",
                                        "attempt_id": receipt["attempt_id"]})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    evidence = preflight()
    if args.preflight_only:
        print(json.dumps(evidence, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("dispatch GO receipt is required before a JVM")
    receipt = check_go(args.admission_receipt, evidence)
    receipt["receipt_path"] = str(args.admission_receipt)
    require(socket.gethostname().split(".", 1)[0] == "node1", "pilot host is not node1")
    handles = []
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    try:
        for name in ("solr-node1-lane.lock", "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        no_competing_jvm()
        require(shutil.disk_usage(ROOT).free >= DISK_FLOOR,
                "insufficient disk before Solr JUnit")
        available = next(int(row.split()[1]) for row in Path("/proc/meminfo").read_text().splitlines()
                         if row.startswith("MemAvailable:"))
        require(available >= MEM_FLOOR_KIB, "insufficient available memory")
        summary = run(evidence, receipt)
        print(json.dumps(summary, sort_keys=True))
    finally:
        for handle in reversed(handles):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
