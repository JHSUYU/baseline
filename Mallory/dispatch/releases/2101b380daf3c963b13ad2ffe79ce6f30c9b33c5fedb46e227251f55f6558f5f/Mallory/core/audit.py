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
from .events import TraceError, event_address, load_trace
from .feedback import analyze, digest
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
    unknown_applied = named_applied = target_retained = 0
    healthy_closure_observed_edges = 0
    healthy_closure_included_named_doors = 0
    healthy_observed_path_doors = 0
    healthy_target_reached = False
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
                                 timed_out=bool(result.get("timed_out")))
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
                graph = OccurrenceGraph(trace.events)
                # Exclude the anchor itself: a qualifying door must have a
                # nonempty, entirely observed causal path into the target.
                observed_ancestors = set()
                for target_row in recomputed.get("target_closures", []):
                    anchor = target_row.get("anchor")
                    if anchor:
                        observed_ancestors.update(
                            graph.backward_closure(anchor, include_candidates=False) - {anchor})
                door_addresses: dict[tuple[Any, ...], list[str | None]] = {}
                for event in trace.events:
                    if event.get("type") != "DOOR_OBSERVED":
                        continue
                    key = (event.get("id"), event.get("site"), event.get("seq"),
                           event.get("node"), event.get("epoch"))
                    door_addresses.setdefault(key, []).append(event_address(event))
                healthy_observed_path_doors = sum(
                    bool(door.get("in_closure")) and
                    _named(door.get("point", {}).get("node")) and
                    len(addresses := door_addresses.get((
                        door.get("event_id"), door.get("site"), door.get("event_seq"),
                        door.get("point", {}).get("node"),
                        door.get("point", {}).get("epoch")), [])) == 1 and
                    addresses[0] in observed_ancestors
                    for door in recomputed.get("doors", []))
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
    healthy_closure_proven = (archive_ok and healthy_target_reached and
                              healthy_closure_observed_edges > 0 and
                              healthy_closure_included_named_doors > 0 and
                              healthy_observed_path_doors > 0)
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
              "healthy_closure_proven": healthy_closure_proven,
              "report_gate_passed": (archive_ok and identity_ok and target_ok and
                                     guidance_ok and healthy_closure_proven),
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
