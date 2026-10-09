#!/usr/bin/env python3
"""Freeze the first 80 effective HDFS-29/30 outcomes as a case-local receipt."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import audit_raw
import campaign

HERE = Path(__file__).resolve().parent
PREFIX = 203
CASES = ("HDFS-29", "HDFS-30")
OUT = HERE / "audits" / "hdfs29-30-peer80-terminal.json"
AUDIT_COPY = HERE / "audits" / "hdfs29-30-peer80-raw-audit.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def durable(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".tmp")
    with pending.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def main() -> int:
    if OUT.exists() or AUDIT_COPY.exists():
        raise RuntimeError("peer80 terminal receipt already exists")
    if audit_raw.main() != 0:
        raise RuntimeError("independent raw audit failed")
    audit_bytes = (HERE / "raw-audit.json").read_bytes()
    audit = json.loads(audit_bytes)
    state = json.loads((HERE / "checkpoint.json").read_text())
    if (audit["completed_attempts"] < PREFIX or audit["errors"]
            or len(state["completed"]) < PREFIX
            or state.get("test") !=
            "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization"):
        raise RuntimeError("peer80 raw audit or original JUnit provenance mismatch")
    prefix = state["completed"][:PREFIX]
    healthy_seconds = sum(row["seconds"] for row in state["healthy"])
    fault_seconds = sum(row["elapsed_seconds"] for row in prefix)
    exact = sum(bool(row["exact_order_applied"]) for row in prefix)
    results = {}
    for case in CASES:
        valid = [(index + 1, row) for index, row in enumerate(prefix)
                 if row["exact_order_applied"] and row["post_fault_target_checks"][case]]
        ext = state["extensions"].get(case)
        if (len(valid) != 80 or state["goals"][case] != 80 or ext is None
                or ext.get("novelty") is not False
                or ext.get("decision_at_trial") != PREFIX
                or ext.get("last_eight_run_ids") != [row["id"] for _, row in valid[-8:]]):
            raise RuntimeError(case + " did not terminate at base effective budget")
        if any((row["coverage_gain"][case]["methods"] or
                row["coverage_gain"][case]["branch_counts"] or
                row["new_io_families"][case]) for _, row in valid[-8:]):
            raise RuntimeError(case + " has extension-triggering novelty in last eight")
        if any(row["target_exceptions_after_fault"][case] for row in prefix):
            raise RuntimeError(case + " has target exception candidate in peer80 prefix")
        cv = {metric: set(state["healthy_coverage"][metric]) for metric in campaign.COVERAGE}
        for _, trial in valid:
            directory = Path(trial["run"])
            for metric in campaign.COVERAGE:
                cv[metric] |= campaign.covered(directory, metric)
        results[case] = {
            "effective": len(valid), "goal": 80,
            "first_effective_attempt": valid[0][0], "80th_effective_attempt": valid[-1][0],
            "last_eight_attempts": [index for index, _ in valid[-8:]],
            "last_eight_novelty": False, "extension_decision": ext,
            "target_exception_candidates": 0,
            "production_coverage_gain": {metric: len(cv[metric] -
                                                     set(state["healthy_coverage"][metric]))
                                         for metric in campaign.COVERAGE}}
    receipt = {"schema": 1, "test": state["test"],
               "source_sha256": {name: sha((HERE / name).read_bytes()) for name in
                                 ("campaign.py", "successor.py", "focus28_v2.py")},
               "first_80_prefix_attempts": PREFIX,
               "prefix_completed_sha256": sha(encoded(prefix)),
               "prefix_exact_full_sequence": exact,
               "prefix_fault_junit_seconds": round(fault_seconds, 3),
               "healthy_junit_seconds": round(healthy_seconds, 3),
               "audit_completed_attempts": audit["completed_attempts"],
               "audit_sha256": sha(audit_bytes),
               "audit_errors": audit["errors"],
               "checkpoint_path": str(HERE / "checkpoint.json"),
               "cases": results,
               "scope": "first 80 effective visits per case; later shared HDFS-28 trials are separate follow-on exploration"}
    durable(AUDIT_COPY, audit_bytes)
    durable(OUT, encoded(receipt))
    print(json.dumps({"receipt": str(OUT), "audit_attempts": audit["completed_attempts"],
                      "prefix": PREFIX, "exact": exact,
                      "fault_seconds": receipt["prefix_fault_junit_seconds"],
                      "cases": {case: results[case]["effective"] for case in CASES}},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
