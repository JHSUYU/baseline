#!/usr/bin/env python3
"""Checkpointed actor-bound exception fuzzing of original HDFS-32 JUnit."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import time

from launch import launch

HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
LOCK = HERE / "campaign.lock"
RESULT = HERE.parent / "result.json"
CASES = ("HDFS-32",)
SELECTED_ACTOR = "episode1/dn1"
SELECTED_SERVICE = "namesServerId1"
METRICS = ("probes", "methods", "branch_counts")
BASE_GOAL, EXTENDED_GOAL = 80, 128
BASE_DEPTH, EXTENDED_DEPTH = 8, 10
BASE_ATTEMPTS, EXTENDED_ATTEMPTS = 320, 512
ERRORS = {"RPC": ("IOException", "EOFException", "SocketTimeoutException"),
          "FILE": ("IOException",)}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".tmp")
    pending.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    pending.replace(path)


def events(directory: Path) -> list[dict]:
    path = directory / "runtime_trace.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def coverage(directory: Path, metric: str) -> set[str]:
    path = directory / ("covered_" + metric + ".txt")
    return set(path.read_text().splitlines()) if path.is_file() else set()


def io_family(event: dict) -> str:
    return "|".join(event.get(key, "") for key in ("marker", "api", "actor", "service"))


def point(event: dict, error: str) -> dict:
    return {key: event[key] for key in ("marker", "api", "actor", "service", "ordinal")} | {"exception": error}


def point_id(sequence: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sequence, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()[:24]


def raw_context(rows: list[dict]) -> tuple[str, str]:
    pools = [e for e in rows if e.get("event") == "NN_POOL"
             and e.get("nnIndex") == "0" and e.get("service") == SELECTED_SERVICE]
    lists = [e for e in rows if e.get("event") == "CLUSTER_DN_LIST"
             and e.get("count") == "2" and
             e.get("actors") == "episode1/dn0,episode1/dn1"]
    if not pools or not pools[-1].get("rawBpid") or not lists:
        raise RuntimeError("two-DN or NN0 block-pool runtime identity absent")
    return SELECTED_ACTOR, pools[-1]["rawBpid"]


def inferred_bpid(rows: list[dict]) -> str | None:
    found = {e.get("rawBpid") for e in rows
             if e.get("event") in ("BP_ACTOR_BEGIN", "POOL_ADD")
             and e.get("actor") == SELECTED_ACTOR
             and e.get("service") == SELECTED_SERVICE and e.get("rawBpid")}
    return next(iter(found)) if len(found) == 1 else None


def target(rows: list[dict]) -> dict | None:
    chosen = [e for e in rows if e.get("event") == "TARGET_CHECK"
              and e.get("selected") == "true"]
    return chosen[0] if len(chosen) == 1 else None


def target_throws(rows: list[dict], check: dict) -> list[dict]:
    return [e for e in rows if e.get("event") == "TARGET_THROW"
            and e.get("selected") == "true" and e.get("seq", 0) > check["seq"]
            and e.get("actor") == check.get("actor")
            and e.get("uuid") == check.get("uuid")
            and e.get("rawBpid") == check.get("rawBpid")]


def signature(rows: list[dict], check: dict) -> dict:
    throws = target_throws(rows, check)
    return {"actor": check["actor"], "service": check["service"],
            "force": check["force"], "present": check["present"],
            "throws": [[e["type"], e["message"]] for e in throws]}


def physical_io(event: dict, rows: list[dict], actor: str, bpid: str) -> bool:
    if (event.get("event") != "IO_OBSERVED" or event.get("bound") != "true"
            or event.get("actor") != actor or event.get("service") != SELECTED_SERVICE
            or event.get("rawBpid") != bpid or not event.get("uuid")):
        return False
    if event.get("marker") == "RPC":
        return bool(event.get("rawEndpoint")) and any(
            e.get("event") == "BP_ACTOR_BEGIN" and e.get("seq", 0) < event["seq"]
            and e.get("actor") == actor and e.get("service") == SELECTED_SERVICE
            and e.get("nnEndpoint") == event.get("rawEndpoint") for e in rows)
    if event.get("marker") == "FILE":
        return any(e.get("event") == "DATASET_MAP"
                   and e.get("seq", 0) < event["seq"]
                   and e.get("actor") == actor
                   and e.get("datasetId") == event.get("datasetId")
                   for e in rows)
    return False


def healthy(directory: Path) -> tuple[list[dict], dict, set[str]]:
    manifest = json.loads((directory / "manifest.json").read_text())
    rows = events(directory)
    if (manifest.get("junit_exit") != 0 or not manifest.get("instrumented")
            or manifest.get("graphchecker_runtime_used") is not False
            or manifest.get("test") !=
            "org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool#testDeleteBlockPool"):
        raise RuntimeError("original JUnit healthy seed failed: " + str(directory))
    actor, bpid = raw_context(rows)
    check = target(rows)
    if (check is None or check.get("actor") != actor or check.get("rawBpid") != bpid
            or not check.get("uuid") or check.get("force") != "true"
            or check.get("present") != "true"):
        raise RuntimeError("healthy selected DN2/BP1 check absent")
    sig = signature(rows, check)
    if len(sig["throws"]) != 1 or sig["throws"][0][0] != "java.io.IOException":
        raise RuntimeError("healthy expected IOException signature absent")
    io = [e for e in rows if e.get("seq", 0) < check["seq"]
          and physical_io(e, rows, actor, bpid)]
    if not io:
        raise RuntimeError("healthy lacks actor-bound RPC/file I/O before target")
    for metric in METRICS:
        if not (directory / ("covered_" + metric + ".txt")).is_file():
            raise RuntimeError("healthy JaCoCo missing " + metric)
    return io, sig, {io_family(e) for e in io}


def add(state: dict, sequence: list[dict], priority: int = 0,
        parent: str | None = None) -> None:
    if len(sequence) > state["max_faults"]:
        return
    identity = point_id(sequence)
    if identity in state["seen"]:
        return
    state["seen"].append(identity)
    state["queue"].append({"id": identity, "sequence": sequence,
                           "priority": priority, "parent": parent,
                           "created": time.time(), "retries": 0})


def initialize() -> dict:
    roots = (HERE / "healthy-a", HERE / "healthy-b")
    initial = [healthy(root) for root in roots]
    if initial[0][1] != initial[1][1]:
        raise RuntimeError("two healthy target signatures differ")
    build_hashes = [sha(root / "manifest.json") for root in roots]
    overlay = [json.loads((root / "manifest.json").read_text())["build"] for root in roots]
    if overlay[0] != overlay[1]:
        raise RuntimeError("two healthy seeds used different overlays")
    state = {"schema": 1, "case": "HDFS-32", "test":
             "org.apache.hadoop.hdfs.server.datanode.TestDeleteBlockPool#testDeleteBlockPool",
             "started_at_utc": utc(), "healthy_manifest_sha256": build_hashes,
             "healthy_signature": initial[0][1], "build": overlay[0],
             "healthy_coverage": {metric: sorted(set().union(*(coverage(root, metric)
                                     for root in roots))) for metric in METRICS},
             "coverage": {}, "healthy_io_families": sorted(initial[0][2] | initial[1][2]),
             "io_families": [], "goal": BASE_GOAL, "max_faults": BASE_DEPTH,
             "attempt_cap": BASE_ATTEMPTS, "extension": None,
             "completed": [], "queue": [], "seen": [], "active": None,
             "stop_reason": None}
    state["coverage"] = {metric: list(state["healthy_coverage"][metric])
                         for metric in METRICS}
    state["io_families"] = list(state["healthy_io_families"])
    a = {tuple(point(e, "IOException").items()) for e in initial[0][0]}
    b = {tuple(point(e, "IOException").items()) for e in initial[1][0]}
    for sample in initial:
        for event in sample[0]:
            for error in ERRORS[event["marker"]]:
                p = point(event, error)
                priority = 2 if tuple(point(event, "IOException").items()) in a & b else 1
                add(state, [p], priority)
    if not state["queue"]:
        raise RuntimeError("healthy actor-bound I/O generated no fault plan")
    atomic_json(STATE, state)
    write_summary(state)
    return state


def matches(event: dict, selected: dict, index: int) -> bool:
    return (event.get("planIndex") == str(index)
            and all(event.get(key) == selected[key] for key in
                    ("marker", "api", "actor", "service", "ordinal"))
            and event.get("exception") == selected["exception"]
            and event.get("bound") == "true")


def analyze(directory: Path, sequence: list[dict], state: dict) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest.get("build") != state["build"] or
            manifest.get("test") != state["test"] or
            manifest.get("graphchecker_runtime_used") is not False):
        raise RuntimeError("trial build/original JUnit differs from healthy seeds")
    rows = events(directory)
    plan = (directory / "fault-plan.tsv").read_text().splitlines()
    expected = ["\t".join(p[key] for key in
                ("marker", "api", "actor", "service", "ordinal", "exception"))
                for p in sequence]
    if plan != expected:
        raise RuntimeError("saved plan differs from checkpoint")
    try:
        actor, bpid = raw_context(rows)
    except RuntimeError:
        actor, bpid = SELECTED_ACTOR, inferred_bpid(rows)
    match = [e for e in rows if e.get("event") == "FAULT_MATCHED"]
    applied = [e for e in rows if e.get("event") == "FAULT_APPLIED"]
    exact = (len(match) == len(applied) == len(sequence)
             and all(matches(match[i], sequence[i], i)
                     and matches(applied[i], sequence[i], i)
                     and match[i]["seq"] < applied[i]["seq"]
                     and bpid is not None
                     and applied[i].get("rawBpid") == bpid
                     and applied[i].get("actor") == actor
                     and applied[i].get("uuid")
                     and physical_io(next((e for e in rows if
                         e.get("event") == "IO_OBSERVED" and
                         e.get("seq") == applied[i]["seq"] - 2), {}),
                         rows, actor, bpid)
                     for i in range(len(sequence)))
             and all(applied[i]["seq"] < match[i + 1]["seq"]
                     for i in range(len(sequence) - 1)))
    check = target(rows)
    last = applied[-1] if exact else None
    effective = bool(check and last and check["seq"] > last["seq"]
                     and check.get("actor") == actor
                     and check.get("rawBpid") == bpid
                     and check.get("uuid") == last.get("uuid"))
    observed = signature(rows, check) if effective else None
    candidate = bool(effective and observed != state["healthy_signature"])
    gain = {metric: sorted(coverage(directory, metric) - set(state["coverage"][metric]))
            if effective else [] for metric in METRICS}
    post_io = [e for e in rows if effective and last["seq"] < e.get("seq", 0) < check["seq"]
               and physical_io(e, rows, actor, bpid)]
    new_io = sorted({io_family(e) for e in post_io} - set(state["io_families"]))
    return {"id": point_id(sequence), "run": str(directory), "sequence": sequence,
            "exact_order_applied": bool(exact), "post_fault_target": effective,
            "candidate_needs_source_review": candidate,
            "target_signature": observed, "selected_target_seq": check["seq"] if check else None,
            "last_fault_seq": last["seq"] if last else None,
            "last_fault_actor": last.get("actor") if last else None,
            "last_fault_uuid": last.get("uuid") if last else None,
            "last_fault_bpid": last.get("rawBpid") if last else None,
            "coverage_gain": gain, "new_io_families": new_io,
            "post_fault_io": [point(e, "") for e in post_io],
            "junit_exit": manifest["junit_exit"],
            "elapsed_seconds": manifest["elapsed_seconds"],
            "raw_trace_sha256": sha(directory / "runtime_trace.jsonl") if rows else None,
            "manifest_sha256": sha(directory / "manifest.json")}


def mutate(state: dict, trial: dict, rows: list[dict]) -> None:
    if not trial["exact_order_applied"] or not trial["post_fault_target"]:
        return
    if len(trial["sequence"]) >= state["max_faults"]:
        return
    actor, bpid = raw_context(rows)
    check = target(rows)
    fresh = [e for e in rows if trial["last_fault_seq"] < e.get("seq", 0) < check["seq"]
             and physical_io(e, rows, actor, bpid)]
    # The trace's exact ordered points define mutation candidates.  An API
    # family is sampled before repeated heartbeat ordinals.
    fresh.sort(key=lambda e: (io_family(e) in state["io_families"], -e["seq"]))
    for event in fresh[:30]:
        for error in ERRORS[event["marker"]]:
            add(state, trial["sequence"] + [point(event, error)],
                priority=2 if io_family(event) in trial["new_io_families"] else 1,
                parent=trial["id"])


def effective(state: dict) -> list[dict]:
    return [row for row in state["completed"] if row["post_fault_target"]]


def update_budget(state: dict) -> None:
    valid = effective(state)
    if len(valid) < BASE_GOAL or state["extension"] is not None:
        return
    tail = valid[BASE_GOAL - 8:BASE_GOAL]
    novel = any(any(row["coverage_gain"][metric] for metric in METRICS)
                or row["new_io_families"] for row in tail)
    state["extension"] = {"decision_at_attempt": len(state["completed"]),
                          "last_eight_ids": [row["id"] for row in tail],
                          "novelty": bool(novel)}
    if novel:
        state["goal"] = EXTENDED_GOAL
        state["max_faults"] = EXTENDED_DEPTH
        state["attempt_cap"] = EXTENDED_ATTEMPTS
        for prior in state["completed"]:
            if prior["post_fault_target"] and len(prior["sequence"]) == BASE_DEPTH:
                mutate(state, prior, events(Path(prior["run"])))


def stop_reason(state: dict) -> str | None:
    if any(row["candidate_needs_source_review"] for row in state["completed"]):
        return "target_outcome_candidate_requires_replay_source_review"
    if len(effective(state)) >= state["goal"]:
        return "effective_budget_met_pending_independent_audit"
    if len(state["completed"]) >= state["attempt_cap"]:
        return "attempt_cap_inconclusive"
    if not state["queue"] and state["active"] is None:
        return "actor_bound_queue_exhausted_inconclusive"
    return None


def choose(state: dict) -> int:
    tested = Counter((row["sequence"][-1]["marker"], row["sequence"][-1]["api"])
                     for row in state["completed"])
    return max(range(len(state["queue"])), key=lambda i: (
        state["queue"][i]["priority"],
        -tested[(state["queue"][i]["sequence"][-1]["marker"],
                 state["queue"][i]["sequence"][-1]["api"])],
        min(len(state["queue"][i]["sequence"]), 6),
        -state["queue"][i]["created"], -i))


def write_summary(state: dict) -> None:
    rows = state["completed"]
    summary = {"schema": 1, "updated_at_utc": utc(), "case": "HDFS-32",
               "attempts": len(rows), "strict": sum(r["exact_order_applied"] for r in rows),
               "effective": len(effective(state)), "goal": state["goal"],
               "candidate_count": sum(r["candidate_needs_source_review"] for r in rows),
               "junit_nonzero": sum(r["junit_exit"] != 0 for r in rows),
               "healthy_junit_seconds": sum(json.loads((HERE / f"healthy-{x}" / "manifest.json").read_text())["elapsed_seconds"] for x in ("a", "b")),
               "fault_junit_seconds": round(sum(r["elapsed_seconds"] for r in rows), 3),
               "queue": len(state["queue"]), "active": state["active"] is not None,
               "max_faults": state["max_faults"], "attempt_cap": state["attempt_cap"],
               "stop_reason": state["stop_reason"], "extension": state["extension"]}
    atomic_json(HERE / "summary.json", summary)
    result = json.loads(RESULT.read_text())
    result["actor_v3"] = {"status": "running" if state["stop_reason"] is None else state["stop_reason"],
                          "test": state["test"], "runtime_identity":
                          "MiniDFSCluster DN object slot + DataNode UUID + NN/BP role + raw BPID + RPC endpoint or dataset object",
                          "historical_attempts_excluded": 80,
                          "attempts": summary["attempts"], "strict": summary["strict"],
                          "effective": summary["effective"], "goal": state["goal"],
                          "candidates": summary["candidate_count"], "confirmed_bugs": 0,
                          "fault_junit_seconds": summary["fault_junit_seconds"],
                          "healthy_junit_seconds": summary["healthy_junit_seconds"],
                          "checkpoint": str(STATE), "summary": str(HERE / "summary.json")}
    atomic_json(RESULT, result)


def trial_run(state: dict) -> bool:
    if state["active"] is None:
        state["active"] = state["queue"].pop(choose(state))
        atomic_json(STATE, state)
    item = state["active"]
    directory = HERE / "runs" / ("trial-%04d" % (len(state["completed"]) + 1))
    directory.mkdir(parents=True, exist_ok=True)
    plan = directory / "fault-plan.tsv"
    contents = "".join("\t".join(p[key] for key in
                       ("marker", "api", "actor", "service", "ordinal", "exception")) + "\n"
                       for p in item["sequence"])
    if not plan.is_file():
        pending = plan.with_suffix(".tsv.tmp")
        pending.write_text(contents)
        pending.replace(plan)
    elif plan.read_text() != contents:
        raise RuntimeError("active fault plan differs from checkpoint")
    if not launch(directory, plan, 180):
        return False
    trial = analyze(directory, item["sequence"], state)
    trial["retries"] = item["retries"]
    state["completed"].append(trial)
    mutate(state, trial, events(directory))
    if not trial["exact_order_applied"] and item["retries"] < 2:
        state["queue"].append({**item, "retries": item["retries"] + 1,
                               "created": time.time()})
    if trial["post_fault_target"]:
        for metric in METRICS:
            state["coverage"][metric] = sorted(set(state["coverage"][metric])
                                                 | set(trial["coverage_gain"][metric]))
        state["io_families"] = sorted(set(state["io_families"])
                                      | set(trial["new_io_families"]))
    state["active"] = None
    update_budget(state)
    state["stop_reason"] = stop_reason(state)
    atomic_json(STATE, state)
    write_summary(state)
    print(json.dumps({"attempt": len(state["completed"]),
                      "strict": trial["exact_order_applied"],
                      "effective": len(effective(state)),
                      "candidate": trial["candidate_needs_source_review"],
                      "stop": state["stop_reason"]}), flush=True)
    return True


def preview() -> dict:
    if not STATE.is_file():
        return {"state": "awaiting_two_new_healthy_calibrations",
                "healthy": [(HERE / f"healthy-{x}" / "manifest.json").is_file()
                            for x in ("a", "b")]}
    state = json.loads(STATE.read_text())
    return {"attempts": len(state["completed"]), "effective": len(effective(state)),
            "goal": state["goal"], "queue": len(state["queue"]),
            "active": state["active"] is not None, "attempt_cap": state["attempt_cap"],
            "max_faults": state["max_faults"], "stop": state["stop_reason"],
            "checkpoint_sha256": sha(STATE)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--max-new-attempts", type=int, default=0)
    parser.add_argument("--wall-seconds", type=int, default=43200)
    parser.add_argument("--poll-seconds", type=int, default=20)
    args = parser.parse_args()
    if args.preview:
        print(json.dumps(preview(), sort_keys=True)); return
    if not args.run:
        parser.error("choose --preview or --run")
    deadline = time.monotonic() + args.wall_seconds
    with LOCK.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text()) if STATE.is_file() else initialize()
        completed_at_start = len(state["completed"])
        while time.monotonic() < deadline:
            reason = stop_reason(state)
            if reason:
                state["stop_reason"] = reason
                atomic_json(STATE, state)
                write_summary(state)
                print("terminal " + reason, flush=True); return
            if trial_run(state):
                if args.max_new_attempts and len(state["completed"]) - completed_at_start >= args.max_new_attempts:
                    print("bounded run ended at atomic checkpoint", flush=True); return
            else:
                time.sleep(min(args.poll_seconds, max(0, deadline - time.monotonic())))
        print("wall cap reached at atomic checkpoint; resume", flush=True)


if __name__ == "__main__":
    main()
