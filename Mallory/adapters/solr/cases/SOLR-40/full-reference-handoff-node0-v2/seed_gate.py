"""Pure admission checks for a fresh SOLR-40 exact-reference seed."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from pathlib import Path

import audit_v2

DOOR = ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
        "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1")
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"


def sha(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"missing evidence: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()[:20]


def atomic_json(path: Path, value: dict) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w") as handle:
        json.dump(value, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)

def validate_seed(summary: dict, trial: dict, audit: dict) -> dict:
    """Require a fresh r0000 JUnit pass and observed exact-reference path."""
    junit = trial.get("junit_validation") or {}
    feedback = trial.get("feedback") or {}
    witnesses = audit.get("exact_reference_witnesses") or {}
    if not (summary.get("case_id") == trial.get("case_id") == "SOLR-40" and
            trial.get("trial_id") == 0 and trial.get("plan") == [] and
            trial.get("return_code") == 0 and trial.get("timed_out") is False and
            junit.get("runner") == "solr_junit_wrapper" and
            junit.get("status") == "passed" and
            (junit.get("tests"), junit.get("failures"), junit.get("errors"),
             junit.get("skipped")) == (1, 0, 0, 0) and
            feedback.get("status") == "observed" and
            feedback.get("target_reached") is True and
            feedback.get("target_threw") is False and
            feedback.get("target_identity_complete") is True and
            feedback.get("target_region_present") is True and
            feedback.get("watcher_exact_reference_witnesses") == witnesses and
            (trial.get("site_catalog_validation") or {}).get("valid") is True and
            (trial.get("site_catalog_validation") or {}).get("class_hash_match") is True and
            (trial.get("events_evidence") or {}).get("gzip_sha256") ==
            audit.get("trace_sha256") and
            junit.get("junit_log_sha256") == audit.get("junit_log_sha256") and
            summary.get("healthy_seed_valid") is True and
            (summary.get("runtime_attestation") or {}).get("valid") is True and
            summary.get("target_node_named") is True and
            summary.get("healthy_eligible_doors", 0) > 0 and
            audit.get("eligible_for_full_review") is True and
            audit.get("junit_status") == "passed" and
            audit.get("junit_tests") == 1 and
            audit.get("named_exact_target_checks", 0) > 0 and
            audit.get("named_observed_watcher_doors", 0) > 0 and
            audit.get("named_observed_watcher_doors") ==
            feedback.get("eligible_doors_before_target") == len(witnesses) and
            all("state_ref" in witness.get("edge_kinds", ()) and
                "return" in witness.get("edge_kinds", ()) and
                witness.get("reference_write_event") and
                witness.get("reference_read_event") and
                witness.get("target_event") for witness in witnesses.values())):
        raise ValueError("fresh r0000 exact-reference JUnit gate failed")
    return {"case_id": "SOLR-40", "status": "fresh_r0000_admitted",
            "junit": "1/0/0/0", "named_exact_target_checks":
            audit["named_exact_target_checks"],
            "named_observed_watcher_doors": audit["named_observed_watcher_doors"],
            "exact_reference_witnesses": witnesses,
            "trace_sha256": audit["trace_sha256"],
            "junit_log_sha256": audit["junit_log_sha256"],
            "trial_result_sha256": audit["trial_result_sha256"],
            "full_campaign_go_receipt_required": True}


def verified_points(trial: dict, verdict: dict) -> set[str]:
    """Only exact typed, named door occurrences with observed reference paths."""
    witnesses = verdict["exact_reference_witnesses"]
    points = set()
    for door in (trial.get("feedback") or {}).get("doors", []):
        point = door.get("point") or {}
        if door.get("event_id") not in witnesses:
            continue
        if not (door.get("in_closure") is True and
                door.get("fault_type") == "EXCEPTION" and
                door.get("exception_class") == EXCEPTION and
                point.get("site") == DOOR and
                isinstance(point.get("node"), str) and
                point["node"] not in ("", "unknown", "null", "None") and
                isinstance(point.get("epoch"), int) and
                isinstance(point.get("door_ordinal"), int) and
                point["door_ordinal"] > 0):
            continue
        points.add(json.dumps(point, sort_keys=True))
    if len(points) != len(witnesses):
        raise ValueError("fresh exact-reference witnesses do not bind unique named typed doors")
    return points


def validate_queue(queue: list, trial: dict, verdict: dict) -> None:
    allowed = verified_points(trial, verdict)
    if not queue or len(queue) != len(allowed):
        raise ValueError("fresh mutation queue does not enumerate admitted watcher doors")
    actual = set()
    for item in queue:
        faults = item.get("faults") or []
        if (len(faults) != 1 or item.get("selection_reason") != "dynamic_closure" or
                faults[0].get("fault_type") != "EXCEPTION" or
                faults[0].get("exception_class") != EXCEPTION):
            raise ValueError("fresh mutation queue contains an unverified fault")
        point = json.dumps(faults[0].get("point"), sort_keys=True)
        if point not in allowed or point in actual:
            raise ValueError("fresh mutation queue has an unverified or duplicate point")
        actual.add(point)
    if actual != allowed:
        raise ValueError("fresh mutation queue omits an admitted watcher door")


def promote(campaign: Path) -> dict:
    """Atomically promote a calibration-only checkpoint after fresh r0000 proof."""
    with (campaign / ".campaign.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = campaign / "checkpoint.json"
        state = read(state_path)
        if state.get("calibration_only") is False:
            return verify_promotion(campaign)
        config = read(campaign / "config.json")
        if not (config.get("case_id") == "SOLR-40" and
                sha(campaign / "config.json") == sha(Path(__file__).resolve().parent / "config.json") and
                config.get("auto_promote_if_healthy") is True and
                config.get("explore_outside_closure") is False and
                config.get("require_event_time_paths") is True and
                config.get("allow_local_timeline_doors") is False and
                config.get("reject_coarse_roots") is True and
                config.get("fault_types") == ["EXCEPTION"] and
                config.get("budget", {}).get("max_faults_per_trial") == 3 and
                state.get("config_digest") == digest(config) and
                state.get("status") == "calibration_complete" and
                state.get("calibration_only") is True and
                state.get("completed_trials") == [0] and
                state.get("running") is None and
                state.get("next_trial") == 1):
            raise ValueError("fresh calibration checkpoint cannot be promoted")
        summary = read(campaign / "result.json")
        if not (summary.get("status") == "calibration_complete" and
                summary.get("fault_trials_completed") == 0 and
                summary.get("case_id") == "SOLR-40"):
            raise ValueError("healthy phase did not end without faults")
        trial_path = campaign / "trials/r0000/result.json"
        trial = read(trial_path)
        verdict = validate_seed(summary, trial, audit_v2.audit(campaign))
        validate_queue(state.get("queue") or [], trial, verdict)
        verdict["queue_entries"] = len(state["queue"])
        verdict["config_sha256"] = sha(campaign / "config.json")
        verdict["summary_sha256_at_promotion"] = sha(campaign / "result.json")
        gate_path = campaign / "fresh-r0000-gate.json"
        if gate_path.exists():
            # A controller may stop after the durable gate write and before
            # flipping the checkpoint. Revalidate fresh raw evidence, queue,
            # and config above, then accept only the identical durable gate.
            if read(gate_path) != verdict:
                raise ValueError("stranded admission gate disagrees with fresh r0000")
        else:
            atomic_json(gate_path, verdict)
        state["calibration_only"] = False
        state["status"] = "running"
        state["updated_at"] = time.time()
        state["promoted_healthy_gate_sha256"] = sha(gate_path)
        atomic_json(state_path, state)
        return verdict


def verify_promotion(campaign: Path) -> dict:
    """Check the immutable r0000 proof before every fault trial or resume."""
    state = read(campaign / "checkpoint.json")
    config = read(campaign / "config.json")
    gate_path = campaign / "fresh-r0000-gate.json"
    gate = read(gate_path)
    if not (state.get("config_digest") == digest(config) and
            sha(campaign / "config.json") == sha(Path(__file__).resolve().parent / "config.json") and
            state.get("calibration_only") is False and
            state.get("promoted_healthy_gate_sha256") == sha(gate_path) and
            state.get("completed_trials", [None])[0] == 0 and
            gate.get("case_id") == "SOLR-40" and
            gate.get("status") == "fresh_r0000_admitted" and
            gate.get("queue_entries", 0) > 0 and
            gate.get("config_sha256") == sha(campaign / "config.json") and
            gate.get("trial_result_sha256") == sha(campaign / "trials/r0000/result.json") and
            gate.get("trace_sha256") == sha(campaign / "trials/r0000/events.jsonl.gz") and
            gate.get("junit_log_sha256") == sha(campaign / "trials/r0000/junit.log") and
            gate.get("exact_reference_witnesses")):
        raise ValueError("promoted checkpoint or exact-reference seed changed")
    return gate


def validate_plan(campaign: Path, plan: list) -> None:
    """Allow later mutations only from previously observed exact paths."""
    gate = verify_promotion(campaign)
    if not plan or len(plan) > 3:
        raise ValueError("empty or over-budget fault plan")
    state = read(campaign / "checkpoint.json")
    healthy = read(campaign / "trials/r0000/result.json")
    allowed = verified_points(healthy, gate)
    for trial_id in state.get("completed_trials", []):
        if trial_id == 0:
            continue
        source = read(campaign / "trials" / f"r{trial_id:04d}" / "result.json")
        feedback = source.get("feedback") or {}
        if not (feedback.get("all_faults_effective") is True and
                feedback.get("target_reached") is True and
                feedback.get("target_identity_complete") is True and
                feedback.get("target_region_present") is True and
                feedback.get("watcher_handoff_evidence") ==
                "observed_event_time_path_only"):
            continue
        witnesses = feedback.get("watcher_exact_reference_witnesses") or {}
        for door in feedback.get("doors", []):
            point = door.get("point") or {}
            witness = witnesses.get(door.get("event_id")) or {}
            if (door.get("in_closure") is True and
                    door.get("fault_type") == "EXCEPTION" and
                    door.get("exception_class") == EXCEPTION and
                    point.get("site") == DOOR and
                    isinstance(point.get("node"), str) and
                    point["node"] not in ("", "unknown", "null", "None") and
                    isinstance(point.get("epoch"), int) and
                    isinstance(point.get("door_ordinal"), int) and
                    point["door_ordinal"] > 0 and
                    "state_ref" in witness.get("edge_kinds", ()) and
                    "return" in witness.get("edge_kinds", ()) and
                    witness.get("reference_write_event") and
                    witness.get("reference_read_event") and
                    witness.get("target_event")):
                allowed.add(json.dumps(point, sort_keys=True))
    for fault in plan:
        if not (fault.get("fault_type") == "EXCEPTION" and
                fault.get("exception_class") == EXCEPTION and
                json.dumps(fault.get("point"), sort_keys=True) in allowed):
            raise ValueError("fault point lacks a prior observed exact-reference path")
