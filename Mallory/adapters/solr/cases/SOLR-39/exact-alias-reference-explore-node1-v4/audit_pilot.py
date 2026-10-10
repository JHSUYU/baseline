#!/usr/bin/env python3
"""Audit one outside-closure postpublication SOLR-39 fault trial."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "exact-alias-reference-offline-v2"))
from audit_identity import TARGET, join_field_events, markers_from  # noqa: E402

PROCESS = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
MANAGER_FIELD = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#this$0"
TARGET_REGION = "org.apache.solr.update.processor.RoutedAliasUpdateProcessor#lookupShardLeadersOfCollections()Ljava/util/List;"
TARGET_THROW_SITE = TARGET_REGION + "@247:throw:1"
TARGET_EXCEPTION = "org.apache.solr.common.SolrException"


def events_from(trial: Path) -> list[dict]:
    raw = trial / "events.jsonl"
    stream = raw.open("rt", encoding="utf-8") if raw.is_file() else gzip.open(
        trial / "events.jsonl.gz", "rt", encoding="utf-8")
    with stream:
        return [json.loads(line) for line in stream if line.strip()]


def matching_event(event: dict, plan_fault: dict) -> bool:
    point = plan_fault["point"]
    return (event.get("site") == point["site"] and
            event.get("node") == point["node"] and
            event.get("epoch") == point["epoch"] and
            event.get("door_ordinal") == point["door_ordinal"])


def audit_rows(events: list[dict], markers: list[dict], result: dict,
               plan_fault: dict, transform_errors: int = 0) -> dict:
    fault_id = plan_fault["fault_id"]
    expected = [row for row in events if row.get("fault_id") == fault_id]
    matched = [row for row in expected if row.get("type") == "FAULT_MATCHED"]
    applied = [row for row in expected if row.get("type") == "FAULT_APPLIED"]
    unexpected = [row for row in events if row.get("type") == "FAULT_APPLIED" and
                  row.get("fault_id") != fault_id]
    feedback = result.get("feedback", {})
    effective = (len(matched) == len(applied) == 1 and not unexpected and
                 matching_event(matched[0], plan_fault) and
                 matching_event(applied[0], plan_fault) and
                 matched[0].get("occurrence") == applied[0].get("occurrence") and
                 matched[0].get("thread_id") == applied[0].get("thread_id") and
                 matched[0].get("fault_type") == applied[0].get("fault_type") ==
                 plan_fault["fault_type"] and
                 matched[0].get("exception_class") == applied[0].get("exception_class") ==
                 plan_fault["exception_class"] and
                 matched[0]["seq"] < applied[0]["seq"] and
                 feedback.get("all_faults_effective") is True and
                 feedback.get("fault_identity_valid") is True)
    output = {"case_id": "SOLR-39", "audit_kind": "outside_closure_postpublication_fault_pilot",
              "healthy_event_time_graph_path_from_door": False,
              "planned_fault_id": fault_id, "matched_fault_events": len(matched),
              "applied_fault_events": len(applied), "unexpected_applied_faults": len(unexpected),
              "strict_fault_effective": effective, "transform_errors": transform_errors,
              "target_retained_same_manager": False, "target_exception_candidate": False,
              "new_bug_confirmed": False, "qualification": None,
              "postfault_exact_target_checks_global": sum(
                  row.get("type") == "TARGET_CHECK" and row.get("branch") == TARGET and
                  bool(applied) and row["ts"] > applied[0]["ts"] for row in events),
              "postfault_exact_target_checks_on_injected_actor": sum(
                  row.get("type") == "TARGET_CHECK" and row.get("branch") == TARGET and
                  row.get("node") == plan_fault["point"]["node"] and
                  row.get("epoch") == plan_fault["point"]["epoch"] and
                  bool(applied) and row["ts"] > applied[0]["ts"] for row in events)}
    if result.get("site_catalog_validation", {}).get("valid") is not True:
        output["qualification"] = "target_class_binding_invalid"
        return output
    if not effective:
        output["qualification"] = "fault_unmatched_or_identity_invalid"
        return output
    fault = applied[0]
    doors = [row for row in events if row.get("type") == "DOOR_OBSERVED" and
             matching_event(row, plan_fault) and row.get("thread_id") == fault.get("thread_id") and
             row.get("occurrence") == fault.get("occurrence") and
             row["ts"] <= fault["ts"]]
    if len(doors) != 1 or not doors[0]["site"].startswith(PROCESS):
        output["qualification"] = "fault_door_occurrence_missing"
        return output
    door = doors[0]
    manager_reads = [row for row in events if row.get("type") == "STATE_READ" and
                     row.get("key") == MANAGER_FIELD and
                     row.get("site", "").startswith(PROCESS) and
                     row.get("site", "").endswith("@2312:field:3") and
                     row.get("node") == door["node"] and
                     row.get("epoch") == door["epoch"] and
                     row.get("thread_id") == door["thread_id"] and
                     row.get("occurrence") == door["occurrence"] and
                     row["ts"] < door["ts"]]
    if not manager_reads:
        output["qualification"] = "watcher_manager_identity_missing"
        return output
    manager = max(manager_reads, key=lambda row: row["ts"])
    if not manager.get("object") or manager["object"] == "static":
        output["qualification"] = "watcher_manager_identity_missing"
        return output
    output.update({"fault_applied_seq": fault["seq"], "fault_door_seq": door["seq"],
                   "watcher_manager_field_seq": manager["seq"],
                   "watcher_manager_object": manager["object"],
                   "fault_node": fault["node"], "fault_epoch": fault["epoch"]})
    if transform_errors:
        output["qualification"] = "supplemental_transform_error"
        return output
    paired, collisions = join_field_events(events, markers)
    output.update({"identity_markers": len(markers), "paired_field_events": len(paired),
                   "owner_identity_collisions": collisions})
    if len(paired) != len(markers):
        output["qualification"] = "supplemental_reference_pairing_incomplete"
        return output
    writes = [row for row in paired if row["kind"] == "write" and
              row["node"] == fault["node"] and row["epoch"] == fault["epoch"] and
              row["field_object"] == manager["object"]]
    prepublication = [row for row in writes if row["field_ts"] < fault["ts"] and
                      row["aliases_ref"] and row["zk_version"] >= 0]
    if not prepublication:
        output["qualification"] = "same_manager_prepublication_missing"
        return output
    publication = max(prepublication, key=lambda row: row["field_ts"])
    output.update({"prepublication_write_seq": publication["field_seq"],
                   "prepublication_aliases_ref": publication["aliases_ref"],
                   "prepublication_zk_version": publication["zk_version"],
                   "prepublication_owner_ref": publication["owner_ref"]})
    reads = [row for row in paired if row["kind"] == "read" and
             row["node"] == fault["node"] and row["epoch"] == fault["epoch"] and
             row["field_object"] == manager["object"] and
             row["owner_ref"] == publication["owner_ref"] and
             row["aliases_ref"] == publication["aliases_ref"] and
             row["zk_version"] == publication["zk_version"] and
             row["field_ts"] > fault["ts"]]
    targets = [row for row in events if row.get("type") == "TARGET_CHECK" and
               row.get("branch") == TARGET and row.get("node") == fault["node"] and
               row.get("epoch") == fault["epoch"] and row["ts"] > fault["ts"]]
    for target in sorted(targets, key=lambda row: row["ts"]):
        starts = [row for row in events if row.get("type") == "REGION_ENTER" and
                  row.get("site") == TARGET_REGION and
                  row.get("node") == target["node"] and
                  row.get("epoch") == target["epoch"] and
                  row.get("thread_id") == target["thread_id"] and
                  row.get("context") == target["context"] and
                  row.get("occurrence") == target["occurrence"] and
                  fault["ts"] < row["ts"] < target["ts"]]
        if not starts:
            continue
        start = max(starts, key=lambda row: row["ts"])
        target_reads = [row for row in reads if row["thread_id"] == target["thread_id"] and
                        row["field_context"] == target["context"] and
                        start["ts"] < row["field_ts"] < target["ts"]]
        if not target_reads:
            continue
        target_read = max(target_reads, key=lambda row: row["field_ts"])
        constructor_reads = [row for row in reads if row["thread_id"] == target["thread_id"] and
                             row["field_context"] == target["context"] and
                             fault["ts"] < row["field_ts"] < start["ts"]]
        if not constructor_reads:
            continue
        constructor_read = max(constructor_reads, key=lambda row: row["field_ts"])
        if any(publication["field_ts"] < row["field_ts"] < target["ts"]
               for row in writes):
            continue
        output.update({"target_retained_same_manager": True,
                       "qualification": "outside_closure_target_retained_exact_prepublication_reference",
                       "target_region_enter_seq": start["seq"],
                       "constructor_read_seq": constructor_read["field_seq"],
                       "target_read_seq": target_read["field_seq"],
                       "target_check_seq": target["seq"],
                       "manager_owner_ref": target_read["owner_ref"],
                       "constructor_aliases_ref": constructor_read["aliases_ref"],
                       "target_aliases_ref": target_read["aliases_ref"],
                       "constructor_zk_version": constructor_read["zk_version"],
                       "target_zk_version": target_read["zk_version"],
                       "alias_reference_changed_before_check": (
                           constructor_read["aliases_ref"] != target_read["aliases_ref"])})
        matching_throws = [row for row in events if row.get("type") == "TARGET_THROW" and
                           row.get("site") == TARGET_THROW_SITE and
                           row.get("exception_class") == TARGET_EXCEPTION and
                           row.get("node") == target["node"] and
                           row.get("epoch") == target["epoch"] and
                           row.get("thread_id") == target["thread_id"] and
                           row.get("context") == target["context"] and
                           row.get("occurrence") == target["occurrence"] and
                           row["ts"] > target["ts"]]
        output["target_exception_candidate"] = (feedback.get("target_exception_candidate") is True and
                                                bool(matching_throws))
        if output["target_exception_candidate"]:
            output["qualification"] = "exact_target_exception_candidate_for_source_review"
        break
    if output["qualification"] is None:
        output["qualification"] = "target_lost_or_manager_path_unqualified"
    return output


def audit(trial: Path, plan_fault: dict) -> dict:
    result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    events = events_from(trial)
    markers, errors = markers_from(trial) if (trial / "junit.log").is_file() else ([], 0)
    return audit_rows(events, markers, result, plan_fault, errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial", type=Path)
    parser.add_argument("--plan", type=Path, default=HERE / "fault-plan.json")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))["faults"]
    print(json.dumps(audit(args.trial, plan[0]), sort_keys=True, indent=2))
