#!/usr/bin/env python3
"""Case-local proof of a real watcher I/O to SOLR-37's range guard."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

PUBLISHED = "solr37:ZkStateReader.constructState:publishedClusterState"
CONSUMED = "solr37:DistributedZkUpdateProcessor.clusterState:consumePublishedState"
ASSIGNED = "solr37:DistributedZkUpdateProcessor.clusterState:assigned"
GUARD_READ = "solr37:DistributedZkUpdateProcessor.doDefensiveChecks:994"


def evaluate(events: tuple[dict, ...]) -> dict:
    graph = OccurrenceGraph(events, reject_coarse_roots=True)
    by_id = {event.get("id"): event for event in events}
    targets = [event for event in events
               if event.get("type") == "TARGET_CHECK"
               and "DistributedZkUpdateProcessor#doDefensiveChecks" in event.get("site", "")
               and "@994:" in event.get("site", "")]
    doors = [event for event in events
             if event.get("type") == "DOOR_OBSERVED"
             and "ZkStateReader#fetchCollectionState" in event.get("site", "")
             and "@1641:" in event.get("site", "")]
    witnesses = []
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
    return {"target_count": len(targets), "door_count": len(doors),
            "observed_state_edges": sum(edge.kind == "state" for edge in graph.edges),
            "candidate_state_edges": sum(edge.kind == "state"
                                         for edge in graph.candidate_edges),
            "strict_witness_count": len(witnesses),
            "strict_witness_sample": witnesses[:8],
            "eligible_for_fault_pilot": bool(witnesses)}


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
