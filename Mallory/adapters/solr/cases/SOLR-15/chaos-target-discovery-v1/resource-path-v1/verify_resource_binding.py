#!/usr/bin/env python3
"""Offline SOLR-15 parent-live-node path and actor gate for native-door plans."""

import argparse
import json
import re
from pathlib import Path

REGION = "org.apache.solr.cloud.api.collections.SplitShardCmd#split(Lorg/apache/solr/common/cloud/ClusterState;Lorg/apache/solr/common/cloud/ZkNodeProps;Lorg/apache/solr/common/util/NamedList;)Z"
FIRST = REGION + "@164:door:2"
SECOND = REGION + "@523:door:3"
NATIVE = "org.apache.solr.common.cloud.SolrZkClient#lambda$exists$2(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)Lorg/apache/zookeeper/data/Stat;@301:door:1"
LIVE_NODE = re.compile(r"^/live_nodes/[^/]+$")
ACTOR = re.compile(r"^node[1-9][0-9]*$")


def _must(condition, reason):
    if not condition:
        raise ValueError(reason)


def _same_context(row, anchor):
    return (row.get("node") == anchor.get("node")
            and row.get("epoch") == anchor.get("epoch")
            and row.get("occurrence") == anchor.get("occurrence")
            and row.get("thread_id") == anchor.get("thread_id")
            and row.get("region") == REGION)


def verify(events, plan):
    """Return one bound parent path; fail closed on ambiguous or mismatched plans."""
    _must(not any(e.get("type") == "TRACE_TRUNCATED" for e in events),
          "incomplete_event_trace")
    faults = plan.get("faults", [])
    _must(len(faults) == 1, "one_native_fault_required")
    fault = faults[0]
    point = fault.get("point") or {}
    _must(point.get("site") == NATIVE, "wrong_native_door_site")
    _must(fault.get("exception_class") ==
          "org.apache.zookeeper.KeeperException$ConnectionLossException",
          "wrong_native_exception_class")
    _must(ACTOR.fullmatch(str(point.get("node", ""))) is not None,
          "unnamed_physical_actor")
    _must(type(point.get("epoch")) is int and
          isinstance(point.get("occurrence"), str) and point["occurrence"] and
          type(point.get("door_ordinal")) is int and point["door_ordinal"] > 0,
          "missing_epoch_occurrence_or_door_ordinal")
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED"]
    selected = [e for e in doors if e.get("site") == NATIVE
                and e.get("node") == point["node"]
                and e.get("epoch") == point["epoch"]
                and e.get("door_ordinal") == point["door_ordinal"]]
    _must(len(selected) == 1, "selected_native_door_missing_or_ambiguous")
    chosen = selected[0]
    _must(type(chosen.get("seq")) is int and
          type(chosen.get("thread_id")) is int and
          chosen.get("region") == REGION and
          isinstance(chosen.get("occurrence"), str),
          "native_door_lacks_split_context")
    _must(point["occurrence"] == chosen["occurrence"], "wrong_occurrence")
    applied = [e for e in events if e.get("type") == "FAULT_APPLIED"
               and e.get("site") == NATIVE
               and e.get("node") == chosen["node"]
               and e.get("epoch") == chosen["epoch"]
               and e.get("door_ordinal") == chosen["door_ordinal"]]
    _must(len(applied) == 1 and _same_context(applied[0], chosen)
          and applied[0].get("resource") == chosen.get("resource")
          and applied[0].get("exception_class") == fault["exception_class"]
          and type(applied[0].get("seq")) is int
          and applied[0]["seq"] > chosen["seq"],
          "applied_fault_not_bound_to_selected_door")
    context = sorted((e for e in doors if _same_context(e, chosen)
                      and type(e.get("seq")) is int), key=lambda e: e["seq"])
    first_calls = [e for e in context if e.get("site") == FIRST
                   and e["seq"] < chosen["seq"]]
    second_calls = [e for e in context if e.get("site") == SECOND
                    and e["seq"] < chosen["seq"]]
    _must(len(first_calls) == 1 and len(second_calls) == 1,
          "first_or_second_parent_lookup_missing_or_ambiguous")
    first_call, second_call = first_calls[0], second_calls[0]
    _must(first_call["seq"] < second_call["seq"], "parent_lookup_order_wrong")
    initial = [e for e in context if e.get("site") == NATIVE
               and first_call["seq"] < e["seq"] < second_call["seq"]]
    later = [e for e in context if e.get("site") == NATIVE
             and second_call["seq"] < e["seq"] <= chosen["seq"]]
    _must(initial and later and later[-1] is chosen,
          "native_attempt_not_bound_to_second_lookup")
    paths = {e.get("resource") for e in initial + later}
    _must(len(paths) == 1, "native_attempts_disagree_on_parent_resource")
    path = next(iter(paths))
    _must(isinstance(path, str) and LIVE_NODE.fullmatch(path) is not None,
          "resource_not_exact_live_node_path")
    if point.get("resource") is not None:
        _must(point["resource"] == path, "plan_resource_differs_from_observation")
    return {"status": "passed", "actor": chosen["node"],
            "occurrence": chosen["occurrence"], "resource": path,
            "selected_door_ordinal": chosen["door_ordinal"],
            "applied_fault_seq": applied[0]["seq"],
            "first_native_attempts": len(initial),
            "second_native_attempts": len(later),
            "evidence_seq": [first_call["seq"], initial[0]["seq"],
                             second_call["seq"], chosen["seq"]]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    events = [json.loads(line) for line in args.events.read_text().splitlines() if line]
    result = verify(events, json.loads(args.plan.read_text()))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
