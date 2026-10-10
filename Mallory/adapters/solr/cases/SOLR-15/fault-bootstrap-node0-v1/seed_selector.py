"""Select the two observed parent-live-node native doors; no target claim here."""

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
    return all(left.get(key) == right.get(key) for key in
               ("node", "epoch", "occurrence", "thread", "context"))


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
                            plan[0]["point"]["site"] != NATIVE):
            continue
        selected = queue.pop(index)
        selected["faults"][-1]["expected_resource_role"] = "parent_leader_znode"
        selected["faults"][-1]["expected_door"] = "second" if faults == 1 else "retry"
        selected["selection_reason"] = ("same_path_first_lookup_fault" if faults == 1
                                        else "same_path_retry_fault")
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
        if any(row.get("resource") != second["resource"] or
               any(row.get(key) != fault["point"].get(key) for key in
                   ("site", "node", "epoch", "door_ordinal")) for row in receipts):
            raise ValueError("fault applied to a different live-node path or actor")
        applied = next(row for row in receipts if row["type"] == "FAULT_APPLIED")
        if fault.get("expected_door") == "second":
            if (not same_execution(applied, second) or
                    applied.get("door_ordinal") != second.get("door_ordinal")):
                raise ValueError("first fault did not match the second leader lookup")
            first_applied = applied
        elif fault.get("expected_door") == "retry":
            if (first_applied is None or not same_execution(applied, first_applied)
                    or applied["seq"] <= first_applied["seq"]):
                raise ValueError("second fault is not a same-split later retry")
        else:
            raise ValueError("unrecognized expected fault door")
