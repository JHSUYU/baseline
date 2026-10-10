#!/usr/bin/env python3
"""SOLR-39 fault audit using exact prior Aliases references, including admin writes.

This is an offline correction of v5.  A failed JUnit is a workload outcome;
it does not erase an intact fault/target trace or an exact target throw.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
ROOT = HERE.parents[5]
sys.path.insert(0, str(CASE / "exact-alias-reference-offline-v2"))
from audit_identity import (FIELD, TARGET, events_from, join_field_events,
                            markers_from)  # noqa: E402
sys.path.insert(0, str(CASE / "preemptive-graph-gap-v4"))
from audit_graph_gap import (validate_postfault_retained_reference,
                             validate_return)  # noqa: E402
sys.path.insert(0, str(ROOT / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"))
from Mallory.core.graph import OccurrenceGraph  # noqa: E402

GATE = "SOLR39_PREFAULT_RESOURCE_MANAGER"
RESOURCE = "/aliases.json"
THROW = ("org.apache.solr.update.processor.RoutedAliasUpdateProcessor"
         "#lookupShardLeadersOfCollections()Ljava/util/List;@247:throw:1")
EXCEPTION = "org.apache.solr.common.SolrException"
SET_IF_NEWER = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#setIfNewer"


def _same_point(row: dict, fault: dict) -> bool:
    return all(row.get(k) == fault["point"][k]
               for k in ("site", "node", "epoch", "door_ordinal"))


def _faulted_watcher_wrote(rows: list[dict], applied: dict, manager: str) -> bool:
    children = {r.get("occurrence") for r in rows
                if r.get("type") == "REGION_ENTER" and
                r.get("parent_id") == applied.get("occurrence") and
                r.get("region", "").startswith(SET_IF_NEWER) and
                (r.get("node"), r.get("epoch"), r.get("thread_id")) ==
                (applied.get("node"), applied.get("epoch"), applied.get("thread_id")) and
                r["seq"] > applied["seq"]}
    return any(r.get("type") == "STATE_WRITE" and r.get("key") == FIELD and
               r.get("object") == manager and r.get("occurrence") in children
               for r in rows)


def _candidate_paths(rows: list[dict], paired: list[dict]) -> list[dict]:
    """Enumerate source-backed write/read paths without a watcher-writer assumption.

    The prior publication may come from the admin update path.  Exact Java
    owner/reference/version pairing and balanced target return are validated
    separately by the v4 overlay before a path can earn credit.
    """
    writes = [r for r in paired if r["kind"] == "write"]
    reads = [r for r in paired if r["kind"] == "read"]
    paths = []
    for target in rows:
        if target.get("type") != "TARGET_CHECK" or target.get("branch") != TARGET:
            continue
        request_reads = [r for r in reads if
                         (r["node"], r["epoch"], r["field_context"]) ==
                         (target["node"], target["epoch"], target["context"]) and
                         r["field_ts"] < target["ts"]]
        request_reads.sort(key=lambda r: r["field_ts"], reverse=True)
        for read in request_reads:
            if not read["aliases_ref"]:
                continue
            earlier = [r for r in request_reads if
                       r["field_ts"] < read["field_ts"] and
                       (r["owner_ref"], r["aliases_ref"], r["zk_version"]) ==
                       (read["owner_ref"], read["aliases_ref"], read["zk_version"])]
            if not earlier:
                continue
            constructor = max(earlier, key=lambda r: r["field_ts"])
            preceding = [w for w in writes if
                         (w["node"], w["epoch"], w["owner_ref"],
                          w["aliases_ref"], w["zk_version"]) ==
                         (read["node"], read["epoch"], read["owner_ref"],
                          read["aliases_ref"], read["zk_version"]) and
                         w["field_ts"] < constructor["field_ts"]]
            if not preceding:
                continue
            write = max(preceding, key=lambda w: w["field_ts"])
            if any(w["node"] == read["node"] and w["epoch"] == read["epoch"] and
                   w["owner_ref"] == read["owner_ref"] and
                   write["field_ts"] < w["field_ts"] < target["ts"]
                   for w in writes):
                continue
            paths.append({"node": target["node"], "epoch": target["epoch"],
                          "cache_write_seq": write["field_seq"],
                          "constructor_read_seq": constructor["field_seq"],
                          "target_read_seq": read["field_seq"],
                          "target_check_seq": target["seq"],
                          "owner_ref": read["owner_ref"],
                          "aliases_ref": read["aliases_ref"],
                          "zk_version": read["zk_version"],
                          "request_context": target["context"],
                          "writer_context": write["field_context"],
                          "writer_origin": "source_observed_setIfNewer"})
            break
    return paths


def _target_throws(rows: list[dict], faults: list[tuple[dict, str]]) -> list[dict]:
    """Count only exact @247 throws in a bound actor's later target occurrence."""
    checks = [r for r in rows if r.get("type") == "TARGET_CHECK" and
              r.get("branch") == TARGET]
    candidates = []
    for throw in rows:
        if (throw.get("type") != "TARGET_THROW" or throw.get("site") != THROW or
                throw.get("exception_class") != EXCEPTION):
            continue
        for applied, manager in faults:
            if not (throw["seq"] > applied["seq"] and
                    (throw.get("node"), throw.get("epoch")) ==
                    (applied.get("node"), applied.get("epoch"))):
                continue
            check = next((r for r in checks if
                          applied["seq"] < r["seq"] < throw["seq"] and
                          (r.get("node"), r.get("epoch"), r.get("thread_id"),
                           r.get("occurrence")) ==
                          (throw.get("node"), throw.get("epoch"),
                           throw.get("thread_id"), throw.get("occurrence"))), None)
            if check is None:
                continue
            if any(r.get("type") == "REGION_EXIT" and
                   (r.get("node"), r.get("epoch"), r.get("occurrence")) ==
                   (check.get("node"), check.get("epoch"), check.get("occurrence")) and
                   check["seq"] < r["seq"] < throw["seq"] for r in rows):
                continue
            # A manager read under this target request binds @247 to the
            # faulted AliasesManager, independently of path/novelty credit.
            if not any(r.get("type") == "STATE_READ" and r.get("key") == FIELD and
                       r.get("object") == manager and
                       (r.get("node"), r.get("epoch"), r.get("context")) ==
                       (check.get("node"), check.get("epoch"), check.get("context")) and
                       applied["seq"] < r["seq"] < check["seq"]
                       for r in rows):
                continue
            candidates.append({"throw_seq": throw["seq"], "check_seq": check["seq"],
                               "fault_applied_seq": applied["seq"],
                               "node": throw["node"], "epoch": throw["epoch"],
                               "occurrence": throw["occurrence"],
                               "manager_object": manager})
            break
    return candidates


def audit_rows(rows: list[dict], markers: list[dict], result: dict,
               plan: list[dict], transform_errors: int = 0) -> dict:
    junit = result.get("junit_validation", {})
    output = {"case_id": "SOLR-39", "kind": "preemptive_v6_exact_prior_reference_audit",
              "valid": False, "novelty_eligible": False,
              "qualification": "unexamined", "faults": [],
              "retained_reference_paths": [], "exact_target_throw_candidates": [],
              "exact_target_exception_candidate": False, "new_bug_confirmed": False,
              "workload_outcome": {"junit_status": junit.get("status"),
                                   "junit_tests": junit.get("tests"),
                                   "junit_failures": junit.get("failures"),
                                   "return_code": result.get("return_code"),
                                   "timed_out": result.get("timed_out")}}
    feedback = result.get("feedback", {})
    if (result.get("site_catalog_validation", {}).get("valid") is not True or
            result.get("trace_error") is not None or result.get("timed_out") is not False or
            feedback.get("trace_truncated") is not False or
            feedback.get("fault_identity_valid") is not True or
            feedback.get("fault_order_valid") is not True or
            feedback.get("target_identity_complete") is not True):
        output["qualification"] = "trace_or_target_identity_incomplete"
        return output
    if (not plan or len(plan) > 3 or result.get("plan") != plan or
            len({f["fault_id"] for f in plan}) != len(plan)):
        output["qualification"] = "plan_identity_invalid"
        return output
    if transform_errors:
        output["qualification"] = "alias_transform_error"
        return output
    by_seq = {r["seq"]: r for r in rows}
    if len(by_seq) != len(rows) or not rows:
        output["qualification"] = "duplicate_or_empty_trace"
        return output
    applied = []
    ids = {f["fault_id"] for f in plan}
    if any(r.get("type") == "FAULT_APPLIED" and r.get("fault_id") not in ids for r in rows):
        output["qualification"] = "unexpected_fault_applied"
        return output
    for fault in plan:
        matched = [r for r in rows if r.get("type") == "FAULT_MATCHED" and
                   r.get("fault_id") == fault["fault_id"]]
        hits = [r for r in rows if r.get("type") == "FAULT_APPLIED" and
                r.get("fault_id") == fault["fault_id"]]
        if len(matched) != 1 or len(hits) != 1:
            output["qualification"] = "fault_unmatched_or_unapplied"
            return output
        m, a = matched[0], hits[0]
        if (not _same_point(m, fault) or not _same_point(a, fault) or
                m["seq"] >= a["seq"] or
                (m.get("occurrence"), m.get("thread_id"), m.get("context")) !=
                (a.get("occurrence"), a.get("thread_id"), a.get("context")) or
                not (m.get("fault_type") == a.get("fault_type") == fault["fault_type"]) or
                m.get("exception_class") != a.get("exception_class") or
                a.get("exception_class") != fault["exception_class"]):
            output["qualification"] = "fault_identity_mismatch"
            return output
        gates = [r for r in rows if r.get("type") == "STATE_READ" and
                 r.get("site") == GATE and r.get("key") == RESOURCE and
                 (r.get("node"), r.get("epoch"), r.get("occurrence"),
                  r.get("thread_id"), r.get("context")) ==
                 (a.get("node"), a.get("epoch"), a.get("occurrence"),
                  a.get("thread_id"), a.get("context")) and r["seq"] < m["seq"]]
        if (len(gates) != 1 or not isinstance(gates[0].get("object"), str) or
                not gates[0]["object"] or gates[0]["object"] == "static"):
            output["qualification"] = "prefault_resource_manager_gate_missing"
            return output
        gate = gates[0]
        doors = [r for r in rows if r.get("type") == "DOOR_OBSERVED" and
                 _same_point(r, fault) and
                 (r.get("occurrence"), r.get("thread_id"), r.get("context")) ==
                 (a.get("occurrence"), a.get("thread_id"), a.get("context")) and
                 gate["seq"] < r["seq"] < m["seq"]]
        if len(doors) != 1:
            output["qualification"] = "selected_door_context_missing"
            return output
        if _faulted_watcher_wrote(rows, a, gate["object"]):
            output["qualification"] = "faulted_watcher_published_aliases"
            return output
        applied.append((a, gate["object"]))
        output["faults"].append({"fault_id": fault["fault_id"],
                                 "applied_seq": a["seq"], "door_seq": doors[0]["seq"],
                                 "gate_seq": gate["seq"], "resource": RESOURCE,
                                 "manager_object": gate["object"],
                                 "node": a["node"], "epoch": a["epoch"],
                                 "occurrence": a["occurrence"]})
    applied.sort(key=lambda pair: pair[0]["seq"])
    if [a["fault_id"] for a, _ in applied] != [f["fault_id"] for f in plan]:
        output["qualification"] = "fault_sequence_order_invalid"
        return output
    output["exact_target_throw_candidates"] = _target_throws(rows, applied)
    output["exact_target_exception_candidate"] = bool(output["exact_target_throw_candidates"])
    paired, collisions = join_field_events(rows, markers)
    if not markers or len(paired) != len(markers) or any(collisions.values()):
        output["qualification"] = "exact_reference_pairing_invalid"
        return output
    output["paired_exact_reference_markers"] = len(paired)
    paths = _candidate_paths(rows, paired)
    graph = OccurrenceGraph(tuple(rows), reject_coarse_roots=True)
    for a, manager in applied:
        selected = None
        for path in paths:
            try:
                write, read = validate_postfault_retained_reference(rows, paired, path, a, manager)
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
                            "fault_applied_seq": a["seq"],
                            "observed_edge_kinds": sorted(kinds)}
        if selected is None:
            output["qualification"] = "postfault_bound_actor_prior_reference_target_missing"
            return output
        output["retained_reference_paths"].append(selected)
    if not any(p["target_check_seq"] > applied[-1][0]["seq"]
               for p in output["retained_reference_paths"]):
        output["qualification"] = "target_lost_after_last_fault"
        return output
    output["valid"] = output["novelty_eligible"] = True
    output["qualification"] = "strict_prior_reference_target_retained"
    return output


def audit(trial: Path, plan: list[dict]) -> dict:
    result = json.loads((trial / "result.json").read_text())
    rows = events_from(trial)
    markers, errors = markers_from(trial)
    return audit_rows(rows, markers, result, plan, errors)
