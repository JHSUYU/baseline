#!/usr/bin/env python3
"""Finalize actor-bound HDFS-32 only after its original-JUnit effective goal."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import audit_v3
import raw_inventory

HERE = Path(__file__).resolve().parent
RESULT = HERE.parent / "result.json"
TERMINAL = HERE / "terminal-v3.json"
METRICS = ("probes", "methods", "branch_counts")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if audit_v3.main() != 0:
        raise RuntimeError("actor-bound independent raw audit rejected final run")
    if raw_inventory.main() != 0:
        raise RuntimeError("all-raw SHA inventory rejected final run")
    state_path = HERE / "checkpoint.json"
    state = json.loads(state_path.read_text())
    audit_path = HERE / "audit-v3.json"
    audit = json.loads(audit_path.read_text())
    inventory_path = HERE / "raw-inventory.json"
    inventory = json.loads(inventory_path.read_text())
    valid = [row for row in state["completed"] if row["post_fault_target"]]
    unavailable = inventory.get("coverage_unavailable_due_to_junit_timeout", [])
    for record in unavailable:
        number = record["trial"]
        row = state["completed"][number - 1]
        if (record != {"trial": number, "junit_exit": 124, "jacoco_bytes": 0}
                or row["junit_exit"] != 124 or row["post_fault_target"]
                or any(row["coverage_gain"][metric] for metric in METRICS)
                or row["new_io_families"]):
            raise RuntimeError("coverage-unavailable timeout was counted as effective or novel")
    if (state.get("case") != "HDFS-32"
            or state.get("stop_reason") != "effective_budget_met_pending_independent_audit"
            or len(valid) != state["goal"] or state["goal"] not in (80, 128)
            or audit["checkpoint_sha256"] != sha(state_path)
            or audit["attempts"] != len(state["completed"])
            or audit["effective"] != len(valid) or audit["errors"]
            or audit["candidate_reviews"] or inventory["errors"]
            or inventory["checkpoint_sha256"] != sha(state_path)
            or inventory["semantic_audit_sha256"] != sha(audit_path)
            or any(row["candidate_needs_source_review"] for row in state["completed"])):
        raise RuntimeError("terminal budget, identity, or raw evidence mismatch")
    if state["goal"] == 80 and (not state["extension"] or state["extension"]["novelty"]):
        raise RuntimeError("base-goal extension decision missing or inconsistent")
    if state["goal"] == 128 and (not state["extension"] or not state["extension"]["novelty"]):
        raise RuntimeError("extended-goal decision missing or inconsistent")
    gain = {metric: len(set(state["coverage"][metric]) -
                        set(state["healthy_coverage"][metric])) for metric in METRICS}
    healthy_seconds = sum(json.loads((HERE / ("healthy-" + suffix) / "manifest.json").read_text())["elapsed_seconds"]
                          for suffix in ("a", "b"))
    fault_seconds = round(sum(row["elapsed_seconds"] for row in state["completed"]), 3)
    strict = sum(bool(row["exact_order_applied"]) for row in state["completed"])
    nonzero = sum(row["junit_exit"] != 0 for row in state["completed"])
    receipt = {"schema": 1, "case": "HDFS-32", "original_junit": state["test"],
               "checkpoint_sha256": sha(state_path), "semantic_audit_sha256": sha(audit_path),
               "raw_inventory_sha256": sha(inventory_path),
               "attempts": len(state["completed"]), "strict_actor_bound": strict,
               "same_uuid_bpid_postfault_effective": len(valid), "goal": state["goal"],
               "attempt_cap": state["attempt_cap"], "max_faults": state["max_faults"],
               "extension": state["extension"],
               "last_eight_effective_ids": [row["id"] for row in valid[-8:]],
               "last_eight_coverage_or_io_novelty": any(
                   any(row["coverage_gain"][metric] for metric in METRICS)
                   or row["new_io_families"] for row in valid[-8:]),
               "production_coverage_gain": gain,
               "healthy_junit_seconds": round(healthy_seconds, 3),
               "fault_junit_seconds": fault_seconds,
               "total_junit_seconds": round(healthy_seconds + fault_seconds, 3),
               "junit_nonzero_trials": nonzero,
               "target_signature": state["healthy_signature"],
               "selected_target_outcome_candidates": 0,
               "raw_file_count": inventory["raw_file_count"],
               "raw_total_bytes": inventory["raw_total_bytes"],
               "coverage_unavailable_due_to_junit_timeout": unavailable,
               "historical_unbound_trials_excluded": 80,
               "source_build_sha256": sha(HERE / "build" / "built.json"),
               "completed_at_utc": datetime.now(timezone.utc).isoformat()}
    if TERMINAL.exists():
        old = json.loads(TERMINAL.read_text())
        if old["checkpoint_sha256"] != receipt["checkpoint_sha256"]:
            raise RuntimeError("terminal receipt already exists for another checkpoint")
        receipt = old
    else:
        pending = TERMINAL.with_name(TERMINAL.name + ".tmp")
        pending.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        pending.replace(TERMINAL)
    result = json.loads(RESULT.read_text())
    if result["case_id"] != "HDFS-32":
        raise RuntimeError("wrong result record")
    if "historical_actor_unbound_campaign" not in result:
        result["historical_actor_unbound_campaign"] = {
            "attempts": result.get("fault_trials"),
            "strict": result.get("strict_injections"),
            "target_after_fault": result.get("target_after_fault"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "coverage_gain": result.get("coverage_gain"),
            "evidence": result.get("independent_evidence"),
            "audit": result.get("audit_evidence"),
            "excluded_from_actor_v3_budget": True}
    result.update({
        "status": "quality_complete", "bug_mark": "none", "new_bug": False,
        "fault_trials": receipt["attempts"], "strict_injections": strict,
        "fully_applied_trials": strict, "target_after_fault": len(valid),
        "coverage_gain": gain["probes"], "production_method_gain": gain["methods"],
        "elapsed_seconds": receipt["total_junit_seconds"],
        "healthy_elapsed_seconds": receipt["healthy_junit_seconds"],
        "junit_nonzero_trials": nonzero,
        "selected_target_throw_after_fault_trials": len(valid),
        "new_selected_target_exception_trials": 0,
        "target_exception_after_fault_trials": len(valid),
        "target_reached": True,
        "coverage_scope": "current_actor_v3_original_JUnit_production_JaCoCo",
        "audit_evidence": str(audit_path.relative_to(HERE.parent)),
        "independent_evidence": str(state_path.relative_to(HERE.parent)),
        "evidence": str(TERMINAL.relative_to(HERE.parent)),
        "reason": "Selected IOException is expected in both healthy JUnit seeds; all effective actor-bound trials retained the same selected target signature. No differing selected outcome was observed.",
        "stop_reason": state["stop_reason"],
        "campaign_budget": state["goal"], "max_faults": state["max_faults"],
        "max_fault_depth_attempted": max(len(row["sequence"]) for row in state["completed"]),
        "actor_v3": {**result.get("actor_v3", {}),
                     "status": "quality_complete", "attempts": receipt["attempts"],
                     "strict": strict, "effective": len(valid), "goal": state["goal"],
                     "candidates": 0, "confirmed_bugs": 0,
                     "fault_junit_seconds": fault_seconds,
                     "healthy_junit_seconds": receipt["healthy_junit_seconds"],
                     "terminal_receipt": str(TERMINAL),
                     "semantic_audit": str(audit_path),
                     "raw_inventory": str(inventory_path),
                     "historical_attempts_excluded": 80}})
    if "quality_review" in result:
        result["quality_review"]["resolution"] = (
            "Fresh actor-bound V3 reached its effective goal with independent "
            "same-UUID/BPID target and all-raw SHA audits.")
    pending = RESULT.with_name(RESULT.name + ".tmp")
    pending.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    pending.replace(RESULT)
    print(json.dumps({"case": "HDFS-32", "attempts": receipt["attempts"],
                      "effective": len(valid), "goal": state["goal"],
                      "strict": strict, "seconds": receipt["total_junit_seconds"],
                      "candidate": 0, "raw_files": receipt["raw_file_count"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
