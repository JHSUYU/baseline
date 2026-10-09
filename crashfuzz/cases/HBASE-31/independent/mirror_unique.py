#!/usr/bin/env python3
"""Independent HBASE-31 oracle ledger for the shared HBASE-12 original JUnit runs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import time

BASE = Path(__file__).resolve().parent
SOURCE = BASE.parents[1] / "HBASE-12" / "independent" / "unique"
sys.path.insert(0, str(SOURCE))
import campaign as runner  # noqa: E402

STATE = BASE / "mirror-state.json"
CHECKPOINTS = BASE / "checkpoints"


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def effective(row: dict, max_faults: int) -> bool:
    return (0 < row["requested"] <= max_faults
            and row["requested"] == row["matched"] == row["applied"]
            and row["strict_identity_match"] and row["target_after_fault"]
            and row["elapsed_seconds"] is not None)


def initialize(source: dict) -> dict:
    targets = runner.rs_events(SOURCE / "gf_healthy.log")
    if not targets or any(t.get("mismatch") != "false" for t in targets):
        raise RuntimeError("original JUnit did not reach healthy HBASE-31 guard")
    obs = runner.observations(SOURCE / "gf_healthy.log")
    last = max(t["exit_position"] for t in targets)
    io = [p for p in obs["points"] if p["position"] < last]
    covered = runner.probes(SOURCE / "gf_healthy.coverage")
    if not covered or not io:
        raise RuntimeError("combined healthy seed lacked I/O or JaCoCo coverage")
    state = {
        "schema_version": 1,
        "case_id": "HBASE-31",
        "methodology": "coverage_io_independent_bytebuddy_jacoco_shared_junit",
        "shared_execution": True,
        "source_case": "HBASE-12/independent/unique",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "completed": [],
        "budget_total": 80,
        "max_faults": 8,
        "coverage_scope_version": source["coverage_scope_version"],
        "coverage_probes": sorted(covered),
        "seen_stable_families": sorted({p["family"] for p in io}),
        "bug_candidates": [],
        "stop_reason": "",
        "healthy": {
            "elapsed_seconds": obs["elapsed_seconds"],
            "target_checks": len(targets),
            "target_exceptions": 0,
            "target_guard_outcomes": [t["mismatch"] for t in targets],
            "io_points": len(io),
            "stable_io_families": len({p["family"] for p in io}),
            "coverage_probes": len(covered),
            "production_methods_covered": source["healthy"]["production_methods_covered"],
            "production_branches_covered": source["healthy"]["production_branches_covered"],
            "production_lines_covered": source["healthy"]["production_lines_covered"],
            "source_trace": str(SOURCE / "gf_healthy.log"),
        },
    }
    save(STATE, state)
    return state


def add_trial(state: dict, name: str) -> dict:
    source = json.loads((SOURCE / "campaign-checkpoints" / (name + ".json")).read_text())
    trace_path = SOURCE / (name + ".log")
    targets = runner.rs_events(trace_path)
    obs = runner.observations(trace_path)
    last_applied = obs["applied"][-1]["position"] if obs["applied"] else -1
    strict = source["strict_identity_match"] and len(obs["applied"]) == source["applied"]
    later = [t for t in targets if t["exit_position"] > last_applied] if strict else []
    target_exception = any(
        t.get("mismatch") == "true"
        and t.get("exception") == "org.apache.hbase.thirdparty.com.google.protobuf.ServiceException"
        and t.get("cause") == "org.apache.hadoop.hbase.DoNotRetryIOException"
        for t in later)
    io = [p for p in obs["points"]
          if targets and p["position"] < targets[-1]["exit_position"]]
    families = {p["family"] for p in io}
    covered = runner.probes(SOURCE / (name + ".coverage"))
    valid = strict and bool(later) and source["elapsed_seconds"] is not None
    new_probes = sorted(covered - set(state["coverage_probes"])) if valid else []
    new_families = sorted(families - set(state["seen_stable_families"])) if valid else []
    row = {
        "trial": name,
        "shared_execution": True,
        "shared_source_trial": "HBASE-12/unique/" + name,
        "source_checkpoint": str(SOURCE / "campaign-checkpoints" / (name + ".json")),
        "source_trace": str(trace_path),
        "source_coverage": str(SOURCE / (name + ".coverage")),
        "faults": source["faults"],
        "requested": source["requested"],
        "matched": source["matched"],
        "applied": source["applied"],
        "strict_identity_match": strict,
        "target_after_fault": bool(later),
        "target_exception_after_fault": target_exception,
        "target_guard_hits": len(targets),
        "target_after_fault_hits": len(later),
        "target_outcomes": [{key: t.get(key) for key in (
            "ordinal", "requestedStartCode", "actualStartCode", "mismatch",
            "exception", "cause", "exit_position")} | {
            "after_last_fault": strict and t["exit_position"] > last_applied}
            for t in targets],
        "exit_code": source["exit_code"],
        "junit_result": source["junit_result"],
        "elapsed_seconds": source["elapsed_seconds"],
        "started_utc": source["started_utc"],
        "ended_utc": source["ended_utc"],
        "observed_io_points": len(io),
        "observed_stable_families": len(families),
        "new_stable_families": new_families,
        "new_production_probes": new_probes,
        "coverage_probe_count": len(covered),
        "production_methods_covered": source["production_methods_covered"],
        "production_branches_covered": source["production_branches_covered"],
        "production_lines_covered": source["production_lines_covered"],
    }
    save(CHECKPOINTS / (name + ".json"), row)
    state["completed"].append(name)
    if valid:
        state["coverage_probes"] = sorted(set(state["coverage_probes"]) | covered)
        state["seen_stable_families"] = sorted(set(state["seen_stable_families"]) | families)
    if target_exception:
        state["bug_candidates"].append(name)
    save(STATE, state)
    return row


def poll() -> bool:
    source_path = SOURCE / "campaign-state.json"
    if not source_path.exists():
        return False
    source = json.loads(source_path.read_text())
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize(source)
    for name in source["completed"][len(state["completed"]):]:
        row = add_trial(state, name)
        print("MIRROR HBASE-31", name, "exact", row["strict_identity_match"],
              "after", row["target_after_fault"],
              "exception", row["target_exception_after_fault"], flush=True)
    rows = [json.loads((CHECKPOINTS / (name + ".json")).read_text())
            for name in state["completed"]]
    valid = [row for row in rows if effective(row, state["max_faults"])]
    if len(valid) >= 80 and "extension_checkpoint" not in state:
        recent = valid[64:80]
        new_coverage = sum(bool(r["new_production_probes"]) for r in recent)
        new_io = sum(bool(r["new_stable_families"]) for r in recent)
        extension = bool(new_coverage or new_io)
        state["extension_checkpoint"] = {
            "recent_effective_trials": [r["trial"] for r in recent],
            "recent_new_production_coverage_trials": new_coverage,
            "recent_new_stable_io_family_trials": new_io,
            "extended": extension,
        }
        if extension:
            state["budget_total"] = 128
            state["max_faults"] = 10
        save(STATE, state)
    if source["stop_reason"]:
        state["stop_reason"] = ("shared_source_finished_budget_reached" if
                                len(valid) >= state["budget_total"] else
                                "shared_source_finished_additional_unique_trials_needed")
        save(STATE, state)
        return True
    return False


if __name__ == "__main__":
    once = "--once" in sys.argv
    while True:
        try:
            done = poll()
            if once or done:
                break
        except Exception as error:
            print("MIRROR_ERROR", type(error).__name__ + ":", error, flush=True)
            if once:
                raise
        time.sleep(10)
