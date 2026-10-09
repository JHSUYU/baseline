#!/usr/bin/env python3
"""Read-only, SHA-bound fault-to-target path audit for terminal Solr campaigns."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import Mallory.core.graph as graph_module
from Mallory.core.graph import OccurrenceGraph


CASES = ("SOLR-05", "SOLR-19", "SOLR-31", "SOLR-36")
TERMINAL = {"budget_exhausted", "queue_exhausted"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def trial_events(trial_dir: Path, trial: dict) -> tuple[list[dict], dict]:
    evidence = trial["events_evidence"]
    packed_path = (trial_dir / evidence["gzip_path"]).resolve()
    if not packed_path.is_relative_to(trial_dir.resolve()):
        raise ValueError("event path escapes trial")
    packed = packed_path.read_bytes()
    if sha(packed) != evidence["gzip_sha256"] or len(packed) != evidence["gzip_bytes"]:
        raise ValueError(f"gzip SHA/bytes mismatch: {trial_dir}")
    raw = gzip.decompress(packed)
    if (sha(raw) != evidence["raw_sha256"] or
            len(raw) != evidence["raw_bytes"] or
            sha(raw) != trial["events_sha256"]):
        raise ValueError(f"raw SHA/bytes mismatch: {trial_dir}")
    events = [json.loads(line) for line in raw.splitlines() if line]
    return events, {"events_gzip_sha256": sha(packed),
                    "events_raw_sha256": sha(raw), "events_raw_bytes": len(raw)}


def exact_fault(events: list[dict], plan: dict) -> list[dict]:
    """Require a unique planned, matched and observed applied fault identity."""
    point = plan["point"]
    fault_id = plan["fault_id"]
    applied = [e for e in events if e.get("type") == "FAULT_APPLIED" and
               e.get("fault_id") == fault_id]
    matched = [e for e in events if e.get("type") == "FAULT_MATCHED" and
               e.get("fault_id") == fault_id]
    if len(applied) != 1 or len(matched) != 1:
        return []
    fault, match = applied[0], matched[0]
    keys = ("site", "node", "epoch", "door_ordinal")
    if (any(fault.get(k) != point.get(k) or match.get(k) != point.get(k) for k in keys)
            or fault.get("fault_type") != plan.get("fault_type")
            or match.get("fault_type") != plan.get("fault_type")
            or fault.get("exception_class") != plan.get("exception_class")
            or match.get("exception_class") != plan.get("exception_class")):
        return []
    doors = [e for e in events if e.get("type") == "DOOR_OBSERVED" and
             all(e.get(k) == fault.get(k) for k in
                 ("site", "node", "epoch", "door_ordinal", "occurrence"))]
    if (len(doors) != 1 or
            doors[0].get("fault_type") != plan.get("fault_type") or
            doors[0].get("exception_class") != plan.get("exception_class") or
            not (doors[0]["seq"] < match["seq"] < fault["seq"])):
        return []
    return [fault]


def inspect_case(base: Path, case_id: str) -> dict:
    if case_id not in CASES:
        raise ValueError("case is not in the scoped posthoc set")
    root = base / "data/mallory/cases" / case_id
    result_path, config_path = root / "result.json", root / "config.json"
    audit_path, sync_path = root / "offline-causal-audit.json", root / "sync-receipt.json"
    top, config, audit, sync = (read(p) for p in
                                (result_path, config_path, audit_path, sync_path))
    if (top["case_id"] != case_id or config["case_id"] != case_id or
            top["status"] not in TERMINAL or
            audit["campaign_result_sha256"] != file_sha(result_path) or
            sync["result_sha256"] != file_sha(result_path) or
            not all(audit[k] is True for k in
                    ("archive_integrity_valid", "guidance_consistent",
                     "target_claims_reverified", "applied_fault_identity_valid"))):
        raise ValueError(f"terminal SHA/audit gate failed for {case_id}")
    sites = set(config["target"]["check_sites"])
    if not sites:
        raise ValueError("no exact target check sites")
    rows = []
    for summary in top["trials"]:
        if summary["trial_id"] == 0 or not (
                summary.get("all_faults_effective") and summary.get("target_reached")):
            continue
        tid = summary["trial_id"]
        trial_dir = root / "trials" / f"r{tid:04d}"
        trial_path = trial_dir / "result.json"
        trial = read(trial_path)
        if trial["case_id"] != case_id or trial["trial_id"] != tid:
            raise ValueError(f"trial identity differs: {case_id} {tid}")
        if (trial["feedback"]["all_faults_effective"] is not True or
                trial["feedback"]["target_reached"] is not True):
            raise ValueError(f"trial feedback differs from terminal summary: {case_id} {tid}")
        events, hashes = trial_events(trial_dir, trial)
        target_checks = [e for e in events if e.get("type") == "TARGET_CHECK" and
                         e.get("site") in sites]
        graph = OccurrenceGraph(tuple(events), reject_coarse_roots=True)
        faults = []
        for plan in trial["plan"]:
            for fault in exact_fault(events, plan):
                later = [c for c in target_checks if c["seq"] > fault["seq"] and
                         c.get("node") == fault.get("node") and
                         c.get("epoch") == fault.get("epoch")]
                same_occurrence = [c["id"] for c in later if
                                   c.get("occurrence") == fault.get("occurrence") and
                                   isinstance(fault.get("thread_id"), int) and
                                   c.get("thread_id") == fault.get("thread_id")]
                same_occurrence_without_numeric = [c["id"] for c in later if
                                                   c.get("occurrence") == fault.get("occurrence")]
                same_thread_name_without_numeric = [c["id"] for c in later if
                                                    c.get("thread") == fault.get("thread")]
                observed = []
                for check in later:
                    path = graph.event_path(fault, check, require_edge=True,
                                            include_candidates=False)
                    if path:
                        observed.append({"target_check_id": check["id"],
                                         "target_occurrence": check.get("occurrence"),
                                         "target_thread_id": check.get("thread_id"),
                                         "edges": [{"kind": edge.kind,
                                                    "producer_event": edge.producer_event,
                                                    "consumer_event": edge.consumer_event,
                                                    "certainty": edge.certainty}
                                                   for edge in path]})
                faults.append({"fault_id": fault["fault_id"],
                               "fault_event_id": fault["id"], "fault_seq": fault["seq"],
                               "site": fault["site"], "node": fault["node"],
                               "epoch": fault["epoch"],
                               "door_ordinal": fault["door_ordinal"],
                               "occurrence": fault.get("occurrence"),
                               "thread_id": fault.get("thread_id"),
                               "later_same_actor_target_count": len(later),
                               "same_occurrence_numeric_target_ids": same_occurrence,
                               "same_occurrence_without_numeric_target_ids":
                                   same_occurrence_without_numeric,
                               "same_thread_name_without_numeric_target_ids":
                                   same_thread_name_without_numeric,
                               "observed_event_paths": observed})
        rows.append({"trial_id": tid, "trial_result_sha256": file_sha(trial_path),
                     **hashes, "plan_size": len(trial["plan"]),
                     "junit_status": trial.get("junit_validation", {}).get("status"),
                     "trace_truncated": trial["feedback"]["trace_truncated"],
                     "target_check_count": len(target_checks),
                     "exact_applied_faults": faults})
    graph_sha = file_sha(Path(graph_module.__file__))
    strong = [r["trial_id"] for r in rows if any(
        f["same_occurrence_numeric_target_ids"] or f["observed_event_paths"]
        for f in r["exact_applied_faults"])]
    return {"schema_version": 1, "case_id": case_id,
            "review_kind": "read_only_posthoc_exact_fault_to_target",
            "classification": ("strict_postfault_path_found" if strong else
                               "strict_postfault_path_not_found"),
            "quality_promotion_authorized": False, "new_bug_confirmed": False,
            "result_sha256": file_sha(result_path),
            "config_sha256": file_sha(config_path),
            "offline_audit_sha256": file_sha(audit_path),
            "sync_receipt_sha256": file_sha(sync_path),
            "graph_module_sha256": graph_sha,
            "graph_module_path": str(Path(graph_module.__file__).resolve()),
            "effective_target_trials_reviewed": len(rows),
            "strict_path_trial_ids": strong,
            "numeric_fault_event_count": sum(isinstance(f["thread_id"], int)
                                              for r in rows for f in r["exact_applied_faults"]),
            "exact_applied_fault_count": sum(len(r["exact_applied_faults"]) for r in rows),
            "trials": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--case-id", choices=CASES, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    review = inspect_case(args.base, args.case_id)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(review, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"case_id": args.case_id,
                      "effective_target_trials_reviewed": review["effective_target_trials_reviewed"],
                      "strict_path_trial_ids": review["strict_path_trial_ids"],
                      "numeric_fault_event_count": review["numeric_fault_event_count"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
