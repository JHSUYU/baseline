#!/usr/bin/env python3
"""Resumable HDFS-40 coverage and observed I/O exception campaign.

The workload is the unchanged Hadoop 3.4.3 MiniDFSCluster JUnit
TestFileAppend#testFailedAppendBlockRejection. The target and I/O probes are
case-local; no GraphChecker, closure graph, or Docker result is consumed.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shlex
import shutil
import subprocess
import time

CASE = Path(__file__).resolve().parents[1]
CAMPAIGN = CASE / "campaign"
SEED = CASE / "healthy/campaign-seed"
STATE = CAMPAIGN / "checkpoint.json"
LEDGER = CAMPAIGN / "trial-ledger.csv"
RESULT = CASE.parent / "result.json"
REMOTE_ROOT = Path("/users/ZhenyuLi/hdfs40-coverage-io")
REMOTE = "ZhenyuLi@node2"
SSH = ["ssh", "-i", "/users/ZhenyuLi/.ssh/id_ed25519_nodes",
       "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", REMOTE]
RSYNC = ["rsync", "-a", "-e",
         "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes"]
TEST = "org.apache.hadoop.hdfs.TestFileAppend#testFailedAppendBlockRejection"
SITE = "FSDirAppendOp.appendFile:136-139"
TARGET_PATH = "/test"
TARGET_BLOCK = 1073741825
KEYS = ("marker", "api", "endpoint", "ordinal", "exception")


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


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open() as stream:
        for line in stream:
            if line.strip():
                out.append(json.loads(line))
    if out and [row.get("seq") for row in out] != list(range(1, len(out) + 1)):
        raise ValueError(f"nonmonotonic raw trace: {path}")
    return out


def coverage(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.rstrip("\n") for line in path.open() if line.strip()}


def point(row: dict) -> dict:
    return {key: row[key] for key in ("marker", "api", "endpoint", "ordinal")}


def point_id(row: dict) -> str:
    return "|".join(str(row[key]) for key in ("marker", "api", "endpoint", "ordinal"))


def family_id(row: dict) -> str:
    return "|".join(str(row[key]) for key in ("marker", "api", "endpoint"))


def seq_id(sequence: list[dict]) -> str:
    blob = json.dumps(sequence, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def relevant(row: dict) -> bool:
    if row.get("event") != "IO_OBSERVED":
        return False
    marker = row.get("marker")
    api = row.get("api", "")
    if marker in ("RPC_SEND", "RPC_RESPONSE_WAIT"):
        return ("[append:/test]" in api or
                "[blockReceivedAndDeleted:block=1073741825]" in api)
    return marker == "FILE_FLUSH" and api == "editLog:durable"


def injectable(row: dict) -> bool:
    # The edit-log flush method has a no-op early return. Its entry marker is
    # useful for observation but is not an exact file-write fault boundary.
    return relevant(row) and row.get("marker") in (
        "RPC_SEND", "RPC_RESPONSE_WAIT")


def base_score(row: dict) -> int:
    marker, api = row["marker"], row["api"]
    if "blockReceivedAndDeleted" in api:
        return 370 if marker == "RPC_SEND" else 330
    if "[append:/test]" in api:
        return 230 if marker == "RPC_SEND" else 270
    return 75


def exceptions(row: dict) -> tuple[str, ...]:
    return (("IOException", "EOFException", "SocketTimeoutException")
            if row["marker"].startswith("RPC_") else ("IOException",))


def target_guards(trace: list[dict], after_seq: int = -1) -> list[dict]:
    return [row for row in trace if row.get("event") == "TARGET_GUARD"
            and row.get("site") == SITE and row.get("path") == TARGET_PATH
            and row.get("blockId") == TARGET_BLOCK and row.get("complete")
            and row["seq"] > after_seq]


def next_target(trace: list[dict], after_seq: int) -> dict | None:
    guards = target_guards(trace, after_seq)
    if not guards:
        return None
    g = guards[0]
    return {"path": g["path"], "block_id": g["blockId"],
            "healthy_ordinal": g["ordinal"]}


def enqueue(state: dict, sequence: list[dict], context: dict,
            reason: str, score: int) -> None:
    identifier = seq_id(sequence)
    if identifier in state["seen"]:
        return
    state["seen"].append(identifier)
    state["queue"].append({"id": identifier, "sequence": sequence,
                           "context": context, "reason": reason,
                           "score": score, "queued_at": len(state["completed"])})


def initialize() -> dict:
    if STATE.exists():
        state = read_json(STATE)
        if state["case_id"] != "HDFS-40" or state["seed_test"] != TEST:
            raise RuntimeError("checkpoint belongs to another case or JUnit")
        return state
    manifest = read_json(SEED / "manifest.json")
    trace = events(SEED / "trace/runtime_trace.jsonl")
    guards = target_guards(trace)
    if manifest["exit"] != 0 or len(guards) < 2:
        raise RuntimeError("no passing original JUnit with repeated exact nonfatal target checks")
    if any(row["fatal"] for row in guards) or any(
            row.get("event") == "TARGET_EXCEPTION" for row in trace):
        raise RuntimeError("selected healthy seed already has target fatal exception")
    first, last = guards[0]["seq"], guards[-1]["seq"]
    points = [row for row in trace if injectable(row) and row["seq"] < last]
    if not points or not any(row["seq"] < first for row in points):
        raise RuntimeError("healthy seed lacks target-preceding observed I/O")
    state = {"schema_version": 1, "case_id": "HDFS-40", "seed_test": TEST,
             "started_at_utc": now(), "seed_guards": len(guards),
             "seed_relevant_io": len(points),
             "budget": {"max_attempts": 80, "max_faults": 8},
             "extension": {"max_attempts": 128, "max_faults": 10},
             "extended": False, "active": None, "queue": [], "seen": [],
             "completed": [], "stop_reason": None}
    for row in sorted(points, key=lambda x: (-base_score(x), -x["seq"])):
        context = next_target(trace, row["seq"])
        if context is None:
            continue
        for error in exceptions(row):
            enqueue(state, [{**point(row), "exception": error}], context,
                    f"healthy I/O seq {row['seq']}", base_score(row) +
                    (3 if error == "IOException" else 0))
    atomic_json(STATE, state)
    return state


def remote_exists(path: Path) -> bool:
    return subprocess.run(SSH + ["test", "-f", str(path)],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def run(args: list[str], log: Path | None = None) -> None:
    if log is None:
        subprocess.run(args, check=True)
        return
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as stream:
        subprocess.run(args, stdout=stream, stderr=subprocess.STDOUT,
                       check=True)


def fetch(remote: Path, local: Path) -> None:
    local.parent.mkdir(parents=True, exist_ok=True)
    run(RSYNC + [f"{REMOTE}:{remote}", str(local)])


def artifacts(number: int, item: dict) -> tuple[Path, dict, float]:
    name = f"trial-{number:03d}"
    out = CAMPAIGN / name
    out.mkdir(parents=True, exist_ok=True)
    plan = CAMPAIGN / "plans" / f"{name}.tsv"
    plan_content = "".join("\t".join(str(row[k]) for k in KEYS) + "\n"
                           for row in item["sequence"])
    if plan.exists() and plan.read_text() != plan_content:
        raise RuntimeError(f"resumed plan changed: {plan}")
    if not plan.exists():
        atomic_text(plan, plan_content)
    remote_plan = REMOTE_ROOT / "campaign/plans" / plan.name
    run(SSH + ["mkdir", "-p", str(remote_plan.parent)])
    run(RSYNC + [str(plan), f"{REMOTE}:{remote_plan}"])
    remote_out = REMOTE_ROOT / "campaign" / name
    started = time.monotonic()
    if not remote_exists(remote_out / "manifest.json"):
        command = SSH + ["python3", str(REMOTE_ROOT / "system-test/run_original.py"),
                         "--test-class", "append", "--method",
                         "testFailedAppendBlockRejection", "--name",
                         f"campaign/{name}", "--probe", "--coverage", "--plan",
                         str(remote_plan), "--timeout-seconds", "180"]
        run(command, out / "driver.log")
    if remote_exists(remote_out / "jacoco.exec") and not remote_exists(
            remote_out / "coverage.tsv"):
        command = SSH + ["python3", str(REMOTE_ROOT / "system-test/run_coverage.py"),
                         "--exec", str(remote_out / "jacoco.exec"), "--output",
                         str(remote_out / "coverage.tsv")]
        run(command, out / "coverage-driver.log")
    for filename, required in (("manifest.json", True),
                               ("trace/runtime_trace.jsonl", False),
                               ("jacoco.exec", False),
                               ("coverage.tsv", False)):
        source = remote_out / filename
        if remote_exists(source):
            fetch(source, out / filename)
        elif required:
            raise RuntimeError(f"missing remote manifest: {source}")
    remote_log = remote_out / "logs/runtime.log"
    local_log = out / "junit.log.gz"
    if remote_exists(remote_log) and not local_log.exists():
        command = SSH + ["gzip", "-c", str(remote_log)]
        with local_log.open("wb") as stream:
            subprocess.run(command, stdout=stream, check=True)
        with gzip.open(local_log, "rb") as stream:
            stream.read(1)
    manifest = read_json(out / "manifest.json")
    if manifest["test"] != TEST:
        raise RuntimeError("trial did not run expected original JUnit")
    return out, manifest, max(time.monotonic() - started,
                               manifest["elapsed_seconds"])


def analyze(number: int, item: dict, out: Path, manifest: dict,
            seconds: float, union_cov: set[str], union_io: set[str],
            union_families: set[str]) -> dict:
    trace = events(out / "trace/runtime_trace.jsonl")
    selected = item["sequence"]
    matched = [row for row in trace if row.get("event") == "FAULT_MATCHED"]
    applied = [row for row in trace if row.get("event") == "FAULT_APPLIED"]
    requested = [tuple(row[key] for key in KEYS) for row in selected]
    actual = [tuple(row.get(key) for key in KEYS) for row in applied]
    strict = actual == requested and len(matched) == len(requested)
    last_fault = max((row["seq"] for row in applied), default=-1)
    guards = target_guards(trace, last_fault) if last_fault >= 0 else []
    context = item["context"]
    same = [g for g in guards if g["path"] == context["path"] and
            g["blockId"] == context["block_id"]]
    guard_keys = {(g["path"], g["blockId"], g["ordinal"])
                  for g in same if g["fatal"]}
    throws = [row for row in trace if row.get("event") == "TARGET_EXCEPTION"
              and row.get("site") == SITE and row.get("type") == "java.io.IOException"
              and row.get("seq", -1) > last_fault >= 0
              and (row.get("path"), row.get("blockId"), row.get("ordinal"))
              in guard_keys]
    candidate = strict and bool(same) and bool(throws)
    status = ("unmatched_or_partial" if not strict else
              "target_exception_candidate" if candidate else
              "lost_target" if not same else
              "workload_timeout" if manifest["exit"] == 124 else
              "checked")
    identifiers = coverage(out / "coverage.tsv")
    observed = [row for row in trace if relevant(row)]
    admitted = strict and bool(same)
    new_cov = identifiers - union_cov if admitted else set()
    new_io = {point_id(row) for row in observed} - union_io if admitted else set()
    new_families = {family_id(row) for row in observed} - union_families if admitted else set()
    result = {"trial": number, "id": f"trial-{number:03d}",
              "sequence_id": item["id"], "selection_reason": item["reason"],
              "sequence": selected, "context": context,
              "requested_faults": len(selected), "matched_faults": len(matched),
              "applied_faults": len(applied), "strict_injection": strict,
              "last_applied_seq": last_fault,
              "target_after_fault": bool(same),
              "post_fault_guard_ordinals": [g["ordinal"] for g in same],
              "post_fault_fatal_count": sum(g["fatal"] for g in same),
              "post_fault_target_exception_count": len(throws),
              "status": status, "bug_mark": "candidate" if candidate else "none",
              "junit_exit": manifest["exit"],
              "junit_elapsed_seconds": manifest["elapsed_seconds"],
              "elapsed_seconds": round(seconds, 3),
              "coverage_ids": len(identifiers),
              "new_coverage_ids": sorted(new_cov),
              "new_coverage_count": len(new_cov),
              "new_io_point_ids": sorted(new_io),
              "new_io_family_ids": sorted(new_families),
              "trace": str(out / "trace/runtime_trace.jsonl"),
              "jacoco": str(out / "jacoco.exec"),
              "junit_log_gzip": str(out / "junit.log.gz"),
              "manifest": str(out / "manifest.json"),
              "completed_at_utc": now()}
    atomic_json(out / "trial-result.json", result)
    return result


def mutate(state: dict, row: dict) -> None:
    if not (row["strict_injection"] and row["target_after_fault"]):
        return
    if len(row["sequence"]) >= state["budget"]["max_faults"]:
        return
    trace = events(Path(row["trace"]))
    upper = max(g["seq"] for g in target_guards(trace, row["last_applied_seq"]))
    used = {point_id(p) for p in row["sequence"]}
    candidates = [r for r in trace if injectable(r)
                  and row["last_applied_seq"] < r["seq"] < upper
                  and point_id(r) not in used]
    # One mutation per semantic family per parent, favor production gain.
    candidates.sort(key=lambda r: (-base_score(r), -r["seq"]))
    seen_families: set[str] = set()
    production_gain = sum(id.startswith(("METHOD\t", "BRANCH_UNIT\t"))
                          for id in row["new_coverage_ids"])
    for observed in candidates:
        family = family_id(observed)
        if family in seen_families:
            continue
        seen_families.add(family)
        context = next_target(trace, observed["seq"])
        if context is None:
            continue
        for error in exceptions(observed):
            sequence = row["sequence"] + [{**point(observed),
                                            "exception": error}]
            enqueue(state, sequence, context, f"mutation of {row['id']}",
                    165 + 16 * len(sequence) + min(production_gain, 15) * 4 +
                    min(len(row["new_io_family_ids"]), 3) * 20 +
                    base_score(observed) // 5)
        if len(seen_families) >= 6:
            break


def choose(state: dict) -> dict:
    queued = state["queue"]
    age = len(state["completed"])
    ranked = sorted(queued, key=lambda item: -(
        item["score"] + min(age - item["queued_at"], 80)))
    top = ranked[:min(16, len(ranked))]
    rng = random.Random(0x40_3043 + age)
    weights = [max(1, item["score"] - top[-1]["score"] + 10)
               for item in top]
    selected = rng.choices(top, weights=weights, k=1)[0]
    queued.remove(selected)
    return selected


def healthy_seconds() -> float:
    return sum(read_json(p)["elapsed_seconds"]
               for p in (CASE / "healthy").glob("*/manifest.json"))


def publish(state: dict, union_cov: set[str], seed_cov: set[str]) -> None:
    rows = state["completed"]
    strict = [r for r in rows if r["strict_injection"]]
    valid = [r for r in strict if r["target_after_fault"]]
    candidates = [r for r in valid if r["post_fault_target_exception_count"]]
    delta = union_cov - seed_cov
    gains = {kind: sum(key.startswith(kind + "\t") for key in delta)
             for kind in ("METHOD", "BRANCH_UNIT", "PROBE")}
    phase = ("candidate_review" if candidates else
             "pending_final_audit" if state["stop_reason"] else "fuzzing")
    current = read_json(RESULT)
    current.update({"case_id": "HDFS-40", "status": phase,
                    "cluster_test": TEST,
                    "alternate_cluster_tests": [
                        "org.apache.hadoop.hdfs.TestFileAppendRestart#testAppendWithPipelineRecovery",
                        "org.apache.hadoop.hdfs.TestFileAppend4#testUpdateNeededReplicationsForAppendedFile"],
                    "target_reached": True,
                    "healthy_target_checks": state["seed_guards"],
                    "healthy_target_fatal": False,
                    "expected_fatal_control": {
                        "test": "org.apache.hadoop.hdfs.TestFileAppend4#testAppendInsufficientLocations",
                        "healthy_target_exception_expected": True,
                        "excluded_from_bug_oracle": True,
                        "manifest": "independent-coverage-io/healthy/append4-expected-fatal/manifest.json"},
                    "methodology": "original_embedded_cluster_junit_case_local_source_probes_jacoco_coverage_io",
                    "io_injection_scope": "semantic RPC send and response-wait boundaries; edit-log flush method-entry is observation-only",
                    "fault_trials": len(rows),
                    "strict_injections": len(strict),
                    "fully_applied_trials": len(strict),
                    "target_after_fault": len(valid),
                    "target_exception_after_fault_trials": len(candidates),
                    "coverage_gain": gains,
                    "elapsed_seconds": round(healthy_seconds() +
                                             sum(r["elapsed_seconds"] for r in rows), 3),
                    "fault_trial_elapsed_seconds": round(
                        sum(r["elapsed_seconds"] for r in rows), 3),
                    "healthy_calibration_elapsed_seconds": round(healthy_seconds(), 3),
                    "budget": state["budget"],
                    "extension_budget": state["extension"],
                    "stop_reason": state["stop_reason"],
                    "bug_mark": "candidate" if candidates else "none",
                    "evidence": {"seed": "independent-coverage-io/healthy/campaign-seed",
                                 "expected_fatal_control":
                                    "independent-coverage-io/healthy/append4-expected-fatal",
                                 "checkpoint": "independent-coverage-io/campaign/checkpoint.json",
                                 "trial_ledger": "independent-coverage-io/campaign/trial-ledger.csv",
                                 "trial_dir": "independent-coverage-io/campaign/trial-NNN"},
                    "updated_at_utc": now()})
    atomic_json(RESULT, current)
    fields = ("trial", "id", "status", "requested_faults", "matched_faults",
              "applied_faults", "strict_injection", "target_after_fault",
              "post_fault_fatal_count", "post_fault_target_exception_count",
              "junit_exit", "elapsed_seconds", "new_coverage_count",
              "new_io_family_ids", "bug_mark", "sequence_id")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        values = {key: row.get(key, "") for key in fields}
        values["new_io_family_ids"] = ";".join(row["new_io_family_ids"])
        writer.writerow(values)
    atomic_text(LEDGER, output.getvalue())


def main() -> None:
    state = initialize()
    seed_cov = coverage(SEED / "coverage.tsv")
    union_cov = set(seed_cov)
    seed_events = events(SEED / "trace/runtime_trace.jsonl")
    union_io = {point_id(r) for r in seed_events if relevant(r)}
    union_families = {family_id(r) for r in seed_events if relevant(r)}
    for row in state["completed"]:
        union_cov.update(row["new_coverage_ids"])
        union_io.update(row["new_io_point_ids"])
        union_families.update(row["new_io_family_ids"])
    publish(state, union_cov, seed_cov)
    stop_after = int(os.environ.get("HDFS40_STOP_AFTER", "0"))
    while (state["active"] or state["queue"]) and not state["stop_reason"]:
        if (CAMPAIGN / "pause.request").exists():
            state["stop_reason"] = "paused_by_case_owner"
            break
        if shutil.disk_usage(CASE).free < 1024 ** 3:
            state["stop_reason"] = "local_disk_below_1GiB"
            break
        if len(state["completed"]) >= state["budget"]["max_attempts"]:
            effective = [r for r in state["completed"]
                         if r["strict_injection"] and r["target_after_fault"]]
            if (not state["extended"] and len(effective) >= 8 and
                    any(any(identifier.startswith(("METHOD\t", "BRANCH_UNIT\t"))
                            for identifier in row["new_coverage_ids"]) or
                        row["new_io_family_ids"] for row in effective[-8:])):
                state["budget"] = dict(state["extension"])
                state["extended"] = True
                atomic_json(STATE, state)
            else:
                state["stop_reason"] = "attempt_budget_reached"
                break
        if state["active"] is None:
            state["active"] = choose(state)
            atomic_json(STATE, state)
        number = len(state["completed"]) + 1
        item = state["active"]
        out, manifest, seconds = artifacts(number, item)
        trial_file = out / "trial-result.json"
        row = (read_json(trial_file) if trial_file.exists() else
               analyze(number, item, out, manifest, seconds,
                       union_cov, union_io, union_families))
        state["completed"].append(row)
        state["active"] = None
        union_cov.update(row["new_coverage_ids"])
        union_io.update(row["new_io_point_ids"])
        union_families.update(row["new_io_family_ids"])
        mutate(state, row)
        atomic_json(STATE, state)
        publish(state, union_cov, seed_cov)
        print(json.dumps({"trial": number, "status": row["status"],
                          "strict": row["strict_injection"],
                          "target_after": row["target_after_fault"],
                          "new_coverage": row["new_coverage_count"],
                          "seconds": row["elapsed_seconds"]}), flush=True)
        if row["bug_mark"] == "candidate":
            state["stop_reason"] = "candidate_requires_source_review"
            break
        if stop_after and len(state["completed"]) >= stop_after:
            print(json.dumps({"clean_pause_after": stop_after,
                              "queued": len(state["queue"])}), flush=True)
            return
    if not state["stop_reason"]:
        state["stop_reason"] = "observed_io_queue_exhausted"
    atomic_json(STATE, state)
    publish(state, union_cov, seed_cov)
    print(json.dumps({"stop_reason": state["stop_reason"],
                      "attempts": len(state["completed"]),
                      "queued": len(state["queue"])}), flush=True)


if __name__ == "__main__":
    main()
