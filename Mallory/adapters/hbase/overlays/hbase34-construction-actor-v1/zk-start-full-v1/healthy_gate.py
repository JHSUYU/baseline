#!/usr/bin/env python3
"""Admit HBASE-34 faults only after a fresh, named, typed healthy r0000."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

CASE = "HBASE-34"
PREFIX = "org.apache.hadoop.hbase.security.token."
START = PREFIX + "ZKSecretWatcher#start()V"
CHECK = (PREFIX + "AuthenticationTokenSecretManager#retrievePassword"
         "(Lorg/apache/hadoop/hbase/security/token/AuthenticationTokenIdentifier;)[B"
         "@159:branch:7")
THROW = CHECK.replace("@159:branch:7", "@160:throw:1")
WRITE = (PREFIX + "AuthenticationTokenSecretManager#addKey"
         "(Lorg/apache/hadoop/hbase/security/token/AuthenticationKey;)V@189:map:1")
READ = CHECK.replace("@159:branch:7", "@137:map:1")
DOORS = {START + "@61:door:1", START + "@63:door:2"}
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    require(path.is_file(), f"missing evidence: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"expected object: {path}")
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


def verify_pair(campaign: Path) -> dict:
    summary_path = campaign / "result.json"
    trial_path = campaign / "trials/r0000/result.json"
    trace_path = campaign / "trials/r0000/events.jsonl.gz"
    summary, trial = read(summary_path), read(trial_path)
    feedback = trial["feedback"]
    require(summary.get("case_id") == trial.get("case_id") == CASE and
            summary.get("status") == "calibration_complete" and
            summary.get("fault_trials_completed") == 0 and
            summary.get("healthy_seed_valid") is True,
            "fresh healthy calibration did not complete cleanly")
    require(summary.get("target_binding") == {"nodes": ["rs0"]} and
            (summary.get("runtime_attestation") or {}).get("valid") is True and
            (summary.get("runtime_attestation") or {}).get("bound_nodes") == ["rs0"] and
            (summary.get("runtime_attestation") or {}).get("target_identity_gap_count") == 0,
            "exact rs0 target identity not attested")
    junit = trial.get("junit_validation") or {}
    require(junit.get("status") == "passed" and junit.get("tests") == 1 and
            junit.get("failures") == junit.get("errors") == junit.get("skipped") == 0,
            "unchanged cluster JUnit did not pass 1/0/0")
    require((trial.get("site_catalog_validation") or {}).get("valid") is True and
            feedback.get("status") == "observed" and
            feedback.get("target_reached") is True and
            feedback.get("target_threw") is False and
            feedback.get("target_region_present") is True and
            feedback.get("target_identity_complete") is True and
            {x.get("node") for x in feedback.get("target_instances", [])} == {"rs0"},
            "healthy exact target or site catalog invalid")
    evidence = trial.get("events_evidence") or {}
    require(sha(trace_path) == evidence.get("gzip_sha256"), "compressed trace SHA mismatch")
    raw = gzip.decompress(trace_path.read_bytes())
    require(hashlib.sha256(raw).hexdigest() == evidence.get("raw_sha256") and
            len(raw) == evidence.get("raw_bytes"), "raw trace SHA or length mismatch")
    events = [json.loads(line) for line in raw.splitlines()]
    checks = [e for e in events if e.get("type") == "TARGET_CHECK" and
              e.get("site") == CHECK and e.get("node") == "rs0"]
    require(len(checks) == 1 and not any(e.get("type") == "TARGET_THROW" and
                                        e.get("site") == THROW for e in events),
            "expected one nonthrowing exact rs0 @159 check")
    check = checks[0]
    reads = [e for e in events if e.get("type") == "STATE_READ" and
             e.get("site") == READ and e.get("node") == "rs0" and
             e.get("occurrence") == check.get("occurrence") and
             e.get("epoch") == check.get("epoch") and
             e.get("seq") + 1 == check.get("seq")]
    require(len(reads) == 1, "exact rs0 allKeys read missing immediately before check")
    state_read = reads[0]
    writes = [e for e in events if e.get("type") == "STATE_WRITE" and
              e.get("site") == WRITE and e.get("node") == "rs0" and
              e.get("seq") < state_read.get("seq") and
              all(e.get(field) == state_read.get(field) and e.get(field) is not None
                  for field in ("object", "key", "version"))]
    require(len(writes) == 1 and
            state_read.get("version_confidence") == writes[0].get("version_confidence") == "sampled",
            "same object/key/version sampled state witness absent or ambiguous")
    state_write = writes[0]
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
             e.get("site") in DOORS and e.get("node") == "rs0" and
             e.get("exception_class") == EXCEPTION and
             e.get("fault_type") == "EXCEPTION" and
             e.get("epoch") == state_write.get("epoch") and
             e.get("occurrence") == state_write.get("occurrence") and
             e.get("thread_id") == state_write.get("thread_id") and
             isinstance(e.get("door_ordinal"), int) and e["door_ordinal"] > 0 and
             e.get("seq") < state_write.get("seq")]
    require({e["site"] for e in doors} == DOORS and len(doors) == 2,
            "typed rs0 watcher doors missing before same-occurrence key write")
    closure = feedback.get("closure_edges") or []
    require(any(edge.get("kind") == "state" and edge.get("certainty") == "candidate" and
                edge.get("evidence") == "sampled_version:object,key,version" and
                edge.get("producer_event") == state_write.get("id") and
                edge.get("consumer_event") == state_read.get("id") for edge in closure),
            "sampled-version candidate state edge absent from target closure")
    expected_points = []
    for door in doors:
        point = {"site": door["site"], "node": "rs0",
                 "epoch": door["epoch"], "door_ordinal": door["door_ordinal"]}
        matches = [row for row in feedback.get("doors", []) if
                   row.get("event_id") == door.get("id") and
                   row.get("point") == point and row.get("in_closure") is True and
                   row.get("exception_class") == EXCEPTION]
        require(len(matches) == 1, "typed rs0 door not in dynamic target closure")
        expected_points.append(point)
    require(check.get("seq") > state_read.get("seq") > state_write.get("seq") and
            all(door.get("seq") < state_write.get("seq") for door in doors),
            "healthy event order changed")
    return {"schema_version": 1, "case_id": CASE, "status": "admitted",
            "junit": "1/0/0", "target_actor": "rs0",
            "target_event_id": check["id"], "target_seq": check["seq"],
            "state_write_event_id": state_write["id"],
            "state_read_event_id": state_read["id"],
            "state_edge_certainty": "candidate", "state_version_confidence": "sampled",
            "state_object": state_read["object"], "state_key": state_read["key"],
            "state_version": state_read["version"],
            "typed_exception": EXCEPTION, "allowed_points": expected_points,
            "result_sha256": sha(summary_path), "trial_sha256": sha(trial_path),
            "trace_gzip_sha256": sha(trace_path)}


def promote(campaign: Path) -> dict:
    with (campaign / ".campaign.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = read(campaign / "config.json")
        state_path = campaign / "checkpoint.json"
        state = read(state_path)
        require(config.get("case_id") == CASE and
                config.get("auto_promote_if_healthy") is True and
                config.get("explore_outside_closure") is False and
                config.get("require_event_time_paths") is False and
                config.get("fault_types") == ["EXCEPTION"],
                "full causal admission policy changed")
        require(state.get("config_digest") == digest(config) and
                state.get("status") == "calibration_complete" and
                state.get("calibration_only") is True and
                state.get("completed_trials") == [0] and
                state.get("running") is None and state.get("next_trial") == 1,
                "checkpoint cannot be safely promoted")
        verdict = verify_pair(campaign)
        allowed = verdict["allowed_points"]
        queue = state.get("queue") or []
        require(queue and len(queue) <= len(allowed) and
                {json.dumps(row["faults"][0]["point"], sort_keys=True) for row in queue} ==
                {json.dumps(point, sort_keys=True) for point in allowed} and
                all(len(row.get("faults", [])) == 1 and
                    row["faults"][0].get("fault_type") == "EXCEPTION" and
                    row["faults"][0].get("exception_class") == EXCEPTION and
                    row.get("selection_reason") == "dynamic_closure" for row in queue),
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
            gate.get("state_edge_certainty") == "candidate" and
            gate.get("trial_sha256") == sha(campaign / "trials/r0000/result.json") and
            gate.get("trace_gzip_sha256") == sha(campaign / "trials/r0000/events.jsonl.gz") and
            state.get("completed_trials", [None])[0] == 0,
            "promoted checkpoint or fresh healthy evidence changed")
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
                   verify_pair(args.campaign))
    except (ValueError, KeyError, OSError, EOFError, gzip.BadGzipFile) as exc:
        if args.promote and args.campaign.is_dir():
            atomic_json(args.campaign / "healthy-gate-failed.json",
                        {"schema_version": 1, "case_id": CASE,
                         "status": "healthy_admission_failed", "reason": str(exc),
                         "fault_trials_started": False})
        raise SystemExit(f"HBASE-34 healthy admission failed: {exc}")
    print(json.dumps(verdict, sort_keys=True))


if __name__ == "__main__":
    main()
