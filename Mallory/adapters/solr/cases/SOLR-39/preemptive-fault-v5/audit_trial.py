#!/usr/bin/env python3
"""Strict SOLR-39 fault and retained prior-reference path audit."""

from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(HERE.parent / "exact-alias-reference-offline-v2"))
from audit_identity import (FIELD, TARGET, audit_rows as reference_audit,
                            events_from, join_field_events, markers_from)  # noqa: E402
sys.path.insert(0, str(HERE.parent / "preemptive-graph-gap-v4"))
from audit_graph_gap import (validate_postfault_retained_reference,
                             validate_return)  # noqa: E402
RELEASE = ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
sys.path.insert(0, str(RELEASE))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

GATE = "SOLR39_PREFAULT_RESOURCE_MANAGER"
RESOURCE = "/aliases.json"
THROW = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor"
         "#lookupShardLeadersOfCollections()Ljava/util/List;@247:throw:1")
EXCEPTION = "org.apache.solr.common.SolrException"
SET_IF_NEWER = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#setIfNewer"


def _matches(row: dict, fault: dict) -> bool:
    point = fault["point"]
    return all(row.get(key) == point[key] for key in
               ("site", "node", "epoch", "door_ordinal"))


def _injected_watcher_wrote(rows: list[dict], applied: dict, manager: str) -> bool:
    """Find nested setIfNewer writes in the exact faulted process occurrence."""
    children = {row.get("occurrence") for row in rows
                if row.get("type") == "REGION_ENTER" and
                row.get("parent_id") == applied.get("occurrence") and
                row.get("region", "").startswith(SET_IF_NEWER) and
                row.get("node") == applied.get("node") and
                row.get("epoch") == applied.get("epoch") and
                row.get("thread_id") == applied.get("thread_id") and
                row["seq"] > applied["seq"]}
    return any(row.get("type") == "STATE_WRITE" and row.get("key") == FIELD and
               row.get("object") == manager and row.get("occurrence") in children
               for row in rows)


def audit_rows(rows: list[dict], markers: list[dict], result: dict,
               plan: list[dict], transform_errors: int = 0) -> dict:
    output = {"case_id": "SOLR-39", "kind": "preemptive_v5_strict_fault_audit",
              "valid": False, "qualification": "unexamined", "faults": [],
              "retained_reference_paths": [], "exact_target_exception_candidate": False,
              "new_bug_confirmed": False, "novelty_eligible": False}
    if result.get("site_catalog_validation", {}).get("valid") is not True:
        output["qualification"] = "target_class_binding_invalid"
        return output
    if not plan or len(plan) > 3 or result.get("plan") != plan:
        output["qualification"] = "plan_identity_invalid"
        return output
    if transform_errors:
        output["qualification"] = "alias_transform_error"
        return output
    paired, collisions = join_field_events(rows, markers)
    if not markers or len(paired) != len(markers) or any(collisions.values()):
        output["qualification"] = "exact_reference_pairing_invalid"
        return output
    output["paired_exact_reference_markers"] = len(paired)
    references = reference_audit(rows, markers, transform_errors)
    by_seq = {row["seq"]: row for row in rows}
    if len(by_seq) != len(rows):
        output["qualification"] = "duplicate_event_sequence"
        return output
    applied_faults = []
    applied_ids = {fault["fault_id"] for fault in plan}
    if len(applied_ids) != len(plan) or any(
            row.get("type") == "FAULT_APPLIED" and row.get("fault_id") not in applied_ids
            for row in rows):
        output["qualification"] = "unexpected_fault_applied"
        return output
    for fault in plan:
        matched = [row for row in rows if row.get("type") == "FAULT_MATCHED" and
                   row.get("fault_id") == fault["fault_id"]]
        applied = [row for row in rows if row.get("type") == "FAULT_APPLIED" and
                   row.get("fault_id") == fault["fault_id"]]
        if len(matched) != 1 or len(applied) != 1:
            output["qualification"] = "fault_unmatched_or_unapplied"
            return output
        m, a = matched[0], applied[0]
        if (not _matches(m, fault) or not _matches(a, fault) or
                m["seq"] >= a["seq"] or
                (m.get("occurrence"), m.get("thread_id"), m.get("context")) !=
                (a.get("occurrence"), a.get("thread_id"), a.get("context")) or
                not (m.get("fault_type") == a.get("fault_type") == fault["fault_type"]) or
                m.get("exception_class") != a.get("exception_class") or
                a.get("exception_class") != fault["exception_class"]):
            output["qualification"] = "fault_identity_mismatch"
            return output
        gates = [row for row in rows if row.get("type") == "STATE_READ" and
                 row.get("site") == GATE and row.get("key") == RESOURCE and
                 row.get("node") == a["node"] and row.get("epoch") == a["epoch"] and
                 row.get("occurrence") == a.get("occurrence") and
                 row.get("thread_id") == a.get("thread_id") and
                 row.get("context") == a.get("context") and row["seq"] < m["seq"]]
        if len(gates) != 1 or not isinstance(gates[0].get("object"), str) or gates[0]["object"] == "static":
            output["qualification"] = "prefault_resource_manager_gate_missing"
            return output
        gate = gates[0]
        door = [row for row in rows if row.get("type") == "DOOR_OBSERVED" and
                _matches(row, fault) and row.get("occurrence") == a.get("occurrence") and
                row.get("thread_id") == a.get("thread_id") and
                gate["seq"] < row["seq"] < m["seq"]]
        if len(door) != 1:
            output["qualification"] = "selected_door_context_missing"
            return output
        if _injected_watcher_wrote(rows, a, gate["object"]):
            output["qualification"] = "faulted_watcher_published_aliases"
            return output
        applied_faults.append((a, gate["object"]))
        output["faults"].append({"fault_id": fault["fault_id"], "applied_seq": a["seq"],
                                 "gate_seq": gate["seq"], "door_seq": door[0]["seq"],
                                 "resource": RESOURCE, "manager_object": gate["object"],
                                 "node": a["node"], "epoch": a["epoch"],
                                 "thread_id": a["thread_id"], "occurrence": a["occurrence"]})
    applied_faults.sort(key=lambda item: item[0]["seq"])
    if [row["fault_id"] for row, _ in applied_faults] != [fault["fault_id"] for fault in plan]:
        output["qualification"] = "fault_sequence_order_invalid"
        return output
    graph = OccurrenceGraph(tuple(rows), reject_coarse_roots=True)
    for applied, manager in applied_faults:
        selected = None
        for path in references["candidate_paths"]:
            try:
                write, read = validate_postfault_retained_reference(
                    rows, paired, path, applied, manager)
                exit_row, continuation = validate_return(rows, path)
            except (ValueError, StopIteration, KeyError):
                continue
            target = by_seq[path["target_check_seq"]]
            graph._add(write, read, "state_exact_ref",
                       "same_volatile_owner_and_java_aliases_reference")
            graph._add(exit_row, continuation, "program_return",
                       "balanced_same_thread_direct_nested_return")
            graph._time_cache.clear()
            witness = graph.event_path(write, target, include_candidates=False, require_edge=True)
            kinds = {edge.kind for edge in witness or ()}
            if witness is None or not {"state_exact_ref", "program_return"} <= kinds:
                continue
            if selected is None or target["seq"] < selected["target_check_seq"]:
                selected = {**path, "manager_object": manager,
                            "fault_applied_seq": applied["seq"],
                            "observed_edge_kinds": sorted(kinds)}
        if selected is None:
            output["qualification"] = "postfault_prior_reference_target_path_missing"
            return output
        output["retained_reference_paths"].append(selected)
    last_seq = applied_faults[-1][0]["seq"]
    if not any(path["target_check_seq"] > last_seq for path in output["retained_reference_paths"]):
        output["qualification"] = "target_lost_after_last_fault"
        return output
    target_occurrences = {(by_seq[p["target_check_seq"]]["node"],
                           by_seq[p["target_check_seq"]]["epoch"],
                           by_seq[p["target_check_seq"]]["thread_id"],
                           by_seq[p["target_check_seq"]]["occurrence"])
                          for p in output["retained_reference_paths"]}
    output["exact_target_exception_candidate"] = any(
        row.get("type") == "TARGET_THROW" and row.get("site") == THROW and
        row.get("exception_class") == EXCEPTION and row["seq"] > last_seq and
        (row.get("node"), row.get("epoch"), row.get("thread_id"), row.get("occurrence"))
        in target_occurrences for row in rows)
    output["valid"] = True
    output["novelty_eligible"] = True
    output["qualification"] = ("exact_target_exception_candidate_for_source_review"
                               if output["exact_target_exception_candidate"] else
                               "strict_prior_reference_target_retained")
    return output


def audit(trial: Path, plan: list[dict]) -> dict:
    try:
        result = json.loads((trial / "result.json").read_text())
        rows = events_from(trial)
        markers, errors = markers_from(trial)
        return audit_rows(rows, markers, result, plan, errors)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        return {"case_id": "SOLR-39", "kind": "preemptive_v5_strict_fault_audit",
                "valid": False, "qualification": "trace_or_reference_audit_invalid",
                "audit_error": str(error), "faults": [],
                "retained_reference_paths": [],
                "exact_target_exception_candidate": False,
                "new_bug_confirmed": False, "novelty_eligible": False}
