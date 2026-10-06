#!/usr/bin/env python3
"""Attach block-instance identity to existing HDFS-15 target observations.

Re-evaluates saved traces and coverage, then extends the queue from their
observed I/O without replaying any completed fault trial.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from run_campaign import (CAMPAIGN, COVERAGE, LEDGER, RESULT, STATE, TARGET_SITE,
                          TRACE, atomic_json, coverage_ids, events, family_id,
                          mutate, next_target_context, now, persist, point_id,
                          relevant)

ARCHIVE = CAMPAIGN / "target-context-migration-2026-10-06"


def preserve(path: Path) -> None:
    archived = ARCHIVE / path.relative_to(CAMPAIGN.parent)
    archived.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and not archived.exists():
        shutil.copy2(path, archived)


def expected_for(sequence: list[dict], healthy: list[dict]) -> dict:
    if len(sequence) != 1:
        raise RuntimeError("migration only supports the ten existing single-fault trials")
    key = point_id(sequence[-1])
    matches = [row for row in healthy if relevant(row) and point_id(row) == key]
    if len(matches) != 1:
        raise RuntimeError(f"ambiguous healthy selector {key}: {len(matches)}")
    context = next_target_context(healthy, matches[0]["seq"])
    if context is None:
        raise RuntimeError(f"no following target for {key}")
    return context


def main() -> None:
    state = json.loads(STATE.read_text())
    healthy = events(TRACE)
    if len(state["completed"]) != 10:
        raise RuntimeError("expected ten completed single-fault trials")
    for row in state["completed"]:
        if len(row["sequence"]) != 1:
            raise RuntimeError("a multi-fault trial already completed")
        preserve(CAMPAIGN / row["trial"] / "trial-result.json")
    for path in (STATE, RESULT, LEDGER):
        preserve(path)
    for item in state["queue"] + ([state["current"]] if state["current"] else []):
        item["target_context"] = expected_for(item["sequence"], healthy)

    union_coverage = coverage_ids(COVERAGE)
    union_io = {point_id(row) for row in healthy if relevant(row)}
    union_families = {family_id(row) for row in healthy if relevant(row)}
    changed_admission = []
    for row in state["completed"]:
        row["target_context_expected"] = expected_for(row["sequence"], healthy)
        trace = events(Path(row["trace"]))
        all_after = [entry for entry in trace
                     if entry.get("event") == "TARGET_GUARD" and
                     entry.get("site") == TARGET_SITE and
                     entry["seq"] > row["last_applied_seq"] >= 0]
        context = row["target_context_expected"]
        matching = [entry for entry in all_after
                    if entry["blockId"] == context["block_id"] and
                    entry["reportedBlockId"] == context["reported_block_id"]]
        old = row["target_guard_after_last_fault"]
        row["target_guard_after_last_fault"] = bool(matching)
        if old != bool(matching):
            changed_admission.append(row["trial"])
        row["target_guard_after_last_fault_count"] = len(matching)
        row["other_block_guard_after_last_fault_count"] = (
            len(all_after) - len(matching))
        row["target_actual_guard_ordinals_after_fault"] = [
            entry["ordinal"] for entry in matching]
        row["target_outcomes_after_fault"] = [
            entry["allowed"] for entry in matching]
        false_guards = {(entry["ordinal"], entry["blockId"])
                        for entry in matching if not entry["allowed"]}
        exact = [entry for entry in trace
                 if entry.get("event") == "TARGET_EXCEPTION" and
                 entry.get("site") == TARGET_SITE and
                 entry.get("type") == "java.lang.IllegalStateException" and
                 entry.get("seq", -1) > row["last_applied_seq"] >= 0 and
                 (entry.get("ordinal"), entry.get("blockId")) in false_guards]
        row["target_exception_after_fault_count"] = len(exact)
        strict = row["strict_injection"]
        row["status"] = ("unmatched" if not strict else
                         "lost_target" if not matching else
                         "target_exception_candidate" if exact else "checked")
        row["bug_mark"] = "candidate" if strict and matching and exact else "none"
        admitted = strict and bool(matching)
        ids = coverage_ids(Path(row["coverage"]))
        fresh = ids - union_coverage if admitted else set()
        row["new_coverage_ids"] = sorted(fresh)
        row["new_coverage_count"] = len(fresh)
        observed = [entry for entry in trace if relevant(entry)]
        points = {point_id(entry) for entry in observed}
        families = {family_id(entry) for entry in observed}
        row["new_io_point_ids"] = sorted(points - union_io) if admitted else []
        row["new_io_family_ids"] = sorted(families - union_families) if admitted else []
        if admitted:
            union_coverage.update(ids)
            union_io.update(points)
            union_families.update(families)
        atomic_json(CAMPAIGN / row["trial"] / "trial-result.json", row)

    previous_queue = len(state["queue"])
    for row in state["completed"]:
        mutate(state, row)
    atomic_json(STATE, state)
    result = json.loads(RESULT.read_text())
    result["target_runtime_identity"] = (
        "BlockInfo.commitBlock:447 guard, BlockInfo blockId and reportedBlockId; "
        "source guard occurrence ordinal recorded for replay")
    result["target_context_migration"] = str(ARCHIVE.relative_to(CAMPAIGN.parent))
    atomic_json(RESULT, result)
    summary = {"migrated_at_utc": now(), "completed_trials": len(state["completed"]),
               "junit_replayed": False, "changed_admission": changed_admission,
               "queue_before": previous_queue, "queue_after": len(state["queue"]),
               "multi_fault_candidates": sum(len(item["sequence"]) > 1
                                             for item in state["queue"]),
               "current_trial_preserved": state["current"]}
    atomic_json(ARCHIVE / "migration-summary.json", summary)
    persist(state)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
