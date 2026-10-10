#!/usr/bin/env python3
"""Case-local proof of a real watcher I/O to SOLR-37's range guard."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

PUBLISHED = "solr37:ZkStateReader.constructState:publishedClusterState"
CONSUMED = "solr37:DistributedZkUpdateProcessor.clusterState:consumePublishedState"
ASSIGNED = "solr37:DistributedZkUpdateProcessor.clusterState:assigned"
GUARD_READ = "solr37:DistributedZkUpdateProcessor.doDefensiveChecks:994"
DOOR = ("org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState"
        "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Ljava/lang/String;)"
        "Lorg/apache/solr/common/cloud/DocCollection;@1641:door:solr37-qualified")
RESOURCE = "/collections/collection1/state.json"
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"
REGION = ("org.apache.solr.common.cloud.ZkStateReader$StateWatcher#refreshAndWatch"
          "(Lorg/apache/zookeeper/Watcher$Event$EventType;)V")


def evaluate(events: tuple[dict, ...], *, min_target_seq: int = -1,
             actor: tuple[str, int] | None = None,
             reader_ref: str | None = None) -> dict:
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    by_id = {event.get("id"): event for event in events}
    targets = [event for event in events
               if event.get("type") == "TARGET_CHECK"
               and "DistributedZkUpdateProcessor#doDefensiveChecks" in event.get("site", "")
               and "@994:" in event.get("site", "")
               and event.get("seq", -1) > min_target_seq
               and (actor is None or (event.get("node"), event.get("epoch")) == actor)]
    doors = [event for event in events
             if event.get("type") == "DOOR_OBSERVED"
             and event.get("site") == DOOR
             and event.get("resource") == RESOURCE
             and event.get("region") == REGION
             and isinstance(event.get("node"), str)
             and re.fullmatch(r"shard-[0-9]+", event["node"])
             and isinstance(event.get("epoch"), int)
             and event["epoch"] >= 0
             and event.get("occurrence_kind") == "watcher_region"
             and event.get("reader_ref")
             and (reader_ref is None or event.get("reader_ref") == reader_ref)
             and isinstance(event.get("state_version"), int)]
    witnesses = []
    qualified_points = set()
    for target in targets:
        if target.get("node") in (None, "", "unknown"):
            continue
        for door in doors:
            if (door.get("node"), door.get("epoch")) != (
                    target.get("node"), target.get("epoch")):
                continue
            path = graph.event_path(door, target, include_candidates=False,
                                    require_edge=True)
            if not path:
                continue
            state_links = [(by_id.get(edge.producer_event, {}).get("site"),
                            by_id.get(edge.consumer_event, {}).get("site"))
                           for edge in path if edge.kind == "state"
                           and edge.certainty == "observed"]
            if ((PUBLISHED, CONSUMED) not in state_links or
                    (ASSIGNED, GUARD_READ) not in state_links):
                continue
            witnesses.append({"door_event": door["id"],
                              "target_event": target["id"],
                              "state_edges": [list(link) for link in state_links],
                              "node": target["node"], "epoch": target["epoch"]})
            qualified_points.add((door["node"], door["epoch"], door["door_ordinal"]))
    return {"target_count": len(targets), "door_count": len(doors),
            "observed_state_edges": sum(edge.kind == "state" for edge in graph.edges),
            "candidate_state_edges": sum(edge.kind == "state"
                                         for edge in graph.candidate_edges),
            "strict_witness_count": len(witnesses),
            "strict_witness_sample": witnesses[:8],
            "qualified_points": [dict(node=node, epoch=epoch, door_ordinal=ordinal)
                                 for node, epoch, ordinal in sorted(qualified_points)],
            "eligible_for_fault_pilot": bool(witnesses)}


def audit_trial(events: tuple[dict, ...], plan: list[dict]) -> dict:
    """Admit a trial only with exact receipts and a named post-fault @994 check."""
    if not plan:
        healthy = evaluate(events)
        return {**healthy, "valid": healthy["eligible_for_fault_pilot"],
                "reason": "strict_healthy_path" if healthy["eligible_for_fault_pilot"]
                else "missing_strict_healthy_path"}
    if len(plan) > 3:
        return {"valid": False, "reason": "too_many_faults"}
    by_type = {kind: [event for event in events if event.get("type") == kind]
               for kind in ("DOOR_OBSERVED", "FAULT_MATCHED", "FAULT_APPLIED", "TARGET_CHECK")}
    order = []
    witnesses = []
    planned_actor = None
    for fault in plan:
        point = fault.get("point", {})
        actor = (point.get("node"), point.get("epoch"))
        if (not isinstance(actor[0], str) or not re.fullmatch(r"shard-[0-9]+", actor[0])
                or not isinstance(actor[1], int) or actor[1] < 0):
            return {"valid": False, "reason": "unqualified_actor"}
        if planned_actor is None:
            planned_actor = actor
        elif actor != planned_actor:
            return {"valid": False, "reason": "cross_actor_fault_sequence"}
        required = {"site": DOOR, "node": actor[0], "epoch": actor[1],
                    "resource": RESOURCE, "region": REGION,
                    "occurrence_kind": "watcher_region"}
        if (any(point.get(key) != value for key, value in required.items())
                or not isinstance(point.get("door_ordinal"), int)
                or point.get("door_ordinal") <= 0
                or fault.get("fault_type") != "EXCEPTION"
                or fault.get("exception_class") != EXCEPTION):
            return {"valid": False, "reason": "unqualified_plan"}
        fid = fault.get("fault_id")
        matched = [row for row in by_type["FAULT_MATCHED"] if row.get("fault_id") == fid]
        applied = [row for row in by_type["FAULT_APPLIED"] if row.get("fault_id") == fid]
        if len(matched) != 1 or len(applied) != 1:
            return {"valid": False, "reason": "fault_receipt_missing_or_duplicated"}
        match, apply = matched[0], applied[0]
        actual_fields = ("site", "node", "epoch", "door_ordinal", "resource", "region",
                         "occurrence_kind", "occurrence", "reader_ref", "state_version")
        if any(match.get(key) != apply.get(key) for key in actual_fields):
            return {"valid": False, "reason": "fault_receipt_identity_drift"}
        if (match.get("fault_type") != "EXCEPTION" or
                apply.get("fault_type") != "EXCEPTION" or
                match.get("exception_class") != EXCEPTION or
                apply.get("exception_class") != EXCEPTION):
            return {"valid": False, "reason": "fault_receipt_type_mismatch"}
        if any(match.get(key) != value for key, value in required.items()):
            return {"valid": False, "reason": "fault_receipt_unqualified"}
        if match.get("door_ordinal") != point["door_ordinal"]:
            return {"valid": False, "reason": "fault_ordinal_mismatch"}
        if not isinstance(match.get("occurrence"), str) or not match["occurrence"]:
            return {"valid": False, "reason": "missing_watcher_occurrence"}
        if point.get("occurrence") is not None and match["occurrence"] != point["occurrence"]:
            return {"valid": False, "reason": "fault_occurrence_mismatch"}
        if not match.get("reader_ref") or not isinstance(match.get("state_version"), int):
            return {"valid": False, "reason": "missing_exact_reference_receipt"}
        observed = [row for row in by_type["DOOR_OBSERVED"]
                    if all(row.get(key) == match.get(key) for key in actual_fields)]
        if len(observed) != 1 or not (
                observed[0].get("seq", -1) < match.get("seq", -1) < apply.get("seq", -1)):
            return {"valid": False, "reason": "door_match_apply_order_or_identity"}
        if observed[0].get("exception_class") != EXCEPTION:
            return {"valid": False, "reason": "door_exception_type_mismatch"}
        order.append(apply["seq"])
        witnesses.append({"fault_id": fid, "door_event": observed[0].get("id"),
                          "matched_event": match.get("id"), "applied_event": apply.get("id"),
                          "reader_ref": apply["reader_ref"],
                          "state_version": apply["state_version"],
                          "occurrence": apply["occurrence"]})
    if order != sorted(order) or len(set(order)) != len(order):
        return {"valid": False, "reason": "fault_order_invalid"}
    targets = [row for row in by_type["TARGET_CHECK"]
               if (row.get("node"), row.get("epoch")) == planned_actor
               and "DistributedZkUpdateProcessor#doDefensiveChecks" in row.get("site", "")
               and "@994:" in row.get("site", "")
               and row.get("seq", -1) > order[-1]]
    if not targets:
        return {"valid": False, "reason": "target_not_reached_after_last_fault",
                "fault_receipts": witnesses}
    return {"valid": True, "reason": "strict_fault_and_postfault_target",
            "fault_receipts": witnesses,
            "postfault_target_count": len(targets),
            "first_postfault_target_event": targets[0].get("id")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path, help="raw .jsonl or archived .jsonl.gz")
    args = parser.parse_args()
    open_trace = gzip.open if args.events.suffix == ".gz" else open
    with open_trace(args.events, "rt", encoding="utf-8") as source:
        events = tuple(json.loads(line) for line in source if line.strip())
    print(json.dumps(evaluate(events), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
