#!/usr/bin/env python3
"""Audit V2 actor binding and exact selectors in two original healthy runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from fuzz_v2 import (HERE, SEEDS, GUARDS, audit_event_identities, guard_events,
                     junit_gate, load_events, point, relevant, seed_candidates,
                     target_actor_map)
from run_healthy import source_provenance


def audit_one(directory: Path) -> tuple[dict, list[dict]]:
    metadata = json.loads((directory / "run.json").read_text())
    gate = junit_gate((directory / "console.log").read_text())
    if metadata["exit_code"] != 0 or gate != (1, 0, 0):
        raise RuntimeError(f"healthy original JUnit failed: {directory}")
    agent_sha = hashlib.sha256(
        (HERE / "solrsubshard-actor-v2-agent.jar").read_bytes()).hexdigest()
    if metadata["agent_sha256"] != agent_sha:
        raise RuntimeError(f"healthy run used different agent: {directory}")
    if metadata['original_source_revision'] != source_provenance()['revision']:
        raise RuntimeError(f'healthy run used different original source: {directory}')
    if metadata['classpath_contains_graphchecker']:
        raise RuntimeError(f'healthy run included GraphChecker: {directory}')
    events = load_events(directory)
    identity_audit = audit_event_identities(events)
    bindings: dict[int, tuple[str, str]] = {}
    for event in events:
        if event["event"] != "CLIENT_BIND":
            continue
        match = re.search(r"clientIdentity=(\d+)", event["detail"])
        if match is None:
            raise RuntimeError("binding lacks raw client identity")
        client_id = int(match.group(1))
        entry = (event["actorKey"], event["physicalNode"])
        if client_id in bindings and bindings[client_id] != entry:
            raise RuntimeError("same SolrZkClient identity maps to different actor")
        bindings[client_id] = entry
    if not bindings:
        raise RuntimeError("no ZkController-to-SolrZkClient actor bindings")
    bound_io = 0
    unbound_io = 0
    for event in events:
        if event["event"] != "IO_OBSERVED":
            continue
        match = re.search(r"clientIdentity=(\d+)", event["detail"])
        if match is None:
            raise RuntimeError("I/O lacks raw SolrZkClient object identity")
        expected = bindings.get(int(match.group(1)))
        if event["actorKey"].startswith("JETTY/"):
            if expected != (event["actorKey"], event["physicalNode"]):
                raise RuntimeError("bound I/O actor contradicts registration")
            if event.get("sessionEligible"):
                if (event.get("zkClientIdentity") != int(match.group(1)) or
                        event.get("zkHandleIdentity", 0) <= 0 or
                        event.get("zkSessionId", 0) <= 0 or
                        event.get("sessionGeneration", 0) <= 0 or
                        event.get("zkState") != "CONNECTED"):
                    raise RuntimeError("eligible I/O lacks physical ZooKeeper session")
                bound_io += 1
            else:
                unbound_io += 1
        else:
            if event["applied"]:
                raise RuntimeError("unbound I/O was faulted")
            unbound_io += 1
    targets = target_actor_map(events)
    for case_id in GUARDS:
        if not guard_events(events, case_id):
            raise RuntimeError(f"missing healthy {case_id} guard")
    return {
        "directory": str(directory),
        "trace_sha256": hashlib.sha256((directory / "events.jsonl").read_bytes()).hexdigest(),
        "elapsed_seconds": metadata["elapsed_seconds"],
        "junit_gate": gate,
        "bindings": len(bindings),
        "bound_io": bound_io,
        "unbound_io_excluded": unbound_io,
        "raw_actor_session_audit": identity_audit,
        "target_actor_map": targets,
    }, events


def main() -> None:
    source_receipt = HERE / 'source-provenance.json'
    if not source_receipt.is_file() or json.loads(source_receipt.read_text()) != source_provenance():
        raise RuntimeError('original Solr source/JAR provenance changed')
    audits, events = zip(*(audit_one(directory) for directory in SEEDS))
    if audits[0]["target_actor_map"] != audits[1]["target_actor_map"]:
        raise RuntimeError("healthy target-child actor map unstable")
    points = seed_candidates(events[0], events[1])
    if not points or any(not relevant(item) for item in points):
        raise RuntimeError("no stable bound I/O selector before target")
    receipt = {
        "method": "unchanged ShardSplitTest#test, two independent clean JVMs",
        "source_provenance_sha256": hashlib.sha256(source_receipt.read_bytes()).hexdigest(),
        "agent_sha256": hashlib.sha256(
            (HERE / "solrsubshard-actor-v2-agent.jar").read_bytes()).hexdigest(),
        "healthy_runs": audits,
        "common_bound_selectors": len(points),
        "common_actor_keys": sorted({point["actorKey"] for point in points}),
        "target_actor_map": audits[0]["target_actor_map"],
        "all_selected_keys_include_actor": all("actorKey" in point for point in points),
        "selector_examples": points[:12],
    }
    output = HERE / "calibration-receipt.json"
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: receipt[key] for key in
                      ("common_bound_selectors", "common_actor_keys", "target_actor_map")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
