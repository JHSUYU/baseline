"""Strictly promote one observed SOLR-10 queue door to a role-bound plan.

The old v28a traces lack `role_ordinal`; promotion therefore fails closed on
them. A future healthy trace must carry an event-time role receipt from the
agent before this function can produce a role plan.
"""

from __future__ import annotations

from copy import deepcopy


ROLE = "overseer-leader"
SITE = "org.apache.solr.cloud.OverseerTaskProcessor#run()V@246:door:1"


def promote(plan: dict, healthy_events: list[dict]) -> dict:
    faults = plan.get("faults")
    if plan.get("schema_version") != 1 or not isinstance(faults, list) or len(faults) != 1:
        raise ValueError("expected a schema-1 single-fault pilot plan")
    result = deepcopy(plan)
    fault = result["faults"][0]
    point = fault.get("point")
    if not isinstance(point, dict) or point.get("site") != SITE:
        raise ValueError("plan does not select exact SOLR-10 run@246 queue door")
    required = {"site", "node", "epoch", "door_ordinal"}
    if set(point) != required or not isinstance(point["door_ordinal"], int):
        raise ValueError("source plan needs an exact physical site/node/epoch/ordinal")
    matches = [event for event in healthy_events
               if event.get("type") == "DOOR_OBSERVED"
               and all(event.get(key) == point[key] for key in required)]
    if len(matches) != 1:
        raise ValueError("original physical door is missing or ambiguous")
    observed = matches[0]
    if observed.get("role") != ROLE or observed.get("role_resolution") != "unique":
        raise ValueError("healthy door has no unique observed overseer leader")
    ordinal = observed.get("role_ordinal")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal <= 0:
        raise ValueError("healthy door has no valid role ordinal")
    if observed.get("role_node") != point["node"] or observed.get("role_epoch") != point["epoch"]:
        raise ValueError("healthy role binding disagrees with physical door identity")
    leader_id = observed.get("role_leader_id")
    if not isinstance(leader_id, str) or not leader_id:
        raise ValueError("healthy role binding lacks Solr election ID")
    # This is a symbolic *constraint*, not an arbitrary-node wildcard. The
    # agent must resolve it uniquely before the call and emit physical identity.
    fault["point"] = {"site": SITE, "role": ROLE, "role_ordinal": ordinal}
    fault["role_source"] = {"healthy_event_id": observed.get("id"),
                            "healthy_node": point["node"],
                            "healthy_epoch": point["epoch"],
                            "healthy_leader_id": leader_id}
    return result


def attest_applied(plan: dict, events: list[dict]) -> dict:
    """Require one exact FAULT_APPLIED with a unique physical role receipt."""
    fault = plan["faults"][0]
    point = fault["point"]
    if set(point) != {"site", "role", "role_ordinal"} or point["site"] != SITE or point["role"] != ROLE:
        raise ValueError("not a strict SOLR-10 role plan")
    applied = [event for event in events if event.get("type") == "FAULT_APPLIED"
               and event.get("fault_id") == fault.get("fault_id")]
    if len(applied) != 1:
        raise ValueError("fault was not applied exactly once")
    event = applied[0]
    if event.get("site") != SITE or event.get("role") != ROLE:
        raise ValueError("applied fault site or role differs")
    if event.get("role_ordinal") != point["role_ordinal"]:
        raise ValueError("applied role ordinal differs")
    node, epoch = event.get("node"), event.get("epoch")
    if not isinstance(node, str) or not node or node == "unknown" or not isinstance(epoch, int):
        raise ValueError("applied fault lacks physical node/epoch")
    if event.get("role_node") != node or event.get("role_epoch") != epoch:
        raise ValueError("role receipt disagrees with applied physical identity")
    if event.get("role_resolution") != "unique" or not event.get("role_leader_id"):
        raise ValueError("applied fault lacks a unique election receipt")
    return {"fault_id": fault["fault_id"], "site": SITE, "physical_node": node,
            "physical_epoch": epoch, "role_ordinal": point["role_ordinal"],
            "leader_id": event["role_leader_id"]}
