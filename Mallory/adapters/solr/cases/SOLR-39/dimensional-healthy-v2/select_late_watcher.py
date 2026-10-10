#!/usr/bin/env python3
"""Select only a proven in-closure, later Aliases watcher door from a healthy trial.

This emits an admission candidate, not a fault plan or a bug finding.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = (ROOT / "Mallory/dispatch/releases/"
           "4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4")
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

sys.path.insert(0, str(HERE.parent / "exact-alias-reference-offline-v2"))
from audit_identity import audit_rows, events_from, markers_from  # noqa: E402

DOOR_SITE = ("org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
             "#process(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1")
EXCEPTION = "org.apache.zookeeper.KeeperException$ConnectionLossException"


def select(trial: Path) -> dict:
    junit = json.loads((trial / "junit-receipt.json").read_text())
    if not (junit.get("status") == "passed" and junit.get("tests") == 1 and
            junit.get("failures") == 0 and junit.get("errors") == 0 and
            junit.get("skipped") == 0):
        raise ValueError("unchanged Dimensional JUnit did not pass")
    events = events_from(trial)
    markers, errors = markers_from(trial)
    result = audit_rows(events, markers, errors)
    if errors or not markers or result["unpaired_markers"] or any(
            result["owner_identity_collisions"].values()):
        raise ValueError("exact Aliases reference telemetry is incomplete")
    by_seq = {row["seq"]: row for row in events}
    if len(by_seq) != len(events):
        raise ValueError("duplicate event sequence")
    graph = OccurrenceGraph(tuple(events), reject_coarse_roots=True)
    candidates = []
    for path in result["candidate_paths"]:
        door, target = by_seq[path["watcher_door_seq"]], by_seq[path["target_check_seq"]]
        if not (door.get("type") == "DOOR_OBSERVED" and
                door.get("site") == DOOR_SITE and
                door.get("exception_class") == EXCEPTION and
                door.get("node") == path["node"] and
                door.get("epoch") == path["epoch"] and
                door.get("seq") < path["cache_write_seq"] <
                path["constructor_read_seq"] < path["target_read_seq"] <
                target["seq"]):
            continue
        earlier_targets = [prior for prior in result["candidate_paths"] if
                           prior["node"] == path["node"] and
                           prior["epoch"] == path["epoch"] and
                           prior["owner_ref"] == path["owner_ref"] and
                           prior["target_check_seq"] < door["seq"] and
                           prior["zk_version"] < path["zk_version"] and
                           prior["aliases_ref"] != path["aliases_ref"]]
        if not earlier_targets:
            continue
        witness = graph.backward_event_reachability(
            target, include_candidates=True).witness(door, require_edge=True)
        if witness is None:
            continue
        previous = max(earlier_targets, key=lambda row: row["target_check_seq"])
        candidates.append({"node": path["node"], "epoch": path["epoch"],
                           "door_site": DOOR_SITE,
                           "door_ordinal": door.get("door_ordinal"),
                           "door_occurrence": door.get("occurrence"),
                           "door_seq": door["seq"],
                           "exception_class": EXCEPTION,
                           "resource": "/aliases.json",
                           "owner_ref": path["owner_ref"],
                           "previous_aliases_ref": previous["aliases_ref"],
                           "previous_zk_version": previous["zk_version"],
                           "previous_target_check_seq": previous["target_check_seq"],
                           "published_aliases_ref": path["aliases_ref"],
                           "published_zk_version": path["zk_version"],
                           "cache_write_seq": path["cache_write_seq"],
                           "constructor_read_seq": path["constructor_read_seq"],
                           "target_read_seq": path["target_read_seq"],
                           "target_check_seq": path["target_check_seq"],
                           "graph_witness": [asdict(edge) for edge in witness]})
    return {"case_id": "SOLR-39", "mode": "healthy_candidate_selection",
            "fault_injection_performed": False,
            "exact_target_checks": result["exact_target_checks"],
            "late_in_closure_candidates": sorted(
                candidates, key=lambda row: (row["target_check_seq"], row["door_seq"])),
            "status": "candidate_observed" if candidates else "no_qualified_late_door"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial", type=Path)
    args = parser.parse_args()
    print(json.dumps(select(args.trial), indent=2, sort_keys=True))
