#!/usr/bin/env python3
"""Schedule late, untried quorum response doors from the healthy trace."""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "run-r3/runtime/runtime_trace.jsonl"
DESTINATION = HERE / "run-r3/runtime/runtime_trace_response_points.jsonl"
CONFIG = HERE / "case-response.json"
SELECTED = {
    ("zk-peer-1#epoch1", 7),
    ("zk-peer-1#epoch1", 8),
    ("zk-peer-2#epoch1", 3),
    ("zk-peer-2#epoch1", 4),
    ("zk-peer-2#epoch1", 5),
    ("zk-peer-2#epoch1", 6),
}


def main() -> None:
    retained = []
    with SOURCE.open() as original, DESTINATION.open("w") as filtered:
        for line in original:
            event = json.loads(line)
            if event.get("event") == "FAULT_POINT_OBSERVED":
                marker = event.get("marker", "")
                if (not marker.startswith("FAULT:ZK_QUORUM:RESPONSE") or
                        (event.get("sourceKey"), event.get("hitOrdinal")) not in SELECTED):
                    continue
                retained.append((marker, event.get("sourceKey"), event.get("hitOrdinal")))
            filtered.write(line)
    if len(retained) != 12 or len(set(retained)) != 12:
        raise SystemExit(f"expected 12 distinct response doors, got {retained}")
    config = json.loads((HERE / "case-r3.json").read_text())
    config["target"].pop("occurrence", None)
    config["seed"]["trace"] = str(DESTINATION)
    config["trial"]["aggregate_command"] = [
        "python3", str(HERE / "aggregate_r3_dynamic.py"),
        "{trace_dir}", "{aggregate_dir}"]
    config["budget"] = {"max_trials": 12, "max_faults": 1, "max_seconds": 800}
    CONFIG.write_text(json.dumps(config, indent=2) + "\n")
    print(json.dumps(retained, indent=2))


if __name__ == "__main__":
    main()
