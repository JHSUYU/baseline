#!/usr/bin/env python3
"""Checkpointed I/O exception sequence campaign for one original HDFS JUnit."""
from __future__ import annotations

import hashlib
import csv
import json
from pathlib import Path
import subprocess
import sys
import time


CASE = Path(__file__).resolve().parent.parent
EVIDENCE = CASE / "evidence"
STATE = EVIDENCE / "campaign-state.json"
RESULT = CASE / "result.json"
LEDGER = CASE / "trial-ledger.csv"
HEALTHY = EVIDENCE / "healthy"
RUNNER = Path(__file__).resolve().parent / "run_original.py"
MAX_TRIALS = 48
MAX_FAULTS = 4


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    result = []
    for line in path.open():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return result


def covered(directory: Path, kind: str) -> set[str]:
    file = directory / ("covered_" + kind + ".txt")
    return set(file.read_text().splitlines()) if file.is_file() else set()


def selector(event: dict) -> dict:
    return {key: event[key] for key in ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal")}


def target_calls(trace: list[dict]) -> list[dict]:
    """Pin the selected check to the second sn0 invocation in this run."""
    ordinals = {}
    active = {}
    result = []
    for raw in trace:
        row = dict(raw)
        if row["event"] == "TARGET_ENTER":
            name = row["snapshot"]
            ordinals[name] = ordinals.get(name, 0) + 1
            active[(row["thread"], name)] = name + "#" + str(ordinals[name])
        if row["event"].startswith("TARGET_"):
            row["invocation_id"] = active.get((row["thread"], row.get("snapshot")))
            result.append(row)
    return result


def selected_branch(trace: list[dict]) -> dict | None:
    return next((row for row in target_calls(trace)
                 if row["event"] == "TARGET_BRANCH" and row["invocation_id"] == "sn0#2"), None)


def key(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:16]


def initial_queue(healthy: list[dict]) -> list[list[dict]]:
    branch = selected_branch(healthy)
    if branch is None or not branch["duplicate"]:
        raise ValueError("Healthy sn0#2 duplicate guard absent")
    target = branch["seq"]
    io = [row for row in healthy if row["event"] == "FAULT_POINT_OBSERVED"
          and row["seq"] < target and row.get("sourceKey") in {"main", "FSEditLogAsync"}]
    # Target-adjacent I/O first; balance RPC and edit-log persistence and retain
    # some earlier setup observations for exploration.
    io.sort(key=lambda row: (abs(target - row["seq"]), row["marker"], row["hitOrdinal"]))
    return [[selector(row)] for row in io]


def plan_text(sequence: list[dict]) -> str:
    return "".join("\t".join((s["marker"], s["siteId"], s["sourceKey"],
                              str(s["hitOrdinal"]), "pending", s.get("faultType", "IOException")))
                   + "\n" for s in sequence)


def summarize(run: Path, sequence: list[dict], baseline: dict, prior: dict) -> dict:
    manifest = read_json(run / "manifest.json")
    trace = events(run / "runtime_trace.jsonl")
    applied = [row for row in trace if row["event"] == "FAULT_APPLIED"]
    matched = [row for row in trace if row["event"] == "FAULT_MATCHED"]
    ordered = len(applied) == len(sequence) and all(
        all(applied[i].get(field) == sequence[i][field]
            for field in ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal"))
        and applied[i].get("faultType", "IOException") == sequence[i].get("faultType", "IOException")
        for i in range(min(len(applied), len(sequence))))
    last_fault = applied[-1]["seq"] if applied and ordered else None
    calls = target_calls(trace)
    post_branches = [row for row in calls if row["event"] == "TARGET_BRANCH"
                     and row["invocation_id"] == "sn0#2"
                     and last_fault is not None and row["seq"] > last_fault]
    post_target = bool(post_branches)
    throws = [row for row in calls if row["event"] == "TARGET_THROW" and
              row.get("exception") == "org.apache.hadoop.hdfs.protocol.SnapshotException" and
              "same name" in row.get("message", "")]
    baseline_throws = baseline["expected_duplicate_throws"]
    unexpected = [row for row in throws if row.get("invocation_id") != "sn0#2"]
    if len(throws) > baseline_throws:
        unexpected = throws
    methods = covered(run, "methods")
    branches = covered(run, "branch_counts")
    probes = covered(run, "probes")
    valid = ordered and post_target
    seen_methods = set(prior["methods"])
    seen_branches = set(prior["branches"])
    seen_probes = set(prior["probes"])
    gain = {"methods": len(methods - seen_methods), "branches": len(branches - seen_branches),
            "probes": len(probes - seen_probes)} if valid else {"methods": 0, "branches": 0, "probes": 0}
    return {"sequence": sequence, "elapsed_seconds": manifest["elapsed_seconds"],
            "junit_exit": manifest["returncode"], "matched": len(matched),
            "applied": len(applied), "exact_order_applied": ordered,
            "target_after_fault": post_target, "post_fault_target_branches": post_branches,
            "selected_target_invocation": "sn0#2", "target_invocations": calls,
            "duplicate_target_throws": len(throws), "expected_healthy_throws": baseline_throws,
            "unexpected_target_throws": unexpected, "bug_mark": "candidate_needs_replay_source_review" if valid and unexpected else "none",
            "coverage_gain": gain,
            "coverage_total": {"methods": len(methods), "branches": len(branches), "probes": len(probes)},
            "valid_for_feedback": valid, "trace": str(run / "runtime_trace.jsonl"),
            "manifest": str(run / "manifest.json"), "log": str(run / "junit.log")}


def write_result(state: dict) -> None:
    numbered = sorted(state["completed"].items(),
                      key=lambda item: Path(item[1]["manifest"]).stat().st_mtime)
    trials = [record for _, record in numbered]
    ledger_temp = LEDGER.with_suffix(".csv.tmp")
    fields = ["trial", "id", "elapsed_seconds", "junit_exit", "fault_count", "sequence_json",
              "matched", "applied", "exact_order_applied", "sn0_second_call_after_fault",
              "duplicate_outcome", "same_name_exception_count", "new_target_exception",
              "method_gain", "branch_gain", "probe_gain", "bug_mark", "manifest", "trace"]
    with ledger_temp.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for number, (identity, row) in enumerate(numbered, 1):
            outcome = row["post_fault_target_branches"]
            writer.writerow({"trial": number, "id": identity, "elapsed_seconds": row["elapsed_seconds"],
                             "junit_exit": row["junit_exit"], "fault_count": len(row["sequence"]),
                             "sequence_json": json.dumps(row["sequence"], sort_keys=True, separators=(",", ":")),
                             "matched": row["matched"], "applied": row["applied"],
                             "exact_order_applied": row["exact_order_applied"],
                             "sn0_second_call_after_fault": row["target_after_fault"],
                             "duplicate_outcome": outcome[0]["duplicate"] if outcome else "",
                             "same_name_exception_count": row["duplicate_target_throws"],
                             "new_target_exception": bool(row["unexpected_target_throws"]),
                             "method_gain": row["coverage_gain"]["methods"],
                             "branch_gain": row["coverage_gain"]["branches"],
                             "probe_gain": row["coverage_gain"]["probes"],
                             "bug_mark": row["bug_mark"], "manifest": row["manifest"], "trace": row["trace"]})
    ledger_temp.replace(LEDGER)
    valid = [t for t in trials if t["valid_for_feedback"]]
    old = read_json(RESULT)
    old.pop("trial_results", None)
    status = ("running" if len(trials) < state["budget"]["max_trials"] and state["queue"]
              else "pending_budget_review")
    if old.get("status") == "quality_complete" and len(trials) >= state["budget"]["max_trials"]:
        status = "quality_complete"
    old.update(status=status,
               cluster_test="org.apache.hadoop.hdfs.TestSnapshotCommands#testCreateSnapshot",
               target_reached=True, elapsed_seconds=round(state["healthy"]["elapsed_seconds"]
                                                    + sum(t["elapsed_seconds"] for t in trials), 3),
               fault_trials=len(trials), strict_injections=sum(t["exact_order_applied"] for t in trials),
               target_after_fault=len(valid), coverage_gain=len(state["branches"]) - state["healthy"]["branch_count"],
               bug_mark="candidate_needs_replay_source_review" if any(t["bug_mark"] != "none" for t in trials) else "none",
               evidence=str(STATE.relative_to(CASE.parent.parent)),
               healthy={"junit_exit": 0, "target_calls": state["healthy"]["target_calls"],
                        "expected_duplicate_throws": state["healthy"]["expected_duplicate_throws"],
                        "elapsed_seconds": state["healthy"]["elapsed_seconds"]},
               budget=state["budget"], trial_ledger=str(LEDGER.relative_to(CASE)),
               trial_metadata_count=len(trials),
               coverage={"methods": len(state["methods"]), "branches": len(state["branches"]),
                         "probes": len(state["probes"])})
    atomic_json(RESULT, old)


def mutation_candidates(trace: list[dict], sequence: list[dict], max_faults: int) -> list[list[dict]]:
    if len(sequence) >= max_faults:
        return []
    branch = selected_branch(trace)
    if branch is None:
        return []
    applied = [row for row in trace if row["event"] == "FAULT_APPLIED"]
    if not applied:
        return []
    last = applied[-1]["seq"]
    candidates = []
    seen = set()
    for row in trace:
        if (row["event"] != "FAULT_POINT_OBSERVED" or not last < row["seq"] < branch["seq"]
                or row.get("sourceKey") not in {"main", "FSEditLogAsync"}):
            continue
        identity = key([selector(row)])
        if identity not in seen:
            candidates.append(row)
            seen.add(identity)
    candidates.sort(key=lambda row: branch["seq"] - row["seq"])
    return [sequence + [selector(row)] for row in candidates]


def reconcile_target_scope(state: dict, healthy: list[dict]) -> dict:
    """Reclassify existing runs and prune old queue; never rerun completed IDs."""
    if state.get("scope_revision") == "sn0_second_call_precheck_v1":
        return state
    methods, branches, probes = [covered(HEALTHY, kind) for kind in ("methods", "branch_counts", "probes")]
    state["methods"], state["branches"], state["probes"] = map(sorted, (methods, branches, probes))
    old = list(state["completed"].items())
    state["completed"] = {}
    for identity, record in old:
        run = Path(record["manifest"]).parent
        fresh = summarize(run, record["sequence"], state["healthy"], state)
        state["completed"][identity] = fresh
        if fresh["valid_for_feedback"]:
            for kind, file_kind in (("methods", "methods"), ("branches", "branch_counts"), ("probes", "probes")):
                state[kind] = sorted(set(state[kind]) | covered(run, file_kind))
    queue = initial_queue(healthy)
    seen = set(state["completed"])
    for record in state["completed"].values():
        if not record["valid_for_feedback"]:
            continue
        run = Path(record["manifest"]).parent
        queue = mutation_candidates(events(run / "runtime_trace.jsonl"), record["sequence"],
                                    state["budget"]["max_faults"]) + queue
    unique = []
    for sequence in queue:
        identity = key(sequence)
        if identity not in seen:
            unique.append(sequence)
            seen.add(identity)
    state["queue"] = unique
    state.pop("current", None)
    state["scope_revision"] = "sn0_second_call_precheck_v1"
    atomic_json(STATE, state)
    write_result(state)
    return state


def main() -> None:
    EVIDENCE.mkdir(exist_ok=True)
    healthy_manifest = read_json(HEALTHY / "manifest.json")
    healthy = events(HEALTHY / "runtime_trace.jsonl")
    if healthy_manifest["returncode"] != 0:
        raise SystemExit("Original healthy JUnit did not pass")
    target = [row for row in healthy if row["event"] == "TARGET_BRANCH"]
    throws = [row for row in healthy if row["event"] == "TARGET_THROW" and "same name" in row.get("message", "")]
    if not target or len(throws) != 1 or throws[0].get("snapshot") != "sn0":
        raise SystemExit("Healthy exact target/expected throw is not established")
    if STATE.is_file():
        state = read_json(STATE)
    else:
        methods, branches, probes = [covered(HEALTHY, kind) for kind in ("methods", "branch_counts", "probes")]
        state = {"case_id": "HDFS-50", "budget": {"max_trials": MAX_TRIALS, "max_faults": MAX_FAULTS},
                 "healthy": {"elapsed_seconds": healthy_manifest["elapsed_seconds"],
                             "target_calls": len(target), "expected_duplicate_throws": len(throws),
                             "branch_count": len(branches)},
                 "queue": initial_queue(healthy), "completed": {},
                 "methods": sorted(methods), "branches": sorted(branches), "probes": sorted(probes)}
        atomic_json(STATE, state)
        write_result(state)
    state = reconcile_target_scope(state, healthy)
    manual = EVIDENCE / "manual-01"
    if (manual / "manifest.json").is_file():
        manual_sequence = [{"marker": "FAULT:HDFS_RPC:RESPONSE", "siteId": "Client.getRpcResponse",
                            "sourceKey": "main", "occurrence": "main/Client.getRpcResponse", "hitOrdinal": 12}]
        manual_id = key(manual_sequence)
        if manual_id not in state["completed"]:
            state["completed"][manual_id] = summarize(manual, manual_sequence, state["healthy"], state)
            atomic_json(STATE, state)
            write_result(state)
    while len(state["completed"]) < state["budget"]["max_trials"] and state["queue"]:
        sequence = state["queue"].pop(0)
        identity = key(sequence)
        if identity in state["completed"]:
            continue
        run = EVIDENCE / "runs" / identity
        run.mkdir(parents=True, exist_ok=True)
        plan = run / "faults.tsv"
        plan.write_text(plan_text(sequence))
        state["current"] = {"id": identity, "sequence": sequence, "started_unix": time.time()}
        atomic_json(STATE, state)
        if not (run / "manifest.json").is_file():
            with (run / "runner-console.log").open("w") as log:
                subprocess.run([sys.executable, str(RUNNER), "--output", str(run), "--plan", str(plan),
                                "--timeout", "90"], stdout=log, stderr=subprocess.STDOUT, check=False)
        if not (run / "manifest.json").is_file():
            raise RuntimeError("trial lacks manifest: " + identity)
        trial = summarize(run, sequence, state["healthy"], state)
        state["completed"][identity] = trial
        if trial["valid_for_feedback"]:
            for kind, file_kind in (("methods", "methods"), ("branches", "branch_counts"), ("probes", "probes")):
                state[kind] = sorted(set(state[kind]) | covered(run, file_kind))
            if len(sequence) < state["budget"]["max_faults"]:
                trace = events(run / "runtime_trace.jsonl")
                existing = {key(item) for item in state["queue"]} | set(state["completed"])
                new = mutation_candidates(trace, sequence, state["budget"]["max_faults"])
                new = [item for item in new if key(item) not in existing]
                state["queue"] = new + state["queue"] if any(trial["coverage_gain"].values()) else state["queue"] + new
        state.pop("current", None)
        atomic_json(STATE, state)
        write_result(state)
        print(json.dumps({"completed": len(state["completed"]), "id": identity,
                          "applied": trial["applied"], "target": trial["target_after_fault"],
                          "gain": trial["coverage_gain"], "candidate": bool(trial["unexpected_target_throws"])}), flush=True)


if __name__ == "__main__":
    main()
