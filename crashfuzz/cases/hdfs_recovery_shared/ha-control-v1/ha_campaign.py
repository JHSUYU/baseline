#!/usr/bin/env python3
"""Resumable, case-local HA heartbeat fuzzing of the original HDFS JUnit.

Only released-Hadoop MiniDFSCluster runs made by run_original.py are inputs.
The selected oracle is the HDFS-30 guard in the second recovery after failover.
The three earlier manual pilots are archived on first start; they are not
replayed or admitted as coverage feedback for the active1-gated adapter.
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
import re
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
STATE = HERE / "ha-campaign-state.json"
SUMMARY = HERE / "ha-campaign-summary.json"
LEDGER = HERE / "ha-trial-ledger.csv"
LOCK = HERE / "ha-campaign.lock"
PAUSE = HERE / "ha-pause.request"
RUNNER = HERE / "run_original.py"
PREFERRED_HEALTHY = HERE / "healthy-active1-v2"
FALLBACK_HEALTHY = HERE / "healthy-node2"
TARGET_SITE = ("<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: "
               "org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB "
               "getActiveNamenodeForBP(java.lang.String)>#u23")
HEARTBEAT_PREFIX = "FAULT:HDFS_HA_HEARTBEAT:"
FAULT_TYPES = ("IOException", "EOFException", "SocketTimeoutException")
COVERAGE = ("probes", "methods", "branch_counts")
MAX_ATTEMPTS = 24
MAX_FAULTS = 2
MAX_FLAKE_RETRIES = 2
MAX_SCHEDULE_RETRIES = 2
JUNIT_TIMEOUT = 180  # The released JUnit also has its own 60-second timeout.
NO_GAIN_VALID_LIMIT = 8
TRIAL_RE = re.compile(r"trial-(\d+)$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def atomic_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, sort_keys=True, indent=2) + "\n")


def load_trace(directory: Path) -> list[dict]:
    path = directory / "runtime_trace.jsonl"
    if not path.is_file():
        return []
    lines = path.read_text().splitlines()
    result = []
    for index, line in enumerate(lines):
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            if index != len(lines) - 1:
                raise
            # A killed JVM can leave one incomplete final trace row.
    return result


def coverage_set(directory: Path, category: str) -> set[str]:
    path = directory / ("covered_" + category + ".txt")
    return set(path.read_text().splitlines()) if path.is_file() else set()


def digest(value: object) -> str:
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def branch_id(target: dict) -> str:
    return digest({key: target[key] for key in
                   ("sourceKey", "blockId", "recoveryId")})


def selector(event: dict, fault_type: str) -> dict:
    return {"marker": event["marker"], "siteId": event["siteId"],
            "sourceKey": event["sourceKey"],
            "occurrenceAddress": event["occurrenceAddress"],
            "hitOrdinal": int(event["hitOrdinal"]), "faultType": fault_type,
            "filePhase": ""}


def selector_key(sequence: list[dict]) -> str:
    return digest(sequence)


def sequence_key(branch: str, sequence: list[dict]) -> str:
    return digest({"branch": branch, "sequence": sequence})


def plan_lines(sequence: list[dict]) -> str:
    fields = ("marker", "siteId", "sourceKey", "occurrenceAddress",
              "hitOrdinal", "faultType", "filePhase")
    return "".join("\t".join(str(point[key]) for key in fields) + "\n"
                   for point in sequence)


def parse_plan(path: Path) -> list[dict]:
    if not path.is_file():
        raise RuntimeError("missing exact plan: " + str(path))
    result = []
    names = ("marker", "siteId", "sourceKey", "occurrenceAddress",
             "hitOrdinal", "faultType", "filePhase")
    for line in path.read_text().splitlines():
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            raise RuntimeError("plan is not seven-column TSV: " + str(path))
        row = dict(zip(names, fields))
        row["hitOrdinal"] = int(row["hitOrdinal"])
        result.append(row)
    if not result or len(result) > MAX_FAULTS:
        raise RuntimeError("invalid fault sequence length: " + str(path))
    return result


def ha_start(trace: list[dict]) -> int | None:
    transitions = [row["seq"] for row in trace
                   if row.get("event") == "HA_TRANSITION"
                   and row.get("active") is True
                   and row.get("nnIndex") == 1
                   and row.get("haPhase") == "active1"]
    return min(transitions) if transitions else None


def targets_after_failover(trace: list[dict]) -> list[dict]:
    start = ha_start(trace)
    if start is None:
        return []
    owners = [row for row in trace if row.get("event") == "RECOVERY_BEGIN"]
    targets = []
    for check in trace:
        if (check.get("event") != "TARGET_CHECK"
                or check.get("caseId") != "HDFS-30"
                or check.get("siteId") != TARGET_SITE
                or check.get("seq", -1) <= start
                or check.get("sourceKey") in (None, "unregistered")):
            continue
        keys = ("sourceKey", "blockId", "recoveryId", "occurrenceAddress")
        if not all(key in check for key in keys):
            continue
        if not any(all(owner.get(key) == check[key] for key in keys)
                   and start < owner.get("seq", -1) < check["seq"]
                   for owner in owners):
            continue
        target = {key: check[key] for key in keys}
        target["bpid"] = check.get("bpid", "")  # Within-run filter only.
        target["seedCheckSeq"] = check["seq"]
        if branch_id(target) not in {branch_id(t) for t in targets}:
            targets.append(target)
    return targets


def eligible_heartbeats(trace: list[dict], target: dict,
                        after_seq: int = -1) -> list[dict]:
    start = ha_start(trace)
    if start is None:
        return []
    matching_checks = [row for row in trace
                       if row.get("event") == "TARGET_CHECK"
                       and row.get("caseId") == "HDFS-30"
                       and row.get("siteId") == TARGET_SITE
                       and all(row.get(key) == target[key] for key in
                               ("sourceKey", "blockId", "recoveryId"))
                       and row.get("seq", -1) > max(start, after_seq)]
    if not matching_checks:
        return []
    until = min(row["seq"] for row in matching_checks)
    bpid = matching_checks[0].get("bpid", "")
    return [row for row in trace
            if row.get("event") == "FAULT_POINT_OBSERVED"
            and row.get("marker", "").startswith(HEARTBEAT_PREFIX)
            and row.get("sourceKey") == target["sourceKey"]
            and row.get("haPhase") == "active1"
            and row.get("nnId") in ("nn1", "nn2", "nn3")
            and row.get("bpid") == bpid
            and max(start, after_seq) < row.get("seq", -1) < until]


def io_family(row: dict) -> str:
    return "|".join(str(row.get(key, "")) for key in
                    ("marker", "siteId", "sourceKey", "originSourceKey",
                     "nnId", "requestApi", "filePhase"))


def relevant_io(trace: list[dict], target: dict,
                after_seq: int = -1) -> set[str]:
    start = ha_start(trace)
    if start is None:
        return set()
    result = set()
    for row in trace:
        if (row.get("event") != "FAULT_POINT_OBSERVED"
                or row.get("seq", -1) <= max(start, after_seq)
                or not row.get("marker", "").startswith("FAULT:")):
            continue
        if row["marker"].startswith(HEARTBEAT_PREFIX):
            if (row.get("sourceKey") == target["sourceKey"]
                    and row.get("haPhase") == "active1"
                    and row.get("bpid") == target.get("bpid")):
                result.add(io_family(row))
            continue
        origin = row.get("originSourceKey", row.get("sourceKey"))
        if (origin == target["sourceKey"]
                and row.get("blockId") == target["blockId"]
                and str(row.get("occurrenceAddress", "")).startswith(
                    target["occurrenceAddress"] + "/")):
            result.add(io_family(row))
    return result


def enqueue(state: dict, branch: str, seed_run: Path,
            sequence: list[dict], seed_reward: int = 0,
            retry: int = 0) -> None:
    identity = sequence_key(branch, sequence)
    if identity in state["seen_sequences"]:
        return
    state["seen_sequences"].append(identity)
    state["queue"].append({"id": identity, "branch_id": branch,
                           "seed_run": seed_run.name, "sequence": sequence,
                           "seed_reward": seed_reward, "retry": retry,
                           "queued_at_attempt": len(state["completed"])})


def seed_run(state: dict, directory: Path, trace: list[dict],
             seed_reward: int = 0, allow_junit_failure: bool = False) -> None:
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = json.loads(manifest_path.read_text())
    if ((manifest.get("returncode") != 0 and not allow_junit_failure)
            or not manifest.get("instrumented")):
        return
    if directory.name in state["seeded_runs"]:
        return
    state["seeded_runs"].append(directory.name)
    for target in targets_after_failover(trace):
        key = branch_id(target)
        if key not in state["branches"]:
            state["branches"][key] = {
                "target": target, "seed_run": directory.name,
                "coverage_sources": [directory.name],
                "io_families": sorted(relevant_io(trace, target)),
            }
        for observed in eligible_heartbeats(trace, target):
            for fault_type in FAULT_TYPES:
                enqueue(state, key, directory,
                        [selector(observed, fault_type)], seed_reward)


def choose_healthy() -> Path:
    for directory in (PREFERRED_HEALTHY, FALLBACK_HEALTHY):
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text())
        if (manifest.get("returncode") == 0 and manifest.get("instrumented")
                and targets_after_failover(load_trace(directory))):
            return directory
    raise RuntimeError("no passed original HA JUnit seed reaching HDFS-30 after active1")


def event_matches(row: dict, selected: dict, index: int) -> bool:
    return (row.get("planIndex") == index
            and all(row.get(key) == selected[key] for key in
                    ("marker", "siteId", "sourceKey", "occurrenceAddress",
                     "hitOrdinal", "faultType"))
            and row.get("haPhase") == "active1"
            and selected.get("filePhase", "") == ""
            and row.get("originSourceKey") == selected["sourceKey"])


def exact_injection(trace: list[dict], sequence: list[dict]) -> tuple[bool, list[dict]]:
    matched = [row for row in trace if row.get("event") == "FAULT_MATCHED"]
    applied = [row for row in trace if row.get("event") == "FAULT_APPLIED"]
    if len(matched) != len(applied) or len(applied) != len(sequence):
        return False, applied
    transition = ha_start(trace)
    if transition is None:
        return False, applied
    for index, (match, apply, selected) in enumerate(zip(matched, applied, sequence)):
        if (not event_matches(match, selected, index)
                or not event_matches(apply, selected, index)
                or not (transition < match["seq"] < apply["seq"])
                or (index and not applied[index - 1]["seq"] < match["seq"])):
            return False, applied
        observed = [row for row in trace
                    if row.get("event") == "FAULT_POINT_OBSERVED"
                    and row.get("seq", -1) < match["seq"]
                    and all(row.get(key) == selected[key] for key in
                            ("marker", "siteId", "sourceKey",
                             "occurrenceAddress", "hitOrdinal"))]
        if not observed:
            return False, applied
    return True, applied


def branch_coverage(state: dict, branch: str, category: str) -> set[str]:
    result = set()
    for dirname in state["branches"][branch]["coverage_sources"]:
        result |= coverage_set(HERE / dirname, category)
    return result


def evaluate(state: dict, directory: Path, sequence: list[dict],
             branch: str | None, adapter_version: str,
             retry: int = 0) -> dict:
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    trace = load_trace(directory)
    exact, applied = exact_injection(trace, sequence) if trace else (False, [])
    matched = [row for row in trace if row.get("event") == "FAULT_MATCHED"]
    target = state["branches"][branch]["target"] if branch in state["branches"] else None
    last = applied[-1] if exact else None
    checks = []
    if last is not None and target is not None:
        checks = [row for row in trace
                  if row.get("event") == "TARGET_CHECK"
                  and row.get("caseId") == "HDFS-30"
                  and row.get("siteId") == TARGET_SITE
                  and row.get("seq", -1) > last["seq"]
                  and row.get("bpid") == last.get("bpid")
                  and all(fault.get("bpid") == row.get("bpid")
                          for fault in applied)
                  and all(row.get(key) == target[key] for key in
                          ("sourceKey", "blockId", "recoveryId"))
                  and any(owner.get("event") == "RECOVERY_BEGIN"
                          and owner.get("seq", -1) < row["seq"]
                          and all(owner.get(key) == row.get(key) for key in
                                  ("sourceKey", "blockId", "recoveryId",
                                   "occurrenceAddress"))
                          for owner in trace)]
    true_checks = [row for row in checks if row.get("outcome") is True]
    throws = []
    if true_checks and target is not None:
        throws = [row for row in trace
                  if row.get("event") == "TARGET_THROW"
                  and row.get("caseId") == "HDFS-30"
                  and row.get("siteId") == TARGET_SITE
                  and row.get("runtimeType") == "java.io.IOException"
                  and all(row.get(key) == target[key] for key in
                          ("sourceKey", "blockId"))
                  and any(check["seq"] < row.get("seq", -1)
                          and check.get("occurrenceAddress") == row.get("occurrenceAddress")
                          for check in true_checks)]
    retained = bool(checks)
    gain = {kind: 0 for kind in COVERAGE}
    io_gain: list[str] = []
    if retained and branch is not None:
        for kind in COVERAGE:
            gain[kind] = len(coverage_set(directory, kind)
                             - branch_coverage(state, branch, kind))
        runtime_target = dict(target,
                              bpid=checks[0].get("bpid", ""),
                              occurrenceAddress=checks[0]["occurrenceAddress"])
        io_gain = sorted(relevant_io(trace, runtime_target, last["seq"])
                         - set(state["branches"][branch]["io_families"]))
    active1 = ha_start(trace) is not None
    if not manifest:
        status = "runner_incomplete"
    elif not exact and not matched and not applied and not active1 and manifest.get("returncode") != 0:
        status = "original_junit_pre_failover_flake"
    elif not exact and not matched and not applied and active1:
        status = "unmatched_schedule"
    elif not exact:
        status = "unmatched_or_partial"
    elif not retained:
        status = "target_lost_or_owner_changed"
    elif throws:
        status = "target_exception_candidate"
    else:
        status = "target_retained_nonfatal"
    trial_number = int(TRIAL_RE.fullmatch(directory.name).group(1))
    return {"trial": trial_number, "run": directory.name,
            "adapter_version": adapter_version,
            "branch_id": branch, "seed_run": (
                state["branches"][branch]["seed_run"]
                if branch in state["branches"] else None),
            "target": target, "sequence": sequence,
            "actual_target_root": checks[0]["occurrenceAddress"] if checks else None,
            "selector_key": selector_key(sequence), "retry": retry,
            "started_at": manifest.get("started_at"),
            "finished_at": utc_now(),
            "elapsed_seconds": manifest.get("elapsed_seconds"),
            "junit_exit": manifest.get("returncode"),
            "junit_timeout_exceeded": manifest.get("timeout_exceeded"),
            "matched_faults": len(matched), "applied_faults": len(applied),
            "exact_order_applied": exact,
            "post_fault_hdfs30_checks": len(checks),
            "hdfs30_true_checks": len(true_checks),
            "hdfs30_ioexception_throws": len(throws),
            "coverage_gain": gain, "new_io_families": io_gain,
            "last_applied_seq": last.get("seq") if last else None,
            "status": status,
            "bug_mark": ("candidate_needs_replay_source_review" if throws
                         else "none")}


def feedback_gain(trial: dict) -> bool:
    return (any(trial["coverage_gain"].values())
            or bool(trial["new_io_families"]))


def admit_feedback(state: dict, trial: dict) -> None:
    if (trial["adapter_version"] != state["adapter_version"]
            or not trial["exact_order_applied"]
            or not trial["post_fault_hdfs30_checks"]):
        return
    branch = trial["branch_id"]
    if branch not in state["branches"]:
        return
    item = state["branches"][branch]
    if trial["run"] not in item["coverage_sources"]:
        item["coverage_sources"].append(trial["run"])
    item["io_families"] = sorted(set(item["io_families"])
                                 | set(trial["new_io_families"]))
    if len(trial["sequence"]) >= MAX_FAULTS:
        return
    trace = load_trace(HERE / trial["run"])
    target = item["target"]
    for observed in eligible_heartbeats(trace, target, trial["last_applied_seq"]):
        for fault_type in FAULT_TYPES:
            point = selector(observed, fault_type)
            if point in trial["sequence"]:
                continue
            enqueue(state, branch, HERE / trial["run"],
                    trial["sequence"] + [point],
                    seed_reward=(sum(trial["coverage_gain"].values())
                                 + 5 * len(trial["new_io_families"])))


def legacy_branch(state: dict, sequence: list[dict], number: int) -> str | None:
    source = sequence[0]["sourceKey"]
    candidates = []
    source_seed = None
    for seed in ((HERE / "healthy-node2"), (HERE / "trial-001")):
        if not (seed / "manifest.json").is_file():
            continue
        for target in targets_after_failover(load_trace(seed)):
            if target["sourceKey"] == source:
                candidates.append(target)
        if candidates:
            source_seed = seed
            break
    if not candidates:
        return None
    target = candidates[0]
    key = branch_id(target)
    if key not in state["branches"]:
        state["branches"][key] = {
            "target": target, "seed_run": source_seed.name,
            "coverage_sources": [source_seed.name],
            "io_families": sorted(relevant_io(load_trace(source_seed), target))}
    return key


def import_legacy(state: dict) -> None:
    folders = sorted((p for p in HERE.iterdir() if p.is_dir()
                      and TRIAL_RE.fullmatch(p.name)),
                     key=lambda p: int(TRIAL_RE.fullmatch(p.name).group(1)))
    for directory in folders:
        number = int(TRIAL_RE.fullmatch(directory.name).group(1))
        if number > 3:
            raise RuntimeError("unexpected pre-campaign trial directory: " + str(directory))
        if not (directory / "manifest.json").is_file():
            raise RuntimeError("manual trial still running or incomplete: " + str(directory))
        sequence = parse_plan(HERE / (directory.name + ".plan.tsv"))
        branch = legacy_branch(state, sequence, number)
        trial = evaluate(state, directory, sequence, branch, "pre_gate")
        trial["origin"] = "legacy_pilot"
        state["completed"].append(trial)
        if trial["status"] != "original_junit_pre_failover_flake":
            state["tested_selector_keys"].append(trial["selector_key"])
        for queued in state["queue"]:
            if queued["sequence"] == sequence and queued["branch_id"] == branch:
                state["queue"].remove(queued)
                if trial["status"] == "original_junit_pre_failover_flake":
                    queued["retry"] = 1
                    state["queue"].append(queued)
                break
    state["next_trial"] = max((int(TRIAL_RE.fullmatch(p.name).group(1))
                               for p in folders), default=0) + 1


def initialize() -> dict:
    healthy = choose_healthy()
    state = {"schema_version": 1,
             "adapter_version": ("active1_gate_v2" if healthy == PREFERRED_HEALTHY
                                 else "pre_gate_seed"),
             "budget": {"max_attempts": MAX_ATTEMPTS,
                        "max_faults": MAX_FAULTS,
                        "max_flake_retries": MAX_FLAKE_RETRIES,
                        "max_schedule_retries": MAX_SCHEDULE_RETRIES,
                        "no_gain_valid_limit": NO_GAIN_VALID_LIMIT},
             "healthy_seed": healthy.name, "started_at": utc_now(),
             "branches": {}, "seeded_runs": [], "queue": [],
             "seen_sequences": [], "tested_selector_keys": [],
             "completed": [], "active": None, "next_trial": 1,
             "valid_no_gain_streak": 0, "stop_reason": None}
    seed_run(state, healthy, load_trace(healthy))
    if not state["queue"]:
        raise RuntimeError("healthy HDFS-30 reached but no pre-target heartbeat selectors")
    import_legacy(state)
    save(state)
    return state


def rank(item: dict, state: dict) -> tuple:
    last = item["sequence"][-1]
    actor = last["occurrenceAddress"].split("/actor:", 1)[-1].split("/", 1)[0]
    role = {"nn2": 30, "nn1": 20, "nn3": 5}.get(actor, 0)
    boundary = 4 if last["marker"].endswith(":RESPONSE") else 0
    type_score = {"IOException": 3, "EOFException": 2,
                  "SocketTimeoutException": 1}.get(last["faultType"], 0)
    family = (last["marker"], actor)
    used_families = {(
        trial["sequence"][-1]["marker"],
        trial["sequence"][-1]["occurrenceAddress"].split("/actor:", 1)[-1].split("/", 1)[0])
        for trial in state["completed"] if trial["sequence"]}
    novelty = 7 if family not in used_families else 0
    waiting = min(8, len(state["completed"]) - item["queued_at_attempt"])
    # A strict fault that removes the selected recovery target is poor seed
    # feedback. Prefer a different actor/boundary family at the next clean
    # checkpoint while retaining the untested queue for exploration.
    lost_in_family = sum(
        trial["adapter_version"] == state["adapter_version"]
        and trial["exact_order_applied"]
        and not trial["post_fault_hdfs30_checks"]
        and trial["sequence"][-1]["marker"] == family[0]
        and trial["sequence"][-1]["occurrenceAddress"].split(
            "/actor:", 1)[-1].split("/", 1)[0] == family[1]
        for trial in state["completed"] if trial["sequence"])
    loss_penalty = min(16, 8 * lost_in_family)
    score = role + boundary + type_score + novelty + waiting - loss_penalty
    score += min(item.get("seed_reward", 0), 10) + 2 * (len(item["sequence"]) - 1)
    return (score, -item.get("retry", 0), item["id"])


def choose(state: dict) -> dict | None:
    tested = set(state["tested_selector_keys"])
    state["queue"] = [item for item in state["queue"]
                      if selector_key(item["sequence"]) not in tested]
    if not state["queue"]:
        return None
    chosen = max(state["queue"], key=lambda item: rank(item, state))
    state["queue"].remove(chosen)
    return chosen


def runner_pid(active: dict) -> int | None:
    candidates = [active["pid"]] if isinstance(active.get("pid"), int) else []
    # Close the crash window between Popen and checkpointing its PID.
    candidates.extend(int(path.name) for path in Path("/proc").iterdir()
                      if path.name.isdigit() and int(path.name) not in candidates)
    for pid in candidates:
        try:
            command = (Path("/proc") / str(pid) / "cmdline").read_bytes()
            arguments = command.split(b"\0")
            if (str(RUNNER).encode() in arguments
                    and str(HERE / active["run"]).encode() in arguments):
                return pid
        except OSError:
            continue
    return None


def update_after_trial(state: dict, trial: dict, item: dict) -> None:
    trial["origin"] = "campaign"
    trial["resume_retry"] = item.get("resume_retry", 0)
    trial["schedule_retry"] = item.get("schedule_retry", 0)
    state["completed"].append(trial)
    if trial["status"] == "original_junit_pre_failover_flake":
        if item["retry"] < MAX_FLAKE_RETRIES:
            retry_item = dict(item, retry=item["retry"] + 1,
                              queued_at_attempt=len(state["completed"]))
            state["queue"].append(retry_item)
    elif trial["status"] == "interrupted_runner_no_manifest":
        if item.get("resume_retry", 0) < MAX_FLAKE_RETRIES:
            retry_item = dict(item, resume_retry=item.get("resume_retry", 0) + 1,
                              queued_at_attempt=len(state["completed"]))
            state["queue"].append(retry_item)
        else:
            state["tested_selector_keys"].append(trial["selector_key"])
    elif trial["status"] == "unmatched_schedule":
        if item.get("schedule_retry", 0) < MAX_SCHEDULE_RETRIES:
            retry_item = dict(item,
                              schedule_retry=item.get("schedule_retry", 0) + 1,
                              queued_at_attempt=len(state["completed"]))
            state["queue"].append(retry_item)
        else:
            state["tested_selector_keys"].append(trial["selector_key"])
    else:
        state["tested_selector_keys"].append(trial["selector_key"])
    if trial["exact_order_applied"] and trial["post_fault_hdfs30_checks"]:
        state["valid_no_gain_streak"] = (
            0 if feedback_gain(trial) else state["valid_no_gain_streak"] + 1)
    admit_feedback(state, trial)
    target_reaching_faulted = (trial["exact_order_applied"]
                              and trial["post_fault_hdfs30_checks"])
    if (trial["adapter_version"] == state["adapter_version"]
            and (trial["junit_exit"] == 0 or target_reaching_faulted)):
        seed_run(state, HERE / trial["run"], load_trace(HERE / trial["run"]),
                 seed_reward=sum(trial["coverage_gain"].values()),
                 allow_junit_failure=target_reaching_faulted)
    state["active"] = None
    save(state)


def recover_active(state: dict) -> None:
    active = state.get("active")
    if active is None:
        return
    directory = HERE / active["run"]
    deadline = active.get("started_epoch", 0) + JUNIT_TIMEOUT + 90
    while not (directory / "manifest.json").is_file() and runner_pid(active) is not None:
        if time.time() > deadline:
            raise RuntimeError("previous HA JUnit runner is still alive past its deadline: "
                               + active["run"])
        time.sleep(2)
    if (directory / "manifest.json").is_file():
        trial = evaluate(state, directory, active["item"]["sequence"],
                         active["item"]["branch_id"], state["adapter_version"],
                         active["item"]["retry"])
    else:
        # An interrupted attempt remains accounted for and its directory is
        # never overwritten. The next invocation starts at a fresh number.
        trial = {"trial": active["number"], "run": active["run"],
                 "adapter_version": state["adapter_version"],
                 "branch_id": active["item"]["branch_id"],
                 "seed_run": active["item"]["seed_run"],
                 "target": state["branches"][active["item"]["branch_id"]]["target"],
                 "sequence": active["item"]["sequence"],
                 "selector_key": selector_key(active["item"]["sequence"]),
                 "retry": active["item"]["retry"], "finished_at": utc_now(),
                 "elapsed_seconds": None, "junit_exit": None,
                 "junit_timeout_exceeded": None, "matched_faults": 0,
                 "applied_faults": 0, "exact_order_applied": False,
                 "post_fault_hdfs30_checks": 0, "hdfs30_true_checks": 0,
                 "hdfs30_ioexception_throws": 0,
                 "coverage_gain": {kind: 0 for kind in COVERAGE},
                 "new_io_families": [], "last_applied_seq": None,
                 "status": "interrupted_runner_no_manifest", "bug_mark": "none"}
    update_after_trial(state, trial, active["item"])


def ledger_rows(state: dict) -> list[dict]:
    result = []
    for trial in state["completed"]:
        target = trial.get("target") or {}
        sequence = trial.get("sequence") or []
        last = sequence[-1] if sequence else {}
        result.append({
            "trial": trial["trial"], "finished_at_utc": trial.get("finished_at"),
            "system": "HDFS 3.4.3", "case": "HDFS-30",
            "source_file": "BlockRecoveryWorker.java", 
            "function": "BlockRecoveryWorker.getActiveNamenodeForBP",
            "target_site": TARGET_SITE, "target_throw_line": 583,
            "seed_run": trial.get("seed_run"), "adapter_version": trial.get("adapter_version"),
            "target_source": target.get("sourceKey"),
            "target_block": target.get("blockId"),
            "target_recovery_id": target.get("recoveryId"),
            "seed_target_root": target.get("occurrenceAddress"),
            "actual_target_root": trial.get("actual_target_root"),
            "fault_count": len(sequence), "fault_source": last.get("sourceKey"),
            "fault_actor": last.get("occurrenceAddress", "").split("/actor:", 1)[-1].split("/", 1)[0],
            "fault_boundary": last.get("marker"), "fault_type": last.get("faultType"),
            "selector": json.dumps(sequence, sort_keys=True, separators=(",", ":")),
            "retry": trial.get("retry"),
            "resume_retry": trial.get("resume_retry", 0),
            "schedule_retry": trial.get("schedule_retry", 0),
            "junit_exit": trial.get("junit_exit"),
            "elapsed_seconds": trial.get("elapsed_seconds"),
            "matched_faults": trial.get("matched_faults"),
            "applied_faults": trial.get("applied_faults"),
            "exact_order_applied": trial.get("exact_order_applied"),
            "target_checks_after_fault": trial.get("post_fault_hdfs30_checks"),
            "target_true_checks": trial.get("hdfs30_true_checks"),
            "target_ioexception_throws": trial.get("hdfs30_ioexception_throws"),
            "new_probes": trial.get("coverage_gain", {}).get("probes"),
            "new_methods": trial.get("coverage_gain", {}).get("methods"),
            "new_covered_branch_count_ids": trial.get("coverage_gain", {}).get("branch_counts"),
            "new_io_families": len(trial.get("new_io_families", [])),
            "status": trial.get("status"), "bug_mark": trial.get("bug_mark"),
            "run_directory": str(HERE / trial["run"]),
        })
    return result


def save(state: dict) -> None:
    atomic_json(STATE, state)
    rows = ledger_rows(state)
    if rows:
        columns = list(rows[0])
        temporary = LEDGER.with_name(LEDGER.name + ".tmp")
        with temporary.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, columns)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, LEDGER)
    counts = Counter(trial["status"] for trial in state["completed"])
    summary = {"schema_version": 1, "updated_at": utc_now(),
               "healthy_seed": state["healthy_seed"],
               "adapter_version": state["adapter_version"],
               "attempts_used": len(state["completed"]),
               "attempt_budget": MAX_ATTEMPTS,
               "legacy_pilots": sum(trial.get("origin") == "legacy_pilot"
                                    for trial in state["completed"]),
               "strict_applied": sum(trial["exact_order_applied"]
                                     for trial in state["completed"]),
               "target_retaining": sum(bool(trial["post_fault_hdfs30_checks"])
                                       for trial in state["completed"]),
               "target_exception_candidates": sum(bool(trial["hdfs30_ioexception_throws"])
                                                   for trial in state["completed"]),
               "valid_no_gain_streak": state["valid_no_gain_streak"],
               "status_counts": dict(counts), "queued": len(state["queue"]),
               "active": state["active"], "stop_reason": state["stop_reason"],
               "ledger": str(LEDGER)}
    atomic_json(SUMMARY, summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true",
                        help="initialize/import pilots and exit without running JUnit")
    parser.add_argument("--status", action="store_true",
                        help="read current summary without starting a campaign")
    args = parser.parse_args()
    if args.status:
        print(SUMMARY.read_text() if SUMMARY.is_file() else
              json.dumps({"status": "not_initialized"}))
        return
    with LOCK.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit("another HA campaign process holds " + str(LOCK)) from exc
        state = json.loads(STATE.read_text()) if STATE.is_file() else initialize()
        recover_active(state)
        if args.prepare:
            save(state)
            print(SUMMARY.read_text())
            return
        if state["stop_reason"] == "paused" and not PAUSE.exists():
            state["stop_reason"] = None
        while len(state["completed"]) < MAX_ATTEMPTS:
            if PAUSE.exists():
                state["stop_reason"] = "paused"
                save(state)
                break
            if state["valid_no_gain_streak"] >= NO_GAIN_VALID_LIMIT:
                state["stop_reason"] = "eight_valid_target_retaining_trials_without_feedback_gain"
                save(state)
                break
            item = choose(state)
            if item is None:
                state["stop_reason"] = "queue_exhausted"
                save(state)
                break
            number = state["next_trial"]
            state["next_trial"] += 1
            directory = HERE / f"trial-{number:03d}"
            if directory.exists():
                raise RuntimeError("refusing to overwrite prior trial: " + str(directory))
            directory.mkdir()
            plan = HERE / (directory.name + ".plan.tsv")
            if plan.exists():
                raise RuntimeError("refusing to overwrite prior plan: " + str(plan))
            atomic_text(plan, plan_lines(item["sequence"]))
            state["active"] = {"number": number, "run": directory.name,
                               "item": item, "started_epoch": time.time(),
                               "pid": None}
            save(state)
            command = [sys.executable, str(RUNNER), "--output", str(directory),
                       "--timeout", str(JUNIT_TIMEOUT), "--instrument",
                       "--plan", str(plan)]
            with (directory / "driver.log").open("w") as log:
                process = subprocess.Popen(command, cwd=HERE, stdout=log,
                                           stderr=subprocess.STDOUT)
                state["active"]["pid"] = process.pid
                save(state)
                process.wait()
            trial = evaluate(state, directory, item["sequence"],
                             item["branch_id"], state["adapter_version"],
                             item["retry"])
            update_after_trial(state, trial, item)
            print(json.dumps({"trial": number, "status": trial["status"],
                              "exact": trial["exact_order_applied"],
                              "target_retained": bool(trial["post_fault_hdfs30_checks"]),
                              "bug_mark": trial["bug_mark"],
                              "elapsed_seconds": trial["elapsed_seconds"]}),
                  flush=True)
        else:
            state["stop_reason"] = "attempt_budget_reached"
            save(state)
        print(SUMMARY.read_text())


if __name__ == "__main__":
    main()
