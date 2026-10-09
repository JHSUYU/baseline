#!/usr/bin/env python3
"""Read-only historical fault-to-target precision review for completed cases.

This deliberately uses immutable archived traces and old audited edges. It
never upgrades a legacy path to the new numeric-thread-ID proof level.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def address(event: dict[str, Any]) -> str | None:
    if not all(key in event for key in ("node", "epoch", "occurrence")):
        return None
    return json.dumps([str(event["node"]), str(event["epoch"]),
                       event["occurrence"]], separators=(",", ":"))


def scoped_region(event: dict[str, Any]) -> bool:
    occurrence = event.get("occurrence")
    return (isinstance(occurrence, str) and occurrence and
            not occurrence.startswith("unscoped:") and
            isinstance(event.get("region"), str) and bool(event["region"]) and
            event.get("node") not in (None, "", "unknown", "null", "None"))


def same_named_thread(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """A legacy diagnostic, never a replacement for numeric JVM thread ID."""
    name = first.get("thread")
    return isinstance(name, str) and bool(name) and name == second.get("thread")


def load_relevant(trial: Path, receipt: dict[str, Any], needed: set[str],
                  target_sites: set[str], target_instances: set[tuple[Any, ...]],
                  last_fault_seq: int) -> tuple[dict[str, dict[str, Any]],
                                                 list[dict[str, Any]], str]:
    evidence = receipt["events_evidence"]
    name = evidence.get("gzip_path") or evidence.get("raw_path")
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("invalid archived trace filename")
    path = trial / name
    if sha(path) != evidence.get("gzip_sha256", evidence.get("raw_sha256")):
        raise ValueError(f"archived trace SHA mismatch: {path}")
    raw_hash = hashlib.sha256()
    found: dict[str, dict[str, Any]] = {}
    checks: list[dict[str, Any]] = []
    opener = gzip.open if evidence.get("gzip_path") else open
    with opener(path, "rb") as stream:
        for line in stream:
            raw_hash.update(line)
            event = json.loads(line)
            event_id = event.get("id")
            if event_id in needed:
                found[event_id] = event
            if (event.get("type") == "TARGET_CHECK" and
                    event.get("site") in target_sites and
                    isinstance(event.get("seq"), int) and
                    event["seq"] > last_fault_seq and
                    (event.get("node"), event.get("epoch"),
                     event.get("occurrence")) in target_instances):
                checks.append(event)
    if raw_hash.hexdigest() != evidence.get("raw_sha256"):
        raise ValueError(f"decompressed trace SHA mismatch: {path}")
    return found, checks, raw_hash.hexdigest()


def occurrence_path(start: str, finish: str, edges: list[dict[str, Any]]) -> bool:
    if start == finish:
        return True
    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        try:
            source_occurrence = json.loads(edge["source"])[2]
            target_occurrence = json.loads(edge["target"])[2]
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        if (not isinstance(source_occurrence, str) or
                not isinstance(target_occurrence, str) or
                source_occurrence.startswith("unscoped:") or
                target_occurrence.startswith("unscoped:")):
            continue
        outgoing[edge["source"]].add(edge["target"])
    seen = {start}
    pending = [start]
    while pending:
        for successor in outgoing[pending.pop()]:
            if successor == finish:
                return True
            if successor not in seen:
                seen.add(successor)
                pending.append(successor)
    return False


def ordered_region_path(start: dict[str, Any], finish: dict[str, Any],
                        edges: list[dict[str, Any]],
                        events: dict[str, dict[str, Any]]) -> list[dict[str, str]] | None:
    """Use unique region invocation IDs and trace order; reject all unscoped hops."""
    if not scoped_region(start) or not scoped_region(finish):
        return None
    start_address, finish_address = address(start), address(finish)
    if start_address == finish_address and start["seq"] < finish["seq"]:
        return []
    outgoing: dict[str, list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for edge in edges:
        producer = events.get(edge.get("producer_event"))
        consumer = events.get(edge.get("consumer_event"))
        if (producer is None or consumer is None or
                not scoped_region(producer) or not scoped_region(consumer) or
                address(producer) != edge.get("source") or
                address(consumer) != edge.get("target") or
                not isinstance(producer.get("seq"), int) or
                not isinstance(consumer.get("seq"), int) or
                producer["seq"] >= consumer["seq"]):
            continue
        outgoing[edge["source"]].append((edge, producer, consumer))
    seen: dict[str, int] = {start_address: start["seq"]}
    pending = [(start_address, start["seq"], [])]
    while pending:
        current_address, current_seq, path = pending.pop()
        if current_seq != seen.get(current_address):
            continue
        for edge, producer, consumer in outgoing[current_address]:
            if producer["seq"] < current_seq:
                continue
            next_address, next_seq = edge["target"], consumer["seq"]
            witness = path + [{"producer_event": edge["producer_event"],
                               "consumer_event": edge["consumer_event"],
                               "kind": edge["kind"]}]
            if next_address == finish_address and next_seq < finish["seq"]:
                return witness
            # For forward reachability an earlier arrival dominates a later
            # one: it can use every subsequent same-region producer.
            if next_seq < seen.get(next_address, 1 << 62):
                seen[next_address] = next_seq
                pending.append((next_address, next_seq, witness))
    return None


def review_case(case: Path) -> dict[str, Any]:
    config_path, result_path, audit_path = (case / name for name in
                                            ("config.json", "result.json",
                                             "offline-causal-audit.json"))
    config = json.loads(config_path.read_text())
    summary = json.loads(result_path.read_text())
    audit = json.loads(audit_path.read_text())
    if (not audit.get("report_gate_passed") or
            audit.get("campaign_result_sha256") != sha(result_path)):
        raise ValueError(f"canonical audit is not bound to result: {case}")
    audit_by_id = {row["trial_id"]: row for row in audit["trials"]}
    target_sites = set(config["target"].get("check_sites", [config["target"].get("site")]))
    strict = same_region = ordered = occurrence_only = actor_thread = 0
    trial_rows = []
    for item in summary["trials"]:
        if not (item.get("trial_id", 0) > 0 and item.get("all_faults_effective") and
                item.get("target_reached")):
            continue
        trial_id = item["trial_id"]
        trial = case / "trials" / f"r{trial_id:04d}"
        result = json.loads((trial / "result.json").read_text())
        audit_row = audit_by_id[trial_id]
        feedback = result["feedback"]
        target_instances = {(row.get("node"), row.get("epoch"), row.get("occurrence"))
                            for row in feedback.get("target_closures", [])}
        applied_ids = {event_id for fault in audit_row.get("faults", [])
                       for event_id in fault.get("applied_event_ids", [])}
        last_fault_seq = feedback.get("last_fault_seq", -1)
        edges = [edge for edge in feedback.get("closure_edges", [])
                 if edge.get("certainty") == "observed"]
        needed = applied_ids | {eid for edge in edges
                                for eid in (edge.get("producer_event"),
                                            edge.get("consumer_event")) if isinstance(eid, str)}
        found, checks, raw_sha = load_relevant(
            trial, result, needed, target_sites, target_instances, last_fault_seq)
        if len(found.keys() & applied_ids) != len(applied_ids) or not applied_ids:
            raise ValueError(f"missing exact applied receipt: {case.name} trial {trial_id}")
        applied = [found[eid] for eid in sorted(applied_ids)]
        same = []
        actor_thread_pairs = []
        paths = []
        occurrence_paths = []
        for fault in applied:
            for check in checks:
                if fault.get("seq", 1 << 62) >= check["seq"]:
                    continue
                if (fault.get("node") == check.get("node") and
                        fault.get("epoch") == check.get("epoch") and
                        same_named_thread(fault, check)):
                    actor_thread_pairs.append((fault["id"], check["id"]))
                if (scoped_region(fault) and scoped_region(check) and
                        address(fault) == address(check) and
                        same_named_thread(fault, check)):
                    same.append((fault["id"], check["id"]))
                witness = ordered_region_path(fault, check, edges, found)
                if witness is not None and witness:
                    paths.append((fault["id"], check["id"], witness))
                if (scoped_region(fault) and scoped_region(check) and
                        occurrence_path(address(fault), address(check), edges)):
                    occurrence_paths.append((fault["id"], check["id"]))
        strict += 1
        same_region += bool(same)
        actor_thread += bool(actor_thread_pairs)
        ordered += bool(paths)
        occurrence_only += bool(occurrence_paths)
        trial_rows.append({"trial_id": trial_id,
                           "trial_result_sha256": sha(trial / "result.json"),
                           "raw_trace_sha256": raw_sha,
                           "applied_event_ids": sorted(applied_ids),
                           "postfault_target_check_count": len(checks),
                           "same_region_continuation": bool(same),
                           "same_actor_named_thread_order": bool(actor_thread_pairs),
                           "ordered_root_free_region_path": bool(paths),
                           "root_free_occurrence_path": bool(occurrence_paths),
                           "sample": {"same_region": same[:1],
                                      "same_actor_named_thread": actor_thread_pairs[:1],
                                      "ordered_path": paths[:1]}})
    return {"schema_version": 1,
            "analysis_kind": "historical_faulted_run_precision_read_only",
            "case_id": case.name,
            "canonical_result_sha256": sha(result_path),
            "canonical_config_sha256": sha(config_path),
            "canonical_audit_sha256": sha(audit_path),
            "strict_target_trials": strict,
            "same_region_continuation_trials": same_region,
            "same_actor_named_thread_order_trials": actor_thread,
            "ordered_root_free_region_path_trials": ordered,
            "root_free_occurrence_path_trials": occurrence_only,
            "classification": ("legacy_faulted_region_evidence" if same_region or ordered
                               else "faulted_path_unverified"),
            "recommended_quality_status": ("retain_legacy_faulted_region_evidence"
                                           if same_region or ordered else
                                           "downgrade_to_faulted_path_unverified"),
            "limits": ("Old traces lack numeric JVM thread_id. A unique region invocation "
                       "plus matching node, epoch, thread name and ordered event IDs "
                       "supports a legacy local/path inference; "
                       "it is not the future event-time gate's thread proof. "
                       "Same actor/thread name outside one region, unscoped occurrence "
                       "paths and target reach alone do not qualify."),
            "trials": trial_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    checklist_path = repo / "data/mallory/checklist102.json"
    checklist = json.loads(checklist_path.read_text())
    cohort_index = out / "index.json"
    if cohort_index.exists():
        # Preserve the cohort selected from the historical checklist even if
        # dispatch updates the live table while this read-only audit runs.
        pinned = json.loads(cohort_index.read_text())
        cases = pinned["cohort"]
        cohort_checklist_sha = pinned["checklist_sha256"]
    else:
        cases = [row["case_id"] for row in checklist["rows"]
                 if row.get("quality_status") == "target_exercised" and
                 row["case_id"] != "HDFS-22"]
        cohort_checklist_sha = sha(checklist_path)
    if len(cases) != 23 or len(set(cases)) != 23 or "HDFS-22" in cases:
        raise ValueError(f"expected exactly 23 pinned historical HQ cases, got {cases}")
    rows = []
    for case_id in cases:
        review = review_case(repo / "data/mallory/cases" / case_id)
        path = out / f"{case_id}.json"
        path.write_text(json.dumps(review, sort_keys=True, indent=2) + "\n")
        rows.append({"case_id": case_id, "classification": review["classification"],
                     "recommended_quality_status": review[
                         "recommended_quality_status"],
                     "strict_target_trials": review["strict_target_trials"],
                     "same_region_continuation_trials": review["same_region_continuation_trials"],
                     "same_actor_named_thread_order_trials": review[
                         "same_actor_named_thread_order_trials"],
                     "ordered_root_free_region_path_trials": review[
                         "ordered_root_free_region_path_trials"],
                     "review_sha256": sha(path)})
        print(case_id, rows[-1]["classification"],
              rows[-1]["same_region_continuation_trials"],
              rows[-1]["ordered_root_free_region_path_trials"], flush=True)
    index = {"schema_version": 1, "cohort": cases,
             "checklist_sha256": cohort_checklist_sha,
             "current_checklist_sha256": sha(checklist_path),
             "source_sha256": sha(Path(__file__)),
             "rows": rows}
    (out / "index.json").write_text(json.dumps(index, sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
