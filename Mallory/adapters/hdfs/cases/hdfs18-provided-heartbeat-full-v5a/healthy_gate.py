#!/usr/bin/env python3
"""Promote only a fresh HDFS-18 seed with an exact DataNode-to-NameNode path."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import time
from pathlib import Path

CASE = "HDFS-18"
DN = "hdfs-cluster-1/dn0"
NN = "hdfs-cluster-1/nn0"
DOOR = ("org.apache.hadoop.hdfs.server.datanode.BPServiceActor#sendHeartBeat"
        "(Z)Lorg/apache/hadoop/hdfs/server/protocol/HeartbeatResponse;@563:door:1")
REGION = ("org.apache.hadoop.hdfs.server.blockmanagement.DatanodeDescriptor#"
          "injectStorage(Lorg/apache/hadoop/hdfs/server/blockmanagement/"
          "DatanodeStorageInfo;)V")
CHECKS = {REGION + "@537:branch:5", REGION + "@537:branch:6"}
EXCEPTION = "java.io.IOException"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


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
    with tmp.open("w") as out:
        json.dump(value, out, sort_keys=True, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def exact_chain(trial: dict, events: list[dict]) -> dict:
    feedback = trial["feedback"]
    require(feedback.get("status") == "observed" and
            feedback.get("target_reached") is True and
            feedback.get("target_threw") is False and
            feedback.get("target_identity_complete") is True and
            feedback.get("target_region_present") is True and
            feedback.get("trace_truncated") is False,
            "healthy exact target or trace is invalid")
    require({x.get("node") for x in feedback.get("target_instances", [])} == {NN},
            "healthy target is not exclusively on nn0")
    edges = feedback.get("closure_edges", [])
    by_id = {event.get("id"): event for event in events}
    require(len(by_id) == len(events), "trace has duplicate event IDs")
    candidates = []
    for door in events:
        if not (door.get("type") == "DOOR_OBSERVED" and
                door.get("site") == DOOR and door.get("node") == DN and
                door.get("exception_class") == EXCEPTION and
                door.get("epoch") == 0 and
                isinstance(door.get("door_ordinal"), int) and
                door["door_ordinal"] > 0 and door.get("id")):
            continue
        point = {"site": DOOR, "node": DN, "epoch": 0,
                 "door_ordinal": door["door_ordinal"]}
        if not any(row.get("event_id") == door["id"] and
                   row.get("point") == point and row.get("in_closure") is True and
                   row.get("exception_class") == EXCEPTION
                   for row in feedback.get("doors", [])):
            continue
        sends = [event for event in events if
                 event.get("type") == "SEND" and event.get("port") == "request" and
                 event.get("transport") == "hadoop-ipc" and
                 event.get("site") == "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest" and
                 event.get("node") == DN and event.get("epoch") == 0 and
                 event.get("thread_id") == door.get("thread_id") and
                 event.get("occurrence") == door.get("occurrence") and
                 event.get("seq", -1) > door["seq"] and event.get("correlation")]
        if not sends:
            continue
        send = min(sends, key=lambda row: row["seq"])
        # One typed call is paired with its first concrete request on this
        # receiver/thread. Never join a later retry to an earlier door.
        if any(event.get("type") == "DOOR_OBSERVED" and
               event.get("thread_id") == door.get("thread_id") and
               door["seq"] < event.get("seq", -1) < send["seq"] for event in events):
            continue
        for edge in edges:
            if not (edge.get("kind") == "rpc" and
                    edge.get("certainty") == "observed" and
                    edge.get("producer_event") == send.get("id")):
                continue
            recv = by_id.get(edge.get("consumer_event"))
            if not (recv and recv.get("type") == "RECV" and
                    recv.get("port") == "request" and
                    recv.get("transport") == "hadoop-ipc" and
                    recv.get("node") == NN and recv.get("epoch") == 0 and
                    recv.get("correlation") == send["correlation"] and
                    recv.get("seq", -1) > send["seq"]):
                continue
            for parent in edges:
                if not (parent.get("kind") == "region_parent" and
                        parent.get("certainty") == "observed" and
                        parent.get("producer_event") == recv["id"]):
                    continue
                region = by_id.get(parent.get("consumer_event"))
                if not (region and region.get("type") == "REGION_ENTER" and
                        region.get("site") == REGION and
                        region.get("node") == NN and region.get("epoch") == 0 and
                        region.get("parent_id") == recv["correlation"] and
                        region.get("seq", -1) > recv["seq"] and
                        region.get("occurrence") and region.get("thread_id")):
                    continue
                checks = [event for event in events if
                          event.get("type") == "TARGET_CHECK" and
                          event.get("site") in CHECKS and
                          event.get("node") == NN and event.get("epoch") == 0 and
                          event.get("thread_id") == region["thread_id"] and
                          event.get("occurrence") == region["occurrence"] and
                          event.get("seq", -1) > region["seq"]]
                if not CHECKS.issubset({check["site"] for check in checks}):
                    continue
                if not any(x.get("node") == NN and
                           x.get("occurrence") == region["occurrence"]
                           for x in feedback.get("target_instances", [])):
                    continue
                candidates.append((door, send, recv, region, checks))
    require(bool(candidates), "no exact named typed door→RPC→region→target path")
    door, send, recv, region, checks = min(candidates,
                                           key=lambda chain: chain[0]["seq"])
    check = min(checks, key=lambda event: event["seq"])
    identity = [DN, door["epoch"], door["occurrence"],
                send["correlation"], NN, region["occurrence"]]
    return {"door_event_id": door["id"], "door_seq": door["seq"],
            "door_ordinal": door["door_ordinal"],
            "door_occurrence": door["occurrence"],
            "send_event_id": send["id"], "send_seq": send["seq"],
            "rpc_token": send["correlation"],
            "recv_event_id": recv["id"], "recv_seq": recv["seq"],
            "region_event_id": region["id"], "region_seq": region["seq"],
            "target_occurrence": region["occurrence"],
            "target_event_id": check["id"], "target_seq": check["seq"],
            "node_occurrence_token_sha256": hashlib.sha256(
                json.dumps(identity, separators=(",", ":")).encode()).hexdigest(),
            "point": {"site": DOOR, "node": DN, "epoch": 0,
                      "door_ordinal": door["door_ordinal"]}}


def verify_pair(campaign: Path) -> dict:
    summary_path = campaign / "result.json"
    trial_path = campaign / "trials/r0000/result.json"
    trace_path = campaign / "trials/r0000/events.jsonl.gz"
    summary, trial = read(summary_path), read(trial_path)
    require(summary.get("case_id") == trial.get("case_id") == CASE and
            summary.get("status") == "calibration_complete" and
            summary.get("fault_trials_completed") == 0 and
            summary.get("healthy_seed_valid") is True and
            summary.get("target_binding") == {"nodes": [NN]},
            "fresh healthy phase did not end with named nn0 target")
    attestation = summary.get("runtime_attestation") or {}
    require(attestation.get("valid") is True and
            attestation.get("bound_nodes") == [NN] and
            attestation.get("exact_site_catalog_valid") is True and
            attestation.get("target_identity_gap_count") == 0,
            "fresh healthy runtime attestation is invalid")
    junit = trial.get("junit_validation") or {}
    require(trial.get("return_code") == 0 and not trial.get("timed_out") and
            junit.get("status") == "passed" and junit.get("tests") == 1 and
            junit.get("failures") == junit.get("errors") == junit.get("skipped") == 0,
            "fresh cluster JUnit did not pass 1/0/0")
    require(trial.get("site_catalog_validation", {}).get("valid") is True and
            trial.get("site_catalog_validation", {}).get("class_hash_match") is True,
            "fresh exact target class/site catalog mismatch")
    evidence = trial.get("events_evidence") or {}
    require(sha(trace_path) == evidence.get("gzip_sha256"),
            "compressed healthy trace SHA mismatch")
    raw = gzip.decompress(trace_path.read_bytes())
    require(hashlib.sha256(raw).hexdigest() == evidence.get("raw_sha256") and
            len(raw) == evidence.get("raw_bytes"),
            "raw healthy trace SHA or size mismatch")
    events = [json.loads(line) for line in raw.splitlines()]
    chain = exact_chain(trial, events)
    return {"schema_version": 1, "case_id": CASE, "status": "admitted",
            "junit": "1/0/0", "typed_exception": EXCEPTION,
            "source_actor": DN, "target_actor": NN, **chain,
            "result_sha256": sha(summary_path), "trial_sha256": sha(trial_path),
            "trace_gzip_sha256": sha(trace_path)}


def promote(campaign: Path) -> dict:
    with (campaign / ".campaign.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = read(campaign / "config.json")
        state_path = campaign / "checkpoint.json"
        state = read(state_path)
        if state.get("calibration_only") is False:
            return verify_promotion(campaign)
        require(config.get("case_id") == CASE and
                config.get("auto_promote_if_healthy") is True and
                config.get("agent_properties", {}).get("auto.io.doors") is False and
                config.get("explore_outside_closure") is False and
                config.get("allow_local_timeline_doors") is False and
                config.get("require_event_time_paths") is True and
                config.get("reject_coarse_roots") is True and
                config.get("fault_types") == ["EXCEPTION"] and
                config.get("budget", {}).get("trials") == 80 and
                config.get("budget", {}).get("seconds") == 3600 and
                config.get("budget", {}).get("max_faults_per_trial") == 3,
                "full-v5a fault and causal policy changed")
        require(state.get("config_digest") == digest(config) and
                state.get("status") == "calibration_complete" and
                state.get("completed_trials") == [0] and
                state.get("running") is None and state.get("next_trial") == 1,
                "fresh controller checkpoint cannot be safely promoted")
        verdict = verify_pair(campaign)
        queue = state.get("queue") or []
        require(queue and all(len(row.get("faults", [])) == 1 and
                              row["faults"][0].get("point") == verdict["point"] and
                              row["faults"][0].get("fault_type") == "EXCEPTION" and
                              row["faults"][0].get("exception_class") == EXCEPTION and
                              row.get("selection_reason") == "dynamic_closure"
                              for row in queue),
                "fresh mutation queue contains an unverified fault point")
        verdict["queue_entries"] = len(queue)
        gate_path = campaign / "healthy-gate.json"
        if gate_path.exists():
            # The previous promotion may have stopped after publishing the
            # gate but before publishing the checkpoint. Recheck the fresh
            # evidence and queue, then reuse the exact existing artifact.
            # A changed or partial gate must never be silently replaced.
            require(read(gate_path) == verdict,
                    "existing healthy gate differs from fresh evidence or queue")
        else:
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
            state.get("completed_trials", [None])[0] == 0 and
            gate.get("case_id") == CASE and gate.get("status") == "admitted" and
            gate.get("trial_sha256") ==
            sha(campaign / "trials/r0000/result.json") and
            gate.get("trace_gzip_sha256") ==
            sha(campaign / "trials/r0000/events.jsonl.gz"),
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
                   verify_pair(args.campaign))
    except (ValueError, KeyError, OSError, EOFError, gzip.BadGzipFile) as exc:
        if args.promote and args.campaign.is_dir():
            atomic_json(args.campaign / "healthy-gate-failed.json",
                        {"schema_version": 1, "case_id": CASE,
                         "status": "healthy_admission_failed", "reason": str(exc),
                         "fault_trials_started": False})
        raise SystemExit(f"HDFS-18 fresh healthy gate failed: {exc}")
    print(json.dumps(verdict, sort_keys=True))


if __name__ == "__main__":
    main()
