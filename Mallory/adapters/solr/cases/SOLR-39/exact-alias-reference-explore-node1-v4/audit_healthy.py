#!/usr/bin/env python3
"""Offline admission for the postpublication, outside-closure SOLR-39 door."""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

sys.path.insert(0, str(HERE.parent / "exact-alias-reference-offline-v2"))
from audit_identity import FIELD, TARGET, join_field_events, PREFIX  # noqa: E402

ARCHIVE = ROOT / "data/mallory/evidence_archives/SOLR-39-aliasref-healthy-node1-v1.tar.gz"
STREAM = "SOLR-39-aliasref-healthy-node1-v1/trials/r0000/"
PROCESS = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assess(events: list[dict], markers: list[dict], selection: dict) -> dict:
    by_seq = {row["seq"]: row for row in events}
    if len(by_seq) != len(events):
        raise ValueError("duplicate healthy sequence")
    paired, collisions = join_field_events(events, markers)
    if len(paired) != len(markers) or any(collisions.values()):
        raise ValueError("incomplete or colliding exact-reference pairings")
    fields = {row["field_seq"]: row for row in paired}
    names = ("cache_write", "watcher_manager_read", "watcher_door", "preconstructor_read",
             "constructor_read", "target_read", "target_check")
    rows = [by_seq[selection[f"healthy_{name}_seq"]] for name in names]
    write, manager, door, initial_read, constructor, target_read, target = rows
    if [row["seq"] for row in rows] != sorted(row["seq"] for row in rows):
        raise ValueError("postpublication sequence order invalid")
    if not (write["type"] == "STATE_WRITE" and write.get("key") == FIELD and
            write.get("node") == manager.get("node") == door.get("node") ==
            initial_read.get("node") == constructor.get("node") ==
            target_read.get("node") == target.get("node") == "node1" and
            all(row.get("epoch") == 0 for row in rows) and
            write.get("object") == manager.get("object") == initial_read.get("object") ==
            constructor.get("object") == target_read.get("object") ==
            selection["healthy_manager_object"] and
            manager.get("type") == "STATE_READ" and
            manager.get("key", "").endswith("#this$0") and
            manager.get("site", "").startswith(PROCESS) and
            door.get("type") == "DOOR_OBSERVED" and
            door.get("site", "").startswith(PROCESS) and
            door.get("door_ordinal") == 2 and
            door.get("exception_class") ==
            "org.apache.zookeeper.KeeperException$ConnectionLossException" and
            manager.get("thread_id") == door.get("thread_id") and
            manager.get("occurrence") == door.get("occurrence") and
            target.get("type") == "TARGET_CHECK" and target.get("branch") == TARGET and
            all(row.get("type") == "STATE_READ" and row.get("key") == FIELD
                for row in (initial_read, constructor, target_read)) and
            initial_read.get("thread_id") == constructor.get("thread_id") ==
            target_read.get("thread_id") == target.get("thread_id") and
            initial_read.get("context") == constructor.get("context") ==
            target_read.get("context") == target.get("context")):
        raise ValueError("healthy actor, epoch, manager, door or request identity invalid")
    w = fields[write["seq"]]
    for row in (w, fields[initial_read["seq"]], fields[constructor["seq"]],
                fields[target_read["seq"]]):
        if (row["owner_ref"] != selection["healthy_manager_ref"] or
                row["aliases_ref"] != selection["healthy_aliases_ref"] or
                row["zk_version"] != selection["healthy_zk_version"]):
            raise ValueError("healthy exact Aliases reference/version changed")
    if any(row["kind"] == "write" and row["node"] == "node1" and
           row["epoch"] == 0 and row["owner_ref"] == w["owner_ref"] and
           write["ts"] < row["field_ts"] < target["ts"] for row in paired):
        raise ValueError("intervening healthy cache publication")
    graph = OccurrenceGraph(tuple(events), reject_coarse_roots=True)
    path = graph.backward_event_reachability(target, include_candidates=True).witness(door)
    if path is not None or selection["observed_event_time_path_from_door"] is not False:
        raise ValueError("door has graph witness; outside-closure label would be false")
    return {"case_id": "SOLR-39", "admission": "outside_closure_exploratory_only",
            "exact_reference_pairings": len(paired), "actor": "node1", "epoch": 0,
            "manager_object": manager["object"], "owner_ref": w["owner_ref"],
            "aliases_ref": w["aliases_ref"], "zk_version": w["zk_version"],
            "cache_write_seq": write["seq"], "watcher_door_seq": door["seq"],
            "target_check_seq": target["seq"], "door_to_target_graph_witness": False}


def sealed_assessment(selection: dict) -> dict:
    if sha(ARCHIVE) != selection["healthy_archive_sha256"]:
        raise ValueError("sealed healthy archive SHA changed")
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        events = [json.loads(line) for line in gzip.decompress(
            archive.extractfile(STREAM + "events.jsonl.gz").read()).splitlines() if line]
        log = archive.extractfile(STREAM + "junit.log").read().decode("utf-8", "replace")
    markers = [json.loads(line.split(PREFIX, 1)[1]) for line in log.splitlines() if PREFIX in line]
    if "MALLORY_ALIAS_REF_TRANSFORM_ERROR" in log:
        raise ValueError("healthy exact-reference transform error")
    return assess(events, markers, selection)


if __name__ == "__main__":
    selection = json.loads((HERE / "fault-plan.json").read_text())["selection"]
    print(json.dumps(sealed_assessment(selection), indent=2, sort_keys=True))
