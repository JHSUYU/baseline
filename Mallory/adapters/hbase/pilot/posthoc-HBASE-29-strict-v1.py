#!/usr/bin/env python3
"""Fail-closed, read-only event-time review of the completed HBASE-29 campaign."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from Mallory.core.graph import OccurrenceGraph
import Mallory.core.graph as graph_module


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_digest(path: Path) -> str:
    return sha256(path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--core-release", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    campaign = args.campaign.resolve()
    expected_graph = (args.core_release / "Mallory/core/graph.py").resolve()
    if Path(graph_module.__file__).resolve() != expected_graph:
        raise SystemExit("wrong graph module loaded; pin PYTHONPATH to --core-release")
    case_result = json.loads((campaign / "result.json").read_text())
    if case_result.get("case_id") != "HBASE-29" or case_result.get("status") not in {
        "budget_exhausted", "queue_exhausted"
    }:
        raise SystemExit("wrong or nonterminal campaign")

    counts = {
        "fault_trials": 0, "fault_trials_with_later_target": 0,
        "fault_trials_with_later_same_actor_target": 0,
        "fault_trials_with_later_same_occurrence_target": 0,
        "fault_trials_with_strict_event_path": 0,
    }
    trials = []
    for trial_dir in sorted((campaign / "trials").glob("r[0-9][0-9][0-9][0-9]")):
        if trial_dir.name == "r0000":
            continue
        result_path = trial_dir / "result.json"
        gzip_path = trial_dir / "events.jsonl.gz"
        if not result_path.exists() or not gzip_path.exists():
            raise SystemExit(f"missing terminal evidence: {trial_dir}")
        result_bytes = result_path.read_bytes()
        trial_result = json.loads(result_bytes)
        compressed = gzip_path.read_bytes()
        raw = gzip.decompress(compressed)
        evidence = trial_result.get("events_evidence", {})
        if evidence.get("gzip_sha256") != sha256(compressed):
            raise SystemExit(f"gzip SHA mismatch: {trial_dir}")
        if evidence.get("raw_sha256") != sha256(raw):
            raise SystemExit(f"raw SHA mismatch: {trial_dir}")
        events = tuple(json.loads(line) for line in raw.splitlines())
        if any(not isinstance(event.get("seq"), int) for event in events):
            raise SystemExit(f"missing numeric event sequence: {trial_dir}")
        graph = OccurrenceGraph(events, reject_coarse_roots=True)
        faults = [event for event in events if event.get("type") == "FAULT_APPLIED"]
        targets = [event for event in events if event.get("type") == "TARGET_CHECK"]
        if not faults:
            continue
        counts["fault_trials"] += 1
        later = [(fault, target) for fault in faults for target in targets
                 if target["seq"] > fault["seq"]]
        same_actor = [(fault, target) for fault, target in later
                      if (fault.get("node"), fault.get("epoch")) ==
                      (target.get("node"), target.get("epoch"))
                      and fault.get("node") != "unknown"]
        same_occurrence = [(fault, target) for fault, target in same_actor
                           if fault.get("occurrence") == target.get("occurrence")]
        strict_witness = None
        if graph.edges:
            for fault, target in later:
                path = graph.event_path(fault, target, require_edge=True)
                if path:
                    strict_witness = {
                        "fault_event": fault["id"], "target_event": target["id"],
                        "edge_kinds": [edge.kind for edge in path],
                    }
                    break
        counts["fault_trials_with_later_target"] += bool(later)
        counts["fault_trials_with_later_same_actor_target"] += bool(same_actor)
        counts["fault_trials_with_later_same_occurrence_target"] += bool(same_occurrence)
        counts["fault_trials_with_strict_event_path"] += bool(strict_witness)
        trials.append({
            "trial": trial_dir.name,
            "result_sha256": sha256(result_bytes),
            "gzip_sha256": sha256(compressed),
            "raw_sha256": sha256(raw),
            "fault_events": [event["id"] for event in faults],
            "later_target_count": len(later),
            "later_same_actor_target_count": len(same_actor),
            "later_same_occurrence_target_count": len(same_occurrence),
            "strict_graph_edges": len(graph.edges),
            "strict_witness": strict_witness,
        })

    report = {
        "schema_version": 1,
        "case_id": "HBASE-29",
        "classification": "faulted_path_unverified" if not counts[
            "fault_trials_with_strict_event_path"] else "strict_path_candidate_needs_review",
        "method": "OccurrenceGraph(reject_coarse_roots=True).event_path(FAULT_APPLIED,TARGET_CHECK,require_edge=True)",
        "require_numeric_seq": True,
        "campaign_result_sha256": source_digest(campaign / "result.json"),
        "campaign_audit_sha256": source_digest(campaign / "offline-causal-audit.json"),
        "core_release_manifest_sha256": source_digest(args.core_release / "manifest.json"),
        "core_graph_sha256": source_digest(expected_graph),
        "counts": counts,
        "trials": trials,
        "limitation": "Named same-actor target retention does not establish an observed fault-to-target path. No quality promotion or bug claim follows from this review.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out.exists():
        if args.out.read_text() != output:
            raise SystemExit("existing immutable receipt differs")
    else:
        args.out.write_text(output)
    print(json.dumps({"counts": counts, "receipt_sha256": sha256(output.encode())}, sort_keys=True))


if __name__ == "__main__":
    main()
