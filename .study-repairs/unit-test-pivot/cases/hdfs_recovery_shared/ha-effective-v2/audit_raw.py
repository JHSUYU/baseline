#!/usr/bin/env python3
"""Independent raw-trace audit; this module never imports the campaign."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


BASE = Path(__file__).resolve().parent
CASES = ("HDFS-28", "HDFS-29", "HDFS-30")
METHOD = "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>"
SITES = {
    "HDFS-28": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocol.DatanodeID getDatanodeID(java.lang.String)>#u12",
    "HDFS-29": METHOD + "#u12",
    "HDFS-30": METHOD + "#u23",
}
METRICS = ("probes", "methods", "branch_counts")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def coverage(directory: Path, metric: str) -> set[str]:
    file = directory / ("covered_" + metric + ".txt")
    return set(file.read_text().splitlines()) if file.exists() else set()


def owner(event: dict) -> str:
    return event.get("originSourceKey", event.get("sourceKey", ""))


def root(event: dict) -> str:
    return event.get("occurrenceAddress", "").split("/rpc:", 1)[0].split("/server:", 1)[0]


def family(event: dict) -> str:
    return "|".join(str(value) for value in
                    (event.get("marker", ""), event.get("siteId", ""),
                     event.get("sourceKey", ""), owner(event),
                     event.get("requestApi", ""), event.get("filePhase", "")))


def io_families(events: list[dict]) -> set[str]:
    return {family(event) for event in events
            if event.get("event") == "FAULT_POINT_OBSERVED"
            and event.get("marker", "").startswith("FAULT:")}


def check_owner(events: list[dict], applied: dict) -> bool:
    if owner(applied) in ("", "unregistered", "unknown-origin") or not root(applied):
        return False
    begin = any(event.get("event") == "RECOVERY_BEGIN"
                and event.get("seq", -1) < applied.get("seq", -1)
                and event.get("sourceKey") == owner(applied)
                and event.get("occurrenceAddress") == root(applied)
                and event.get("blockId") == applied.get("blockId")
                and (applied.get("recoveryId") is None or
                     event.get("recoveryId") == applied.get("recoveryId"))
                for event in events)
    if not begin:
        return False
    if not applied.get("marker", "").startswith("FAULT:HDFS_FILE:"):
        return True
    if applied.get("filePhase") not in ("initReplicaRecovery", "updateReplicaUnderRecovery"):
        return False
    if (applied["filePhase"] == "updateReplicaUnderRecovery" and
            applied.get("sourceKey") != owner(applied)):
        return False
    return any(event.get("event") == "SERVER_RECOVERY_BEGIN"
               and event.get("seq", -1) < applied.get("seq", -1)
               and event.get("sourceKey") == applied.get("sourceKey")
               and event.get("originSourceKey") == owner(applied)
               and event.get("blockId") == applied.get("blockId")
               and event.get("recoveryId") == applied.get("recoveryId")
               for event in events)


def matches(event: dict, selected: dict, index: int) -> bool:
    return (event.get("planIndex") == index
            and owner(event) == selected["originSourceKey"]
            and all(event.get(key, "") == selected[key] for key in
                    ("marker", "siteId", "sourceKey", "occurrenceAddress",
                     "hitOrdinal", "requestApi", "filePhase", "faultType")))


def same_target(applied: dict, event: dict) -> bool:
    return (event.get("sourceKey") == owner(applied)
            and event.get("occurrenceAddress") == root(applied)
            and event.get("blockId") == applied.get("blockId")
            and (applied.get("recoveryId") is None or
                 event.get("recoveryId") == applied.get("recoveryId")))


def verify_healthy(directory: Path, errors: list[str]) -> tuple[list[dict], dict[str, set[str]]]:
    if not (directory / "manifest.json").exists():
        errors.append("missing fresh healthy manifest: " + str(directory))
        return [], {metric: set() for metric in METRICS}
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest.get("returncode") != 0 or manifest.get("instrumented") is not True
            or manifest.get("graphchecker_runtime_used") is not False
            or manifest.get("test") !=
            "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization"):
        errors.append("unhealthy original-JUnit calibration: " + str(directory))
    events = rows(directory / "runtime_trace.jsonl")
    physical = {event.get("sourceKey") for event in events
                if event.get("event") == "RECOVERY_BEGIN"
                and event.get("sourceKey") not in (None, "unregistered")}
    if not physical or not any(event.get("event") == "CLUSTER_REGISTER"
                               and event.get("dataNodes") == 3 for event in events):
        errors.append("healthy lacks three-DN cluster or physical recovery actor: "
                      + str(directory))
    if any(event.get("event") == "TARGET_THROW" for event in events):
        errors.append("healthy contains target throw: " + str(directory))
    for case in CASES:
        checks = [event for event in events if event.get("event") == "TARGET_CHECK"
                  and event.get("caseId") == case and event.get("siteId") == SITES[case]]
        if not checks or any(event.get("outcome") is not False for event in checks):
            errors.append("healthy lacks nonfatal target " + case + ": " + str(directory))
    cv = {}
    for metric in METRICS:
        path = directory / ("covered_" + metric + ".txt")
        if not path.exists():
            errors.append("healthy missing coverage " + metric + ": " + str(directory))
        cv[metric] = coverage(directory, metric)
    return events, cv


def main() -> int:
    state_file = BASE / "checkpoint.json"
    state = json.loads(state_file.read_text())
    errors = []
    if state.get("schema") != 2 or tuple(state.get("cases", ())) != CASES:
        errors.append("checkpoint schema/cases mismatch")
    healthy_traces = []
    initial = {metric: set() for metric in METRICS}
    base_io = set()
    for directory in (BASE / "healthy-a", BASE / "healthy-b"):
        events, cv = verify_healthy(directory, errors)
        healthy_traces.append(events)
        base_io |= io_families(events)
        for metric in METRICS:
            initial[metric] |= cv[metric]
    if any(set(state["healthy_coverage"][m]) != initial[m] for m in METRICS):
        errors.append("initial JaCoCo union differs from raw healthy coverage")
    union = {case: {m: set(initial[m]) for m in METRICS} for case in CASES}
    families = {case: set(base_io) for case in CASES}
    counts = Counter()
    candidates = []
    times = []
    for number, trial in enumerate(state["completed"], 1):
        directory = Path(trial["run"])
        expected = BASE / "runs" / ("trial-%04d" % number)
        if directory.resolve() != expected.resolve():
            errors.append("run path/order mismatch at " + str(number))
            continue
        try:
            manifest = json.loads((directory / "manifest.json").read_text())
            events = rows(directory / "runtime_trace.jsonl")
            plan = [line.split("\t") for line in
                    (directory / "fault-plan.tsv").read_text().splitlines()]
        except (FileNotFoundError, json.JSONDecodeError) as exception:
            errors.append("missing/malformed raw trial " + str(number) + ": " + str(exception))
            continue
        sequence = trial["sequence"]
        plan_expected = [[str(item[key]) for key in
                          ("marker", "siteId", "sourceKey", "occurrenceAddress",
                           "hitOrdinal", "faultType")] + [item["filePhase"]]
                         for item in sequence]
        if plan != plan_expected:
            errors.append("fault plan differs from checkpoint at " + str(number))
        seqs = [event.get("seq") for event in events]
        if seqs != list(range(1, len(events) + 1)):
            errors.append("trace sequence gap/reorder at " + str(number))
        matched = [event for event in events if event.get("event") == "FAULT_MATCHED"]
        applied = [event for event in events if event.get("event") == "FAULT_APPLIED"]
        exact = (len(matched) == len(applied) == len(sequence)
                 and all(matches(matched[i], sequence[i], i)
                         and matches(applied[i], sequence[i], i)
                         and matched[i]["seq"] < applied[i]["seq"]
                         and check_owner(events, applied[i])
                         for i in range(len(sequence)))
                 and all(applied[i]["seq"] < matched[i + 1]["seq"]
                         for i in range(len(sequence) - 1)))
        if exact != trial["exact_order_applied"]:
            errors.append("strict/identity disagreement at " + str(number))
        last = applied[-1] if exact else None
        cv = {metric: coverage(directory, metric) for metric in METRICS}
        observed_io = io_families(events)
        for case in CASES:
            check_events = [event for event in events
                            if last is not None and event.get("event") == "TARGET_CHECK"
                            and event.get("caseId") == case
                            and event.get("siteId") == SITES[case]
                            and event.get("seq", -1) > last["seq"]
                            and same_target(last, event)]
            count = len(check_events)
            throws = [event for event in events
                      if last is not None and event.get("event") == "TARGET_THROW"
                      and event.get("caseId") == case
                      and event.get("siteId") == SITES[case]
                      and event.get("runtimeType") == "java.io.IOException"
                      and event.get("sourceKey") == owner(last)
                      and event.get("occurrenceAddress") == root(last)
                      and event.get("blockId") == last.get("blockId")
                      and event.get("seq", -1) > last["seq"]
                      and any(check.get("outcome") is True
                              and check["seq"] < event["seq"] for check in check_events)]
            if count != trial["post_fault_target_checks"][case]:
                errors.append("postfault target mismatch at " + str(number) + " " + case)
            if len(throws) != trial["target_exceptions_after_fault"][case]:
                errors.append("target throw mismatch at " + str(number) + " " + case)
            if count:
                counts[case] += 1
                new_coverage = {metric: len(cv[metric] - union[case][metric])
                                for metric in METRICS}
                if new_coverage != trial["coverage_gain"][case]:
                    errors.append("production coverage gain mismatch at "
                                  + str(number) + " " + case)
                new_io = sorted(observed_io - families[case])
                if new_io != trial["new_io_families"][case]:
                    errors.append("I/O novelty mismatch at " + str(number) + " " + case)
                for metric in METRICS:
                    union[case][metric] |= cv[metric]
                families[case] |= observed_io
            elif any(trial["coverage_gain"][case].values()) or trial["new_io_families"][case]:
                errors.append("feedback credited without target at " + str(number) + " " + case)
            if throws:
                candidates.append({"trial": number, "case": case,
                                   "throw_seqs": [event["seq"] for event in throws]})
        if manifest.get("returncode") != trial["junit_exit"]:
            errors.append("JUnit exit mismatch at " + str(number))
        if manifest.get("elapsed_seconds") != trial["elapsed_seconds"]:
            errors.append("JUnit timing mismatch at " + str(number))
        if sha(directory / "runtime_trace.jsonl") != trial["raw_trace_sha256"]:
            errors.append("trace hash mismatch at " + str(number))
        times.append(manifest["elapsed_seconds"])
    for case in CASES:
        for metric in METRICS:
            if union[case][metric] != set(state["coverage"][case][metric]):
                errors.append("final production JaCoCo union mismatch " + case + " " + metric)
        if families[case] != set(state["io_families"][case]):
            errors.append("final I/O family union mismatch " + case)
    result = {"schema": 1, "checkpoint_sha256": sha(state_file),
              "fresh_healthy": len(healthy_traces),
              "completed_attempts": len(state["completed"]),
              "strict_applied": sum(bool(row["exact_order_applied"])
                                    for row in state["completed"]),
              "effective_by_case": {case: counts[case] for case in CASES},
              "goals": state["goals"], "target_exception_candidates": candidates,
              "fault_junit_seconds": round(sum(times), 3), "errors": errors,
              "raw_files_retained": True}
    pending = BASE / "raw-audit.json.tmp"
    pending.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    pending.replace(BASE / "raw-audit.json")
    print(json.dumps({"attempts": result["completed_attempts"],
                      "effective": result["effective_by_case"],
                      "candidates": len(candidates), "errors": len(errors)}))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
