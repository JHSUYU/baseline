#!/usr/bin/env python3
"""Annotate queued observed I/O with parent-run target order; keep all items."""

from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import campaign


HERE = Path(__file__).resolve().parent
POINT_KEYS = ("marker", "siteId", "sourceKey", "originSourceKey",
              "occurrenceAddress", "hitOrdinal", "requestApi", "faultType")
EVENT_KEYS = POINT_KEYS[:-1]


def key(point: dict) -> tuple:
    return tuple(point.get(field, "") for field in POINT_KEYS)


def observed(trace: list[dict], selected: dict) -> dict | None:
    for event in trace:
        if event.get("event") != "FAULT_POINT_OBSERVED":
            continue
        if any((event.get("originSourceKey", event.get("sourceKey", ""))
                if field == "originSourceKey" else event.get(field, ""))
               != selected.get(field, "") for field in EVENT_KEYS):
            continue
        if (selected.get("filePhase") and event.get("filePhase")
                and event["filePhase"] != selected["filePhase"]):
            continue
        return event
    return None


def main() -> None:
    state = json.loads(campaign.STATE.read_text())
    if state.get("stop_reason") != "operator_pause" or state.get("active") is not None:
        raise RuntimeError("pause at a completed trial boundary first")
    report = HERE / "pre-target-priority-change.json"
    if report.exists():
        raise RuntimeError("priority migration already recorded")
    original = campaign.STATE.read_bytes()
    with gzip.open(HERE / "campaign-state.before-pre-target-priority.json.gz", "wb") as backup:
        backup.write(original)

    parents = {}
    for trial in state["completed"]:
        parents.setdefault(tuple(key(point) for point in trial["sequence"]), []).append(trial)
    healthy = [campaign.rows(Path(p)) for p in state["healthy_dirs"]]
    trace_cache = {}
    counts = Counter()
    for item in state["queue"]:
        sequence = item["sequence"]
        selected = sequence[-1]
        if len(sequence) == 1:
            events = [(trace, observed(trace, selected)) for trace in healthy]
            found = [campaign.relevant_before_target(event, trace)
                     for trace, event in events if event is not None]
            item["pre_target"] = any(found)
            counts["single_before" if item["pre_target"] else "single_later_or_missing"] += 1
            continue
        matches = parents.get(tuple(key(point) for point in sequence[:-1]), [])
        if not matches:
            item["pre_target"] = False
            counts["multi_parent_missing"] += 1
            continue
        if len(matches) > 1:
            counts["multi_parent_replayed"] += 1
        found = []
        for parent in matches:
            parent_run = parent["run"]
            if parent_run not in trace_cache:
                trace_cache[parent_run] = campaign.rows(Path(parent_run))
            trace = trace_cache[parent_run]
            event = observed(trace, selected)
            if event is not None:
                found.append(campaign.relevant_before_target(event, trace))
        if not found:
            item["pre_target"] = False
            counts["multi_observed_point_missing"] += 1
            continue
        item["pre_target"] = any(found)
        counts["multi_before" if item["pre_target"] else "multi_later"] += 1

    completed = state["completed"]
    strict = [trial for trial in completed if trial["exact_order_applied"]]
    prechange = {}
    for depth in (1, 2):
        subset = [trial for trial in completed if len(trial["sequence"]) == depth]
        exact = [trial for trial in subset if trial["exact_order_applied"]]
        prechange[str(depth)] = {
            "attempted": len(subset), "strict": len(exact),
            "strict_target_retained_any_case": sum(
                any(trial["post_fault_target_checks"].values()) for trial in exact),
        }
    state["priority_rule_version"] = "observed_pre_target_3_of_4_v1"
    state["priority_changed_after_trial"] = len(completed)
    campaign.atomic_json(campaign.STATE, state)
    campaign.atomic_json(report, {
        "rule": "three of four selections prefer parent-observed same-owner I/O before next target check; fourth explores all",
        "raw_state_sha256": hashlib.sha256(original).hexdigest(),
        "changed_after_completed_trials": len(completed),
        "queue_items_before_and_after": len(state["queue"]),
        "classifications": dict(counts),
        "before_effectiveness_by_fault_depth": prechange,
        "before_strict_total": len(strict),
    })
    print(json.dumps({"completed": len(completed),
                      "queue": len(state["queue"]),
                      "classifications": dict(counts)}, sort_keys=True))


if __name__ == "__main__":
    main()
