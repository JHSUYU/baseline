#!/usr/bin/env python3
"""Read-only per-check accounting from an actor-V2 storage campaign checkpoint."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("anchor", type=Path)
    parser.add_argument("case_id")
    args = parser.parse_args()
    state = json.loads((args.anchor / "campaign-state.json").read_text())
    healthy = json.loads((args.anchor / "healthy_receipt.json").read_text())
    case = args.case_id
    if case not in state["case_ids"] or case not in healthy["case_ids"]:
        parser.error("case is absent from the campaign or healthy receipt")
    if not healthy["pass"] or len(healthy["seeds"]) != 2:
        raise RuntimeError("two passing original healthy seeds are required")
    goal = state["budget"]["goal_by_case"][case]
    effective = 0
    selected = strict = applied_events = expected_throws = novel_throws = 0
    seconds = 0.0
    depths: Counter[str] = Counter()
    retained_depths: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    markers: Counter[str] = Counter()
    first_goal = None
    for index, sequence_id in enumerate(state["completion_order"], 1):
        entry = state["completed"][sequence_id]
        item, result = entry["item"], entry["result"]
        if case not in item["cases"]:
            continue
        selected += 1
        depth = str(len(item["sequence"]))
        depths[depth] += 1
        seconds += sum(attempt["elapsed_seconds"] for attempt in entry["attempts"])
        if result["exact_order_applied"]:
            strict += 1
            applied_events += len(item["sequence"])
            for fault in item["sequence"]:
                kinds[fault["faultType"]] += 1
                markers[fault["marker"]] += 1
        observed = result["by_case"][case]
        expected_throws += observed["target_exceptions_matching_healthy_signature"]
        novel_throws += observed["target_exceptions_with_novel_signature"]
        if observed["valid_for_feedback"]:
            effective += 1
            retained_depths[depth] += 1
            if effective == goal and first_goal is None:
                first_goal = {"sequence_id": sequence_id, "completed_index": index,
                              "finished_at_utc": json.loads(Path(result["manifest"]).read_text())["finished_at_utc"]}
        if first_goal is not None:
            break
    if effective != min(state["effective_by_case"][case], goal):
        raise RuntimeError("per-case effective count differs from checkpoint")
    seeds = healthy["seeds"]
    coverage = {kind: len(points) for kind, points in state["coverage"][case].items()}
    gains = {kind: sum(row["coverage_gain"][kind]
                       for row in state["effective_history"][case][:effective])
             for kind in coverage}
    output = {
        "case_id": case, "checkpoint_status": state["status"],
        "group_completed": len(state["completion_order"]),
        "goal": goal, "max_faults": state["budget"]["faults_by_case"][case],
        "selected_fault_trials": selected, "fully_applied_trials": strict,
        "applied_fault_events": applied_events, "target_after_fault": effective,
        "first_goal": first_goal,
        "junit_attempt_seconds": round(seconds, 3),
        "healthy_seconds": round(sum(seed["elapsed_seconds"] for seed in seeds), 3),
        "elapsed_seconds": round(seconds + sum(seed["elapsed_seconds"] for seed in seeds), 3),
        "healthy_junit_exit": [seed["junit_exit"] for seed in seeds],
        "healthy_target_checks": [seed["targets"][case] for seed in seeds],
        "healthy_target_throws": [seed["target_throws"][case] for seed in seeds],
        "expected_signature_throws_after_fault": expected_throws,
        "novel_signature_throws_after_fault": novel_throws,
        "coverage_total": coverage, "coverage_gain": gains,
        "io_families": len(state["io_families"][case]),
        "tested_sequence_depths": dict(sorted(depths.items())),
        "target_retaining_sequence_depths": dict(sorted(retained_depths.items())),
        "applied_fault_type_counts": dict(sorted(kinds.items())),
        "applied_io_marker_counts": dict(sorted(markers.items())),
        "instrumentation_digest_sha256": state["instrumentation_digest_sha256"],
        "healthy_receipt_sha256": state["healthy_receipt_sha256"],
    }
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
