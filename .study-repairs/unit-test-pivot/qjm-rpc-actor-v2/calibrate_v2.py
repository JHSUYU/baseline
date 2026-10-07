#!/usr/bin/env python3
"""Offline identity/target/coverage gate for two original QJM V2 seeds."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_offline import HERE
from run_v2 import METHOD
from strict_receipt import RPC, SITES, actor


def events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(case: str, name: str) -> dict:
    run = HERE / "evidence" / f"HDFS-{case}" / name
    manifest = json.loads((run / "manifest.json").read_text())
    expected = "org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager#" + METHOD[case]
    if (manifest.get("test") != expected or manifest.get("returncode") != 0 or
            manifest.get("plan") is not None):
        raise ValueError(f"{case}/{name}: not passing original fault-free JUnit")
    for label, path in (("trace", run / "runtime_trace.jsonl"),
                        ("jacoco", run / "jacoco.exec")):
        if (not path.is_file() or not path.stat().st_size or
                manifest.get(label + "_sha256") != sha(path)):
            raise ValueError(f"{case}/{name}: missing/changed raw {label}")
    trace = events(run / "runtime_trace.jsonl")
    registration = {}
    roots = {}
    for event in trace:
        if event.get("event") != "NODE_PORT_REGISTER":
            continue
        port, key, root = (event.get("port"), event.get("journalNode"),
                           event.get("storageRoot"))
        if (not isinstance(port, int) or port <= 0 or actor(root) != key or
                port in registration and registration[port] != key or
                key in roots and roots[key] != root):
            raise ValueError(f"{case}/{name}: invalid listener/storage registration")
        registration[port] = key
        roots[key] = root
    if set(roots) != {f"journalnode-{i}" for i in range(3)}:
        raise ValueError(f"{case}/{name}: incomplete three-JN actor map")
    peer_by_thread = {}
    seen_io = []
    checks = []
    for event in trace:
        kind, thread = event.get("event"), event.get("threadId")
        if kind == "RPC_PEER_RESOLVED":
            if thread is None or registration.get(event.get("port")) != event.get("journalNode"):
                raise ValueError(f"{case}/{name}: unregistered RPC peer")
            peer_by_thread[thread] = (event["seq"], event["journalNode"])
        elif kind == "FAULT_POINT_OBSERVED":
            key = actor(event.get("sourceKey"))
            if key is None:
                continue
            if event.get("marker") == RPC:
                peer = peer_by_thread.get(thread)
                if not peer or peer[1] != key or peer[0] >= event["seq"]:
                    raise ValueError(f"{case}/{name}: observed RPC lacks peer binding")
            seen_io.append(event)
        elif kind == "TARGET_CHECK" and event.get("siteId") == SITES[case]:
            if (event.get("journalNode") not in roots or
                    event.get("journalId") != "test-journal" or thread is None):
                raise ValueError(f"{case}/{name}: exact target actor/journal absent")
            checks.append(event)
    if not checks or not seen_io:
        raise ValueError(f"{case}/{name}: no exact target or actor-aware I/O")
    feedback = {kind: run / f"covered_{kind}.txt" for kind in
                ("probes", "methods", "branch_counts", "lines")}
    if any(not path.is_file() or not path.stat().st_size or
           manifest.get("coverage_sha256", {}).get(kind) != sha(path)
           for kind, path in feedback.items()):
        raise ValueError(f"{case}/{name}: incomplete production JaCoCo feedback")
    families = {"\t".join(str(event[key]) for key in
                          ("marker", "siteId", "sourceKey")) for event in seen_io}
    return {"run": name, "seconds": manifest["elapsed_seconds"],
            "test": expected, "overlay_probe_sha256": manifest["overlay_probe_sha256"],
            "overlay_client_sha256": manifest["overlay_client_sha256"],
            "listener_registrations": len(registration),
            "target_actors": sorted({event["journalNode"] for event in checks}),
            "target_checks": len(checks), "io_families": sorted(families),
            "production_coverage": {kind: len(path.read_text().splitlines())
                                    for kind, path in feedback.items()}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=METHOD)
    args = parser.parse_args()
    first, second = inspect(args.case, "healthy-a"), inspect(args.case, "healthy-b")
    if (first["overlay_probe_sha256"] != second["overlay_probe_sha256"] or
            first["overlay_client_sha256"] != second["overlay_client_sha256"]):
        raise ValueError("healthy seeds used different V2 overlays")
    shared_actors = sorted(set(first["target_actors"]) & set(second["target_actors"]))
    shared_families = sorted(set(first["io_families"]) & set(second["io_families"]))
    if not shared_actors or not shared_families:
        raise ValueError("no stable target actor / I/O family across healthy seeds")
    output = HERE / "evidence" / f"HDFS-{args.case}" / "healthy-calibration.json"
    if output.exists():
        raise ValueError("immutable calibration receipt already exists")
    receipt = {"pass": True, "case": f"HDFS-{args.case}",
               "original_junit_seeds": 2, "new_effective_trials": 0,
               "legacy_trials_imported": 0, "seeds": [first, second],
               "shared_target_actors": shared_actors,
               "shared_io_families": shared_families}
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
