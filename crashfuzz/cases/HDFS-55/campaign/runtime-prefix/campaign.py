#!/usr/bin/env python3
"""Resumable runtime-ordered cached-key rejection sequence calibration."""

import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CASE = HERE.parents[1]
STATE = HERE / "state.json"
ORIGINAL = HERE / "build/original-overlay"
FIXED = HERE / "build/fixed-overlay"
FAULT = re.compile(r"CASE55 runtime_prefix_fault=(\d+) attempt=(\d+) role=balancer-target-dn manager=(\d+) target=([^ ]+) key_id=([^ ]+) refresh=false")
GUARD = re.compile(r"CASE55 key_guard=(\d+) manager=(\d+) cached_key_id=([^ ]+) refresh=(\w+) after_fault=(\w+)")
FAIL = re.compile(r"CONTROL original_junit_failures=(\d+)")
EXIT_ASSERTION = re.compile(r"expected:<0> but was:<(-?\d+)>")
KINDS = ("methods", "branch_counts", "probes")


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def coverage_ids(directory, kind):
    file = directory / f"covered_{kind}.txt"
    if not file.is_file():
        return set()
    return {line for line in file.read_text().splitlines()
            if "Hdfs17899Probe" not in line and "RunOneJUnit" not in line}


def parse(directory, budget, cumulative):
    manifest = json.loads((directory / "manifest.json").read_text())
    lines = (directory / "junit.log").read_text(errors="replace").splitlines()
    faults = []
    last_fault_line = -1
    junit_failures = None
    failed_exit_status = None
    for index, line in enumerate(lines):
        if match := FAULT.search(line):
            faults.append({"sequence": int(match.group(1)), "attempt": int(match.group(2)),
                           "manager_identity": int(match.group(3)), "target_dn": match.group(4),
                           "key_id": match.group(5)})
            last_fault_line = index
        if match := FAIL.search(line):
            junit_failures = int(match.group(1))
        if match := EXIT_ASSERTION.search(line):
            failed_exit_status = int(match.group(1))
    ordered = [item["sequence"] for item in faults] == list(range(1, budget + 1))
    coherent = len({(item["manager_identity"], item["key_id"]) for item in faults}) <= 1
    post_guards = []
    if faults:
        final = faults[-1]
        for line in lines[last_fault_line + 1:]:
            if match := GUARD.search(line):
                if (int(match.group(2)) == final["manager_identity"]
                        and match.group(3) == final["key_id"]
                        and match.group(5) == "true"):
                    post_guards.append({"refresh": match.group(4) == "true",
                                        "manager_identity": int(match.group(2)),
                                        "key_id": match.group(3)})
    complete = (manifest["returncode"] in (0, 1) and junit_failures is not None
                and (directory / "jacoco.exec").is_file()
                and (directory / "jacoco.exec").stat().st_size > 0
                and (directory / "covered_methods.txt").is_file())
    fully_applied = ordered and coherent and len(faults) == budget
    target_after = bool(post_guards)
    coverage = {kind: coverage_ids(directory, kind) for kind in KINDS}
    return {"budget_faults": budget, "faults": faults,
            "matched_fault_count": len(faults), "applied_fault_count": len(faults),
            "in_runtime_order": ordered, "identity_coherent": coherent,
            "fully_applied": fully_applied, "target_after_final_fault": target_after,
            "postfault_cached_reuse": sum(not g["refresh"] for g in post_guards),
            "operation_failed": junit_failures is not None and junit_failures > 0,
            "oracle_candidate": bool(faults) and junit_failures is not None and junit_failures > 0,
            "junit_failures": junit_failures, "returncode": manifest["returncode"],
            "balancer_exit_status": (failed_exit_status if failed_exit_status is not None
                                     else 0 if junit_failures == 0 else None),
            "balancer_successful_assertion_phases": sum(
                "TestBalancer.java:runBalancer(828)" in line for line in lines),
            "harness_complete": complete,
            "successful_block_moves": sum("Successfully moved blk_" in line for line in lines),
            "cache_clear_events": sum("CASE55 balancer_key_cache_cleared=true" in line for line in lines),
            "coverage_gain": {kind: len(coverage[kind] - cumulative[kind]) for kind in KINDS},
            "covered_counts": {kind: len(coverage[kind]) for kind in KINDS},
            "elapsed_seconds": manifest["elapsed_seconds"],
            "log": str((directory / "junit.log").relative_to(CASE)),
            "manifest": str((directory / "manifest.json").relative_to(CASE))}


def ledger(state):
    with (HERE / "trial-ledger.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("run", "budget", "applied", "ordered", "same_manager_key",
                         "target_after_final", "cached_reuse_after_final", "moves",
                         "junit_failures", "balancer_exit_status", "method_gain",
                         "branch_gain", "elapsed_seconds"))
        for row in state["trials"]:
            writer.writerow((row["id"], row["budget_faults"], row["applied_fault_count"],
                             row["in_runtime_order"], row["identity_coherent"],
                             row["target_after_final_fault"], row["postfault_cached_reuse"],
                             row["successful_block_moves"], row["junit_failures"],
                             row["balancer_exit_status"],
                             row["coverage_gain"]["methods"],
                             row["coverage_gain"]["branch_counts"], row["elapsed_seconds"]))


def execute(output, overlay, budget):
    if (output / "manifest.json").is_file():
        return
    command = [sys.executable, str(CASE / "run_control.py"),
               "--output", str(output), "--overlay", str(overlay),
               "--inject", "--runtime-prefix-faults", str(budget)]
    with (HERE / (output.name + ".runner.log")).open("w") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-faults", type=int, default=20)
    args = parser.parse_args()
    if not ORIGINAL.is_dir() or not FIXED.is_dir():
        raise SystemExit("build case-local original and fixed overlays first")
    if STATE.exists():
        state = json.loads(STATE.read_text())
    else:
        state = {"case_id": "HDFS-55", "family": "runtime_ordered_cached_key_prefix",
                 "not_exact_ordinal_fuzz": True, "status": "running", "max_faults": args.max_faults,
                 "trials": [], "fixed_replay": None}
    state["max_faults"] = args.max_faults
    state["status"] = "running"
    atomic(STATE, state)
    cumulative = {kind: coverage_ids(CASE / "evidence/healthy-01", kind)
                  for kind in KINDS}
    for row in state["trials"]:
        if row["harness_complete"] and row["fully_applied"] and row["target_after_final_fault"]:
            for kind in KINDS:
                cumulative[kind].update(coverage_ids(HERE / "runs" / row["id"], kind))
    start = len(state["trials"]) + 1
    for budget in range(start, args.max_faults + 1):
        output = HERE / "runs" / f"prefix-{budget:02d}"
        execute(output, ORIGINAL, budget)
        row = parse(output, budget, cumulative)
        row["id"] = output.name
        state["trials"].append(row)
        if row["harness_complete"] and row["fully_applied"] and row["target_after_final_fault"]:
            for kind in KINDS:
                cumulative[kind].update(coverage_ids(output, kind))
        atomic(STATE, state)
        ledger(state)
        if row["oracle_candidate"] or not (row["harness_complete"] and
                                          row["fully_applied"] and row["target_after_final_fault"]):
            break
    candidate = next((row for row in state["trials"] if row["oracle_candidate"]
                      and row["fully_applied"] and row["target_after_final_fault"]), None)
    if candidate:
        output = HERE / "fixed-replay" / candidate["id"]
        execute(output, FIXED, candidate["budget_faults"])
        state["fixed_replay"] = parse(output, candidate["budget_faults"], cumulative)
        state["fixed_replay"]["id"] = candidate["id"]
    state["status"] = ("failure_candidate_with_fixed_replay" if state["fixed_replay"]
                       else "budget_or_target_stop")
    atomic(STATE, state)
    ledger(state)
    print(json.dumps({"status": state["status"], "trials": len(state["trials"]),
                      "candidate": candidate["id"] if candidate else None}))


if __name__ == "__main__":
    main()
