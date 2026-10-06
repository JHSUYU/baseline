#!/usr/bin/env python3
"""Resumable coverage and observed-I/O fault campaign for HDFS-20.

Uses only case-local source probes, JaCoCo feedback, and the unchanged
pipeline-recovery MiniDFSCluster JUnit. No graph or closure artifacts are read.
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


CASE = Path(__file__).resolve().parents[1]
CAMPAIGN = CASE / "campaign"
HEALTHY = CASE / "healthy/instrumented"
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
TEST_METHOD = "testPipelineRecoveryOnOOB"
TARGET_SITE = "BPOfferService.updateActorStatesFromHeartbeat:606"


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
    return {key: row[key] for key in ("marker", "api", "ordinal")}


def point_id(value: dict) -> str:
    return f"{value['marker']}:{value['api']}:{value['ordinal']}"


def family_id(value: dict) -> str:
    return f"{value['marker']}:{value['api']}"


def sequence_id(sequence: list[dict]) -> str:
    canonical = json.dumps(sequence, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def relevant(row: dict) -> bool:
    return (row.get("event") == "IO_OBSERVED" and
            row.get("marker") in {"RPC_RESPONSE", "FILE_FLUSH"} and
            (row["marker"] != "FILE_FLUSH" or
             row.get("api", "").endswith(":durable")))


def base_priority(row: dict) -> int:
    if row["marker"] == "FILE_FLUSH":
        return 95 if row["api"].startswith("editLog:") else 25
    api = row["api"]
    if api.endswith(".sendHeartbeat"):
        return 210
    if api.endswith(".registerDatanode"):
        return 185
    if api.endswith(".versionRequest"):
        return 175
    if api.endswith(".shutdownDatanode"):
        return 170
    if api.endswith(".updatePipeline"):
        return 155
    if api.endswith(".updateBlockForPipeline"):
        return 150
    if api.endswith(".addBlock"):
        return 145
    if api.endswith(".fsync"):
        return 135
    if api.endswith(".create"):
        return 125
    if api.endswith(".blockReceivedAndDeleted"):
        return 105
    if api.endswith(".complete"):
        return 95
    return 60


def exception_options(row: dict) -> tuple[str, ...]:
    return (("IOException", "EOFException", "SocketTimeoutException")
            if row["marker"] == "RPC_RESPONSE" else ("IOException",))


def next_target_context(trace: list[dict], after_seq: int) -> dict | None:
    """Bind a fault to the observed guard in the restarted BPOfferService."""
    guards = [row for row in trace if row.get("event") == "TARGET_GUARD"
              and row.get("site") == TARGET_SITE and row["seq"] > after_seq
              and row.get("bposInstance", 0) >= 2]
    if not guards:
        return None
    guard = min(guards, key=lambda row: row["seq"])
    return {"bpos_instance": guard["bposInstance"],
            "actor_instance": guard["actorInstance"],
            "healthy_txid": guard["txid"],
            "source_guard_ordinal": guard["ordinal"]}


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
        if state["case_id"] != "HDFS-20":
            raise RuntimeError("wrong campaign checkpoint")
        return state
    healthy = events(TRACE)
    guards = [row for row in healthy if row.get("event") == "TARGET_GUARD"
              and row.get("site") == TARGET_SITE]
    if (len(guards) < 2 or not all(row["allowed"] for row in guards) or
            not any(row.get("bposInstance", 0) >= 2 for row in guards)):
        raise RuntimeError("original healthy JUnit did not reach the exact guard")
    final_guard = max(row["seq"] for row in guards
                      if row.get("bposInstance", 0) >= 2)
    candidates = [row for row in healthy if relevant(row)
                  and row["seq"] < final_guard]
    if not candidates:
        raise RuntimeError("healthy test has no relevant observed I/O")
    state = {"case_id": "HDFS-20", "schema_version": 1,
             "budget": {"max_trials": 80, "max_faults": 8},
             "extension_budget": {"max_trials": 128, "max_faults": 10},
             "queue": [], "current": None, "completed": [],
             "seen_sequence_ids": [], "started_at_utc": now(),
             "healthy_target_guards": len(guards),
             "healthy_io_points": len([r for r in healthy if relevant(r)])}
    # Exact identities originate only in the successful original JUnit.
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


def artifacts(number: int, sequence: list[dict]) -> tuple[Path, dict, float]:
    name = f"trial-{number:02d}"
    out = CAMPAIGN / name
    out.mkdir(parents=True, exist_ok=True)
    plan = CAMPAIGN / "plans" / f"{name}.tsv"
    if not plan.is_file():
        atomic_text(plan, "".join(
            f"{p['marker']}\t{p['api']}\t{p['ordinal']}\t{p['exception']}\n"
            for p in sequence))
    elif plan.read_text() != "".join(
            f"{p['marker']}\t{p['api']}\t{p['ordinal']}\t{p['exception']}\n"
            for p in sequence):
        raise RuntimeError(f"resumed plan changed for {name}")
    run_command(SSH + ["mkdir", "-p", str(plan.parent)])
    run_command(RSYNC + [str(plan), REMOTE + ":" + str(plan)])
    started = time.monotonic()
    remote_out = CASE / "campaign" / name
    if not remote_exists(remote_out / "manifest.json"):
        command = SSH + ["python3", str(CASE / "system-test/run_original.py"),
                         "--method", TEST_METHOD, "--name", f"campaign/{name}",
                         "--probe", "--coverage", "--plan", str(plan),
                         "--timeout-seconds", "120"]
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
    requested = [(p["marker"], p["api"], p["ordinal"], p["exception"])
                 for p in sequence]
    matched = [row for row in trace if row.get("event") == "FAULT_MATCHED"]
    applied = [row for row in trace if row.get("event") == "FAULT_APPLIED"]
    actual = [(r["marker"], r["api"], r["ordinal"], r["exception"])
              for r in applied]
    strict = actual == requested and len(matched) == len(requested)
    last_fault_seq = max((row["seq"] for row in applied), default=-1)
    any_guards_after = [row for row in trace
                        if row.get("event") == "TARGET_GUARD" and
                        row.get("site") == TARGET_SITE and
                        row["seq"] > last_fault_seq >= 0]
    expected_bpos = item["target_context"]["bpos_instance"]
    expected_actor = item["target_context"]["actor_instance"]
    guards_after = [row for row in any_guards_after
                    if row["bposInstance"] == expected_bpos and
                    row["actorInstance"] == expected_actor]
    target_after = bool(guards_after)
    false_guards = {(row["ordinal"], row["bposInstance"],
                     row["actorInstance"])
                    for row in guards_after if not row["allowed"]}
    exact_exceptions = [row for row in trace
                        if row.get("event") == "TARGET_EXCEPTION" and
                        row.get("site") == TARGET_SITE and
                        row.get("type") == "java.lang.AssertionError" and
                        row.get("seq", -1) > last_fault_seq >= 0 and
                        (row.get("ordinal"), row.get("bposInstance"),
                         row.get("actorInstance")) in false_guards]
    any_context_exceptions = [row for row in trace
                              if row.get("event") == "TARGET_EXCEPTION" and
                              row.get("site") == TARGET_SITE and
                              row.get("type") == "java.lang.AssertionError" and
                              row.get("seq", -1) > last_fault_seq >= 0]
    candidate = strict and target_after and bool(exact_exceptions)
    other_candidate = strict and bool(any_context_exceptions) and not candidate
    status = ("unmatched" if not strict else
              "target_exception_candidate" if candidate else
              "other_context_exception_candidate" if other_candidate else
              "lost_target" if not target_after else
              "workload_timeout" if manifest["exit"] == 124 else "checked")
    ids = coverage_ids(out / "coverage.tsv")
    observed = [row for row in trace if relevant(row)]
    observed_ids = {point_id(row) for row in observed}
    families = {family_id(row) for row in observed}
    admitted = strict and target_after
    new_coverage = ids - union_coverage if admitted else set()
    new_io = observed_ids - union_io if admitted else set()
    new_families = families - union_families if admitted else set()
    row = {"trial": name(number), "number": number,
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
           "target_exception_any_context_after_fault_count": (
               len(any_context_exceptions)),
           "status": status,
           "bug_mark": "candidate" if candidate or other_candidate else "none",
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


def mutation_priority(parent: dict, sequence: list[dict],
                      healthy_points: set[str]) -> int:
    """Favor new production behavior and I/O families, with waiting fairness."""
    production_gain = sum(identifier.startswith(("METHOD\t", "BRANCH_UNIT\t"))
                          for identifier in parent["new_coverage_ids"])
    last = sequence[-1]
    last_family = family_id(last)
    earlier_families = [family_id(point) for point in sequence[:-1]]
    repeated_file_family = (last["marker"] == "FILE_FLUSH" and
                            last_family in earlier_families)
    priority = (110 + 6 * len(sequence) + min(production_gain, 12) * 3 +
                min(len(parent["new_io_family_ids"]), 3) * 20 +
                (15 if last_family not in earlier_families else 0) +
                (10 if point_id(last) not in healthy_points else 0) -
                (30 if repeated_file_family else 0) -
                (20 if production_gain == 0 and
                 not parent["new_io_family_ids"] else 0) -
                (50 if parent["seconds"] > 75 else 0))
    return max(priority, 10)


def mutate(state: dict, row: dict) -> None:
    if (row["status"] != "checked" or
            len(row["sequence"]) >= state["budget"]["max_faults"]):
        return
    trace = events(Path(row["trace"]))
    lower = row["last_applied_seq"]
    guards = [e["seq"] for e in trace if e.get("event") == "TARGET_GUARD"
              and e.get("site") == TARGET_SITE and e["seq"] > lower
              and e.get("bposInstance") == row["target_context_expected"]["bpos_instance"]
              and e.get("actorInstance") == row["target_context_expected"]["actor_instance"]]
    if not guards:
        return
    # Only I/O preceding the same restarted BPOS/actor can mutate this seed.
    upper = max(guards)
    used = {point_id(p) for p in row["sequence"]}
    healthy_points = {point_id(p) for p in events(TRACE) if relevant(p)}
    candidates = [e for e in trace if relevant(e) and
                  lower < e["seq"] < upper and point_id(e) not in used]
    candidates.sort(key=lambda e: (point_id(e) in healthy_points,
                                   -base_priority(e), -e["seq"]))
    selected = []
    family_counts: dict[str, int] = {}
    for observed in candidates:
        family = family_id(observed)
        if family_counts.get(family, 0) >= 2:
            continue
        selected.append(observed)
        family_counts[family] = family_counts.get(family, 0) + 1
        if len(selected) == 8:
            break
    for observed in selected:
        target_context = next_target_context(trace, observed["seq"])
        if target_context is None:
            continue
        for exception in exception_options(observed):
            selector = {**point(observed), "exception": exception}
            new_sequence = row["sequence"] + [selector]
            enqueue(state, new_sequence,
                    f"mutated {row['trial']} from observed post-fault I/O "
                    f"seq {observed['seq']}",
                    mutation_priority(row, new_sequence, healthy_points),
                    target_context)


def choose(state: dict) -> dict:
    completed = len(state["completed"])
    retention: dict[str, list[int]] = {}
    for row in state["completed"]:
        if not row["strict_injection"]:
            continue
        api = row["sequence"][-1]["api"]
        counts = retention.setdefault(api, [0, 0])
        counts[0] += 1
        counts[1] += int(row["target_guard_after_last_fault"])

    def retention_bonus(item: dict) -> int:
        attempts, reached = retention.get(item["sequence"][-1]["api"], [0, 0])
        if attempts < 3:
            return 0
        return round(60 * (reached / attempts - 0.5))

    best = max(range(len(state["queue"])),
               key=lambda index: (state["queue"][index]["priority"] +
                                  retention_bonus(state["queue"][index]) +
                                  min(completed - state["queue"][index][
                                      "queued_after_trial"], 64),
                                  -state["queue"][index]["queued_after_trial"],
                                  -index))
    return state["queue"].pop(best)


def persist(state: dict) -> dict:
    atomic_json(STATE, state)
    rows = state["completed"]
    result = json.loads(RESULT.read_text())
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
              "phase_complete_pending_ha" if
              state.get("phase_pivot_reason") and
              len(rows) >= state["budget"]["max_trials"] else
              "quality_complete" if (len(rows) >= state["budget"]["max_trials"]
                                     or not state["queue"] and not state["current"])
              else "fuzzing")
    result.update({"status": status, "fault_trials": len(rows),
                   "baseline_trial_budget": state["budget"]["max_trials"],
                   "baseline_max_faults_per_sequence": state["budget"]["max_faults"],
                   "selection_policy_version": "retention_feedback_v3",
                   "requested_fault_events": sum(r["requested_faults"] for r in rows),
                   "matched_fault_events": sum(r["matched_faults"] for r in rows),
                   "applied_fault_events": sum(r["applied_faults"] for r in rows),
                   "strict_injection_trials": strict_count,
                   "strict_injections": strict_count,
                   "fully_applied_trials": strict_count,
                   "post_fault_target_reach_trials": target_after_count,
                   "target_after_fault": target_after_count,
                   "target_exception_after_fault_trials": sum(
                       r["strict_injection"] and
                       r["target_exception_after_fault_count"] > 0 for r in rows),
                   "target_exception_any_context_after_fault_trials": sum(
                       r["strict_injection"] and
                       r["target_exception_any_context_after_fault_count"] > 0
                       for r in rows),
                   "workload_timeout_trials": sum(r["junit_exit"] == 124
                                                  for r in rows),
                   "oracle_candidates": sum(r["bug_mark"] == "candidate" for r in rows),
                   "bug_mark": "candidate" if any(r["bug_mark"] == "candidate"
                                                    for r in rows) else "none",
                   "coverage_gain": gains,
                   "elapsed_seconds": round(
                       result["healthy_test_elapsed_seconds"] +
                       result["healthy_probe_elapsed_seconds"] +
                       sum(r["seconds"] for r in rows), 3),
                   "evidence": {**result.get("evidence", {}),
                                "checkpoint": "independent-coverage-io/campaign/checkpoint.json",
                                "trial_ledger": "independent-coverage-io/campaign/trial-ledger.csv",
                                "trial_dir": "independent-coverage-io/campaign/trial-XX/"},
                   "updated_at_utc": now()})
    if status == "quality_complete" and rows:
        result["completed_at_utc"] = rows[-1]["completed_at_utc"]
        result["stop_reason"] = (
            "Current trial budget reached; no new production method/branch "
            "coverage or stable I/O family appeared in its final eight "
            "trials." if
            len(rows) >= state["budget"]["max_trials"] else
            "Observed I/O mutation queue exhausted.")
    if status == "phase_complete_pending_ha":
        result["stop_reason"] = state["phase_pivot_reason"]
    atomic_json(RESULT, result)
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
    return result


def main() -> None:
    state = initialize()
    healthy_coverage = coverage_ids(COVERAGE)
    healthy_rows = [r for r in events(TRACE) if relevant(r)]
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
            if (state["budget"]["max_trials"] == 80 and
                    any(any(identifier.startswith(("METHOD\t", "BRANCH_UNIT\t"))
                            for identifier in row["new_coverage_ids"]) or
                        row["new_io_family_ids"]
                        for row in state["completed"][-8:])):
                state["budget"] = dict(state["extension_budget"])
                print("extended to 128 trials / 10 faults", flush=True)
                persist(state)
            else:
                break
        if state["current"] is None:
            state["current"] = choose(state)
            atomic_json(STATE, state)
        number = len(state["completed"]) + 1
        item = state["current"]
        out, manifest, seconds = artifacts(number, item["sequence"])
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
    print("campaign checkpoint count", len(state["completed"]), flush=True)
    persist(state)


if __name__ == "__main__":
    main()
