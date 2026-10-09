#!/usr/bin/env python3
"""Resumable shared HDFS storage fuzzing with strict runtime actor identity.

This campaign owns only hdfs-storage-actor-v2/evidence. It never writes the
historical case checkpoints or shared checklist. Source review must happen
before a V2 result is promoted to a case's terminal quality status.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from calibrate import GROUPS, rows, storage_volume, target_throw_signature

HERE = Path(__file__).resolve().parent
FILE_FAULTS = ("IOException", "FileNotFoundException")
RPC_FAULTS = ("IOException", "SocketTimeoutException", "EOFException")
COVERAGE = ("probes", "methods", "branch_counts", "lines")
BASE_EFFECTIVE = 80
EXTENDED_EFFECTIVE = 128
BASE_FAULTS = 8
EXTENDED_FAULTS = 10


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def coverage(directory: Path, category: str) -> set[str]:
    path = directory / f"covered_{category}.txt"
    return set(path.read_text().splitlines()) if path.is_file() else set()


def check_events(trace: list[dict], case_id: str) -> list[dict]:
    return [r for r in trace if r["event"] == "TARGET_CHECK" and r.get("caseId") == case_id
            and r.get("actorKey") != "unbound" and r.get("storageKey") != "unbound"]


def related(io: dict, target: dict) -> bool:
    if io["seq"] >= target["seq"] or io.get("actorKey") != target.get("actorKey"):
        return False
    if io.get("actorKey") == "unbound" or io.get("sourceKey") == "unbound":
        return False
    if "RPC:" in io["marker"]:
        return io.get("peerRole") == "NN0"
    volume = storage_volume(io.get("storageKey"))
    return volume != "unbound" and volume == storage_volume(target.get("storageKey"))


def eligible_io(trace: list[dict], cases: tuple[str, ...], after: int = -1,
                actor: str | None = None) -> list[dict]:
    targets = [r for case in cases for r in check_events(trace, case)]
    return [r for r in trace if r["event"] == "FAULT_POINT_OBSERVED"
            and r["seq"] > after and (actor is None or r.get("actorKey") == actor)
            and any(related(r, target) for target in targets)]


def selector(row: dict, kind: str) -> dict:
    return {key: row.get(key) for key in
            ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal",
             "actorKey", "storageKey", "peerRole")} | {"faultType": kind}


def sequence_id(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:20]


def plan_text(sequence: list[dict]) -> str:
    return "".join("\t".join((s["marker"], s["siteId"], s["sourceKey"],
                               str(s["hitOrdinal"]), "pending", s["faultType"])) + "\n"
                   for s in sequence)


def exact_applied(sequence: list[dict], trace: list[dict]) -> tuple[bool, list[dict]]:
    applied = [r for r in trace if r["event"] == "FAULT_APPLIED"]
    fields = ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal",
              "actorKey", "storageKey", "peerRole", "faultType")
    exact = len(sequence) == len(applied) and all(
        all(a.get(k) == s.get(k) for k in fields) and a.get("faultIndex") == index
        for index, (s, a) in enumerate(zip(sequence, applied)))
    if exact:
        endpoints_by_actor: dict[str, set[str]] = {}
        for row in trace:
            if row.get("peerRole") == "NN0" and row.get("endpointRaw"):
                endpoints_by_actor.setdefault(row.get("actorKey", "unbound"), set()).add(
                    row["endpointRaw"])
        for step, event in zip(sequence, applied):
            if "RPC:" not in step["marker"]:
                continue
            endpoints = endpoints_by_actor.get(step["actorKey"], set())
            if (len(endpoints) != 1 or event.get("endpointRaw") not in endpoints
                    or event.get("actorNamenodeRaw") != event.get("endpointRaw")):
                exact = False
                break
    return exact, applied


def postfault(trace: list[dict], case_id: str, sequence: list[dict],
              applied: list[dict], exact: bool) -> tuple[list[dict], list[dict]]:
    if not exact or not applied:
        return [], []
    last = applied[-1]
    actor = sequence[-1]["actorKey"]
    storage = storage_volume(sequence[-1]["storageKey"]) if "FILE:" in sequence[-1]["marker"] else None
    def same_actor(row: dict) -> bool:
        return row["seq"] > last["seq"] and row.get("actorKey") == actor and (
            storage is None or storage_volume(row.get("storageKey")) == storage)
    targets = [r for r in check_events(trace, case_id) if same_actor(r)]
    throws = [r for r in trace if r["event"] == "TARGET_THROW"
              and r.get("caseId") == case_id and same_actor(r)]
    return targets, throws


def family(row: dict) -> str:
    return "|".join((row["marker"], row["siteId"], row["sourceKey"]))


def initial_queue(receipt: dict, seed_trace: list[dict], cases: tuple[str, ...]) -> list[dict]:
    stable = {tuple(s) for case in cases for s in
              receipt["stable_selectors_by_case"][case]}
    by_identity: dict[str, dict] = {}
    for row in eligible_io(seed_trace, cases):
        address = tuple(row.get(k) for k in ("marker", "siteId", "sourceKey", "hitOrdinal"))
        if address not in stable:
            continue
        related_cases = [case for case in cases
                         if any(related(row, t) for t in check_events(seed_trace, case))]
        if not related_cases:
            continue
        for kind in RPC_FAULTS if "RPC:" in row["marker"] else FILE_FAULTS:
            sequence = [selector(row, kind)]
            identity = sequence_id(sequence)
            target_distance = min(t["seq"] - row["seq"] for case in related_cases
                                  for t in check_events(seed_trace, case) if related(row, t))
            by_identity[identity] = {"id": identity, "sequence": sequence,
                                    "cases": related_cases, "score": max(0, 1000 - target_distance),
                                    "seed": "healthy-a"}
    return sorted(by_identity.values(), key=lambda item: (-item["score"], item["id"]))


def load_state(anchor: Path, group: str, receipt: dict, max_attempts: int) -> dict:
    state_path = anchor / "campaign-state.json"
    _, cases = GROUPS[group]
    receipt_hash = hashlib.sha256((anchor / "healthy_receipt.json").read_bytes()).hexdigest()
    instrumentation_hash = receipt["seeds"][0]["instrumentation_digest_sha256"]
    if state_path.is_file():
        state = json.loads(state_path.read_text())
        if state["group"] != group or state["schema"] != "hdfs-storage-actor-v2-campaign-1":
            raise RuntimeError("checkpoint identity/schema mismatch")
        if len(state["completion_order"]) != len(set(state["completion_order"])) or (
                set(state["completion_order"]) != set(state["completed"])):
            raise RuntimeError("checkpoint completion set mismatch")
        if state["healthy_receipt_sha256"] != receipt_hash:
            raise RuntimeError("healthy calibration receipt changed while resuming")
        if state.get("instrumentation_digest_sha256", instrumentation_hash) != instrumentation_hash:
            raise RuntimeError("instrumentation changed while resuming")
        state["instrumentation_digest_sha256"] = instrumentation_hash
        expected_throws = receipt.get("healthy_target_throw_signatures_by_case", {})
        if state.get("healthy_target_throw_signatures_by_case", expected_throws) != expected_throws:
            raise RuntimeError("healthy target-throw signatures changed while resuming")
        state["healthy_target_throw_signatures_by_case"] = expected_throws
        if max_attempts < state["budget"]["max_attempts"]:
            raise RuntimeError("attempt cap cannot be reduced on resume")
        state["budget"]["max_attempts"] = max_attempts
        return state
    seed = anchor / "healthy-a"
    seed_trace = rows(seed / "runtime_trace.jsonl")
    baseline = {k: sorted(coverage(seed, k)) for k in COVERAGE}
    state = {
        "schema": "hdfs-storage-actor-v2-campaign-1", "group": group,
        "case_ids": list(cases), "healthy_receipt": str(anchor / "healthy_receipt.json"),
        "healthy_receipt_sha256": receipt_hash,
        "instrumentation_digest_sha256": instrumentation_hash,
        "healthy_target_throw_signatures_by_case":
            receipt.get("healthy_target_throw_signatures_by_case", {}),
        "budget": {"base_effective": BASE_EFFECTIVE, "extended_effective": EXTENDED_EFFECTIVE,
                   "base_faults": BASE_FAULTS, "extended_faults": EXTENDED_FAULTS,
                   "max_attempts": max_attempts,
                   "goal_by_case": {case: BASE_EFFECTIVE for case in cases},
                   "faults_by_case": {case: BASE_FAULTS for case in cases}},
        "queue": initial_queue(receipt, seed_trace, cases), "completed": {},
        "completion_order": [], "in_flight": None,
        "effective_by_case": {case: 0 for case in cases},
        "effective_history": {case: [] for case in cases},
        "coverage": {case: dict(baseline) for case in cases},
        "io_families": {case: sorted({family(r) for r in eligible_io(seed_trace, (case,))})
                        for case in cases},
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json(state_path, state)
    return state


def pick(state: dict) -> dict | None:
    if state["in_flight"] is not None:
        return state["in_flight"]
    while state["queue"]:
        n = len(state["completion_order"])
        target_lost_file = sum(
            bool(entry.get("item")) and bool(entry.get("result"))
            and "FILE:" in entry["item"]["sequence"][-1]["marker"]
            and entry["result"]["exact_order_applied"]
            and not any(result["valid_for_feedback"]
                        for result in entry["result"]["by_case"].values())
            for entry in state["completed"].values())
        # Repeated VERSION-read faults killed startup before its exact check.
        # Keep their evidence and queue entries, but favor bound RPC and cases
        # whose postfault target has had fewer effective trials so far.
        progress = state["effective_by_case"]
        frontier = max(progress.values(), default=0)
        def priority(i: int) -> tuple[int, int, int]:
            entry = state["queue"][i]
            pending = [c for c in entry["cases"]
                       if progress.get(c, 0) < state["budget"]["goal_by_case"].get(c, 80)]
            deficit = frontier - min((progress.get(c, 0) for c in pending), default=frontier)
            file_penalty = 1000 if (target_lost_file >= 3 and
                                    "FILE:" in entry["sequence"][-1]["marker"]) else 0
            return (entry["score"] + 300 * deficit - file_penalty,
                    len(entry["sequence"]), -i)
        if n % 10 == 9:  # occasionally sample the oldest pending bound RPC
            rpc = [i for i, entry in enumerate(state["queue"])
                   if "RPC:" in entry["sequence"][-1]["marker"]]
            index = rpc[0] if rpc else 0
        else:
            index = max(range(len(state["queue"])), key=priority)
        item = state["queue"].pop(index)
        if item["id"] in state["completed"]:
            continue
        if all(state["effective_by_case"][c] >= state["budget"]["goal_by_case"][c]
               for c in item["cases"]):
            continue
        state["in_flight"] = item
        return item
    return None


def summarize_attempt(anchor: Path, item: dict, run: Path, cases: tuple[str, ...],
                      state: dict) -> dict:
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest.get("instrumentation_digest_sha256") != state["instrumentation_digest_sha256"]:
        raise RuntimeError("trial instrumentation differs from calibrated healthy seeds: " + str(run))
    trace = rows(run / "runtime_trace.jsonl")
    exact, applied = exact_applied(item["sequence"], trace)
    covered = {k: coverage(run, k) for k in COVERAGE}
    summary = {"manifest": str(run / "manifest.json"),
               "trace": str(run / "runtime_trace.jsonl"),
               "trace_sha256": hashlib.sha256((run / "runtime_trace.jsonl").read_bytes()).hexdigest(),
               "junit_log": str(run / "junit.log"),
               "junit_exit": manifest["returncode"],
               "elapsed_seconds": manifest["elapsed_seconds"],
               "exact_order_applied": exact, "applied_faults": len(applied),
               "requested_faults": len(item["sequence"]), "by_case": {}}
    for case in cases:
        post, throws = postfault(trace, case, item["sequence"], applied, exact)
        valid = exact and bool(post)
        gains = {k: len(covered[k] - set(state["coverage"][case][k])) if valid else 0
                 for k in COVERAGE}
        new_io = len({family(r) for r in eligible_io(trace, (case,))}
                     - set(state["io_families"][case])) if valid else 0
        summary["by_case"][case] = {
            "valid_for_feedback": valid, "same_actor_post_target": len(post),
            "target_exception_after_fault": len(throws), "target_exceptions": throws,
            "target_exceptions_matching_healthy_signature": sum(
                target_throw_signature(row) in {
                    tuple(signature) for signature in
                    state["healthy_target_throw_signatures_by_case"].get(case, [])}
                for row in throws),
            "bug_mark": "candidate_needs_replay_source_review" if throws else "none",
            "coverage_gain": gains, "new_io_families": new_io,
        }
    return summary


def add_mutations(state: dict, item: dict, trace: list[dict]) -> None:
    sequence = item["sequence"]
    exact, applied = exact_applied(sequence, trace)
    if not exact or not applied:
        return
    eligible_cases = [c for c in item["cases"]
                      if state["effective_by_case"][c] < state["budget"]["goal_by_case"][c]
                      and postfault(trace, c, sequence, applied, exact)[0]]
    if not eligible_cases:
        return
    max_depth = max(state["budget"]["faults_by_case"][c] for c in eligible_cases)
    if len(sequence) >= max_depth:
        return
    actor = sequence[-1]["actorKey"]
    seen = set(state["completed"]) | {entry["id"] for entry in state["queue"]}
    if state["in_flight"] is not None:
        seen.add(state["in_flight"]["id"])
    for row in eligible_io(trace, tuple(eligible_cases), after=applied[-1]["seq"], actor=actor):
        kinds = RPC_FAULTS if "RPC:" in row["marker"] else FILE_FAULTS
        for kind in kinds:
            child = sequence + [selector(row, kind)]
            identity = sequence_id(child)
            if identity in seen:
                continue
            child_cases = [case for case in eligible_cases
                           if len(child) <= state["budget"]["faults_by_case"][case]
                           and any(related(row, t) for t in check_events(trace, case))]
            if not child_cases:
                continue
            score = 1000 + 70 * len(child) + 20 * len(child_cases)
            parent = state["completed"].get(item["id"], {}).get("result", {})
            score += max((parent.get("by_case", {}).get(case, {})
                          .get("coverage_gain", {}).get("branch_counts", 0)
                          for case in child_cases), default=0)
            state["queue"].append({"id": identity, "sequence": child,
                                   "cases": child_cases, "score": score,
                                   "seed": item["id"]})
            seen.add(identity)


def advance_goals(state: dict) -> None:
    for case in state["case_ids"]:
        if state["effective_by_case"][case] != BASE_EFFECTIVE:
            continue
        if state["budget"]["goal_by_case"][case] != BASE_EFFECTIVE:
            continue
        last = state["effective_history"][case][-8:]
        novelty = any(x["coverage_gain"]["branch_counts"] > 0
                      or x["new_io_families"] > 0 for x in last)
        if novelty:
            state["budget"]["goal_by_case"][case] = EXTENDED_EFFECTIVE
            state["budget"]["faults_by_case"][case] = EXTENDED_FAULTS
            state.setdefault("extensions", []).append({"case": case,
                "trigger": "last_eight_effective_coverage_or_io_novelty",
                "at_completed": len(state["completion_order"])})


def campaign(group: str, anchor: Path, max_attempts: int, timeout: int,
             pause_after_first_effective: bool = False) -> dict:
    case, cases = GROUPS[group]
    receipt = json.loads((anchor / "healthy_receipt.json").read_text())
    if not receipt["pass"] or receipt["group"] != group:
        raise RuntimeError("two healthy calibrations have not passed")
    state = load_state(anchor, group, receipt, max_attempts)
    state_path = anchor / "campaign-state.json"
    state["status"] = "running"
    write_json(state_path, state)
    while len(state["completion_order"]) < max_attempts:
        if pause_after_first_effective and any(state["effective_by_case"].values()):
            state["status"] = "first_effective_pause"
            break
        if all(state["effective_by_case"][c] >= state["budget"]["goal_by_case"][c]
               for c in cases):
            state["status"] = "effective_budget_met"
            break
        item = pick(state)
        write_json(state_path, state)
        if item is None:
            state["status"] = "queue_exhausted"
            break
        root = anchor / "runs" / item["id"]
        root.mkdir(parents=True, exist_ok=True)
        attempts = []
        chosen = None
        for attempt_no in (1, 2):
            run = root / f"attempt-{attempt_no}"
            run.mkdir(parents=True, exist_ok=True)
            plan = run / "faults.tsv"
            if not plan.is_file():
                plan.write_text(plan_text(item["sequence"]))
            elif plan.read_text() != plan_text(item["sequence"]):
                raise RuntimeError("plan drift while resuming " + item["id"])
            if not (run / "manifest.json").is_file():
                with (run / "runner-console.log").open("w") as log:
                    subprocess.run([sys.executable, str(HERE / "run_original.py"),
                                    "--case", case, "--output", str(run),
                                    "--plan", str(plan), "--timeout", str(timeout)],
                                   stdout=log, stderr=subprocess.STDOUT, check=False)
            if not (run / "manifest.json").is_file() or not (run / "runtime_trace.jsonl").is_file():
                raise RuntimeError("missing durable attempt output " + str(run))
            result = summarize_attempt(anchor, item, run, cases, state)
            attempts.append(result)
            if result["exact_order_applied"]:
                chosen = result
                break
        if chosen is None:
            chosen = attempts[-1]
        state["completed"][item["id"]] = {"item": item, "attempts": attempts,
                                           "result": chosen}
        state["completion_order"].append(item["id"])
        state["in_flight"] = None
        trace = rows(Path(chosen["trace"]))
        run_cov = {k: coverage(Path(chosen["manifest"]).parent, k) for k in COVERAGE}
        for c in cases:
            outcome = chosen["by_case"][c]
            if not outcome["valid_for_feedback"]:
                continue
            state["effective_by_case"][c] += 1
            state["effective_history"][c].append({
                "sequence_id": item["id"], "coverage_gain": outcome["coverage_gain"],
                "new_io_families": outcome["new_io_families"]})
            for category in COVERAGE:
                state["coverage"][c][category] = sorted(
                    set(state["coverage"][c][category]) | run_cov[category])
            state["io_families"][c] = sorted(set(state["io_families"][c]) |
                                                {family(r) for r in eligible_io(trace, (c,))})
        advance_goals(state)
        add_mutations(state, item, trace)
        write_json(state_path, state)
    else:
        state["status"] = "attempt_cap_pending"
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(state_path, state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=GROUPS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-attempts", type=int, default=600)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--pause-after-first-effective", action="store_true",
                        help="Stop after the first strict same-actor postfault target")
    args = parser.parse_args()
    state = campaign(args.group, args.output.resolve(), args.max_attempts, args.timeout,
                     args.pause_after_first_effective)
    print(json.dumps({"group": args.group, "status": state["status"],
                      "completed": len(state["completion_order"]),
                      "effective_by_case": state["effective_by_case"],
                      "goal_by_case": state["budget"]["goal_by_case"],
                      "queue": len(state["queue"])}, indent=2))


if __name__ == "__main__":
    main()
