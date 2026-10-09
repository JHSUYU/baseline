#!/usr/bin/env python3
"""Fail-closed event and source proof for SOLR-18's BadVersion recovery path."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import Mallory.core.graph as graph_module
from Mallory.core.graph import OccurrenceGraph


DOOR = (
    "org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
    "#applyModificationAndExportToZk(Ljava/util/function/UnaryOperator;)V@2259:door:1"
)
TARGET = (
    "org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
    "#setIfNewer(Lorg/apache/solr/common/cloud/Aliases;)Z@2347:branch:"
)
BAD_VERSION = "org.apache.zookeeper.KeeperException$BadVersionException"
UPDATE = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#update()Z"
SET_IF_NEWER = (
    "org.apache.solr.common.cloud.ZkStateReader$AliasesManager"
    "#setIfNewer(Lorg/apache/solr/common/cloud/Aliases;)Z"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def same_identity(left: dict, right: dict) -> bool:
    return all(left.get(key) == right.get(key) for key in
               ("site", "node", "epoch", "thread_id", "occurrence", "door_ordinal"))


def same_actor(left: dict, right: dict) -> bool:
    return all(left.get(key) == right.get(key) for key in
               ("node", "epoch", "thread_id"))


def proof(events: list[dict], plan: dict) -> dict:
    """Return one strict witness, or a precise fail-closed reason."""
    try:
        point = plan["point"]
        if (point["site"] != DOOR or plan["exception_class"] != BAD_VERSION or
                plan["fault_type"] != "EXCEPTION"):
            return {"valid": False, "reason": "wrong_plan"}
        if (not isinstance(point.get("node"), str) or point["node"] in
                ("", "unknown", "null", "None") or
                not isinstance(point.get("epoch"), int) or
                not isinstance(point.get("door_ordinal"), int)):
            return {"valid": False, "reason": "unbound_plan"}
        if (len({row.get("id") for row in events}) != len(events) or
                len({row.get("seq") for row in events}) != len(events)):
            return {"valid": False, "reason": "ambiguous_event_identity"}
        applied = [row for row in events if row.get("type") == "FAULT_APPLIED"]
        matched = [row for row in events if row.get("type") == "FAULT_MATCHED"]
        if (len(applied) != 1 or len(matched) != 1 or
                applied[0].get("fault_id") != plan["fault_id"] or
                matched[0].get("fault_id") != plan["fault_id"]):
            return {"valid": False, "reason": "fault_receipt_count_or_id"}
        fault, match = applied[0], matched[0]
        doors = [row for row in events if row.get("type") == "DOOR_OBSERVED"
                 and same_identity(row, fault)]
        if (len(doors) != 1 or not same_identity(fault, match) or
                not isinstance(fault.get("thread_id"), int) or
                isinstance(fault.get("thread_id"), bool) or
                fault.get("exception_class") != BAD_VERSION or
                match.get("exception_class") != BAD_VERSION or
                doors[0].get("exception_class") != BAD_VERSION or
                any(fault.get(key) != point[key] for key in
                    ("site", "node", "epoch", "door_ordinal"))):
            return {"valid": False, "reason": "fault_identity_or_type"}
        door = doors[0]
        regions = [row for row in events if row.get("type") == "REGION_ENTER"
                   and row.get("occurrence") == fault["occurrence"]]
        exits = [row for row in events if row.get("type") == "REGION_EXIT"
                 and row.get("occurrence") == fault["occurrence"]]
        if len(regions) != 1 or len(exits) != 1:
            return {"valid": False, "reason": "apply_region_unbalanced"}
        apply_enter, apply_exit = regions[0], exits[0]
        if (apply_enter.get("site") != DOOR.split("@", 1)[0] or
                not same_actor(apply_enter, fault) or
                not same_actor(apply_exit, fault) or
                not (apply_enter["seq"] < door["seq"] < match["seq"] <
                     fault["seq"] < apply_exit["seq"])):
            return {"valid": False, "reason": "fault_order_or_apply_region"}
        updates = [row for row in events if row.get("type") == "REGION_ENTER"
                   and row.get("site") == UPDATE and
                   row.get("parent_id") == fault["occurrence"] and
                   same_actor(row, fault) and
                   fault["seq"] < row["seq"] < apply_exit["seq"]]
        if len(updates) != 1:
            return {"valid": False, "reason": "missing_unique_caught_update"}
        update = updates[0]
        children = [row for row in events if row.get("type") == "REGION_ENTER"
                    and row.get("site") == SET_IF_NEWER and
                    row.get("parent_id") == update["occurrence"] and
                    same_actor(row, fault) and
                    update["seq"] < row["seq"] < apply_exit["seq"]]
        if len(children) != 1:
            return {"valid": False, "reason": "missing_unique_set_if_newer_child"}
        child = children[0]
        checks = [row for row in events if row.get("type") == "TARGET_CHECK"
                  and row.get("site", "").startswith(TARGET) and
                  row.get("occurrence") == child["occurrence"] and
                  same_actor(row, fault) and
                  child["seq"] < row["seq"] < apply_exit["seq"]]
        if not checks:
            return {"valid": False, "reason": "missing_selected_target_check"}
        target = min(checks, key=lambda row: row["seq"])
        graph = OccurrenceGraph(tuple(events), reject_coarse_roots=True)
        path = graph.event_path(fault, target, require_edge=True,
                                include_candidates=False)
        if (path is None or len(path) != 2 or
                [(edge.kind, edge.producer_event, edge.consumer_event)
                 for edge in path] != [
                     ("program_order", fault["id"], update["id"]),
                     ("region_parent", update["id"], child["id"])]):
            return {"valid": False, "reason": "missing_exact_observed_graph_path"}
        return {
            "valid": True, "reason": "same_apply_badversion_recovery",
            "node": fault["node"], "epoch": fault["epoch"],
            "thread_id": fault["thread_id"], "apply_occurrence": fault["occurrence"],
            "door_ordinal": fault["door_ordinal"],
            "event_ids": {"apply_enter": apply_enter["id"], "door": door["id"],
                          "matched": match["id"], "applied": fault["id"],
                          "update": update["id"], "set_if_newer": child["id"],
                          "target_check": target["id"], "apply_exit": apply_exit["id"]},
            "graph_edges": [{"kind": edge.kind, "producer_event": edge.producer_event,
                             "consumer_event": edge.consumer_event,
                             "certainty": edge.certainty} for edge in path],
        }
    except (AssertionError, KeyError, TypeError, ValueError, IndexError) as exc:
        return {"valid": False, "reason": "malformed_event_chain", "detail": type(exc).__name__}


def review(campaign: Path, source: Path, test_source: Path) -> dict:
    top_path, config_path = campaign / "result.json", campaign / "config.json"
    trial_path = campaign / "trials/r0001/result.json"
    audit_path = campaign / "offline-causal-audit.json"
    trace_path = campaign / "trials/r0001/events.jsonl.gz"
    top, config, trial, audit = (load(path) for path in
                                 (top_path, config_path, trial_path, audit_path))
    assert top["case_id"] == config["case_id"] == trial["case_id"] == audit["case_id"] == "SOLR-18"
    assert top["status"] == "budget_exhausted" and top["fault_trials_completed"] == 1
    assert config["budget"]["trials"] == config["budget"]["max_faults_per_trial"] == 1
    assert config["site_file"].endswith("sites-v44-badversion.json")
    assert config["agent_properties"]["auto.io.doors"] is False
    assert config["mapping"]["target_source_sha256"] == digest(source)
    assert config["mapping"]["test_source_sha256"] == digest(test_source)
    assert audit["campaign_result_sha256"] == digest(top_path)
    assert all(audit[key] is True for key in
               ("archive_integrity_valid", "guidance_consistent",
                "target_claims_reverified", "applied_fault_identity_valid"))
    assert trial["feedback"]["trace_truncated"] is False
    assert trial["trace_error"] is None and trial["timed_out"] is False
    junit = trial["junit_validation"]
    assert (junit["status"] == "passed" and junit["tests"] == 1 and
            junit["failures"] == junit["errors"] == junit["skipped"] == 0)
    assert len(trial["plan"]) == 1
    source_text = source.read_text()
    method = source_text.split("public void applyModificationAndExportToZk(", 1)[1].split(
        "public boolean update()", 1)[0]
    update = source_text.split("public boolean update()", 1)[1].split(
        "public void process(WatchedEvent event)", 1)[0]
    catch = method.split("catch (KeeperException.BadVersionException e)", 1)[1]
    assert "update();" in catch
    assert "final byte[] data = zkClient.getData(ALIASES, null, stat, true);" in update
    assert "return setIfNewer(Aliases.fromJSON(data, stat.getVersion()));" in update
    assert "testDeleteAliasWithExistingCollectionName()" in test_source.read_text()
    release_graph = Path(config["core_release"]) / "Mallory/core/graph.py"
    assert Path(graph_module.__file__).resolve() == release_graph.resolve()
    raw_gzip = trace_path.read_bytes()
    raw = gzip.decompress(raw_gzip)
    events = [json.loads(line) for line in raw.splitlines() if line]
    chain = proof(events, trial["plan"][0])
    target_throws = [row for row in events if row.get("type") == "TARGET_THROW"
                     and row.get("site", "").startswith(SET_IF_NEWER)]
    return {
        "schema_version": 1, "case_id": "SOLR-18",
        "classification": ("same_invocation_badversion_recovery_witness" if chain["valid"]
                           else "no_strict_badversion_recovery_witness"),
        "full_campaign_promoted": False, "new_bug_confirmed": False,
        "campaign_result_sha256": digest(top_path), "config_sha256": digest(config_path),
        "trial_result_sha256": digest(trial_path), "audit_sha256": digest(audit_path),
        "events_gzip_sha256": digest(trace_path),
        "events_raw_sha256": hashlib.sha256(raw).hexdigest(), "events_raw_bytes": len(raw),
        "source_sha256": digest(source), "test_source_sha256": digest(test_source),
        "core_graph_sha256": digest(release_graph),
        "junit_status": junit["status"], "trace_truncated": False,
        "target_throw_event_ids": [row.get("id") for row in target_throws],
        "pilot_fault_id": trial["plan"][0]["fault_id"], "plan_point": trial["plan"][0]["point"],
        "chain": chain,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--test-source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--require-witness", action="store_true")
    args = parser.parse_args()
    row = review(args.campaign, args.source, args.test_source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": row["classification"],
                      "graph_edges": row["chain"].get("graph_edges", [])}, sort_keys=True))
    if args.require_witness and not row["chain"]["valid"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
