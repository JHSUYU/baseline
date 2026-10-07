#!/usr/bin/env python3
"""Fail-closed actor audit for the selected equal-version alias check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def events(path: Path) -> list[tuple[int, str, str, list[str]]]:
    rows = []
    for line in path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) >= 3:
            rows.append((int(fields[0]), fields[1], fields[2], fields[3:]))
    return rows


def actor(fields: list[str]) -> str | None:
    values = [value[6:] for value in fields if value.startswith("actor=")]
    if len(values) != 1 or not values[0].startswith("ZKCLIENT@"):
        return None
    return values[0]


def selected_check(rows: list[tuple[int, str, str, list[str]]]):
    started = next((row[0] for row in rows if row[1] == "TEST_STARTED"), None)
    if started is None:
        return None
    first = next((row for row in rows if row[1] == "APPLY_MODIFICATION"
                  and row[0] > started and len(row[3]) >= 3
                  and row[3][1] == "TEST_BODY" and actor(row[3])), None)
    if first is None:
        return None
    manager = first[3][0]
    chosen_actor = actor(first[3])
    next_apply = next((row[0] for row in rows if row[1] == "APPLY_MODIFICATION"
                       and row[0] > first[0] and row[3]
                       and row[3][0] == manager), None)
    finished = next((row[0] for row in rows if row[1] == "TEST_FINISHED"
                     and row[0] > first[0]), None)
    return next((row for row in rows if row[1] == "TARGET_EQUAL_CHECK"
                 and row[0] > first[0]
                 and (next_apply is None or row[0] < next_apply)
                 and (finished is None or row[0] < finished)
                 and len(row[3]) >= 8 and row[3][0] == manager
                 and row[3][3:6] == ["1", "1", "0"]
                 and actor(row[3]) == chosen_actor), None)


def audit(path: Path, plan: list[str]) -> dict:
    rows = events(path)
    target = selected_check(rows)
    if target is None:
        return {"selected_target": False, "effective": False,
                "reason": "no selected test-body version-1 check with bound ZK client"}
    target_actor = actor(target[3])
    applied = [row for row in rows if row[1] == "FAULT_APPLIED"]
    matched = [row for row in rows if row[1] == "FAULT_MATCHED"]
    actual = [row[3][0] + "@@" + row[3][1] for row in applied if len(row[3]) >= 4]
    strict = bool(plan and len(applied) == len(plan) == len(matched)
                  and actual == plan
                  and [row[3][0] + "@@" + row[3][1] for row in matched] == plan
                  and all(match[0] + 1 == injection[0]
                          for match, injection in zip(matched, applied)))
    all_actor_bound = strict and all(actor(row[3]) == target_actor for row in applied)
    postfinal = bool(applied and target[0] > applied[-1][0])
    useful_io = [row[3][0] + "@@" + row[3][1] for row in rows
                 if row[1] == "IO" and len(row[3]) >= 3
                 and actor(row[3]) == target_actor and row[0] < target[0]]
    return {
        "selected_target": True,
        "selected_target_sequence": target[0],
        "target_actor": target_actor,
        "target_json_equal": target[3][6] == "true",
        "strict_ordered_faults": strict,
        "all_faults_on_target_client": all_actor_bound,
        "target_after_final_fault": postfinal,
        "effective": bool(strict and all_actor_bound and postfinal),
        "relevant_same_client_io_selectors": list(dict.fromkeys(useful_io)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--plan", default="")
    args = parser.parse_args()
    print(json.dumps(audit(args.trace, args.plan.split("|||") if args.plan else []),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
