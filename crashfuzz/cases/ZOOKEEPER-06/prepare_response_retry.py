#!/usr/bin/env python3
"""Retry only the two response selectors lost to nondeterminism."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "run-r3/runtime/runtime_trace_response_points.jsonl"
DESTINATION = HERE / "run-r3/runtime/runtime_trace_response_retry.jsonl"
kept = set()
with SOURCE.open() as original, DESTINATION.open("w") as filtered:
    for line in original:
        event = json.loads(line)
        if event.get("event") == "FAULT_POINT_OBSERVED":
            if not (event.get("sourceKey") == "zk-peer-2#epoch1"
                    and event.get("hitOrdinal") == 6
                    and event.get("marker", "").startswith("FAULT:ZK_QUORUM:RESPONSE")):
                continue
            kept.add(event["marker"])
        filtered.write(line)
if kept != {"FAULT:ZK_QUORUM:RESPONSE", "FAULT:ZK_QUORUM:RESPONSE:EOFException"}:
    raise SystemExit(f"retry selectors missing: {kept}")
config = json.loads((HERE / "case-response.json").read_text())
config["seed"]["trace"] = str(DESTINATION)
config["budget"] = {"max_trials": 2, "max_faults": 1, "max_seconds": 180}
(HERE / "case-response-retry.json").write_text(json.dumps(config, indent=2) + "\n")
