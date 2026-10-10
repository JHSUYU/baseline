#!/usr/bin/env python3
"""GO-gated node1 campaign with a fresh strict healthy proof before faults."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import config_v3
import graph_overlay

HERE = Path(__file__).resolve().parent
GO = HERE / "admission-strict-pilot-node1.json"
CONFIG = HERE / "config-generated-node1.json"


def strict_healthy_proof(trial: Path) -> dict:
    """Independently require a native observed graph path on fresh r0000."""
    events = tuple(graph_overlay.unique_writer.load_trace(trial))
    rows = graph_overlay.unique_writer.witnesses(list(events))
    graph = graph_overlay.SourceBackedSolr38Graph(events, reject_coarse_roots=True)
    by_id = {row["id"]: row for row in events if isinstance(row.get("id"), str)}
    strict = []
    for row in rows:
        path = graph.event_path(by_id[row["door"]], by_id[row["target"]],
                                require_edge=True)
        if path and any(edge.kind == "state" and
                        edge.evidence.startswith("solr38_source_backed") for edge in path):
            strict.append(row)
    typed = {(row["node"], row["door"]) for row in strict}
    state_edges = [edge for edge in graph.edges
                   if edge.kind == "state" and edge.evidence.startswith("solr38_source_backed")]
    return {"valid": bool(strict and typed and state_edges),
            "strict_door_target_paths": len(strict),
            "typed_door_actors": sorted({node for node, _ in typed}),
            "source_backed_state_edges": len(state_edges),
            "candidate_state_edges_not_promoted": sum(
                edge.kind == "state" for edge in graph.candidate_edges),
            "graph_overlay_sha256": config_v3.sha(HERE / "graph_overlay.py"),
            "trace_sha256": config_v3.sha(trial / "events.jsonl.gz")}


def install_health_gate(campaign) -> None:
    original = campaign._apply_result

    def gated_apply(state: dict, config: dict, result: dict, item: dict | None) -> None:
        if result["trial_id"] > 0:
            feedback = result["feedback"]
            feedback["solr38_strict_fault_acceptance"] = bool(
                feedback.get("all_faults_effective") and
                feedback.get("target_check_reached") and
                feedback.get("target_reached"))
        original(state, config, result, item)
        if result["trial_id"] != 0:
            return
        if result["feedback"].get("status") != "observed" or not (
                state.get("runtime_attestation") or {}).get("valid"):
            proof = {"valid": False, "reason": "healthy JUnit/target/runtime attestation failed"}
        else:
            try:
                proof = strict_healthy_proof(Path(state["out"]) / "trials/r0000")
            except (OSError, ValueError, KeyError) as exc:
                proof = {"valid": False, "reason": str(exc)}
        state["solr38_strict_healthy_proof"] = proof
        if not proof["valid"]:
            state["status"] = "healthy_strict_path_missing"
            state["queue"].clear()

    campaign._apply_result = gated_apply


def check_go(path: Path, meta: dict) -> None:
    if path.resolve() != GO:
        raise ValueError("case-local dispatch GO path required")
    grant = json.loads(path.read_text(encoding="utf-8"))
    for key in ("case_id", "host", "mode", "source_manifest_sha256",
                "runner_sha256", "intended_output"):
        if grant.get(key) != meta[key]:
            raise ValueError(f"dispatch GO differs: {key}")
    if (grant.get("go") is not True or grant.get("scope") != "one_bounded_strict_fault_pilot"
            or grant.get("max_fault_trials") != 4):
        raise ValueError("dispatch GO did not authorize bounded strict pilot")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    import preflight
    meta = preflight.main()
    if args.preflight_only:
        print(json.dumps(meta, sort_keys=True))
        return 0
    if args.admission_receipt is None:
        parser.error("node1 dispatch GO receipt required")
    check_go(args.admission_receipt, meta)
    if socket.gethostname().split(".", 1)[0] != "node1":
        raise ValueError("node1 host required")
    if config_v3.OUT.exists() and not (config_v3.OUT / "checkpoint.json").is_file():
        raise ValueError("output exists without resumable checkpoint")
    if (config_v3.OUT / "checkpoint.json").is_file():
        checkpoint = json.loads((config_v3.OUT / "checkpoint.json").read_text(encoding="utf-8"))
        if (0 in checkpoint.get("completed_trials", []) and
                not (checkpoint.get("solr38_strict_healthy_proof") or {}).get("valid")):
            raise ValueError("resumed campaign lacks its strict healthy proof")
    lock_dir = Path("/tmp/mallory-lanes")
    lock_dir.mkdir(parents=True, exist_ok=True)
    handles = []
    try:
        for name in ("solr-node1-lane.lock", "solr-source-graphchecker-8.11.4.lock"):
            handle = (lock_dir / name).open("a+")
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handles.append(handle)
        processes = subprocess.check_output(
            ["ps", "-u", str(os.getuid()), "-o", "comm="], text=True).splitlines()
        if any(name.strip() in {"java", "mvn"} for name in processes):
            raise ValueError("competing user JVM or Maven process")
        if shutil.disk_usage(config_v3.ROOT).free < 7_650_410_496:
            raise ValueError("insufficient free disk")
        available_kib = next(int(row.split()[1]) for row in
                             Path("/proc/meminfo").read_text().splitlines()
                             if row.startswith("MemAvailable:"))
        if available_kib < 8_388_608:
            raise ValueError("insufficient available memory")
        config = config_v3.generate()
        sys.path.insert(0, str(config_v3.RELEASE))
        from Mallory.core import campaign
        campaign.validate_config(config)
        graph_overlay.install()
        install_health_gate(campaign)
        serialized = json.dumps(config, sort_keys=True, indent=2) + "\n"
        if CONFIG.exists() and CONFIG.read_text(encoding="utf-8") != serialized:
            raise ValueError("generated config changed after prior launch")
        CONFIG.write_text(serialized, encoding="utf-8")
        state = campaign.run(CONFIG, config_v3.OUT, calibration_only=False)
        print(json.dumps({"case_id": "SOLR-38", "status": state["status"],
                          "completed_trials": state["completed_trials"],
                          "strict_healthy_proof": state.get("solr38_strict_healthy_proof")},
                         sort_keys=True))
    finally:
        for handle in reversed(handles):
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
