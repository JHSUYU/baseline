#!/usr/bin/env python3
"""CAS-merge the audited actor V2 result into HDFS-43 and its checklist row."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

CASE = Path(__file__).resolve().parent
TOP = CASE.parent
STUDY = TOP.parent.parent
sys.path.insert(0, str(STUDY))
import checklist  # noqa: E402

RESULT = TOP / "result.json"
LEGACY = CASE / "legacy-pre-v2-result.json"
TABLE = STUDY / "checklist102.json"
MARKDOWN = STUDY / "checklist102.md"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_cas(path: Path, before: bytes, after: bytes) -> None:
    if path.read_bytes() != before:
        raise RuntimeError(f"concurrent edit of {path}; re-read and merge")
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("wb") as stream:
        stream.write(after)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != before:
        temporary.unlink()
        raise RuntimeError(f"concurrent edit of {path}; re-read and merge")
    os.replace(temporary, path)


def render_json(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2,
                       sort_keys=True) + "\n").encode()


def main() -> None:
    v2 = json.loads((CASE / "result.json").read_text())
    summary = json.loads((CASE / "campaign/final-summary.json").read_text())
    audit = json.loads((CASE / "campaign/final-audit.json").read_text())
    state = json.loads((CASE / "campaign/checkpoint.json").read_text())
    if (v2["status"] != "quality_complete" or summary["status"] !=
            "quality_complete" or not audit["integrity_passed"] or
            audit["effective"] != 80 or audit["strict"] != 84 or
            audit["audited_trials"] != 125 or audit["errors"] or
            state["stop_reason"] != "effective_budget_reached"):
        raise RuntimeError("V2 terminal raw audit is incomplete")

    before_result = RESULT.read_bytes()
    old = json.loads(before_result)
    if old["case_id"] != "HDFS-43":
        raise RuntimeError("wrong root result")
    already_published = (old.get("actor_v2_audit") ==
                         "actor-v2/campaign/final-audit.json")
    if already_published:
        if (old.get("status") != "quality_complete" or
                old.get("fault_trials") != 125 or
                old.get("fully_applied_trials") != 84 or
                old.get("target_after_fault") != 80 or not LEGACY.is_file()):
            raise RuntimeError("partial V2 result differs from audited totals")
    elif LEGACY.exists():
        if LEGACY.read_bytes() != before_result:
            raise RuntimeError("pre-V2 legacy snapshot differs from current result")
    else:
        temporary = LEGACY.with_name(LEGACY.name + f".tmp.{os.getpid()}")
        with temporary.open("wb") as stream:
            stream.write(before_result)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, LEGACY)

    rows = state["completed"]
    compact = [{key: row[key] for key in (
        "id", "status", "sequence", "requested_faults", "matched_faults",
        "applied_faults", "strict_injection", "target_after_fault_same_actor",
        "post_fault_target_exception_count", "junit_exit", "elapsed_seconds",
        "new_coverage_count", "new_io_family_ids", "bug_mark", "sequence_id")}
        for row in rows]
    review = dict(old.get("quality_review", {}))
    review["resolution"] = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "replacement": "actor-v2/campaign/final-audit.json",
        "independent_raw_audit_errors": 0,
        "physical_rpc_destination_and_dn_uuid_checked": True,
        "same_file_block_target_after_last_fault": 80,
        "historical_counters_still_excluded": True,
    }
    new = dict(old)
    new.update({
        "status": "quality_complete", "bug_mark": "none", "new_bug": False,
        "methodology": v2["methodology"], "fault_trials": 125,
        "strict_injections": 84, "fully_applied_trials": 84,
        "target_after_fault": 80, "post_fault_target_reach_trials": 80,
        "target_exception_after_fault": 80,
        "target_exception_after_fault_trials": 80,
        "expected_guard_response_trials": 80,
        "coverage_gain": v2["coverage_gain"],
        "coverage_gain_detail": {
            "metric": "distinct production METHOD, BRANCH_UNIT, PROBE IDs admitted only from strict same-actor target-retaining trials",
            "counts": v2["coverage_gain"],
            "whole_junit_coverage_not_causal_proof": True,
        },
        "elapsed_seconds": v2["elapsed_seconds"],
        "elapsed_seconds_semantics": "two fresh healthy original JUnit calibrations and 125 actual fault trials, including controller overhead",
        "budget": {"max_effective": 80, "max_trials": 80,
                   "max_attempts": 320, "max_faults": 8,
                   "extension_max_effective": 128,
                   "extension_max_attempts": 512,
                   "extension_max_faults": 10},
        "extension_decision": {
            "effective_73_to_80_new_production_coverage_or_stable_io_family": False,
            "extended": False, "stop_reason": "effective_budget_reached",
            "window": summary["extension_gate_effective_73_to_80"],
        },
        "quality_review": review,
        "actor_v2_audit": "actor-v2/campaign/final-audit.json",
        "actor_v2_summary": "actor-v2/campaign/final-summary.json",
        "actor_v2_artifact_manifest": "actor-v2/campaign/final-artifact-manifest.json",
        "actor_v2_raw_archive": "actor-v2/campaign/raw-trace-selector-evidence.tar.gz",
        "actor_v2_checkpoint": "actor-v2/campaign/checkpoint.json",
        "actor_v2_ledger": "actor-v2/campaign/trial-ledger.csv",
        "actor_v2_original_junit_outcomes":
            summary["original_junit_effective_outcomes"],
        "actor_v2_fault_event_counts": {
            "requested": summary["requested_faults"],
            "matched": summary["matched_faults"],
            "applied": summary["applied_faults"]},
        "actor_v2_io_families": summary["new_stable_io_families"],
        "trial_results": compact,
        "historical_actor_unverified_result": "actor-v2/legacy-pre-v2-result.json",
        "historical_main_trials_excluded": 80,
        "historical_supplementary_trials_excluded": 128,
        "historical_fields_retained_from_pre_v2": [
            "supplementary_equal_branch", "alternate_original_junit_calibration",
            "combined_main_and_supplementary_junit_seconds", "coverage",
            "healthy_target_branch_outcomes", "post_fault_target_branch_outcomes",
            "target_retaining_sequence_depths", "tested_sequence_depths"],
        "source_review": v2["source_review"],
        "instrumentation_provenance": {
            "causal_graph_or_closure": False,
            "graphchecker_prewoven": False,
            "original_junit": v2["cluster_test"],
            "runtime_hooks": "case-local source probes for RPC request/destination/DN UUID and exact truncate guard",
            "coverage": "JaCoCo 0.8.15 production Hadoop 3.4.3 JARs plus case-local source overrides",
            "selector": "ordered observed RPC response I/O with physical endpoint and actor identity",
            "source_build_receipt": "actor-v2/system-test/build-probe.json",
            "raw_audit": "actor-v2/campaign/final-audit.json"},
        "evidence": "actor-v2/campaign/final-audit.json",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    if not already_published:
        write_cas(RESULT, before_result, render_json(new))

    before_table = TABLE.read_bytes()
    table = json.loads(before_table)
    items = table["rows"]
    prior_other_rows = {row["case_id"]: row for row in items
                        if row["case_id"] != "HDFS-43"}
    fresh = next(row for row in checklist.rows() if row["case_id"] == "HDFS-43")
    replacement = [fresh if row["case_id"] == "HDFS-43" else row
                   for row in items]
    if (len(replacement) != 104 or
            {row["case_id"]: row for row in replacement
             if row["case_id"] != "HDFS-43"} != prior_other_rows):
        raise RuntimeError("another checklist row would change")
    table["rows"] = replacement
    write_cas(TABLE, before_table, render_json(table))

    before_md = MARKDOWN.read_bytes()
    old_lines = before_md.decode().splitlines(keepends=True)
    generated = checklist.markdown(replacement).splitlines(keepends=True)
    wanted = {"status": next(line for line in generated
                             if line.startswith("Status: ")),
              "case": next(line for line in generated
                           if line.startswith("| HDFS-43 |"))}
    found = Counter()
    new_lines = []
    for line in old_lines:
        if line.startswith("Status: "):
            line = wanted["status"]
            found["status"] += 1
        elif line.startswith("| HDFS-43 |"):
            line = wanted["case"]
            found["case"] += 1
        new_lines.append(line)
    if found != {"status": 1, "case": 1}:
        raise RuntimeError(f"markdown status/case row mismatch: {found}")
    write_cas(MARKDOWN, before_md, "".join(new_lines).encode())
    print(json.dumps({"result_sha256": digest(RESULT.read_bytes()),
                      "checklist_sha256": digest(TABLE.read_bytes()),
                      "markdown_sha256": digest(MARKDOWN.read_bytes()),
                      "other_rows_preserved": len(prior_other_rows),
                      "case_status": fresh["status"],
                      "case_trials": fresh["fault_trials"],
                      "case_strict": fresh["fully_applied_trials"],
                      "case_target": fresh["target_after_fault"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
