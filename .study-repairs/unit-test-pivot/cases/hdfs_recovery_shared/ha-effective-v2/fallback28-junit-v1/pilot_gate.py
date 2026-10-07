#!/usr/bin/env python3
"""Run one bounded alternate-JUnit pilot with the shared JVM start gate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
HA = HERE.parent
sys.path.insert(0, str(HA))
import campaign  # noqa: E402

TEST = ("org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover"
        "#testLeaseRecoveryAfterFailover")
GATE_WAIT_SECONDS = 20


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", type=int, choices=(1, 2), required=True)
    args = parser.parse_args()
    ledger = json.loads((HERE / "pilot-plans.json").read_text())
    if (ledger.get("test") != TEST or ledger.get("separate_denominator") is not True
            or ledger.get("healthy_validation_sha256") != sha(HERE / "healthy-validation.json")):
        raise RuntimeError("pilot source/healthy provenance mismatch")
    plan = ledger["plans"][args.pilot - 1]
    if plan["pilot"] != args.pilot or plan["id"] != campaign.identity(plan["sequence"]):
        raise RuntimeError("pilot ID mismatch")
    directory = HERE / ("pilot-%02d" % args.pilot)
    plan_file = directory / "fault-plan.tsv"
    if plan["plan_sha256"] != sha(plan_file):
        raise RuntimeError("pilot plan changed")
    manifest_file = directory / "manifest.json"
    if manifest_file.is_file():
        manifest = json.loads(manifest_file.read_text())
        if manifest.get("test") != TEST or not (directory / "runtime_trace.jsonl").is_file():
            raise RuntimeError("existing pilot raw does not match selected JUnit")
        print("pilot already completed; reuse raw", flush=True)
    else:
        if (directory / "driver.log").exists():
            raise RuntimeError("partial pilot needs manual review; no automatic rerun")
        campaign.MIN_FREE_BYTES = 10 * 1024**3
        while not campaign.launch(directory, ["--instrument", "--plan", str(plan_file),
                                              "--test-method", "testLeaseRecoveryAfterFailover",
                                              "--output", str(directory), "--timeout", "180"]):
            print("waiting for shared Java/disk gate", flush=True)
            time.sleep(GATE_WAIT_SECONDS)
    manifest = json.loads(manifest_file.read_text())
    if manifest.get("test") != TEST:
        raise RuntimeError("wrong original JUnit ran")
    print(json.dumps({"pilot": args.pilot, "junit_exit": manifest["returncode"],
                      "seconds": manifest["elapsed_seconds"],
                      "manifest_sha256": sha(manifest_file),
                      "trace_sha256": sha(directory / "runtime_trace.jsonl"),
                      "shared_start_lock": str(campaign.START_LOCK)}, sort_keys=True),
          flush=True)


if __name__ == "__main__":
    main()
