"""Strict SOLR-14 fault-to-retry target retention from raw runtime events."""

from __future__ import annotations

from audit_healthy import CHECK, FIRST, SECOND, TYPED, CONFIG

THROW = CONFIG["target"]["throw_site"]


def evaluate(events: list[dict], feedback: dict, healthy_actor: str) -> dict:
    if feedback.get("all_faults_effective") is not True or feedback.get("fault_identity_valid") is not True:
        return {"valid": False, "reason": "fault_not_effective_or_identity_invalid"}
    applied = sorted((row for row in events if row.get("type") == "FAULT_APPLIED"),
                     key=lambda row: row.get("seq", -1))
    if not applied or any(row.get("site") not in (FIRST, SECOND)
                          or row.get("fault_type") != "EXCEPTION"
                          or row.get("exception_class") != TYPED
                          or row.get("node") != healthy_actor
                          or not isinstance(row.get("epoch"), int)
                          or not row.get("occurrence") for row in applied):
        return {"valid": False, "reason": "applied_fault_not_typed_same_actor_split_door"}
    last = applied[-1]
    target = sorted((row for row in events if row.get("type") == "TARGET_CHECK"
                     and row.get("site") == CHECK and row.get("node") == healthy_actor
                     and row.get("epoch") == last["epoch"]
                     and row.get("occurrence") != last["occurrence"]
                     and row.get("seq", -1) > last["seq"]),
                    key=lambda row: row["seq"])
    for check in target:
        matching = [row for row in events if row.get("type") == "DOOR_OBSERVED"
                    and row.get("node") == healthy_actor
                    and row.get("epoch") == check["epoch"]
                    and row.get("occurrence") == check["occurrence"]
                    and row.get("exception_class") == TYPED
                    and row.get("fault_type") == "EXCEPTION"]
        first = [row for row in matching if row.get("site") == FIRST
                 and last["seq"] < row.get("seq", -1) < check["seq"]]
        second = [row for row in matching if row.get("site") == SECOND
                  and last["seq"] < row.get("seq", -1) < check["seq"]]
        if not any(a["seq"] < b["seq"] for a in first for b in second):
            continue
        throws = [row for row in events if row.get("type") == "TARGET_THROW"
                  and row.get("site") == THROW and row.get("node") == healthy_actor
                  and row.get("epoch") == check["epoch"]
                  and row.get("occurrence") == check["occurrence"]
                  and row.get("seq", -1) > check["seq"]]
        return {"valid": True, "reason": "postfault_retry_target_reached",
                "actor": healthy_actor, "fault_seq": last["seq"],
                "fault_occurrence": last["occurrence"],
                "retry_occurrence": check["occurrence"],
                "retry_target_seq": check["seq"], "target_threw": bool(throws)}
    return {"valid": False, "reason": "no_later_same_actor_typed_retry_target",
            "actor": healthy_actor, "last_fault_seq": last["seq"]}
