#!/usr/bin/env python3
"""Resumable actor-aware I/O/coverage fuzzing of the unchanged TestPread JUnit.

The earlier HDFS-01 campaign remains historical evidence. This checkpoint has
its own healthy seeds, bytecode SHA, fault selectors and effective denominator.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
CAMPAIGN = HERE / "campaign-v3"
STATE = CAMPAIGN / "checkpoint.json"
TARGET = "DFSInputStream.fetchBlockAt#L517-B5"
TARGET_THROW = "DFSInputStream.fetchBlockAt#L518"
FILE = "/preadtest.dat"
KINDS = ("IOException", "SocketTimeoutException", "EOFException")
COVERAGE = ("methods", "branch_counts", "probes", "lines")
SELECTOR = ("marker", "siteId", "actorKey", "resourceKey", "hitOrdinal")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("w") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def covered(directory: Path, category: str) -> set[str]:
    path = directory / f"covered_{category}.txt"
    return set(path.read_text().splitlines()) if path.is_file() else set()


def family(row: dict) -> str:
    return "|".join(str(row[key]) for key in
                    ("marker", "siteId", "actorKey", "resourceKey"))


def selectable(row: dict) -> bool:
    if row.get("event") != "FAULT_POINT_OBSERVED" or not row.get("identityBound"):
        return False
    if row.get("marker") == "FAULT:HDFS_DATA_TRANSFER:READ":
        return row.get("resourceKey", "").startswith(FILE + "@") and bool(row.get("actorUuid"))
    return row.get("sourceKey") == "main" or row.get("sourceKey", "").startswith(
        "DataStreamer for file " + FILE)


def selector(row: dict, kind: str) -> dict:
    return {**{key: row[key] for key in SELECTOR}, "faultType": kind}


def plan_id(plan: list[dict]) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()[:20]


def plan_text(plan: list[dict]) -> str:
    return "".join("\t".join((point["marker"], point["siteId"],
                                point["actorKey"], point["resourceKey"],
                                str(point["hitOrdinal"]), "pending",
                                point["faultType"])) + "\n" for point in plan)


def target_checks(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("event") == "TARGET_CHECK"
            and row.get("siteId") == TARGET and row.get("file") == FILE]


def read_binding_verified(rows: list[dict], applied: list[dict]) -> bool:
    """Independently join a faulted read to an earlier raw NN block location."""
    locations = [row for row in rows if row.get("event") == "BLOCK_LOCATION"]
    for event in applied:
        if event.get("marker") != "FAULT:HDFS_DATA_TRANSFER:READ":
            continue
        matches = [row for row in locations if row["seq"] < event["seq"]
                   and row.get("file") == FILE
                   and row.get("blockId") == event.get("blockId")
                   and row.get("actorUuid") == event.get("actorUuid")]
        if not matches:
            return False
        latest = max(matches, key=lambda row: row["seq"])
        if (event.get("actorKey") != "replica:" + str(latest["replicaIndex"])
                or event.get("resourceKey") != FILE + "@" + str(latest["startOffset"])):
            return False
    return True


def points_before_target(rows: list[dict], after_seq: int = -1) -> list[dict]:
    checks = target_checks(rows)
    if not checks:
        return []
    stop = max(row["seq"] for row in checks)
    return [row for row in rows if selectable(row) and after_seq < row["seq"] < stop]


def point_score(row: dict) -> int:
    marker = row["marker"]
    if marker == "FAULT:HDFS_DATA_TRANSFER:READ":
        return 80
    if marker == "FAULT:HDFS_RPC:GET_BLOCK_LOCATIONS":
        return 60
    if row.get("sourceKey", "").startswith("DataStreamer for file"):
        return 45
    return 30


def add_plan(state: dict, plan: list[dict], parent: dict | None = None) -> None:
    identifier = plan_id(plan)
    if identifier in state["seen"]:
        return
    state["seen"].append(identifier)
    state["queue"].append({"id": identifier, "plan": plan,
                           "parent": parent["id"] if parent else None,
                           "parent_gain": parent["feedback_score"] if parent else 0,
                           "queued_at_attempt": len(state["completed"])})


def initialize() -> dict:
    calibration = HERE / "healthy-v3-calibration.json"
    if not calibration.is_file():
        raise RuntimeError("two actor-aware original JUnit healthy seeds are required")
    receipt = json.loads(calibration.read_text())
    overlay_sha = sha256(HERE / "build/receipt.json")
    if overlay_sha != receipt["overlay_receipt_sha256"]:
        raise RuntimeError("overlay SHA changed after healthy calibration")
    if STATE.is_file():
        state = json.loads(STATE.read_text())
        if state["calibration_sha256"] != sha256(calibration):
            raise RuntimeError("checkpoint healthy calibration SHA changed")
        return state
    seeds = [HERE / name for name in ("healthy-v3-a", "healthy-v3-b")]
    histories = [trace(seed / "runtime_trace.jsonl") for seed in seeds]
    common = set((row["marker"], row["siteId"], row["actorKey"],
                  row["resourceKey"], row["hitOrdinal"])
                 for row in points_before_target(histories[0]))
    common &= set((row["marker"], row["siteId"], row["actorKey"],
                   row["resourceKey"], row["hitOrdinal"])
                  for row in points_before_target(histories[1]))
    seed_rows = [row for row in points_before_target(histories[0])
                 if tuple(row[key] for key in SELECTOR) in common]
    if not seed_rows or not any(row["marker"] == "FAULT:HDFS_DATA_TRANSFER:READ"
                                for row in seed_rows):
        raise RuntimeError("healthy actor-bound I/O seed is empty")
    coverage_union = {category: sorted(set().union(
        *(covered(seed, category) for seed in seeds))) for category in COVERAGE}
    families = sorted({family(row) for history in histories for row in history
                       if selectable(row)})
    state = {"schema_version": 3, "case_id": "HDFS-01",
             "original_junit": "org.apache.hadoop.hdfs.TestPread#testPreadDFS",
             "calibration_sha256": sha256(calibration),
             "overlay_receipt_sha256": overlay_sha,
             "started_at_utc": utc(), "budget": {"effective": 80,
                                                "max_faults": 8, "max_attempts": 320},
             "extended": False, "queue": [], "seen": [], "current": None,
             "completed": [], "coverage": coverage_union,
             "io_families": families, "stop_reason": None}
    for row in sorted(seed_rows, key=lambda item: (-point_score(item), item["seq"])):
        for kind in KINDS:
            add_plan(state, [selector(row, kind)])
    atomic_json(STATE, state)
    return state


def choose(state: dict) -> dict:
    queue = state["queue"]
    attempt = len(state["completed"])
    # A fault that repeatedly removes the selected check is poor feedback for
    # this target. Keep it in the queue, but let new and target-retaining I/O
    # families run first. One root in sixteen still explores every family.
    attempts_by_marker = Counter(row["plan"][-1]["marker"]
                                 for row in state["completed"])
    effective_by_marker = Counter(row["plan"][-1]["marker"]
                                  for row in state["completed"] if row["effective"])
    target_losing = {marker for marker, count in attempts_by_marker.items()
                     if count >= 5 and effective_by_marker[marker] == 0}
    # Every fourth attempt exercises an untested healthy root; the other
    # rounds use coverage/I/O reward, actor novelty, depth and waiting time.
    roots = [(i, item) for i, item in enumerate(queue) if len(item["plan"]) == 1]
    preferred = [(i, item) for i, item in roots
                 if item["plan"][-1]["marker"] not in target_losing]
    # When every unused root has repeatedly removed the target, keep a
    # one-in-sixteen exploration slot instead of spending every fourth run.
    if roots and attempt % 4 == 0 and (preferred or attempt % 16 == 0):
        candidates = roots if attempt % 16 == 0 else preferred
        index = min(candidates, key=lambda pair: pair[1]["queued_at_attempt"])[0]
    else:
        def score(item: dict) -> tuple[int, int, int]:
            point = item["plan"][-1]
            return (point_score(point) + min(item["parent_gain"], 80)
                    + min(len(item["plan"]), 6) * 4
                    + min(attempt - item["queued_at_attempt"], 30)
                    - (100 if point["marker"] in target_losing else 0),
                    -item["queued_at_attempt"], -len(item["plan"]))
        index = max(range(len(queue)), key=lambda i: score(queue[i]))
    return queue.pop(index)


def assess(state: dict, current: dict, directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    rows = trace(directory / "runtime_trace.jsonl")
    applied = [row for row in rows if row.get("event") == "FAULT_APPLIED"]
    plan = current["plan"]
    strict = len(applied) == len(plan) and all(
        row.get("faultIndex") == index and row.get("faultType") == point["faultType"]
        and all(row.get(key) == point[key] for key in SELECTOR)
        and row.get("identityBound") is True
        for index, (row, point) in enumerate(zip(applied, plan)))
    binding_verified = read_binding_verified(rows, applied)
    strict = strict and binding_verified
    after = applied[-1]["seq"] if strict else 1 << 60
    checks = [row for row in target_checks(rows) if row["seq"] > after]
    effective = strict and bool(checks)
    throws = [row for row in rows if row.get("event") == "TARGET_THROW"
              and row.get("siteId") == TARGET_THROW
              and row.get("exception") == "java.io.EOFException"
              and row.get("file") == FILE and row["seq"] > after]
    trial_coverage = {category: covered(directory, category) for category in COVERAGE}
    gain = {category: len(values - set(state["coverage"][category])) if effective else 0
            for category, values in trial_coverage.items()}
    io = {family(row) for row in rows if selectable(row)}
    io_gain = len(io - set(state["io_families"])) if effective else 0
    feedback_score = min(80, gain["methods"] * 8 + gain["branch_counts"] * 4
                         + io_gain * 3)
    return {"id": current["id"], "plan": plan, "attempt": len(state["completed"]) + 1,
            "manifest": str(directory / "manifest.json"),
            "trace": str(directory / "runtime_trace.jsonl"),
            "elapsed_seconds": manifest["elapsed_seconds"],
            "junit_exit": manifest["returncode"], "strict": strict,
            "raw_read_binding_verified": binding_verified,
            "applied_faults": len(applied), "effective": effective,
            "post_fault_target_checks": len(checks),
            "exact_target_throws": len(throws) if effective else 0,
            "coverage_gain": gain, "new_io_families": io_gain,
            "feedback_score": feedback_score,
            "candidate_needs_replay": effective and bool(throws),
            "coverage_ids": {key: sorted(value) for key, value in trial_coverage.items()}
            if effective else {}, "io_family_ids": sorted(io) if effective else []}


def mutate(state: dict, trial: dict) -> None:
    plan = trial["plan"]
    if len(plan) >= state["budget"]["max_faults"]:
        return
    rows = trace(Path(trial["trace"]))
    applied = [row for row in rows if row.get("event") == "FAULT_APPLIED"]
    candidates = points_before_target(rows, applied[-1]["seq"])
    candidates.sort(key=lambda item: (-point_score(item), item["seq"]))
    # Bound child fanout while retaining different observed actor/resource sites.
    emitted = set()
    for row in candidates:
        key = (row["marker"], row["siteId"], row["actorKey"], row["resourceKey"])
        if key in emitted:
            continue
        emitted.add(key)
        for kind in KINDS:
            add_plan(state, plan + [selector(row, kind)], trial)
        if len(emitted) >= 24:
            break


def finalize_trial(state: dict, current: dict, directory: Path) -> None:
    trial = assess(state, current, directory)
    state["completed"].append(trial)
    if trial["effective"]:
        for key in COVERAGE:
            state["coverage"][key] = sorted(set(state["coverage"][key]) |
                                            set(trial["coverage_ids"][key]))
        state["io_families"] = sorted(set(state["io_families"]) |
                                      set(trial["io_family_ids"]))
        mutate(state, trial)
    state["current"] = None
    atomic_json(STATE, state)
    print(json.dumps({"attempt": trial["attempt"], "effective_total":
                      sum(row["effective"] for row in state["completed"]),
                      "strict": trial["strict"], "posttarget": trial["effective"],
                      "target_throws": trial["exact_target_throws"],
                      "branch_gain": trial["coverage_gain"]["branch_counts"],
                      "io_gain": trial["new_io_families"]}), flush=True)


def run(max_new_attempts: int | None) -> None:
    state = initialize()
    initially_completed = len(state["completed"])
    while True:
        effective = [row for row in state["completed"] if row["effective"]]
        if len(effective) >= 80 and not state["extended"]:
            recent = effective[-8:]
            novel = any(row["coverage_gain"]["methods"] or
                        row["coverage_gain"]["branch_counts"] or
                        row["new_io_families"] for row in recent)
            if novel:
                state["budget"] = {"effective": 128, "max_faults": 10,
                                   "max_attempts": 512}
                state["extended"] = True
                atomic_json(STATE, state)
            else:
                state["stop_reason"] = "base_budget_complete"
                atomic_json(STATE, state)
                break
        if len(effective) >= state["budget"]["effective"]:
            state["stop_reason"] = "extended_budget_complete"
            atomic_json(STATE, state)
            break
        if len(state["completed"]) >= state["budget"]["max_attempts"]:
            state["stop_reason"] = "attempt_cap_before_effective_budget"
            atomic_json(STATE, state)
            break
        if max_new_attempts is not None and len(state["completed"]) - initially_completed >= max_new_attempts:
            break
        current = state["current"]
        if current is None:
            if not state["queue"]:
                state["stop_reason"] = "queue_exhausted_before_effective_budget"
                atomic_json(STATE, state)
                break
            current = choose(state)
            state["current"] = current
            atomic_json(STATE, state)
        directory = CAMPAIGN / "trials" / ("t%04d" % (len(state["completed"]) + 1))
        directory.mkdir(parents=True, exist_ok=True)
        if not (directory / "manifest.json").is_file():
            plan = directory / "faults.tsv"
            plan.write_text(plan_text(current["plan"]))
            command = [sys.executable, str(HERE / "run_original.py"),
                       "--output", str(directory), "--plan", str(plan),
                       "--timeout", "180"]
            with (directory / "driver.log").open("w") as output:
                runner = subprocess.run(command, stdout=output,
                                        stderr=subprocess.STDOUT, check=False)
            if runner.returncode and not (directory / "manifest.json").is_file():
                raise RuntimeError(f"runner failed before manifest for {current['id']}")
        finalize_trial(state, current, directory)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new-attempts", type=int)
    arguments = parser.parse_args()
    run(arguments.max_new_attempts)
