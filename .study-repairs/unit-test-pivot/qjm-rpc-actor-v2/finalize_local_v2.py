#!/usr/bin/env python3
"""Project an independently audited terminal QJM V2 archive into a case result.

The source archive is immutable and the old coarse-actor result is preserved.
This script does not start a JVM or modify a campaign checkpoint.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import tarfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / "cases"
FIELDS = ("budget", "fault_trials", "fully_applied_trials", "strict_injections",
          "target_after_fault", "target_reached", "coverage", "coverage_gain",
          "io_families", "elapsed_seconds", "healthy", "evidence", "source_review",
          "trial_results", "quality_review", "instrumentation_provenance",
          "completed_at_utc", "extension_decision", "coverage_gain_detail",
          "coverage_metric_note", "elapsed_seconds_semantics",
          "candidate_semantic_classification", "expected_guard_response_trials",
          "target_exception_after_fault")


def member_json(archive: tarfile.TarFile, path: str) -> dict:
    source = archive.extractfile("./" + path)
    if source is None:
        raise ValueError(f"archive lacks {path}")
    return json.load(source)


def member_set(archive: tarfile.TarFile, path: str) -> set[str]:
    source = archive.extractfile("./" + path)
    if source is None:
        raise ValueError(f"archive lacks {path}")
    return set(io.TextIOWrapper(source, encoding="utf-8").read().splitlines())


def finalize(case: str) -> None:
    ident = f"HDFS-{case}"
    source = HERE / "evidence" / ident
    audit = json.loads((source / "audit-terminal-128.json").read_text())
    if not audit["pass"] or audit["errors"] or audit["effective"] != 128:
        raise ValueError("terminal raw audit must pass at 128 effective")
    archive_path = source / "final-raw-128.tar.gz"
    archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with tarfile.open(archive_path, "r:gz") as archive:
        state = member_json(archive, "campaign-v2/checkpoint.json")
        calibration = member_json(archive, "healthy-calibration.json")
        baseline = {key: member_set(archive, f"healthy-a/covered_{key}.txt") |
                    member_set(archive, f"healthy-b/covered_{key}.txt")
                    for key in ("probes", "methods", "branch_counts", "lines")}
        if (state["case"] != ident or state["status"] != "budget_complete_128"
                or state["current"] is not None or len(state["completed"]) != audit["attempts"]
                or sum(bool(x["effective"]) for x in state["completed"]) != 128
                or calibration["original_junit_seeds"] != 2):
            raise ValueError("archive checkpoint disagrees with terminal audit")
        if any(row["run"] != checked["run"] for row, checked in zip(state["completed"], audit["runs"])):
            raise ValueError("audit row order differs from checkpoint")
    case_dir = ROOT / ident
    result_path = case_dir / "result.json"
    result = json.loads(result_path.read_text())
    if result["status"] not in ("actor_identity_recheck_pending", "quality_complete"):
        raise ValueError("unexpected existing case status")
    if result["status"] == "quality_complete":
        if result.get("raw_evidence_archive", {}).get("sha256") != archive_hash:
            raise ValueError("a different terminal archive was already projected")
        old = result["legacy_coarse_actor"]
    else:
        old = {key: result[key] for key in FIELDS if key in result}
        old["audit"] = result.get("audit")
        old["bug_mark"] = result["bug_mark"]
    result["legacy_coarse_actor"] = old
    rows = state["completed"]
    seconds = round(sum(row["elapsed_seconds"] for row in rows), 3)
    try:
        start = datetime.fromisoformat(state["started_at_utc"])
        end = datetime.fromisoformat(rows[-1]["completed_at_utc"])
        wall = round((end - start).total_seconds(), 3)
    except (ValueError, KeyError):
        wall = None
    coverage = {key: len(state["coverage_union"][key])
                for key in ("probes", "methods", "branch_counts", "lines")}
    novelty = sum(row["new_coverage_method_branch"] for row in rows)
    candidates = [row for row in rows if row["candidate"]]
    if case == "09" and candidates:
        raise ValueError("HDFS-09 unexpected target exception candidate")
    if case == "10" and not candidates:
        raise ValueError("HDFS-10 expected source-reviewed guard candidates absent")
    target_key = "target_illegal_argument_events" if case == "09" else "target_ioexception_events"
    result.update({
        "status": "quality_complete", "bug_mark": "none",
        "methodology": "actor_aware_graph_free_original_junit_coverage_guided_fault_injection",
        "budget": {"initial_effective_goal": 80, "initial_max_faults": 8,
                   "initial_attempt_cap": 320, "conditional_extension_triggered": True,
                   "effective_goal": 128, "max_faults": 10, "attempt_cap": 512,
                   "actual_attempts": len(rows),
                   "actual_max_faults_applied": max(len(row["sequence"]) for row in rows)},
        "fault_trials": len(rows),
        "fully_applied_trials": sum(row["receipt"]["applied"] == row["receipt"]["planned"]
                                    for row in rows),
        "strict_injections": sum(row["receipt"]["pass"] or
                                 row["receipt"]["applied"] == row["receipt"]["planned"]
                                 for row in rows),
        "target_after_fault": 128, "target_reached": True,
        "coverage": coverage, "coverage_gain": novelty,
        "coverage_gain_detail": {key: coverage[key] - len(baseline[key]) for key in coverage},
        "coverage_metric_note": "JaCoCo on released Hadoop production classes; branch_counts is per-method covered branch counts, while probe IDs are exact.",
        "io_families": len(state["io_union"]), "elapsed_seconds": seconds,
        "elapsed_seconds_semantics": "sum of fault-trial original JUnit durations; healthy JUnit and controller overhead excluded",
        "wall_elapsed_seconds": wall,
        "completed_at_utc": rows[-1]["completed_at_utc"],
        "extension_decision": {"triggered": True, "near_limit_window_effective_trials": 8,
                               "feedback": "one new Hadoop IPC ProcessingDetails.get production branch",
                               "target_relevance": "weak; RPC timing metric branch, not selected Journal guard"},
        "healthy": {"original_junit_seeds": 2, "junit_exits": [0, 0],
                    "elapsed_seconds": [seed["seconds"] for seed in calibration["seeds"]],
                    "target_actors": calibration["shared_target_actors"],
                    "journal_id": "test-journal",
                    "production_coverage": {key: len(value) for key, value in baseline.items()}},
        "instrumentation_provenance": {
            "junit": "unchanged_Hadoop_3_4_3_TestQuorumJournalManager_embedded_3JN",
            "runtime_hooks": "case_local_QJM_V2_ASM_source_overlay",
            "rpc_identity": "actual_Client_connection_remote_port_to_physical_JournalNode_role",
            "file_identity": "JournalNode_storage_actor_and_test_journal",
            "coverage": "JaCoCo_0_8_15_released_Hadoop_production_classes",
            "io_selection": "observed_actor_bound_io_plus_coverage_feedback",
            "causal_graph_or_closure": False, "graphchecker_runtime_jar": False,
            "static_io_map": False},
        "trial_ledger": "qjm-v2-trial-ledger.csv",
        "evidence": f"qjm-rpc-actor-v2/evidence/{ident}/audit-terminal-128.json",
        "raw_evidence_archive": {"archive": f"qjm-rpc-actor-v2/evidence/{ident}/final-raw-128.tar.gz",
                                 "sha256": archive_hash, "bytes": archive_path.stat().st_size,
                                 "original_junit_manifests": len(rows) + 2,
                                 "contents": "two original healthy seeds, immutable fault plans/manifests/traces/JUnit logs/raw JaCoCo/coverage, controller checkpoint and terminal audit; temporary JournalNode scratch excluded"},
        "quality_review": {
            "prior_status": "actor_identity_recheck_pending",
            "legacy_actor_gap": "Historical RPC selectors lacked physical JournalNode endpoint; retained separately and excluded from V2 denominator.",
            "resolution": f"Fresh endpoint-aware V2; two healthy original JUnits; {len(rows)} trial attempts; 128 strict postfault same-JournalNode target trials; independent terminal raw audit.",
            "raw_audit": f"qjm-rpc-actor-v2/evidence/{ident}/audit-terminal-128.json",
            "bug_mark_unchanged": "none",
            "resolved_at_utc": rows[-1]["completed_at_utc"]},
        "trial_results": [{
            "run": row["run"], "faults": len(row["sequence"]),
            "physical_target_actor": row["target_actor"], "journal_id": "test-journal",
            "matched": row["receipt"]["matched"], "applied": row["receipt"]["applied"],
            "postfault_target_checks": row["receipt"]["post_fault_target_checks"],
            target_key: row["receipt"]["post_fault_target_throws"],
            "effective": row["effective"], "junit_exit": row["junit_returncode"],
            "elapsed_seconds": row["elapsed_seconds"],
            "new_coverage_method_branch": row["new_coverage_method_branch"],
            "new_io_families": row["new_io_families"],
            "bug_mark": row["bug_mark"]} for row in rows],
    })
    if case == "09":
        result.pop("expected_guard_response_trials", None)
        result.pop("target_exception_after_fault", None)
        result["candidate_semantic_classification"] = {
            "label": "cross_node_committed_txid_monotonicity",
            "assessment": "site-level check; no selected exception in actor-aware V2 campaign"}
        result["source_review"] = ("Journal.checkRequest compares client committedTxId with the physical JournalNode's committedTxnId. "
            "The unchanged single-writer JUnit performed 128 strict postfault same-JN checks, with zero selected IllegalArgumentException events. "
            "JUnit nonzero exits caused by injected I/O or quorum loss are not target exceptions. No new bug established.")
    else:
        result["target_exception_after_fault"] = sum(row["receipt"]["post_fault_target_throws"] for row in rows)
        result["expected_guard_response_trials"] = len(candidates)
        result["candidate_semantic_classification"] = {
            "label": "expected_writer_epoch_guard_after_direct_injected_persistence_failure",
            "assessment": "A deliberately failed PersistentLongFile.set leaves the local writer epoch stale; clean replay of representative plans reproduces the expected Journal.checkWriteRequest guard while the 3-JN original JUnit passes. No new bug established."}
        result["source_review"] = ("Journal.startLogSegment persists lastWriterEpoch through PersistentLongFile.set; an injected write failure leaves "
            "the older epoch, and Journal.checkWriteRequest throws IOException on a later mismatched epoch. Independent clean "
            "replays and source review classify this as the expected direct fault response, not a new coordination bug.")
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    ledger_path = case_dir / "qjm-v2-trial-ledger.csv"
    with ledger_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("run", "faults", "physical_target_actor",
            "journal_id", "planned_and_applied", "postfault_target_checks", "target_exception_events",
            "effective", "junit_exit", "junit_seconds", "new_methods", "new_branches",
            "new_io_families", "bug_mark", "plan"))
        writer.writeheader()
        for row in rows:
            r = row["receipt"]
            writer.writerow({"run": row["run"], "faults": len(row["sequence"]),
                "physical_target_actor": row["target_actor"], "journal_id": "test-journal",
                "planned_and_applied": str(r["matched"] == r["applied"] == r["planned"]).lower(),
                "postfault_target_checks": r["post_fault_target_checks"],
                "target_exception_events": r["post_fault_target_throws"],
                "effective": str(row["effective"]).lower(), "junit_exit": row["junit_returncode"],
                "junit_seconds": row["elapsed_seconds"],
                "new_methods": len(row["new_coverage_ids"]["methods"]),
                "new_branches": len(row["new_coverage_ids"]["branch_counts"]),
                "new_io_families": row["new_io_families"], "bug_mark": row["bug_mark"],
                "plan": json.dumps(row["sequence"], separators=(",", ":"))})
    readme = case_dir / "README.md"
    old_readme = readme.read_text()
    if "## Current endpoint-aware V2 result" not in old_readme:
        intro = (f"# {ident}: endpoint-aware original-JUnit campaign complete\n\n"
            "## Current endpoint-aware V2 result\n\n"
            f"The unchanged Hadoop 3.4.3 `TestQuorumJournalManager#testSingleWriter` ran in a fresh three-JournalNode embedded cluster per trial. "
            f"Two healthy seeds passed in {calibration['seeds'][0]['seconds']:.3f} and {calibration['seeds'][1]['seconds']:.3f} seconds. "
            "The graph-free ASM hook binds the client RPC's actual remote endpoint and each file write to a physical JournalNode/`test-journal`; "
            "the strict receipt requires that same actor to execute the chosen check after the final fault.\n\n"
            f"The new campaign attempted **{len(rows)}** sequences, {sum(row['receipt']['applied']==row['receipt']['planned'] for row in rows)} with all planned faults applied, "
            f"and **128 effective** postfault same-actor checks. Original JUnit execution totaled {seconds:.3f}s"
            + (f" (wall {wall:.3f}s)" if wall is not None else "") + ". "
            f"The initial 80-effective/max-8 budget extended to 128/max-10 after one new production Hadoop IPC `ProcessingDetails.get` branch in the last eight effective trials; "
            "this feedback is an RPC timing branch and only weakly related to QJM recovery. "
            f"The deepest tested sequence had {max(len(row['sequence']) for row in rows)} faults. "
            f"The selected target exception appeared {sum(row['receipt']['post_fault_target_throws'] for row in rows)} times. "
            + ("HDFS-10 throws were source reviewed and representative plans replayed from clean fixtures; they are the expected local guard after an injected writer-epoch persistence failure. " if case == "10" else "")
            + "No new bug is established. JUnit nonzero exits alone are not target exceptions.\n\n"
            f"The [terminal raw audit](../../qjm-rpc-actor-v2/evidence/{ident}/audit-terminal-128.json) passes with zero errors; "
            f"the [per-trial ledger](qjm-v2-trial-ledger.csv) records time, exact faults, actor, postfault target, coverage and candidate status. "
            f"The [raw archive](../../qjm-rpc-actor-v2/evidence/{ident}/final-raw-128.tar.gz) has SHA-256 `{archive_hash}`. "
            "Earlier coarse actor trials remain under `legacy_coarse_actor` in `result.json` and do not enter the new denominator.\n\n"
            "## Historical coarse actor campaign\n\n")
        readme.write_text(intro + old_readme)
    print(json.dumps({"case": ident, "attempts": len(rows), "effective": 128,
                      "seconds": seconds, "archive_sha256": archive_hash,
                      "candidate_runs": len(candidates)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("09", "10"), required=True)
    args = parser.parse_args()
    finalize(args.case)
