#!/usr/bin/env python3
"""Resumable graph-free recovery RPC and replica-file I/O campaign."""

from __future__ import annotations

from collections import Counter
import csv
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
CASES = ("HDFS-28", "HDFS-29", "HDFS-30")
CASE_ROOT = HERE.parents[1]
STATE = HERE / "campaign-state.json"
LOCK = HERE / "campaign.lock"
PAUSE = HERE / "pause.request"
RUNNER = HERE / "run_original.py"
HEALTHY = tuple(sorted(HERE.glob("healthy-file-*")))
SMOKE = HERE / "smoke-file-remote"
KINDS_RPC = ("IOException", "EOFException", "SocketTimeoutException")
KINDS_FILE = ("IOException", "FileNotFoundException")
COVERAGE = ("probes", "methods", "branch_counts")
TARGET_SITE = {
    "HDFS-28": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocol.DatanodeID getDatanodeID(java.lang.String)>#u12",
    "HDFS-29": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>#u12",
    "HDFS-30": "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>#u23",
}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    temporary.replace(path)


def rows(directory: Path) -> list[dict]:
    path = directory / "runtime_trace.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def covered(directory: Path, category: str) -> set[str]:
    path = directory / ("covered_" + category + ".txt")
    return set(path.read_text().splitlines()) if path.exists() else set()


def point(event: dict, kind: str) -> dict:
    return {**{key: event[key] for key in
               ("marker", "siteId", "sourceKey", "occurrenceAddress", "hitOrdinal")},
            "originSourceKey": event.get("originSourceKey", event["sourceKey"]),
            "requestApi": event.get("requestApi", ""),
            "filePhase": event.get("filePhase", ""),
            "faultType": kind}


def fault_kinds(event: dict) -> tuple[str, ...]:
    return KINDS_FILE if event.get("marker", "").startswith("FAULT:HDFS_FILE:") else KINDS_RPC


def sequence_id(sequence: list[dict]) -> str:
    canonical = json.dumps(sequence, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def family(value: dict) -> str:
    # An IPC send site can carry distinct original RPC operations.
    return "|".join(str(value.get(key, "")) for key in
                    ("marker", "siteId", "sourceKey", "originSourceKey", "requestApi"))


def recovery_root(event: dict) -> str:
    address = event.get("occurrenceAddress", "")
    return address.split("/rpc:", 1)[0].split("/server:", 1)[0]


def relevant_before_target(event: dict, trace: list[dict]) -> bool:
    if not event.get("marker", "").startswith("FAULT:"):
        return False
    return any(row.get("event") == "TARGET_CHECK"
               and row.get("caseId") in CASES
               and row.get("sourceKey") == event.get("originSourceKey", event.get("sourceKey"))
               and row.get("blockId") == event.get("blockId")
               and row.get("occurrenceAddress") == recovery_root(event)
               and row.get("seq", -1) > event.get("seq", -1)
               for row in trace)


def relevant_recovery_io(event: dict, trace: list[dict]) -> bool:
    """Seed later commit/update RPCs too; a failure may cause a retry."""
    return (event.get("marker", "").startswith("FAULT:")
            and any(row.get("event") == "TARGET_CHECK"
                    and row.get("sourceKey") == event.get("originSourceKey", event.get("sourceKey"))
                    and row.get("blockId") == event.get("blockId")
                    and row.get("occurrenceAddress") == recovery_root(event)
                    for row in trace))


def enqueue(state: dict, sequence: list[dict], priority: int = 0,
            pre_target: bool = False) -> None:
    identity = sequence_id(sequence)
    if identity in state["seen_sequences"]:
        return
    state["seen_sequences"].append(identity)
    state["queue"].append({"id": identity, "sequence": sequence,
                           "priority": priority, "pre_target": pre_target,
                           "created": time.time()})


def initialize() -> dict:
    healthy = [directory for directory in HEALTHY if
               (directory / "manifest.json").is_file()]
    if not healthy:
        raise RuntimeError("no independent original-JUnit healthy seed")
    traces = []
    baseline = {category: set() for category in COVERAGE}
    elapsed = 0.0
    for directory in healthy:
        manifest = json.loads((directory / "manifest.json").read_text())
        if manifest["returncode"] != 0 or not manifest["instrumented"]:
            raise RuntimeError("healthy seed failed or is not instrumented: " + str(directory))
        trace = rows(directory)
        for case in CASES:
            checks = [r for r in trace if r.get("event") == "TARGET_CHECK"
                      and r.get("caseId") == case and r.get("siteId") == TARGET_SITE[case]]
            if not checks or any(r.get("outcome") is not False
                                 or r.get("sourceKey") == "unregistered" for r in checks):
                raise RuntimeError("healthy original JUnit did not reach the nonfatal " + case)
        if any(r.get("event") == "TARGET_THROW" for r in trace):
            raise RuntimeError("healthy seed had an expected target exception")
        traces.append(trace)
        elapsed += manifest["elapsed_seconds"]
        for category in COVERAGE:
            baseline[category] |= covered(directory, category)
    state = {"schema": 1, "budget": {"max_trials": 80, "max_faults": 8},
             "healthy_dirs": [str(x) for x in healthy],
             "healthy_seconds": round(elapsed, 3),
             "healthy_coverage": {k: sorted(v) for k, v in baseline.items()},
             "coverage": {case: {k: sorted(v) for k, v in baseline.items()}
                          for case in CASES},
             "io_families": {case: sorted({family(e) for trace in traces for e in trace
                                          if e.get("event") == "FAULT_POINT_OBSERVED"
                                          and e.get("marker", "").startswith("FAULT:")})
                             for case in CASES},
             "queue": [], "seen_sequences": [], "completed": [], "active": None,
             "started_at": time.time(), "stop_reason": None}
    for trace in traces:
        for event in trace:
            if event.get("event") == "FAULT_POINT_OBSERVED" and relevant_recovery_io(event, trace):
                for kind in fault_kinds(event):
                    enqueue(state, [point(event, kind)],
                            pre_target=relevant_before_target(event, trace))
    if not state["queue"]:
        raise RuntimeError("healthy target reached but no real pre-target RPC point")
    # This exact original-JUnit replay already exercised all three checks.
    if (SMOKE / "manifest.json").is_file():
        applied = [e for e in rows(SMOKE) if e.get("event") == "FAULT_APPLIED"]
        if len(applied) != 1:
            raise RuntimeError("saved strict smoke has no unique applied selector")
        trial = evaluate(SMOKE, [point(applied[0], applied[0]["faultType"])], state)
        if (not trial["exact_order_applied"] or
                not trial["post_fault_target_checks"]["HDFS-29"] or
                not trial["post_fault_target_checks"]["HDFS-30"]):
            raise RuntimeError("saved file smoke lost HDFS-29/30 owner targets")
        state["queue"] = [item for item in state["queue"] if item["id"] != trial["id"]]
        state["completed"].append(trial)
        admit(state, trial)
    atomic_json(STATE, state)
    write_result(state)
    return state


def event_matches(event: dict, selected: dict, index: int) -> bool:
    return (event.get("planIndex") == index and
            event.get("originSourceKey", event.get("sourceKey"))
            == selected["originSourceKey"] and
            event.get("filePhase", "") == selected.get("filePhase", "") and all(
        event.get(key) == selected[key] for key in
        ("marker", "siteId", "sourceKey", "occurrenceAddress", "hitOrdinal",
         "requestApi", "faultType")))


def identity_verified(trace: list[dict], event: dict) -> bool:
    """Tie a selected physical I/O call to its original recovery owner."""
    root = recovery_root(event)
    origin = event.get("originSourceKey", event.get("sourceKey"))
    if origin in (None, "unregistered", "unknown-origin") or not root:
        return False
    owner = any(row.get("event") == "RECOVERY_BEGIN"
                and row.get("seq", -1) < event.get("seq", -1)
                and row.get("sourceKey") == origin
                and row.get("blockId") == event.get("blockId")
                and row.get("occurrenceAddress") == root
                and (event.get("recoveryId") is None or
                     row.get("recoveryId") == event.get("recoveryId"))
                for row in trace)
    if not owner:
        return False
    if not event.get("marker", "").startswith("FAULT:HDFS_FILE:"):
        return True
    phase = event.get("filePhase")
    if phase not in ("initReplicaRecovery", "updateReplicaUnderRecovery"):
        return False
    if phase == "updateReplicaUnderRecovery" and event.get("sourceKey") != origin:
        return False
    return any(row.get("event") == "SERVER_RECOVERY_BEGIN"
               and row.get("seq", -1) < event.get("seq", -1)
               and row.get("sourceKey") == event.get("sourceKey")
               and row.get("originSourceKey") == origin
               and row.get("blockId") == event.get("blockId")
               and row.get("recoveryId") == event.get("recoveryId")
               for row in trace)


def evaluate(directory: Path, sequence: list[dict], state: dict) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    trace = rows(directory)
    matched = [e for e in trace if e.get("event") == "FAULT_MATCHED"]
    applied = [e for e in trace if e.get("event") == "FAULT_APPLIED"]
    identity_ok = (len(applied) == len(sequence) and
                   all(identity_verified(trace, event) for event in applied))
    exact = (len(matched) == len(applied) == len(sequence)
             and identity_ok
             and all(event_matches(matched[i], sequence[i], i)
                     and event_matches(applied[i], sequence[i], i)
                     and matched[i]["seq"] < applied[i]["seq"]
                     for i in range(len(sequence)))
             and all(applied[i]["seq"] < matched[i + 1]["seq"]
                     for i in range(len(sequence) - 1)))
    last = applied[-1] if exact else None
    after = {}
    target_exceptions = {}
    for case in CASES:
        post_checks = [e for e in trace if e.get("event") == "TARGET_CHECK"
                       and e.get("caseId") == case and e.get("siteId") == TARGET_SITE[case]
                       and last is not None and e.get("seq", -1) > last["seq"]
                       and e.get("sourceKey") == last.get("originSourceKey", last.get("sourceKey"))
                       and e.get("blockId") == last.get("blockId")
                       and e.get("occurrenceAddress") == recovery_root(last)]
        post_throws = [e for e in trace if e.get("event") == "TARGET_THROW"
                       and e.get("caseId") == case
                       and e.get("siteId") == TARGET_SITE[case]
                       and e.get("runtimeType") == "java.io.IOException"
                       and last is not None and e.get("seq", -1) > last["seq"]
                       and e.get("sourceKey") == last.get("originSourceKey", last.get("sourceKey"))
                       and e.get("blockId") == last.get("blockId")
                       and e.get("occurrenceAddress") == recovery_root(last)
                       and any(check.get("outcome") is True
                               and check["seq"] < e["seq"]
                               for check in post_checks)]
        after[case] = len(post_checks)
        target_exceptions[case] = len(post_throws) if post_checks else 0
    coverage = {category: covered(directory, category) for category in COVERAGE}
    gains = {case: {category: len(coverage[category] - set(state["coverage"][case][category]))
                    if after[case] else 0 for category in COVERAGE}
             for case in CASES}
    families = {family(e) for e in trace
                if e.get("event") == "FAULT_POINT_OBSERVED"
                and e.get("marker", "").startswith("FAULT:")}
    new_families = {case: sorted(families - set(state["io_families"][case]))
                    if after[case] else [] for case in CASES}
    return {"id": sequence_id(sequence), "sequence": sequence,
            "run": str(directory), "junit_exit": manifest["returncode"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "requested_faults": len(sequence), "matched_faults": len(matched),
            "applied_faults": len(applied), "runtime_identity_verified": identity_ok,
            "file_phases": [event.get("filePhase") for event in applied
                            if event.get("marker", "").startswith("FAULT:HDFS_FILE:")],
            "exact_order_applied": exact,
            "post_fault_target_checks": after,
            "target_exceptions_after_fault": target_exceptions,
            "coverage_gain": gains, "new_io_families": new_families,
            "last_applied_seq": last["seq"] if last else None,
            "last_source_key": last.get("sourceKey") if last else None,
            "last_origin_source_key": last.get("originSourceKey", last.get("sourceKey"))
            if last else None,
            "last_recovery_root": recovery_root(last) if last else None,
            "last_block_id": last.get("blockId") if last else None,
            "bug_mark": "candidate_needs_replay_source_review" if
            any(target_exceptions.values()) else "none"}


def admit(state: dict, trial: dict) -> None:
    directory = Path(trial["run"])
    trace = rows(directory)
    for case in CASES:
        if not trial["post_fault_target_checks"][case]:
            continue
        for category in COVERAGE:
            state["coverage"][case][category] = sorted(
                set(state["coverage"][case][category]) | covered(directory, category))
        state["io_families"][case] = sorted(
            set(state["io_families"][case]) |
            {family(e) for e in trace if e.get("event") == "FAULT_POINT_OBSERVED"
             and e.get("marker", "").startswith("FAULT:")})
    if not any(trial["post_fault_target_checks"].values()):
        return
    if len(trial["sequence"]) >= state["budget"]["max_faults"]:
        return
    for event in trace:
        if (event.get("event") != "FAULT_POINT_OBSERVED"
                or not event.get("marker", "").startswith("FAULT:")
                or event.get("seq", -1) <= trial["last_applied_seq"]
                or not relevant_recovery_io(event, trace)):
            continue
        for kind in fault_kinds(event):
            selected = point(event, kind)
            if selected in trial["sequence"]:
                continue
            priority = (sum(g["probes"] for g in trial["coverage_gain"].values())
                        + 50 * any(trial["new_io_families"].values())
                        + 3 * len(trial["sequence"]))
            enqueue(state, trial["sequence"] + [selected], priority,
                    pre_target=relevant_before_target(event, trace))


def choose(state: dict) -> int:
    completed = state["completed"]
    type_counts = Counter(t["sequence"][-1]["faultType"] for t in completed)
    last_counts = Counter(family(t["sequence"][-1]) for t in completed)
    root_counts = Counter(family(t["sequence"][0]) for t in completed)
    single = sum(len(t["sequence"]) == 1 for t in completed)
    # Sample three distinct single-fault contexts for each multi-fault
    # sequence. A pair of file failures can keep the original JUnit waiting
    # for lease recovery until timeout, so breadth is cheaper early on.
    prefer_single = single < 3 * ((len(completed) - single) + 1)
    eligible = [(i, x) for i, x in enumerate(state["queue"])
                if (len(x["sequence"]) == 1) == prefer_single]
    if not eligible:
        eligible = list(enumerate(state["queue"]))
    # Three rounds in four favor an I/O point that preceded the next check
    # of the same recovery owner in its parent execution. The fourth round
    # still explores later I/O and possible retry behavior.
    if len(completed) % 4 != 3:
        before_target = [(i, x) for i, x in eligible if x.get("pre_target")]
        if before_target:
            eligible = before_target
    return min(eligible, key=lambda item: (
        type_counts[item[1]["sequence"][-1]["faultType"]],
        last_counts[family(item[1]["sequence"][-1])],
        root_counts[family(item[1]["sequence"][0])],
        -item[1]["priority"], item[1]["created"]))[0]


def write_result(state: dict) -> None:
    completed = state["completed"]
    strict = [t for t in completed if t["exact_order_applied"]]
    elapsed = state["healthy_seconds"] + sum(t["elapsed_seconds"] for t in completed)
    for case in CASES:
        path = CASE_ROOT / case / "result.json"
        legacy_path = CASE_ROOT / case / "legacy-rpc-result.json"
        legacy = json.loads(legacy_path.read_text())
        old = json.loads(path.read_text())
        valid = [t for t in strict if t["post_fault_target_checks"][case]]
        candidates = [t for t in valid if t["target_exceptions_after_fault"][case]]
        if len(completed) < state["budget"]["max_trials"] and state["queue"]:
            status = "running"
        elif candidates:
            status = "pending_source_review"
        elif len(completed) >= state["budget"]["max_trials"] and valid:
            # Final raw-evidence audit is separate from the campaign loop.
            # HDFS-30 also needs an original HA JUnit control-plane trial.
            status = "running_supplemental" if case == "HDFS-30" else "pending_final_audit"
        elif not valid:
            status = "no_valid_target_trial"
        else:
            status = "search_exhausted"
        gain = len(state["coverage"][case]["probes"]) - len(
            state["healthy_coverage"]["probes"])
        old.update(status=status, target_reached=True,
                   fault_trials=len(completed),
                   strict_injections=len(strict),
                   fully_applied_trials=len(strict),
                   target_after_fault=len(valid),
                   target_exception_after_fault_trials=len(candidates),
                   coverage_gain=gain,
                   coverage_scope="phase_v4_rpc_and_replica_file_io_only",
                   elapsed_seconds=round(elapsed, 3),
                   bug_mark="candidate_needs_replay_source_review" if candidates else "none",
                   methodology="original_junit_case_local_asm_jacoco_graph_free",
                   independent_campaign={
                       "shared_checkpoint": str(STATE), "shared_healthy": state["healthy_dirs"],
                       "budget": state["budget"],
                       "default_trial_timeout_seconds_after_trial_4": 180,
                       "strict_target_trials": len(valid),
                       "target_exception_candidates": len(candidates),
                       "production_probe_gain": gain,
                       "coverage_scope": "phase_v4_rpc_and_replica_file_io_only",
                       "file_phase_calibration": state.get("phase_calibration"),
                       "legacy_rpc_pilot": {
                           "result": str(legacy_path),
                           "fault_trials": legacy["fault_trials"],
                           "strict_injections": legacy["strict_injections"],
                           "target_after_fault": legacy["target_after_fault"],
                           "elapsed_seconds": legacy["elapsed_seconds"],
                       },
                       "method_gain": len(state["coverage"][case]["methods"])
                       - len(state["healthy_coverage"]["methods"]),
                       "branch_count_gain": len(state["coverage"][case]["branch_counts"])
                       - len(state["healthy_coverage"]["branch_counts"])},
                   evidence=str(HERE / "campaign-state.json")
                   + "; per-trial exact selector, JUnit, target, and JaCoCo evidence in "
                   + str(HERE / "runs") + "; prior RPC-only pilot in "
                   + str(legacy_path))
        atomic_json(path, old)
        ledger = CASE_ROOT / case / "trial-ledger-v4.csv"
        with ledger.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("trial", "sequence_id", "requested_faults", "seconds",
                             "junit_exit", "exact_injection", "target_after_fault",
                             "target_exception", "new_probes", "new_methods",
                             "new_branch_counts", "new_io_families", "run"))
            for index, trial in enumerate(completed, 1):
                writer.writerow((index, trial["id"], trial["requested_faults"],
                                 trial["elapsed_seconds"], trial["junit_exit"],
                                 trial["exact_order_applied"],
                                 bool(trial["post_fault_target_checks"][case]),
                                 trial["target_exceptions_after_fault"][case],
                                 trial["coverage_gain"][case]["probes"],
                                 trial["coverage_gain"][case]["methods"],
                                 trial["coverage_gain"][case]["branch_counts"],
                                 len(trial["new_io_families"][case]), trial["run"]))


def run_one(state: dict, item: dict) -> None:
    number = len(state["completed"]) + 1
    run = HERE / "runs" / ("trial-%03d" % number)
    run.mkdir(parents=True, exist_ok=True)
    plan = run / "fault-plan.tsv"
    plan.write_text("".join("\t".join(str(fault[key]) for key in
                                       ("marker", "siteId", "sourceKey",
                                        "occurrenceAddress", "hitOrdinal", "faultType"))
                            + "\t" + fault.get("filePhase", "")
                            + "\n" for fault in item["sequence"]))
    if not (run / "manifest.json").is_file():
        command = [sys.executable, str(RUNNER), "--instrument", "--plan", str(plan),
                   "--output", str(run), "--timeout", "180"]
        with (run / "driver.log").open("w") as log:
            subprocess.run(command, cwd=HERE, stdout=log, stderr=subprocess.STDOUT)
    if not (run / "manifest.json").is_file():
        raise RuntimeError("trial missing manifest; active sequence remains for resume")
    trial = evaluate(run, item["sequence"], state)
    trial["unmatched_retry"] = item.get("retry", 0)
    state["completed"].append(trial)
    admit(state, trial)
    # Runtime leader selection can alternate dn0/dn1. Retry an unexecuted
    # exact node selector twice, preserving each attempt's timing/evidence.
    if not trial["exact_order_applied"] and item.get("retry", 0) < 2:
        state["queue"].append({**item, "retry": item.get("retry", 0) + 1,
                               "created": time.time(), "priority": item["priority"] + 1})
    state["active"] = None
    atomic_json(STATE, state)
    write_result(state)
    print("HDFS-28/29/30", number, "exact", trial["exact_order_applied"],
          "targets", {case: bool(trial["post_fault_target_checks"][case])
                      for case in CASES},
          "candidate", trial["bug_mark"], flush=True)


def main() -> None:
    with LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
        if state.get("stop_reason") == "operator_pause":
            state["stop_reason"] = None
        while len(state["completed"]) < state["budget"]["max_trials"] and (
                state["queue"] or state["active"]):
            if PAUSE.exists():
                state["stop_reason"] = "operator_pause"
                atomic_json(STATE, state)
                write_result(state)
                print("Campaign paused at completed trial boundary", flush=True)
                return
            if state["active"] is None:
                state["active"] = state["queue"].pop(choose(state))
                atomic_json(STATE, state)
            run_one(state, state["active"])
        if len(state["completed"]) == 80:
            recent = [t for t in state["completed"]
                      if t["exact_order_applied"]
                      and any(t["post_fault_target_checks"].values())][-8:]
            novelty = any(any(g["probes"] or g["methods"] or g["branch_counts"]
                              for g in trial["coverage_gain"].values())
                          or any(trial["new_io_families"].values())
                          for trial in recent)
            if novelty:
                state["budget"] = {"max_trials": 128, "max_faults": 10}
                atomic_json(STATE, state)
                write_result(state)
                print("Extending to 128/max10: recent valid novelty", flush=True)
                while len(state["completed"]) < 128 and (state["queue"] or state["active"]):
                    if PAUSE.exists():
                        state["stop_reason"] = "operator_pause"
                        atomic_json(STATE, state)
                        write_result(state)
                        print("Campaign paused at completed trial boundary", flush=True)
                        return
                    if state["active"] is None:
                        state["active"] = state["queue"].pop(choose(state))
                        atomic_json(STATE, state)
                    run_one(state, state["active"])
        state["stop_reason"] = ("budget" if len(state["completed"])
                                >= state["budget"]["max_trials"] else "queue_exhausted")
        atomic_json(STATE, state)
        write_result(state)
        print("Campaign stopped:", state["stop_reason"],
              "completed", len(state["completed"]), flush=True)


if __name__ == "__main__":
    main()
