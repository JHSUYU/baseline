#!/usr/bin/env python3
"""Verify actor binding in two unchanged-original-JUnit healthy calibrations."""

import hashlib
import json
from pathlib import Path

from feedback import atomic_json, events


WORK = Path(__file__).resolve().parents[1]
NAMES = ("healthy-instrumented", "healthy-instrumented-002")


def metadata(event: dict) -> dict[str, str]:
    return dict(part.split("=", 1) for part in event["parts"] if "=" in part)


def main() -> None:
    original = []
    for name in ("healthy-original", "healthy-original-002"):
        manifest = json.loads((WORK / "evidence" / name / "manifest.json").read_text())
        if manifest["exit_code"] != 0:
            raise RuntimeError(f"Original JUnit failed: {name}")
        original.append({"name": name, "exit_code": 0,
                         "elapsed_seconds": manifest["elapsed_seconds"]})
    calibrated = []
    for name in NAMES:
        directory = WORK / "evidence" / name
        manifest = json.loads((directory / "manifest.json").read_text())
        trace = events(directory / "events.tsv")
        registered = [e for e in trace if e["kind"] == "ACTOR_REGISTERED"]
        bound = [e for e in trace if e["kind"] == "TARGET_ACTORS_BOUND"]
        target = [e for e in trace if e["kind"] == "TARGET_CHECK"]
        if manifest["exit_code"] != 0 or len(registered) != 4 or len(bound) != 1 or len(target) != 1:
            raise RuntimeError(f"Actor registration/target proof failed: {name}")
        client = metadata(bound[0])["overseer_client_id"]
        if metadata(target[0])["overseer_client_id"] != client:
            raise RuntimeError(f"Selected check used a different reader: {name}")
        if client not in {metadata(event)["client_id"] for event in registered}:
            raise RuntimeError(f"Selected reader has no node registration: {name}")
        io = [e for e in trace if e["kind"] == "IO_OBSERVED" and
              e["seq"] > bound[0]["seq"] and e["seq"] < target[0]["seq"]]
        http = [e for e in io if e["parts"][0] == "HTTP_POST" and
                "actor=target_replica_http" in e["parts"]]
        callbacks = [e for e in io if "actor=target_overseer" in e["parts"] and
                     f"client_id={client}" in e["parts"] and
                     any(part.startswith("thread=zkCallback") for part in e["parts"])]
        if len(http) != 1 or not callbacks:
            raise RuntimeError(f"HTTP or async callback role proof failed: {name}")
        calibrated.append({
            "name": name, "exit_code": 0, "elapsed_seconds": manifest["elapsed_seconds"],
            "registered_node_clients": len(registered), "bound_overseer_client_id": client,
            "selected_guard_overseer_client_id": metadata(target[0])["overseer_client_id"],
            "target_outcome": target[0]["parts"][0],
            "target_core": target[0]["parts"][5],
            "pre_target_http_exact_actor": len(http),
            "pre_target_overseer_async_callbacks_same_client": len(callbacks),
            "trace_sha256": hashlib.sha256((directory / "events.tsv").read_bytes()).hexdigest(),
        })
    atomic_json(WORK / "evidence/healthy-actor-audit.json", {
        "original_junit": original, "actor_instrumented_junit": calibrated,
        "cross_run_selector": "target role + exact caller + operation + resource + hit ordinal",
        "raw_node_name": "audit only; ephemeral Jetty port prevents stable cross-run identity",
    })


if __name__ == "__main__":
    main()
