#!/usr/bin/env python3
"""Publish HBASE-11/12 target-specific projections of shared HBASE-10 JUnit runs."""

from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess
import sys
import time

CASE_ID = sys.argv[1] if len(sys.argv) > 1 else ""
if CASE_ID not in {"HBASE-11", "HBASE-12"}:
    raise SystemExit("usage: sync.py HBASE-11|HBASE-12")
CASE = Path(__file__).resolve().parent.parent / CASE_ID
RESULT = CASE / "result.json"
TRIALS = CASE / "trials-summary.json"
CLIENT_CANDIDATE = CASE / "independent" / "client-candidate.json"
REMOTE = ("/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/"
          + CASE_ID + "/independent")


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def snapshot() -> dict | None:
    script = """
from pathlib import Path
import json
p=Path(%r)
f=p/'mirror-state.json'
if not f.exists():
    print('null')
else:
    s=json.loads(f.read_text())
    rows=[]
    for name in s['completed']:
        c=p/'checkpoints'/(name+'.json')
        if c.exists(): rows.append(json.loads(c.read_text()))
    print(json.dumps({'state':s,'rows':rows}))
""" % REMOTE
    proc = subprocess.run([
        "ssh", "-i", str(Path.home() / ".ssh/id_ed25519_nodes"),
        "-o", "IdentitiesOnly=yes", "ZhenyuLi@node1", "python3", "-"],
        input=script, text=True, capture_output=True, timeout=20, check=True)
    return json.loads(proc.stdout)


def sync() -> bool:
    snap = snapshot()
    if not snap:
        return False
    state = snap["state"]
    rows = snap["rows"]
    result = json.loads(RESULT.read_text())
    client_candidate = (json.loads(CLIENT_CANDIDATE.read_text())
                        if CLIENT_CANDIDATE.exists() else None)
    diagnostic_seconds = 0.0
    if client_candidate:
        diagnostic_seconds += sum(
            replay["elapsed_seconds"]
            for replay in client_candidate.get("clean_same_selector_replays", []))
        diagnostic_seconds += client_candidate.get(
            "secondary_equivalent_assign_replay", {}).get("elapsed_seconds", 0)
    bug_candidates = list(state["bug_candidates"])
    if client_candidate and client_candidate.get("id"):
        bug_candidates.append(client_candidate["id"])
    healthy = state["healthy"]
    effective = [r for r in rows if r["strict_identity_match"]
                 and r["target_after_fault"]
                 and 0 < r["requested"] <= state["max_faults"]
                 and r["requested"] == r["matched"] == r["applied"]]
    status = ("pending_additional_unique_trials" if
              state["stop_reason"].endswith("additional_unique_trials_needed") else
              "pending_source_review" if state["stop_reason"] else
              "fuzzing_shared_execution")
    current = datetime.now(timezone.utc)
    result.update({
        "status": status,
        "methodology": "shared_original_junit_execution_target_specific_feedback",
        "methodology_note": "Graph-free case-local HBASE-10 ByteBuddy/JaCoCo execution is shared without replay; this case independently classifies its own B2 or B3 target, exact exceptions, I/O family novelty, and production coverage. Its own additional fault queue has not started.",
        "shared_execution": True,
        "execution_shared_with": "HBASE-10",
        "instrumentation_provenance": {
            "recorder": "case-local ByteBuddy HBase10Agent",
            "coverage": "JaCoCo original HBase server/client production classes",
            "graphchecker_runtime_jar": False,
            "graphchecker_woven_classes": False,
            "static_skeleton": False,
        },
        "target_reached": healthy["target_checks"] > 0,
        "healthy_target_guard_hits": healthy["target_checks"],
        "healthy_target_exception_hits": healthy["target_exceptions"],
        "healthy_target_guard_outcomes": healthy["target_guard_outcomes"],
        "seed_seconds": healthy["elapsed_seconds"],
        "healthy_fault_points": healthy["io_points"],
        "healthy_stable_io_families": healthy["stable_io_families"],
        "healthy_production_probes": healthy["coverage_probes"],
        "healthy_method_coverage": healthy["production_methods_covered"],
        "healthy_branch_outcome_coverage": healthy["production_branches_covered"],
        "fault_trials": len(rows),
        "attempted_fault_trials": len(rows),
        "effective_fault_trials": len(effective),
        "strict_injections": sum(r["strict_identity_match"] for r in rows),
        "fully_applied_trials": sum(r["strict_identity_match"] for r in rows),
        "requested_fault_events": sum(r["requested"] for r in rows),
        "matched_fault_events": sum(r["matched"] for r in rows),
        "applied_fault_events": sum(r["applied"] for r in rows),
        "target_after_fault": sum(r["target_after_fault"] for r in rows),
        "target_exception_after_fault_trials": sum(r["target_exception_after_fault"] for r in rows),
        "expected_target_exception_after_fault_trials": sum(
            r["expected_target_exception_after_fault"] for r in rows),
        "unexpected_target_exception_after_fault_trials": sum(
            r["unexpected_target_exception_after_fault"] for r in rows),
        "coverage_gain": max(0, len(state["coverage_probes"]) - healthy["coverage_probes"]),
        "production_probe_coverage_total": len(state["coverage_probes"]),
        "stable_io_family_total": len(state["seen_stable_families"]),
        "trial_results": rows,
        "trial_runtime_total_seconds": round(sum(r["elapsed_seconds"] or 0 for r in rows), 3),
        "elapsed_seconds": round(healthy["elapsed_seconds"] +
                                 sum(r["elapsed_seconds"] or 0 for r in rows), 3),
        "diagnostic_replay_total_seconds": round(diagnostic_seconds, 3),
        "elapsed_seconds_with_diagnostics": round(
            healthy["elapsed_seconds"] +
            sum(r["elapsed_seconds"] or 0 for r in rows) + diagnostic_seconds, 3),
        "runtime_accounting_note": "Campaign JVM executions are shared with HBASE-10; per-check campaign times are not additive across these cases. Diagnostic candidate replays are separately timed and excluded from the fuzz budget.",
        "fault_budget": {"default_trials": 80, "max_faults_per_sequence": 8,
                         "extension_trials": 128, "extension_max_faults": 10,
                         "extension_requires_stable_io_family_or_production_coverage": True,
                         "current_trials": state["budget_total"],
                         "current_max_faults": state["max_faults"]},
        "extension_checkpoint": state.get("extension_checkpoint"),
        "bug_mark": "candidate_unconfirmed" if bug_candidates else "none",
        "bug_candidates": bug_candidates,
        "client_level_candidate": client_candidate,
        "stopping_reason": state["stop_reason"] or "Shared HBASE-10 original JUnit campaign running",
        "source_campaign_created_utc": state["source_campaign_created_utc"],
        "updated_at_utc": current.isoformat(),
    })
    if client_candidate:
        result["source_review"] = (
            "Healthy TestRegionMove intentionally throws B2 on both move calls. "
            "After a successful assign/unassign RPC response is replaced by a timeout, "
            "HBaseAdmin retries the already completed transition and B2 correctly "
            "rejects the duplicate request. The externally visible Admin result and "
            "original-JUnit failure are recorded separately as an unconfirmed "
            "client-level candidate; the injected timeout itself is not a bug."
        )
    atomic_json(TRIALS, rows)
    atomic_json(RESULT, result)
    print("SYNC", CASE_ID, len(rows), "effective", len(effective),
          "after", result["target_after_fault"],
          "exceptions", result["target_exception_after_fault_trials"],
          "candidates", state["bug_candidates"],
          "stop", state["stop_reason"], flush=True)
    return bool(state["stop_reason"])


if __name__ == "__main__":
    once = "--once" in sys.argv
    while True:
        try:
            if sync():
                break
        except Exception as error:
            print("SYNC_ERROR", type(error).__name__ + ":", error, flush=True)
            if once:
                raise
        if once:
            break
        time.sleep(20)
