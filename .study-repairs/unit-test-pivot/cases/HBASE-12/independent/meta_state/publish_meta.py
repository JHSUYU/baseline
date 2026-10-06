#!/usr/bin/env python3
"""Publish HBASE-12's separate, bounded TableState I/O audit from node1."""

from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess
import sys
import time

CASE = Path(__file__).resolve().parents[2]
RESULT = CASE / "result.json"
REMOTE = ("/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/"
          "cases/HBASE-12/independent/meta_state")


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def snapshot() -> dict | None:
    remote_script = """
from pathlib import Path
import json
p=Path(%r)
f=p/'campaign-state.json'
if not f.exists():
 print('null')
else:
 s=json.loads(f.read_text())
 rows=[]
 for name in s.get('completed',[]):
  q=p/'checkpoints'/(name+'.json')
  if q.exists(): rows.append(json.loads(q.read_text()))
 print(json.dumps({'state':s,'rows':rows}))
""" % REMOTE
    proc = subprocess.run([
        "ssh", "-C", "-i", str(Path.home() / ".ssh/id_ed25519_nodes"),
        "-o", "IdentitiesOnly=yes", "ZhenyuLi@node1", "python3", "-"],
        input=remote_script, text=True, capture_output=True, timeout=30, check=True)
    return json.loads(proc.stdout)


def publish() -> bool:
    snap = snapshot()
    if not snap:
        return False
    state = snap["state"]
    rows = snap["rows"]
    result = json.loads(RESULT.read_text())
    healthy = state.get("healthy", {})
    exact = [row for row in rows if row["strict_identity_match"]]
    retained = [row for row in exact if row["target_after_fault"]]
    target_exception = [row for row in retained
                        if row["selected_exception_after_fault"]]
    healthy_seconds = healthy.get("elapsed_seconds") or 0
    trial_seconds = sum(row.get("elapsed_seconds") or 0 for row in rows)
    phase = {
        "status": state["phase"],
        "stopping_reason": state.get("stop_reason", ""),
        "methodology": "independent_meta_table_state_io_original_junit",
        "instrumentation_provenance": "case-local HBase12MetaAgent + HBase10Agent; JaCoCo production classes; no GraphChecker runtime, woven classes, skeleton, graph or closure",
        "coverage_scope_note": "Ten production classes including MetaTableAccessor and TableStateManager; never unioned with the preceding RPC-only campaign's nine-class scope",
        "healthy_junit_result": healthy.get("junit_result"),
        "healthy_b3_visits": sum(v["b3_evaluated"] for v in healthy.get("target_visits", [])),
        "healthy_meta_io_points": len(healthy.get("io", [])),
        "healthy_stable_io_families": len(healthy.get("stable_io_families", [])),
        "healthy_production_probes": len(healthy.get("production_probes", [])),
        "healthy_seconds": healthy_seconds,
        "attempted_fault_trials": len(rows),
        "strict_injections": len(exact),
        "target_after_fault": len(retained),
        "exact_b3_exception_trials": len(target_exception),
        "production_probe_gain": max(0, len(state.get("coverage_probes", []))
                                     - len(healthy.get("production_probes", []))),
        "stable_io_family_total": len(state.get("seen_stable_families", [])),
        "trial_runtime_total_seconds": round(trial_seconds, 3),
        "elapsed_seconds": round(healthy_seconds + trial_seconds, 3),
        "trial_results": rows,
    }
    result["supplemental_meta_state_phase"] = phase
    result["supplemental_meta_fault_trials"] = len(rows)
    result["supplemental_meta_elapsed_seconds"] = phase["elapsed_seconds"]
    result["elapsed_seconds_with_meta_supplement"] = round(
        result.get("elapsed_seconds", 0) + phase["elapsed_seconds"], 3)
    if state["phase"] == "complete":
        result["status"] = "pending_source_review_meta_supplement"
    elif state["phase"] == "healthy_failed" or state["phase"] == "healthy_no_target":
        result["status"] = "pending_meta_setup_review"
    else:
        result["status"] = "fuzzing_meta_state_supplement"
    result["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    atomic_json(RESULT, result)
    print("META_SYNC",state["phase"],len(rows),"exact",len(exact),
          "B3-after",len(retained),"B3-exception",len(target_exception),flush=True)
    return state["phase"] in ("complete", "healthy_failed", "healthy_no_target")


if __name__ == "__main__":
    once = "--once" in sys.argv
    while True:
        try:
            done = publish()
            if done or once:
                break
        except Exception as error:
            print("META_SYNC_ERROR",type(error).__name__ + ":",error,flush=True)
            if once:
                raise
        time.sleep(20)
