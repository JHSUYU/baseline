#!/usr/bin/env python3
"""Audit two fresh actor-aware original embedded-cluster JUnit traces."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fuzz_v2 import (AGENT, CORE, GUARD, HERE, SEEDS, TARGET, guard_events,
                     junit_gate, load_events, point, relevant, seed_candidates,
                     validate_actor_trace)


def audit_one(directory: Path) -> tuple[dict, list[dict]]:
    metadata = json.loads((directory / "run.json").read_text())
    gate = junit_gate((directory / "console.log").read_text())
    agent_sha = hashlib.sha256(AGENT.read_bytes()).hexdigest()
    if metadata["exit_code"] != 0 or gate != (1, 0, 0):
        raise RuntimeError(f"original JUnit failed: {directory}")
    if metadata["agent_sha256"] != agent_sha:
        raise RuntimeError(f"healthy run used different V2 agent: {directory}")
    events = load_events(directory)
    actor = validate_actor_trace(events)
    guards = guard_events(events)
    if len(guards) != 1:
        raise RuntimeError(f"healthy trace lacks exact single target guard: {directory}")
    target = guards[0]
    if (target["marker"] != GUARD or target["sourceKey"] != TARGET
            or target["resource"] != CORE or target["actorKey"] != "JETTY/node1"):
        raise RuntimeError("healthy target child/core/actor mismatch")
    file_events = [event for event in events if event["event"] == "IO_OBSERVED"
                   and event["marker"] == "FAULT:FILE:core.properties:read"]
    return {
        "directory": str(directory),
        "trace_sha256": hashlib.sha256((directory / "events.jsonl").read_bytes()).hexdigest(),
        "elapsed_seconds": metadata["elapsed_seconds"],
        "junit_gate": gate,
        "actor_audit": actor,
        "target": {field: target[field] for field in
                   ("marker", "sourceKey", "actorKey", "physicalNode", "resource")},
        "file_reads": len(file_events),
        "actor_bound_target_file_reads": sum(relevant(point(event)) for event in file_events),
        "unbound_file_reads_excluded": sum(not relevant(point(event)) for event in file_events),
    }, events


def main() -> None:
    audits, events = zip(*(audit_one(directory) for directory in SEEDS))
    points = seed_candidates(events[0], events[1])
    if not points or any(not relevant(item) for item in points):
        raise RuntimeError("no stable actor-aware I/O selector before target")
    file_points = [item for item in points
                   if item["marker"] == "FAULT:FILE:core.properties:read"]
    receipt = {
        "method": "unchanged CollectionReloadTest#testReloadedLeaderStateAfterZkSessionLoss in two fresh JVMs",
        "agent_sha256": hashlib.sha256(AGENT.read_bytes()).hexdigest(),
        "healthy_runs": audits,
        "stable_bound_selectors": len(points),
        "stable_file_selectors": len(file_points),
        "all_selected_keys_include_actor": all(item["actorKey"] == "JETTY/node1"
                                                for item in points),
        "selector_examples": points[:12],
    }
    output = HERE / "calibration-receipt.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: receipt[key] for key in
                      ("stable_bound_selectors", "stable_file_selectors",
                       "all_selected_keys_include_actor")}, sort_keys=True))


if __name__ == "__main__":
    main()
