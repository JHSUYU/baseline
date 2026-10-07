#!/usr/bin/env python3
"""Reclassify completed V3 pilot traces under the target-only oracle, once."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path

from campaign import CASE, coverage, family, mutate
from identity_gate import atomic, evaluate, rows

EXPECTED_OLD_GATE = "c4c5c015a3d764cf96b2c4591d7ff8acdd2024cc57290d9d5a8fa637c342bc09"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    home = CASE / "campaign"
    checkpoint = home / "checkpoint.json"
    migration = home / "oracle-migration-target-only"
    if migration.exists():
        raise RuntimeError("migration already exists")
    with (home / "controller.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(checkpoint.read_text())
        if state["status"] != "pilot_boundary" or state["in_flight"]:
            raise RuntimeError("pilot must be at a complete boundary")
        completed = sorted(state["completed"].items(),
                           key=lambda pair: pair[1]["attempt"])
        if len(completed) != state["attempted"]:
            raise RuntimeError("completed attempts disagree with checkpoint")
        migration.mkdir()
        before_sha = sha(checkpoint)
        (migration / "checkpoint-before.json").write_bytes(checkpoint.read_bytes())
        (migration / "trial-ledger-before.jsonl").write_bytes(
            (home / "trial-ledger.jsonl").read_bytes())
        raw_manifest_shas = {}
        baseline_coverage = coverage(CASE / "healthy/a") | coverage(CASE / "healthy/b")
        baseline_io = {family(row) for seed in (CASE / "healthy/a", CASE / "healthy/b")
                       for row in rows(seed) if row.get("event") == "IO_OBSERVED"}
        union_coverage, union_io = set(baseline_coverage), set(baseline_io)
        new_completed, recent_gain, ledger = {}, [], []
        old_effective = state["effective"]
        for identifier, entry in completed:
            number = entry["attempt"]
            run = home / f"trial-{number:04d}"
            plan = home / "plans" / (identifier + ".tsv")
            recorded = json.loads((run / "v3-result.json").read_text())
            (migration / f"trial-{number:04d}-result-before.json").write_bytes(
                (run / "v3-result.json").read_bytes())
            raw_manifest_shas[str(number)] = {
                "manifest": sha(run / "manifest.json"),
                "trace": sha(run / "trace/runtime_trace.jsonl"),
                "plan": sha(plan)}
            verdict = evaluate(run, plan, CASE / "healthy-receipt.json")
            trace = rows(run)
            new_coverage = coverage(run) - union_coverage
            new_families = {family(row) for row in trace
                            if row.get("event") == "IO_OBSERVED"} - union_io
            if not verdict["valid_for_feedback"]:
                new_coverage.clear()
                new_families.clear()
            if verdict["valid_for_feedback"]:
                union_coverage |= new_coverage
                union_io |= new_families
                recent_gain.append(bool(new_coverage or new_families))
                mutate(state, recorded["sequence"], trace, verdict,
                       len(new_coverage) + len(new_families))
            verdict.update({key: recorded[key] for key in
                            ("sequence_id", "sequence", "selection_reason",
                             "completed_at_utc")})
            verdict["new_coverage_ids"] = sorted(new_coverage)
            verdict["new_io_families"] = sorted(new_families)
            atomic(run / "v3-result.json", verdict)
            new_completed[identifier] = {
                "attempt": number,
                "exact_order_applied": verdict["exact_order_applied"],
                "valid_for_feedback": verdict["valid_for_feedback"],
                "last_family": family(recorded["sequence"][-1]),
                "new_coverage": len(new_coverage),
                "new_io_families": len(new_families),
                "trial": str(run)}
            ledger.append({"attempt": number, "sequence_id": identifier,
                           "elapsed_seconds": verdict["elapsed_seconds"],
                           "junit_exit": verdict["junit_exit"],
                           "exact_order_applied": verdict["exact_order_applied"],
                           "valid_for_feedback": verdict["valid_for_feedback"],
                           "workload_failure": verdict["workload_failure"],
                           "injected_exception_in_junit_log":
                           verdict["injected_exception_in_junit_log"],
                           "environment_failure_in_junit_log":
                           verdict["environment_failure_in_junit_log"],
                           "postfault_target_count": verdict["postfault_target_count"],
                           "target_exception_candidate":
                           verdict["target_exception_candidate"],
                           "new_coverage_count": len(new_coverage),
                           "new_io_family_count": len(new_families)})
        state["completed"] = new_completed
        state["effective"] = sum(entry["valid_for_feedback"]
                                 for entry in new_completed.values())
        state["recent_effective_gain"] = recent_gain
        state["coverage_ids"] = sorted(union_coverage)
        state["io_families"] = sorted(union_io)
        state["status"] = "pilot_boundary"
        state["controller_sha256"] = sha(CASE / "campaign.py")
        state["gate_sha256"] = sha(CASE / "identity_gate.py")
        atomic(checkpoint, state)
        ledger_temp = home / ("trial-ledger.jsonl." + str(os.getpid()) + ".tmp")
        ledger_temp.write_text("".join(json.dumps(row, sort_keys=True) + "\n"
                                       for row in ledger))
        os.replace(ledger_temp, home / "trial-ledger.jsonl")
        receipt = {"schema": "hdfs16-v3-target-only-oracle-migration-1",
                   "reason": "selected target after exact fault is the validity gate; "
                             "injected workload failure is separate",
                   "raw_junit_reruns": 0, "old_gate_sha256": EXPECTED_OLD_GATE,
                   "new_gate_sha256": sha(CASE / "identity_gate.py"),
                   "checkpoint_before_sha256": before_sha,
                   "checkpoint_after_sha256": sha(checkpoint),
                   "attempts_unchanged": len(completed),
                   "effective_before": old_effective,
                   "effective_after": state["effective"],
                   "raw_artifact_shas": raw_manifest_shas}
        atomic(migration / "receipt.json", receipt)
        print(json.dumps({key: receipt[key] for key in
                          ("attempts_unchanged", "effective_before",
                           "effective_after", "raw_junit_reruns")},
                         sort_keys=True))


if __name__ == "__main__":
    main()
