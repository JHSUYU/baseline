"""Case-local, path-qualified bootstrap for the unchanged SOLR-34 cluster JUnit."""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from typing import Any, Callable

RESOURCE = "/collections/.sys.COORDINATOR-COLL-conf/state.json"
NODE = "node5"
EPOCH = 0
REGION = ("org.apache.solr.servlet.CoordinatorHttpSolrCall"
          "#getCore(Lorg/apache/solr/servlet/CoordinatorHttpSolrCall$Factory;"
          "Lorg/apache/solr/servlet/HttpSolrCall;Ljava/lang/String;Z)"
          "Lorg/apache/solr/core/SolrCore;")
CHECK = REGION + "@139:branch:6"
RETHROW = REGION + "@140:throw:1"
NEW_THROW = REGION + "@143:throw:2"
DOOR = ("org.apache.solr.common.cloud.SolrZkClient#lambda$getData$6"
        "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
        "Lorg/apache/zookeeper/data/Stat;)[B@349:door:1")
TYPED = "org.apache.zookeeper.KeeperException$ConnectionLossException"


def _seq(row: dict) -> int:
    value = row.get("seq")
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _root(context: Any) -> str | None:
    return context.split(":", 1)[0] if isinstance(context, str) and ":" in context else None


def operation_witness(rows: list[dict], door: dict) -> dict | None:
    """Tie a servlet-thread path read to one active getCore and HTTP receive.

    The interval and shared trace root are evidence of operation membership;
    they are not a claim that every Overseer hop has a traced causal edge.
    Callback threads are excluded from this first bootstrap.
    """
    if (door.get("type") != "DOOR_OBSERVED" or door.get("site") != DOOR
            or door.get("resource") != RESOURCE or door.get("node") != NODE
            or door.get("epoch") != EPOCH or door.get("fault_type") != "EXCEPTION"
            or door.get("exception_class") != TYPED
            or not str(door.get("thread", "")).startswith("qtp")
            or not isinstance(door.get("door_ordinal"), int)
            or not isinstance(door.get("occurrence"), str)):
        return None
    seq, root = _seq(door), _root(door.get("context"))
    if seq < 0 or root is None:
        return None
    receives = [row for row in rows if row.get("type") == "RECV"
                and row.get("node") == NODE and row.get("epoch") == EPOCH
                and row.get("site") == "SolrDispatchFilter#doFilter"
                and row.get("transport") == "solr-http"
                and row.get("context") == door.get("context")
                and _seq(row) < seq]
    if len(receives) != 1:
        return None
    recv = receives[0]
    sends = [row for row in rows if row.get("type") == "SEND"
             and row.get("transport") == "solr-http"
             and row.get("correlation") == recv.get("correlation")
             and _seq(row) < _seq(recv)]
    if len(sends) != 1:
        return None
    enters = [row for row in rows if row.get("type") == "REGION_ENTER"
              and row.get("site") == REGION and row.get("node") == NODE
              and row.get("epoch") == EPOCH and _root(row.get("context")) == root
              and _seq(row) < seq]
    candidates = []
    for enter in enters:
        exits = [row for row in rows if row.get("type") == "REGION_EXIT"
                 and row.get("site") == REGION and row.get("node") == NODE
                 and row.get("epoch") == EPOCH
                 and row.get("occurrence") == enter.get("occurrence")
                 and _seq(row) > seq]
        if len(exits) == 1:
            candidates.append((enter, exits[0]))
    if len(candidates) != 1:
        return None
    enter, exit_row = candidates[0]
    return {"parent_getcore_occurrence": enter["occurrence"],
            "parent_enter_seq": _seq(enter), "parent_exit_seq": _seq(exit_row),
            "http_send_id": sends[0].get("id"), "http_recv_id": recv.get("id"),
            "inner_http_context": door["context"], "inner_occurrence": door["occurrence"]}


def annotate_feedback(rows: list[dict], feedback: dict, plan: list[dict]) -> dict:
    """Add path/operation evidence that the frozen generic feedback omits."""
    by_seq = {_seq(row): row for row in rows if row.get("type") == "DOOR_OBSERVED"}
    result = copy.deepcopy(feedback)
    for door in result.get("doors", []):
        raw = by_seq.get(door.get("event_seq"))
        if raw is None or raw.get("site") != door.get("site"):
            continue
        door["resource"] = raw.get("resource")
        door["thread"] = raw.get("thread")
        door["context"] = raw.get("context")
        door["occurrence"] = raw.get("occurrence")
        witness = operation_witness(rows, raw)
        if witness:
            door["operation_witness"] = witness
    if plan:
        last = plan[-1]
        applied = [row for row in rows if row.get("type") == "FAULT_APPLIED"
                   and row.get("fault_id") == last.get("fault_id")]
        if len(applied) == 1:
            matching = [row for row in rows if row.get("type") == "DOOR_OBSERVED"
                        and row.get("site") == applied[0].get("site")
                        and row.get("node") == applied[0].get("node")
                        and row.get("epoch") == applied[0].get("epoch")
                        and row.get("door_ordinal") == applied[0].get("door_ordinal")]
            if len(matching) == 1:
                witness = operation_witness(rows, matching[0])
                if witness:
                    result["solr34_active_parent_occurrence"] = witness["parent_getcore_occurrence"]
    return result


def mutate(parent: list[dict], feedback: dict, config: dict,
           original: Callable, signature: Callable, *, bootstrap: bool) -> list[dict]:
    if not bootstrap:
        return []  # This package stops at first exact target; no graph phase.
    selected = copy.deepcopy(feedback)
    parent_occurrence = selected.get("solr34_active_parent_occurrence") if parent else None
    selected["doors"] = [door for door in selected.get("doors", [])
                         if door.get("site") == DOOR and door.get("resource") == RESOURCE
                         and door.get("point", {}).get("node") == NODE
                         and door.get("point", {}).get("epoch") == EPOCH
                         and door.get("operation_witness")
                         and (not parent or
                              door["operation_witness"]["parent_getcore_occurrence"]
                              == parent_occurrence)]
    if parent and parent_occurrence is None:
        return []
    candidates = original(parent, selected, config, bootstrap=True)
    for candidate in candidates:
        fault = candidate["faults"][-1]
        fault["point"]["resource"] = RESOURCE
        fault["expected_resource"] = RESOURCE
        candidate["selection_reason"] = "solr34_synthetic_state_bootstrap"
        candidate["signature"] = signature(candidate["faults"])
    return candidates


def load_events(trial: Path) -> list[dict]:
    with gzip.open(trial / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def audit_trial(rows: list[dict], plan: list[dict], catalog: list[dict]) -> dict:
    if {CHECK, RETHROW, NEW_THROW, DOOR} - {row.get("site") for row in catalog}:
        return {"valid": False, "status": "exact_site_catalog_missing"}
    if not plan:
        eligible = [row for row in rows if operation_witness(rows, row)]
        return {"valid": bool(eligible),
                "status": "eligible_healthy_bootstrap" if eligible else "no_qualified_parent_path_door",
                "qualified_path_doors": len(eligible),
                "qualified_ordinals": [row["door_ordinal"] for row in eligible]}
    fault_proofs = []
    for fault in plan:
        point = fault.get("point", {})
        if (point.get("site") != DOOR or point.get("node") != NODE
                or point.get("epoch") != EPOCH or point.get("resource") != RESOURCE
                or not isinstance(point.get("door_ordinal"), int)):
            return {"valid": False, "status": "unqualified_fault_plan"}
        doors = [row for row in rows if row.get("type") == "DOOR_OBSERVED"
                 and all(row.get(key) == point.get(key) for key in
                         ("site", "node", "epoch", "door_ordinal", "resource"))]
        matched = [row for row in rows if row.get("type") == "FAULT_MATCHED"
                   and row.get("fault_id") == fault.get("fault_id")]
        applied = [row for row in rows if row.get("type") == "FAULT_APPLIED"
                   and row.get("fault_id") == fault.get("fault_id")]
        if len(doors) != 1 or len(matched) != 1 or len(applied) != 1:
            return {"valid": False, "status": "fault_not_applied_once"}
        door, match, apply = doors[0], matched[0], applied[0]
        witness = operation_witness(rows, door)
        if (witness is None or not (_seq(door) < _seq(match) < _seq(apply))
                or any(row.get("occurrence") != door.get("occurrence")
                       or row.get("context") != door.get("context")
                       or any(row.get(key) != point[key] for key in
                              ("site", "node", "epoch", "door_ordinal", "resource"))
                       for row in (match, apply))):
            return {"valid": False, "status": "fault_resource_or_operation_mismatch"}
        fault_proofs.append({"fault_id": fault["fault_id"], "door_seq": _seq(door),
                             "applied_seq": _seq(apply), "door_ordinal": point["door_ordinal"],
                             "occurrence": door["occurrence"], "operation_witness": witness})
    parents = {proof["operation_witness"]["parent_getcore_occurrence"]
               for proof in fault_proofs}
    if len(parents) != 1:
        return {"valid": False, "status": "faults_crossed_parent_operation"}
    after = max(proof["applied_seq"] for proof in fault_proofs)
    parent_occurrence = next(iter(parents))
    checks = [row for row in rows if row.get("type") == "TARGET_CHECK"
              and row.get("site") == CHECK and row.get("node") == NODE
              and row.get("epoch") == EPOCH and row.get("occurrence") == parent_occurrence
              and _seq(row) > after]
    throws = [row for row in rows if row.get("type") == "TARGET_THROW"
              and row.get("site") in (RETHROW, NEW_THROW)
              and row.get("node") == NODE and row.get("epoch") == EPOCH
              and row.get("occurrence") == parent_occurrence
              and checks and _seq(row) > min(_seq(check) for check in checks)]
    outcome = ("selected_new_exception" if any(row["site"] == NEW_THROW for row in throws)
               else "prior_exception_rethrow" if any(row["site"] == RETHROW for row in throws)
               else "check_without_attributed_throw" if checks else "target_absent")
    return {"valid": True, "status": "attributed", "faults": fault_proofs,
            "parent_getcore_occurrence": parent_occurrence,
            "target_after_fault": bool(checks), "target_check_seqs": [_seq(row) for row in checks],
            "target_outcome": outcome,
            "selected_throw_seqs": [_seq(row) for row in throws if row["site"] == NEW_THROW],
            "rethrow_seqs": [_seq(row) for row in throws if row["site"] == RETHROW]}
