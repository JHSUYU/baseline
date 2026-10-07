#!/usr/bin/env python3
"""Recompute HDFS-43 I/O feedback after canonicalizing thread object IDs.

Run only while the case's remote campaign is stopped at an atomic checkpoint.
The original checkpoint/result are preserved as *.pre-stable-family.json.
No selector, fault trial, or production coverage is changed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from campaign import BASE, GROUPS, atomic_json, events, families, update_results


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def novelty_last8(state: dict, case_id: str) -> bool:
    return any(
        item[case_id]["new_io_families"]
        or any(item[case_id]["coverage_gain"].values())
        for identity in state["completion_order"][-8:]
        for item in (state["completed"][identity],)
    )


def main() -> None:
    case_id = GROUPS["truncate43"][0]
    anchor = BASE / case_id / "independent/evidence"
    state_path = anchor / "campaign-state.json"
    result_path = BASE / case_id / "result.json"
    before_state = anchor / "campaign-state.pre-stable-family.json"
    before_result = anchor / "result.pre-stable-family.json"
    if not before_state.is_file() or not before_result.is_file():
        raise SystemExit("Auditable pre-normalization copies are required")
    if digest(before_state) == digest(state_path) and digest(before_result) == digest(result_path):
        pass
    elif (anchor / "stable-io-reconciliation.json").is_file():
        raise SystemExit("I/O feedback has already been reconciled")
    else:
        raise SystemExit("Checkpoint changed after its pre-normalization copy")

    state = json.loads(state_path.read_text())
    old_result = json.loads(result_path.read_text())
    old_order = list(state["completion_order"])
    old_queue = list(state["queue"])
    old_current = state.get("current")
    old_families = list(state["io_families"][case_id])
    old_novelty = novelty_last8(state, case_id)
    healthy = anchor / "healthy/runtime_trace.jsonl"
    if not healthy.is_file():
        raise SystemExit("Healthy raw trace missing")
    seen = families(events(healthy))
    changes = []
    for identity in old_order:
        row = state["completed"][identity][case_id]
        old = row["new_io_families"]
        new = 0
        if row["valid_for_feedback"]:
            trace_path = Path(row["trace"])
            if not trace_path.is_file():
                raise SystemExit("Raw trial trace missing: " + str(trace_path))
            observed = families(events(trace_path))
            new = len(observed - seen)
            seen.update(observed)
        row["new_io_families"] = new
        if old != new:
            changes.append({"trial_id": identity, "old_new_families": old,
                            "stable_new_families": new})
    state["io_families"][case_id] = sorted(seen)
    if state["completion_order"] != old_order or state["queue"] != old_queue or state.get("current") != old_current:
        raise SystemExit("A trial or queued selector changed during reconciliation")
    atomic_json(state_path, state)
    update_results(state, GROUPS["truncate43"], state_path)
    updated = json.loads(result_path.read_text())
    if (updated["fault_trials"] != old_result["fault_trials"]
            or updated["strict_injections"] != old_result["strict_injections"]
            or updated["target_after_fault"] != old_result["target_after_fault"]
            or updated["coverage_gain"] != old_result["coverage_gain"]):
        raise SystemExit("A non-I/O result changed unexpectedly")
    audit = {
        "case_id": case_id,
        "before_checkpoint_sha256": digest(before_state),
        "before_result_sha256": digest(before_result),
        "completed_trials_unchanged": len(old_order),
        "queued_selectors_unchanged": len(old_queue),
        "current_selector_unchanged": old_current,
        "exact_match_and_target_counts_unchanged": True,
        "old_io_family_count": len(old_families),
        "stable_io_family_count": len(seen),
        "old_last8_coverage_or_io_novelty": old_novelty,
        "stable_last8_coverage_or_io_novelty": novelty_last8(state, case_id),
        "budget_extension_decision_note": (
            "This is an interim checkpoint. The extension decision is made only "
            "after trial 80 from its final last-eight trials."),
        "changed_trial_feedback": changes,
        "identity_rule": "Replace random @hex thread object IDs with @object for I/O-family feedback only; retain exact per-run runtime selectors.",
    }
    atomic_json(anchor / "stable-io-reconciliation.json", audit)
    print(json.dumps({k: audit[k] for k in (
        "completed_trials_unchanged", "old_io_family_count", "stable_io_family_count",
        "old_last8_coverage_or_io_novelty", "stable_last8_coverage_or_io_novelty")},
        sort_keys=True))


if __name__ == "__main__":
    main()
