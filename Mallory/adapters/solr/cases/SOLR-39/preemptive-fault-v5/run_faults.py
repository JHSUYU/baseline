#!/usr/bin/env python3
"""GO-gated, checkpoint-safe SOLR-39 preemptive alias watcher campaign."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import zipfile

from audit_trial import audit, events_from

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
HEALTHY = ROOT / "data/mallory/pilot_observations/SOLR-39-preemptive-healthy-node1-v3/trials/r0000"
HEALTHY_RECEIPT = ROOT / "data/mallory/evidence_archives/SOLR-39-preemptive-healthy-node1-v3.receipt.json"
HEALTHY_ARCHIVE = ROOT / "data/mallory/evidence_archives/SOLR-39-preemptive-healthy-node1-v3.tar.gz"
OVERLAY = HERE.parent / "preemptive-graph-gap-v4"
OUT = ROOT / "data/mallory/solr39_preemptive_fault_v5_node1/SOLR-39"
DISK_FLOOR = 7_650_410_496
MEM_FLOOR_KIB = 8_388_608


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def signature(plan: list[dict]) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def selected_points() -> list[dict]:
    stage = read(HERE / "selected-doors.json")
    return stage["selected_healthy_points"]


def make_fault(point: dict) -> dict:
    door = point["point"]
    return {"fault_id": f"solr39_v5_{door['node']}_{door['epoch']}_{door['door_ordinal']}",
            "point": door, "fault_type": "EXCEPTION",
            "exception_class": point["exception_class"]}


def initial_state(config: dict, go_sha: str) -> dict:
    points = selected_points()
    queue = []
    for index, point in enumerate(points):
        plan = [make_fault(point)]
        queue.append({"plan": plan, "signature": signature(plan),
                      "priority": 100 - index, "queued_at": 0,
                      "selection_reason": "sealed_healthy_late_watcher"})
    healthy_feedback = read(HEALTHY / "result.json")["feedback"]
    return {"schema_version": 1, "case_id": "SOLR-39", "status": "running",
            "config_sha256": sha(HERE / "config.json"), "admission_go_sha256": go_sha,
            "healthy_archive_sha256": sha(HEALTHY_ARCHIVE),
            "offline_proof_sha256": sha(OVERLAY / "offline-proof.json"),
            "started_at": time.time(), "elapsed_seconds": 0.0,
            "next_trial": 1, "completed_fault_trials": [], "running": None,
            "queue": queue, "seen_sequences": [item["signature"] for item in queue],
            "coverage_ids": sorted(set(healthy_feedback.get("coverage_ids", []))),
            "closure_coverage_ids": sorted(set(healthy_feedback.get("closure_coverage_ids", []))),
            "edge_keys": [], "exact_target_exception_candidates": [],
            "valid_trials": [], "invalid_trials": []}


def preflight() -> dict:
    config = read(HERE / "config.json")
    points = selected_points()
    receipt = read(HEALTHY_RECEIPT)
    proof = read(OVERLAY / "offline-proof.json")
    stage = read(OVERLAY / "fault-stage-request.json")
    require(config["case_id"] == "SOLR-39" and config["system"] == "solr" and
            config["cluster_test"] ==
            "org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest#testPreemptiveCreation" and
            config["budget"] == {"trials": 12, "seconds": 2400,
                                 "max_faults_per_trial": 3, "trial_timeout_seconds": 480} and
            not config["calibration_only"] and not config["auto_promote_if_healthy"] and
            not config["explore_outside_closure"] and
            config["require_event_time_paths"] and config["reject_coarse_roots"],
            "campaign config or budget changed")
    require(config["core_release"] == str(RELEASE) and
            config["command"][1].endswith("/preemptive-healthy-v3/run_pilot.py") and
            "--campaign" in config["command"] and
            config["target"]["check_sites"] == [
                "org.apache.solr.update.processor.RoutedAliasUpdateProcessor"
                "#lookupShardLeadersOfCollections()Ljava/util/List;@246:branch:1"],
            "pinned JUnit runner or exact target changed")
    require(receipt["healthy_seed_valid"] and receipt["junit_1_0_0"] and
            receipt["exact_target_checks"] == 11 and
            receipt["archive_sha256"] == stage["healthy_archive_sha256"] ==
            sha(HEALTHY_ARCHIVE) and
            receipt["trace_gzip_sha256"] == sha(HEALTHY / "events.jsonl.gz"),
            "sealed healthy seed changed")
    require(sha(OVERLAY / "offline-proof.json") == stage["offline_proof_sha256"] and
            proof["status"] == "strict_late_healthy_doors_observed" and
            len(proof["late_qualified_paths"]) == len(points) == 3 and
            points == stage["selected_healthy_points"],
            "sealed graph overlay or selected doors changed")
    require([(p["point"]["node"], p["point"]["epoch"],
              p["point"]["door_ordinal"], p["healthy_door_seq"])
             for p in points] == [("node2", 0, 12, 23175),
                                  ("node3", 0, 13, 25649),
                                  ("node2", 0, 15, 32156)] and
            all(p["resource_from_pinned_source"] == "/aliases.json" and
                p["exception_class"] ==
                "org.apache.zookeeper.KeeperException$ConnectionLossException"
                for p in points), "selected runtime resource, actor or typed exception changed")
    java = Path(config["cwd"]) / "solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java"
    source = java.read_text()
    require(sha(java) == config["mapping"]["reader_source_sha256"] and
            'zkClient.getData(ALIASES, this, stat, true)' in source and
            'public static final String ALIASES = "/aliases.json";' in source and
            'catch (KeeperException.ConnectionLossException | KeeperException.SessionExpiredException e)' in source,
            "watcher source or actual fixed resource changed")
    jar = HERE / "preemptive-gate.jar"
    require(jar.is_file() and
            config["runtime_artifacts"][-1] == {"path": str(jar), "sha256": sha(jar)} and
            config["agent_properties"]["adapter.jars"].endswith(str(jar)) and
            config["agent_properties"]["adapter.transformers"].endswith(
                "edu.uva.liftlab.mallory.solr.solr39.PreemptiveTransformer"),
            "case-local pre-injection resource gate not selected")
    with zipfile.ZipFile(jar) as archive:
        require({"edu/uva/liftlab/mallory/solr/solr39/PreemptiveGate.class",
                 "edu/uva/liftlab/mallory/solr/solr39/PreemptiveTransformer.class"}
                <= set(archive.namelist()), "case-local gate classes missing")
    verification = read(HERE / "offline-verification.json")
    require(verification["actual_wrong_path_control"] == "WRONG_PATH_FAIL_CLOSED_OK" and
            verification["actual_exact_path_control"] == "EXACT_PATH_GATE_OK" and
            verification["pinned_woven_class"].startswith("WOVEN_CLASS_VERIFY_OK ") and
            verification["gate_jar_sha256"] == sha(jar) and
            verification["junit_or_cluster_started"] is False,
            "offline -Xverify:all gate controls missing")
    for artifact in config["runtime_artifacts"]:
        path = Path(artifact["path"])
        require(path.is_file() and sha(path) == artifact["sha256"],
                f"runtime artifact changed: {path}")
    release_manifest = read(RELEASE / "manifest.json")
    for name, expected in release_manifest["files"].items():
        path = RELEASE / name
        require(path.is_file() and sha(path) == expected,
                f"pinned controller changed: {name}")
    sys.path.insert(0, str(RELEASE))
    from Mallory.core import campaign
    require(Path(campaign.__file__).resolve().is_relative_to(RELEASE),
            "pinned controller release unavailable")
    campaign.validate_config(config)
    manifest = read(HERE / "sha-manifest.json")
    for name, expected in manifest["files"].items():
        require(sha(HERE / name) == expected, f"package file changed: {name}")
    return {"case_id": "SOLR-39", "host": "node1", "mode": "preemptive_fault_v5",
            "config_sha256": sha(HERE / "config.json"),
            "selected_doors_sha256": sha(HERE / "selected-doors.json"),
            "jar_sha256": sha(jar), "manifest_sha256": sha(HERE / "sha-manifest.json"),
            "runner_sha256": sha(Path(__file__)),
            "audit_sha256": sha(HERE / "audit_trial.py"),
            "healthy_archive_sha256": sha(HEALTHY_ARCHIVE),
            "offline_proof_sha256": sha(OVERLAY / "offline-proof.json"),
            "intended_output": str(OUT), "go": False,
            "jvm_run": False, "status": "offline_preflight_passed"}


def check_go(path: Path, pre: dict) -> dict:
    go = read(path)
    names = ("case_id", "host", "mode", "config_sha256", "selected_doors_sha256",
             "jar_sha256", "manifest_sha256", "runner_sha256", "audit_sha256",
             "healthy_archive_sha256", "offline_proof_sha256", "intended_output")
    require(go.get("go") is True and all(go.get(key) == pre[key] for key in names) and
            isinstance(go.get("attempt_id"), str) and bool(go["attempt_id"]),
            "fresh dispatch GO receipt absent or SHA mismatch")
    return go


def _live_group(pid: int | None) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _observed_later_point(rows: list[dict], point: dict, after_seq: int) -> bool:
    p = point["point"]
    return any(row.get("type") == "DOOR_OBSERVED" and row["seq"] > after_seq and
               all(row.get(key) == p[key] for key in
                   ("site", "node", "epoch", "door_ordinal")) for row in rows)


def apply_result(state: dict, config: dict, result: dict, post: dict,
                 rows: list[dict], item: dict) -> None:
    """Only fully strict trials can contribute coverage novelty or children."""
    trial_id = result["trial_id"]
    require(trial_id not in state["completed_fault_trials"] and
            result["plan"] == item["plan"], "trial/checkpoint identity mismatch")
    state["completed_fault_trials"].append(trial_id)
    state["elapsed_seconds"] += result["elapsed_seconds"]
    state["running"] = None
    state["next_trial"] = trial_id + 1
    novelty = {"coverage": 0, "closure_coverage": 0, "observed_reference_edges": 0}
    if not post["valid"]:
        state["invalid_trials"].append({"trial_id": trial_id,
                                        "reason": post["qualification"]})
        result["case_local_novelty"] = novelty
        result["case_local_valid"] = False
        return
    state["valid_trials"].append(trial_id)
    feedback = result.get("feedback", {})
    coverage = set(feedback.get("coverage_ids", []))
    closure = set(feedback.get("closure_coverage_ids", []))
    old_coverage, old_closure = set(state["coverage_ids"]), set(state["closure_coverage_ids"])
    novelty["coverage"] = len(coverage - old_coverage)
    novelty["closure_coverage"] = len(closure - old_closure)
    state["coverage_ids"] = sorted(old_coverage | coverage)
    state["closure_coverage_ids"] = sorted(old_closure | closure)
    edge_keys = {f"{p['cache_write_seq']}:{p['target_read_seq']}:{p['target_check_seq']}"
                 for p in post["retained_reference_paths"]}
    novelty["observed_reference_edges"] = len(edge_keys - set(state["edge_keys"]))
    state["edge_keys"] = sorted(set(state["edge_keys"]) | edge_keys)
    result["case_local_novelty"] = novelty
    result["case_local_valid"] = True
    if post["exact_target_exception_candidate"]:
        state["exact_target_exception_candidates"].append(trial_id)
        if item.get("selection_reason") != "candidate_replay":
            state["queue"].insert(0, {**item, "priority": 1000,
                                       "selection_reason": "candidate_replay",
                                       "queued_at": trial_id, "replay_of": trial_id})
    if item.get("selection_reason") == "candidate_replay":
        return
    points = selected_points()
    order = {(p["point"]["node"], p["point"]["door_ordinal"]): i
             for i, p in enumerate(points)}
    last = item["plan"][-1]["point"]
    last_index = order[last["node"], last["door_ordinal"]]
    last_applied = post["faults"][-1]["applied_seq"]
    for point in points[last_index + 1:]:
        if not _observed_later_point(rows, point, last_applied):
            continue
        plan = item["plan"] + [make_fault(point)]
        if len(plan) > config["budget"]["max_faults_per_trial"]:
            continue
        sig = signature(plan)
        if sig in state["seen_sequences"]:
            continue
        score = (15 + 2 * len(plan) + 0.25 * novelty["coverage"] +
                 2 * novelty["closure_coverage"] +
                 3 * novelty["observed_reference_edges"])
        state["queue"].append({"plan": plan, "signature": sig,
                               "priority": round(score, 3), "queued_at": trial_id,
                               "selection_reason": "strict_retained_reference_mutation"})
        state["seen_sequences"].append(sig)


def run(pre: dict, go: dict, go_path: Path) -> dict:
    sys.path.insert(0, str(RELEASE))
    from Mallory.core import campaign
    config = read(HERE / "config.json")
    OUT.mkdir(parents=True, exist_ok=True)
    go_sha = sha(go_path)
    checkpoint = OUT / "checkpoint.json"
    if checkpoint.exists():
        state = read(checkpoint)
        require(state["config_sha256"] == pre["config_sha256"] and
                state["admission_go_sha256"] == go_sha and
                state["healthy_archive_sha256"] == pre["healthy_archive_sha256"] and
                state["offline_proof_sha256"] == pre["offline_proof_sha256"],
                "checkpoint belongs to another release or GO")
    else:
        require(not any(OUT.iterdir()), "output exists without checkpoint")
        state = initial_state(config, go_sha)
        campaign.atomic_json(checkpoint, state)
    while state["status"] == "running":
        if len(state["completed_fault_trials"]) >= config["budget"]["trials"]:
            state["status"] = "budget_exhausted"
            break
        if state["elapsed_seconds"] >= config["budget"]["seconds"]:
            state["status"] = "time_budget_exhausted"
            break
        pending = state["running"]
        if pending is None:
            if not state["queue"]:
                state["status"] = "queue_exhausted"
                break
            state["queue"].sort(key=lambda item: (-item["priority"] -
                                                    0.05 * (state["next_trial"] - item["queued_at"]),
                                                    item["queued_at"], item["signature"]))
            item = state["queue"].pop(0)
            pending = {"trial_id": state["next_trial"], "item": item,
                       "pid": None, "attempt_id": go["attempt_id"]}
            state["running"] = pending
            campaign.atomic_json(checkpoint, state)
        else:
            require(pending["attempt_id"] == go["attempt_id"],
                    "pending trial belongs to another attempt")
        item = pending["item"]
        trial_id = pending["trial_id"]
        trial = OUT / "trials" / f"r{trial_id:04d}"
        result_file = trial / "result.json"
        if not result_file.exists():
            require(shutil.disk_usage(ROOT).free >= DISK_FLOOR,
                    "node1 disk fell below reserve before next trial")
            available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                             if line.startswith("MemAvailable:"))
            require(available >= MEM_FLOOR_KIB,
                    "node1 memory fell below reserve before next trial")
            require(not _live_group(pending.get("pid")),
                    "prior trial JVM process group is still alive")
            if trial.exists():
                interrupted = OUT / "interrupted" / f"r{trial_id:04d}-{int(time.time())}"
                interrupted.parent.mkdir(exist_ok=True)
                trial.rename(interrupted)
            trial_config = copy.deepcopy(config)
            trial_config["env"]["MALLORY_SOLR39_SELECTED_DOORS"] = ",".join(
                f"{f['point']['node']}@{f['point']['epoch']}:{f['point']['door_ordinal']}"
                for f in item["plan"])
            os.environ["MALLORY_ATTEMPT_ID"] = go["attempt_id"]

            def save_running(pid: int) -> None:
                pending["pid"] = pid
                campaign.atomic_json(checkpoint, state)

            campaign._run_trial(trial_config, OUT, trial_id, item["plan"],
                                save_running, None)
        result = read(result_file)
        require(result["trial_id"] == trial_id and result["plan"] == item["plan"] and
                result["dispatch_attempt_id"] == go["attempt_id"],
                "trial result does not belong to this plan/GO")
        post = audit(trial, item["plan"])
        try:
            rows = events_from(trial)
        except (OSError, ValueError, json.JSONDecodeError):
            rows = []
        campaign.atomic_json(trial / "case-local-audit.json", post)
        apply_result(state, config, result, post, rows, item)
        campaign.atomic_json(result_file, result)
        campaign.atomic_json(checkpoint, state)
    campaign.atomic_json(checkpoint, state)
    summary = {"case_id": "SOLR-39", "status": state["status"],
               "fault_trials_completed": len(state["completed_fault_trials"]),
               "valid_trials": state["valid_trials"], "invalid_trials": state["invalid_trials"],
               "exact_target_exception_candidates": state["exact_target_exception_candidates"],
               "elapsed_seconds": round(state["elapsed_seconds"], 3),
               "new_bug_confirmed": False, "config_sha256": pre["config_sha256"],
               "healthy_archive_sha256": pre["healthy_archive_sha256"],
               "offline_proof_sha256": pre["offline_proof_sha256"],
               "go_receipt_sha256": go_sha}
    campaign.atomic_json(OUT / "campaign-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    pre = preflight()
    if args.preflight_only:
        print(json.dumps(pre, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("fresh dispatch GO receipt is required before a JVM")
    go = check_go(args.admission_receipt, pre)
    require(socket.gethostname().split(".", 1)[0] == "node1",
            "SOLR-39 v5 is assigned to node1")
    locks = []
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    try:
        for name in ("solr-node1-lane.lock", "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locks.append(handle)
        processes = subprocess.check_output(["ps", "-u", str(os.getuid()), "-o", "comm="],
                                            text=True).splitlines()
        require(not any(name.strip() in {"java", "mvn", "javac"} for name in processes),
                "competing user JVM or Maven process")
        require(shutil.disk_usage(ROOT).free >= DISK_FLOOR, "node1 disk below reserve")
        available = next(int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()
                         if line.startswith("MemAvailable:"))
        require(available >= MEM_FLOOR_KIB, "node1 memory below reserve")
        print(json.dumps(run(pre, go, args.admission_receipt), sort_keys=True))
    finally:
        for handle in reversed(locks):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
