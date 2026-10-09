#!/usr/bin/env python3
"""Read-only exact-door audit of the canonical SOLR-19 v23b archive."""

from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from Mallory.core.events import Trace, event_address, event_seq
from Mallory.core.feedback import analyze
from Mallory.core.graph import OccurrenceGraph


CAMPAIGN = REPO / "data/mallory/replays/SOLR-19-v23b-lane2"
OUT = Path(__file__).with_suffix(".json")
UNKNOWN = {"", "unknown", "null", "None"}
POINT_FIELDS = ("site", "node", "epoch", "door_ordinal")
KEEP_TYPES = {"DOOR_OBSERVED", "FAULT_MATCHED", "FAULT_APPLIED", "TARGET_CHECK", "TARGET_THROW"}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def point(event: dict) -> tuple | None:
    values = tuple(event.get(key) for key in POINT_FIELDS)
    if (values[0] is None or not isinstance(values[1], str) or values[1] in UNKNOWN
            or values[2] is None or not isinstance(values[3], int)
            or isinstance(values[3], bool) or values[3] <= 0):
        return None
    return values


def named(event: dict) -> bool:
    return isinstance(event.get("node"), str) and event["node"] not in UNKNOWN


def exact_check(event: dict, target: dict) -> bool:
    return (event.get("type") == "TARGET_CHECK" and named(event)
            and event.get("site") in target["check_sites"]
            and ("nodes" not in target or event.get("node") in target["nodes"]))


def events(trial: Path, result: dict, *, full: bool) -> tuple[list[dict], dict]:
    receipt = result["events_evidence"]
    path = trial / receipt["gzip_path"]
    gzip_hash = sha(path)
    if gzip_hash != receipt["gzip_sha256"] or path.stat().st_size != receipt["gzip_bytes"]:
        raise ValueError(f"gzip trace receipt mismatch: {path}")
    raw_hash = hashlib.sha256()
    raw_bytes = 0
    rows: list[dict] = []
    last_line = b""
    with gzip.open(path, "rb") as stream:
        for line in stream:
            last_line = line
            raw_hash.update(line)
            raw_bytes += len(line)
            if not line.strip():
                continue
            event = json.loads(line)
            if full or event.get("type") in KEEP_TYPES:
                rows.append(event)
    if (last_line and not last_line.endswith(b"\n") or
            raw_hash.hexdigest() != receipt["raw_sha256"] or
            raw_bytes != receipt["raw_bytes"]):
        raise ValueError(f"raw trace receipt mismatch: {path}")
    return rows, {"gzip_sha256": gzip_hash, "raw_sha256": raw_hash.hexdigest(),
                  "raw_bytes": raw_bytes}


def healthy_points(rows: list[dict], config: dict, healthy_result: dict) -> tuple[set[tuple], set[tuple], set[tuple], dict]:
    target = config["target"]
    trace = Trace(tuple(rows))
    checks = [row for row in rows if exact_check(row, target)]
    doors = [row for row in rows if row.get("type") == "DOOR_OBSERVED" and point(row)]
    legacy = OccurrenceGraph(trace.events)
    root_free = OccurrenceGraph(trace.events, reject_coarse_roots=True)
    legacy_ancestors = set()
    root_free_ancestors = set()
    for check in checks:
        address = event_address(check)
        legacy_ancestors.update(legacy.backward_closure(address, include_candidates=False) - {address})
        root_free_ancestors.update(root_free.backward_closure(address, include_candidates=False) - {address})
    # Bind the exact archived DOOR_OBSERVED event to the stored healthy door
    # receipt. This avoids conflating equal sites on different actors or hits.
    by_id = {row["id"]: row for row in doors}
    legacy_points = set()
    root_free_points = set()
    for door in healthy_result["feedback"]["doors"]:
        event = by_id.get(door.get("event_id"))
        if (event is None or event.get("site") != door.get("site") or
                event_seq(event) != door.get("event_seq") or
                point(event) != point(door.get("point", {}))):
            continue
        if event_address(event) in legacy_ancestors:
            legacy_points.add(point(event))
        if (event_address(event) in root_free_ancestors and
                any(root_free.event_path(event, check, require_edge=True) is not None
                    for check in checks)):
            root_free_points.add(point(event))
    local = analyze(trace, target, [], return_code=0, timed_out=False,
                    reject_coarse_roots=True, allow_local_timeline_doors=True)
    local_points = {point(door["point"]) for door in local["doors"]
                    if "local_timeline_evidence" in door and point(door["point"]) is not None}
    root_free_feedback = analyze(trace, target, [], return_code=0, timed_out=False,
                                 reject_coarse_roots=True)
    strict_feedback = analyze(trace, target, [], return_code=0, timed_out=False,
                              require_event_time_paths=True)
    diagnostics = {
        "exact_target_checks": len(checks), "observed_doors": len(doors),
        "numeric_thread_ids": sum(isinstance(row.get("thread_id"), int) for row in rows),
        "legacy_graph_edges": legacy.summary()["edges"],
        "root_free_graph_edges": root_free.summary()["edges"],
        "root_free_graph_gaps": root_free.summary()["gaps"],
        "root_free_closure_edges": len(root_free_feedback["closure_edges"]),
        "strict_event_time_closure_edges": len(strict_feedback["closure_edges"]),
        "legacy_exact_path_points": len(legacy_points),
        "root_free_exact_event_path_points": len(root_free_points),
        "root_free_local_timeline_points": len(local_points),
    }
    return legacy_points, root_free_points, local_points, diagnostics


def scan() -> dict:
    config = read(CAMPAIGN / "config.json")
    result = read(CAMPAIGN / "result.json")
    audit = read(CAMPAIGN / "offline-causal-audit.json")
    sync = read(CAMPAIGN / "sync-receipt.json")
    if (result["case_id"] != "SOLR-19" or result["status"] != "budget_exhausted" or
            audit["report_gate_passed"] is not True or audit["trial_count"] != 81 or
            sync["result_sha256"] != sha(CAMPAIGN / "result.json")):
        raise ValueError("canonical terminal/archive identity differs")
    target = config["target"]
    healthy_dir = CAMPAIGN / "trials/r0000"
    healthy_result = read(healthy_dir / "result.json")
    healthy_rows, healthy_trace = events(healthy_dir, healthy_result, full=True)
    legacy_points, root_free_points, local_points, healthy = healthy_points(
        healthy_rows, config, healthy_result)
    if healthy["legacy_exact_path_points"] != audit["healthy_observed_path_doors"]:
        raise ValueError("legacy observed-path count differs from frozen audit")

    counts: Counter[str] = Counter()
    trial_rows = []
    for trial_id in range(1, 81):
        trial = CAMPAIGN / "trials" / f"r{trial_id:04d}"
        trial_result = read(trial / "result.json")
        plan = read(trial / "plan.json")["faults"]
        if not plan:
            raise ValueError(f"expected at least one fault in trial {trial_id}")
        rows, trace = events(trial, trial_result, full=False)
        plan_ids = [fault["fault_id"] for fault in plan]
        unexpected = [row for row in rows if row.get("type") == "FAULT_APPLIED"
                      and row.get("fault_id") not in plan_ids]
        fault_rows = []
        for fault in plan:
            fid = fault["fault_id"]
            fault_point = point(fault["point"])
            matched = [row for row in rows if row.get("type") == "FAULT_MATCHED" and row.get("fault_id") == fid]
            applied = [row for row in rows if row.get("type") == "FAULT_APPLIED" and row.get("fault_id") == fid]
            observed = [row for row in rows if row.get("type") == "DOOR_OBSERVED" and point(row) == fault_point]
            effective = (fault_point is not None and len(matched) == len(applied) == len(observed) == 1
                         and point(matched[0]) == point(applied[0]) == fault_point
                         and event_seq(observed[0]) < event_seq(matched[0]) < event_seq(applied[0]))
            after = [row for row in rows if exact_check(row, target) and
                     effective and event_seq(row) > event_seq(applied[0])]
            same_actor = [row for row in after if event_address(row) == event_address(applied[0])]
            at_legacy = bool(effective and fault_point in legacy_points)
            at_root_free = bool(effective and fault_point in root_free_points)
            at_local = bool(effective and fault_point in local_points)
            direct_local = bool(same_actor and effective and
                                event_address(observed[0]) == event_address(applied[0]))
            counts["planned_faults"] += 1
            counts["individually_effective_faults"] += effective
            counts["effective_faults_then_exact_target"] += bool(after)
            counts["effective_faults_then_same_actor_occurrence_target"] += bool(same_actor)
            counts["effective_faults_at_legacy_healthy_path_point"] += at_legacy
            counts["effective_faults_at_legacy_healthy_path_point_then_target"] += bool(at_legacy and after)
            counts["effective_faults_at_healthy_root_free_path_point_then_target"] += bool(at_root_free and after)
            counts["effective_faults_at_healthy_local_point_then_same_actor_target"] += bool(at_local and direct_local)
            counts["fault_local_same_actor_occurrence_followups_without_healthy_admission"] += direct_local
            fault_rows.append({
                "fault_id": fid, "point": fault["point"], "individually_effective": bool(effective),
                "observed_door_event_id": observed[0].get("id") if len(observed) == 1 else None,
                "fault_applied_event_id": applied[0].get("id") if len(applied) == 1 else None,
                "fault_applied_seq": event_seq(applied[0]) if len(applied) == 1 else None,
                "post_exact_target_event_ids": [row["id"] for row in after],
                "post_same_actor_occurrence_target_event_ids": [row["id"] for row in same_actor],
                "at_legacy_healthy_path_point": at_legacy,
                "at_root_free_healthy_path_point": at_root_free,
                "at_healthy_local_timeline_point": at_local,
            })
        applied_ids = [row.get("fault_id") for row in rows if row.get("type") == "FAULT_APPLIED"]
        trial_effective = (all(row["individually_effective"] for row in fault_rows)
                           and not unexpected and applied_ids == plan_ids)
        if trial_effective != bool(trial_result["feedback"]["all_faults_effective"]):
            raise ValueError(f"effectiveness differs from frozen feedback in trial {trial_id}")
        last_applied_seq = max((row["fault_applied_seq"] for row in fault_rows
                                if row["fault_applied_seq"] is not None), default=-1)
        trial_after = [row for row in rows if exact_check(row, target) and trial_effective
                       and event_seq(row) > last_applied_seq]
        counts["fault_trials"] += 1
        counts["effective_trials"] += trial_effective
        counts["effective_trials_then_exact_target_after_all_faults"] += bool(trial_after)
        trial_rows.append({
            "trial_id": trial_id, "trial_result_sha256": sha(trial / "result.json"),
            "trace_gzip_sha256": trace["gzip_sha256"], "trial_effective": bool(trial_effective),
            "post_exact_target_after_all_faults_event_ids": [row["id"] for row in trial_after],
            "faults": fault_rows,
        })
    if (counts["fault_trials"] != result["fault_trials_completed"] or
            counts["effective_trials_then_exact_target_after_all_faults"] != audit["target_retained_fault_trials"]):
        raise ValueError("fault trial or retained target count differs from frozen audit")
    inputs = {name: sha(CAMPAIGN / name) for name in
              ("config.json", "result.json", "offline-causal-audit.json", "sync-receipt.json")}
    inputs["trials/r0000/result.json"] = sha(healthy_dir / "result.json")
    inputs["trials/r0000/events.jsonl.gz"] = healthy_trace["gzip_sha256"]
    source = {name: sha(REPO / f"Mallory/core/{name}") for name in
              ("events.py", "feedback.py", "graph.py", "audit.py")}
    return {"schema_version": 1, "case_id": "SOLR-19", "audit_kind": "v23b_root_free_exact_door_precision",
            "campaign": str(CAMPAIGN.relative_to(REPO)), "inputs_sha256": inputs,
            "scanner_sha256": sha(Path(__file__)), "current_core_source_sha256": source,
            "frozen_audit": {"report_gate_passed": audit["report_gate_passed"],
                             "healthy_observed_path_doors": audit["healthy_observed_path_doors"],
                             "target_retained_fault_trials": audit["target_retained_fault_trials"]},
            "criterion": "unique exact (site,node,epoch,door_ordinal) DOOR_OBSERVED and matching FAULT_MATCHED/FAULT_APPLIED; healthy root-free ordered observed graph path with at least one edge into exact TARGET_CHECK; effective fault then exact TARGET_CHECK. Local proof additionally requires healthy same-actor/epoch/occurrence pretarget door and postfault same-actor/epoch/occurrence target.",
            "healthy": healthy, "counts": dict(sorted(counts.items())), "trials": trial_rows,
            "finding": "legacy_occurrence_gate_passes_but_no_root_free_path_or_local_timeline_proof",
            "qualification": "The v23b agent emitted no numeric thread_id. Its legacy unscoped root/token occurrences lose all observed graph edges when coarse roots are rejected. Same-occurrence healthy doors do not precede the exact target. These archived trials cannot prove the current root-free event-time criterion; a new versioned healthy run would be needed.",
            "raw_campaign_mutated": False}


def main() -> None:
    result = scan()
    encoded = json.dumps(result, sort_keys=True, indent=2) + "\n"
    if OUT.exists() and OUT.read_text() != encoded:
        raise ValueError(f"immutable sidecar differs: {OUT}")
    OUT.write_text(encoded)
    print(json.dumps({"out": str(OUT), "sha256": sha(OUT), "counts": result["counts"],
                      "healthy": result["healthy"]}, sort_keys=True))


if __name__ == "__main__":
    main()
