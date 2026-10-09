#!/usr/bin/env python3
"""Read-only, offline causal-quality audit of one terminal Mallory campaign."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from .campaign import atomic_json, read_json
from .events import TraceError, event_address, event_seq, load_trace
from .feedback import _target_match, analyze, digest
from .graph import OccurrenceGraph

SCHEMA = 1
TERMINAL = {"budget_exhausted", "queue_exhausted", "healthy_seed_invalid",
            "healthy_node_identity_missing", "healthy_seed_ambiguous",
            "healthy_no_injectable_door", "healthy_attestation_failed",
            "fault_trials_not_attested", "calibration_complete"}
UNKNOWN_NODES = {"", "unknown", "null", "None"}


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _evidence_name(name: Any) -> str:
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError("trace evidence path must be one filename inside its trial directory")
    return name


def _load_archived_trace(trial_dir: Path, result: dict[str, Any]):
    receipt = result.get("events_evidence", {})
    if not isinstance(receipt, dict):
        raise ValueError("events_evidence is absent")
    gzip_name = receipt.get("gzip_path")
    raw_name = receipt.get("raw_path")
    if bool(gzip_name) == bool(raw_name):
        raise ValueError("exactly one raw or compressed event path is required")
    name = _evidence_name(gzip_name or raw_name)
    path = trial_dir / name
    if not path.is_file():
        raise FileNotFoundError(path)
    expected_raw_hash = receipt.get("raw_sha256") or result.get("events_sha256")
    if not isinstance(expected_raw_hash, str) or len(expected_raw_hash) != 64:
        raise ValueError("raw trace SHA-256 receipt is absent")
    if gzip_name:
        if _sha256(path) != receipt.get("gzip_sha256"):
            raise ValueError("compressed trace SHA-256 mismatch")
        if receipt.get("gzip_bytes") is not None and path.stat().st_size != receipt["gzip_bytes"]:
            raise ValueError("compressed trace byte count mismatch")
        with tempfile.TemporaryDirectory(prefix="mallory-causal-audit-") as temporary:
            raw = Path(temporary) / "events.jsonl"
            try:
                with gzip.open(path, "rb") as source, raw.open("wb") as sink:
                    shutil.copyfileobj(source, sink, 1024 * 1024)
            except (OSError, EOFError) as exc:
                raise ValueError("compressed trace cannot be decoded") from exc
            if _sha256(raw) != expected_raw_hash:
                raise ValueError("decompressed trace SHA-256 mismatch")
            if receipt.get("raw_bytes") is not None and raw.stat().st_size != receipt["raw_bytes"]:
                raise ValueError("decompressed trace byte count mismatch")
            trace = load_trace(raw)
    else:
        if _sha256(path) != expected_raw_hash:
            raise ValueError("raw trace SHA-256 mismatch")
        if receipt.get("raw_bytes") is not None and path.stat().st_size != receipt["raw_bytes"]:
            raise ValueError("raw trace byte count mismatch")
        trace = load_trace(path)
    if trace.incomplete_last_line:
        raise ValueError("trace has an incomplete final JSONL line")
    return trace, {"path": str(path), "raw_sha256": expected_raw_hash,
                   "compressed": bool(gzip_name), "verified": True}


def _named(node: Any) -> bool:
    return isinstance(node, str) and node not in UNKNOWN_NODES


def _exact_point(point: dict[str, Any]) -> bool:
    common = ("site", "node", "epoch")
    if not _named(point.get("node")) or any(point.get(key) is None for key in common):
        return False
    ordinal = point.get("door_ordinal")
    if isinstance(ordinal, int) and not isinstance(ordinal, bool) and ordinal > 0:
        return "occurrence" not in point and "hit" not in point
    return (isinstance(point.get("occurrence"), str) and bool(point["occurrence"])
            and isinstance(point.get("hit"), int) and point["hit"] > 0)


def _matches_point(event: dict[str, Any], point: dict[str, Any]) -> bool:
    keys = (("site", "node", "epoch", "door_ordinal") if "door_ordinal" in point else
            ("site", "node", "epoch", "occurrence", "hit"))
    return all(event.get(key) == point.get(key) for key in keys)


def _audit_faults(events: tuple[dict[str, Any], ...],
                  plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for fault in plan:
        point = fault.get("point") if isinstance(fault, dict) else None
        if not isinstance(point, dict):
            point = {}
        fid = fault.get("fault_id") if isinstance(fault, dict) else None
        doors = [e for e in events if e.get("type") == "DOOR_OBSERVED"
                 and _matches_point(e, point)] if _exact_point(point) else []
        matched = [e for e in events if e.get("type") == "FAULT_MATCHED"
                   and e.get("fault_id") == fid]
        applied = [e for e in events if e.get("type") == "FAULT_APPLIED"
                   and e.get("fault_id") == fid]
        receipts_exact = (len(matched) == len(applied) == 1 and
                          _matches_point(matched[0], point) and
                          _matches_point(applied[0], point)) if _exact_point(point) else False
        rows.append({"fault_id": fid, "point": point,
                     "named_actor": _named(point.get("node")),
                     "exact_point": _exact_point(point),
                     "observed_door_matches": len(doors),
                     "observed_door_event_ids": [e.get("id") for e in doors],
                     "matched_receipts": len(matched),
                     "matched_event_ids": [e.get("id") for e in matched],
                     "applied_receipts": len(applied),
                     "applied_event_ids": [e.get("id") for e in applied],
                     "receipts_exact": receipts_exact,
                     "applied_identity_valid": (not applied or
                                                len(doors) == 1 and receipts_exact)})
    return rows


def _door_membership(feedback: dict[str, Any]) -> dict[str, bool]:
    rows: dict[str, bool] = {}
    for door in feedback.get("doors", []):
        point = door.get("point")
        if not isinstance(point, dict):
            point = {}
        key = digest([door.get("event_id"), door.get("site"), door.get("event_seq"),
                      point.get("node"), point.get("epoch")])
        rows[key] = bool(door.get("in_closure"))
    return rows


def _membership_receipt(rows: dict[str, bool]) -> dict[str, Any]:
    encoded = json.dumps(sorted(rows.items()), separators=(",", ":")).encode()
    return {"count": len(rows), "sha256": hashlib.sha256(encoded).hexdigest(),
            "in_closure_count": sum(rows.values())}


def _edge_fingerprints(feedback: dict[str, Any]) -> set[str]:
    return {digest([edge["source"], edge["target"], edge["kind"], edge["certainty"]])
            for edge in feedback.get("closure_edges", [])}


def _same_actor_target_followups(events: tuple[dict[str, Any], ...],
                                 target: dict[str, Any],
                                 plan: list[dict[str, Any]],
                                 effective: bool,
                                 admitted_local_sites: set[str],
                                 doors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prove a selected check after an applied fault in the same exact occurrence.

    This is a stricter post-fault observation for local-timeline guidance.
    Generic target reach may come from another actor or another occurrence.
    """
    if not plan or not effective or not admitted_local_sites:
        return []
    points = {fault.get("fault_id"): fault.get("point") for fault in plan}
    local_doors = {door.get("event_id") for door in doors
                   if door.get("site") in admitted_local_sites and
                   "local_timeline_evidence" in door}
    checks: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.get("type") != "TARGET_CHECK" or not _target_match(
                event, target, throwing=False):
            continue
        address = event_address(event)
        if address is not None and _named(event.get("node")):
            checks.setdefault(address, []).append(event)
    proofs = []
    for fault in events:
        if fault.get("type") != "FAULT_APPLIED" or fault.get("fault_id") not in points:
            continue
        point = points[fault.get("fault_id")]
        if (not isinstance(point, dict) or fault.get("site") not in admitted_local_sites or
                not _exact_point(point)):
            continue
        observed = [door for door in events if door.get("type") == "DOOR_OBSERVED"
                    and _matches_point(door, point)]
        if len(observed) != 1 or observed[0].get("id") not in local_doors:
            continue
        address = event_address(fault)
        if address is None or not _named(fault.get("node")):
            continue
        check = next((row for row in checks.get(address, [])
                      if event_seq(row) > event_seq(fault)), None)
        if check is not None:
            proofs.append({"fault_id": fault.get("fault_id"),
                           "fault_event_id": fault.get("id"),
                           "fault_seq": event_seq(fault),
                           "target_check_event_id": check.get("id"),
                           "target_check_seq": event_seq(check),
                           "target_check_site": check.get("site"),
                           "door_event_id": observed[0].get("id"),
                           "door_site": observed[0].get("site"),
                           "node": fault["node"], "epoch": fault["epoch"],
                           "occurrence": fault["occurrence"]})
    return proofs


def audit_campaign(campaign: Path, out: Path) -> dict[str, Any]:
    campaign = campaign.resolve()
    out = out.resolve()
    if out == campaign or (campaign in out.parents and
                           out != campaign / "offline-causal-audit.json"):
        raise ValueError("only offline-causal-audit.json may be written inside the campaign")
    summary_path = campaign / "result.json"
    summary = read_json(summary_path)
    config = read_json(campaign / "config.json")
    if summary.get("status") not in TERMINAL:
        raise ValueError("campaign is not terminal")
    if summary.get("case_id") != config.get("case_id"):
        raise ValueError("campaign result and config case IDs differ")
    binding = summary.get("target_binding") or {}
    rows: list[dict[str, Any]] = []
    old_coverage: set[str] = set()
    old_closure: set[str] = set()
    old_edges: set[str] = set()
    gaps: Counter[str] = Counter()
    unknown_applied = named_applied = target_retained = same_actor_target_trials = 0
    healthy_closure_observed_edges = 0
    healthy_closure_included_named_doors = 0
    healthy_observed_path_doors = 0
    healthy_local_timeline_doors = 0
    healthy_local_timeline_sites: set[str] = set()
    healthy_local_timeline_evidence_sample: list[dict[str, Any]] = []
    healthy_event_time_path_sample: list[dict[str, Any]] = []
    healthy_target_reached = False
    healthy_target_nonthrowing = False
    for entry in sorted(summary.get("trials", []), key=lambda row: row["trial_id"]):
        trial_id = entry["trial_id"]
        result_path = campaign / "trials" / f"r{trial_id:04d}" / "result.json"
        row: dict[str, Any] = {"trial_id": trial_id, "result_path": str(result_path),
                               "archive_integrity_valid": False,
                               "guidance_consistent": False,
                               "target_claim_reverified": False}
        try:
            result = read_json(result_path)
            if result.get("case_id") != config["case_id"] or result.get("trial_id") != trial_id:
                raise ValueError("trial result identity differs from case/trial directory")
            if entry.get("result") != str(result_path.relative_to(campaign)):
                raise ValueError("summary trial result path differs from archived trial")
            trace, evidence = _load_archived_trace(result_path.parent, result)
            plan = result.get("plan", [])
            if not isinstance(plan, list):
                raise ValueError("trial plan is not a list")
            target = {**config["target"], **(binding if trial_id > 0 else {})}
            recomputed = analyze(trace, target, plan,
                                 return_code=result.get("return_code"),
                                 timed_out=bool(result.get("timed_out")),
                                 allow_local_timeline_doors=config.get(
                                     "allow_local_timeline_doors", False),
                                 reject_coarse_roots=config.get("reject_coarse_roots", False),
                                 require_event_time_paths=config.get(
                                     "require_event_time_paths", False))
            old = result.get("feedback", {})
            if trial_id == 0:
                healthy_closure_observed_edges = sum(
                    edge.get("certainty") == "observed"
                    for edge in recomputed.get("closure_edges", []))
                healthy_closure_included_named_doors = sum(
                    bool(door.get("in_closure")) and
                    _named(door.get("point", {}).get("node"))
                    for door in recomputed.get("doors", []))
                healthy_target_reached = bool(recomputed.get("target_reached"))
                healthy_target_nonthrowing = not bool(recomputed.get("target_threw"))
                local_evidence = [door["local_timeline_evidence"]
                                  for door in recomputed.get("doors", [])
                                  if "local_timeline_evidence" in door]
                healthy_local_timeline_doors = len(local_evidence)
                healthy_local_timeline_sites = {
                    str(door["site"]) for door in recomputed.get("doors", [])
                    if "local_timeline_evidence" in door and isinstance(door.get("site"), str)}
                healthy_local_timeline_evidence_sample = local_evidence[:10]
                graph = OccurrenceGraph(
                    trace.events,
                    reject_coarse_roots=(config.get("reject_coarse_roots", False) or
                                         config.get("require_event_time_paths", False)))
                # The future gate binds each door to an exact target check
                # through ordered event IDs. Legacy audits retain their
                # original occurrence-level meaning.
                event_time_gate = bool(config.get("require_event_time_paths", False))
                observed_ancestors = set()
                if not event_time_gate:
                    for target_row in recomputed.get("target_closures", []):
                        anchor = target_row.get("anchor")
                        if anchor:
                            observed_ancestors.update(
                                graph.backward_closure(anchor, include_candidates=False) - {anchor})
                door_events: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
                for event in trace.events:
                    if event.get("type") != "DOOR_OBSERVED":
                        continue
                    key = (event.get("id"), event.get("site"), event.get("seq"),
                           event.get("node"), event.get("epoch"))
                    door_events.setdefault(key, []).append(event)
                target_events = [event for event in trace.events
                                 if event.get("type") == "TARGET_CHECK" and
                                 _named(event.get("node")) and
                                 _target_match(event, target, throwing=False)]
                for door in recomputed.get("doors", []):
                    if (not door.get("in_closure") or
                            not _named(door.get("point", {}).get("node"))):
                        continue
                    key = (door.get("event_id"), door.get("site"), door.get("event_seq"),
                           door.get("point", {}).get("node"),
                           door.get("point", {}).get("epoch"))
                    matches = door_events.get(key, [])
                    if len(matches) != 1:
                        continue
                    if event_time_gate:
                        for check in target_events:
                            witness = graph.event_path(matches[0], check, require_edge=True)
                            if witness is None:
                                continue
                            healthy_observed_path_doors += 1
                            if len(healthy_event_time_path_sample) < 10:
                                healthy_event_time_path_sample.append({
                                    "door_event_id": matches[0].get("id"),
                                    "target_check_event_id": check.get("id"),
                                    "door_seq": event_seq(matches[0]),
                                    "target_check_seq": event_seq(check),
                                    "edges": [{"producer_event": edge.producer_event,
                                               "consumer_event": edge.consumer_event,
                                               "kind": edge.kind}
                                              for edge in witness]})
                            break
                    elif event_address(matches[0]) in observed_ancestors:
                        healthy_observed_path_doors += 1
            faults = _audit_faults(trace.events, plan)
            applied_events = [e for e in trace.events if e.get("type") == "FAULT_APPLIED"]
            unknown_applied += sum(not _named(e.get("node")) for e in applied_events)
            named_applied += sum(_named(e.get("node")) for e in applied_events)
            if plan and recomputed["all_faults_effective"] and recomputed["target_reached"]:
                target_retained += 1
            for key, count in recomputed["graph"]["gaps"].items():
                gaps[key] += count
            new_coverage = set(recomputed["coverage_ids"])
            new_closure = set(recomputed["closure_coverage_ids"])
            new_edges = _edge_fingerprints(recomputed)
            novelty = {"coverage": len(new_coverage - old_coverage),
                       "closure_coverage": len(new_closure - old_closure),
                       "closure_edges": len(new_edges - old_edges)}
            old_coverage |= new_coverage
            old_closure |= new_closure
            old_edges |= new_edges
            old_membership = _door_membership(old)
            new_membership = _door_membership(recomputed)
            membership_consistent = old_membership == new_membership
            changed_door_keys = sorted(set(old_membership) | set(new_membership))
            changed_door_keys = [key for key in changed_door_keys
                                 if old_membership.get(key) != new_membership.get(key)]
            novelty_consistent = result.get("novelty") == novelty
            closure_occurrences_consistent = (set(old.get("closure_occurrences", [])) ==
                                              set(recomputed["closure_occurrences"]))
            closure_edges_consistent = (_edge_fingerprints(old) ==
                                        _edge_fingerprints(recomputed))
            guidance_consistent = (membership_consistent and novelty_consistent and
                                   closure_occurrences_consistent and closure_edges_consistent)
            old_claim = bool(old.get("target_exception_candidate"))
            claim_reverified = not old_claim or bool(recomputed["target_exception_candidate"])
            applied_identity_valid = all(fault["applied_identity_valid"] for fault in faults)
            # An unexpected applied fault with no plan identity is never safe.
            applied_identity_valid = (applied_identity_valid and
                                      not recomputed["unexpected_applied_fault_ids"])
            same_actor_followups = _same_actor_target_followups(
                trace.events, target, plan,
                bool(recomputed["all_faults_effective"] and applied_identity_valid),
                healthy_local_timeline_sites, recomputed.get("doors", []))
            if same_actor_followups:
                same_actor_target_trials += 1
            row.update({"archive_integrity_valid": True, "trace_evidence": evidence,
                        "event_count": len(trace.events), "selection_reason": result.get("selection_reason"),
                        "faults": faults, "applied_identity_valid": applied_identity_valid,
                        "old_status": old.get("status"),
                        "recomputed_status": recomputed["status"],
                        "old_target_exception_candidate": old_claim,
                        "recomputed_target_exception_candidate": recomputed["target_exception_candidate"],
                        "target_claim_reverified": claim_reverified,
                        "target_retained": bool(plan and recomputed["all_faults_effective"] and
                                                recomputed["target_reached"]),
                        "same_actor_target_after_fault": bool(same_actor_followups),
                        "same_actor_target_followups": same_actor_followups,
                        "old_graph": old.get("graph"),
                        "recomputed_graph": recomputed["graph"],
                        "graph_changed": old.get("graph") != recomputed["graph"],
                        "old_eligible_door_membership": _membership_receipt(old_membership),
                        "recomputed_eligible_door_membership": _membership_receipt(new_membership),
                        "eligible_door_membership_diff_count": len(changed_door_keys),
                        "eligible_door_membership_diff_sample": [
                            {"event_key": key, "old": old_membership.get(key),
                             "recomputed": new_membership.get(key)}
                            for key in changed_door_keys[:10]],
                        "eligible_door_membership_consistent": membership_consistent,
                        "closure_occurrences_consistent": closure_occurrences_consistent,
                        "closure_edges_consistent": closure_edges_consistent,
                        "old_novelty": result.get("novelty"),
                        "recomputed_novelty": novelty,
                        "closure_novelty_consistent": novelty_consistent,
                        "guidance_consistent": guidance_consistent})
        except (FileNotFoundError, OSError, ValueError, KeyError, TraceError) as exc:
            row["error"] = str(exc)
        rows.append(row)
    archive_ok = bool(rows) and all(row["archive_integrity_valid"] for row in rows)
    identity_ok = archive_ok and all(row.get("applied_identity_valid", False) for row in rows)
    target_ok = archive_ok and all(row["target_claim_reverified"] for row in rows)
    guidance_ok = archive_ok and all(row["guidance_consistent"] for row in rows)
    allow_local_timeline = config.get("allow_local_timeline_doors", False)
    healthy_closure_evidence_types = (["observed_graph_path"]
                                      if healthy_observed_path_doors > 0 else [])
    if allow_local_timeline and healthy_local_timeline_doors > 0:
        healthy_closure_evidence_types.append("observed_local_timeline")
    healthy_closure_proven = (archive_ok and healthy_target_reached and
                              healthy_target_nonthrowing and
                              (healthy_observed_path_doors > 0 or
                               allow_local_timeline and healthy_local_timeline_doors > 0))
    local_timeline_only = (allow_local_timeline and healthy_observed_path_doors == 0
                           and healthy_local_timeline_doors > 0)
    same_actor_target_required = (local_timeline_only and
                                  summary["status"] in {"budget_exhausted", "queue_exhausted"})
    same_actor_target_gate_passed = (not same_actor_target_required or
                                     same_actor_target_trials > 0)
    result = {"schema_version": SCHEMA, "audit_kind": "offline_causal_quality",
              "case_id": config["case_id"], "campaign_dir": str(campaign),
              "core_source_sha256": {name: _sha256(Path(__file__).with_name(name))
                                     for name in ("audit.py", "events.py", "graph.py",
                                                  "feedback.py", "campaign.py")},
              "campaign_result_sha256": _sha256(summary_path),
              "terminal_status": summary["status"], "trial_count": len(rows),
              "archive_integrity_valid": archive_ok,
              "applied_fault_identity_valid": identity_ok,
              "target_claims_reverified": target_ok,
              "guidance_consistent": guidance_ok,
              "healthy_closure_observed_edges": healthy_closure_observed_edges,
              "healthy_closure_included_named_doors": healthy_closure_included_named_doors,
              "healthy_observed_path_doors": healthy_observed_path_doors,
              "healthy_event_time_path_sample": healthy_event_time_path_sample,
              "healthy_local_timeline_doors": healthy_local_timeline_doors,
              "healthy_local_timeline_sites": sorted(healthy_local_timeline_sites),
              "healthy_local_timeline_evidence_sample": healthy_local_timeline_evidence_sample,
              "healthy_closure_evidence_types": healthy_closure_evidence_types,
              "allow_local_timeline_doors": allow_local_timeline,
              "reject_coarse_roots": bool(config.get("reject_coarse_roots", False) or
                                          config.get("require_event_time_paths", False)),
              "require_event_time_paths": bool(config.get("require_event_time_paths", False)),
              "local_timeline_only": local_timeline_only,
              "same_actor_target_required": same_actor_target_required,
              "same_actor_target_gate_passed": same_actor_target_gate_passed,
              "same_actor_target_trials": same_actor_target_trials,
              "healthy_target_nonthrowing": healthy_target_nonthrowing,
              "healthy_closure_proven": healthy_closure_proven,
              "report_gate_passed": (archive_ok and identity_ok and target_ok and
                                     guidance_ok and healthy_closure_proven and
                                     same_actor_target_gate_passed),
              "graph_guidance_changed_trials": [row["trial_id"] for row in rows
                                                if row.get("graph_changed")],
              "named_applied_faults": named_applied,
              "unknown_applied_faults": unknown_applied,
              "target_retained_fault_trials": target_retained,
              "observed_edges_total": sum(row.get("recomputed_graph", {}).get("edges", 0)
                                          for row in rows),
              "candidate_edges_total": sum(row.get("recomputed_graph", {}).get("candidate_edges", 0)
                                           for row in rows),
              "gap_counts": dict(sorted(gaps.items())), "trials": rows}
    atomic_json(out, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    artifact = audit_campaign(args.campaign, args.out)
    print(json.dumps({key: artifact[key] for key in
                      ("case_id", "terminal_status", "trial_count", "report_gate_passed",
                       "graph_guidance_changed_trials")}, sort_keys=True))
    return 0 if artifact["report_gate_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
