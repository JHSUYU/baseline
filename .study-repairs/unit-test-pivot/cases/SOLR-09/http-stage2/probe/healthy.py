#!/usr/bin/env python3
"""Verify the unchanged cluster JUnit and the exact CoreAdmin HTTP hook."""

import json
from pathlib import Path
import subprocess
import sys

from feedback import atomic_json, events


WORK = Path(__file__).resolve().parents[1]
EVIDENCE = WORK / "evidence"


def run(name: str, original: bool) -> dict:
    output = EVIDENCE / name
    command = [sys.executable, str(WORK / "probe/run.py"), str(output),
               "--timeout", "300", "--original" if original else "--coverage"]
    subprocess.run(command, check=False)
    return json.loads((output / "manifest.json").read_text())


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    original = run("healthy-original", True)
    if original["exit_code"] != 0:
        raise RuntimeError("Unchanged DeleteReplicaTest failed; inspect healthy-original/junit.log")
    instrumented = run("healthy-instrumented", False)
    if instrumented["exit_code"] != 0:
        raise RuntimeError("Instrumented DeleteReplicaTest failed; inspect healthy-instrumented/junit.log")
    trace = events(EVIDENCE / "healthy-instrumented/events.tsv")
    targets = [event for event in trace if event["kind"] == "TARGET_CHECK"
               and len(event["parts"]) >= 2 and event["parts"][1] == "SOLR-09"]
    http = [event for event in trace if event["kind"] == "IO_OBSERVED"
            and len(event["parts"]) >= 3
            and event["parts"][0] == "HTTP_POST"
            and "action=UNLOAD" in event["parts"][1]
            and any(target["seq"] > event["seq"] for target in targets)]
    report = {
        "case_id": "SOLR-09", "stage": "independent_http_coreadmin",
        "original_exit": original["exit_code"],
        "original_seconds": original["elapsed_seconds"],
        "instrumented_exit": instrumented["exit_code"],
        "instrumented_seconds": instrumented["elapsed_seconds"],
        "target_checks": len(targets),
        "target_guard_outcomes": [event["parts"][0] for event in targets],
        "pre_target_http_unload_count": len(http),
        "pre_target_http_unload_identities": sorted({
            event["parts"][0] + "|" + event["parts"][1] + "|" + event["parts"][2]
            for event in http}),
        "pre_target_http_unload_events": [event["parts"] for event in http],
    }
    atomic_json(EVIDENCE / "healthy-summary.json", report)
    print(json.dumps(report, sort_keys=True), flush=True)
    if not targets or not http:
        raise RuntimeError("Healthy run did not prove target and pre-target CoreAdmin UNLOAD")


if __name__ == "__main__":
    main()
