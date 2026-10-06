#!/usr/bin/env python3
"""Target-specific checkpoints derived from shared original-JUnit HBASE-10 executions.

This process never starts a JVM or chooses new faults. It attributes each completed
HBASE-10 execution to the adjacent B2/B3 check using original runtime markers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import time

BASE = Path(__file__).resolve().parent
CASE_ID = BASE.parent.name
if CASE_ID not in {"HBASE-11", "HBASE-12"}:
    raise SystemExit("mirror.py must live in HBASE-11 or HBASE-12 independent directory")
SOURCE = Path("/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/HBASE-10/independent")
STATE = BASE / "mirror-state.json"
CHECKPOINTS = BASE / "checkpoints"
DEFAULT_TRIALS = 80
DEFAULT_MAX_FAULTS = 8
EXTENDED_TRIALS = 128
EXTENDED_MAX_FAULTS = 10
RECENT_WINDOW = 16
B2_EXCEPTION = "org.apache.hadoop.hbase.client.DoNotRetryRegionException"
B3_EXCEPTION = "org.apache.hadoop.hbase.DoNotRetryIOException"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def fields(line: str, prefix: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in line[len(prefix):].split() if "=" in token)


def trace(path: Path) -> dict:
    io = []
    applied = []
    targets = {}
    step = None
    for position, line in enumerate(path.open(errors="replace")):
        line = line.rstrip("\n")
        if line.startswith("HBASE10 STEP_ENTER "):
            step = fields(line, "HBASE10 STEP_ENTER ").get("step")
        elif line.startswith("HBASE10 STEP_EXIT "):
            step = None
        elif line.startswith("HBASE10 IO "):
            event = fields(line, "HBASE10 IO ")
            event["position"] = position
            io.append(event)
            if event.get("applied") == "true":
                applied.append(event)
        elif line.startswith("HBASE10 TARGET_ENTER "):
            event = fields(line, "HBASE10 TARGET_ENTER ")
            event["enter_position"] = position
            event["step"] = step or "unknown"
            targets[event["ordinal"]] = event
        elif line.startswith("HBASE10 TARGET_EXIT "):
            event = fields(line, "HBASE10 TARGET_EXIT ")
            target = targets.get(event["ordinal"])
            if target is not None:
                target.update(event)
                target["exit_position"] = position
    return {"io": io, "applied": applied,
            "targets": sorted((t for t in targets.values() if "exit_position" in t),
                              key=lambda t: t["exit_position"])}


def probes(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.open(errors="replace")
            if line.startswith("PROBE class=")}


def selected(target: dict) -> bool:
    # AssignmentManager.preTransitCheck: B1 precedes B2, and B2 precedes B3.
    if target.get("hasProcedure") != "false" or target.get("b1Thrown") != "false":
        return False
    if CASE_ID == "HBASE-11":
        return True
    return target.get("exception") in {"none", B3_EXCEPTION}


def thrown(target: dict) -> bool:
    return target.get("exception") == (B2_EXCEPTION if CASE_ID == "HBASE-11" else B3_EXCEPTION)


def expected_exception_reason(target: dict, source_row: dict, healthy: dict) -> str | None:
    if not thrown(target):
        return None
    if CASE_ID == "HBASE-11" and target["step"] in healthy["expected_exception_steps"]:
        return "same_B2_state_rejection_as_healthy_JUnit"
    # The source waits for assignment/unassignment before replying. Losing that
    # successful response makes HBaseAdmin retry the completed request, which
    # the source guard rejects because the region is now in the new state.
    if CASE_ID == "HBASE-11":
        expected_method = ("UnassignRegion" if target["step"].startswith("unassign#")
                           else "AssignRegion" if target["step"].startswith("assign#")
                           else None)
        if expected_method and any(
            fault["marker"] == "RPC_RESPONSE"
            and fault["step"] == target["step"]
            and fault["method"].endswith("." + expected_method)
            for fault in source_row["faults"]
        ):
            return "retry_of_completed_admin_transition_after_response_fault"
    return None


def eligible(row: dict, max_faults: int) -> bool:
    return (0 < row["requested"] <= max_faults
            and row["requested"] == row["matched"] == row["applied"]
            and row["strict_identity_match"] and row["target_after_fault"]
            and row["elapsed_seconds"] is not None)


def effective_rows(state: dict) -> list[dict]:
    rows = [json.loads((CHECKPOINTS / (name + ".json")).read_text())
            for name in state["completed"]]
    return [row for row in rows if eligible(row, state["max_faults"])]


def initialize(source_state: dict) -> dict:
    raw = trace(SOURCE / "gf_healthy.log")
    matched = [target for target in raw["targets"] if selected(target)]
    if not matched:
        raise RuntimeError(CASE_ID + " guard was not evaluated by original healthy JUnit")
    baseline_expected_steps = sorted({target["step"] for target in matched if thrown(target)})
    last_target = max(t["exit_position"] for t in matched)
    candidate_io = [p for p in raw["io"] if p["position"] < last_target]
    baseline_probes = probes(SOURCE / "gf_healthy.coverage")
    if not baseline_probes:
        raise RuntimeError("shared healthy execution has no production JaCoCo probes")
    state = {
        "schema_version": 1,
        "case_id": CASE_ID,
        "methodology": "shared_original_junit_execution_target_specific_feedback",
        "created_utc": now(),
        "source_case": "HBASE-10",
        "source_campaign_created_utc": source_state["created_utc"],
        "source_healthy_log": str(SOURCE / "gf_healthy.log"),
        "shared_execution": True,
        "budget_total": DEFAULT_TRIALS,
        "max_faults": DEFAULT_MAX_FAULTS,
        "completed": [],
        "coverage_probes": sorted(baseline_probes),
        "seen_stable_families": sorted({p["family"] for p in candidate_io}),
        "seen_io_ids": sorted({p["id"] for p in candidate_io}),
        "bug_candidates": [],
        "stop_reason": "",
        "healthy": {
            "exit_code": source_state["healthy"]["exit_code"],
            "elapsed_seconds": source_state["healthy"]["elapsed_seconds"],
            "source_target_checks": len(raw["targets"]),
            "target_checks": len(matched),
            "target_exceptions": sum(thrown(t) for t in matched),
            "target_guard_outcomes": [
                {"step": t["step"], "exception": t["exception"],
                 "selected_exception": thrown(t)} for t in matched],
            "expected_exception_steps": baseline_expected_steps,
            "io_points": len(candidate_io),
            "stable_io_families": len({p["family"] for p in candidate_io}),
            "coverage_probes": len(baseline_probes),
            "production_methods_covered": source_state["healthy"]["production_methods_covered"],
            "production_branches_covered": source_state["healthy"]["production_branches_covered"],
            "production_lines_covered": source_state["healthy"]["production_lines_covered"],
        },
    }
    save(STATE, state)
    print("INIT", CASE_ID, "healthy guards", len(matched), "expected exceptions",
          baseline_expected_steps, "families", state["healthy"]["stable_io_families"], flush=True)
    return state


def add_trial(state: dict, name: str) -> dict:
    source_row = json.loads((SOURCE / "campaign-checkpoints" / (name + ".json")).read_text())
    raw = trace(SOURCE / (name + ".log"))
    matching = [target for target in raw["targets"] if selected(target)]
    last_applied = raw["applied"][-1]["position"] if raw["applied"] else -1
    later = [target for target in matching if target["exit_position"] > last_applied]
    strict = (source_row["strict_identity_match"] and
              source_row["requested"] == source_row["matched"] == source_row["applied"] and
              len(raw["applied"]) == source_row["applied"])
    target_after = bool(strict and later)
    selected_exceptions = [target for target in later if thrown(target)] if strict else []
    unexpected = [target for target in selected_exceptions
                  if expected_exception_reason(target, source_row, state["healthy"]) is None]
    covered = probes(SOURCE / (name + ".coverage"))
    families = {p["family"] for p in raw["io"]}
    io_ids = {p["id"] for p in raw["io"]}
    valid = strict and target_after and source_row["elapsed_seconds"] is not None
    new_probes = sorted(covered - set(state["coverage_probes"])) if valid else []
    new_families = sorted(families - set(state["seen_stable_families"])) if valid else []
    row = {
        "trial": name,
        "shared_source_trial": "HBASE-10/" + name,
        "source_checkpoint": str(SOURCE / "campaign-checkpoints" / (name + ".json")),
        "source_trace": str(SOURCE / (name + ".log")),
        "source_coverage": str(SOURCE / (name + ".coverage")),
        "shared_execution": True,
        "faults": source_row["faults"],
        "requested": source_row["requested"],
        "matched": source_row["matched"],
        "applied": source_row["applied"],
        "strict_identity_match": strict,
        "target_after_fault": target_after,
        "target_exception_after_fault": bool(selected_exceptions),
        "expected_target_exception_after_fault": bool(selected_exceptions) and not unexpected,
        "unexpected_target_exception_after_fault": bool(unexpected),
        "target_check_hits": len(matching),
        "target_after_fault_hits": len(later) if strict else 0,
        "target_exception_hits_after_fault": len(selected_exceptions),
        "target_check_outcomes": [
            {"step": t["step"], "exception": t["exception"],
             "selected_exception": thrown(t),
             "expected_exception_reason": expected_exception_reason(
                 t, source_row, state["healthy"]),
             "after_last_fault": strict and t["exit_position"] > last_applied}
            for t in matching],
        "source_target_hits": len(raw["targets"]),
        "junit_result": source_row["junit_result"],
        "exit_code": source_row["exit_code"],
        "elapsed_seconds": source_row["elapsed_seconds"],
        "observed_io_points": len(raw["io"]),
        "observed_stable_families": len(families),
        "new_stable_families": new_families,
        "new_production_probes": new_probes,
        "coverage_probe_count": len(covered),
        "production_methods_covered": source_row["production_methods_covered"],
        "production_branches_covered": source_row["production_branches_covered"],
        "production_lines_covered": source_row["production_lines_covered"],
        "started_utc": source_row["started_utc"],
        "ended_utc": source_row["ended_utc"],
    }
    save(CHECKPOINTS / (name + ".json"), row)
    state["completed"].append(name)
    if valid:
        state["coverage_probes"] = sorted(set(state["coverage_probes"]) | covered)
        state["seen_stable_families"] = sorted(set(state["seen_stable_families"]) | families)
        state["seen_io_ids"] = sorted(set(state["seen_io_ids"]) | io_ids)
    if unexpected:
        state["bug_candidates"].append(name)
    save(STATE, state)
    return row


def maybe_extend(state: dict) -> None:
    rows = effective_rows(state)
    if len(rows) != DEFAULT_TRIALS or state["budget_total"] != DEFAULT_TRIALS:
        return
    recent = rows[-RECENT_WINDOW:]
    coverage = sum(bool(row["new_production_probes"]) for row in recent)
    io = sum(bool(row["new_stable_families"]) for row in recent)
    state["extension_checkpoint"] = {
        "recent_effective_trials": [row["trial"] for row in recent],
        "recent_new_production_coverage_trials": coverage,
        "recent_new_stable_io_family_trials": io,
        "extended": bool(coverage or io),
    }
    if coverage or io:
        state["budget_total"] = EXTENDED_TRIALS
        state["max_faults"] = EXTENDED_MAX_FAULTS
    save(STATE, state)


def poll() -> bool:
    source_file = SOURCE / "campaign-state.json"
    if not source_file.exists():
        return False
    source_state = json.loads(source_file.read_text())
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize(source_state)
    for name in source_state["completed"][len(state["completed"]):]:
        row = add_trial(state, name)
        maybe_extend(state)
        print("MIRROR", CASE_ID, name, "exact", row["strict_identity_match"],
              "after", row["target_after_fault"],
              "selected_exception", row["target_exception_after_fault"],
              "unexpected", row["unexpected_target_exception_after_fault"],
              "new_probes", len(row["new_production_probes"]), flush=True)
    if source_state["stop_reason"]:
        state["stop_reason"] = ("shared_source_finished_budget_reached" if
                                len(effective_rows(state)) >= state["budget_total"] else
                                "shared_source_finished_additional_unique_trials_needed")
        save(STATE, state)
        print("STOP", CASE_ID, state["stop_reason"], "attempts", len(state["completed"]),
              "effective", len(effective_rows(state)), flush=True)
        return True
    return False


if __name__ == "__main__":
    once = "--once" in sys.argv
    while True:
        try:
            done = poll()
            if done or once:
                break
        except Exception as error:
            print("MIRROR_ERROR", type(error).__name__ + ":", error, flush=True)
            if once:
                raise
        time.sleep(10)
