#!/usr/bin/env python3
"""Calibrate the unchanged cluster JUnit before any fault injection."""

import json
from pathlib import Path
import subprocess
import sys

import campaign
from feedback import atomic_json, events, io_identity


WORK = Path(__file__).resolve().parents[1]
EVIDENCE = WORK / "evidence"


def run(name: str, original: bool) -> dict:
    output = EVIDENCE / name
    command = [sys.executable, str(WORK / "probe/run.py"), str(output),
               "--timeout", "300"]
    command.append("--original" if original else "--coverage")
    subprocess.run(command, check=False)
    return json.loads((output / "manifest.json").read_text())


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    original = run("healthy-original", True)
    if original["exit_code"] != 0:
        raise RuntimeError("Unmodified original JUnit failed; inspect healthy-original/junit.log")
    instrumented = run("healthy-instrumented", False)
    if instrumented["exit_code"] != 0:
        raise RuntimeError("Instrumented original JUnit failed; inspect healthy-instrumented/junit.log")
    trace = events(EVIDENCE / "healthy-instrumented/events.tsv")
    targets = campaign.target_counts(trace)
    relevant = [io_identity(event) for event in trace
                if (identity := io_identity(event)) and campaign.relevant(identity)]
    report = {"case_id": "SOLR-09", "original_exit": original["exit_code"],
              "original_seconds": original["elapsed_seconds"],
              "instrumented_exit": instrumented["exit_code"],
              "instrumented_seconds": instrumented["elapsed_seconds"],
              "target_checks": targets, "relevant_io_observations": len(relevant),
              "relevant_io_identities": len(set(relevant))}
    atomic_json(EVIDENCE / "healthy-summary.json", report)
    print(json.dumps(report, sort_keys=True), flush=True)
    if targets["SOLR-09"] == 0:
        raise RuntimeError("Original test did not reach selected DeleteReplicaCmd branch")
    if not relevant:
        raise RuntimeError("No observed I/O in the selected fault scope")


if __name__ == "__main__":
    main()
