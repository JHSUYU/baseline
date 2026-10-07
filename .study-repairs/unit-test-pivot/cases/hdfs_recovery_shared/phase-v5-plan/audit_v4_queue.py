#!/usr/bin/env python3
"""Read-only feasibility and migration audit for the archived V4 recovery queue."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
V4 = HERE.parent / "phase-v4"
sys.path.insert(0, str(V4))
import campaign  # noqa: E402

CASES = ("HDFS-28", "HDFS-29", "HDFS-30")
PARENT_KEYS = ("marker", "siteId", "sourceKey", "originSourceKey",
               "occurrenceAddress", "hitOrdinal", "requestApi", "faultType")
EVENT_KEYS = PARENT_KEYS[:-1]
HASHED_FILES = ("campaign-state.json", "campaign.py", "run_original.py",
                "RecoveryProbe.java", "PatchRecovery.java", "final-audit.json",
                "raw-evidence.tar.gz")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def key(point: dict) -> tuple:
    # V4 annotated queued file phases after some parents completed. Those
    # historical parents kept their original hashes, so phase is not a
    # parent-lookup key. It is still checked when matching the actual I/O.
    return tuple(point.get(field, "") for field in PARENT_KEYS)


def observed(event: dict, selected: dict) -> bool:
    if event.get("event") != "FAULT_POINT_OBSERVED":
        return False
    for field in EVENT_KEYS:
        value = (event.get("originSourceKey", event.get("sourceKey", ""))
                 if field == "originSourceKey" else event.get(field, ""))
        if value != selected.get(field, ""):
            return False
    phase = selected.get("filePhase", "")
    return not (phase and event.get("filePhase") and event["filePhase"] != phase)


def later_same_owner_check(trace: list[dict], io: dict, case: str) -> bool:
    return any(row.get("event") == "TARGET_CHECK"
               and row.get("caseId") == case
               and row.get("sourceKey") == io.get("originSourceKey", io.get("sourceKey"))
               and row.get("blockId") == io.get("blockId")
               and row.get("occurrenceAddress") == campaign.recovery_root(io)
               and row.get("seq", -1) > io.get("seq", -1)
               for row in trace)


def main() -> None:
    state = json.loads((V4 / "campaign-state.json").read_text())
    if state.get("active") is not None or state.get("stop_reason") != "budget":
        raise RuntimeError("V4 is not at its archived completed-trial boundary")
    completed, queue = state["completed"], state["queue"]
    completed_by_id = defaultdict(list)
    strict_parents = defaultdict(list)
    for trial in completed:
        completed_by_id[trial["id"]].append(trial)
        if trial["exact_order_applied"]:
            strict_parents[tuple(key(point) for point in trial["sequence"])].append(trial)
    strict_ids = {trial["id"] for trial in completed if trial["exact_order_applied"]}
    queued_ids = [item["id"] for item in queue]
    if len(set(queued_ids)) != len(queued_ids):
        raise RuntimeError("duplicate pending plan IDs")
    if strict_ids.intersection(queued_ids):
        raise RuntimeError("an already strictly injected plan is pending again")

    single = [item for item in queue if len(item["sequence"]) == 1]
    pair = [item for item in queue if len(item["sequence"]) == 2]
    if len(single) + len(pair) != len(queue):
        raise RuntimeError("unexpected queued fault depth")
    traces: dict[str, list[dict]] = {}
    pre_target: dict[str, list[str]] = {case: [] for case in CASES}
    unresolved: list[str] = []
    for item in pair:
        parents = strict_parents.get(tuple(key(point) for point in item["sequence"][:-1]), [])
        if not parents:
            unresolved.append(item["id"])
            continue
        matched = False
        eligible = set()
        for parent in parents:
            run = parent["run"]
            if run not in traces:
                traces[run] = campaign.rows(Path(run))
            trace = traces[run]
            for event in trace:
                if event.get("seq", -1) <= parent["last_applied_seq"]:
                    continue
                if not observed(event, item["sequence"][-1]):
                    continue
                matched = True
                for case in CASES:
                    if later_same_owner_check(trace, event, case):
                        eligible.add(case)
        if not matched:
            unresolved.append(item["id"])
            continue
        for case in eligible:
            pre_target[case].append(item["id"])

    effective = {case: sum(bool(trial["exact_order_applied"] and
                                  trial["post_fault_target_checks"][case])
                           for trial in completed) for case in CASES}
    receipt = {
        "schema": "hdfs-recovery-v5-offline-queue-audit-1",
        "v4_sha256": {name: digest(V4 / name) for name in HASHED_FILES},
        "v4_state_boundary": {"active": state["active"],
                              "stop_reason": state["stop_reason"],
                              "max_trials": state["budget"]["max_trials"],
                              "max_faults": state["budget"]["max_faults"]},
        "completed_attempts": len(completed),
        "completed_distinct_plan_ids": len(completed_by_id),
        "strict_attempts": sum(x["exact_order_applied"] for x in completed),
        "strict_distinct_plan_ids": len(strict_ids),
        "effective_by_case": effective,
        "pending": {"total": len(queue), "single": len(single), "pair": len(pair),
                    "distinct_plan_ids": len(set(queued_ids)),
                    "already_strict_plan_ids": len(strict_ids.intersection(queued_ids)),
                    "unmatched_retry_plan_ids": len(set(completed_by_id).intersection(queued_ids)),
                    "single_later_or_unproven": sum(not item.get("pre_target") for item in single),
                    "single_fault_types": dict(Counter(item["sequence"][-1]["faultType"]
                                                       for item in single)),
                    "pair_second_fault_pre_target_by_case":
                        {case: sorted(ids) for case, ids in pre_target.items()},
                    "pair_unresolved_parent_or_io": sorted(unresolved)},
        "source_order": "BlockRecoveryWorker.RecoveryTaskContiguous.recover calls HDFS-28 "
                        "at each replica-loop entry; HDFS-29/30 follow replica RPCs.",
    }
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
