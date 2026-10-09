#!/usr/bin/env python3
"""Publish an audited V2 result without mixing prior unbound campaigns."""

import argparse
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
CASES = Path("crashfuzz/cases")
SOURCE_NOTES = {
    "HBASE-08": (
        "The original getNamespace(String) null check is at "
        "ClusterSchemaServiceImpl.java:116. CreateNamespaceProcedure retries IOException "
        "during CREATE_NAMESPACE_UPDATE_ZK; ZKNamespaceManager watcher read errors "
        "can abort a Master and lose the target."
    ),
    "HBASE-21": (
        "The original region quota predicate is at NamespaceStateManager.java:128. "
        "The unchanged restore-snapshot JUnit expects a QuotaExceededException "
        "inside RestoreSnapshotException when four snapshot regions exceed the limit of three."
    ),
    "HBASE-22": (
        "The original table creation region quota predicate is at "
        "NamespaceStateManager.java:166. The unchanged table-operations JUnit "
        "expects a QuotaExceededException when five new regions exceed the limit of five "
        "with one existing region."
    ),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finalize(case):
    case_dir = CASES / case
    old_path = case_dir / "result.json"
    legacy_path = case_dir / "legacy-pre-actor-v2-result.json"
    if not legacy_path.exists():
        legacy_path.write_bytes(old_path.read_bytes())
    old = json.loads(legacy_path.read_text())
    row = json.loads((case_dir / "evidence/actor-v2-result-row.json").read_text())
    audit = json.loads((case_dir / "evidence/actor-v2-raw-audit.json").read_text())
    archive = case_dir / "evidence" / (case.lower().replace("-", "") + "-actor-v2-evidence.tar.gz")
    if row["case_id"] != case or audit["case_id"] != case:
        raise ValueError("Case mismatch")
    if row["status"] not in ("budget_complete_pending_audit", "queue_exhausted_pending_audit",
                             "attempt_cap_pending_audit"):
        raise ValueError("V2 campaign has not stopped at an audit checkpoint")
    if audit["errors"] or audit["status"] != row["status"]:
        raise ValueError("Raw audit failed or does not match stopped campaign")
    if (audit["attempts"], audit["effective"], audit["strict_trials"]) != (
            row["attempted_trials"], row["effective_trials"], row["strict_trials"]):
        raise ValueError("Raw audit totals differ from V2 result row")
    if any(x["effective"] and not x["outcomes"] for x in audit["raw_receipts"]):
        raise ValueError("Invalid effective target receipt")
    if row["target_exception_candidates"]:
        raise ValueError("Review and replay new target exceptions before finalizing")
    if not archive.is_file():
        raise FileNotFoundError(archive)
    late = any(x["new_methods"] or x["new_branches"] or x["new_stable_io_families"]
               for x in audit["last8_effective_novelty"])
    if row["effective_trials"] == 80 and row["budget"]["effective_trials"] == 80 and late:
        raise ValueError("Late novelty requires extension before completion")
    stop_reason = row["status"].replace("_pending_audit", "")
    selected_outcomes = audit["selected_outcomes_all_raw"]
    if case in ("HBASE-21", "HBASE-22") and (
            set(selected_outcomes) - set(row["healthy_expected_outcomes"])):
        raise ValueError("A selected guard outcome differs from healthy quota behavior; review source and replay")
    result = {
        "case_id": case, "system": "HBase", "version": "2.6.6",
        "status": "quality_complete" if row["status"] == "budget_complete_pending_audit"
                  else "quality_complete_limited_by_" + stop_reason,
        "source_revision": row["source_revision"], "source_file": row["source_file"],
        "source_path": row["source_file"], "source_line": row["target_guard_line"],
        "function": row["target_function"],
        "target_function": row["target_function"],
        "target_guard_line": row["target_guard_line"],
        "cluster_test": row["original_junit"], "target_reached": True,
        "methodology": row["methodology"],
        "fault_trials": row["attempted_trials"],
        "effective_fault_trials": row["effective_trials"],
        "strict_injections": row["strict_trials"],
        "target_after_fault": row["strict_postfault_target_trials"],
        "requested_faults": row["requested_faults"],
        "applied_faults": row["applied_faults"],
        "coverage_gain": row["new_production_branches"],
        "new_production_methods": row["new_production_methods"],
        "new_production_branches": row["new_production_branches"],
        "new_stable_io_families": row["new_stable_io_families"],
        "healthy_elapsed_seconds": round(row["healthy_elapsed_seconds"], 2),
        "fault_elapsed_seconds": round(row["fault_elapsed_seconds"], 2),
        "elapsed_seconds": round(row["total_elapsed_seconds"], 2),
        "bug_mark": "none", "target_exception_candidates": 0,
        "budget": row["budget"], "stop_reason": stop_reason,
        "extension_decision": {"last8_effective_novelty": late,
                               "extended_to_128": row["budget"]["effective_trials"] == 128},
        "source_audit_note": SOURCE_NOTES[case]
          + " The raw audit found selected outcomes " + str(selected_outcomes)
          + "; none established a new bug within the admitted fault scope.",
        "current_campaign": row,
        "raw_audit": {key: audit[key] for key in
                      ("checkpoint_sha256", "attempts", "effective", "strict_trials",
                       "selected_outcomes_all_raw", "depth_attempts", "fault_kinds",
                       "fault_families", "junit_exit_counts", "errors")},
        "instrumentation_provenance": {
            "runtime_source": "unchanged original HBase 2.6.6 server and test JARs",
            "server_jar_sha256": "27b736c5e7a86288752c7d19ba9c9e1a026b27693068cf56c6827aa13274d696",
            "test_jar_sha256": "b1f7524b395808c660e7fdaa3a95bc777b1097125aacedb3414ac6799d1832b5",
            "agent": "standalone namespace actor V2 ByteBuddy agent plus JaCoCo 0.8.15",
            "agent_jar_sha256": audit["agent_sha256"][0],
            "same_actor_gate": "raw ACTIVE_MASTER ServerName and manager identity, exact ordered I/O, postfault guard",
            "graphchecker_prewoven_jar": False,
            "graph_or_closure_feedback": False,
        },
        "evidence": ["README.md", "evidence/actor-v2-result-row.json",
                     "evidence/actor-v2-raw-audit.json", str(archive.relative_to(case_dir)),
                     str(legacy_path.relative_to(case_dir))],
        "evidence_archive_sha256": digest(archive),
        "evidence_archive_bytes": archive.stat().st_size,
        "current_method_trials_count": row["attempted_trials"],
        "historical_unbound_trials_count": old.get("fault_trials", 0),
        "historical_graphchecker_pilot_trials_count": old.get("legacy_evidence", {}).get("fault_trials", 0),
        "historical_evidence": str(legacy_path.relative_to(case_dir)),
        "comparison_scope": "Only actor-bound V2 trials contribute to top-level fault, target, time, and coverage counters; prior unbound results are archived separately.",
        "quality_review": {
            "prior_issue": "Earlier graph-free selectors did not prove the communicating Master/manager identity.",
            "resolution": "Independent actor-bound V2 runs and raw audit prove the selected guard after exact faults on the same Master/manager.",
        },
    }
    old_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=SOURCE_NOTES)
    args = parser.parse_args()
    result = finalize(args.case)
    print(json.dumps({key: result[key] for key in
                      ("case_id", "status", "fault_trials", "effective_fault_trials",
                       "target_after_fault", "elapsed_seconds", "bug_mark")}))
