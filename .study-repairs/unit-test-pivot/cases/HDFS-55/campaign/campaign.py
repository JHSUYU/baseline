#!/usr/bin/env python3
"""Checkpointed I/O and coverage guided exact-sequence campaign for HDFS-55."""

import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
STATE = HERE / "state.json"
RUNS = HERE / "runs"
PLANS = HERE / "plans"
HEALTHY = CASE / "evidence/healthy-01"
OVERLAY = HERE / "build/original-overlay"
KINDS = ("probes", "methods", "branch_counts", "lines")

ATTEMPT = re.compile(r"CASE55 balancer_sasl_attempt=(\d+) target=([^ ]+) key_id=([^ ]+)")
MATCH = re.compile(r"CASE55 fault_matched=(\d+) role=balancer-target-dn manager=(\d+) target=([^ ]+) key_id=([^ ]+) refresh=false")
APPLIED = re.compile(r"CASE55 injected_invalid_key_at_balancer_sasl=(\d+)")
GUARD = re.compile(r"CASE55 key_guard=(\d+) manager=(\d+) cached_key_id=([^ ]+) refresh=(\w+) after_fault=(\w+)")
NONMATCH = re.compile(r"CASE55 fault_plan_nonmatch=(\d+) target=([^ ]+) key_id=([^ ]+)")
FAILURES = re.compile(r"CONTROL original_junit_failures=(\d+)")


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def ids(path, kind):
    file = path / ("covered_" + kind + ".txt")
    if not file.is_file():
        return set()
    return {line for line in file.read_text().splitlines()
            if "Hdfs17899Probe" not in line and "RunOneJUnit" not in line}


def plan_path(sequence):
    name = "p" + "_".join(map(str, sequence))
    path = PLANS / (name + ".tsv")
    path.parent.mkdir(parents=True, exist_ok=True)
    expected = "".join(f"{ordinal}\tbalancer-target-dn\tcached-reuse\n"
                       for ordinal in sequence)
    if path.exists() and path.read_text() != expected:
        raise RuntimeError("plan contents changed: " + str(path))
    if not path.exists():
        path.write_text(expected)
    return path


def trial_name(sequence):
    return "p" + "_".join(map(str, sequence))


def parse_trial(sequence, directory, cumulative):
    manifest = json.loads((directory / "manifest.json").read_text())
    lines = (directory / "junit.log").read_text(errors="replace").splitlines()
    attempts = []
    matched = []
    applied = []
    nonmatches = []
    failures = None
    last_applied_line = -1
    for index, line in enumerate(lines):
        if match := ATTEMPT.search(line):
            attempts.append({"ordinal": int(match.group(1)), "target": match.group(2),
                             "key_id": match.group(3), "line": index})
        if match := MATCH.search(line):
            matched.append({"ordinal": int(match.group(1)),
                            "manager_identity": int(match.group(2)),
                            "target_dn": match.group(3), "key_id": match.group(4),
                            "line": index})
        if match := APPLIED.search(line):
            applied.append(int(match.group(1)))
            last_applied_line = index
        if match := NONMATCH.search(line):
            nonmatches.append({"ordinal": int(match.group(1)),
                               "target_dn": match.group(2), "key_id": match.group(3)})
        if match := FAILURES.search(line):
            failures = int(match.group(1))
    planned = list(sequence)
    matched_order = [item["ordinal"] for item in matched]
    applied_order = list(applied)
    matched_ordinals = sorted(matched_order)
    applied_ordinals = sorted(applied_order)
    all_faults_observed = (matched_ordinals == planned and applied_ordinals == planned)
    in_plan_order = matched_order == planned and applied_order == planned
    identity_coherent = len({(item["manager_identity"], item["key_id"])
                             for item in matched}) <= 1
    fully_applied = all_faults_observed and in_plan_order and identity_coherent
    final_identity = next((item for item in reversed(matched)
                           if applied_order and item["ordinal"] == applied_order[-1]), None)
    postfault_guards = []
    if final_identity is not None and last_applied_line >= 0:
        for line in lines[last_applied_line + 1:]:
            match = GUARD.search(line)
            if not match:
                continue
            if (int(match.group(2)) == final_identity["manager_identity"]
                    and match.group(3) == final_identity["key_id"]):
                postfault_guards.append({"manager_identity": int(match.group(2)),
                                         "cached_key_id": match.group(3),
                                         "refresh": match.group(4) == "true",
                                         "after_fault": match.group(5) == "true"})
    target_after_final = bool(postfault_guards)
    target_reuse_after_final = sum(not item["refresh"] and item["after_fault"]
                                   for item in postfault_guards)
    coverage = {kind: ids(directory, kind) for kind in KINDS}
    coverage_complete = ((directory / "jacoco.exec").is_file()
                         and (directory / "jacoco.exec").stat().st_size > 0
                         and (directory / "covered_methods.txt").is_file())
    gain = {kind: len(coverage[kind] - cumulative[kind]) for kind in KINDS}
    healthy_gain = {kind: len(coverage[kind] - ids(HEALTHY, kind))
                    for kind in KINDS}
    moves = sum("Successfully moved blk_" in line for line in lines)
    oracle_candidate = bool(applied) and failures is not None and failures > 0
    harness_complete = manifest["returncode"] in (0, 1) and failures is not None
    result = ("harness_incomplete" if not harness_complete else
              "out_of_order_plan" if all_faults_observed and not in_plan_order else
              "split_cached_key_plan" if all_faults_observed and not identity_coherent else
              "target_retaining" if fully_applied and target_after_final else
              "fully_applied_target_lost" if fully_applied else "incomplete_plan")
    return {
        "result": result, "planned_fault_count": len(sequence),
        "matched_fault_count": len(matched), "applied_fault_count": len(applied),
        "planned_ordinals": planned, "matched_ordinals": matched_ordinals,
        "applied_ordinals": applied_ordinals,
        "matched_observed_order": matched_order,
        "applied_observed_order": applied_order,
        "all_faults_observed": all_faults_observed,
        "in_plan_order": in_plan_order,
        "identity_coherent": identity_coherent,
        "unmatched_ordinals": sorted(
            set(planned) - set(applied_ordinals)),
        "plan_nonmatches": nonmatches, "fully_applied": fully_applied,
        "target_after_final_fault": target_after_final,
        "target_reuse_after_final_fault": target_reuse_after_final,
        "admitted_for_coverage_feedback": harness_complete and fully_applied and target_after_final
                                          and coverage_complete,
        "oracle_candidate": oracle_candidate,
        "matched_runtime_identity": matched,
        "observed_attempts": attempts,
        "operation_failed": failures is not None and failures > 0,
        "original_junit_failures": failures,
        "successful_block_moves": moves,
        "returncode": manifest["returncode"],
        "junit_pass": failures == 0,
        "harness_timeout_after_junit": manifest["returncode"] == 124
                                       and failures is not None,
        "harness_complete": harness_complete,
        "coverage_complete": coverage_complete,
        "elapsed_seconds": manifest["elapsed_seconds"],
        "coverage_gain_vs_cumulative": gain,
        "coverage_gain_vs_healthy": healthy_gain,
        "covered_counts": {kind: len(coverage[kind]) for kind in KINDS},
        "log": str((directory / "junit.log").relative_to(CASE)),
        "coverage": str((directory / "jacoco.exec").relative_to(CASE)),
        "manifest": str((directory / "manifest.json").relative_to(CASE)),
    }


def cumulative_coverage(state):
    cumulative = {kind: ids(HEALTHY, kind) for kind in KINDS}
    for row in state["trials"]:
        admitted = row.get("admitted_for_coverage_feedback")
        if admitted is None:
            directory = RUNS / row["id"]
            admitted = (row["result"] == "target_retaining"
                        and (directory / "jacoco.exec").is_file()
                        and (directory / "jacoco.exec").stat().st_size > 0
                        and (directory / "covered_methods.txt").is_file())
        if not admitted:
            continue
        directory = RUNS / row["id"]
        for kind in KINDS:
            cumulative[kind].update(ids(directory, kind))
    return cumulative


def add_candidate(state, sequence, parent=None, priority=0):
    if any(row["sequence"] == sequence for row in state["queue"] + state["trials"]):
        return
    if len(sequence) > state["budget"]["max_faults"]:
        return
    state["queue"].append({"sequence": sequence, "parent": parent,
                           "priority": priority, "waiting_rounds": 0})


def generate_children(state, row):
    if row["result"] != "target_retaining" or len(row["sequence"]) >= state["budget"]["max_faults"]:
        return
    last = row["sequence"][-1]
    observed = sorted({item["ordinal"] for item in row["observed_attempts"]
                       if item["ordinal"] > last})
    gain = row["coverage_gain_vs_cumulative"]
    # Depth pressure reaches long repeated failures; coverage decides among
    # siblings. Root seeds keep a one-time priority for diverse entry points.
    priority = 1000 + 1000 * len(row["sequence"]) + 10 * gain["methods"] + gain["branch_counts"]
    for ordinal in observed[:2]:
        add_candidate(state, row["sequence"] + [ordinal], row["id"], priority)


def ledger(state):
    path = HERE / "trial-ledger.csv"
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("trial", "plan", "planned", "matched", "applied",
                         "matched_observed_order", "applied_observed_order", "in_plan_order",
                         "identity_coherent",
                         "target_after_final_fault", "cached_key_reuse_after_final",
                         "block_moves", "junit_failures", "oracle_candidate", "covered_method_gain",
                         "elapsed_seconds", "result"))
        for row in state["trials"]:
            writer.writerow((row["id"], "+".join(map(str, row["sequence"])),
                             row["planned_fault_count"], row["matched_fault_count"],
                             row["applied_fault_count"],
                             "+".join(map(str, row.get("matched_observed_order", []))),
                             "+".join(map(str, row.get("applied_observed_order", []))),
                             row.get("in_plan_order"), row.get("identity_coherent"),
                             row["target_after_final_fault"],
                             row["target_reuse_after_final_fault"], row["successful_block_moves"],
                             row["original_junit_failures"], row["oracle_candidate"],
                             row["coverage_gain_vs_cumulative"]["methods"],
                             row["elapsed_seconds"], row["result"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-trials", type=int, default=32)
    parser.add_argument("--max-faults", type=int, default=20)
    parser.add_argument("--max-seconds", type=int, default=3000)
    args = parser.parse_args()
    if not OVERLAY.is_dir():
        subprocess.run([sys.executable, str(CASE / "build_overlay.py"),
                        "--mode", "original", "--build-dir", str(HERE / "build")], check=True)
    if STATE.exists():
        state = json.loads(STATE.read_text())
    else:
        state = {"case_id": "HDFS-55", "known_bug": "HDFS-17899",
                 "fault_policy": "exact_ordinal_cached_reuse",
                 "stateful_differential_separate": True,
                 "budget": {"max_trials": args.max_trials, "max_faults": args.max_faults,
                            "max_seconds": args.max_seconds},
                 "status": "running", "queue": [], "trials": [],
                 "started_wall_time": time.time(), "campaign_elapsed_wall_seconds": 0}
        for ordinal in (1, 2, 3, 4, 5):
            add_candidate(state, [ordinal], priority=5000 - ordinal)
    state["budget"] = {"max_trials": args.max_trials, "max_faults": args.max_faults,
                       "max_seconds": args.max_seconds}
    state["status"] = "running"
    # A larger resumed budget can extend earlier trials that were terminal
    # only under the previous, smaller max-fault setting.
    for completed in list(state["trials"]):
        generate_children(state, completed)
    atomic(STATE, state)
    while state["queue"] and len(state["trials"]) < args.max_trials:
        if state["campaign_elapsed_wall_seconds"] >= args.max_seconds:
            state["status"] = "time_budget_exhausted"
            break
        state["queue"].sort(key=lambda x: (-x["priority"] - x["waiting_rounds"],
                                           len(x["sequence"]), x["sequence"]))
        candidate = state["queue"].pop(0)
        for waiting in state["queue"]:
            waiting["waiting_rounds"] += 1
        seq = candidate["sequence"]
        name = trial_name(seq)
        plan = plan_path(seq)
        output = RUNS / name
        output.mkdir(parents=True, exist_ok=True)
        recovered = (output / "manifest.json").is_file()
        started = time.monotonic()
        if not recovered:
            command = [sys.executable, str(CASE / "run_control.py"),
                       "--output", str(output), "--overlay", str(OVERLAY),
                       "--inject", "--plan", str(plan)]
            with (HERE / (name + ".runner.log")).open("w") as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
        charged = (json.loads((output / "manifest.json").read_text())["elapsed_seconds"]
                   if recovered and (output / "manifest.json").is_file()
                   else round(time.monotonic() - started, 3))
        state["campaign_elapsed_wall_seconds"] += charged
        if not (output / "manifest.json").is_file():
            state["queue"].insert(0, candidate)
            state["status"] = "runner_error"
            atomic(STATE, state)
            break
        row = parse_trial(seq, output, cumulative_coverage(state))
        row.update({"id": name, "sequence": seq, "parent": candidate["parent"],
                    "recovered_existing_run": recovered})
        state["trials"].append(row)
        generate_children(state, row)
        atomic(STATE, state)
        ledger(state)
    else:
        state["status"] = ("trial_budget_exhausted" if state["queue"] else "queue_exhausted")
    atomic(STATE, state)
    ledger(state)


if __name__ == "__main__":
    main()
