#!/usr/bin/env python3
"""Resumable two-pair original and actor-aware healthy JUnit calibration."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from feedback import (actor_registrations, atomic_json, checked_target_identity,
                      events, fields, io_identity, runtime_actor, target_counts)

CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"
RUN = CASE / "probe/run.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_original(name: str) -> dict:
    directory = EVIDENCE / name
    manifest = json.loads((directory / "manifest.json").read_text())
    log = (directory / "junit.log").read_text(errors="replace")
    if (manifest["exit_code"] != 0 or not manifest["original_classes"] or
            "SOLR05_V2_JUNIT_RESULT run=1 failures=0 ignored=0" not in log or
            "SOLR05_V2_JUNIT_ASSUMPTION" in log):
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
            "SOLR05_V2_JUNIT_RESULT run=1 failures=0 ignored=0" not in log or
            "SOLR05_V2_JUNIT_ASSUMPTION" in log or
            counts["SOLR-05"] == 0 or
            any(event["kind"] == "TARGET_EXCEPTION" for event in trace) or
            roles != {"node1", "node2", "node3"} or len(registrations) != 3 or
            not checked_target_identity(trace)):
        raise RuntimeError(f"Actor/replica-bound JUnit or guard proof failed: {name}")
    targets = [e for e in trace if e["kind"] == "TARGET_CHECK"]
    related = [e for e in trace if io_identity(e) is not None and
               e["parts"][1].startswith("/collections/testAddMultipleReplicas") and
               any(t["seq"] > e["seq"] and runtime_actor(t) == runtime_actor(e)
                   for t in targets)]
    if not related:
        raise RuntimeError(f"No same-replica collection-state I/O before target: {name}")
    return {"name": name, "elapsed_seconds": manifest["elapsed_seconds"],
            "target_counts": counts, "registered_client_count": len(registrations),
            "stable_jetty_roles": sorted(roles), "related_io_before_target": len(related),
            "target_replicas": sorted({fields(e)["replica"] for e in targets}),
            "trace_sha256": sha(directory / "events.tsv"),
            "log_sha256": sha(directory / "junit.log"),
            "jacoco_sha256": sha(directory / "jacoco.exec")}


def main() -> None:
    if not (CASE / "build-receipt.json").exists():
        raise RuntimeError("Build actor V2 probes before healthy calibration")
    originals = []
    actor_runs = []
    for round_number in (1, 2):
        suffix = f"{round_number:03d}"
        for name, flags in (("healthy-original-" + suffix, ["--original"]),
                            ("healthy-actor-" + suffix, ["--coverage"])):
            directory = EVIDENCE / name
            if not (directory / "manifest.json").exists():
                if directory.exists():
                    directory.rename(EVIDENCE / (name + "-interrupted-" + str(int(time.time()))))
                subprocess.run([sys.executable, str(RUN), str(directory), *flags], check=True)
            if "original" in name:
                verify_original(name)
            else:
                verify_instrumented(name)
            scratch = directory / "scratch"
            if scratch.exists():
                shutil.rmtree(scratch)
        originals.append(verify_original("healthy-original-" + suffix))
        actor_runs.append(verify_instrumented("healthy-actor-" + suffix))
        atomic_json(EVIDENCE / "healthy-summary.json", {
            "original_junit": originals, "actor_instrumented_junit": actor_runs,
            "test": "AddReplicaTest.testAddMultipleReplicas",
            "original_test_class_sha256": json.loads((CASE / "build-receipt.json").read_text())["test_class_sha256"],
            "calibration_complete": round_number == 2,
        })
    print("SOLR05_V2_HEALTHY_CALIBRATION_PASS")


if __name__ == "__main__":
    main()
