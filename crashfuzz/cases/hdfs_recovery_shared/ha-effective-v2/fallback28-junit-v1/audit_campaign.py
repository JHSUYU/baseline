#!/usr/bin/env python3
"""Independent raw audit of the alternate original-JUnit HDFS-28 campaign."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


BASE = Path(__file__).resolve().parent
CASES = ("HDFS-28",)
TEST = "org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover#testLeaseRecoveryAfterFailover"
TARGET_CLASS = "org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker"
SITES = {
    "HDFS-28": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocol.DatanodeID getDatanodeID(java.lang.String)>#u12",
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


def target_coverage(directory: Path, metric: str) -> set[str]:
    return {value for value in coverage(directory, metric)
            if value.startswith(TARGET_CLASS)}


def stable_io(events: list[dict], last: dict | None = None) -> set[str]:
    result = set()
    for event in events:
        if (event.get("event") != "FAULT_POINT_OBSERVED"
                or not event.get("marker", "").startswith("FAULT:")
                or (last is not None and (event.get("seq", 0) <= last["seq"]
                                          or owner(event) != owner(last)
                                          or root(event) != root(last)))
                or not check_owner(events, event)):
            continue
        if any(check.get("event") == "TARGET_CHECK"
               and check.get("caseId") == "HDFS-28"
               and check.get("siteId") == SITES["HDFS-28"]
               and check.get("seq", -1) > event.get("seq", -1)
               and same_target(event, check) for check in events):
            result.add(family(event))
    return result


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
            TEST):
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
    if state.get("test") != TEST:
        errors.append("checkpoint original JUnit mismatch")
    pilot_audit = json.loads((BASE / "pilot-audit.json").read_text())
    history = state.get("pilot_history", {})
    if (history.get("audit_sha256") != sha(BASE / "pilot-audit.json")
            or pilot_audit.get("errors") or pilot_audit.get("fault_trials") != 2
            or pilot_audit.get("effective_hdfs28") != 1):
        errors.append("independent pilot history mismatch")
    pilot_plans = json.loads((BASE / "pilot-plans.json").read_text())["plans"]
    if (history.get("exact_plan_id") != pilot_plans[0]["id"]
            or history.get("missed_plan_id") != pilot_plans[1]["id"]
            or history.get("pilot_attempts_outside_denominator") != 2
            or history.get("pilot_effective_outside_denominator") != 1):
        errors.append("pilot IDs or separate denominator mismatch")
    if any(t.get("id") == history.get("exact_plan_id") for t in state["completed"]):
        errors.append("exact pilot plan repeated in campaign")
    healthy_traces = []
    initial = {metric: set() for metric in METRICS}
    base_io = set()
    stable = set()
    target = {metric: set() for metric in ("methods", "branch_counts")}
    for directory in (BASE / "healthy-a", BASE / "healthy-b"):
        events, cv = verify_healthy(directory, errors)
        healthy_traces.append(events)
        base_io |= io_families(events)
        stable |= stable_io(events)
        for metric in METRICS:
            initial[metric] |= cv[metric]
        for metric in target:
            target[metric] |= target_coverage(directory, metric)
    if any(set(state["healthy_coverage"][m]) != initial[m] for m in METRICS):
        errors.append("initial JaCoCo union differs from raw healthy coverage")
    pilot_dir = BASE / "pilot-01"
    pilot_events = rows(pilot_dir / "runtime_trace.jsonl")
    pilot_applied = [event for event in pilot_events if event.get("event") == "FAULT_APPLIED"]
    if (len(pilot_applied) != 1 or not pilot_audit["trials"][0]["exact_actor_bound"]
            or history.get("bootstrap_trace_sha256") != sha(pilot_dir / "runtime_trace.jsonl")):
        errors.append("pilot bootstrap trace/identity mismatch")
    pilot_last = pilot_applied[0] if len(pilot_applied) == 1 else None
    if pilot_last is not None:
        if not any(event.get("event") == "TARGET_CHECK"
                   and event.get("caseId") == "HDFS-28"
                   and event.get("siteId") == SITES["HDFS-28"]
                   and event.get("seq", -1) > pilot_last["seq"]
                   and same_target(pilot_last, event) for event in pilot_events):
            errors.append("pilot bootstrap lacks same-root postfault target")
        stable |= stable_io(pilot_events, pilot_last)
    for metric in METRICS:
        initial[metric] |= coverage(pilot_dir, metric)
    for metric in target:
        target[metric] |= target_coverage(pilot_dir, metric)
    base_io |= io_families(pilot_events)
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
        if (manifest.get("test") != TEST or manifest.get("instrumented") is not True
                or manifest.get("graphchecker_runtime_used") is not False):
            errors.append("trial is not alternate original instrumented JUnit at " + str(number))
        healthy_manifest = json.loads((BASE / "healthy-a" / "manifest.json").read_text())
        for field in ("original_test_class_sha256", "original_tests_jar_sha256",
                      "original_test_resource_sha256", "instrumentation_source_sha256"):
            if manifest.get(field) != healthy_manifest.get(field):
                errors.append("source/JAR provenance mismatch at " + str(number) + " " + field)
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
        for name, digest in trial.get("raw_sha256", {}).items():
            file = directory / name
            if not file.is_file() or sha(file) != digest:
                errors.append("raw file hash mismatch at " + str(number) + " " + name)
        if len(trial.get("raw_sha256", {})) != 8:
            errors.append("incomplete raw hash list at " + str(number))
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
                new_target = {metric: len(target_coverage(directory, metric)
                                          - target[metric]) for metric in target}
                if new_target != trial.get("target_related_coverage_gain"):
                    errors.append("target-related coverage feedback mismatch at " + str(number))
                newly_stable = sorted(stable_io(events, last) - stable)
                if newly_stable != trial.get("stable_actor_io_gain"):
                    errors.append("stable actor I/O feedback mismatch at " + str(number))
                for metric in METRICS:
                    union[case][metric] |= cv[metric]
                families[case] |= observed_io
                for metric in target:
                    target[metric] |= target_coverage(directory, metric)
                stable |= set(newly_stable)
            elif any(trial["coverage_gain"][case].values()) or trial["new_io_families"][case]:
                errors.append("feedback credited without target at " + str(number) + " " + case)
            if not count and (any(trial.get("target_related_coverage_gain", {}).values())
                              or trial.get("stable_actor_io_gain")):
                errors.append("target-related feedback credited without target at " + str(number))
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
    for metric in target:
        if target[metric] != set(state.get("target_related_coverage", {}).get(metric, [])):
            errors.append("final target-related coverage union mismatch " + metric)
    if stable != set(state.get("stable_actor_io_families", [])):
        errors.append("final stable actor I/O union mismatch")
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
