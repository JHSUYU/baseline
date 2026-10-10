"""Independent receipt gate for v3's third I/O fault and postfault target."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "fault-bootstrap-node0-v2"))
import seed_selector as seed  # noqa: E402


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def attest(trial: Path, plan: list[dict]) -> dict:
    require(len(plan) == 3 and [x.get("expected_door") for x in plan[:2]] ==
            ["second", "retry"], "third-fault plan lacks qualified parent prefix")
    seed.attest_fault_resources(trial, plan)
    rows = seed.events(trial)
    second = seed.second_lookup(trial)
    pair = [row for row in rows if row.get("type") == "FAULT_APPLIED" and
            row.get("fault_id") == plan[1]["fault_id"]]
    require(len(pair) == 1, "parent retry application missing")
    last_pair = pair[0]
    fault = plan[2]
    point = fault["point"]
    receipts = [row for row in rows if row.get("fault_id") == fault["fault_id"] and
                row.get("type") in ("FAULT_MATCHED", "FAULT_APPLIED")]
    require(sorted(row["type"] for row in receipts) ==
            ["FAULT_APPLIED", "FAULT_MATCHED"],
            "third fault matched/applied receipt missing or duplicated")
    matched = next(row for row in receipts if row["type"] == "FAULT_MATCHED")
    applied = next(row for row in receipts if row["type"] == "FAULT_APPLIED")
    require(last_pair["seq"] < matched["seq"] < applied["seq"] and
            seed.same_execution(matched, applied),
            "third fault was not applied after parent pair on one execution")
    require(all(applied.get(key) == point.get(key) for key in
                ("site", "node", "epoch")), "third fault actor or site changed")
    phase = point.get("solr15_parent_lookup")
    if point["site"] == seed.NATIVE:
        require(phase in ("after_pair", "explicit_resource"),
                "native third fault lacks pre-injection resource qualification")
        if phase == "after_pair":
            require(seed.same_execution(applied, last_pair) and
                    applied.get("selector_phase") == "after_pair" and
                    applied.get("bound_resource") == second["resource"],
                    "after-pair native fault lost bound split identity")
            expected = (second["resource"] if point.get("resource_role") == "bound_parent"
                        else point.get("resource"))
            require(expected and applied.get("resource") == expected,
                    "after-pair native fault used another path")
            candidates = [row for row in rows if
                          row.get("type") == "SOLR15_PARENT_CANDIDATE" and
                          row.get("selector_phase") == "after_pair" and
                          row.get("resource") == expected and
                          row.get("bound_resource") == second["resource"] and
                          row.get("seq", -1) > last_pair["seq"] and
                          row.get("seq", -1) < matched["seq"] and
                          seed.same_execution(row, applied)]
            require(len(candidates) == 1,
                    "after-pair pre-injection resource candidate missing")
        else:
            require(point.get("resource") and
                    applied.get("resource") == point["resource"] and
                    applied.get("occurrence") == point.get("occurrence") and
                    applied.get("door_ordinal") == point.get("door_ordinal"),
                    "explicit native resource, occurrence or ordinal changed")
    else:
        require(phase is None and point.get("occurrence") and
                applied.get("occurrence") == point["occurrence"] and
                applied.get("door_ordinal") == point.get("door_ordinal"),
                "nonnative third occurrence or ordinal changed")
    target_after = seed.attest_target_after_fault(trial, plan)
    return {"valid": True, "third_applied_event_id": applied["id"],
            "third_resource": applied.get("resource"),
            "third_scope": phase or "exact_occurrence_ordinal",
            "target_after_all_faults": target_after}
