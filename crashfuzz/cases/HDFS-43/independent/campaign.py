#!/usr/bin/env python3
"""HDFS-43 coverage and observed-I/O guided original MiniDFSCluster JUnit trials."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent
RUNNER = HERE / "run_original.py"
GROUPS = {
    "truncate43": ("HDFS-43",),
}
SITES = {
    "HDFS-43": ("FSDirTruncateOp.truncate#L113-IFNE",),
}
TARGET = {
    "HDFS-43": ("FSDirTruncateOp.java", "truncate", 117,
                "newLength == truncateLength for a block UNDER_RECOVERY"),
}
EXPECTED = {
    "HDFS-43": ("org.apache.hadoop.hdfs.protocol.AlreadyBeingCreatedException",
                "is being truncated"),
}
FILE_FAULTS = ("IOException", "FileNotFoundException")
RPC_FAULTS = ("IOException", "SocketTimeoutException", "EOFException")
COVERAGE = ("probes", "methods", "branch_counts", "lines")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temp.replace(path)


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


def covered(path: Path, category: str) -> set[str]:
    name = path / ("covered_" + category + ".txt")
    return set(name.read_text().splitlines()) if name.is_file() else set()


def families(trace: list[dict]) -> set[str]:
    # BlockRecoveryWorker thread names include an identityHashCode. The Java
    # recorder masks decimal digits, leaving random a-f hex characters behind
    # (for example @Nfaf). That is an exact per-run selector, but not a new
    # stable I/O family for feedback or budget extension.
    def stable_source(source: str) -> str:
        return re.sub(r"@[0-9a-fA-FN]+", "@object", source)

    return {"|".join((r["marker"], r["siteId"], stable_source(r["sourceKey"])))
            for r in trace if r["event"] == "FAULT_POINT_OBSERVED"}


def checks(trace: list[dict], case_id: str) -> list[dict]:
    return [r for r in trace if r["event"] == "TARGET_CHECK"
            and r.get("caseId") == case_id and r.get("siteId") in SITES[case_id]]


def io_before_targets(trace: list[dict], cases: tuple[str, ...], after: int = -1) -> list[dict]:
    targets = [r for c in cases for r in checks(trace, c)]
    if not targets:
        return []
    end = max(r["seq"] for r in targets)
    return [r for r in trace if r["event"] == "FAULT_POINT_OBSERVED"
            and r["marker"].startswith("FAULT:HDFS43_") and after < r["seq"] < end]


def selector(row: dict, kind: str) -> dict:
    return {**{k: row[k] for k in ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal")},
            "faultType": kind}


def sequence_id(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:16]


def plan_text(sequence: list[dict]) -> str:
    return "".join("\t".join((s["marker"], s["siteId"], s["sourceKey"],
                                str(s["hitOrdinal"]), "pending", s["faultType"])) + "\n"
                   for s in sequence)


def exact_applied(sequence: list[dict], trace: list[dict]) -> tuple[bool, list[dict]]:
    applied = [r for r in trace if r["event"] == "FAULT_APPLIED"]
    return len(applied) == len(sequence) and all(
        all(applied[i].get(k) == sequence[i][k] for k in
            ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal", "faultType"))
        for i in range(len(sequence))), applied


def distance(row: dict, targets: list[dict]) -> int:
    return min((t["seq"] - row["seq"] for t in targets if t["seq"] > row["seq"]),
               default=999999)


def initial_queue(trace: list[dict], cases: tuple[str, ...]) -> list[list[dict]]:
    targets = [r for c in cases for r in checks(trace, c)]
    # Faults after the first exact check can still reach later instances.
    rows = [r for r in io_before_targets(trace, cases)
            if "datanodeMaster" not in r["sourceKey"]]
    rows.sort(key=lambda r: (distance(r, targets), r["seq"]))
    rpc = [r for r in rows if "RPC:" in r["marker"]]
    files = [r for r in rows if "FILE:" in r["marker"]]
    balanced = []
    while rpc or files:
        if rpc:
            balanced.append(rpc.pop(0))
        if files:
            balanced.append(files.pop(0))
    return [[selector(r, kind)] for r in balanced
            for kind in (RPC_FAULTS if "RPC:" in r["marker"] else FILE_FAULTS)]


def summarize(case_id: str, seq: list[dict], trace: list[dict], manifest: dict,
              state: dict, run: Path, exact: bool, applied: list[dict],
              run_coverage: dict[str, set[str]]) -> dict:
    final_fault = applied[-1]["seq"] if exact else None
    post = [r for r in checks(trace, case_id)
            if final_fault is not None and r["seq"] > final_fault]
    throws = [r for r in trace if r["event"] == "TARGET_THROW"
              and r.get("caseId") == case_id and final_fault is not None
              and r["seq"] > final_fault]
    valid = exact and bool(post)
    expected_class, prefix = EXPECTED[case_id]
    expected = valid and bool(throws) and all(
        r.get("exception") == expected_class and prefix in r.get("message", "")
        for r in throws)
    # A target assertion in HDFS-27 needs replay and source review even if
    # its exception class and message match the guard's wording.
    candidate = valid and bool(throws) and (case_id == "HDFS-27" or not expected)
    return {
        "sequence": seq, "elapsed_seconds": manifest["elapsed_seconds"],
        "junit_exit": manifest["returncode"], "exact_order_applied": exact,
        "requested_faults": len(seq),
        "matched_faults": sum(r["event"] == "FAULT_MATCHED" for r in trace),
        "applied_faults": len(applied), "target_after_fault": bool(post),
        "post_fault_target_checks": len(post), "target_exception_after_fault": len(throws),
        "target_exception_events": throws,
        "target_exception_classification": ("candidate_needs_replay_source_review" if candidate
            else "expected_truncate_in_progress_response" if expected else "none"),
        "valid_for_feedback": valid,
        "coverage_gain": {k: len(run_coverage[k] - set(state["coverage"][case_id][k]))
                          if valid else 0 for k in COVERAGE},
        "coverage_total": {k: len(run_coverage[k]) for k in COVERAGE},
        "new_io_families": len(families(trace) - set(state["io_families"][case_id]))
            if valid else 0,
        "bug_mark": "candidate_needs_replay_source_review" if candidate else "none",
        "manifest": str(run / "manifest.json"), "trace": str(run / "runtime_trace.jsonl"),
        "log": str(run / "junit.log")}


def update_results(state: dict, cases: tuple[str, ...], state_path: Path) -> None:
    for case_id in cases:
        path = BASE / case_id / "result.json"
        old = json.loads(path.read_text())
        trials = [state["completed"][identity][case_id]
                  for identity in state["completion_order"]]
        valid = [t for t in trials if t["valid_for_feedback"]]
        source, function, line, code = TARGET[case_id]
        old.pop("reason", None)
        old.update(
            status="running" if len(trials) < state["budget"]["max_trials"] and state["queue"]
                else "pending_budget_review",
            methodology="independent_coverage_io_original_junit_shared_run"
                if len(cases) > 1 else "independent_coverage_io_original_junit",
            target_source_file="hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/namenode/" + source,
            target_source_line=line, target_guard_sites=list(SITES[case_id]),
            target_function=source.removesuffix(".java") + "." + function,
            target_code=code,
            cluster_test="org.apache.hadoop.hdfs.server.namenode.TestFileTruncate#testTruncateTwiceTogether",
            own_mapped_cluster_test="org.apache.hadoop.hdfs.server.namenode.TestFileTruncate#testMultipleTruncate",
            shared_run_case_ids=list(cases),
            instrumentation_provenance={
                "runtime_hooks": "case_local_offline_asm_9_6_overlay",
                "coverage": "jacoco_0_8_15_production_hdfs_ipc_classes",
                "coverage_filter": "exclude_runtime_generated_MockitoMock_classes",
                "junit": "original_hadoop_3_4_3_test_jar_and_native_fixture",
                "graphchecker_prewoven": False, "graphchecker_runtime_jar": False,
                "region_skeleton": False, "static_io_map": False,
                "causal_graph_or_closure": False,
                "io_selection": "observed_original_junit_io_plus_production_coverage_feedback",
                "io_family_normalization": "thread_object_hash_to_@object_for_feedback_only; exact_runtime_selector_unchanged"},
            target_reached=state["healthy"][case_id]["target_checks"] > 0,
            elapsed_seconds=round(state["setup_elapsed_seconds"] +
                sum(t["elapsed_seconds"] for t in trials), 3),
            fault_trials=len(trials),
            strict_injections=sum(t["exact_order_applied"] for t in trials),
            fully_applied_trials=sum(t["exact_order_applied"] for t in trials),
            target_after_fault=len(valid),
            target_exception_after_fault=sum(t["target_exception_after_fault"] for t in trials),
            expected_guard_response_trials=sum(t["target_exception_classification"] ==
                "expected_truncate_in_progress_response" for t in trials),
            coverage_gain=len(state["coverage"][case_id]["branch_counts"])
                - state["healthy"][case_id]["branch_count"],
            bug_mark="candidate_needs_replay_source_review" if any(t["bug_mark"] != "none"
                for t in trials) else "none",
            evidence=os.path.relpath(state_path, path.parent),
            healthy=state["healthy"][case_id], budget=state["budget"],
            coverage={k: len(v) for k, v in state["coverage"][case_id].items()},
            io_families=len(state["io_families"][case_id]), trial_results=trials)
        atomic_json(path, old)


def mutate(trace: list[dict], seq: list[dict], cases: tuple[str, ...],
           max_faults: int) -> list[list[dict]]:
    if len(seq) >= max_faults:
        return []
    exact, applied = exact_applied(seq, trace)
    if not exact:
        return []
    targets = [r for c in cases for r in checks(trace, c)]
    rows = io_before_targets(trace, cases, applied[-1]["seq"])
    rows.sort(key=lambda r: (distance(r, targets), r["seq"]))
    return [seq + [selector(r, (RPC_FAULTS if "RPC:" in r["marker"] else FILE_FAULTS)
                              [len(seq) % (3 if "RPC:" in r["marker"] else 2)])]
            for r in rows]


def choose(queue: list[list[dict]], n: int) -> int:
    def stable(seq: list[dict]) -> int:
        first = seq[0]
        identity = (first["marker"], first["siteId"], first["sourceKey"])
        return int(all((s["marker"], s["siteId"], s["sourceKey"]) == identity
                       for s in seq) and all(a["hitOrdinal"] < b["hitOrdinal"]
                                             for a, b in zip(seq, seq[1:])))
    deep = [i for i, s in enumerate(queue) if len(s) >= 2]
    if deep and n >= 12 and n % 3 == 0:
        return max(deep, key=lambda i: (stable(queue[i]), len(queue[i]), -i))
    rpc = [i for i, s in enumerate(queue) if "RPC:" in s[-1]["marker"]]
    files = [i for i, s in enumerate(queue) if "FILE:" in s[-1]["marker"]]
    pool = files if n % 4 == 3 and files else rpc if rpc else files
    return min(pool, key=lambda i: (len(queue[i]), i)) if pool else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=GROUPS, required=True)
    parser.add_argument("--max-trials", type=int, default=80)
    parser.add_argument("--max-faults", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=360)
    args = parser.parse_args()
    cases = GROUPS[args.group]
    anchor = BASE / cases[0] / "independent/evidence"
    healthy = anchor / "healthy"
    state_path = anchor / "campaign-state.json"
    healthy_manifest = json.loads((healthy / "manifest.json").read_text())
    healthy_trace = events(healthy / "runtime_trace.jsonl")
    if healthy_manifest["returncode"] != 0 or not all(checks(healthy_trace, c) for c in cases):
        raise SystemExit("All exact targets must be reached by passing original JUnit")
    if state_path.is_file():
        state = json.loads(state_path.read_text())
        if set(state["completion_order"]) != set(state["completed"]):
            raise SystemExit("Inconsistent checkpoint order")
        old_max = state["budget"]["max_faults"]
        state["budget"] = {"max_trials": args.max_trials, "max_faults": args.max_faults}
        if "current" in state and state["current"]["id"] not in state["completed"]:
            state["queue"].insert(0, state["current"]["sequence"])
            state.pop("current")
        if args.max_faults > old_max:
            seen = set(state["completed"]) | {sequence_id(s) for s in state["queue"]}
            for item in state["completed"].values():
                seq = item[cases[0]]["sequence"]
                if len(seq) < old_max or not any(item[c]["valid_for_feedback"] for c in cases):
                    continue
                for new in mutate(events(Path(item[cases[0]]["trace"])), seq, cases, args.max_faults):
                    identity = sequence_id(new)
                    if identity not in seen:
                        state["queue"].append(new)
                        seen.add(identity)
    else:
        baseline = {k: sorted(covered(healthy, k)) for k in COVERAGE}
        state = {
            "case_ids": list(cases),
            "budget": {"max_trials": args.max_trials, "max_faults": args.max_faults},
            "healthy": {c: {"elapsed_seconds": healthy_manifest["elapsed_seconds"],
                "junit_exit": 0, "target_checks": len(checks(healthy_trace, c)),
                "target_exceptions": sum(r["event"] == "TARGET_THROW" and r.get("caseId") == c
                                         for r in healthy_trace),
                "branch_count": len(baseline["branch_counts"]),
                "io_points": sum(r["event"] == "FAULT_POINT_OBSERVED" for r in healthy_trace)}
                for c in cases},
            "queue": initial_queue(healthy_trace, cases), "completed": {}, "completion_order": [],
            "coverage": {c: dict(baseline) for c in cases},
            "io_families": {c: sorted(families(healthy_trace)) for c in cases},
            "setup_elapsed_seconds": healthy_manifest["elapsed_seconds"],
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    atomic_json(state_path, state)
    update_results(state, cases, state_path)
    while len(state["completion_order"]) < args.max_trials and state["queue"]:
        seq = state["queue"].pop(choose(state["queue"], len(state["completion_order"])))
        identity = sequence_id(seq)
        if identity in state["completed"]:
            continue
        root = anchor / "runs" / identity
        root.mkdir(parents=True, exist_ok=True)
        state["current"] = {"id": identity, "sequence": seq, "started_unix": time.time()}
        atomic_json(state_path, state)
        summary = None
        for attempt in (1, 2):
            run = root / ("attempt-" + str(attempt))
            run.mkdir(parents=True, exist_ok=True)
            plan = run / "faults.tsv"
            plan.write_text(plan_text(seq))
            if not (run / "manifest.json").is_file():
                with (run / "runner-console.log").open("w") as log:
                    subprocess.run([sys.executable, str(RUNNER), "--case", cases[0],
                                    "--output", str(run), "--plan", str(plan),
                                    "--timeout", str(args.timeout)],
                                   stdout=log, stderr=subprocess.STDOUT, check=False)
            if not (run / "manifest.json").is_file():
                raise RuntimeError("Missing manifest: " + identity)
            manifest = json.loads((run / "manifest.json").read_text())
            trace = events(run / "runtime_trace.jsonl")
            exact, applied = exact_applied(seq, trace)
            coverage = {k: covered(run, k) for k in COVERAGE}
            summary = {c: summarize(c, seq, trace, manifest, state, run,
                                    exact, applied, coverage) for c in cases}
            for row in summary.values():
                row["attempt"] = attempt
            if exact:
                break
        assert summary is not None
        state["completed"][identity] = summary
        state["completion_order"].append(identity)
        trace = events(Path(summary[cases[0]]["trace"]))
        run = Path(summary[cases[0]]["manifest"]).parent
        for c in cases:
            if summary[c]["valid_for_feedback"]:
                for k in COVERAGE:
                    state["coverage"][c][k] = sorted(set(state["coverage"][c][k]) | covered(run, k))
                state["io_families"][c] = sorted(set(state["io_families"][c]) | families(trace))
        if any(summary[c]["valid_for_feedback"] for c in cases):
            seen = set(state["completed"]) | {sequence_id(s) for s in state["queue"]}
            new = [s for s in mutate(trace, seq, cases, args.max_faults)
                   if sequence_id(s) not in seen]
            if any(summary[c]["new_io_families"] or any(summary[c]["coverage_gain"].values())
                   for c in cases):
                state["queue"] = new + state["queue"]
            else:
                state["queue"].extend(new)
        state.pop("current", None)
        atomic_json(state_path, state)
        update_results(state, cases, state_path)
        print(json.dumps({"group": args.group, "completed": len(state["completion_order"]),
                          "id": identity, "applied": summary[cases[0]]["applied_faults"],
                          "target_after": {c: summary[c]["target_after_fault"] for c in cases},
                          "candidate": {c: summary[c]["bug_mark"] for c in cases}}), flush=True)


if __name__ == "__main__":
    main()
