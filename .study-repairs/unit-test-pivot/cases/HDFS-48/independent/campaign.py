#!/usr/bin/env python3
"""Checkpointed coverage and observed-IPC fuzzing of the original HDFS-48 JUnit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
EVIDENCE = HERE / "evidence"
HEALTHY = EVIDENCE / "instrumented-healthy-01"
STATE = EVIDENCE / "campaign-state.json"
LEDGER = HERE / "trial-ledger.csv"
RESULT = CASE / "result.json"
RUNNER = HERE / "run_original.py"
KINDS = ("IOException", "SocketTimeoutException", "EOFException")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temp, path)


def events(path: Path) -> list[tuple[int, str, list[str]]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        pieces = line.split("\t")
        if len(pieces) >= 3:
            rows.append((int(pieces[0]), pieces[1], pieces[3:]))
    return rows


def covered(path: Path) -> set[str]:
    return set(path.read_text().splitlines()) if path.is_file() else set()


def selector(row: tuple[int, str, list[str]], kind: str) -> str:
    fields = row[2]
    return "|".join((fields[0], fields[1], fields[2], kind))


def family(row: tuple[int, str, list[str]]) -> str:
    return "|".join(row[2][:2])


def first_target(rows: list[tuple[int, str, list[str]]], after: int = 0):
    # The first occurrence is the test's direct root.replaceChild spy setup.
    # The selected rollback check is the later /dir1/foo occurrence.
    return next((row for row in rows if row[1] == "TARGET_GUARD" and row[0] > after
                 and row[2][0] == "/dir1" and row[2][1] == "foo"), None)


def available_io(rows: list[tuple[int, str, list[str]]], after: int = 0):
    target = first_target(rows, after)
    if target is None:
        return []
    return [row for row in rows if row[1] == "IO" and after < row[0] < target[0]]


def initial() -> dict:
    manifest = json.loads((HEALTHY / "manifest.json").read_text())
    rows = events(HEALTHY / "runtime_trace.tsv")
    assert manifest["returncode"] == 0, "Original JUnit healthy run must pass"
    assert first_target(rows) is not None, "Exact rollback replaceChild guard was not reached"
    assert not any(row[1] == "TARGET_FALSE" and row[2][:2] == ["/dir1", "foo"]
                   for row in rows), "Healthy selected guard unexpectedly failed"
    io = available_io(rows)
    assert io, "No observed IPC event before target"
    # The client's late RPC response reads are closest to rename rollback.
    io.sort(key=lambda row: (row[2][1] != "main", -row[0]))
    queue = [{"plan": [selector(row, kind)],
              "priority": 10 if row[2][1] == "main" else 5}
             for row in io for kind in KINDS]
    state = {"schema": 1, "budget": {"max_trials": 80, "max_faults": 8},
             "healthy_seconds": manifest["elapsed_seconds"], "queue": queue,
             "seen_plans": [item["plan"] for item in queue], "completed": [],
             "coverage": sorted(covered(HEALTHY / "covered_probes.txt")),
             "io_families": sorted({family(row) for row in rows if row[1] == "IO"}),
             "active": None, "next_trial": 1, "stop_reason": None}
    save(state)
    return state


def write_ledger(state: dict) -> None:
    columns = ["trial", "elapsed_seconds", "fault_count", "matched_faults", "applied_faults",
               "exact_order_applied", "target_after_fault", "selected_target_throw", "junit_exit",
               "coverage_gain", "new_io_families", "plan", "run_dir"]
    temp = LEDGER.with_name(LEDGER.name + ".tmp")
    with temp.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for trial in state["completed"]:
            writer.writerow({key: json.dumps(trial[key]) if key == "plan" else trial[key]
                             for key in columns})
    os.replace(temp, LEDGER)


def update_result(state: dict) -> None:
    old = json.loads(RESULT.read_text())
    trials = state["completed"]
    valid = [item for item in trials if item["exact_order_applied"] and item["target_after_fault"]]
    old.update({"status": "fuzzing" if not state["stop_reason"] else "pending_source_review",
                "methodology": "original_cluster_junit_case_local_asm_jacoco_graph_free",
                "target_reached": True, "fault_trials": len(trials),
                "strict_injections": sum(item["exact_order_applied"] for item in trials),
                "fully_applied_trials": sum(item["exact_order_applied"] for item in trials),
                "target_after_fault": len(valid),
                "effective_trials": len(valid),
                "selected_target_throws": sum(item["selected_target_throw"] for item in valid),
                "coverage_gain": len(set(state["coverage"]) - covered(HEALTHY / "covered_probes.txt")),
                "elapsed_seconds": round(state["healthy_seconds"] + sum(item["elapsed_seconds"] for item in trials), 3),
                "max_faults": state["budget"]["max_faults"], "campaign_budget": state["budget"],
                "stop_reason": state["stop_reason"], "independent_evidence": "independent/evidence/campaign-state.json",
                "trial_ledger": "independent/trial-ledger.csv",
                "bug_mark": "candidate_needs_replay_source_review" if any(item["selected_target_throw"] for item in valid) else "none"})
    atomic_json(RESULT, old)


def save(state: dict) -> None:
    atomic_json(STATE, state)
    write_ledger(state)
    update_result(state)


def enqueue(state: dict, plan: list[str], priority: int) -> None:
    if len(plan) > state["budget"]["max_faults"] or plan in state["seen_plans"]:
        return
    state["seen_plans"].append(plan)
    state["queue"].append({"plan": plan, "priority": priority})


def run_trial(job: dict, number: int) -> dict:
    out = EVIDENCE / "runs" / ("trial-%03d" % number)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not (out / "manifest.json").is_file():
        # A stopped runner may leave an incomplete trace. Rebuild that trial
        # cleanly instead of appending events to a partial execution.
        shutil.rmtree(out, ignore_errors=True)
        command = [sys.executable, str(RUNNER), "--output", str(out),
                   "--plan", "|||".join(job["plan"]), "--timeout", "180"]
        with (out.parent / (out.name + "-driver.log")).open("w") as log:
            subprocess.run(command, cwd=HERE, stdout=log, stderr=subprocess.STDOUT,
                           timeout=240, check=False)
    manifest = json.loads((out / "manifest.json").read_text())
    rows = events(out / "runtime_trace.tsv")
    applied = [row for row in rows if row[1] == "FAULT_APPLIED"]
    matched = [row for row in rows if row[1] == "FAULT_MATCHED"]
    actual = ["|".join((*row[2][:3], row[2][4])) for row in applied]
    exact = actual == job["plan"] and len(matched) == len(job["plan"])
    last_fault = applied[-1][0] if exact else 0
    target = first_target(rows, last_fault) if exact else None
    target_path = target[2][0] + "/" + target[2][1] if target else None
    throws = [row for row in rows if row[1] == "TARGET_FALSE" and row[0] > last_fault
              and row[2][:2] == ["/dir1", "foo"]] if target else []
    probes = covered(out / "covered_probes.txt")
    io = {family(row) for row in rows if row[1] == "IO"}
    return {"trial": number, "elapsed_seconds": manifest["elapsed_seconds"],
            "fault_count": len(job["plan"]), "matched_faults": len(matched),
            "applied_faults": len(applied), "exact_order_applied": exact,
            "target_after_fault": target is not None, "target_path": target_path,
            "selected_target_throw": len(throws), "junit_exit": manifest["returncode"],
            "coverage_gain": 0, "new_io_families": 0,
            "plan": job["plan"], "run_dir": str(out.relative_to(CASE)),
            "observed_io": [selector(row, KINDS[0]) for row in available_io(rows, last_fault)] if target else [],
            "observed_probes": sorted(probes), "observed_families": sorted(io),
            "last_applied_sequence": last_fault}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-trials", type=int, default=80)
    parser.add_argument("--max-attempts", type=int, default=180)
    parser.add_argument("--max-seconds", type=int, default=9000)
    parser.add_argument("--max-faults", type=int, default=8)
    args = parser.parse_args()
    state = json.loads(STATE.read_text()) if STATE.is_file() else initial()
    state["budget"] = {"max_trials": args.max_trials, "max_faults": args.max_faults}
    state.setdefault("started_at", time.time())
    # All three exceptions at the immediately preceding main read (#16)
    # retained the rollback guard; ordinals 10-15 repeatedly lost it.
    # Explore other observed thread roles before more of that prefix.
    for job in state["queue"]:
        last = job["plan"][-1].split("|")
        if (len(last) == 4 and last[0] == "Client.getRpcResponse"
                and last[1] == "main" and int(last[2]) < 16):
            job["priority"] = min(job["priority"], 2)
    state["stop_reason"] = None
    effective = lambda: sum(x["exact_order_applied"] and x["target_after_fault"]
                            for x in state["completed"])
    while (effective() < args.max_trials and len(state["completed"]) < args.max_attempts
           and time.time() - state["started_at"] < args.max_seconds and state["queue"]):
        if state["active"] is None:
            chosen = max(range(len(state["queue"])), key=lambda i: (state["queue"][i]["priority"], -i))
            state["active"] = {"job": state["queue"].pop(chosen), "trial": state["next_trial"]}
            state["next_trial"] += 1
            save(state)
        active = state["active"]
        trial = run_trial(active["job"], active["trial"])
        valid = trial["exact_order_applied"] and trial["target_after_fault"]
        if valid:
            known_coverage = set(state["coverage"])
            known_io = set(state["io_families"])
            probes = set(trial.pop("observed_probes"))
            families = set(trial.pop("observed_families"))
            trial["coverage_gain"] = len(probes - known_coverage)
            trial["new_io_families"] = len(families - known_io)
            state["coverage"] = sorted(known_coverage | probes)
            state["io_families"] = sorted(known_io | families)
            if len(active["job"]["plan"]) < args.max_faults:
                for selector_base in trial["observed_io"]:
                    for kind in KINDS:
                        plan = active["job"]["plan"] + [selector_base.rsplit("|", 1)[0] + "|" + kind]
                        priority = 3 + trial["coverage_gain"] + 2 * trial["new_io_families"] + len(plan)
                        enqueue(state, plan, priority)
        else:
            trial.pop("observed_probes")
            trial.pop("observed_families")
        trial.pop("observed_io")
        state["completed"].append(trial)
        state["active"] = None
        save(state)
        # Hadoop scratch is reset on every JUnit run; preserve trace, coverage, logs, and plan.
        shutil.rmtree((CASE / trial["run_dir"] / "scratch"), ignore_errors=True)
        # Raw JaCoCo is the reproducible coverage artifact. The large derived
        # text lists have already been merged into the checkpoint.
        for derived in (CASE / trial["run_dir"]).glob("covered_*.txt"):
            derived.unlink()
        if trial["selected_target_throw"] and valid:
            state["stop_reason"] = "target_exception_candidate_requires_replay_and_source_review"
            save(state)
            break
    if not state["stop_reason"]:
        state["stop_reason"] = ("effective_budget_exhausted" if effective() >= args.max_trials
                                else "attempt_cap" if len(state["completed"]) >= args.max_attempts
                                else "wall_clock_cap" if time.time() - state["started_at"] >= args.max_seconds
                                else "queue_exhausted")
    save(state)
    print(json.dumps({"trials": len(state["completed"]), "stop_reason": state["stop_reason"]}))


if __name__ == "__main__":
    main()
