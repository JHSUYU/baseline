#!/usr/bin/env python3
"""Resumable actor-aware CrashFuzz-style HDFS-16 embedded JUnit campaign."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from identity_gate import HERE, KEYS, atomic, evaluate, rows, selector

CASE = HERE
LOCK = Path("/users/ZhenyuLi/baseline/crashfuzz/jvm-start.lock")
EXCEPTIONS = ("IOException", "EOFException", "SocketTimeoutException")


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def java_count() -> int:
    result = subprocess.check_output(["jps", "-l"], text=True)
    return sum(bool(line.strip()) and not line.endswith("sun.tools.jps.Jps")
               for line in result.splitlines())


def disk_gib() -> float:
    stat = os.statvfs(CASE)
    return stat.f_bavail * stat.f_frsize / 1024 ** 3


def coverage(run: Path) -> set[str]:
    path = run / "coverage.tsv"
    return set(path.read_text().splitlines()) if path.is_file() else set()


def family(row: dict) -> str:
    return "|".join(str(row.get(key)) for key in KEYS[:5])


def plan_text(steps: list[dict]) -> str:
    return "".join("\t".join(str(step[key]) for key in (*KEYS, "exception")) + "\n"
                   for step in steps)


def sequence_id(steps: list[dict]) -> str:
    return hashlib.sha256(plan_text(steps).encode()).hexdigest()[:20]


def point(row: dict, exception: str) -> dict:
    return {**{key: row[key] for key in KEYS}, "exception": exception}


def base_priority(step: dict) -> int:
    api = step["api"]
    if "updatePipeline" in api:
        return 200
    if "registerDatanode" in api and step["poolClass"] == "BP0":
        return 190
    if "registerDatanode" in api:
        return 165
    if "create" in api or "addBlock" in api or "fsync" in api:
        return 155
    if step["marker"] == "FILE_FLUSH":
        return 125 - min(int(step["ordinal"]), 20)
    if step["actorKey"].startswith("episode="):
        return 115
    return 100


def enqueue(state: dict, steps: list[dict], reason: str, bonus: int = 0) -> None:
    identifier = sequence_id(steps)
    if identifier in state["seen"]:
        return
    state["seen"].append(identifier)
    state["queue"].append({"id": identifier, "sequence": steps,
                           "reason": reason, "priority": base_priority(steps[-1]) + bonus,
                           "queued_at": time.time()})


def initialize() -> dict:
    healthy = json.loads((CASE / "healthy-receipt.json").read_text())
    if not healthy.get("pass"):
        raise RuntimeError("two healthy actor calibrations required")
    a, b = CASE / "healthy/a", CASE / "healthy/b"
    baseline_coverage = coverage(a) | coverage(b)
    baseline_families = {family(row) for run in (a, b) for row in rows(run)
                         if row.get("event") == "IO_OBSERVED"}
    state = {"schema": "hdfs16-actor-v3-campaign-1", "status": "running",
             "case_id": "HDFS-16", "original_junit": healthy["test"],
             "healthy_receipt_sha256": hashlib.sha256(
                 (CASE / "healthy-receipt.json").read_bytes()).hexdigest(),
             "controller_sha256": file_sha(CASE / "campaign.py"),
             "gate_sha256": file_sha(CASE / "identity_gate.py"),
             "queue": [], "seen": [], "completed": {}, "in_flight": None,
             "attempted": 0, "effective": 0, "max_effective": 80,
             "max_faults": 8, "max_attempts": 400,
             "recent_effective_gain": [], "elapsed_seconds": 0.0,
             "coverage_ids": sorted(baseline_coverage),
             "io_families": sorted(baseline_families)}
    for selected in healthy["stable_selectors"]:
        for exception in EXCEPTIONS:
            enqueue(state, [{**selected, "exception": exception}],
                    "two-healthy-seed-stable-io")
    assert state["queue"]
    return state


def choose(state: dict) -> dict:
    if state.get("in_flight"):
        return next(item for item in state["queue"]
                    if item["id"] == state["in_flight"])
    performance = defaultdict(lambda: [0, 0])
    for entry in state["completed"].values():
        if entry["exact_order_applied"]:
            key = entry["last_family"]
            performance[key][0] += 1
            performance[key][1] += int(entry["valid_for_feedback"])
    now = time.time()
    def score(item: dict) -> tuple:
        key = family(item["sequence"][-1])
        tried, retained = performance[key]
        retention = round(50 * (retained / tried - 0.5)) if tried >= 3 else 0
        age = min(100, int((now - item["queued_at"]) / 30))
        depth = len(item["sequence"])
        return (item["priority"] + retention + age + min(depth, 4) * 4,
                -item["queued_at"])
    return max(state["queue"], key=score)


def eligible(row: dict, healthy: dict, selected_uuid: str | None) -> bool:
    if row.get("event") != "IO_OBSERVED":
        return False
    if row.get("peerClass") not in ("NN0", "LOCAL_NN0"):
        return False
    actor = row.get("actorKey")
    if actor == healthy["stable_actor"]:
        return bool(selected_uuid and row.get("rawDatanodeUuid") in
                    (None, "", selected_uuid))
    return actor in ("CLIENT", "NN0")


def mutate(state: dict, sequence: list[dict], trace: list[dict], verdict: dict,
           novelty: int) -> None:
    if not verdict["valid_for_feedback"] or len(sequence) >= state["max_faults"]:
        return
    last_applied = max(row["seq"] for row in trace
                       if row.get("event") == "FAULT_APPLIED")
    target_seqs = [row["seq"] for row in trace
                   if row.get("event") == "TARGET_GUARD" and
                   row.get("blockId") == json.loads(
                       (CASE / "healthy-receipt.json").read_text())["target_block_id"]
                   and row["seq"] > last_applied]
    if not target_seqs:
        return
    upper = max(target_seqs)
    healthy = json.loads((CASE / "healthy-receipt.json").read_text())
    selected_uuid = verdict["selected_datanode_uuid"]
    old = {tuple(step[key] for key in KEYS) for step in sequence}
    observed = [row for row in trace if last_applied < row["seq"] < upper and
                eligible(row, healthy, selected_uuid) and selector(row) not in old]
    observed.sort(key=lambda row: (-base_priority(row), row["seq"]))
    chosen, family_count = [], defaultdict(int)
    for row in observed:
        key = family(row)
        if family_count[key] >= 2:
            continue
        family_count[key] += 1
        chosen.append(row)
        if len(chosen) >= 8:
            break
    for row in chosen:
        for exception in EXCEPTIONS:
            enqueue(state, sequence + [point(row, exception)],
                    "postfault-observed-io-before-same-block-target",
                    bonus=min(novelty, 20) * 5 + min(len(sequence), 6) * 8)


def run_one(state: dict, item: dict) -> dict:
    number = state["attempted"] + 1
    run = CASE / "campaign" / f"trial-{number:04d}"
    plan = CASE / "campaign/plans" / (item["id"] + ".tsv")
    plan.parent.mkdir(parents=True, exist_ok=True)
    text = plan_text(item["sequence"])
    if plan.exists() and plan.read_text() != text:
        raise RuntimeError("immutable plan changed: " + item["id"])
    if not plan.exists():
        plan.write_text(text)
    run.mkdir(parents=True, exist_ok=True)
    manifest_path = run / "manifest.json"
    if not manifest_path.exists():
        with LOCK.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            count, free = java_count(), disk_gib()
            gate = {"at_utc": utc(), "java_before_launch": count,
                    "free_disk_gib": round(free, 3), "java_limit_before_launch": 4,
                    "minimum_free_disk_gib": 10.0, "shared_lock": str(LOCK)}
            atomic(run / "launch-gate.json", gate)
            if count > 4:
                raise RuntimeError("WAIT_JAVA_SLOT")
            if free < 10.0:
                raise RuntimeError("LOW_DISK")
            command = [sys.executable, str(CASE / "system-test/run_original.py"),
                       "--name", f"campaign/trial-{number:04d}", "--probe",
                       "--coverage", "--plan", str(plan),
                       "--timeout-seconds", "90"]
            with (run / "runner.log").open("w") as log:
                process = subprocess.run(command, stdout=log,
                                         stderr=subprocess.STDOUT)
            gate["finished_at_utc"] = utc()
            gate["runner_exit"] = process.returncode
            atomic(run / "launch-gate.json", gate)
            if not manifest_path.exists():
                raise RuntimeError("original JUnit left no manifest")
    manifest = json.loads(manifest_path.read_text())
    if (run / "jacoco.exec").is_file() and not (run / "coverage.tsv").exists():
        command = [sys.executable, str(CASE / "system-test/run_coverage.py"),
                   "--exec", str(run / "jacoco.exec"),
                   "--output", str(run / "coverage.tsv")]
        # Coverage is a separate Java process, so use the same launch lock
        # and total-process limit as the original JUnit child.
        while True:
            with LOCK.open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                if java_count() <= 4:
                    with (run / "coverage-runner.log").open("w") as log:
                        subprocess.run(command, stdout=log,
                                       stderr=subprocess.STDOUT, check=True)
                    break
            time.sleep(10)
    return {"run": run, "plan": plan, "manifest": manifest}


def append_ledger(state: dict, row: dict) -> None:
    path = CASE / "campaign/trial-ledger.jsonl"
    with path.open("a") as stream:
        stream.write(json.dumps({"attempt": state["attempted"], **row},
                                sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def campaign(max_new_completions: int | None = None) -> dict:
    campaign_dir = CASE / "campaign"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    state_path = campaign_dir / "checkpoint.json"
    with (campaign_dir / "controller.lock").open("w") as exclusive:
        fcntl.flock(exclusive, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(state_path.read_text()) if state_path.exists() else initialize()
        for field, filename in (("controller_sha256", "campaign.py"),
                                ("gate_sha256", "identity_gate.py")):
            if field in state and state[field] != file_sha(CASE / filename):
                raise RuntimeError("code differs from checkpoint: " + field)
        if state["status"] == "paused_target_exception_candidate":
            raise RuntimeError("candidate needs source review before continuing")
        state["status"] = "running"
        atomic(state_path, state)
        starting_attempts = state["attempted"]
        while state["queue"] and state["attempted"] < state["max_attempts"]:
            if (max_new_completions is not None and
                    state["attempted"] - starting_attempts >= max_new_completions):
                state["status"] = "pilot_boundary"
                break
            if state["effective"] >= state["max_effective"]:
                if state["max_effective"] == 80 and any(
                        state["recent_effective_gain"][-8:]):
                    state["max_effective"], state["max_faults"] = 128, 10
                    atomic(state_path, state)
                else:
                    break
            item = choose(state)
            state["in_flight"] = item["id"]
            atomic(state_path, state)
            try:
                artifact = run_one(state, item)
            except RuntimeError as error:
                if str(error) == "WAIT_JAVA_SLOT":
                    time.sleep(15)
                    continue
                if str(error) == "LOW_DISK":
                    state["status"] = "paused_low_disk"
                    atomic(state_path, state)
                    break
                state["status"] = "paused_controller_error"
                state["last_error"] = str(error)
                atomic(state_path, state)
                raise
            run, plan, manifest = (artifact[k] for k in ("run", "plan", "manifest"))
            verdict = evaluate(run, plan, CASE / "healthy-receipt.json")
            trace = rows(run)
            identifiers = coverage(run)
            new_coverage = identifiers - set(state["coverage_ids"])
            families = {family(row) for row in trace
                        if row.get("event") == "IO_OBSERVED"}
            new_families = families - set(state["io_families"])
            if not verdict["valid_for_feedback"]:
                new_coverage.clear()
                new_families.clear()
            verdict.update({"sequence_id": item["id"], "sequence": item["sequence"],
                            "selection_reason": item["reason"],
                            "new_coverage_ids": sorted(new_coverage),
                            "new_io_families": sorted(new_families),
                            "completed_at_utc": utc()})
            atomic(run / "v3-result.json", verdict)
            if verdict["valid_for_feedback"]:
                state["effective"] += 1
                state["recent_effective_gain"].append(
                    bool(new_coverage or new_families))
                state["coverage_ids"] = sorted(set(state["coverage_ids"]) |
                                               new_coverage)
                state["io_families"] = sorted(set(state["io_families"]) |
                                              new_families)
                mutate(state, item["sequence"], trace, verdict,
                       len(new_coverage) + len(new_families))
            state["attempted"] += 1
            state["elapsed_seconds"] += verdict["elapsed_seconds"]
            state["completed"][item["id"]] = {
                "attempt": state["attempted"], "exact_order_applied":
                verdict["exact_order_applied"], "valid_for_feedback":
                verdict["valid_for_feedback"], "last_family":
                family(item["sequence"][-1]), "new_coverage": len(new_coverage),
                "new_io_families": len(new_families), "trial": str(run)}
            state["queue"] = [candidate for candidate in state["queue"]
                              if candidate["id"] != item["id"]]
            state["in_flight"] = None
            atomic(state_path, state)
            append_ledger(state, {"sequence_id": item["id"],
                                  "elapsed_seconds": verdict["elapsed_seconds"],
                                  "junit_exit": verdict["junit_exit"],
                                  "exact_order_applied": verdict["exact_order_applied"],
                                  "valid_for_feedback": verdict["valid_for_feedback"],
                                  "workload_failure": verdict["workload_failure"],
                                  "injected_exception_in_junit_log":
                                  verdict["injected_exception_in_junit_log"],
                                  "environment_failure_in_junit_log":
                                  verdict["environment_failure_in_junit_log"],
                                  "postfault_target_count": verdict["postfault_target_count"],
                                  "target_exception_candidate":
                                  verdict["target_exception_candidate"],
                                  "new_coverage_count": len(new_coverage),
                                  "new_io_family_count": len(new_families)})
            scratch = CASE / "temp" / f"campaign-trial-{state['attempted']:04d}"
            if scratch.exists():
                shutil.rmtree(scratch)
            print(json.dumps({"at_utc": utc(), "attempted": state["attempted"],
                              "effective": state["effective"],
                              "verdict": {k: verdict[k] for k in
                                          ("exact_order_applied", "valid_for_feedback",
                                           "postfault_target_count",
                                           "target_exception_candidate",
                                           "workload_failure",
                                           "elapsed_seconds")}}, sort_keys=True), flush=True)
            if verdict["target_exception_candidate"]:
                state["status"] = "paused_target_exception_candidate"
                atomic(state_path, state)
                break
            if verdict["environment_failure_in_junit_log"] or (
                    verdict["workload_failure"] and not
                    verdict["injected_exception_in_junit_log"]):
                state["status"] = "paused_unclassified_workload_or_host_failure"
                atomic(state_path, state)
                break
            if verdict["elapsed_seconds"] > 90 or manifest["exit"] == 124:
                state["status"] = "paused_slow_or_timeout_trial"
                atomic(state_path, state)
                break
            if (campaign_dir / "pause-request.txt").exists():
                state["status"] = "paused_external_request"
                atomic(state_path, state)
                break
        else:
            state["status"] = ("queue_exhausted" if not state["queue"] else
                               "attempt_cap_reached")
        if state["status"] == "running" and state["effective"] >= state["max_effective"]:
            state["status"] = "effective_budget_reached"
        atomic(state_path, state)
        return {key: state[key] for key in
                ("status", "attempted", "effective", "max_effective",
                 "max_faults", "elapsed_seconds")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new-completions", type=int)
    args = parser.parse_args()
    print(json.dumps(campaign(args.max_new_completions), sort_keys=True))
