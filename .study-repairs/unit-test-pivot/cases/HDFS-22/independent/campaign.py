#!/usr/bin/env python3
"""One original JUnit, five separately scored storage-version checks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
CASE22 = HERE.parent
CASE23 = CASE22.parent / "HDFS-23"
CASE25 = CASE22.parent / "HDFS-25"
CASE34 = CASE22.parent / "HDFS-34"
CASE35 = CASE22.parent / "HDFS-35"
EVIDENCE = HERE / "evidence"
HEALTHY = EVIDENCE / "healthy"
STATE = EVIDENCE / "campaign-state.json"
RUNNER = HERE / "run_original.py"
CASES = {
    "HDFS-22": {"directory": CASE22, "guard_line": 392, "line": 396,
                "source_file": "BlockPoolSliceStorage.java", "function": "doTransition",
                "site": "BlockPoolSliceStorage.doTransition#L392-IF_ICMPEQ",
                "code": "getNamespaceID() == nsInfo.getNamespaceID()",
                "expected_message": "Incompatible namespaceIDs in "},
    "HDFS-23": {"directory": CASE23, "guard_line": 398, "line": 401,
                "source_file": "BlockPoolSliceStorage.java", "function": "doTransition",
                "site": "BlockPoolSliceStorage.doTransition#L398-IFNE",
                "code": "blockpoolID.equals(nsInfo.getBlockPoolID())",
                "expected_message": "Incompatible blockpoolIDs in "},
    "HDFS-25": {"directory": CASE25, "guard_line": 184, "line": 186,
                "source_file": "BlockPoolSliceStorage.java", "function": "loadStorageDirectory",
                "site": "BlockPoolSliceStorage.loadStorageDirectory#L184-IFEQ",
                "code": "getCTime() == nsInfo.getCTime()",
                "expected_message": "Datanode CTime (="},
    "HDFS-34": {"directory": CASE34, "guard_line": 740, "line": 744,
                "source_file": "DataStorage.java", "function": "doTransition",
                "site": "DataStorage.doTransition#L740-IF_ICMPEQ",
                "code": "!federationSupported && getNamespaceID() == nsInfo.getNamespaceID()",
                "expected_message": "Incompatible namespaceIDs in "},
    "HDFS-35": {"directory": CASE35, "guard_line": 749, "line": 752,
                "source_file": "DataStorage.java", "function": "doTransition",
                "site": "DataStorage.doTransition#L749-IFNE",
                "code": "federationSupported && getClusterID().equals(nsInfo.getClusterID())",
                "expected_message": "Incompatible clusterIDs in "},
}
FILE_KINDS = ("IOException", "FileNotFoundException")
RPC_KINDS = ("IOException", "SocketTimeoutException", "EOFException")
COVERAGE = ("probes", "methods", "branch_counts", "lines")


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
            pass
    return rows


def covered(directory: Path, category: str) -> set[str]:
    path = directory / ("covered_" + category + ".txt")
    return set(path.read_text().splitlines()) if path.is_file() else set()


def families(trace: list[dict]) -> set[str]:
    return {"|".join((row["marker"], row["siteId"], row["sourceKey"]))
            for row in trace if row["event"] == "FAULT_POINT_OBSERVED"}


def checks(trace: list[dict], case_id: str) -> list[dict]:
    return [row for row in trace if row["event"] == "TARGET_CHECK"
            and row.get("caseId") == case_id and row.get("siteId") == CASES[case_id]["site"]]


def selectable_io(trace: list[dict], after_seq: int = -1) -> list[dict]:
    targets = [row for case_id in CASES for row in checks(trace, case_id)]
    if not targets:
        return []
    final_target = max(row["seq"] for row in targets)
    return [row for row in trace if row["event"] == "FAULT_POINT_OBSERVED"
            and row["marker"].startswith("FAULT:HDFS_BP_")
            and after_seq < row["seq"] < final_target]


def selector(row: dict, kind: str) -> dict:
    return {**{k: row[k] for k in ("marker", "siteId", "sourceKey", "occurrence", "hitOrdinal")},
            "faultType": kind}


def sequence_id(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True).encode()).hexdigest()[:16]


def sequence_fingerprint(sequence: list[dict]) -> tuple[tuple[str, str, str, int, str], ...]:
    return tuple(tuple(fault[field] for field in
                       ("marker", "siteId", "sourceKey", "hitOrdinal", "faultType"))
                 for fault in sequence)


def distance(row: dict, targets: list[dict]) -> int:
    return min((target["seq"] - row["seq"] for target in targets
                if target["seq"] > row["seq"]), default=999999)


def initial_queue(trace: list[dict]) -> list[list[dict]]:
    targets = [row for case_id in CASES for row in checks(trace, case_id)]
    first_target = min(row["seq"] for row in targets)
    # The original test's first three DataNode VERSION variants are expected
    # to start. An exception in any of them aborts the test before later
    # checks. The fourth read begins the first namespace-incompatible variant.
    fourth_version = next((row["seq"] for row in trace
                          if row["event"] == "FAULT_POINT_OBSERVED"
                          and row["siteId"] == "DataStorage.readProperties"
                          and row["sourceKey"] == "dfs/data1"
                          and row["hitOrdinal"] == 4), first_target + 1)
    rows = sorted((row for row in selectable_io(trace) if row["seq"] >= fourth_version
                   and "datanodeMaster" not in row["sourceKey"]),
                  key=lambda row: (distance(row, targets), row["seq"]))
    files = [row for row in rows if "FILE:" in row["marker"]]
    rpcs = [row for row in rows if "RPC:" in row["marker"]]
    balanced = []
    while files or rpcs:
        if files:
            balanced.append(files.pop(0))
        if rpcs:
            balanced.append(rpcs.pop(0))
    return [[selector(row, kind)] for row in balanced
            for kind in (FILE_KINDS if "FILE:" in row["marker"] else RPC_KINDS)]


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


def summarize_case(case_id: str, sequence: list[dict], trace: list[dict],
                   manifest: dict, state: dict, run: Path,
                   exact: bool, applied: list[dict], run_coverage: dict[str, set[str]]) -> dict:
    last_fault = applied[-1]["seq"] if exact else None
    post_checks = [row for row in checks(trace, case_id)
                   if last_fault is not None and row["seq"] > last_fault]
    throws = [row for row in trace if row["event"] == "TARGET_THROW"
              and row.get("caseId") == case_id and row.get("exception") == "java.io.IOException"
              and last_fault is not None and row["seq"] > last_fault]
    valid = exact and bool(post_checks)
    expected = bool(valid and throws and all(
        row.get("message", "").startswith(CASES[case_id]["expected_message"]) for row in throws))
    gains = {name: len(run_coverage[name] - set(state["coverage"][case_id][name])) if valid else 0
             for name in COVERAGE}
    observed = families(trace)
    return {"sequence": sequence, "elapsed_seconds": manifest["elapsed_seconds"],
            "junit_exit": manifest["returncode"], "exact_order_applied": exact,
            "requested_faults": len(sequence), "matched_faults": sum(
                row["event"] == "FAULT_MATCHED" for row in trace), "applied_faults": len(applied),
            "target_after_fault": bool(post_checks), "post_fault_target_checks": len(post_checks),
            "target_exception_after_fault": len(throws), "target_exception_events": throws,
            "target_exception_classification": "expected_incompatible_version_guard" if expected
            else ("candidate_needs_replay_source_review" if throws else "none"),
            "valid_for_feedback": valid, "coverage_gain": gains,
            "coverage_total": {name: len(run_coverage[name]) for name in COVERAGE},
            "new_io_families": len(observed - set(state["io_families"][case_id])) if valid else 0,
            "bug_mark": "candidate_needs_replay_source_review" if valid and throws and not expected else "none",
            "manifest": str(run / "manifest.json"), "trace": str(run / "runtime_trace.jsonl"),
            "log": str(run / "junit.log")}


def update_results(state: dict) -> None:
    for case_id, case in CASES.items():
        result_path = case["directory"] / "result.json"
        old = json.loads(result_path.read_text())
        trials = [state["completed"][identity][case_id]
                  for identity in state["completion_order"]]
        reached = state["healthy"][case_id]["target_checks"] > 0
        valid = [trial for trial in trials if trial["valid_for_feedback"]]
        status = "running" if reached and len(trials) < state["budget"]["max_trials"] and state["queue"] \
            else ("pending_budget_review" if reached else "target_not_reached_in_original_junit")
        old.pop("reason", None)
        if status == "running":
            old.pop("completed_at_utc", None)
        old.update(status=status, methodology="independent_coverage_io_original_junit_shared_run",
                   target_source_file="hadoop-hdfs/src/main/java/org/apache/hadoop/hdfs/server/datanode/"
                       + case["source_file"],
                   target_source_line=case["line"],
                   target_guard_line=case["guard_line"],
                   target_function=case["source_file"].removesuffix(".java") + "." + case["function"]
                       + ("(NamespaceInfo,StorageLocation,StartupOption,List,Configuration)"
                          if case_id == "HDFS-25" else
                          "(StorageDirectory,NamespaceInfo,StartupOption,List,Configuration)"),
                   target_code=case["code"],
                   cluster_test="org.apache.hadoop.hdfs.TestDFSStartupVersions#testVersions",
                   shared_run_case_ids=list(CASES),
                   instrumentation_provenance={
                       "runtime_hooks": "case_local_offline_asm_9_6_overlay",
                       "coverage": "jacoco_0_8_15_original_hdfs_ipc_classes",
                       "coverage_filter": "exclude_runtime_generated_MockitoMock_classes",
                       "junit": "original_hadoop_3_4_3_test_jar_and_native_fixture",
                       "graphchecker_prewoven": False, "graphchecker_runtime_jar": False,
                       "region_skeleton": False, "static_io_map": False,
                       "causal_graph_or_closure": False,
                       "io_selection": "observed_original_junit_io_plus_production_coverage_feedback"},
                   target_reached=reached,
                   elapsed_seconds=round(state["setup_elapsed_seconds"] + sum(
                       trial["elapsed_seconds"] for trial in trials), 3),
                   fault_trials=len(trials), strict_injections=sum(t["exact_order_applied"] for t in trials),
                   fully_applied_trials=sum(t["exact_order_applied"] for t in trials),
                   target_after_fault=len(valid),
                   target_exception_after_fault=sum(t["target_exception_after_fault"] for t in trials),
                   expected_guard_response_trials=sum(t["target_exception_classification"] ==
                       "expected_incompatible_version_guard" for t in trials),
                   coverage_gain=len(state["coverage"][case_id]["branch_counts"])
                       - state["healthy"][case_id]["branch_count"],
                   bug_mark="candidate_needs_replay_source_review" if any(t["bug_mark"] != "none"
                       for t in trials) else "none",
                   evidence=os.path.relpath(STATE, case["directory"]),
                   healthy=state["healthy"][case_id], budget=state["budget"],
                   coverage={name: len(values) for name, values in state["coverage"][case_id].items()},
                   io_families=len(state["io_families"][case_id]), trial_results=trials)
        atomic_json(result_path, old)


def mutate(trace: list[dict], sequence: list[dict], max_faults: int) -> list[list[dict]]:
    if len(sequence) >= max_faults:
        return []
    exact, applied = exact_applied(sequence, trace)
    if not exact:
        return []
    targets = [row for case_id in CASES for row in checks(trace, case_id)]
    rows = selectable_io(trace, applied[-1]["seq"])
    rows.sort(key=lambda row: (0 if "FILE:" in row["marker"] else 1,
                               distance(row, targets), row["seq"]))
    return [sequence + [selector(row, (FILE_KINDS if "FILE:" in row["marker"]
                                      else RPC_KINDS)[len(sequence) % (2 if "FILE:" in row["marker"] else 3)])]
            for row in rows]


def choose(queue: list[list[dict]], completed: int,
           early_hdfs34: dict[tuple[str, str, str, int], int],
           valid_hdfs34_prefixes: set[tuple[tuple[str, str, str, int, str], ...]]) -> int:
    if 60 <= completed < 75:
        # HDFS-34 is checked in earlier VERSION variants than the other four
        # targets. Reserve a slice of the shared budget for still-untried
        # combinations descended from trials that actually retained it.
        # Healthy global event order alone is unstable across threads.
        retained_prefix = [i for i, sequence in enumerate(queue)
                           if len(sequence) == 2
                           and sequence_fingerprint(sequence[:-1]) in valid_hdfs34_prefixes
                           and sequence[-1]["sourceKey"] == "Thread-N"
                           and sequence[-1]["hitOrdinal"] <= 12]
        if retained_prefix:
            return min(retained_prefix, key=lambda i: (
                queue[i][0]["sourceKey"] != "Thread-N",
                queue[i][-1]["hitOrdinal"], i))
        # Also try the remaining healthy points near HDFS-34. Each trial's
        # actual post-fault target event, never the healthy timestamp, decides
        # whether the result contributes feedback.
        early = [i for i, sequence in enumerate(queue) if len(sequence) == 1
                 and "RPC:" in sequence[0]["marker"]
                 and tuple(sequence[0][field] for field in
                           ("marker", "siteId", "sourceKey", "hitOrdinal"))
                 in early_hdfs34]
        if early:
            return min(early, key=lambda i: (
                early_hdfs34[tuple(queue[i][0][field] for field in
                                   ("marker", "siteId", "sourceKey", "hitOrdinal"))], i))
    if completed >= 24 and completed % 3 == 0:
        deep = [i for i, item in enumerate(queue) if len(item) >= 2]
        if deep:
            def stable_family(sequence: list[dict]) -> int:
                first = sequence[0]
                identity = (first["marker"], first["siteId"], first["sourceKey"])
                same_source = all((fault["marker"], fault["siteId"], fault["sourceKey"])
                                  == identity for fault in sequence)
                increasing = all(left["hitOrdinal"] < right["hitOrdinal"]
                                 for left, right in zip(sequence, sequence[1:]))
                if same_source and increasing:
                    return 2 if "RPC:" in first["marker"] else 1
                return 0

            # Cross-thread file/RPC events can swap their order even when
            # both selectors match. Prefer stable source-local I/O chains,
            # while every third deep selection still samples other chains.
            if completed % 9 != 0:
                return max(deep, key=lambda i: (stable_family(queue[i]),
                                                len(queue[i]), -i))
            return max(deep, key=lambda i: (len(queue[i]), -i))
    files = [i for i, item in enumerate(queue) if "FILE:" in item[-1]["marker"]]
    rpcs = [i for i, item in enumerate(queue) if "RPC:" in item[-1]["marker"]]
    # File failures often abort the original version-test loop before any
    # check. Retain some file exploration, but favor the RPC family that has
    # repeatedly preserved all five exact target checks after the fault.
    if completed % 3 != 2 and rpcs:
        return min(rpcs, key=lambda i: (len(queue[i]), i))
    if files:
        return min(files, key=lambda i: (len(queue[i]), i))
    return min(rpcs, key=lambda i: (len(queue[i]), i)) if rpcs else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-trials", type=int, default=80)
    parser.add_argument("--max-faults", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=360)
    args = parser.parse_args()
    healthy_manifest = json.loads((HEALTHY / "manifest.json").read_text())
    healthy_trace = events(HEALTHY / "runtime_trace.jsonl")
    if healthy_manifest["returncode"] != 0 or not any(checks(healthy_trace, c) for c in CASES):
        raise SystemExit("Healthy original JUnit/selected target not established")
    last_hdfs34 = max(row["seq"] for row in checks(healthy_trace, "HDFS-34"))
    early_hdfs34 = {
        tuple(row[field] for field in ("marker", "siteId", "sourceKey", "hitOrdinal")):
        row["seq"] for row in healthy_trace
        if row["event"] == "FAULT_POINT_OBSERVED" and row["seq"] < last_hdfs34}
    if STATE.is_file():
        state = json.loads(STATE.read_text())
        if set(state.get("completion_order", [])) != set(state["completed"]):
            raise SystemExit("Completion order missing or inconsistent in checkpoint")
        old_max = state["budget"]["max_faults"]
        state["budget"] = {"max_trials": args.max_trials, "max_faults": args.max_faults}
        if "current" in state and state["current"]["id"] not in state["completed"]:
            state["queue"].insert(0, state["current"]["sequence"])
            state.pop("current")
        if state.get("selection_revision") != "after_compatible_versions_v4":
            useful_start = next((row["seq"] for row in healthy_trace
                                 if row["event"] == "FAULT_POINT_OBSERVED"
                                 and row["siteId"] == "DataStorage.readProperties"
                                 and row["sourceKey"] == "dfs/data1"
                                 and row["hitOrdinal"] == 4), -1)
            if useful_start < 0:
                raise SystemExit("Fourth DataNode VERSION read missing from healthy trace")
            first_fault_seq = {(row["marker"], row["siteId"], row["sourceKey"],
                                row["hitOrdinal"]): row["seq"]
                               for row in healthy_trace if row["event"] == "FAULT_POINT_OBSERVED"}
            state["queue"] = [seq for seq in state["queue"] if seq
                              and "datanodeMaster" not in seq[0]["sourceKey"]
                              and first_fault_seq.get((seq[0]["marker"], seq[0]["siteId"],
                                                       seq[0]["sourceKey"], seq[0]["hitOrdinal"]),
                                                      -1) >= useful_start]
            state["selection_revision"] = "after_compatible_versions_v4"
        if args.max_faults > old_max:
            seen = set(state["completed"]) | {sequence_id(s) for s in state["queue"]}
            for item in state["completed"].values():
                sequence = item["HDFS-22"]["sequence"]
                if not any(item[c]["valid_for_feedback"] for c in CASES) or len(sequence) < old_max:
                    continue
                for candidate in mutate(events(Path(item["HDFS-22"]["trace"])), sequence, args.max_faults):
                    identity = sequence_id(candidate)
                    if identity not in seen:
                        state["queue"].append(candidate)
                        seen.add(identity)
    else:
        baseline = {name: sorted(covered(HEALTHY, name)) for name in COVERAGE}
        base_families = sorted(families(healthy_trace))
        state = {"case_ids": list(CASES),
                 "budget": {"max_trials": args.max_trials, "max_faults": args.max_faults},
                 "healthy": {c: {"elapsed_seconds": healthy_manifest["elapsed_seconds"],
                                  "junit_exit": 0, "target_checks": len(checks(healthy_trace, c)),
                                  "target_exceptions": sum(row["event"] == "TARGET_THROW"
                                      and row.get("caseId") == c for row in healthy_trace),
                                  "branch_count": len(baseline["branch_counts"]),
                                  "io_points": sum(row["event"] == "FAULT_POINT_OBSERVED"
                                      for row in healthy_trace)} for c in CASES},
                 "queue": initial_queue(healthy_trace), "completed": {},
                 "completion_order": [],
                 "selection_revision": "after_compatible_versions_v4",
                 "coverage": {c: dict(baseline) for c in CASES},
                 "io_families": {c: base_families for c in CASES},
                 "setup_elapsed_seconds": healthy_manifest["elapsed_seconds"]}
    atomic_json(STATE, state)
    update_results(state)
    while len(state["completed"]) < args.max_trials and state["queue"]:
        valid_hdfs34_prefixes = {
            sequence_fingerprint(item["HDFS-34"]["sequence"])
            for item in state["completed"].values()
            if item["HDFS-34"]["valid_for_feedback"]}
        sequence = state["queue"].pop(choose(state["queue"], len(state["completed"]),
                                             early_hdfs34, valid_hdfs34_prefixes))
        identity = sequence_id(sequence)
        if identity in state["completed"]:
            continue
        root = EVIDENCE / "runs" / identity
        root.mkdir(parents=True, exist_ok=True)
        state["current"] = {"id": identity, "sequence": sequence, "started_unix": time.time()}
        atomic_json(STATE, state)
        summary = None
        for attempt in (1, 2):
            run = root / ("attempt-" + str(attempt))
            run.mkdir(parents=True, exist_ok=True)
            plan = run / "faults.tsv"
            plan.write_text(plan_text(sequence))
            if not (run / "manifest.json").is_file():
                with (run / "runner-console.log").open("w") as log:
                    subprocess.run([sys.executable, str(RUNNER), "--output", str(run),
                                    "--plan", str(plan), "--timeout", str(args.timeout)],
                                   stdout=log, stderr=subprocess.STDOUT, check=False)
            if not (run / "manifest.json").is_file():
                raise RuntimeError("Missing trial manifest " + identity)
            manifest = json.loads((run / "manifest.json").read_text())
            trace = events(run / "runtime_trace.jsonl")
            exact, applied = exact_applied(sequence, trace)
            run_coverage = {name: covered(run, name) for name in COVERAGE}
            summary = {c: summarize_case(c, sequence, trace, manifest, state,
                                         run, exact, applied, run_coverage) for c in CASES}
            for row in summary.values():
                row["attempt"] = attempt
            if exact:
                break
        assert summary is not None
        state["completed"][identity] = summary
        state["completion_order"].append(identity)
        trace = events(Path(summary["HDFS-22"]["trace"]))
        run = Path(summary["HDFS-22"]["manifest"]).parent
        for case_id in CASES:
            if summary[case_id]["valid_for_feedback"]:
                for name in COVERAGE:
                    state["coverage"][case_id][name] = sorted(
                        set(state["coverage"][case_id][name]) | covered(run, name))
                state["io_families"][case_id] = sorted(
                    set(state["io_families"][case_id]) | families(trace))
        if any(summary[c]["valid_for_feedback"] for c in CASES):
            new = mutate(trace, sequence, args.max_faults)
            seen = set(state["completed"]) | {sequence_id(item) for item in state["queue"]}
            new = [item for item in new if sequence_id(item) not in seen]
            if any(summary[c]["new_io_families"] or any(summary[c]["coverage_gain"].values())
                   for c in CASES):
                state["queue"] = new + state["queue"]
            else:
                state["queue"].extend(new)
        state.pop("current", None)
        atomic_json(STATE, state)
        update_results(state)
        print(json.dumps({"completed": len(state["completed"]), "id": identity,
                          "applied": summary["HDFS-22"]["applied_faults"],
                          "target_after": {c: summary[c]["target_after_fault"] for c in CASES},
                          "candidate": {c: summary[c]["bug_mark"] for c in CASES}}), flush=True)


if __name__ == "__main__":
    main()
