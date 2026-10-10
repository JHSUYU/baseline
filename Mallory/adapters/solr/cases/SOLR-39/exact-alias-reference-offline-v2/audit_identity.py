#!/usr/bin/env python3
"""Audit exact Aliases references against a sealed SOLR-39 healthy trace."""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path

PREFIX = "MALLORY_ALIAS_REF "
FIELD = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#aliases"
TARGET = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor"
          "#lookupShardLeadersOfCollections()Ljava/util/List;@246:branch:1")
DOOR = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
SITES = {
    "read": ("STATE_READ", "#getAliases(", "@2223:field:1"),
    "write": ("STATE_WRITE", "#setIfNewer(", "@2342:field:4"),
}


def events_from(trial: Path) -> list[dict]:
    path = trial / "events.jsonl"
    if path.is_file():
        stream = path.open("rt", encoding="utf-8")
    else:
        stream = gzip.open(trial / "events.jsonl.gz", "rt", encoding="utf-8")
    with stream:
        return [json.loads(line) for line in stream if line.strip()]


def markers_from(trial: Path) -> tuple[list[dict], int]:
    log = (trial / "junit.log").read_text(encoding="utf-8", errors="replace")
    rows = [json.loads(line.split(PREFIX, 1)[1]) for line in log.splitlines() if PREFIX in line]
    return rows, log.count("MALLORY_ALIAS_REF_TRANSFORM_ERROR")


def join_field_events(events: list[dict], markers: list[dict]) -> tuple[list[dict], dict]:
    """Pair exact field events with pre-access Java reference markers."""
    fields = defaultdict(list)
    for event in events:
        if event.get("type") not in ("STATE_READ", "STATE_WRITE") or event.get("key") != FIELD:
            continue
        key = (event.get("node"), event.get("epoch"), event.get("thread_id"),
               event.get("occurrence"), event["type"])
        fields[key].append(event)
    for group in fields.values():
        group.sort(key=lambda row: row["ts"])

    paired = []
    used = set()
    for marker in sorted(markers, key=lambda row: row["ts_ns"]):
        if marker.get("kind") not in SITES:
            continue
        kind, method, site_suffix = SITES[marker["kind"]]
        key = (marker.get("node"), marker.get("epoch"), marker.get("thread_id"),
               marker.get("context"), kind)
        group = fields.get(key, [])
        matches = [row for row in group if row["id"] not in used and
                   row["ts"] >= marker["ts_ns"] and method in row.get("site", "") and
                   row.get("site", "").endswith(site_suffix)]
        if len(matches) != 1:
            continue
        event = matches[0]
        used.add(event["id"])
        paired.append(dict(marker, field_event_id=event["id"], field_seq=event["seq"],
                           field_ts=event["ts"], field_site=event["site"],
                           field_context=event["context"], field_object=event.get("object")))

    # Core object tokens and supplemental Java reference IDs are independent
    # observations of the same owner. Require a one-to-one mapping per actor.
    objects_by_ref, refs_by_object = defaultdict(set), defaultdict(set)
    for row in paired:
        actor = (row["node"], row["epoch"])
        objects_by_ref[actor, row["owner_ref"]].add(row["field_object"])
        refs_by_object[actor, row["field_object"]].add(row["owner_ref"])
    collisions = {
        "owner_ref_to_objects": sum(len(values) > 1 for values in objects_by_ref.values()),
        "object_to_owner_refs": sum(len(values) > 1 for values in refs_by_object.values()),
    }
    if any(collisions.values()):
        raise ValueError(f"AliasesManager identity collision: {collisions}")
    return paired, collisions


def audit_rows(events: list[dict], markers: list[dict], transform_errors: int = 0) -> dict:
    paired, collisions = join_field_events(events, markers)
    writes = [row for row in paired if row["kind"] == "write"]
    reads = [row for row in paired if row["kind"] == "read"]
    doors = [row for row in events if row.get("type") == "DOOR_OBSERVED" and
             row.get("site", "").startswith(DOOR)]
    targets = [row for row in events if row.get("type") == "TARGET_CHECK" and
               row.get("branch") == TARGET]
    paths = []
    for target in targets:
        request_reads = [row for row in reads if row["node"] == target["node"] and
                         row["epoch"] == target["epoch"] and
                         row["field_context"] == target["context"] and
                         row["field_ts"] < target["ts"]]
        request_reads.sort(key=lambda row: row["field_ts"])
        for target_read in reversed(request_reads):
            earlier_reads = [row for row in request_reads if row["field_ts"] < target_read["field_ts"] and
                             row["owner_ref"] == target_read["owner_ref"] and
                             row["aliases_ref"] == target_read["aliases_ref"] and
                             row["zk_version"] == target_read["zk_version"]]
            if not earlier_reads or not target_read["aliases_ref"]:
                continue
            constructor_read = earlier_reads[-1]
            preceding = [row for row in writes if row["node"] == target["node"] and
                         row["epoch"] == target["epoch"] and
                         row["owner_ref"] == target_read["owner_ref"] and
                         row["field_ts"] < constructor_read["field_ts"]]
            if not preceding:
                continue
            preceding.sort(key=lambda row: row["field_ts"])
            write = preceding[-1]
            if (write["aliases_ref"] != target_read["aliases_ref"] or
                    write["zk_version"] != target_read["zk_version"]):
                continue
            # An intervening publication breaks the exact value path, even if
            # two sampled reads coincidentally report the same reference.
            if any(row["node"] == target["node"] and row["epoch"] == target["epoch"] and
                   row["owner_ref"] == target_read["owner_ref"] and
                   constructor_read["field_ts"] < row["field_ts"] < target["ts"]
                   for row in writes):
                continue
            parents = [row for row in doors if row["node"] == write["node"] and
                       row["epoch"] == write["epoch"] and
                       row["context"] == write["field_context"] and
                       row["thread_id"] == write["thread_id"] and row["ts"] < write["field_ts"]]
            if not parents:
                continue
            parent = max(parents, key=lambda row: row["ts"])
            paths.append({"node": target["node"], "epoch": target["epoch"],
                          "watcher_door_seq": parent["seq"],
                          "cache_write_seq": write["field_seq"],
                          "constructor_read_seq": constructor_read["field_seq"],
                          "target_read_seq": target_read["field_seq"],
                          "target_check_seq": target["seq"],
                          "owner_ref": target_read["owner_ref"],
                          "aliases_ref": target_read["aliases_ref"],
                          "zk_version": target_read["zk_version"],
                          "request_context": target["context"]})
            break
    return {"case_id": "SOLR-39", "diagnostic": "exact_aliases_reference_offline_v2",
            "status": ("transform_error" if transform_errors else
                       "no_identity_markers" if not markers else
                       "candidate_path_observed" if paths else "no_qualified_path"),
            "identity_markers": len(markers), "paired_field_events": len(paired),
            "unpaired_markers": len(markers) - len(paired),
            "owner_identity_collisions": collisions, "transform_errors": transform_errors,
            "exact_target_checks": len(targets), "candidate_paths": paths,
            "bug_confirmed": False, "fault_injection_performed": False}


def audit(trial: Path) -> dict:
    events = events_from(trial)
    markers, transform_errors = markers_from(trial)
    return audit_rows(events, markers, transform_errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.trial), sort_keys=True, indent=2))
