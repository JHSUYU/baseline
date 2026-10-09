#!/usr/bin/env python3
"""Review every SOLR-18 v45 fault trial for the exact BadVersion recovery path."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import Mallory.core.graph as graph_module
from Mallory.core.graph import OccurrenceGraph

from verify_solr18_badversion_recovery import BAD_VERSION, DOOR, SET_IF_NEWER, digest, proof


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def contained(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes campaign: {relative}")
    return path


def event_trace(trial_dir: Path, trial: dict) -> tuple[list[dict], dict]:
    evidence = trial["events_evidence"]
    packed_path = contained(trial_dir, evidence["gzip_path"])
    packed = packed_path.read_bytes()
    packed_sha = hashlib.sha256(packed).hexdigest()
    if packed_sha != evidence["gzip_sha256"] or len(packed) != evidence["gzip_bytes"]:
        raise ValueError(f"compressed event SHA/size differs: {trial_dir}")
    raw = gzip.decompress(packed)
    raw_sha = hashlib.sha256(raw).hexdigest()
    if (raw_sha != evidence["raw_sha256"] or raw_sha != trial["events_sha256"] or
            len(raw) != evidence["raw_bytes"]):
        raise ValueError(f"raw event SHA/size differs: {trial_dir}")
    return ([json.loads(line) for line in raw.splitlines() if line],
            {"events_gzip_sha256": packed_sha, "events_raw_sha256": raw_sha,
             "events_raw_bytes": len(raw)})


def full_trace_proof(events: list[dict], plan_fault: dict) -> dict:
    """Prove one exact fault on both its own chain and the unfiltered event graph."""
    fault_id = plan_fault.get("fault_id")
    if not isinstance(fault_id, str):
        return {"valid": False, "reason": "missing_plan_fault_id"}
    scoped = [row for row in events if row.get("type") not in
              ("FAULT_MATCHED", "FAULT_APPLIED") or row.get("fault_id") == fault_id]
    chain = proof(scoped, plan_fault)
    if not chain["valid"]:
        return chain
    by_id = {row["id"]: row for row in events}
    fault = by_id[chain["event_ids"]["applied"]]
    target = by_id[chain["event_ids"]["target_check"]]
    path = OccurrenceGraph(tuple(events), reject_coarse_roots=True).event_path(
        fault, target, require_edge=True, include_candidates=False)
    observed = ([{"kind": edge.kind, "producer_event": edge.producer_event,
                  "consumer_event": edge.consumer_event, "certainty": edge.certainty}
                 for edge in path] if path is not None else None)
    if observed != chain["graph_edges"]:
        return {"valid": False, "reason": "filtered_chain_not_preserved_in_full_trace"}
    return chain


def review(root: Path, source: Path, test_source: Path) -> dict:
    top_path, config_path = root / "result.json", root / "config.json"
    audit_path, sync_path = root / "offline-causal-audit.json", root / "sync-receipt.json"
    top, config, audit, sync = (read(path) for path in
                                (top_path, config_path, audit_path, sync_path))
    if not (top["case_id"] == config["case_id"] == audit["case_id"] ==
            sync["case_id"] == "SOLR-18"):
        raise ValueError("wrong case identity")
    if top["status"] not in ("budget_exhausted", "queue_exhausted"):
        raise ValueError("campaign is not terminal")
    if (config["budget"]["trials"] != 80 or config["budget"]["seconds"] != 3600 or
            config["budget"]["max_faults_per_trial"] != 6 or
            config["site_file"].endswith("sites-v44-badversion.json") is False or
            [row["site"] for row in config["validated_recovery_sites"]] != [DOOR]):
        raise ValueError("wrong pinned recovery campaign")
    if (config["mapping"]["target_source_sha256"] != digest(source) or
            config["mapping"]["test_source_sha256"] != digest(test_source)):
        raise ValueError("source/test SHA differs")
    release_graph = Path(config["core_release"]) / "Mallory/core/graph.py"
    if Path(graph_module.__file__).resolve() != release_graph.resolve():
        raise ValueError("reviewer loaded a different graph release")
    if (audit["campaign_result_sha256"] != digest(top_path) or
            sync["result_sha256"] != digest(top_path) or
            not all(audit[key] is True for key in
                    ("archive_integrity_valid", "guidance_consistent",
                     "target_claims_reverified", "applied_fault_identity_valid"))):
        raise ValueError("frozen audit or sync does not bind terminal result")
    source_text = source.read_text()
    apply_method = source_text.split("public void applyModificationAndExportToZk(", 1)[1]
    apply_method = apply_method.split("public boolean update()", 1)[0]
    update_method = source_text.split("public boolean update()", 1)[1]
    update_method = update_method.split("public void process(WatchedEvent event)", 1)[0]
    if ("catch (KeeperException.BadVersionException e)" not in apply_method or
            "update();" not in apply_method or
            "zkClient.getData(ALIASES, null, stat, true)" not in update_method or
            "return setIfNewer(Aliases.fromJSON(data, stat.getVersion()));" not in update_method or
            "testDeleteAliasWithExistingCollectionName()" not in test_source.read_text()):
        raise ValueError("caught retry source/test path changed")

    retained = sync["retained_files"]
    rows = []
    if len(top["trials"]) != top["fault_trials_completed"] + 1:
        raise ValueError("trial count differs from terminal result")
    for trial_id in range(1, top["fault_trials_completed"] + 1):
        trial_dir = root / "trials" / f"r{trial_id:04d}"
        result_path = trial_dir / "result.json"
        relative_result = str(result_path.relative_to(root))
        if retained[relative_result]["sha256"] != digest(result_path):
            raise ValueError(f"trial result differs from node2 sync: {trial_id}")
        trial = read(result_path)
        if trial["trial_id"] != trial_id or trial["case_id"] != "SOLR-18":
            raise ValueError(f"trial identity differs: {trial_id}")
        events, hashes = event_trace(trial_dir, trial)
        relative_events = str((trial_dir / trial["events_evidence"]["gzip_path"]).relative_to(root))
        if retained[relative_events]["sha256"] != hashes["events_gzip_sha256"]:
            raise ValueError(f"trial trace differs from node2 sync: {trial_id}")
        feedback, junit, plan = trial["feedback"], trial["junit_validation"], trial["plan"]
        exact_plan = [fault for fault in plan if fault.get("point", {}).get("site") == DOOR and
                      fault.get("exception_class") == BAD_VERSION]
        target_throws = [event["id"] for event in events if event.get("type") == "TARGET_THROW"
                         and event.get("site", "").startswith(SET_IF_NEWER)]
        eligible = (len(plan) == len(exact_plan) and len(plan) > 0 and
                    feedback["all_faults_effective"] is True and
                    feedback["fault_identity_valid"] is True and
                    feedback["trace_truncated"] is False and
                    trial.get("trace_error") is None and trial.get("timed_out") is False and
                    junit["status"] == "passed" and junit["tests"] == 1 and
                    junit["failures"] == junit["errors"] == junit["skipped"] == 0)
        chains = ([full_trace_proof(events, fault) for fault in exact_plan] if eligible else
                  [{"valid": False, "reason": "not_all_effective_passing_badversion_faults"}])
        strict = all(chain["valid"] for chain in chains)
        rows.append({"trial_id": trial_id, "trial_result_sha256": digest(result_path),
                     **hashes, "plan_size": len(plan), "exact_badversion_plans": len(exact_plan),
                     "all_faults_effective": feedback["all_faults_effective"],
                     "target_reached": feedback["target_reached"],
                     "target_threw": feedback["target_threw"],
                     "target_exception_candidate": feedback["target_exception_candidate"],
                     "target_throw_event_ids": target_throws,
                     "junit_status": junit["status"], "trace_truncated": feedback["trace_truncated"],
                     "strict_recovery_chains": chains,
                     "all_exact_faults_have_strict_recovery_chain": strict})
    positives = [row["trial_id"] for row in rows
                 if row["all_exact_faults_have_strict_recovery_chain"]]
    single = [row["trial_id"] for row in rows
              if row["all_exact_faults_have_strict_recovery_chain"] and row["plan_size"] == 1]
    multi = [row["trial_id"] for row in rows
             if row["all_exact_faults_have_strict_recovery_chain"] and row["plan_size"] > 1]
    effective = [row["trial_id"] for row in rows if row["all_faults_effective"]]
    effective_target = [row["trial_id"] for row in rows
                        if row["all_faults_effective"] and row["target_reached"]]
    unmatched = [row["trial_id"] for row in rows if not row["all_faults_effective"]]
    return {"schema_version": 1, "case_id": "SOLR-18",
            "classification": ("terminal_badversion_recovery_precision_proven" if positives else
                               "terminal_badversion_recovery_precision_unproven"),
            "canonical_quality_claim": False, "new_bug_confirmed": False,
            "causality_limit": "The caught exception and event path establish a same-invocation recovery execution; a counterfactual effect on the later guard is not established.",
            "campaign_result_sha256": digest(top_path), "config_sha256": digest(config_path),
            "offline_audit_sha256": digest(audit_path),
            "offline_audit_gate": audit["report_gate_passed"],
            "sync_receipt_sha256": digest(sync_path),
            "source_sha256": digest(source), "test_source_sha256": digest(test_source),
            "core_graph_sha256": digest(release_graph),
            "fault_trials_completed": len(rows), "strict_recovery_trials": positives,
            "strict_single_fault_recovery_trials": single,
            "strict_multi_fault_recovery_trials": multi,
            "effective_fault_trials": effective,
            "effective_target_trials": effective_target,
            "unmatched_or_ineffective_trials": unmatched,
            "exact_target_exception_candidate_trials": [row["trial_id"] for row in rows
                                                        if row["target_exception_candidate"]],
            "trials": rows}


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
                      "strict_recovery_trials": row["strict_recovery_trials"],
                      "exact_target_exception_candidate_trials":
                          row["exact_target_exception_candidate_trials"]}, sort_keys=True))
    if args.require_witness and not row["strict_recovery_trials"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
