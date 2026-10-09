#!/usr/bin/env python3
"""Separate, fail-closed target and actor audit for alternate original JUnits."""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRST = HERE.parent


def parse(path: Path) -> list[tuple[int, str, str, list[str]]]:
    rows = []
    for line in path.read_text().splitlines():
        fields = line.split("\t")
        if len(fields) >= 3:
            rows.append((int(fields[0]), fields[1], fields[2], fields[3:]))
    assert all(a[0] < b[0] for a, b in zip(rows, rows[1:])), path
    return rows


def actor(fields: list[str]) -> str | None:
    values = [value.removeprefix("actor=") for value in fields
              if value.startswith("actor=")]
    return values[0] if len(values) == 1 and values[0].startswith("ZKCLIENT@") else None


def normalized(selector: str) -> str:
    return re.sub(r":/collections/[^/]+/state\.json:",
                  ":/collections/{collection}/state.json:", selector)


def old_roots() -> set[str]:
    inventory = json.loads((FIRST / "frontier-inventory-701plus.json").read_text())
    assert len(inventory["roots"]) == 21
    return {row["selector"] for row in inventory["roots"]}


def audit(path: Path) -> dict:
    rows = parse(path)
    starts = [row for row in rows if row[1] == "TEST_STARTED"]
    finishes = [row for row in rows if row[1] == "TEST_FINISHED"]
    result = {"selected_target": False, "reason": "no eligible API mutation and guard",
              "test_started_count": len(starts), "test_finished_count": len(finishes),
              "stable_root_candidates": [], "same_actor_pretarget_roots": []}
    if len(starts) != 1 or len(finishes) != 1 or finishes[0][0] <= starts[0][0]:
        result["reason"] = "missing or multiple test boundaries"
        return result
    start, finish = starts[0][0], finishes[0][0]
    candidates = [row for row in rows if row[1] == "APPLY_MODIFICATION"
                  and start < row[0] < finish and len(row[3]) >= 3
                  and row[3][1] == "CREATE_ALIAS_CMD" and actor(row[3])]
    if not candidates:
        result["reason"] = "no bound CreateAliasCmd mutation in test interval"
        return result
    first = candidates[0]
    manager, chosen_actor = first[3][0], actor(first[3])
    next_apply = next((row[0] for row in rows if row[1] == "APPLY_MODIFICATION"
                       and row[0] > first[0] and row[3]
                       and row[3][0] == manager), finish)
    limit = min(next_apply, finish)
    guard = next((row for row in rows if row[1] == "TARGET_GUARD"
                  and first[0] < row[0] < limit and len(row[3]) >= 7
                  and row[3][0] == manager and row[3][3:6] == ["1", "1", "0"]
                  and actor(row[3]) == chosen_actor), None)
    result.update({"first_api_apply_sequence": first[0], "manager": manager,
                   "target_actor": chosen_actor, "next_same_manager_apply_sequence": next_apply})
    if guard is None:
        result["reason"] = "first API mutation has no same-manager version-1 guard before next mutation"
        return result
    outcome = next((row for row in rows if row[1] in
                    ("TARGET_EQUAL_CHECK", "TARGET_THROW") and row[0] > guard[0]
                    and row[3][:6] == guard[3][:6]
                    and actor(row[3]) == chosen_actor), None)
    roots = list(dict.fromkeys(row[3][0] + "@@" + row[3][1]
                               for row in rows if row[1] == "IO"
                               and row[0] < guard[0] and len(row[3]) >= 3
                               and actor(row[3]) == chosen_actor))
    prior = old_roots()
    prior_normalized = {normalized(root) for root in prior}
    novel = [root for root in roots if root not in prior
             and normalized(root) not in prior_normalized]
    result.update({"selected_target": True, "reason": "selected",
                   "selected_target_sequence": guard[0],
                   "target_versions_cmp": guard[3][3:6],
                   "target_outcome": outcome[1] if outcome else None,
                   "target_json_equal": (outcome[3][6] == "true" if outcome
                                         and outcome[1] == "TARGET_EQUAL_CHECK" else None),
                   "same_actor_pretarget_roots": roots,
                   "stable_root_candidates": novel})
    return result
