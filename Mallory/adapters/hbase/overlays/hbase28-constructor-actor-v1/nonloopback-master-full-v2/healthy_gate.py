#!/usr/bin/env python3
"""Admit HBASE-28 fault trials only after a matching fresh healthy r0000.

The controller's calibration-only run creates the queue but does not execute
it. This gate verifies the exact, typed, same-occurrence read/check pair and
then promotes that checkpoint without rerunning the healthy workload.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

CASE = "HBASE-28"
DOOR = ("org.apache.hadoop.hbase.util.Addressing#isLocalAddress"
        "(Ljava/net/InetAddress;)Z@148:door:1")
CHECK = ("org.apache.hadoop.hbase.regionserver.HRegionServer#putUpWebUI()V"
         "@2482:branch:3")
THROW = ("org.apache.hadoop.hbase.regionserver.HRegionServer#putUpWebUI()V"
         "@2487:throw:1")
EXCEPTION = "java.net.SocketException"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    require(path.is_file(), f"missing evidence: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected JSON object: {path}")
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


def verify_pair(campaign: Path, *, require_local_timeline: bool) -> dict:
    summary_path = campaign / "result.json"
    trial_path = campaign / "trials/r0000/result.json"
    trace_path = campaign / "trials/r0000/events.jsonl.gz"
    summary, trial = read(summary_path), read(trial_path)
    feedback = trial["feedback"]
    require(summary.get("case_id") == trial.get("case_id") == CASE,
            "wrong healthy case")
    require(summary.get("status") == "calibration_complete" and
            summary.get("fault_trials_completed") == 0,
            "healthy phase did not terminate without faults")
    require(summary.get("healthy_seed_valid") is True and
            summary.get("target_binding") == {"nodes": ["master0", "rs0"]} and
            summary.get("target_node_named") is True,
            "healthy target is not bound to master0")
    attestation = summary.get("runtime_attestation") or {}
    require(attestation.get("valid") is True and
            attestation.get("bound_nodes") == ["master0", "rs0"] and
            attestation.get("target_identity_gap_count") == 0 and
            attestation.get("exact_site_catalog_valid") is True,
            "healthy runtime identity is incomplete")
    junit = trial.get("junit_validation") or {}
    require(junit.get("status") == "passed" and junit.get("tests") == 1 and
            junit.get("failures") == junit.get("errors") == junit.get("skipped") == 0,
            "unchanged cluster JUnit did not pass 1/0/0")
    require(feedback.get("status") == "observed" and
            feedback.get("target_reached") is True and
            feedback.get("target_threw") is False and
            feedback.get("target_identity_complete") is True and
            feedback.get("target_region_present") is True and
            {x.get("node") for x in feedback.get("target_instances", [])} ==
            {"master0", "rs0"},
            "exact healthy target failed or was ambiguous")
    require(trial.get("site_catalog_validation", {}).get("valid") is True,
            "exact runtime site catalog failed")
    evidence = trial.get("events_evidence") or {}
    require(sha(trace_path) == evidence.get("gzip_sha256"),
            "healthy compressed trace SHA mismatch")
    raw = gzip.decompress(trace_path.read_bytes())
    require(hashlib.sha256(raw).hexdigest() == evidence.get("raw_sha256") and
            len(raw) == evidence.get("raw_bytes"),
            "healthy raw trace SHA or size mismatch")
    events = [json.loads(line) for line in raw.splitlines()]
    checks = [e for e in events if e.get("type") == "TARGET_CHECK" and
              e.get("site") == CHECK and e.get("node") == "master0"]
    require(len(checks) == 1, "expected one named master0 exact @2482 check")
    require(not any(e.get("type") == "TARGET_THROW" and e.get("site") == THROW
                    for e in events), "healthy target threw")
    check = checks[0]
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
             e.get("site") == DOOR and e.get("exception_class") == EXCEPTION and
             e.get("node") == "master0" and e.get("epoch") == check.get("epoch") and
             e.get("occurrence") == check.get("occurrence") and
             e.get("thread_id") == check.get("thread_id") and
             isinstance(e.get("door_ordinal"), int) and e["door_ordinal"] > 0 and
             e.get("seq") + 1 == check.get("seq")]
    require(len(doors) == 1, "typed SocketException door is not immediately before the exact check")
    door = doors[0]
    require(check.get("occurrence") not in (None, "", "root") and
            check.get("thread_id") is not None and
            check.get("epoch") is not None,
            "same-occurrence identity is incomplete")
    matching = [d for d in feedback.get("doors", []) if
                d.get("event_id") == door.get("id") and d.get("in_closure") is True and
                d.get("exception_class") == EXCEPTION and
                d.get("point") == {"site": DOOR, "node": "master0",
                                   "epoch": door["epoch"],
                                   "door_ordinal": door["door_ordinal"]}]
    require(len(matching) == 1, "typed same-occurrence door absent from target closure")
    if require_local_timeline:
        timeline = matching[0].get("local_timeline_evidence") or {}
        require(timeline.get("door_event_id") == door.get("id") and
                timeline.get("target_check_event_id") == check.get("id") and
                timeline.get("door_seq") + 1 == timeline.get("target_check_seq"),
                "fresh run lacks exact local timeline proof")
    return {
        "case_id": CASE, "status": "admitted", "schema_version": 1,
        "junit": "1/0/0", "target_actor": "master0",
        "door_event_id": door["id"], "door_seq": door["seq"],
        "target_event_id": check["id"], "target_seq": check["seq"],
        "epoch": check["epoch"], "occurrence": check["occurrence"],
        "thread_id": check["thread_id"], "door_ordinal": door["door_ordinal"],
        "typed_exception": EXCEPTION, "in_closure": True,
        "local_timeline_proven": require_local_timeline,
        "result_sha256": sha(summary_path), "trial_sha256": sha(trial_path),
        "trace_gzip_sha256": sha(trace_path),
    }


def promote(campaign: Path) -> dict:
    lock_path = campaign / ".campaign.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = read(campaign / "config.json")
        state_path = campaign / "checkpoint.json"
        state = read(state_path)
        if state.get("calibration_only") is False:
            return verify_promotion(campaign)
        require(config.get("case_id") == CASE and
                config.get("auto_promote_if_healthy") is True and
                config.get("explore_outside_closure") is False and
                config.get("allow_local_timeline_doors") is True and
                config.get("require_event_time_paths") is False and
                config.get("reject_coarse_roots") is True,
                "full-v2 causal admission policy changed")
        require(state.get("config_digest") == digest(config) and
                state.get("status") == "calibration_complete" and
                state.get("calibration_only") is True and
                state.get("completed_trials") == [0] and
                state.get("running") is None and
                state.get("next_trial") == 1,
                "checkpoint cannot be safely promoted")
        verdict = verify_pair(campaign, require_local_timeline=True)
        allowed = {"site": DOOR, "node": "master0",
                   "epoch": verdict["epoch"],
                   "door_ordinal": verdict["door_ordinal"]}
        queue = state.get("queue") or []
        require(queue and all(len(row.get("faults", [])) == 1 and
                              row["faults"][0].get("point") == allowed and
                              row["faults"][0].get("fault_type") == "EXCEPTION" and
                              row["faults"][0].get("exception_class") == EXCEPTION and
                              row.get("selection_reason") == "dynamic_closure"
                              for row in queue),
                "fresh mutation queue contains an unverified fault point")
        verdict["queue_entries"] = len(queue)
        gate_path = campaign / "healthy-gate.json"
        atomic_json(gate_path, verdict)
        state["calibration_only"] = False
        state["status"] = "running"
        state["updated_at"] = time.time()
        state["promoted_healthy_gate_sha256"] = sha(gate_path)
        atomic_json(state_path, state)
        return verdict


def verify_promotion(campaign: Path) -> dict:
    state = read(campaign / "checkpoint.json")
    config = read(campaign / "config.json")
    gate_path = campaign / "healthy-gate.json"
    gate = read(gate_path)
    require(state.get("config_digest") == digest(config) and
            state.get("calibration_only") is False and
            state.get("promoted_healthy_gate_sha256") == sha(gate_path) and
            gate.get("case_id") == CASE and gate.get("status") == "admitted" and
            gate.get("local_timeline_proven") is True and
            gate.get("result_sha256") and gate.get("trial_sha256") ==
            sha(campaign / "trials/r0000/result.json") and
            gate.get("trace_gzip_sha256") ==
            sha(campaign / "trials/r0000/events.jsonl.gz") and
            state.get("completed_trials", [None])[0] == 0,
            "promoted checkpoint or healthy evidence changed")
    return gate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--verify-promotion", action="store_true")
    args = parser.parse_args()
    try:
        require(not (args.promote and args.verify_promotion), "choose one gate action")
        verdict = (promote(args.campaign) if args.promote else
                   verify_promotion(args.campaign) if args.verify_promotion else
                   verify_pair(args.campaign, require_local_timeline=False))
    except (ValueError, KeyError, OSError, EOFError, gzip.BadGzipFile) as exc:
        if args.promote and args.campaign.is_dir():
            atomic_json(args.campaign / "healthy-gate-failed.json",
                        {"schema_version": 1, "case_id": CASE,
                         "status": "healthy_admission_failed", "reason": str(exc),
                         "fault_trials_started": False})
        raise SystemExit(f"HBASE-28 healthy admission failed: {exc}")
    print(json.dumps(verdict, sort_keys=True))


if __name__ == "__main__":
    main()
