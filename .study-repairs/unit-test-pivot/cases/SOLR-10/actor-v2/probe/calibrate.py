#!/usr/bin/env python3
"""When cluster slots are free, run two original/actor-aware healthy JUnit pairs."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from feedback import (CASES, actor_registrations, atomic_json,
                      checked_target_identity, events, fields, target_counts)


CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"
RUN = CASE / "probe/run.py"
SUMMARY = EVIDENCE / "healthy-summary-v4.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_original(name: str) -> dict:
    directory = EVIDENCE / name
    manifest = json.loads((directory / "manifest.json").read_text())
    log = (directory / "junit.log").read_text(errors="replace")
    if (manifest["exit_code"] != 0 or not manifest["original_classes"] or
            "SOLR103940_JUNIT_RESULT run=1 failures=0 ignored=0" not in log or
            "SOLR103940_JUNIT_ASSUMPTION" in log):
        raise RuntimeError(f"Original JUnit failed or skipped: {name}")
    return {"name": name, "elapsed_seconds": manifest["elapsed_seconds"],
            "log_sha256": sha(directory / "junit.log")}


def verify_instrumented(name: str) -> dict:
    directory = EVIDENCE / name
    manifest = json.loads((directory / "manifest.json").read_text())
    trace = events(directory / "events.tsv")
    log = (directory / "junit.log").read_text(errors="replace")
    counts = target_counts(trace)
    registrations = actor_registrations(trace)
    roles = {item["role"] for item in registrations.values()}
    if (manifest["exit_code"] != 0 or manifest["original_classes"] or
            "SOLR103940_JUNIT_RESULT run=1 failures=0 ignored=0" not in log or
            "SOLR103940_JUNIT_ASSUMPTION" in log or
            any(counts[site] == 0 for site in CASES) or
            any(event["kind"] == "TARGET_EXCEPTION" for event in trace) or
            roles != {"node1", "node2", "node3", "node4"} or
            not checked_target_identity(trace)):
        raise RuntimeError(f"Actor-bound JUnit/guard proof failed: {name}")
    alias_io = [e for e in trace if e["kind"] == "IO_OBSERVED" and
                e["parts"][1] == "/aliases.json" and
                fields(e).get("actor", "").startswith("jetty:node")]
    if not alias_io:
        raise RuntimeError(f"No registered alias I/O receiver in {name}")
    return {"name": name, "elapsed_seconds": manifest["elapsed_seconds"],
            "target_counts": counts, "registered_client_count": len(registrations),
            "stable_jetty_roles": sorted(roles), "alias_io_registered": len(alias_io),
            "trace_sha256": sha(directory / "events.tsv"),
            "log_sha256": sha(directory / "junit.log"),
            "jacoco_sha256": sha(directory / "jacoco.exec")}


def main() -> None:
    if not (CASE / "build-receipt.json").exists():
        raise RuntimeError("Build the actor V2 probes before healthy calibration")
    originals = []
    instrumented = []
    for round_number in (1, 2):
        suffix = f"{round_number:03d}"
        original_name = "healthy-original-v4-" + suffix
        actor_name = "healthy-actor-v4-" + suffix
        for name, flags in ((original_name, ["--original"]),
                            (actor_name, ["--coverage"])):
            directory = EVIDENCE / name
            manifest = directory / "manifest.json"
            if not manifest.exists():
                if directory.exists():
                    interrupted = EVIDENCE / (name + "-interrupted-" + str(int(time.time())))
                    directory.rename(interrupted)
                subprocess.run([sys.executable, str(RUN), str(directory), *flags],
                               check=True)
            if name == original_name:
                verify_original(name)
            else:
                verify_instrumented(name)
            scratch = directory / "scratch"
            if scratch.exists():
                shutil.rmtree(scratch)
        originals.append(verify_original(original_name))
        instrumented.append(verify_instrumented(actor_name))
        atomic_json(SUMMARY, {
            "original_junit": originals, "actor_instrumented_junit": instrumented,
            "test": "TimeRoutedAliasUpdateProcessorTest.test",
            "build_receipt_sha256": sha(CASE / "build-receipt.json"),
            "source_commit": json.loads((CASE / "build-receipt.json").read_text())["source_commit"],
            "actor_probe_class_sha256": json.loads((CASE / "build-receipt.json").read_text())["actor_probe_class_sha256"],
            "original_test_class_sha256": json.loads((CASE / "build-receipt.json").read_text())["test_class_sha256"],
            "calibration_complete": round_number == 2,
        })
    print("SOLR103940_V2_HEALTHY_CALIBRATION_PASS")


if __name__ == "__main__":
    main()
