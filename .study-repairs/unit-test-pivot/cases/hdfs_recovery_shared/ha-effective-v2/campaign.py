#!/usr/bin/env python3
"""Resumable, target-retaining I/O exception fuzzing of an original HA JUnit.

The selected I/O calls and target visits come only from this run's trace.  No
static or dynamic causal graph participates in sequence generation.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time


HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_original.py"
STATE = HERE / "checkpoint.json"
LOCK = HERE / "campaign.lock"
START_LOCK = HERE.parents[2] / "jvm-start.lock"
HEALTHY = (HERE / "healthy-a", HERE / "healthy-b")
CASES = ("HDFS-28", "HDFS-29", "HDFS-30")
SITES = {
    "HDFS-28": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocol.DatanodeID getDatanodeID(java.lang.String)>#u12",
    "HDFS-29": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>#u12",
    "HDFS-30": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>#u23",
}
COVERAGE = ("probes", "methods", "branch_counts")
RPC_ERRORS = ("IOException", "EOFException", "SocketTimeoutException")
FILE_ERRORS = ("IOException", "FileNotFoundException")
BASE, EXTENDED = 80, 128
BASE_DEPTH, EXTENDED_DEPTH = 8, 10
BASE_ATTEMPTS, EXTENDED_ATTEMPTS = 320, 512
MAX_JAVA_BEFORE_START = 4
MIN_FREE_BYTES = 8 * 1024**3


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".tmp")
    pending.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    pending.replace(path)


def write_summary(state: dict) -> None:
    valid = effective(state)
    fault_seconds = sum(row["elapsed_seconds"] for row in state["completed"])
    result = {
        "schema": 1, "updated_at_utc": utc(), "test": state["test"],
        "healthy_seconds": round(sum(row["seconds"] for row in state["healthy"]), 3),
        "fault_junit_seconds": round(fault_seconds, 3),
        "attempts": len(state["completed"]),
        "exact_full_sequence": sum(bool(row["exact_order_applied"])
                                   for row in state["completed"]),
        "max_faults": state["max_faults"], "attempt_cap": state["attempt_cap"],
        "stop_reason": state["stop_reason"],
        "cases": {case: {
            "effective": len(valid[case]), "goal": state["goals"][case],
            "target_exception_candidates": sum(
                row["target_exceptions_after_fault"][case]
                for row in state["completed"]),
            "coverage_gain": {metric: len(set(state["coverage"][case][metric])
                                          - set(state["healthy_coverage"][metric]))
                              for metric in COVERAGE},
        } for case in CASES},
        "checkpoint": str(STATE),
    }
    atomic_json(HERE / "summary.json", result)
    path = HERE / "trial-ledger.csv"
    pending = path.with_name(path.name + ".tmp")
    with pending.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("trial", "case", "sequence_id", "last_fault_site",
                         "last_fault_source", "last_fault_occurrence", "requested_faults",
                         "seconds", "junit_exit", "exact_injection",
                         "postfault_target_checks", "target_ioexception",
                         "new_probes", "new_methods", "new_branch_counts",
                         "new_io_families", "run"))
        for index, row in enumerate(state["completed"], 1):
            for case in CASES:
                last = row["sequence"][-1]
                writer.writerow((index, case, row["id"], last["siteId"],
                                 last["sourceKey"], last["occurrenceAddress"],
                                 row["requested_faults"],
                                 row["elapsed_seconds"], row["junit_exit"],
                                 row["exact_order_applied"],
                                 row["post_fault_target_checks"][case],
                                 row["target_exceptions_after_fault"][case],
                                 row["coverage_gain"][case]["probes"],
                                 row["coverage_gain"][case]["methods"],
                                 row["coverage_gain"][case]["branch_counts"],
                                 len(row["new_io_families"][case]), row["run"]))
    pending.replace(path)


def trace(run: Path) -> list[dict]:
    return [json.loads(line) for line in (run / "runtime_trace.jsonl").read_text().splitlines()
            if line]


def covered(run: Path, category: str) -> set[str]:
    path = run / ("covered_" + category + ".txt")
    return set(path.read_text().splitlines()) if path.is_file() else set()


def root(event: dict) -> str:
    value = event.get("occurrenceAddress", "")
    return value.split("/rpc:", 1)[0].split("/server:", 1)[0]


def origin(event: dict) -> str:
    return event.get("originSourceKey", event.get("sourceKey", ""))


def same_owner(event: dict, check: dict) -> bool:
    return (check.get("sourceKey") == origin(event)
            and check.get("occurrenceAddress") == root(event)
            and check.get("blockId") == event.get("blockId")
            and (event.get("recoveryId") is None
                 or check.get("recoveryId") == event.get("recoveryId")))


def later_targets(event: dict, events: list[dict]) -> tuple[str, ...]:
    return tuple(case for case in CASES if any(
        check.get("event") == "TARGET_CHECK" and check.get("caseId") == case
        and check.get("siteId") == SITES[case]
        and check.get("seq", -1) > event.get("seq", -1)
        and same_owner(event, check) for check in events))


def point(event: dict, kind: str) -> dict:
    keys = ("marker", "siteId", "sourceKey", "occurrenceAddress",
            "hitOrdinal", "requestApi", "filePhase")
    return {**{key: event.get(key, "") for key in keys},
            "originSourceKey": origin(event), "faultType": kind}


def kinds(event: dict) -> tuple[str, ...]:
    return FILE_ERRORS if event["marker"].startswith("FAULT:HDFS_FILE:") else RPC_ERRORS


def identity(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()[:24]


def family(event: dict) -> str:
    return "|".join(str(value) for value in
                    (event.get("marker", ""), event.get("siteId", ""),
                     event.get("sourceKey", ""), origin(event),
                     event.get("requestApi", ""), event.get("filePhase", "")))


def add(state: dict, sequence: list[dict], priority: int = 0,
        eligible: tuple[str, ...] = ()) -> None:
    key = identity(sequence)
    if key in state["seen"]:
        return
    state["seen"].append(key)
    state["queue"].append({"id": key, "sequence": sequence,
                           "priority": priority, "eligible": eligible,
                           "created": time.time(), "retries": 0})


def verify_healthy(directory: Path) -> list[dict]:
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest["returncode"] != 0 or not manifest["instrumented"]
            or manifest.get("graphchecker_runtime_used") is not False
            or manifest.get("test") !=
            "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization"):
        raise RuntimeError("invalid original-JUnit healthy seed: " + str(directory))
    events = trace(directory)
    if any(event.get("event") == "TARGET_THROW" for event in events):
        raise RuntimeError("healthy target exception: " + str(directory))
    if not any(event.get("event") == "CLUSTER_REGISTER"
               and event.get("dataNodes") == 3 for event in events):
        raise RuntimeError("HA healthy seed lacked the three-DataNode cluster")
    if not any(event.get("event") == "RECOVERY_BEGIN"
               and event.get("sourceKey") not in (None, "unregistered") for event in events):
        raise RuntimeError("HA healthy seed lacked a physical recovery owner")
    for case in CASES:
        checks = [event for event in events if event.get("event") == "TARGET_CHECK"
                  and event.get("caseId") == case and event.get("siteId") == SITES[case]]
        if not checks or any(event.get("outcome") is not False or
                             event.get("sourceKey") == "unregistered" for event in checks):
            raise RuntimeError("healthy seed missed nonfatal " + case)
    for category in COVERAGE:
        if not (directory / ("covered_" + category + ".txt")).is_file():
            raise RuntimeError("healthy seed missing production coverage " + category)
    return events


def start_state() -> dict:
    baseline = {name: set() for name in COVERAGE}
    io = set()
    sources = []
    state = {"schema": 2, "test":
             "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization",
             "cases": CASES, "healthy": [], "healthy_coverage": {},
             "coverage": {}, "io_families": {}, "queue": [], "seen": [],
             "completed": [], "active": None, "started_at_utc": utc(),
             "goals": {case: BASE for case in CASES}, "extensions": {},
             "stop_reason": None, "attempt_cap": BASE_ATTEMPTS,
             "max_faults": BASE_DEPTH}
    for directory in HEALTHY:
        events = verify_healthy(directory)
        manifest = json.loads((directory / "manifest.json").read_text())
        state["healthy"].append({"run": str(directory),
                                 "seconds": manifest["elapsed_seconds"],
                                 "trace_sha256": hashlib.sha256(
                                     (directory / "runtime_trace.jsonl").read_bytes()).hexdigest()})
        sources.append(events)
        for category in COVERAGE:
            baseline[category] |= covered(directory, category)
        for event in events:
            if event.get("event") != "FAULT_POINT_OBSERVED" or not event.get("marker", "").startswith("FAULT:"):
                continue
            io.add(family(point(event, "")))
            eligible = later_targets(event, events)
            if not eligible:
                continue
            for kind in kinds(event):
                add(state, [point(event, kind)], eligible=eligible)
    if not state["queue"]:
        raise RuntimeError("two HA healthy traces contained no observed pre-target I/O")
    state["healthy_coverage"] = {name: sorted(values) for name, values in baseline.items()}
    state["coverage"] = {case: {name: sorted(values) for name, values in baseline.items()}
                         for case in CASES}
    state["io_families"] = {case: sorted(io) for case in CASES}
    state["initial_queue"] = len(state["queue"])
    atomic_json(STATE, state)
    write_summary(state)
    return state


def event_matches(event: dict, selected: dict, index: int) -> bool:
    return (event.get("planIndex") == index
            and origin(event) == selected["originSourceKey"]
            and all(event.get(key, "") == selected[key] for key in
                    ("marker", "siteId", "sourceKey", "occurrenceAddress",
                     "hitOrdinal", "requestApi", "filePhase", "faultType")))


def identity_verified(events: list[dict], event: dict) -> bool:
    owner = origin(event)
    if owner in ("", "unregistered", "unknown-origin") or not root(event):
        return False
    if not any(row.get("event") == "RECOVERY_BEGIN" and
               row.get("seq", -1) < event.get("seq", -1)
               and row.get("sourceKey") == owner and
               row.get("occurrenceAddress") == root(event) and
               row.get("blockId") == event.get("blockId") and
               (event.get("recoveryId") is None or
                row.get("recoveryId") == event.get("recoveryId"))
               for row in events):
        return False
    if not event.get("marker", "").startswith("FAULT:HDFS_FILE:"):
        return True
    if event.get("filePhase") not in ("initReplicaRecovery", "updateReplicaUnderRecovery"):
        return False
    if (event["filePhase"] == "updateReplicaUnderRecovery" and
            event["sourceKey"] != owner):
        return False
    return any(row.get("event") == "SERVER_RECOVERY_BEGIN" and
               row.get("seq", -1) < event.get("seq", -1)
               and row.get("sourceKey") == event.get("sourceKey")
               and row.get("originSourceKey") == owner
               and row.get("blockId") == event.get("blockId")
               and row.get("recoveryId") == event.get("recoveryId")
               for row in events)


def evaluate(directory: Path, sequence: list[dict], state: dict) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    events = trace(directory)
    matched = [event for event in events if event.get("event") == "FAULT_MATCHED"]
    applied = [event for event in events if event.get("event") == "FAULT_APPLIED"]
    exact = (len(matched) == len(applied) == len(sequence)
             and all(event_matches(matched[i], sequence[i], i)
                     and event_matches(applied[i], sequence[i], i)
                     and matched[i]["seq"] < applied[i]["seq"]
                     and identity_verified(events, applied[i])
                     for i in range(len(sequence)))
             and all(applied[i]["seq"] < matched[i + 1]["seq"]
                     for i in range(len(sequence) - 1)))
    last = applied[-1] if exact else None
    after, thrown = {}, {}
    for case in CASES:
        checks = [event for event in events if event.get("event") == "TARGET_CHECK"
                  and event.get("caseId") == case and event.get("siteId") == SITES[case]
                  and last is not None and event.get("seq", -1) > last["seq"]
                  and same_owner(last, event)]
        after[case] = len(checks)
        thrown[case] = sum(event.get("event") == "TARGET_THROW"
                           and event.get("caseId") == case
                           and event.get("siteId") == SITES[case]
                           and event.get("runtimeType") == "java.io.IOException"
                           and event.get("sourceKey") == origin(last)
                           and event.get("occurrenceAddress") == root(last)
                           and event.get("blockId") == last.get("blockId")
                           and event.get("seq", -1) > last["seq"]
                           and any(check.get("outcome") is True and
                                   check["seq"] < event["seq"] for check in checks)
                           for event in events) if last is not None else 0
    all_coverage = {category: covered(directory, category) for category in COVERAGE}
    gain = {case: {category: len(all_coverage[category]
                                  - set(state["coverage"][case][category]))
                   if after[case] else 0 for category in COVERAGE} for case in CASES}
    families = {family(event) for event in events
                if event.get("event") == "FAULT_POINT_OBSERVED"
                and event.get("marker", "").startswith("FAULT:")}
    new_io = {case: sorted(families - set(state["io_families"][case]))
              if after[case] else [] for case in CASES}
    return {"id": identity(sequence), "sequence": sequence, "run": str(directory),
            "junit_exit": manifest["returncode"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "requested_faults": len(sequence), "matched_faults": len(matched),
            "applied_faults": len(applied), "exact_order_applied": exact,
            "runtime_identity_verified": exact,
            "post_fault_target_checks": after,
            "target_exceptions_after_fault": thrown,
            "coverage_gain": gain, "new_io_families": new_io,
            "last_applied_seq": last["seq"] if last else None,
            "candidate_needs_review": any(thrown.values()),
            "raw_trace_sha256": hashlib.sha256(
                (directory / "runtime_trace.jsonl").read_bytes()).hexdigest()}


def admit(state: dict, trial: dict) -> None:
    if not trial["exact_order_applied"]:
        return
    directory = Path(trial["run"])
    events = trace(directory)
    for case in CASES:
        if not trial["post_fault_target_checks"][case]:
            continue
        for category in COVERAGE:
            state["coverage"][case][category] = sorted(
                set(state["coverage"][case][category]) | covered(directory, category))
        state["io_families"][case] = sorted(
            set(state["io_families"][case]) |
            {family(event) for event in events
             if event.get("event") == "FAULT_POINT_OBSERVED"
             and event.get("marker", "").startswith("FAULT:")})
    if len(trial["sequence"]) >= state["max_faults"]:
        return
    for event in events:
        if (event.get("event") != "FAULT_POINT_OBSERVED" or
                not event.get("marker", "").startswith("FAULT:") or
                event.get("seq", -1) <= trial["last_applied_seq"] or
                origin(event) != origin(trial["sequence"][-1]) or
                root(event) != root(trial["sequence"][-1])):
            continue
        eligible = later_targets(event, events)
        if not eligible:
            continue
        for kind in kinds(event):
            selected = point(event, kind)
            if selected in trial["sequence"]:
                continue
            priority = (sum(trial["coverage_gain"][case]["methods"]
                            + trial["coverage_gain"][case]["branch_counts"]
                            for case in eligible)
                        + 10 * sum(bool(trial["new_io_families"][case]) for case in eligible)
                        + 3 * len(trial["sequence"]))
            add(state, trial["sequence"] + [selected], priority, eligible)


def effective(state: dict) -> dict[str, list[dict]]:
    return {case: [trial for trial in state["completed"]
                   if trial["exact_order_applied"] and
                   trial["post_fault_target_checks"][case]] for case in CASES}


def update_budget(state: dict) -> None:
    valid = effective(state)
    for case in CASES:
        if len(valid[case]) < BASE or case in state["extensions"]:
            continue
        tail = valid[case][BASE - 8:BASE]
        novelty = any(trial["coverage_gain"][case]["methods"] or
                      trial["coverage_gain"][case]["branch_counts"] or
                      trial["new_io_families"][case] for trial in tail)
        state["extensions"][case] = {"decision_at_trial": len(state["completed"]),
                                      "last_eight_run_ids": [t["id"] for t in tail],
                                      "novelty": bool(novelty)}
        if novelty:
            state["goals"][case] = EXTENDED
            state["attempt_cap"] = EXTENDED_ATTEMPTS
            if state["max_faults"] < EXTENDED_DEPTH:
                state["max_faults"] = EXTENDED_DEPTH
                # Depth-eight executions were terminal under the base budget.
                # Re-open their observed post-fault I/O when depth ten becomes
                # available, while sequence IDs still prevent duplicate runs.
                for prior in state["completed"]:
                    if prior["exact_order_applied"] and len(prior["sequence"]) == BASE_DEPTH:
                        admit(state, prior)


def stop_reason(state: dict) -> str | None:
    if any(any(trial["target_exceptions_after_fault"].values())
           for trial in state["completed"]):
        return "candidate_requires_replay_and_source_review"
    counts = effective(state)
    if all(len(counts[case]) >= state["goals"][case] for case in CASES):
        return "effective_budget_met_pending_independent_audit"
    if len(state["completed"]) >= state["attempt_cap"]:
        return "attempt_cap_inconclusive"
    if not state["queue"] and state["active"] is None:
        return "queue_exhausted_inconclusive"
    return None


def choose(state: dict) -> int:
    completed = state["completed"]
    counts = effective(state)
    deficit = {case for case in CASES if len(counts[case]) < state["goals"][case]}
    types = Counter(t["sequence"][-1]["faultType"] for t in completed)
    families = Counter(family(t["sequence"][-1]) for t in completed)
    return max(range(len(state["queue"])), key=lambda i: (
        len(deficit.intersection(state["queue"][i]["eligible"])),
        -types[state["queue"][i]["sequence"][-1]["faultType"]],
        -families[family(state["queue"][i]["sequence"][-1])],
        min(len(state["queue"][i]["sequence"]), 6),
        state["queue"][i]["priority"],
        -state["queue"][i]["created"],
        -i))


def java_count() -> int:
    result = subprocess.run(["pgrep", "-c", "java"], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    return int(result.stdout.strip() or "0")


def child_java_started(directory: Path) -> bool:
    needle = str(directory).encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            value = (proc / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if b"/java\0" in value and needle in value:
            return True
    return False


def previous_runner_alive(directory: Path) -> bool:
    needle = str(directory).encode()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            value = (proc / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if b"run_original.py" in value and needle in value:
            return True
    return False


def launch(directory: Path, args: list[str]) -> bool:
    """Share the launch gate; release it after this trial's JVM appears."""
    with START_LOCK.open("a+") as gate:
        fcntl.flock(gate, fcntl.LOCK_EX)
        if java_count() > MAX_JAVA_BEFORE_START or shutil.disk_usage(HERE).free < MIN_FREE_BYTES:
            return False
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                with (directory / "driver.log").open("w") as out:
                    subprocess.run([sys.executable, str(RUNNER), *args], cwd=HERE,
                                   stdout=out, stderr=subprocess.STDOUT, check=False)
            except BaseException as error:
                errors.append(error)

        job = threading.Thread(target=worker)
        job.start()
        while job.is_alive() and not child_java_started(directory):
            time.sleep(0.2)
    job.join()
    if errors:
        raise errors[0]
    if not (directory / "manifest.json").is_file():
        raise RuntimeError("JUnit runner ended without a manifest: " + str(directory))
    return True


def calibrate() -> bool:
    for directory in HEALTHY:
        directory.mkdir(parents=True, exist_ok=True)
        if not (directory / "manifest.json").is_file():
            if previous_runner_alive(directory):
                return False
            if not launch(directory, ["--instrument", "--output", str(directory),
                                      "--timeout", "180"]):
                return False
        verify_healthy(directory)
    return True


def run_trial(state: dict) -> bool:
    if state["active"] is None:
        state["active"] = state["queue"].pop(choose(state))
        atomic_json(STATE, state)
    item = state["active"]
    directory = HERE / "runs" / ("trial-%04d" % (len(state["completed"]) + 1))
    directory.mkdir(parents=True, exist_ok=True)
    plan = directory / "fault-plan.tsv"
    contents = "".join("\t".join(str(fault[key]) for key in
                                   ("marker", "siteId", "sourceKey",
                                    "occurrenceAddress", "hitOrdinal", "faultType"))
                       + "\t" + fault["filePhase"] + "\n"
                       for fault in item["sequence"])
    if not plan.exists():
        temporary = plan.with_name(plan.name + ".tmp")
        temporary.write_text(contents)
        temporary.replace(plan)
    elif plan.read_text() != contents:
        raise RuntimeError("saved fault plan differs from active checkpoint")
    if not (directory / "manifest.json").is_file():
        if previous_runner_alive(directory):
            return False
        if not launch(directory, ["--instrument", "--plan", str(plan),
                                  "--output", str(directory), "--timeout", "180"]):
            return False
    trial = evaluate(directory, item["sequence"], state)
    trial["retries"] = item["retries"]
    state["completed"].append(trial)
    admit(state, trial)
    if not trial["exact_order_applied"] and item["retries"] < 2:
        state["queue"].append({**item, "retries": item["retries"] + 1,
                               "created": time.time()})
    state["active"] = None
    update_budget(state)
    state["stop_reason"] = stop_reason(state)
    atomic_json(STATE, state)
    write_summary(state)
    print(json.dumps({"trial": len(state["completed"]), "exact": trial["exact_order_applied"],
                      "effective": {case: len(rows) for case, rows in effective(state).items()},
                      "candidate": trial["candidate_needs_review"],
                      "stop_reason": state["stop_reason"]}), flush=True)
    return True


def preview() -> dict:
    if not STATE.is_file():
        return {"state": "awaiting_two_fresh_original_JUnit_calibrations",
                "healthy_existing": [path.joinpath("manifest.json").is_file()
                                     for path in HEALTHY]}
    state = json.loads(STATE.read_text())
    return {"completed": len(state["completed"]),
            "effective": {case: len(rows) for case, rows in effective(state).items()},
            "goals": state["goals"], "queue": len(state["queue"]),
            "active": state["active"] is not None,
            "attempt_cap": state["attempt_cap"], "max_faults": state["max_faults"],
            "stop_reason": state["stop_reason"],
            "checkpoint_sha256": hashlib.sha256(STATE.read_bytes()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--max-new-attempts", type=int, default=0)
    parser.add_argument("--wall-seconds", type=int, default=24 * 3600)
    parser.add_argument("--poll-seconds", type=int, default=20)
    args = parser.parse_args()
    if args.preview:
        print(json.dumps(preview(), sort_keys=True))
        return
    if not args.run:
        parser.error("choose --preview or --run")
    deadline = time.monotonic() + args.wall_seconds
    with LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not STATE.exists() and not calibrate():
            print("resource gate deferred healthy calibration", flush=True)
            return
        state = json.loads(STATE.read_text()) if STATE.exists() else start_state()
        write_summary(state)
        new = 0
        while time.monotonic() < deadline:
            reason = stop_reason(state)
            if reason:
                state["stop_reason"] = reason
                atomic_json(STATE, state)
                write_summary(state)
                print("terminal " + reason, flush=True)
                return
            if run_trial(state):
                new += 1
                if args.max_new_attempts and new >= args.max_new_attempts:
                    print("bounded run ended at atomic checkpoint", flush=True)
                    return
            else:
                time.sleep(args.poll_seconds)
        print("wall cap reached; resume this checkpoint", flush=True)


if __name__ == "__main__":
    main()
