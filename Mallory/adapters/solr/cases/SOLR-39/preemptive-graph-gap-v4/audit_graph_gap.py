#!/usr/bin/env python3
"""Offline, case-local event-time graph repair for sealed SOLR-39 healthy trace.

The overlay accepts only a balanced nested getter return and a field value
whose exact Java reference was observed at both the volatile write and read.
It does not edit the shared graph, raw trace, or target system.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

sys.path.insert(0, str(HERE.parent / "exact-alias-reference-offline-v2"))
from audit_identity import audit_rows, events_from, join_field_events, markers_from  # noqa: E402

TRIAL = ROOT / "data/mallory/pilot_observations/SOLR-39-preemptive-healthy-node1-v3/trials/r0000"
RECEIPT = ROOT / "data/mallory/evidence_archives/SOLR-39-preemptive-healthy-node1-v3.receipt.json"
SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4/solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java")
TARGET_SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4/solr/core/src/java/org/apache/solr/update/processor/RoutedAliasUpdateProcessor.java")
GETTER = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#getAliases()Lorg/apache/solr/common/cloud/Aliases;"
TARGET = "org.apache.solr.update.processor.RoutedAliasUpdateProcessor#lookupShardLeadersOfCollections()Ljava/util/List;"
DOOR_SITE = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_seal(trial: Path = TRIAL) -> None:
    receipt = json.loads(RECEIPT.read_text())
    if not (receipt["healthy_seed_valid"] and receipt["junit_1_0_0"] and
            receipt["exact_target_checks"] == 11 and
            sha(trial / "events.jsonl.gz") == receipt["trace_gzip_sha256"]):
        raise ValueError("sealed healthy trace identity changed")
    junit = json.loads((trial / "junit-receipt.json").read_text())
    if not (junit["status"] == "passed" and junit["tests"] == 1 and
            junit["failures"] == junit["errors"] == junit["skipped"] == 0):
        raise ValueError("healthy JUnit gate failed")
    if (sha(SOURCE) != "83e14eadfcc4896ff05f9ac77706fdb683e0c181caeee21802f8861f68ac373d" or
            sha(TARGET_SOURCE) != "6ed4337435f68d00ba85d7b05eeb324cea9a14298c34cabd137756d682f24590"):
        raise ValueError("source revision changed")
    pins = {
        HERE.parent / "exact-alias-reference-node1-v1/src/edu/uva/liftlab/mallory/solr/aliasref/AliasValueTransformer.java":
            "42f1d94ba4f4e39f9ef13d7f581a2e22bf87c7a8dd5223e2e1b1e5bb3bb4818f",
        HERE.parent / "exact-alias-reference-node1-v1/src/edu/uva/liftlab/mallory/solr/aliasref/AliasValueTrace.java":
            "920249faea6a96269009224229fec8a71e5439ceb637fc0fb3c662c4c3f941f0",
        HERE.parent / "exact-alias-reference-offline-v2/audit_identity.py":
            "8d40095d2878535c2b9ddd6b3ada0cb33ba60bd4aefe3af4705e1a27b0129bfc",
        RELEASE / "Mallory/core/graph.py":
            "b3375c52d8f69f52420b3e374cfc9c6a6aeec0d9f7182df63284d52b0140477d",
    }
    if any(sha(path) != expected for path, expected in pins.items()):
        raise ValueError("instrumentation or graph source pin changed")


def validate_return(rows: list[dict], path: dict) -> tuple[dict, dict]:
    """Find child REGION_EXIT -> first parent event on one JVM thread.

    The getter must be a directly nested call in the exact target occurrence;
    its return and caller continuation must be balanced and in program order.
    """
    by_seq = {row["seq"]: row for row in rows}
    if len(by_seq) != len(rows):
        raise ValueError("duplicate sequence")
    read, target = by_seq[path["target_read_seq"]], by_seq[path["target_check_seq"]]
    identity = (read.get("node"), read.get("epoch"), read.get("thread_id"))
    if (read.get("type") != "STATE_READ" or read.get("region") != GETTER or
            target.get("type") != "TARGET_CHECK" or target.get("region") != TARGET or
            identity != (target.get("node"), target.get("epoch"), target.get("thread_id")) or
            not isinstance(identity[2], int) or isinstance(identity[2], bool) or
            not read["seq"] < target["seq"]):
        raise ValueError("target getter/read identity mismatch")
    thread_rows = [row for row in rows if
                   (row.get("node"), row.get("epoch"), row.get("thread_id")) == identity]
    # Require a direct child entry linked to this exact target occurrence.
    entries = [row for row in thread_rows if row.get("type") == "REGION_ENTER" and
               row.get("occurrence") == read.get("occurrence") and
               row.get("parent_id") == target.get("occurrence") and row["seq"] < read["seq"]]
    if len(entries) != 1:
        raise ValueError("getter does not enter under target")
    enter = entries[0]
    target_entries = [row for row in thread_rows if row.get("type") == "REGION_ENTER" and
                      row.get("occurrence") == target.get("occurrence") and row["seq"] < enter["seq"]]
    if len(target_entries) != 1:
        raise ValueError("target occurrence entry ambiguous")
    target_enter = target_entries[0]
    # Validate the full local nested stack from target entry through check.
    stack = []
    exit_row = None
    continuation = None
    for row in thread_rows:
        if not target_enter["seq"] <= row["seq"] <= target["seq"]:
            continue
        kind, occurrence = row.get("type"), row.get("occurrence")
        if kind == "REGION_ENTER":
            if stack and row.get("parent_id") != stack[-1]:
                raise ValueError("unbalanced nested parent")
            stack.append(occurrence)
        elif kind == "REGION_EXIT":
            if not stack or stack[-1] != occurrence:
                raise ValueError("unbalanced nested exit")
            if occurrence == read["occurrence"]:
                if exit_row is not None or row["seq"] <= read["seq"]:
                    raise ValueError("getter exit missing or repeated")
                exit_row = row
            stack.pop()
        elif exit_row is not None and continuation is None and row["seq"] > exit_row["seq"]:
            continuation = row
        if row["seq"] == target["seq"] and stack != [target["occurrence"]]:
            raise ValueError("target not active at check")
    if (exit_row is None or continuation is None or
            continuation.get("occurrence") != target.get("occurrence") or
            continuation.get("type") not in {"STATE_READ", "TARGET_CHECK", "DOOR_OBSERVED"} or
            not read["seq"] < exit_row["seq"] < continuation["seq"] <= target["seq"]):
        raise ValueError("getter return has no same-thread caller continuation")
    return exit_row, continuation


def validate_value(rows: list[dict], paired: list[dict], path: dict) -> tuple[dict, dict]:
    by_seq = {row["seq"]: row for row in rows}
    write, read = by_seq[path["cache_write_seq"]], by_seq[path["target_read_seq"]]
    markers = {row["field_seq"]: row for row in paired}
    wm, rm = markers.get(write["seq"]), markers.get(read["seq"])
    if wm is None or rm is None:
        raise ValueError("exact field marker missing")
    if (wm["kind"] != "write" or rm["kind"] != "read" or
            (wm["node"], wm["epoch"], wm["owner_ref"], wm["aliases_ref"], wm["zk_version"]) !=
            (rm["node"], rm["epoch"], rm["owner_ref"], rm["aliases_ref"], rm["zk_version"]) or
            wm["aliases_ref"] == 0 or wm["zk_version"] < 0 or
            write.get("object") != read.get("object") or
            write.get("node") != read.get("node") or write.get("epoch") != read.get("epoch") or
            not write["seq"] < read["seq"] or
            wm["field_object"] != rm["field_object"]):
        raise ValueError("writer and reader did not observe the same Aliases reference")
    if any(row["kind"] == "write" and row["node"] == rm["node"] and
           row["epoch"] == rm["epoch"] and row["owner_ref"] == rm["owner_ref"] and
           write["seq"] < row["field_seq"] < read["seq"] for row in paired):
        raise ValueError("intervening aliases publication")
    return write, read


def validate_postfault_retained_reference(rows: list[dict], paired: list[dict],
                                          path: dict, fault: dict,
                                          manager_object: str) -> tuple[dict, dict]:
    """Require a *prior* publication feeding a later target on the faulted manager.

    This is only one component of a fault-trial audit. The caller must first
    attest exact fault match/application and absence of a write in its watcher
    occurrence; this function cannot infer a negative causal edge.
    """
    write, read = validate_value(rows, paired, path)
    validate_return(rows, path)
    target = next(row for row in rows if row["seq"] == path["target_check_seq"])
    if (not isinstance(manager_object, str) or not manager_object or
            write.get("object") != manager_object or read.get("object") != manager_object or
            (write.get("node"), write.get("epoch")) !=
            (fault.get("node"), fault.get("epoch")) or
            not write["seq"] < fault.get("seq", -1) < read["seq"] < target["seq"]):
        raise ValueError("postfault target lacks prior reference on bound manager")
    return write, read


def qualify(trial: Path = TRIAL) -> dict:
    validate_seal(trial)
    rows = events_from(trial)
    markers, errors = markers_from(trial)
    paired, collisions = join_field_events(rows, markers)
    if (errors or len(markers) != 1250 or len(paired) != len(markers) or
            any(collisions.values())):
        raise ValueError("exact-reference marker gate failed")
    audit = audit_rows(rows, markers, errors)
    if audit["exact_target_checks"] != 11 or len(audit["candidate_paths"]) != 5:
        raise ValueError("candidate path count changed")
    by_seq = {row["seq"]: row for row in rows}
    graph = OccurrenceGraph(tuple(rows), reject_coarse_roots=True)
    qualified = []
    for path in audit["candidate_paths"]:
        door = by_seq[path["watcher_door_seq"]]
        if (door.get("type") != "DOOR_OBSERVED" or door.get("site") != DOOR_SITE or
                door.get("node") != path["node"] or door.get("epoch") != path["epoch"] or
                door["seq"] >= path["cache_write_seq"]):
            raise ValueError("watcher door identity mismatch")
        write, read = validate_value(rows, paired, path)
        exit_row, continuation = validate_return(rows, path)
        if graph.event_path(door, by_seq[path["target_check_seq"]],
                            include_candidates=True, require_edge=True) is not None:
            raise ValueError("baseline already has this event-time witness")
        # The existing graph must already prove the watcher->writer prefix.
        if graph.event_path(door, write, require_edge=True) is None:
            raise ValueError("watcher->publication program-order prefix absent")
        graph._add(write, read, "state_exact_ref", "same_volatile_owner_and_java_aliases_reference")
        graph._add(exit_row, continuation, "program_return", "balanced_same_thread_direct_nested_return")
        graph._time_cache.clear()
        witness = graph.event_path(door, by_seq[path["target_check_seq"]],
                                   include_candidates=False, require_edge=True)
        if witness is None or not {"program_order", "state_exact_ref", "program_return"} <= {
                edge.kind for edge in witness}:
            raise ValueError("observed event-time path absent after exact overlay")
        qualified.append({**path, "getter_exit_seq": exit_row["seq"],
                          "caller_continuation_seq": continuation["seq"],
                          "observed_witness": [asdict(edge) for edge in witness]})
    late = []
    for item in qualified:
        earlier = [x for x in qualified if x["node"] == item["node"] and
                   x["epoch"] == item["epoch"] and x["owner_ref"] == item["owner_ref"] and
                   x["target_check_seq"] < item["watcher_door_seq"] and
                   x["zk_version"] < item["zk_version"] and
                   x["aliases_ref"] != item["aliases_ref"]]
        if earlier:
            late.append(item)
    return {"case_id": "SOLR-39", "kind": "sealed_healthy_case_local_graph_overlay",
            "fault_injection_performed": False, "new_bug_confirmed": False,
            "raw_events_sha256": sha(trial / "events.jsonl.gz"),
            "exact_target_checks": 11, "paired_exact_ref_markers": len(paired),
            "qualified_event_time_paths": qualified, "late_qualified_paths": late,
            "status": "strict_late_healthy_doors_observed" if late else "no_strict_late_door"}


if __name__ == "__main__":
    print(json.dumps(qualify(), indent=2, sort_keys=True))
