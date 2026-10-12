#!/usr/bin/env python3
"""Build one exact role fault from a fresh healthy SOLR-10 role trace."""

from __future__ import annotations

import argparse
from collections import deque
import gzip
import hashlib
import json
from pathlib import Path

from role_plan import ROLE, SITE, promote


TARGET = ("org.apache.solr.cloud.api.collections.MaintainRoutedAliasCmd#call"
          "(Lorg/apache/solr/common/cloud/ClusterState;"
          "Lorg/apache/solr/common/cloud/ZkNodeProps;"
          "Lorg/apache/solr/common/util/NamedList;)V@116:branch:2")


def events_from(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def observed_path(feedback: dict, door: dict, target: dict) -> list[dict]:
    rows = [row for row in feedback.get("doors", [])
            if row.get("event_id") == door.get("id")]
    if len(rows) != 1 or rows[0].get("in_closure") is not True:
        raise ValueError("selected role door is not uniquely in target closure")
    def key(event: dict) -> str:
        return json.dumps([event["node"], str(event["epoch"]), event["occurrence"]],
                          separators=(",", ":"))
    start, finish = key(door), key(target)
    edges = [edge for edge in feedback.get("closure_edges", [])
             if edge.get("certainty") == "observed"]
    frontier = deque([(start, [])])
    seen = {start}
    while frontier:
        current, path = frontier.popleft()
        if current == finish:
            return path
        for edge in edges:
            if edge.get("source") != current or edge.get("target") in seen:
                continue
            seen.add(edge["target"])
            frontier.append((edge["target"], path + [edge]))
    raise ValueError("no observed causal path from selected role door to later target")


def prepare(events: list[dict], role_ordinal: int = 16,
            feedback: dict | None = None) -> tuple[dict, dict]:
    if role_ordinal <= 0:
        raise ValueError("role ordinal must be positive")
    candidates = [(index, event) for index, event in enumerate(events)
                  if event.get("type") == "DOOR_OBSERVED"
                  and event.get("site") == SITE
                  and event.get("role") == ROLE
                  and event.get("role_ordinal") == role_ordinal]
    if len(candidates) != 1:
        raise ValueError("fresh healthy trace needs exactly one selected role door")
    index, door = candidates[0]
    after = [event for event in events[index + 1:]
             if event.get("type") == "TARGET_CHECK" and event.get("site") == TARGET]
    if not after:
        raise ValueError("selected role door has no later exact target check in healthy trace")
    physical = {"site": SITE, "node": door.get("node"),
                "epoch": door.get("epoch"), "door_ordinal": door.get("door_ordinal")}
    if (not isinstance(physical["node"], str) or physical["node"] == "unknown"
            or not isinstance(physical["epoch"], int)
            or not isinstance(physical["door_ordinal"], int)):
        raise ValueError("healthy door lacks exact physical identity")
    physical_plan = {"schema_version": 1, "faults": [{
        "fault_id": f"solr10-overseer-role-{role_ordinal}-v1",
        "fault_type": "EXCEPTION",
        "exception_class": "org.apache.zookeeper.KeeperException$ConnectionLossException",
        "point": physical,
    }]}
    role_plan = promote(physical_plan, events)
    receipt = {"selected_healthy_door_id": door.get("id"),
               "later_healthy_target_id": after[0].get("id"),
               "role_ordinal": role_ordinal,
               "healthy_physical_node": door["node"],
               "healthy_physical_epoch": door["epoch"],
               "leader_id": door["role_leader_id"]}
    if feedback is not None:
        path = observed_path(feedback, door, after[0])
        receipt["observed_causal_path"] = [
            {"kind": edge["kind"], "producer_event": edge["producer_event"],
             "consumer_event": edge["consumer_event"],
             "certainty": edge["certainty"]} for edge in path]
    return role_plan, receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--healthy-events", type=Path, required=True)
    parser.add_argument("--healthy-result", type=Path, required=True)
    parser.add_argument("--role-ordinal", type=int, default=16)
    parser.add_argument("--output-plan", type=Path, required=True)
    parser.add_argument("--output-receipt", type=Path, required=True)
    args = parser.parse_args()
    events = events_from(args.healthy_events)
    result = json.loads(args.healthy_result.read_text())
    plan, receipt = prepare(events, args.role_ordinal, result["feedback"])
    plan_bytes = (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode()
    receipt["healthy_events_sha256"] = hashlib.sha256(args.healthy_events.read_bytes()).hexdigest()
    receipt["plan_sha256"] = hashlib.sha256(plan_bytes).hexdigest()
    args.output_plan.write_bytes(plan_bytes)
    args.output_receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
