#!/usr/bin/env python3
"""Isolated, resumable actor-aware I/O and coverage guided HDFS key campaign."""
from __future__ import annotations

import argparse
from collections import defaultdict
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from identity_gate import KEYS, SITES, atomic, evaluate, rows

HERE = Path(__file__).resolve().parent
SASL_FAULT_TYPES = ("IOException", "EOFException", "SocketTimeoutException")
PRODUCER_RESPONSE_FAULT_TYPES = ("IOException", "SocketTimeoutException", "Delay1500ms")
PRODUCER_APPLY_FAULT_TYPES = ("IOException", "Delay1500ms", "Delay3000ms")
COVERAGE = ("probes", "methods", "branch_counts")


def fault_types(row: dict) -> tuple[str, ...]:
    marker = row.get("marker", "")
    if marker == "FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE":
        return PRODUCER_RESPONSE_FAULT_TYPES if row.get("keyRole") == "ROTATED_CURRENT" else ()
    if marker == "FAULT:HDFS_KEY_UPDATE:LOCAL_APPLY":
        return PRODUCER_APPLY_FAULT_TYPES if row.get("keyRole") == "ROTATED_CURRENT" else ()
    return SASL_FAULT_TYPES if marker == "FAULT:HDFS_SASL:READ" else ()


def sequence_id(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:20]


def source_identity(row: dict) -> dict:
    return {key: row[key] for key in KEYS}


def point(row: dict, fault_type: str) -> dict:
    return dict(source_identity(row), faultType=fault_type,
                requiredRawKeyId="*" if row["marker"].startswith("FAULT:HDFS_KEY_UPDATE:") else "-")


def family(row: dict) -> str:
    return "|".join(str(row[k]) for k in ("marker", "siteId", "faultActor", "resource"))


def covered(run: Path, category: str) -> set[str]:
    path = run / ("covered_" + category + ".txt")
    return set(path.read_text().splitlines()) if path.exists() else set()


def add(state: dict, sequence: list[dict], priority: int = 0) -> None:
    identity = sequence_id(sequence)
    if identity in state["seen"]:
        return
    state["seen"].append(identity)
    state["queue"].append(dict(id=identity, sequence=sequence,
                               priority=priority, enqueued=time.time()))


def plan_text(sequence: list[dict]) -> str:
    return "".join("\t".join(str(step[key]) for key in
                             ("marker", "siteId", "faultActor", "resource",
                              "hitOrdinal", "faultType", "requiredRawKeyId")) + "\n"
                   for step in sequence)


def suffix_family(sequence: list[dict]) -> str | None:
    """The last two actor-local I/O sites at this sequence depth."""
    if len(sequence) < 2:
        return None
    last = sequence[-1]
    suffix = "->".join(step["siteId"] + "@" + str(step["actorLocalOrdinal"])
                       for step in sequence[-2:])
    return (last["faultActor"] + "|" + last["resource"]
            + "|depth=" + str(len(sequence)) + "|" + suffix)


def suffix_feedback(output: Path, state: dict) -> dict[str, dict[str, int]]:
    """Recompute from immutable completed receipts so resume never loses feedback."""
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"lost": 0, "valid": 0})
    for identity in state["completed"]:
        result_path = output / "runs" / identity / "v2_result.json"
        plan_path = output / "plans" / (identity + ".tsv")
        if not result_path.exists() or not plan_path.exists():
            continue
        result = json.loads(result_path.read_text())
        if not result.get("exact_order_applied"):
            continue
        selected = [line.split("\t") for line in plan_path.read_text().splitlines() if line]
        if len(selected) < 2:
            continue
        last = selected[-1]
        family = (last[2] + "|" + last[3] + "|depth=" + str(len(selected)) + "|"
                  + "->".join(step[1] + "@" + step[4] for step in selected[-2:]))
        stats[family]["valid" if result.get("valid_for_feedback") else "lost"] += 1
    return dict(stats)


def parent_prefix_key(sequence: list[dict]) -> str | None:
    """Identify all proposed children of the same exact tested fault prefix."""
    if len(sequence) < 3:
        return None
    return hashlib.sha256(plan_text(sequence[:-1]).encode()).hexdigest()


def parent_prefix_feedback(output: Path, state: dict) -> dict[str, dict[str, int]]:
    """Count target-retaining and lost children from immutable trial receipts."""
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"lost": 0, "valid": 0})
    for identity in state["completed"]:
        result_path = output / "runs" / identity / "v2_result.json"
        plan_path = output / "plans" / (identity + ".tsv")
        if not result_path.exists() or not plan_path.exists():
            continue
        lines = plan_path.read_text().splitlines()
        if len(lines) < 3:
            continue
        key = hashlib.sha256(("\n".join(lines[:-1]) + "\n").encode()).hexdigest()
        result = json.loads(result_path.read_text())
        stats[key]["valid" if result.get("valid_for_feedback") else "lost"] += 1
    return dict(stats)


def select_next(output: Path, state: dict) -> tuple[dict, dict]:
    if state.get("in_flight"):
        for item in state["queue"]:
            if item["id"] == state["in_flight"]:
                return item, {"reason": "resume_in_flight", "scheduler_version": 4}
        raise RuntimeError("in-flight sequence is missing from queue")
    stats = suffix_feedback(output, state)
    parents = parent_prefix_feedback(output, state)
    now = time.time()
    candidates = []
    for item in state["queue"]:
        family = suffix_family(item["sequence"])
        prior = stats.get(family, {"lost": 0, "valid": 0})
        # Only a repeatedly observed, *exactly applied* target-losing suffix
        # gets demoted. A single valid target-retaining run cancels demotion.
        suffix_penalty = (min(1200, 250 * prior["lost"])
                          if family and prior["lost"] >= 3 and prior["valid"] == 0 else 0)
        parent_key = parent_prefix_key(item["sequence"])
        parent_prior = parents.get(parent_key, {"lost": 0, "valid": 0})
        parent_penalty = (min(1200, 250 * parent_prior["lost"])
                          if parent_key and parent_prior["lost"] >= 3
                          and parent_prior["valid"] == 0 else 0)
        penalty = suffix_penalty + parent_penalty
        age = min(400, int(max(0, now - item["enqueued"]) / 12))
        candidates.append((item["priority"] - penalty + age, item, family,
                           penalty, age, prior, suffix_penalty, parent_key,
                           parent_prior, parent_penalty))
    # Keep a small, deterministic exploration share for demoted families.
    penalized = [entry for entry in candidates if entry[3] > 0]
    explore = bool(penalized) and state["attempted_trials"] % 12 == 11
    if explore:
        chosen = min(penalized, key=lambda entry: entry[1]["enqueued"])
    else:
        chosen = max(candidates, key=lambda entry: (entry[0], -entry[1]["enqueued"]))
    (score, item, family, penalty, age, prior, suffix_penalty, parent_key,
     parent_prior, parent_penalty) = chosen
    return item, {"scheduler_version": 4,
                  "reason": "penalized_family_exploration" if explore else "highest_adjusted_score",
                  "suffix_family": family, "prior_strict_target_loss": prior["lost"],
                  "prior_valid": prior["valid"], "base_priority": item["priority"],
                  "suffix_target_loss_penalty": suffix_penalty,
                  "parent_prefix_key": parent_key,
                  "parent_prior_target_loss": parent_prior["lost"],
                  "parent_prior_valid": parent_prior["valid"],
                  "parent_target_loss_penalty": parent_penalty,
                  "target_loss_penalty": penalty, "waiting_age_bonus": age,
                  "adjusted_score": score}


def initial_state(case: str, output: Path, healthy: dict) -> dict:
    if case != "HDFS-12":
        raise ValueError("this isolated producer campaign is HDFS-12 only")
    seed = output / "healthy-a"
    trace = rows(seed)
    healthy_io_rows = trace + rows(output / "healthy-b")
    selected = set(map(tuple, healthy["stable_selectors"]))
    state = {
        "schema": "hdfs-key-actor-v2-campaign-1", "case_id": case,
        "status": "running", "queue": [], "seen": [], "completed": {}, "in_flight": None,
        "effective_trials": 0, "attempted_trials": 0, "total_elapsed_seconds": 0.0,
        "coverage": {kind: sorted(covered(seed, kind)) for kind in COVERAGE},
        "io_families": sorted({family(row) for row in healthy_io_rows
                               if row.get("event") == "FAULT_POINT_OBSERVED"}),
        "max_effective": 80, "max_faults": 8, "recent_gain": [],
        "healthy_receipt": str(output / "healthy_receipt.json"),
    }
    for row in trace:
        if row.get("event") == "FAULT_POINT_OBSERVED" and tuple(row.get(k) for k in KEYS) in selected:
            for fault_type in fault_types(row):
                priority = (250 if row["marker"] == "FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE"
                            else 200 if row["marker"] == "FAULT:HDFS_KEY_UPDATE:LOCAL_APPLY"
                            else 0)
                sequence = [point(row, fault_type)]
                if (output / "runs" / sequence_id(sequence) / "manifest.json").exists():
                    priority += 10000  # Import the completed smoke before starting a new JVM.
                add(state, sequence, priority=priority)
    if not state["queue"]:
        raise RuntimeError("two healthy runs had no stable eligible V2 fault selector")
    return state


def extend(state: dict, sequence: list[dict], trace: list[dict], result: dict,
           new_coverage: int, new_io: int) -> None:
    if not result["valid_for_feedback"] or len(sequence) >= state["max_faults"]:
        return
    applied = [r for r in trace if r.get("event") == "FAULT_APPLIED"]
    last = applied[-1]["seq"]
    actor, resource = sequence[-1]["faultActor"], sequence[-1]["resource"]
    target_site = SITES[state["case_id"]][0]
    targets = [r["seq"] for r in trace if r.get("event") == "TARGET_CHECK"
               and r.get("caseId") == state["case_id"]
               and r.get("siteId") == target_site and r["seq"] > last
               and r.get("targetActor") == actor and r.get("resource") == resource]
    if not targets:
        return
    upper = max(targets)
    for row in trace:
        if (row.get("event") != "FAULT_POINT_OBSERVED" or
                not last < row["seq"] < upper or
                row.get("faultActor") != actor or row.get("resource") != resource):
            continue
        for fault_type in fault_types(row):
            selected = point(row, fault_type)
            if selected not in sequence:
                add(state, sequence + [selected],
                    priority=10 * new_coverage + 20 * new_io + len(sequence)
                    + (100 if row["marker"].startswith("FAULT:HDFS_KEY_UPDATE:") else 0))


def campaign(case: str, output: Path, max_attempts: int, pause_on_candidate: bool) -> dict:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    healthy_file = output / "healthy_receipt.json"
    if not healthy_file.is_file():
        raise RuntimeError("run two original-JUnit calibrations first")
    healthy = json.loads(healthy_file.read_text())
    if healthy.get("pass") is not True or healthy.get("case_id") != case:
        raise RuntimeError("healthy receipt did not pass for this case")
    state_path = output / "campaign-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else initial_state(case, output, healthy)
    atomic(state_path, state)
    while state["queue"] and state["attempted_trials"] < max_attempts:
        if state["effective_trials"] >= state["max_effective"]:
            if (state["max_effective"] == 80 and any(state["recent_gain"][-8:])):
                state["max_effective"], state["max_faults"] = 128, 10
            else:
                break
        item, scheduling = select_next(output, state)
        identity, sequence = item["id"], item["sequence"]
        run = output / "runs" / identity
        plan = output / "plans" / (identity + ".tsv")
        plan.parent.mkdir(parents=True, exist_ok=True)
        if not plan.exists():
            plan.write_text(plan_text(sequence))
        elif plan.read_text() != plan_text(sequence):
            raise RuntimeError(f"plan changed for {identity}")
        state["in_flight"] = identity
        state.setdefault("scheduler_history", []).append(dict(sequence_id=identity,
                                                               **scheduling))
        atomic(state_path, state)
        if not (run / "manifest.json").exists():
            run.parent.mkdir(parents=True, exist_ok=True)
            with (output / "runs" / (identity + ".runner.log")).open("w") as log:
                subprocess.run([sys.executable, str(HERE / "run_original.py"), "--case", case,
                                "--output", str(run), "--plan", str(plan)],
                               stdout=log, stderr=subprocess.STDOUT, check=False)
        if not (run / "manifest.json").exists():
            raise RuntimeError(f"missing JUnit manifest for {identity}; checkpoint retains in-flight trial")
        result = evaluate(case, run, plan, healthy_file)
        trace = rows(run)
        gain = {category: covered(run, category) - set(state["coverage"][category])
                for category in COVERAGE}
        new_coverage = sum(len(values) for values in gain.values()) if result["valid_for_feedback"] else 0
        families = {family(row) for row in trace if row.get("event") == "FAULT_POINT_OBSERVED"}
        new_families = families - set(state["io_families"]) if result["valid_for_feedback"] else set()
        result["new_coverage"] = {name: len(values) for name, values in gain.items()}
        result["new_io_families"] = sorted(new_families)
        result["sequence_id"] = identity
        atomic(run / "v2_result.json", result)
        if result["valid_for_feedback"]:
            for category in COVERAGE:
                state["coverage"][category] = sorted(set(state["coverage"][category]) | gain[category])
            state["io_families"] = sorted(set(state["io_families"]) | new_families)
            state["effective_trials"] += 1
            state["recent_gain"].append(bool(new_coverage or new_families))
            extend(state, sequence, trace, result, new_coverage, len(new_families))
        state["completed"][identity] = {
            "run": str(run), "elapsed_seconds": result["elapsed_seconds"],
            "valid_for_feedback": result["valid_for_feedback"],
            "target_exception_candidate": result["target_exception_candidate"],
            "new_coverage": new_coverage, "new_io_families": len(new_families),
        }
        state["attempted_trials"] += 1
        state["total_elapsed_seconds"] += result["elapsed_seconds"]
        state["queue"] = [candidate for candidate in state["queue"] if candidate["id"] != identity]
        state["in_flight"] = None
        atomic(state_path, state)
        if pause_on_candidate and result["target_exception_candidate"]:
            state["status"] = "candidate_paused_for_replay"
            atomic(state_path, state)
            break
    if not state["queue"]:
        state["status"] = "queue_exhausted"
    elif state["effective_trials"] >= state["max_effective"]:
        state["status"] = "effective_budget_reached"
    elif state["attempted_trials"] >= max_attempts:
        state["status"] = "attempt_cap_reached"
    atomic(state_path, state)
    return {key: state[key] for key in ("case_id", "status", "attempted_trials",
                                       "effective_trials", "total_elapsed_seconds")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("HDFS-12",), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=600)
    parser.add_argument("--pause-on-candidate", action="store_true")
    args = parser.parse_args()
    lock = args.output.resolve() / "campaign.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps(campaign(args.case, args.output, args.max_attempts,
                                  args.pause_on_candidate), sort_keys=True))


if __name__ == "__main__":
    main()
