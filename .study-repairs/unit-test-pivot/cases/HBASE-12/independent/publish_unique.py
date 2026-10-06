#!/usr/bin/env python3
"""Publish separate HBASE-12/31 ledgers from the same native JUnit executions."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess
import sys
import time

CASES = Path(__file__).resolve().parents[2]
REMOTE = "/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases"


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def snapshot() -> dict:
    script = """
from pathlib import Path
import json
base=Path(%r)
def one(directory, state_name, rows_directory):
 p=base/directory
 f=p/state_name
 if not f.exists(): return None
 s=json.loads(f.read_text())
 rows=[]
 for name in s['completed']:
  c=p/rows_directory/(name+'.json')
  if c.exists(): rows.append(json.loads(c.read_text()))
 compact={key:s.get(key) for key in ('healthy','budget_total','max_faults','stop_reason','extension_checkpoint','bug_candidates','coverage_scope_version')}
 compact['coverage_probe_count']=len(s.get('coverage_probes',[]))
 compact['stable_io_family_count']=len(s.get('seen_stable_families',[]))
 compact['completed_count']=len(s['completed'])
 return {'state':compact,'rows':rows}
print(json.dumps({
 'shared':one('HBASE-12/independent','mirror-state.json','checkpoints'),
 'unique':one('HBASE-12/independent/unique','campaign-state.json','campaign-checkpoints'),
 'rs':one('HBASE-31/independent','mirror-state.json','checkpoints')}))
""" % REMOTE
    proc = subprocess.run([
        "ssh", "-C", "-i", str(Path.home() / ".ssh/id_ed25519_nodes"),
        "-o", "IdentitiesOnly=yes", "ZhenyuLi@node1", "python3", "-"],
        input=script, text=True, capture_output=True, timeout=30, check=True)
    return json.loads(proc.stdout)


def eligible(row: dict, maximum: int) -> bool:
    return (row["strict_identity_match"] and row["target_after_fault"]
            and 0 < row["requested"] <= maximum
            and row["requested"] == row["matched"] == row["applied"]
            and row["elapsed_seconds"] is not None)


def publish_b3(shared: dict | None, unique: dict | None) -> None:
    if not shared and not unique:
        return
    path = CASES / "HBASE-12" / "result.json"
    result = json.loads(path.read_text())
    shared_rows = shared["rows"] if shared else []
    unique_rows = unique["rows"] if unique else []
    shared_budget = shared["state"]["max_faults"] if shared else 8
    unique_budget = unique["state"]["max_faults"] if unique else 8
    shared_effective = [row for row in shared_rows if eligible(row, shared_budget)]
    unique_effective = [row for row in unique_rows if eligible(row, unique_budget)]
    combined = ([{"execution_origin": "shared_HBASE-10", **row} for row in shared_rows]
                + [{"execution_origin": "target_guided_unique", **row} for row in unique_rows])
    shared_state = shared["state"] if shared else {}
    unique_state = unique["state"] if unique else {}
    unique_healthy = unique_state.get("healthy", {})
    shared_healthy = shared_state.get("healthy", {})
    limit = unique_state.get("budget_total", 80)
    effective_total = len(shared_effective) + len(unique_effective)
    if unique and unique_state.get("stop_reason"):
        status = ("pending_source_review" if effective_total >= limit
                  else "pending_additional_unique_trials")
    elif unique:
        status = "fuzzing_target_guided_unique"
    else:
        status = "fuzzing_shared_execution"
    new_candidates = unique_state.get("bug_candidates", [])
    old_candidates = shared_state.get("bug_candidates", [])
    result.update({
        "status": status,
        "methodology": "coverage_io_independent_bytebuddy_jacoco",
        "methodology_note": "Original TestRegionMove JUnit. HBASE-10 runs are target-specifically projected without replay; the case-local HBASE-12 queue executes only sequences not completed by HBASE-10. Separate JaCoCo scopes are reported separately, never numerically unioned.",
        "shared_execution": True,
        "execution_shared_with": ["HBASE-10", "HBASE-31"],
        "instrumentation_provenance": {
            "recorder": "case-local ByteBuddy HBase10Agent + HBase31Probe",
            "coverage": "JaCoCo original production classes, including RSRpcServices in unique campaign",
            "graphchecker_runtime_jar": False,
            "graphchecker_woven_classes": False,
            "static_skeleton": False,
        },
        "target_reached": bool(unique_healthy.get("target_checks") or shared_healthy.get("target_checks")),
        "healthy_target_guard_hits": unique_healthy.get("target_checks", shared_healthy.get("target_checks")),
        "healthy_target_exception_hits": 0,
        "seed_seconds": unique_healthy.get("elapsed_seconds", shared_healthy.get("elapsed_seconds")),
        "healthy_fault_points": unique_healthy.get("io_points", shared_healthy.get("io_points")),
        "healthy_stable_io_families": unique_healthy.get("stable_io_families", shared_healthy.get("stable_io_families")),
        "healthy_production_probes": unique_healthy.get("coverage_probes", shared_healthy.get("coverage_probes")),
        "healthy_method_coverage": unique_healthy.get("production_methods_covered", shared_healthy.get("production_methods_covered")),
        "healthy_branch_outcome_coverage": unique_healthy.get("production_branches_covered", shared_healthy.get("production_branches_covered")),
        "fault_trials": len(combined),
        "attempted_fault_trials": len(combined),
        "effective_fault_trials": effective_total,
        "shared_effective_fault_trials": len(shared_effective),
        "unique_effective_fault_trials": len(unique_effective),
        "strict_injections": sum(row["strict_identity_match"] for row in combined),
        "fully_applied_trials": sum(row["strict_identity_match"] for row in combined),
        "requested_fault_events": sum(row["requested"] for row in combined),
        "matched_fault_events": sum(row["matched"] for row in combined),
        "applied_fault_events": sum(row["applied"] for row in combined),
        "target_after_fault": sum(row["target_after_fault"] for row in combined),
        "target_exception_after_fault_trials": sum(row["target_exception_after_fault"] for row in combined),
        "shared_campaign_coverage_gain": max(0, shared_state.get("coverage_probe_count", 0) - shared_healthy.get("coverage_probes", 0)),
        "unique_campaign_coverage_gain": max(0, unique_state.get("coverage_probe_count", 0) - unique_healthy.get("coverage_probes", 0)),
        "coverage_gain": max(0, unique_state.get("coverage_probe_count", 0) - unique_healthy.get("coverage_probes", 0)) if unique else max(0, shared_state.get("coverage_probe_count", 0) - shared_healthy.get("coverage_probes", 0)),
        "production_probe_coverage_total": unique_state.get("coverage_probe_count", shared_state.get("coverage_probe_count")),
        "stable_io_family_total": unique_state.get("stable_io_family_count", shared_state.get("stable_io_family_count")),
        "trial_results": combined,
        "trial_runtime_total_seconds": round(sum(row["elapsed_seconds"] or 0 for row in combined), 3),
        "elapsed_seconds": round((unique_healthy.get("elapsed_seconds") or shared_healthy.get("elapsed_seconds") or 0)
                                 + sum(row["elapsed_seconds"] or 0 for row in combined), 3),
        "runtime_accounting_note": "Per-check attribution includes JVM executions shared with HBASE-10 and HBASE-31; sums across cases double-count shared runs. HBASE-12 unique healthy seed is counted once.",
        "fault_budget": {"default_trials": 80, "max_faults_per_sequence": 8,
                         "extension_trials": 128, "extension_max_faults": 10,
                         "extension_requires_stable_io_family_or_production_coverage": True,
                         "current_trials": limit,
                         "current_max_faults": unique_budget},
        "extension_checkpoint": unique_state.get("extension_checkpoint"),
        "bug_mark": "candidate_unconfirmed" if new_candidates or old_candidates else "none",
        "bug_candidates": {"shared": old_candidates, "unique": new_candidates},
        "stopping_reason": unique_state.get("stop_reason") or "Target-guided unique campaign running",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    atomic_json(CASES / "HBASE-12" / "trials-summary.json", combined)
    atomic_json(path, result)


def publish_rs(rs: dict | None) -> None:
    if not rs:
        return
    path = CASES / "HBASE-31" / "result.json"
    result = json.loads(path.read_text())
    state = rs["state"]
    rows = rs["rows"]
    healthy = state["healthy"]
    effective_rows = [row for row in rows if eligible(row, state["max_faults"])]
    status = ("pending_source_review" if state["stop_reason"] and
              len(effective_rows) >= state["budget_total"] else
              "pending_additional_unique_trials" if state["stop_reason"] else
              "fuzzing_shared_execution")
    if result.get("candidate_screening") == "screened_out_non_adhoc":
        status = "source_excluded"
    result.update({
        "status": status,
        "methodology": "coverage_io_independent_bytebuddy_jacoco_shared_junit",
        "methodology_note": "Original TestRegionMove JUnit. HBASE-31 target outcomes, exact I/O matches, production coverage and timing are projected into independent checkpoints from HBASE-12's unique JVM executions. A separate original regression test and source review classify this site as a non-adhoc direct start-code guard.",
        "shared_execution": True,
        "execution_shared_with": "HBASE-12/independent/unique",
        "instrumentation_provenance": {
            "recorder": "case-local ByteBuddy HBase31Probe + HBase10Agent",
            "coverage": "JaCoCo original HBase production classes including RSRpcServices",
            "graphchecker_runtime_jar": False,
            "graphchecker_woven_classes": False,
            "static_skeleton": False,
        },
        "target_reached": healthy["target_checks"] > 0,
        "healthy_target_guard_hits": healthy["target_checks"],
        "healthy_target_exception_hits": healthy["target_exceptions"],
        "seed_seconds": healthy["elapsed_seconds"],
        "healthy_fault_points": healthy["io_points"],
        "healthy_stable_io_families": healthy["stable_io_families"],
        "healthy_production_probes": healthy["coverage_probes"],
        "healthy_method_coverage": healthy["production_methods_covered"],
        "healthy_branch_outcome_coverage": healthy["production_branches_covered"],
        "fault_trials": len(rows),
        "attempted_fault_trials": len(rows),
        "effective_fault_trials": len(effective_rows),
        "strict_injections": sum(row["strict_identity_match"] for row in rows),
        "fully_applied_trials": sum(row["strict_identity_match"] for row in rows),
        "requested_fault_events": sum(row["requested"] for row in rows),
        "matched_fault_events": sum(row["matched"] for row in rows),
        "applied_fault_events": sum(row["applied"] for row in rows),
        "target_after_fault": sum(row["target_after_fault"] for row in rows),
        "target_exception_after_fault_trials": sum(row["target_exception_after_fault"] for row in rows),
        "coverage_gain": max(0, state["coverage_probe_count"] - healthy["coverage_probes"]),
        "production_probe_coverage_total": state["coverage_probe_count"],
        "stable_io_family_total": state["stable_io_family_count"],
        "trial_results": rows,
        "trial_runtime_total_seconds": round(sum(row["elapsed_seconds"] or 0 for row in rows), 3),
        "elapsed_seconds": round(healthy["elapsed_seconds"] + sum(row["elapsed_seconds"] or 0 for row in rows), 3),
        "runtime_accounting_note": "Same JVM executions are attributed to HBASE-12; per-case totals are not additive.",
        "fault_budget": {"default_trials": 80, "max_faults_per_sequence": 8,
                         "extension_trials": 128, "extension_max_faults": 10,
                         "extension_requires_stable_io_family_or_production_coverage": True,
                         "current_trials": state["budget_total"],
                         "current_max_faults": state["max_faults"]},
        "extension_checkpoint": state.get("extension_checkpoint"),
        "bug_mark": "candidate_unconfirmed" if state["bug_candidates"] else "none",
        "bug_candidates": state["bug_candidates"],
        "stopping_reason": state["stop_reason"] or "Shared HBASE-12 original JUnit campaign running",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    atomic_json(CASES / "HBASE-31" / "trials-summary.json", rows)
    atomic_json(path, result)


def sync() -> bool:
    snap = snapshot()
    publish_b3(snap["shared"], snap["unique"])
    publish_rs(snap["rs"])
    if snap["unique"]:
        print("SYNC unique", len(snap["unique"]["rows"]),
              "RS", len(snap["rs"]["rows"]) if snap["rs"] else 0,
              "stop", snap["unique"]["state"]["stop_reason"], flush=True)
    return bool(snap["unique"] and snap["unique"]["state"]["stop_reason"] and
                snap["shared"] and snap["shared"]["state"]["stop_reason"] and
                snap["rs"] and snap["rs"]["state"]["stop_reason"])


if __name__ == "__main__":
    once = "--once" in sys.argv
    while True:
        try:
            done = sync()
            if once or done:
                break
        except Exception as error:
            print("SYNC_ERROR", type(error).__name__ + ":", error, flush=True)
            if once:
                raise
        time.sleep(20)
