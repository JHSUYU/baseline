#!/usr/bin/env python3
"""Summarize one immutable Solr healthy calibration without promoting it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def actor(value: object) -> tuple[str, str] | None:
    try:
        address = json.loads(value) if isinstance(value, str) else value
        if not isinstance(address, list) or len(address) != 3:
            return None
        node, epoch = address[:2]
        if not isinstance(node, str) or node in {"", "unknown", "null", "None"}:
            return None
        return node, str(epoch)
    except (TypeError, ValueError):
        return None


def summarize(campaign: Path) -> dict:
    terminal_path = campaign / "result.json"
    trial_path = campaign / "trials/r0000/result.json"
    terminal, trial = read(terminal_path), read(trial_path)
    pilot = read(campaign / "trials/r0000/pilot-result.json")
    junit_path = campaign / "trials/r0000/junit-receipt.json"
    junit = read(junit_path) if junit_path.is_file() else None
    feedback = trial.get("feedback", {})
    catalog = trial.get("site_catalog_validation", {})
    binding = terminal.get("runtime_attestation", {})

    events = trial.get("events_evidence", {})
    gzip_path = events.get("gzip_path")
    gzip_ok = bool(gzip_path and (campaign / "trials/r0000" / gzip_path).is_file()
                   and sha256(campaign / "trials/r0000" / gzip_path)
                   == events.get("gzip_sha256"))
    edges = [edge for edge in feedback.get("closure_edges", [])
             if edge.get("certainty") == "observed"
             and actor(edge.get("source")) and actor(edge.get("target"))]
    cross_actor = [edge for edge in edges if actor(edge["source"]) != actor(edge["target"])]
    rpc = [edge for edge in cross_actor if edge.get("kind") == "rpc"]
    doors = [door for door in feedback.get("doors", [])
             if door.get("in_closure") is True
             and isinstance(door.get("point"), dict)
             and door["point"].get("node") not in {None, "", "unknown", "null", "None"}]
    target_nodes = sorted({entry.get("node") for entry in feedback.get("target_closures", [])
                           if entry.get("node") not in {None, "", "unknown", "null", "None"}})
    junit_passed = bool(junit and junit.get("status") == "passed")
    verified = (terminal.get("status") == "calibration_complete"
                and terminal.get("healthy_seed_valid") is True
                and trial.get("return_code") == 0
                and junit_passed and pilot.get("status") == "healthy_calibrated"
                and feedback.get("target_reached") is True
                and feedback.get("target_threw") is False
                and feedback.get("target_identity_complete") is True
                and binding.get("valid") is True and catalog.get("valid") is True
                and gzip_ok and bool(target_nodes))
    return {
        "case_id": terminal.get("case_id"),
        "exact_target": {key: terminal.get("target", {}).get(key)
                         for key in ("source_path", "source_line", "function",
                                     "check_sites", "throw_site", "exception_class")},
        "terminal_status": terminal.get("status"),
        "terminal_sha256": sha256(terminal_path),
        "healthy_trial_sha256": sha256(trial_path),
        "healthy_trace_gzip_sha256": events.get("gzip_sha256"),
        "healthy_trace_sha_verified": gzip_ok,
        "junit": junit,
        "pilot_status": pilot.get("status"),
        "pilot_test": pilot.get("test"),
        "pilot_target_check_count": pilot.get("target_check_count"),
        "pilot_target_throw_count": pilot.get("target_throw_count"),
        "exact_catalog_valid": catalog.get("valid"),
        "target_class_sha256": catalog.get("observed_target_class_sha256"),
        "target_loader_ids": catalog.get("target_class_loader_ids", []),
        "named_target_nodes": target_nodes,
        "target_identity_complete": feedback.get("target_identity_complete"),
        "observed_named_closure_edges": len(edges),
        "observed_named_cross_actor_edges": len(cross_actor),
        "observed_named_rpc_edges": len(rpc),
        "named_in_closure_doors": len(doors),
        "named_in_closure_door_sites": sorted({door.get("site") for door in doors}),
        "healthy_seed_verified": verified,
        "quality_ready_for_review": verified and bool(cross_actor) and bool(doors),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = summarize(args.campaign)
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
