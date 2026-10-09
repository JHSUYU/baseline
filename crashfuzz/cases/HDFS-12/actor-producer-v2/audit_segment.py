#!/usr/bin/env python3
"""Read-only audit of a fixed prefix of the HDFS-12 actor V2 checkpoint."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


COVERAGE = ("probes", "methods", "branch_counts")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def io_families(trace: list[dict]) -> set[str]:
    return {"|".join(str(row[key]) for key in
                     ("marker", "siteId", "faultActor", "resource"))
            for row in trace if row.get("event") == "FAULT_POINT_OBSERVED"}


def covered(path: Path, kind: str) -> set[str]:
    return set((path / ("covered_" + kind + ".txt")).read_text().splitlines())


def audit(output: Path, count: int) -> dict:
    output = output.resolve()
    state = json.loads((output / "campaign-state.json").read_text())
    history = state["scheduler_history"]
    if not 1 <= count <= state["attempted_trials"]:
        raise ValueError("requested count is outside the completed checkpoint")
    ids = [row["sequence_id"] for row in history[:count]]
    if len(ids) != count or len(set(ids)) != count:
        raise RuntimeError("scheduler history is not a unique completed prefix")
    if any(identity not in state["completed"] for identity in ids):
        raise RuntimeError("a selected sequence has not completed")
    healthy = {kind: covered(output / "healthy-a", kind) for kind in COVERAGE}
    seen_coverage = {kind: set(values) for kind, values in healthy.items()}
    healthy_io = io_families(rows(output / "healthy-a" / "runtime_trace.jsonl"))
    healthy_io |= io_families(rows(output / "healthy-b" / "runtime_trace.jsonl"))
    seen_io = set(healthy_io)
    runs = []
    for identity in ids:
        run = output / "runs" / identity
        manifest_path = run / "manifest.json"
        result_path = run / "v2_result.json"
        trace_path = run / "runtime_trace.jsonl"
        plan_path = output / "plans" / (identity + ".tsv")
        manifest = json.loads(manifest_path.read_text())
        result = json.loads(result_path.read_text())
        trace = rows(trace_path)
        plan = plan_path.read_text().splitlines()
        fault_families = [line.split("\t")[0] for line in plan]
        matched = [row for row in trace if row.get("event") == "FAULT_MATCHED"]
        applied = [row for row in trace if row.get("event") == "FAULT_APPLIED"]
        if (manifest["returncode"] != result["junit_exit"] or
                len(plan) != result["requested_faults"] or
                len(matched) != result["matched_faults"] or
                len(applied) != result["applied_faults"]):
            raise RuntimeError(f"raw JUnit/fault count mismatch in {identity}")
        if any(first["seq"] >= second["seq"]
               for first, second in zip(matched, applied)):
            raise RuntimeError(f"fault event order mismatch in {identity}")
        new_coverage = {}
        for kind in COVERAGE:
            values = covered(run, kind)
            new_coverage[kind] = len(values - seen_coverage[kind])
            if result["valid_for_feedback"]:
                seen_coverage[kind] |= values
        if new_coverage != result["new_coverage"]:
            raise RuntimeError(f"raw JaCoCo feedback mismatch in {identity}")
        new_io = io_families(trace) - seen_io if result["valid_for_feedback"] else set()
        if new_io != set(result["new_io_families"]):
            raise RuntimeError(f"raw I/O feedback mismatch in {identity}")
        seen_io |= new_io
        runs.append({
            "id": identity, "started_at_utc": manifest["started_at_utc"],
            "finished_at_utc": manifest["finished_at_utc"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "peak_junit_rss_kib": manifest["peak_junit_rss_kib"],
            "junit_exit": manifest["returncode"],
            "fault_depth": len(plan), "fault_families": fault_families,
            "matched_faults": len(matched), "applied_faults": len(applied),
            "exact_order_applied": result["exact_order_applied"],
            "classification": result["classification"],
            "valid_for_feedback": result["valid_for_feedback"],
            "postfault_target_count": result["postfault_target_count"],
            "postfault_target_exception_count": result["postfault_target_exception_count"],
            "postfault_same_actor": result["postfault_target_same_actor_resource"],
            "target_exception_candidate": result["target_exception_candidate"],
            "new_coverage": new_coverage, "new_io_families": sorted(new_io),
            "manifest_sha256": sha(manifest_path),
            "trace_sha256": sha(trace_path),
            "jacoco_exec_sha256": sha(run / "jacoco.exec"),
            "v2_result_sha256": sha(result_path),
            "plan_sha256": sha(plan_path),
        })
    return {
        "schema": "hdfs12-actor-v2-segment-audit-1", "case_id": "HDFS-12",
        "authoritative_host": "node1", "audited_prefix_trials": count,
        "checkpoint_attempted_at_audit": state["attempted_trials"],
        "fully_applied_trials": sum(row["exact_order_applied"] for row in runs),
        "effective_trials": sum(row["valid_for_feedback"] for row in runs),
        "strict_target_retaining_trials": sum(
            row["exact_order_applied"] and
            row["postfault_target_count"] > 0 and row["postfault_same_actor"]
            for row in runs),
        "target_exception_candidates": sum(row["target_exception_candidate"] for row in runs),
        "total_elapsed_seconds": round(sum(row["elapsed_seconds"] for row in runs), 3),
        "cumulative_coverage_gain_against_healthy_a": {
            kind: len(seen_coverage[kind] - healthy[kind]) for kind in COVERAGE},
        "healthy_io_family_union_size": len(healthy_io),
        "new_io_families_against_both_healthy_seeds": sorted(seen_io - healthy_io),
        "fault_depth_counts": dict(Counter(row["fault_depth"] for row in runs)),
        "fault_family_step_counts": dict(Counter(
            family for row in runs for family in row["fault_families"])),
        "classification_counts": dict(Counter(row["classification"] for row in runs)),
        "max_junit_rss_kib": max(row["peak_junit_rss_kib"] for row in runs),
        "checkpoint_path": str(output / "campaign-state.json"),
        "tmux_session": "hdfs12_actor_v2_budget", "runs": runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.output, args.count), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
