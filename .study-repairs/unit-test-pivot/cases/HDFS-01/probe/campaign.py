#!/usr/bin/env python3
"""Resumable coverage and I/O guided fault campaign for HDFS-01."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

CASE = Path(__file__).resolve().parent.parent
EVIDENCE = CASE / "evidence"
HEALTHY = EVIDENCE / "healthy"
STATE = EVIDENCE / "campaign-state.json"
RESULT = CASE / "result.json"
RUNNER = Path(__file__).resolve().parent / "run_original.py"
KINDS = ("IOException", "SocketTimeoutException", "EOFException")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.open():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def covered(directory: Path, category: str) -> set[str]:
    file = directory / ("covered_" + category + ".txt")
    return set(file.read_text().splitlines()) if file.is_file() else set()


def selector(row: dict, kind: str) -> dict:
    return {**{k: row[k] for k in ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal")},
            "faultType": kind}


def sequence_id(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:16]


def target_checks(trace: list[dict]) -> list[dict]:
    return [row for row in trace if row["event"] == "TARGET_CHECK"
            and row.get("siteId") == "DFSInputStream.fetchBlockAt#L517-B5"]


def selectable_io(trace: list[dict], after_seq: int = -1) -> list[dict]:
    targets = target_checks(trace)
    if not targets:
        return []
    final_target = targets[-1]["seq"]
    # Main-thread reads/RPCs and the original test's file DataStreamer can
    # affect later block reads. This is a coarse I/O scope, not a graph.
    return [row for row in trace if row["event"] == "FAULT_POINT_OBSERVED"
            and row.get("sourceKey") in {"main", "DataStreamer for file /preadtest.dat"}
            and after_seq < row["seq"] < final_target]


def distance_to_future_target(row: dict, targets: list[dict]) -> int:
    return min((target["seq"] - row["seq"] for target in targets if target["seq"] > row["seq"]), default=999999)


def initial_queue(trace: list[dict]) -> list[list[dict]]:
    targets = target_checks(trace)
    io = selectable_io(trace)
    # Alternate data-transfer reads, block-location RPCs, and IPC responses,
    # then favor sites observed just before a selected guard in both phases.
    io.sort(key=lambda row: (distance_to_future_target(row, targets), row["seq"]))
    reads = [row for row in io if row["marker"].endswith("DATA_TRANSFER:READ")]
    locations = [row for row in io if row["marker"].endswith("GET_BLOCK_LOCATIONS")]
    responses = [row for row in io if row["marker"].endswith("RPC:RESPONSE")
                 and row["sourceKey"] == "main"]
    streamers = [row for row in io if row["sourceKey"].startswith("DataStreamer for file ")]
    balanced = []
    while reads or streamers or locations or responses:
        if reads:
            balanced.append(reads.pop(0))
        if streamers:
            balanced.append(streamers.pop(0))
        if responses:
            balanced.append(responses.pop(0))
        if locations:
            balanced.append(locations.pop(0))
    ordered = []
    for row in balanced:
        ordered.extend([[selector(row, kind)] for kind in KINDS])
    return ordered


def plan_text(sequence: list[dict]) -> str:
    return "".join("\t".join((fault["marker"], fault["siteId"], fault["sourceKey"],
                                str(fault["hitOrdinal"]), "pending", fault["faultType"])) + "\n"
                   for fault in sequence)


def exact_applied(sequence: list[dict], trace: list[dict]) -> tuple[bool, list[dict]]:
    applied = [row for row in trace if row["event"] == "FAULT_APPLIED"]
    exact = len(applied) == len(sequence) and all(
        all(applied[i].get(field) == sequence[i][field]
            for field in ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal", "faultType"))
        for i in range(len(sequence)))
    return exact, applied


def summarize(run: Path, sequence: list[dict], state: dict) -> dict:
    manifest = json.loads((run / "manifest.json").read_text())
    trace = events(run / "runtime_trace.jsonl")
    exact, applied = exact_applied(sequence, trace)
    last_fault = applied[-1]["seq"] if exact else None
    post_checks = [row for row in target_checks(trace) if last_fault is not None and row["seq"] > last_fault]
    target_throws = [row for row in trace if row["event"] == "TARGET_THROW"
                     and row.get("siteId") == "DFSInputStream.fetchBlockAt#L518"
                     and row.get("exception") == "java.io.EOFException"
                     and last_fault is not None and row["seq"] > last_fault]
    valid = exact and bool(post_checks)
    coverage_sets = {name: covered(run, name) for name in ("probes", "methods", "branch_counts", "lines")}
    gain = {name: len(values - set(state["coverage"][name])) if valid else 0
            for name, values in coverage_sets.items()}
    io_families = {"|".join((row["marker"], row["siteId"]))
                   for row in trace if row["event"] == "FAULT_POINT_OBSERVED"}
    return {"sequence": sequence, "elapsed_seconds": manifest["elapsed_seconds"],
            "junit_exit": manifest["returncode"], "exact_order_applied": exact,
            "requested_faults": len(sequence),
            "matched_faults": sum(row["event"] == "FAULT_MATCHED" for row in trace),
            "applied_faults": len(applied),
            "matched": sum(row["event"] == "FAULT_MATCHED" for row in trace),
            "applied": len(applied), "target_after_fault": bool(post_checks),
            "post_fault_target_checks": len(post_checks), "target_eof_after_fault": len(target_throws),
            "target_eof_events": target_throws, "valid_for_feedback": valid,
            "coverage_gain": gain, "coverage_total": {name: len(values) for name, values in coverage_sets.items()},
            "new_io_families": len(io_families - set(state["io_families"])) if valid else 0,
            "bug_mark": "candidate_needs_replay_source_review" if valid and target_throws else "none",
            "manifest": str(run / "manifest.json"), "trace": str(run / "runtime_trace.jsonl"),
            "log": str(run / "junit.log")}


def update_result(state: dict) -> None:
    trials = list(state["completed"].values())
    valid = [trial for trial in trials if trial["valid_for_feedback"]]
    status = "running" if len(trials) < state["budget"]["max_trials"] and state["queue"] else "pending_budget_review"
    old = json.loads(RESULT.read_text())
    if status == "running":
        old.pop("completed_at_utc", None)
    old.update(status=status, cluster_test="org.apache.hadoop.hdfs.TestPread#testPreadDFS",
               instrumentation_provenance={
                   "runtime_hooks": "case_local_offline_asm_9_6_overlay",
                   "coverage": "jacoco_0_8_15_original_hdfs_ipc_classes",
                   "junit": "original_hadoop_3_4_3_test_jar_and_native_fixture",
                   "graphchecker_prewoven": False, "graphchecker_runtime_jar": False,
                   "region_skeleton": False, "static_io_map": False,
                   "causal_graph_or_closure": False,
                   "io_selection": "observed_original_junit_io_plus_coverage_feedback",
               },
               target_reached=True, elapsed_seconds=round(state.get("setup_elapsed_seconds", state["healthy"]["elapsed_seconds"])
                                                   + sum(t["elapsed_seconds"] for t in trials), 3),
               fault_trials=len(trials), strict_injections=sum(t["exact_order_applied"] for t in trials),
               fully_applied_trials=sum(t["exact_order_applied"] for t in trials),
               target_after_fault=len(valid),
               coverage_gain=len(state["coverage"]["branch_counts"]) - state["healthy"]["branch_count"],
               bug_mark="candidate_needs_replay_source_review"
               if any(t["bug_mark"] != "none" for t in trials) else "none",
               evidence=str(STATE.relative_to(CASE.parent.parent)),
               healthy=state["healthy"], budget=state["budget"],
               coverage={name: len(values) for name, values in state["coverage"].items()},
               io_families=len(state["io_families"]), trial_results=trials)
    atomic_json(RESULT, old)


def mutate(trace: list[dict], sequence: list[dict], max_faults: int) -> list[list[dict]]:
    if len(sequence) >= max_faults:
        return []
    exact, applied = exact_applied(sequence, trace)
    if not exact:
        return []
    targets = target_checks(trace)
    rows = selectable_io(trace, applied[-1]["seq"])
    rows.sort(key=lambda row: (0 if row["marker"].endswith("DATA_TRANSFER:READ") else 1,
                               distance_to_future_target(row, targets), row["seq"]))
    return [sequence + [selector(row, KINDS[len(sequence) % len(KINDS)])] for row in rows]


def choose_queue_index(queue: list[list[dict]], completed: int) -> int:
    """Spend most rounds on target-retaining reads and sample file streaming."""
    reads = [i for i, item in enumerate(queue)
             if item[-1]["marker"].endswith("DATA_TRANSFER:READ")]
    streamers = [i for i, item in enumerate(queue)
                 if item[-1]["sourceKey"].startswith("DataStreamer for file ")]
    if completed >= 124:
        deep_reads = [i for i in reads if len(queue[i]) >= 8]
        if deep_reads:
            return max(deep_reads, key=lambda i: (len(queue[i]), -i))
    if completed >= 64 and completed % 4 == 0:
        deep_reads = [i for i in reads if len(queue[i]) >= 4]
        if deep_reads:
            return max(deep_reads, key=lambda i: (len(queue[i]), -i))
    if completed % 5 == 4 and streamers:
        return min(streamers, key=lambda i: (len(queue[i]), i))
    if reads:
        return min(reads, key=lambda i: (len(queue[i]), i))
    if streamers:
        return min(streamers, key=lambda i: (len(queue[i]), i))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-trials", type=int, default=64)
    parser.add_argument("--max-faults", type=int, default=6)
    args = parser.parse_args()
    healthy_manifest = json.loads((HEALTHY / "manifest.json").read_text())
    healthy_trace = events(HEALTHY / "runtime_trace.jsonl")
    checks = target_checks(healthy_trace)
    if healthy_manifest["returncode"] != 0 or not checks:
        raise SystemExit("Healthy original JUnit/selected target not established")
    if STATE.is_file():
        state = json.loads(STATE.read_text())
        prior_max_faults = state["budget"]["max_faults"]
        state["budget"] = {"max_trials": args.max_trials, "max_faults": args.max_faults}
        if args.max_faults > prior_max_faults:
            seen = set(state["completed"]) | {sequence_id(s) for s in state["queue"]}
            for completed_trial in state["completed"].values():
                sequence = completed_trial["sequence"]
                if not completed_trial["valid_for_feedback"] or len(sequence) < prior_max_faults:
                    continue
                for candidate in mutate(events(Path(completed_trial["trace"])), sequence,
                                        args.max_faults):
                    identity = sequence_id(candidate)
                    if identity not in seen:
                        state["queue"].append(candidate)
                        seen.add(identity)
        if state.get("seed_revision") != "data_transfer_read_v2":
            state["setup_elapsed_seconds"] = (state.get("setup_elapsed_seconds", state["healthy"]["elapsed_seconds"])
                                              + healthy_manifest["elapsed_seconds"])
            state["prior_healthy"] = state["healthy"]
            coverage = {name: sorted(covered(HEALTHY, name)) for name in ("probes", "methods", "branch_counts", "lines")}
            io_families = {"|".join((row["marker"], row["siteId"]))
                           for row in healthy_trace if row["event"] == "FAULT_POINT_OBSERVED"}
            state["healthy"] = {"elapsed_seconds": healthy_manifest["elapsed_seconds"],
                                "junit_exit": 0, "target_checks": len(checks),
                                "target_eof_throws": sum(row["event"] == "TARGET_THROW" for row in healthy_trace),
                                "branch_count": len(coverage["branch_counts"]),
                                "io_points": sum(row["event"] == "FAULT_POINT_OBSERVED" for row in healthy_trace)}
            state["coverage"] = coverage
            state["io_families"] = sorted(io_families)
            old_queue = state["queue"]
            seen = set(state["completed"])
            fresh_queue = []
            for sequence in initial_queue(healthy_trace) + old_queue:
                identity = sequence_id(sequence)
                if identity not in seen:
                    fresh_queue.append(sequence)
                    seen.add(identity)
            state["queue"] = fresh_queue
            state["seed_revision"] = "data_transfer_read_v2"
    else:
        coverage = {name: sorted(covered(HEALTHY, name)) for name in ("probes", "methods", "branch_counts", "lines")}
        io_families = {"|".join((row["marker"], row["siteId"]))
                       for row in healthy_trace if row["event"] == "FAULT_POINT_OBSERVED"}
        state = {"case_id": "HDFS-01", "budget": {"max_trials": args.max_trials, "max_faults": args.max_faults},
                 "healthy": {"elapsed_seconds": healthy_manifest["elapsed_seconds"],
                             "junit_exit": 0, "target_checks": len(checks),
                             "target_eof_throws": sum(row["event"] == "TARGET_THROW" for row in healthy_trace),
                             "branch_count": len(coverage["branch_counts"]),
                             "io_points": sum(row["event"] == "FAULT_POINT_OBSERVED" for row in healthy_trace)},
                 "queue": initial_queue(healthy_trace), "completed": {},
                 "coverage": coverage, "io_families": sorted(io_families),
                 "setup_elapsed_seconds": healthy_manifest["elapsed_seconds"],
                 "seed_revision": "data_transfer_read_v2"}
    atomic_json(STATE, state)
    update_result(state)
    if "current" in state and state["current"]["id"] not in state["completed"]:
        state["queue"].insert(0, state["current"]["sequence"])
        state.pop("current")
        atomic_json(STATE, state)
    if state.get("scheduler_revision") != "read_and_streamer_diversity_v2":
        seen = set(state["completed"])
        queue = []
        for sequence in initial_queue(healthy_trace) + state["queue"]:
            identity = sequence_id(sequence)
            if identity not in seen:
                queue.append(sequence)
                seen.add(identity)
        def rank(sequence: list[dict]) -> tuple[int, int, int]:
            fault = sequence[-1]
            if fault["marker"].endswith("DATA_TRANSFER:READ"):
                family = 0
            elif fault["sourceKey"].startswith("DataStreamer for file "):
                family = 1
            elif fault["marker"].endswith("GET_BLOCK_LOCATIONS"):
                family = 2
            else:
                family = 3
            return family, len(sequence), fault["hitOrdinal"]
        queue.sort(key=rank)
        state["queue"] = queue
        state["scheduler_revision"] = "read_and_streamer_diversity_v2"
        atomic_json(STATE, state)
    while len(state["completed"]) < state["budget"]["max_trials"] and state["queue"]:
        sequence = state["queue"].pop(choose_queue_index(state["queue"], len(state["completed"])))
        identity = sequence_id(sequence)
        if identity in state["completed"]:
            continue
        run_root = EVIDENCE / "runs" / identity
        run_root.mkdir(parents=True, exist_ok=True)
        state["current"] = {"id": identity, "sequence": sequence, "started_unix": time.time()}
        atomic_json(STATE, state)
        trial = None
        run = None
        for attempt in (1, 2):
            run = run_root / ("attempt-" + str(attempt))
            run.mkdir(parents=True, exist_ok=True)
            plan = run / "faults.tsv"
            plan.write_text(plan_text(sequence))
            if not (run / "manifest.json").is_file():
                with (run / "runner-console.log").open("w") as log:
                    subprocess.run([sys.executable, str(RUNNER), "--output", str(run),
                                    "--plan", str(plan), "--timeout", "120"],
                                   stdout=log, stderr=subprocess.STDOUT, check=False)
            if not (run / "manifest.json").is_file():
                raise RuntimeError("Missing trial manifest " + identity)
            trial = summarize(run, sequence, state)
            trial["attempt"] = attempt
            if trial["exact_order_applied"]:
                break
        assert trial is not None and run is not None
        state["completed"][identity] = trial
        if trial["valid_for_feedback"]:
            for name in state["coverage"]:
                state["coverage"][name] = sorted(set(state["coverage"][name]) | covered(run, name))
            trace = events(run / "runtime_trace.jsonl")
            state["io_families"] = sorted(set(state["io_families"]) | {
                "|".join((row["marker"], row["siteId"])) for row in trace
                if row["event"] == "FAULT_POINT_OBSERVED"})
            new = mutate(trace, sequence, state["budget"]["max_faults"])
            seen = set(state["completed"]) | {sequence_id(item) for item in state["queue"]}
            new = [item for item in new if sequence_id(item) not in seen]
            if trial["new_io_families"] or any(trial["coverage_gain"].values()):
                state["queue"] = new + state["queue"]
            else:
                state["queue"].extend(new)
        state.pop("current", None)
        atomic_json(STATE, state)
        update_result(state)
        print(json.dumps({"completed": len(state["completed"]), "id": identity,
                          "applied": trial["applied"], "target_after_fault": trial["target_after_fault"],
                          "branch_gain": trial["coverage_gain"]["branch_counts"],
                          "candidate": trial["bug_mark"] != "none"}), flush=True)


if __name__ == "__main__":
    main()
