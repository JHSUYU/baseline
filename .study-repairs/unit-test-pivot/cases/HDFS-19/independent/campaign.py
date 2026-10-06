#!/usr/bin/env python3
"""Resumable coverage and I/O guided campaign for the original HDFS-19 JUnit."""

from __future__ import annotations

from collections import Counter
import csv
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
STATE = HERE / "campaign-state.json"
LOCK = HERE / "campaign.lock"
RESULT = CASE / "result.json"
LEDGER = CASE / "independent-trial-ledger.csv"
RUNNER = HERE / "run_original.py"
HEALTHY = HERE / "healthy-instrumented-02"
SMOKE = HERE / "smoke-first-block-report"
KINDS = ("IOException", "EOFException", "SocketTimeoutException")
TARGET = "BPOfferService.processCommandFromActive#L768"
THROW = "BPOfferService.processCommandFromActive#L769"
COVERAGE = ("probes", "methods", "branch_counts")


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def rows(directory: Path) -> list[dict]:
    return [json.loads(line) for line in
            (directory / "runtime_trace.jsonl").read_text().splitlines() if line]


def covered(directory: Path, category: str) -> set[str]:
    path = directory / ("covered_" + category + ".txt")
    return set(path.read_text().splitlines()) if path.exists() else set()


def point(event: dict, kind: str) -> dict:
    return {**{key: event[key] for key in
               ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal")},
            "faultType": kind}


def sequence_id(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:20]


def family(value: dict) -> str:
    return "|".join(value[key] for key in ("marker", "siteId", "sourceKey"))


def event_matches(event: dict, selected: dict, index: int) -> bool:
    return event.get("planIndex") == index and all(
        event.get(key) == selected[key] for key in
        ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal", "faultType"))


def evaluate(directory: Path, sequence: list[dict], state: dict) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    trace = rows(directory)
    matched = [event for event in trace if event["event"] == "FAULT_MATCHED"]
    applied = [event for event in trace if event["event"] == "FAULT_APPLIED"]
    exact = (len(matched) == len(applied) == len(sequence)
             and all(event_matches(matched[i], sequence[i], i)
                     and event_matches(applied[i], sequence[i], i)
                     and matched[i]["seq"] < applied[i]["seq"]
                     for i in range(len(sequence)))
             and all(applied[i]["seq"] < matched[i + 1]["seq"]
                     for i in range(len(sequence) - 1)))
    last_fault = applied[-1]["seq"] if exact else None
    post_checks = [event for event in trace if event["event"] == "TARGET_CHECK"
                   and event.get("siteId") == TARGET
                   and last_fault is not None and event["seq"] > last_fault]
    target_throws = [event for event in trace if event["event"] == "TARGET_THROW"
                     and event.get("siteId") == THROW
                     and event.get("exception") ==
                     "java.lang.AssertionError"
                     and last_fault is not None and event["seq"] > last_fault]
    valid = exact and bool(post_checks)
    now_coverage = {category: covered(directory, category) for category in COVERAGE}
    gain = {category: len(values - set(state["coverage"][category])) if valid else 0
            for category, values in now_coverage.items()}
    current_families = {family(event) for event in trace
                        if event["event"] == "FAULT_POINT_OBSERVED"}
    new_families = sorted(current_families - set(state["io_families"])) if valid else []
    return {"id": sequence_id(sequence), "sequence": sequence,
            "run": str(directory), "junit_exit": manifest["returncode"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "requested_faults": len(sequence), "matched_faults": len(matched),
            "applied_faults": len(applied), "exact_order_applied": exact,
            "target_after_fault": bool(post_checks),
            "target_checks_after_fault": len(post_checks),
            "target_exception_after_fault": len(target_throws),
            "valid_for_feedback": valid, "coverage_gain": gain,
            "new_io_families": new_families,
            "last_applied_seq": last_fault,
            "bug_mark": "candidate_needs_replay_source_review" if valid and target_throws else "none"}


def enqueue(state: dict, sequence: list[dict], priority: int = 0) -> None:
    identity = sequence_id(sequence)
    if identity in state["seen_sequences"]:
        return
    state["seen_sequences"].append(identity)
    state["queue"].append({"id": identity, "sequence": sequence,
                           "priority": priority, "created": time.time()})


def initial_queue(state: dict) -> None:
    trace = rows(HEALTHY)
    targets = [event["seq"] for event in trace
               if event["event"] == "TARGET_CHECK" and event.get("siteId") == TARGET]
    if not targets:
        raise RuntimeError("original JUnit did not reach HDFS-19 target")
    for event in trace:
        if event["event"] == "FAULT_POINT_OBSERVED" and event["seq"] < max(targets):
            for kind in KINDS:
                enqueue(state, [point(event, kind)])


def extend(state: dict, trial: dict) -> None:
    sequence = trial["sequence"]
    if not trial["valid_for_feedback"] or len(sequence) >= state["budget"]["max_faults"]:
        return
    trace = rows(Path(trial["run"]))
    later_checks = [event["seq"] for event in trace
                    if event["event"] == "TARGET_CHECK" and event.get("siteId") == TARGET
                    and event["seq"] > trial["last_applied_seq"]]
    if not later_checks:
        return
    for event in trace:
        if (event["event"] == "FAULT_POINT_OBSERVED"
                and trial["last_applied_seq"] < event["seq"] < max(later_checks)):
            for kind in KINDS:
                selected = point(event, kind)
                if selected in sequence:
                    continue
                priority = (10 * trial["coverage_gain"]["methods"]
                            + 5 * trial["coverage_gain"]["branch_counts"]
                            + 50 * bool(trial["new_io_families"])
                            + 3 * len(sequence))
                enqueue(state, sequence + [selected], priority)


def admit(state: dict, trial: dict) -> None:
    if not trial["valid_for_feedback"]:
        return
    directory = Path(trial["run"])
    for category in COVERAGE:
        state["coverage"][category] = sorted(
            set(state["coverage"][category]) | covered(directory, category))
    state["io_families"] = sorted(set(state["io_families"]) | set(
        family(event) for event in rows(directory)
        if event["event"] == "FAULT_POINT_OBSERVED"))
    extend(state, trial)


def choose(state: dict) -> int:
    completed = state["completed"]
    last_counts = Counter(family(trial["sequence"][-1]) for trial in completed)
    root_counts = Counter(family(trial["sequence"][0]) for trial in completed)
    single_count = sum(len(trial["sequence"]) == 1 for trial in completed)
    prefer_single = single_count <= len(completed) - single_count
    eligible = [(index, item) for index, item in enumerate(state["queue"])
                if (len(item["sequence"]) == 1) == prefer_single]
    if not eligible:
        eligible = list(enumerate(state["queue"]))
    return min(eligible, key=lambda indexed: (
        last_counts[family(indexed[1]["sequence"][-1])],
        root_counts[family(indexed[1]["sequence"][0])],
        -indexed[1]["priority"], indexed[1]["created"]))[0]


def write_result(state: dict) -> None:
    completed = state["completed"]
    strict = [trial for trial in completed if trial["exact_order_applied"]]
    valid = [trial for trial in completed if trial["valid_for_feedback"]]
    candidates = [trial for trial in valid if trial["target_exception_after_fault"]]
    old = json.loads(RESULT.read_text())
    elapsed = state["healthy_seconds"] + sum(t["elapsed_seconds"] for t in completed)
    status = ("running" if len(completed) < state["budget"]["max_trials"] and state["queue"]
              else "pending_source_review" if valid else "no_valid_target_trial")
    old.update(status=status, target_reached=True, fault_trials=len(completed),
               strict_injections=len(strict), fully_applied_trials=len(strict),
               target_after_fault=len(valid),
               target_exception_after_fault_trials=len(candidates),
               coverage_gain={category: len(state["coverage"][category])
                              - len(state["healthy_coverage"][category])
                              for category in COVERAGE},
               elapsed_seconds=round(elapsed, 3),
               bug_mark="candidate_needs_replay_source_review" if candidates else "none",
               cluster_test="org.apache.hadoop.hdfs.TestDFSFinalize#"
               "testFinalize",
               methodology="coverage_io_case_local_asm_jacoco_original_junit",
               independent_campaign={"budget": state["budget"],
                                     "checkpoint": str(STATE),
                                     "healthy": str(HEALTHY),
                                     "completed_sequence_ids": [t["id"] for t in completed],
                                     "strict_target_trials": len(valid),
                                     "target_exception_candidates": len(candidates)})
    atomic_json(RESULT, old)
    with LEDGER.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(("trial", "sequence_id", "faults", "seconds", "junit_exit",
                         "exact", "target_after_fault", "target_exception", "methods_gain",
                         "branches_gain", "new_io_families", "run"))
        for index, trial in enumerate(completed, 1):
            writer.writerow((index, trial["id"], len(trial["sequence"]),
                             trial["elapsed_seconds"], trial["junit_exit"],
                             trial["exact_order_applied"], trial["target_after_fault"],
                             trial["target_exception_after_fault"],
                             trial["coverage_gain"]["methods"],
                             trial["coverage_gain"]["branch_counts"],
                             len(trial["new_io_families"]), trial["run"]))


def initialize() -> dict:
    if not (HEALTHY / "manifest.json").is_file():
        raise RuntimeError("independent healthy JUnit trace missing")
    healthy = json.loads((HEALTHY / "manifest.json").read_text())
    if healthy["returncode"] != 0:
        raise RuntimeError("original healthy JUnit failed")
    baseline = {category: sorted(covered(HEALTHY, category)) for category in COVERAGE}
    state = {"schema": 1, "budget": {"max_trials": 80, "max_faults": 8},
             "healthy_seconds": healthy["elapsed_seconds"],
             "healthy_coverage": baseline, "coverage": {k: list(v) for k, v in baseline.items()},
             "io_families": sorted({family(event) for event in rows(HEALTHY)
                                    if event["event"] == "FAULT_POINT_OBSERVED"}),
             "queue": [], "seen_sequences": [], "completed": [], "active": None,
             "started_at": time.time()}
    initial_queue(state)
    smoke_event = next(event for event in rows(SMOKE)
                       if event["event"] == "FAULT_APPLIED")
    sequence = [point(smoke_event, smoke_event["faultType"])]
    trial = evaluate(SMOKE, sequence, state)
    if not trial["valid_for_feedback"]:
        raise RuntimeError("independent smoke is not a valid target trial")
    state["queue"] = [item for item in state["queue"] if item["id"] != trial["id"]]
    state["completed"].append(trial)
    admit(state, trial)
    atomic_json(STATE, state)
    write_result(state)
    return state


def run_one(state: dict, item: dict) -> None:
    number = len(state["completed"]) + 1
    run = HERE / "runs" / ("trial-%03d" % number)
    run.mkdir(parents=True, exist_ok=True)
    plan = run / "fault-plan.tsv"
    plan.write_text("".join("\t".join(str(fault[key]) for key in
                                        ("marker", "siteId", "sourceKey", "hitOrdinal", "faultType"))
                            + "\n" for fault in item["sequence"]))
    command = [sys.executable, str(RUNNER), "--instrument", "--plan", str(plan),
               "--output", str(run), "--timeout", "300"]
    with (run / "driver.log").open("w") as log:
        subprocess.run(command, cwd=HERE, stdout=log, stderr=subprocess.STDOUT)
    if not (run / "manifest.json").is_file():
        raise RuntimeError("trial missing manifest; active sequence remains for retry")
    trial = evaluate(run, item["sequence"], state)
    state["completed"].append(trial)
    admit(state, trial)
    state["active"] = None
    atomic_json(STATE, state)
    write_result(state)
    print("HDFS-19", number, "exact", trial["exact_order_applied"],
          "target", trial["target_after_fault"], "candidate",
          trial["target_exception_after_fault"], flush=True)


def main() -> None:
    with LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
        for trial in state["completed"]:
            extend(state, trial)
        atomic_json(STATE, state)
        while len(state["completed"]) < state["budget"]["max_trials"] and (
                state["queue"] or state["active"]):
            if state["active"] is None:
                state["active"] = state["queue"].pop(choose(state))
                atomic_json(STATE, state)
            run_one(state, state["active"])
        # Extend only when the recent valid runs still add genuinely new
        # production method/branch coverage or a stable I/O family.
        if len(state["completed"]) == 80:
            recent = [trial for trial in state["completed"][-8:]
                      if trial["valid_for_feedback"]]
            novelty = any(trial["coverage_gain"]["methods"]
                          or trial["coverage_gain"]["branch_counts"]
                          or trial["new_io_families"] for trial in recent)
            if novelty:
                state["budget"] = {"max_trials": 128, "max_faults": 10}
                for trial in state["completed"]:
                    extend(state, trial)
                atomic_json(STATE, state)
                write_result(state)
                while len(state["completed"]) < 128 and (state["queue"] or state["active"]):
                    if state["active"] is None:
                        state["active"] = state["queue"].pop(choose(state))
                        atomic_json(STATE, state)
                    run_one(state, state["active"])
        write_result(state)


if __name__ == "__main__":
    main()
