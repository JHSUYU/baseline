"""Select a runtime-qualified parent lookup and audit the resulting fault trace."""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

SPLIT = ("org.apache.solr.cloud.api.collections.SplitShardCmd#split"
         "(Lorg/apache/solr/common/cloud/ClusterState;"
         "Lorg/apache/solr/common/cloud/ZkNodeProps;"
         "Lorg/apache/solr/common/util/NamedList;)Z")
FIRST = SPLIT + "@164:door:2"
SECOND = SPLIT + "@523:door:3"
NATIVE = ("org.apache.solr.common.cloud.SolrZkClient#lambda$exists$2"
          "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)"
          "Lorg/apache/zookeeper/data/Stat;@301:door:1")
ROLE = re.compile(r"MALLORY_SOLR_NODE logical=shard-[1-9][0-9]* "
                  r"physical=([^\s]+) epoch=[0-9]+")


def events(trial: Path) -> list[dict]:
    with gzip.open(trial / "events.jsonl.gz", "rt") as stream:
        return [json.loads(line) for line in stream]


def same_execution(left: dict, right: dict) -> bool:
    keys = ("node", "epoch", "occurrence", "thread", "context")
    return (all(key in left and key in right and left[key] == right[key]
                for key in keys) and
            isinstance(left["node"], str) and left["node"] not in ("", "unknown") and
            isinstance(left["epoch"], int) and left["epoch"] >= 0 and
            all(isinstance(left[key], str) and left[key] for key in
                ("occurrence", "thread", "context")))


def _next_native(rows: list[dict], caller: dict) -> dict | None:
    return next((row for row in rows if row.get("type") == "DOOR_OBSERVED"
                 and row.get("site") == NATIVE and same_execution(row, caller)
                 and row["seq"] > caller["seq"]), None)


def second_lookup(trial: Path) -> dict:
    """Bind the exact second caller to its native same-path operation."""
    rows = events(trial)
    parents = set(ROLE.findall((trial / "junit.log").read_text(errors="replace")))
    firsts = [row for row in rows if row.get("type") == "DOOR_OBSERVED"
              and row.get("site") == FIRST]
    seconds = [row for row in rows if row.get("type") == "DOOR_OBSERVED"
               and row.get("site") == SECOND]
    for second in seconds:
        first = next((row for row in firsts if same_execution(row, second)
                      and row["seq"] < second["seq"]), None)
        if first is None:
            continue
        native_first, native_second = _next_native(rows, first), _next_native(rows, second)
        if native_first is None or native_second is None:
            continue
        path = native_second.get("resource")
        if (path == native_first.get("resource") and isinstance(path, str)
                and path.startswith("/live_nodes/") and path.count("/") == 2
                and path.split("/", 2)[2] in parents
                and native_first["seq"] < native_second["seq"]):
            return native_second
    raise ValueError("same-parent first/second native lookup not observed")


def retry_after_fault(trial: Path, expected: dict) -> dict:
    """Find the next native retry on the same split and same live-node path."""
    rows = events(trial)
    second = second_lookup(trial)
    applied = [row for row in rows if row.get("type") == "FAULT_APPLIED"
               and row.get("fault_id") == expected["fault_id"]]
    if (len(applied) != 1 or applied[0].get("resource") != second["resource"]
            or not same_execution(applied[0], second)
            or applied[0].get("door_ordinal") != second.get("door_ordinal")):
        raise ValueError("first fault did not apply on selected live-node path")
    fault = applied[0]
    retry = next((row for row in rows if row.get("type") == "DOOR_OBSERVED"
                  and row.get("site") == NATIVE and same_execution(row, fault)
                  and row.get("resource") == second["resource"]
                  and row["seq"] > fault["seq"]), None)
    if retry is None:
        raise ValueError("no same-split same-path native retry after first fault")
    return retry


def point_of(row: dict) -> dict:
    ordinal = row.get("door_ordinal")
    if not isinstance(ordinal, int) or ordinal <= 0:
        raise ValueError("native door has no replayable ordinal")
    return {"site": row["site"], "node": row["node"],
            "epoch": row["epoch"], "door_ordinal": ordinal}


def pick_exact(queue: list[dict], point: dict, *, faults: int) -> dict:
    for index, candidate in enumerate(queue):
        plan = candidate.get("faults", [])
        if len(plan) != faults or plan[-1].get("point") != point:
            continue
        if faults == 2 and (plan[0].get("expected_door") != "second" or
                            plan[0]["point"].get("site") != NATIVE or
                            plan[0]["point"].get("solr15_parent_lookup") != "second" or
                            plan[0]["point"].get("node") != point["node"] or
                            plan[0]["point"].get("epoch") != point["epoch"]):
            continue
        selected = queue.pop(index)
        fault = selected["faults"][-1]
        phase = "second" if faults == 1 else "retry"
        fault["point"] = {"site": point["site"], "node": point["node"],
                          "epoch": point["epoch"], "solr15_parent_lookup": phase}
        fault["expected_resource_role"] = "parent_leader_znode"
        fault["expected_door"] = phase
        selected["selection_reason"] = "runtime_qualified_parent_" + phase
        from Mallory.core.scheduler import sequence_signature
        selected["signature"] = sequence_signature(selected["faults"])
        return selected
    raise ValueError("exact path-qualified native door absent from bootstrap queue")


def attest_fault_resources(trial: Path, plan: list[dict]) -> None:
    rows = events(trial)
    second = second_lookup(trial)
    first_applied = None
    for fault in plan:
        if "expected_resource_role" not in fault:
            continue  # Later graph-guided faults retain the core's own oracle.
        if fault["expected_resource_role"] != "parent_leader_znode":
            raise ValueError("unrecognized expected resource role")
        receipts = [row for row in rows if row.get("fault_id") == fault["fault_id"]
                    and row.get("type") in ("FAULT_MATCHED", "FAULT_APPLIED")]
        if sorted(row["type"] for row in receipts) != ["FAULT_APPLIED", "FAULT_MATCHED"]:
            raise ValueError("fault matched/applied receipt missing or duplicated")
        phase = fault.get("expected_door")
        point = fault["point"]
        if (point.get("solr15_parent_lookup") != phase or
                set(point) != {"site", "node", "epoch", "solr15_parent_lookup"}):
            raise ValueError("fault plan lacks strict runtime selector")
        if any(row.get("resource") != second["resource"] or
               row.get("bound_resource") != second["resource"] or
               row.get("selector_phase") != phase or
               any(row.get(key) != point.get(key) for key in
                   ("site", "node", "epoch")) for row in receipts):
            raise ValueError("fault applied to a different live-node path or actor")
        matched = next(row for row in receipts if row["type"] == "FAULT_MATCHED")
        applied = next(row for row in receipts if row["type"] == "FAULT_APPLIED")
        if (matched.get("seq", -1) >= applied.get("seq", -1) or
                not same_execution(matched, applied)):
            raise ValueError("fault receipt order or execution differs")
        candidates = [row for row in rows if row.get("type") == "SOLR15_PARENT_CANDIDATE"
                      and row.get("selector_phase") == phase and
                      row.get("resource") == second["resource"] and
                      row.get("bound_resource") == second["resource"] and
                      row.get("door_ordinal") == applied.get("door_ordinal") and
                      same_execution(row, applied) and
                      row.get("seq", -1) < matched["seq"]]
        if len(candidates) != 1:
            raise ValueError("pre-injection qualified candidate receipt missing")
        if fault.get("expected_door") == "second":
            if (not same_execution(applied, second) or
                    applied.get("door_ordinal") != second.get("door_ordinal") or
                    candidates[0]["seq"] <= second["seq"]):
                raise ValueError("first fault did not match the second leader lookup")
            first_applied = applied
        elif fault.get("expected_door") == "retry":
            if (first_applied is None or not same_execution(applied, first_applied)
                    or applied["seq"] <= first_applied["seq"] or
                    candidates[0]["seq"] <= first_applied["seq"]):
                raise ValueError("second fault is not a same-split later retry")
        else:
            raise ValueError("unrecognized expected fault door")


def attest_target_after_fault(trial: Path, plan: list[dict]) -> bool:
    """Credit target reachability only after all qualified faults on one split."""
    rows = events(trial)
    applied = [row for row in rows if row.get("type") == "FAULT_APPLIED" and
               row.get("fault_id") in {fault["fault_id"] for fault in plan}]
    if len(applied) != len(plan):
        raise ValueError("target gate requires all planned faults applied")
    last = max(applied, key=lambda row: row["seq"])
    target = SPLIT + "@536:branch:40"
    return any(row.get("type") == "TARGET_CHECK" and row.get("site") == target and
               row.get("seq", -1) > last["seq"] and same_execution(row, last)
               for row in rows)
