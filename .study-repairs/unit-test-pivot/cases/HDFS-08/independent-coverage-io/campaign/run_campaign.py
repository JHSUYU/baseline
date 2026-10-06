#!/usr/bin/env python3
"""Resumable independent coverage and I/O fault campaign for HDFS-08.

Uses only case-local source probes, JaCoCo feedback, and the unchanged
TestQuorumJournalManager MiniJournalCluster JUnit. No graph artifact is read.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time

from aggregate_result import publish_case_result


CASE = Path(__file__).resolve().parents[1]
STAGE = os.environ.get("HDFS08_STAGE", "singlewriter")
if STAGE not in {"singlewriter", "multiwriter"}:
    raise ValueError("HDFS08_STAGE must be singlewriter or multiwriter")
CAMPAIGN = CASE / ("campaign" if STAGE == "singlewriter"
                   else "campaign-multiwriter")
HEALTHY = CASE / ("healthy/instrumented-segment-context"
                  if STAGE == "singlewriter" else "healthy/multiwriter-probe")
PAXOS_HEALTHY = CASE / "healthy/multiwriter-paxos-probe"
TRACE = HEALTHY / "trace/runtime_trace.jsonl"
COVERAGE = HEALTHY / "coverage.tsv"
STATE = CAMPAIGN / "checkpoint.json"
RESULT = CASE.parent / "result.json"
LEDGER = CAMPAIGN / "trial-ledger.csv"
REMOTE = "ZhenyuLi@node1"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", REMOTE]
RSYNC = ["rsync", "-a", "-e",
         "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes"]
TEST_METHOD = ("testSingleWriter" if STAGE == "singlewriter"
               else "testChangeWritersLogsInSync")
TARGET_SITE = "Journal.checkRequest:486"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temp.open("w") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def atomic_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def coverage_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    with path.open() as stream:
        return {line.rstrip("\n") for line in stream if line.strip()}


def point(row: dict) -> dict:
    return {key: row[key] for key in ("marker", "api", "node", "ordinal")}


def point_id(value: dict) -> str:
    return f"{value['marker']}:{value['api']}:{value['node']}:{value['ordinal']}"


def family_id(value: dict) -> str:
    return f"{value['marker']}:{value['api']}:{value['node']}"


def sequence_id(sequence: list[dict]) -> str:
    canonical = json.dumps(sequence, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def relevant(row: dict) -> bool:
    return (row.get("event") == "IO_OBSERVED" and
            row.get("marker") in {"RPC_RESPONSE", "EPOCH_FILE_WRITE",
                                  "EDITLOG_FLUSH", "PAXOS_FILE_WRITE"} and
            row.get("node") != "unknown" and
            (row["marker"] != "EDITLOG_FLUSH" or
             row.get("api", "").endswith(":durable")))


def base_priority(row: dict) -> int:
    if STAGE == "multiwriter":
        # A second QJM advances the promised epoch.  Exercise that handoff
        # and its recovery RPCs before the finalization response.
        if row["marker"] == "PAXOS_FILE_WRITE":
            base = 195 if row["api"].endswith(":before") else 190
        elif row["marker"] == "EPOCH_FILE_WRITE":
            base = 175 if row["api"].startswith("last-promised") else 130
        elif row["marker"] == "EDITLOG_FLUSH":
            base = 110
        else:
            api = row["api"]
            base = (185 if "newEpoch" in api else
                    170 if "prepareRecovery" in api else
                    165 if "acceptRecovery" in api else
                    145 if "finalizeLogSegment" in api else
                    125 if "journal" in api else 75)
        return base + (8 if row["node"] == "jn2" else 0)
    if row["marker"] == "EPOCH_FILE_WRITE":
        base = 150 if row["api"].startswith("last-promised") else 135
    elif row["marker"] == "EDITLOG_FLUSH":
        base = 110
    else:
        api = row["api"]
        base = (165 if "finalizeLogSegment" in api else
                155 if "newEpoch" in api else
                150 if "acceptRecovery" in api else
                145 if "prepareRecovery" in api else
                125 if "journal" in api else 75)
    return base + (8 if row["node"] == "jn2" else 0)


def exception_options(row: dict) -> tuple[str, ...]:
    return (("IOException", "EOFException", "SocketTimeoutException")
            if row["marker"] == "RPC_RESPONSE" else ("IOException",))


def next_target_context(trace: list[dict], after_seq: int) -> dict | None:
    """Bind the fault to the next selected jn2 finalize segment."""
    guards = [row for row in trace if row.get("event") == "TARGET_GUARD"
              and row.get("site") == TARGET_SITE and row.get("node") == "jn2"
              and row.get("caller") == "finalizeLogSegment" and
              row["seq"] > after_seq]
    if not guards:
        return None
    guard = min(guards, key=lambda row: row["seq"])
    return {"node": guard["node"], "caller": guard["caller"],
            "journal_id": guard["journalId"],
            "segment_start_txid": guard["segmentStartTxId"],
            "segment_end_txid": guard["segmentEndTxId"],
            "source_guard_ordinal": guard["ordinal"],
            "source_request_epoch": guard["requestEpoch"],
            "source_request_serial": guard["serial"]}


def same_target_context(row: dict, expected: dict) -> bool:
    return (row.get("node") == expected["node"] and
            row.get("caller") == expected["caller"] and
            row.get("journalId") == expected["journal_id"] and
            row.get("segmentStartTxId") == expected["segment_start_txid"] and
            row.get("segmentEndTxId") == expected["segment_end_txid"])


def enqueue(state: dict, sequence: list[dict], reason: str,
            priority: int, target_context: dict) -> None:
    identifier = sequence_id(sequence)
    if identifier in state["seen_sequence_ids"]:
        return
    state["seen_sequence_ids"].append(identifier)
    state["queue"].append({"sequence_id": identifier, "sequence": sequence,
                           "reason": reason, "priority": priority,
                           "target_context": target_context,
                           "queued_after_trial": len(state["completed"])})


def initialize() -> dict:
    if STATE.is_file():
        state = json.loads(STATE.read_text())
        if state["case_id"] != "HDFS-08" or state.get("stage", "singlewriter") != STAGE:
            raise RuntimeError("wrong campaign checkpoint")
        return state
    healthy = events(TRACE)
    guards = [row for row in healthy if row.get("event") == "TARGET_GUARD"
              and row.get("site") == TARGET_SITE and row.get("node") == "jn2"
              and row.get("caller") == "finalizeLogSegment"]
    expected_segments = ({(1, 3), (4, 4)} if STAGE == "singlewriter"
                         else {(1, 3)})
    if (len(guards) != len(expected_segments) or
            not all(row["allowed"] for row in guards) or
            {(row["segmentStartTxId"], row["segmentEndTxId"])
             for row in guards} != expected_segments or
            (STAGE == "multiwriter" and not all(
                row["requestEpoch"] == row["promisedEpoch"] == 2
                for row in guards))):
        raise RuntimeError("original JUnit did not reach expected exact jn2 guards")
    final_guard = max(row["seq"] for row in guards)
    candidates = [row for row in healthy if relevant(row)
                  and row["seq"] < final_guard]
    if not candidates:
        raise RuntimeError("healthy test has no relevant observed I/O")
    single_completed = 0
    if STAGE == "multiwriter":
        single_completed = len(json.loads((CASE / "campaign/checkpoint.json").read_text())[
            "completed"])
    state = {"case_id": "HDFS-08", "stage": STAGE, "schema_version": 1,
             "instrumentation_version": "source_probes_v1",
             "singlewriter_completed_before_stage": single_completed,
             "budget": {"max_trials": 80 - single_completed,
                        "max_faults": 8},
             "extension_budget": {"max_trials": 128 - single_completed,
                                  "max_faults": 10},
             "queue": [], "current": None, "completed": [],
             "seen_sequence_ids": [], "started_at_utc": now(),
             "healthy_target_guards": len(guards),
             "healthy_io_points": len([r for r in healthy if relevant(r)])}
    # Exact identities originate only in the successful, unmodified JUnit.
    for row in sorted(candidates,
                      key=lambda item: (-base_priority(item), -item["seq"])):
        target_context = next_target_context(healthy, row["seq"])
        if target_context is None:
            continue
        for exception in exception_options(row):
            value = {**point(row), "exception": exception}
            enqueue(state, [value], f"healthy I/O seq {row['seq']}",
                    base_priority(row) + (3 if exception == "IOException" else 0),
                    target_context)
    atomic_json(STATE, state)
    return state


def remote_exists(path: Path) -> bool:
    return subprocess.run(SSH + ["test", "-f", str(path)],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def run_command(args: list[str], log: Path | None = None) -> None:
    if log is None:
        subprocess.run(args, check=True)
    else:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w") as stream:
            subprocess.run(args, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)


def artifacts(number: int, sequence: list[dict],
              paxos_enabled: bool) -> tuple[Path, dict, float]:
    name = f"trial-{number:02d}"
    out = CAMPAIGN / name
    out.mkdir(parents=True, exist_ok=True)
    plan = CAMPAIGN / "plans" / f"{name}.tsv"
    if not plan.is_file():
        atomic_text(plan, "".join(
            f"{p['marker']}\t{p['api']}\t{p['node']}\t{p['ordinal']}\t"
            f"{p['exception']}\n"
            for p in sequence))
    elif plan.read_text() != "".join(
            f"{p['marker']}\t{p['api']}\t{p['node']}\t{p['ordinal']}\t"
            f"{p['exception']}\n"
            for p in sequence):
        raise RuntimeError(f"resumed plan changed for {name}")
    run_command(SSH + ["mkdir", "-p", str(plan.parent)])
    run_command(RSYNC + [str(plan), REMOTE + ":" + str(plan)])
    started = time.monotonic()
    remote_out = CAMPAIGN / name
    if not remote_exists(remote_out / "manifest.json"):
        command = SSH + ["python3", str(CASE / "system-test/run_original.py"),
                         "--method", TEST_METHOD,
                         "--name", f"{CAMPAIGN.name}/{name}",
                         "--probe", "--coverage", "--plan", str(plan),
                         "--timeout-seconds", "150"]
        if paxos_enabled:
            command.append("--paxos")
        run_command(command, out / "driver.log")
    if remote_exists(remote_out / "jacoco.exec") and not remote_exists(
            remote_out / "coverage.tsv"):
        command = SSH + ["python3", str(CASE / "system-test/run_coverage.py"),
                         "--exec", str(remote_out / "jacoco.exec"),
                         "--output", str(remote_out / "coverage.tsv")]
        run_command(command, out / "coverage-driver.log")
    for filename, required in (("manifest.json", True),
                               ("trace/runtime_trace.jsonl", False),
                               ("coverage.tsv", False)):
        remote_file = remote_out / filename
        if remote_exists(remote_file):
            local_file = out / filename
            local_file.parent.mkdir(parents=True, exist_ok=True)
            run_command(RSYNC + [REMOTE + ":" + str(remote_file),
                                 str(local_file)])
        elif required:
            raise RuntimeError(f"remote trial lacks {remote_file}")
    manifest = json.loads((out / "manifest.json").read_text())
    elapsed = max(time.monotonic() - started, manifest["elapsed_seconds"])
    return out, manifest, elapsed


def analyze_trial(state: dict, number: int, item: dict, out: Path,
                  manifest: dict, seconds: float,
                  union_coverage: set[str], union_io: set[str],
                  union_families: set[str]) -> dict:
    sequence = item["sequence"]
    trace = events(out / "trace/runtime_trace.jsonl")
    requested = [(p["marker"], p["api"], p["node"], p["ordinal"], p["exception"])
                 for p in sequence]
    matched = [row for row in trace if row.get("event") == "FAULT_MATCHED"]
    applied = [row for row in trace if row.get("event") == "FAULT_APPLIED"]
    actual = [(r["marker"], r["api"], r["node"], r["ordinal"], r["exception"])
              for r in applied]
    strict = actual == requested and len(matched) == len(requested)
    last_fault_seq = max((row["seq"] for row in applied), default=-1)
    any_guards_after = [row for row in trace
                        if row.get("event") == "TARGET_GUARD" and
                        row.get("site") == TARGET_SITE and
                        row["seq"] > last_fault_seq >= 0]
    guards_after = [row for row in any_guards_after
                    if same_target_context(row, item["target_context"])]
    target_after = bool(guards_after)
    false_guards = {(row["ordinal"], row["node"],
                     row["segmentStartTxId"], row["segmentEndTxId"])
                    for row in guards_after if not row["allowed"]}
    exact_exceptions = [row for row in trace
                        if row.get("event") == "TARGET_EXCEPTION" and
                        row.get("site") == TARGET_SITE and
                        row.get("type") == "java.io.IOException" and
                        row.get("message", "").startswith("IPC's epoch ") and
                        row.get("seq", -1) > last_fault_seq >= 0 and
                        (row.get("ordinal"), row.get("node"),
                         row.get("segmentStartTxId"),
                         row.get("segmentEndTxId")) in false_guards]
    candidate = strict and target_after and bool(exact_exceptions)
    status = ("unmatched" if not strict else
              "lost_target" if not target_after else
              "target_exception_candidate" if candidate else "checked")
    ids = coverage_ids(out / "coverage.tsv")
    observed = [row for row in trace if relevant(row)]
    observed_ids = {point_id(row) for row in observed}
    families = {family_id(row) for row in observed}
    admitted = strict and target_after
    new_coverage = ids - union_coverage if admitted else set()
    new_io = observed_ids - union_io if admitted else set()
    new_families = families - union_families if admitted else set()
    row = {"trial": name(number), "number": number,
           "instrumentation_version": (
               "paxos_hook_v2" if manifest.get("paxos") else "source_probes_v1"),
           "test_method": TEST_METHOD, "sequence": sequence,
           "sequence_id": item["sequence_id"],
           "selection_reason": item["reason"],
           "requested_faults": len(sequence), "matched_faults": len(matched),
           "applied_faults": len(applied), "strict_injection": strict,
           "last_applied_seq": last_fault_seq,
           "target_context_expected": item["target_context"],
           "target_guard_after_last_fault": target_after,
           "target_guard_after_last_fault_count": len(guards_after),
           "other_context_guard_after_last_fault_count": (
               len(any_guards_after) - len(guards_after)),
           "target_actual_guard_ordinals_after_fault": [
               r["ordinal"] for r in guards_after],
           "target_outcomes_after_fault": [r["allowed"] for r in guards_after],
           "target_exception_after_fault_count": len(exact_exceptions),
           "status": status, "bug_mark": "candidate" if candidate else "none",
           "junit_exit": manifest["exit"], "junit_seconds": manifest["elapsed_seconds"],
           "seconds": round(seconds, 3),
           "coverage_ids": len(ids),
           "coverage_by_kind": {kind: sum(identifier.startswith(kind + "\t")
                                            for identifier in ids)
                                for kind in ("METHOD", "BRANCH_UNIT", "PROBE")},
           "new_coverage_ids": sorted(new_coverage),
           "new_coverage_count": len(new_coverage),
           "new_io_point_ids": sorted(new_io),
           "new_io_family_ids": sorted(new_families),
           "observed_io_points": len(observed),
           "trace": str(out / "trace/runtime_trace.jsonl"),
           "coverage": str(out / "coverage.tsv"),
           "manifest": str(out / "manifest.json"),
           "completed_at_utc": now()}
    atomic_json(out / "trial-result.json", row)
    return row


def name(number: int) -> str:
    return f"trial-{number:02d}"


def mutate(state: dict, row: dict) -> None:
    if (row["status"] != "checked" or
            len(row["sequence"]) >= state["budget"]["max_faults"]):
        return
    trace = events(Path(row["trace"]))
    lower = row["last_applied_seq"]
    guards = [e["seq"] for e in trace if e.get("event") == "TARGET_GUARD"
              and e.get("site") == TARGET_SITE and e.get("node") == "jn2"
              and e.get("caller") == "finalizeLogSegment" and
              e["seq"] > lower]
    if not guards:
        return
    # The JUnit finalizes two distinct segments.  A new fault after the first
    # guard may precede the second; bind it to that segment's target instance.
    upper = max(guards)
    used = {point_id(p) for p in row["sequence"]}
    healthy_points = {point_id(p) for p in events(TRACE) if relevant(p)}
    if state.get("instrumentation_version") == "paxos_hook_v2":
        healthy_points.update(point_id(p) for p in events(
            PAXOS_HEALTHY / "trace/runtime_trace.jsonl") if relevant(p))
    candidates = [e for e in trace if relevant(e) and
                  lower < e["seq"] < upper and point_id(e) not in used]
    candidates.sort(key=lambda e: (point_id(e) in healthy_points,
                                   -base_priority(e), -e["seq"]))
    for observed in candidates[:8]:
        target_context = next_target_context(trace, observed["seq"])
        if target_context is None:
            continue
        for exception in exception_options(observed):
            selector = {**point(observed), "exception": exception}
            enqueue(state, row["sequence"] + [selector],
                    f"mutated {row['trial']} from observed post-fault I/O "
                    f"seq {observed['seq']}",
                    180 + 20 * len(row["sequence"]) +
                    min(row["new_coverage_count"], 50) * 3 +
                    len(row["new_io_point_ids"]) * 15 +
                    (25 if point_id(observed) not in healthy_points else 0),
                    target_context)


def choose(state: dict) -> dict:
    completed = len(state["completed"])
    # The original CrashFuzz favors an untested I/O fault ID.  Cap the
    # inherited coverage score so repeated exceptions at one epoch file do
    # not consume the whole budget before other observed RPC/file families.
    tested_families = {family_id(row["sequence"][-1])
                       for row in state["completed"]}
    tested_fault_ids = {family_id(row["sequence"][-1]) + ":" +
                        row["sequence"][-1]["exception"]
                        for row in state["completed"]}

    def score(index: int) -> tuple[int, int, int]:
        item = state["queue"][index]
        last = item["sequence"][-1]
        family = family_id(last)
        fault_id = family + ":" + last["exception"]
        return (min(item["priority"], 230) +
                (80 if family not in tested_families else 0) +
                (30 if fault_id not in tested_fault_ids else 0) +
                min(completed - item["queued_after_trial"], 64) -
                15 * max(len(item["sequence"]) - 4, 0),
                -item["queued_after_trial"],
                -index)

    best = max(range(len(state["queue"])),
               key=score)
    return state["queue"].pop(best)


def persist(state: dict) -> dict:
    atomic_json(STATE, state)
    rows = state["completed"]
    healthy_coverage = coverage_ids(COVERAGE)
    union = set(healthy_coverage)
    for row in rows:
        union.update(row["new_coverage_ids"])
    kinds = ("METHOD", "BRANCH_UNIT", "PROBE")
    gains = {kind: sum(identifier.startswith(kind + "\t")
                       for identifier in union - healthy_coverage)
             for kind in kinds}
    strict_count = sum(row["strict_injection"] for row in rows)
    target_after_count = sum(
        row["strict_injection"] and row["target_guard_after_last_fault"]
        for row in rows)
    status = ("candidate_review" if any(r["bug_mark"] == "candidate"
                                        for r in rows) else
              "budget_reached" if len(rows) >= state["budget"]["max_trials"]
              else "queue_exhausted" if not state["queue"] and not state["current"]
              else "paused_for_multiwriter" if STAGE == "singlewriter" and
              (CAMPAIGN / "stage-pause.json").is_file() else "fuzzing")
    original_manifest = CASE / "healthy" / (
        "original/manifest.json" if STAGE == "singlewriter" else
        "multiwriter-original/manifest.json")
    probe_manifest = HEALTHY / "manifest.json"
    healthy_seconds = (json.loads(original_manifest.read_text())["elapsed_seconds"] +
                       json.loads(probe_manifest.read_text())["elapsed_seconds"])
    if (STAGE == "multiwriter" and
            (CAMPAIGN / "recorder-migration.json").is_file()):
        healthy_seconds += json.loads((PAXOS_HEALTHY / "manifest.json").read_text())[
            "elapsed_seconds"]
    stage_result = {"case_id": "HDFS-08", "stage": STAGE,
                    "instrumentation_version": state.get(
                        "instrumentation_version", "source_probes_v1"),
                    "cluster_test": TEST_METHOD, "status": status,
                    "fault_trials": len(rows),
                    "trial_budget": state["budget"]["max_trials"],
                    "max_faults_per_sequence": state["budget"]["max_faults"],
                    "requested_fault_events": sum(r["requested_faults"] for r in rows),
                    "matched_fault_events": sum(r["matched_faults"] for r in rows),
                    "applied_fault_events": sum(r["applied_faults"] for r in rows),
                    "strict_injection_trials": strict_count,
                    "post_fault_target_reach_trials": target_after_count,
                    "target_exception_after_fault_trials": sum(
                        r["strict_injection"] and
                        r["target_exception_after_fault_count"] > 0 for r in rows),
                    "oracle_candidates": sum(r["bug_mark"] == "candidate" for r in rows),
                    "target_lost_trials": sum(r["status"] == "lost_target" for r in rows),
                    "unmatched_trials": sum(r["status"] == "unmatched" for r in rows),
                    "multi_fault_trials": sum(r["requested_faults"] > 1 for r in rows),
                    "max_requested_faults": max((r["requested_faults"] for r in rows),
                                                default=0),
                    "coverage_gain_within_stage": gains,
                    "new_io_family_ids_within_stage": sorted({family
                        for row in rows for family in row["new_io_family_ids"]}),
                    "elapsed_seconds": round(healthy_seconds +
                                             sum(r["seconds"] for r in rows), 3),
                    "healthy_seconds": healthy_seconds,
                    "updated_at_utc": now()}
    atomic_json(CAMPAIGN / "stage-result.json", stage_result)
    fields = ("number", "trial", "status", "requested_faults",
              "matched_faults", "applied_faults", "strict_injection",
              "target_guard_after_last_fault", "target_exception_after_fault_count",
              "junit_exit", "seconds", "new_coverage_count",
              "new_io_point_ids", "bug_mark", "sequence_id")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        item = {key: row.get(key, "") for key in fields}
        item["new_io_point_ids"] = ";".join(row["new_io_point_ids"])
        writer.writerow(item)
    atomic_text(LEDGER, output.getvalue())
    return publish_case_result()


def main() -> None:
    state = initialize()
    healthy_coverage = coverage_ids(COVERAGE)
    healthy_rows = [r for r in events(TRACE) if relevant(r)]
    if state.get("instrumentation_version") == "paxos_hook_v2":
        healthy_rows.extend(r for r in events(
            PAXOS_HEALTHY / "trace/runtime_trace.jsonl") if relevant(r))
    union_coverage = set(healthy_coverage)
    union_io = {point_id(r) for r in healthy_rows}
    union_families = {family_id(r) for r in healthy_rows}
    for row in state["completed"]:
        union_coverage.update(row["new_coverage_ids"])
        union_io.update(row["new_io_point_ids"])
        union_families.update(row["new_io_family_ids"])
    persist(state)
    while state["current"] or state["queue"]:
        if len(state["completed"]) >= state["budget"]["max_trials"]:
            if (STAGE == "multiwriter" and
                    state["budget"]["max_trials"] ==
                    state["extension_budget"]["max_trials"] - 48 and
                    any(any(identifier.startswith(("METHOD\t", "BRANCH_UNIT\t"))
                            for identifier in row["new_coverage_ids"]) or
                        row["new_io_family_ids"]
                        for row in state["completed"][-8:])):
                state["budget"] = dict(state["extension_budget"])
                print("extended HDFS-08 case to 128 total trials / 10 faults",
                      flush=True)
                persist(state)
            else:
                break
        if state["current"] is None:
            state["current"] = choose(state)
            atomic_json(STATE, state)
        number = len(state["completed"]) + 1
        item = state["current"]
        out, manifest, seconds = artifacts(
            number, item["sequence"],
            state.get("instrumentation_version") == "paxos_hook_v2")
        trial_result = out / "trial-result.json"
        row = (json.loads(trial_result.read_text()) if trial_result.is_file()
               else analyze_trial(state, number, item, out, manifest, seconds,
                                  union_coverage, union_io, union_families))
        state["completed"].append(row)
        state["current"] = None
        union_coverage.update(row["new_coverage_ids"])
        union_io.update(row["new_io_point_ids"])
        union_families.update(row["new_io_family_ids"])
        mutate(state, row)
        result = persist(state)
        print(json.dumps({key: row[key] for key in
                          ("trial", "status", "requested_faults", "applied_faults",
                           "target_guard_after_last_fault", "new_coverage_count",
                           "seconds")}), flush=True)
        if row["bug_mark"] == "candidate":
            print("Exact target exception candidate: pause for same-selector "
                  "replay and source review", flush=True)
            break
        if os.environ.get("HDFS08_RUN_ONE") == "1":
            print("stopped after one resumed trial for recorder migration",
                  flush=True)
            break
    print("campaign checkpoint count", len(state["completed"]), flush=True)
    persist(state)


if __name__ == "__main__":
    main()
