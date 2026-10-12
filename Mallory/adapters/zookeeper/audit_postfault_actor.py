#!/usr/bin/env python3
"""Check exact or observed-path target retention after each applied fault."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def trace(trial_dir: Path, result: dict) -> tuple[dict, ...]:
    receipt = result["events_evidence"]
    name = receipt.get("gzip_path") or receipt.get("raw_path")
    if not name or Path(name).name != name:
        raise ValueError("trace evidence path is not local to trial")
    path = trial_dir / name
    if name.endswith(".gz"):
        if sha(path) != receipt["gzip_sha256"]:
            raise ValueError("compressed trace SHA mismatch")
        with gzip.open(path, "rb") as source:
            raw = source.read()
    else:
        raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt["raw_sha256"]:
        raise ValueError("raw trace SHA mismatch")
    return tuple(json.loads(line) for line in raw.splitlines() if line)


def observed_path(graph: OccurrenceGraph, fault: dict,
                  checks: list[dict]) -> list[dict]:
    # Reuse the pinned core's event-time proof. It checks each edge's exact
    # producer/consumer IDs and the JVM thread at each occurrence. A bounded
    # thread-scoped root may be valid; a legacy actor-wide root is rejected
    # by OccurrenceGraph(reject_coarse_roots=True).
    for check in checks:
        witness = graph.event_path(fault, check, require_edge=True)
        if witness is not None:
            return [{
                "kind": edge.kind, "producer_event": edge.producer_event,
                "consumer_event": edge.consumer_event,
                "source": edge.source, "target": edge.target,
            } for edge in witness]
    return []


def audit(campaign: Path, output: Path, superseded: Path | None) -> None:
    summary_path = campaign / "result.json"
    old_audit_path = campaign / "offline-causal-audit.json"
    summary, old_audit, config = read(summary_path), read(old_audit_path), read(campaign / "config.json")
    if not (summary["status"] in {"budget_exhausted", "queue_exhausted"} and
            old_audit["report_gate_passed"] is True and
            old_audit["campaign_result_sha256"] == sha(summary_path)):
        raise ValueError("terminal pilot and original audit must be intact")
    sites = set(config["target"]["check_sites"])
    rows = []
    for trial in summary["trials"]:
        if trial["trial_id"] == 0:
            continue
        trial_dir = campaign / "trials" / f"r{trial['trial_id']:04d}"
        result = read(trial_dir / "result.json")
        events = trace(trial_dir, result)
        graph = OccurrenceGraph(
            events, reject_coarse_roots=bool(config.get("reject_coarse_roots", False)))
        checks = [row for row in events if row.get("type") == "TARGET_CHECK"
                  and row.get("site") in sites]
        for fault in (row for row in events if row.get("type") == "FAULT_APPLIED"):
            later = [row for row in checks if row["seq"] > fault["seq"]]
            scoped_origin = (isinstance(fault.get("occurrence"), str) and
                             not graph._is_coarse_root(fault) and
                             not graph._is_legacy_unscoped(fault))
            exact = [row for row in later if scoped_origin and all(
                row.get(key) == fault.get(key) for key in
                ("node", "epoch", "occurrence", "thread_id"))]
            path = observed_path(graph, fault, later) if scoped_origin else []
            rows.append({
                "trial_id": trial["trial_id"], "selection_reason": result.get("selection_reason"),
                "fault_event_id": fault.get("id"), "fault_seq": fault["seq"],
                "fault_site": fault.get("site"), "fault_node": fault.get("node"),
                "fault_epoch": fault.get("epoch"), "fault_occurrence": fault.get("occurrence"),
                "fault_scope_valid": scoped_origin,
                "scope_rejection": None if scoped_origin else "unscoped_fault_origin",
                "later_exact_check_event_ids": [row["id"] for row in exact],
                "later_any_check_event_ids": [row["id"] for row in later],
                "observed_path": path,
                "postfault_target_causality_proven": bool(exact or path),
            })
    proven = sum(row["postfault_target_causality_proven"] for row in rows)
    record = {
        "schema_version": 2, "case_id": summary["case_id"],
        "status": "postfault_target_causality_proven" if proven else "no_proven_postfault_target_causality",
        "pilot_result": str(summary_path.resolve()), "pilot_result_sha256": sha(summary_path),
        "original_offline_audit": str(old_audit_path.resolve()),
        "original_offline_audit_sha256": sha(old_audit_path),
        "original_audit_gate_passed": old_audit["report_gate_passed"],
        "applied_fault_count": len(rows), "proven_fault_count": proven,
        "exact_same_occurrence_count": sum(bool(row["later_exact_check_event_ids"]) for row in rows),
        "time_respecting_observed_path_count": sum(bool(row["observed_path"]) for row in rows),
        "faults": rows,
    }
    if superseded is not None:
        record["supersedes_admission"] = str(superseded.resolve())
        record["supersedes_admission_sha256"] = sha(superseded)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--supersedes-admission", type=Path)
    args = parser.parse_args()
    audit(args.campaign.resolve(), args.output.resolve(),
          args.supersedes_admission.resolve() if args.supersedes_admission else None)
