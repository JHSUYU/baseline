#!/usr/bin/env python3
"""Publish only the independent HBASE-04 campaign into the 102-check ledger."""

from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess
import time


CASE = Path(__file__).resolve().parent
RESULT = CASE / "result.json"
TRIALS = CASE / "trials-summary.json"
SOURCE = r'''
from pathlib import Path
import json
p=Path('/users/ZhenyuLi/baseline/crashfuzz/cases/HBASE-04/graphfree-validation')
validation_file=p/'validation.json'
validation=json.loads(validation_file.read_text()) if validation_file.exists() else None
state_file=p/'campaign-state.json'
if state_file.exists():
    s=json.loads(state_file.read_text())
    rows=[]
    for name in s['completed']:
        file=p/'campaign-checkpoints'/(name+'.json')
        if file.exists(): rows.append(json.loads(file.read_text()))
    state={
        'created_utc':s['created_utc'], 'healthy':s['healthy'],
        'budget_total':s['budget_total'], 'max_faults':s['max_faults'],
        'stop_reason':s['stop_reason'], 'queue_length':len(s['queue']),
        'inflight':s['inflight']['trial'] if s['inflight'] else None,
        'stable_families':len(s['seen_stable_families']),
        'production_probes':len(s['coverage_probes']),
        'family_tests':s['family_tests'], 'bug_candidates':s['bug_candidates'],
        'extension_checkpoint':s.get('extension_checkpoint'),
        'coverage_scope_version':s.get('coverage_scope_version'),
        'coverage_scope':s.get('coverage_scope',[]),
        'healthy_identity_comparison':s.get('healthy_identity_comparison'),
        'checkpoints':rows,
    }
else:
    state=None
print(json.dumps({'validation':validation,'state':state}))
'''


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def snapshot() -> dict:
    proc = subprocess.run([
        "ssh", "-i", str(Path.home() / ".ssh/id_ed25519_nodes"),
        "-o", "IdentitiesOnly=yes", "ZhenyuLi@node1", "python3", "-"],
        input=SOURCE, text=True, capture_output=True, timeout=20, check=True)
    return json.loads(proc.stdout)


def sync() -> bool:
    result = json.loads(RESULT.read_text())
    if not result.get("legacy_graph_phase2_stop_reason"):
        return False
    snap = snapshot()
    current = datetime.now(timezone.utc)
    validation = snap["validation"]
    if validation:
        result["independent_representative_validation"] = validation
        if validation["ready_for_new_campaign"] and not snap["state"]:
            result["status"] = "pending_independent_campaign_seed"
            result["independent_method_status"] = "representative_replay_passed"
            result["target_reached"] = True
        elif not validation["ready_for_new_campaign"]:
            result["status"] = "pending_independent_recorder_review"
            result["independent_method_status"] = "representative_replay_failed_gate"
    state = snap["state"]
    if not state:
        result["updated_at_utc"] = current.isoformat()
        atomic_json(RESULT, result)
        return False
    rows = state["checkpoints"]
    effective = [row for row in rows if row["requested"] == row["matched"] == row["applied"]
                 and row["target_after_fault"]
                 and 0 < row["requested"] <= state["max_faults"]]
    healthy = state["healthy"]
    elapsed = (current - datetime.fromisoformat(state["created_utc"])).total_seconds()
    result.update({
        "status": ("candidate_review" if state["bug_candidates"] else
                   "pending_source_review" if state["stop_reason"] else "fuzzing"),
        "methodology": "coverage_io_independent_bytebuddy_jacoco",
        "methodology_note": "Case-local ByteBuddy I/O recorder and ordered exception injector; stable family plus occurrence ordinal identity (dynamic socket port logged but excluded); JaCoCo production probe feedback; original HBase JUnit mini cluster; no GraphChecker JAR, woven classes, static region skeleton, aggregate graph, or closure used.",
        "instrumentation_provenance": {
            "recorder": "case-local ByteBuddy HBase04CampaignAgent",
            "coverage": "JaCoCo production probes for " + ", ".join(
                name.rsplit("/", 1)[-1] for name in state["coverage_scope"]),
            "graphchecker_runtime_jar": False,
            "graphchecker_woven_classes": False,
            "static_skeleton": False,
        },
        "coverage_scope_version": state["coverage_scope_version"],
        "coverage_scope": state["coverage_scope"],
        "healthy_identity_comparison": state["healthy_identity_comparison"],
        "independent_method_status": "fuzzing" if not state["stop_reason"] else "pending_final_source_review",
        "target_reached": healthy["target_checks"] == 4,
        "healthy_target_guard_hits": healthy["target_checks"],
        "seed_seconds": healthy["elapsed_seconds"],
        "healthy_fault_points": healthy["io_points"],
        "healthy_production_probes": healthy["coverage_probes"],
        "healthy_method_coverage": healthy.get("production_methods_covered", 0),
        "healthy_branch_outcome_coverage": healthy.get("production_branches_covered", 0),
        "healthy_stable_io_families": healthy["stable_io_families"],
        "fault_trials": len(rows),
        "attempted_fault_trials": len(rows),
        "effective_fault_trials": len(effective),
        "strict_injections": sum(row["strict_identity_match"] for row in rows),
        "fully_applied_trials": sum(row["strict_identity_match"] for row in rows),
        "requested_fault_events": sum(row["requested"] for row in rows),
        "matched_fault_events": sum(row["matched"] for row in rows),
        "applied_fault_events": sum(row["applied"] for row in rows),
        "target_after_fault": sum(row["target_after_fault"] for row in rows),
        "target_exception_after_fault_trials": sum(row["target_exception_after_fault"] for row in rows),
        "coverage_gain": max(0, state["production_probes"] - healthy["coverage_probes"]),
        "production_probe_coverage_total": state["production_probes"],
        "stable_io_family_total": state["stable_families"],
        "trial_results": rows,
        "trial_runtime_total_seconds": round(sum(row["elapsed_seconds"] or 0 for row in rows), 3),
        "total_elapsed_seconds": round(elapsed + (healthy["elapsed_seconds"] or 0), 3),
        "elapsed_seconds": round(elapsed + (healthy["elapsed_seconds"] or 0), 3),
        "fault_budget": {"default_trials": 80, "max_faults_per_sequence": 8,
                         "extension_trials": 128, "extension_max_faults": 10,
                         "extension_requires_stable_io_family_or_production_coverage": True,
                         "current_trials": state["budget_total"],
                         "current_max_faults": state["max_faults"]},
        "extension_checkpoint": state["extension_checkpoint"],
        "queue_length": state["queue_length"],
        "family_tests": state["family_tests"],
        "bug_mark": "candidate_unconfirmed" if state["bug_candidates"] else "none",
        "bug_candidates": state["bug_candidates"],
        "stopping_reason": state["stop_reason"] or "Independent graph-free campaign running",
        "started_at_utc": state["created_utc"],
        "updated_at_utc": current.isoformat(),
    })
    atomic_json(TRIALS, rows)
    atomic_json(RESULT, result)
    print("synced independent", len(rows), "effective", len(effective),
          "target", result["target_after_fault"], "coverage+", result["coverage_gain"],
          "stop", state["stop_reason"], flush=True)
    return bool(state["stop_reason"])


if __name__ == "__main__":
    while True:
        try:
            if sync():
                break
        except Exception as error:
            print("sync failed", type(error).__name__ + ":", error, flush=True)
        time.sleep(20)
