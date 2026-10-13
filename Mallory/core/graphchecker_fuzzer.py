"""Resumable, target-guided fuzz loop over native GraphChecker JUnit trials.

The queue contains only fault plans formed from attributed FAULT_DOOR rows in
completed trials. Exact causal closure and static MAY scope have distinct
priorities. Neither an old Mallory event graph nor a static relation can prove
that a fault applied or that the exact target exception ran.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graphchecker_campaign import (_json, _write_json, load_config, prepare,
                                    run_trial)

SCHEMA = 1
PLAN_FIELDS = ("siteId", "node", "occurrenceId", "ordinal", "exceptionClass")
TIER_WEIGHT = {"observed_closure": 100, "static_may_observed": 55,
               "outside_closure": 15, "after_target": -100}
MAX_QUEUE = 5000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _budget(config_path: Path) -> dict[str, int]:
    raw = _json(config_path).get("budget")
    if not isinstance(raw, dict):
        raise ValueError("campaign needs budget: fault_trials, seconds, max_faults_per_trial")
    values = {key: raw.get(key) for key in
              ("fault_trials", "seconds", "max_faults_per_trial")}
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
           for value in values.values()):
        raise ValueError("campaign budget values must be positive integers")
    if values["max_faults_per_trial"] > 10:
        raise ValueError("max_faults_per_trial exceeds 10")
    return values


def _plan_key(faults: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(faults, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _live_process(trial: Path) -> bool:
    receipt = trial / "process.json"
    if not receipt.is_file():
        return False
    data = _json(receipt)
    pid = data.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        fields = stat.rsplit(") ", 1)[1].split()
        return fields[19] == data.get("start_ticks") and fields[0] != "Z"
    except (OSError, IndexError):
        return False


def _score(item: dict[str, Any], completed: int) -> float:
    return (TIER_WEIGHT[item["tier"]] + item["novelty"] +
            4 * len(item["faults"]) + min(30, completed - item["enqueued_at"]))


def _pick(queue: list[dict[str, Any]], completed: int) -> dict[str, Any]:
    # A periodic exploration slot prevents exact-closure sites from starving
    # static MAY and outside-closure sites under a finite trial budget.
    candidates = queue
    if completed % 5 == 4:
        exploratory = [item for item in queue if item["tier"] != "observed_closure"]
        if exploratory:
            candidates = exploratory
    selected = max(candidates, key=lambda item: (_score(item, completed),
                                                -item["enqueued_at"], item["key"]))
    queue.remove(selected)
    return selected


def _novelty(result: dict[str, Any]) -> int:
    graph = result.get("graphchecker_feedback", {})
    return min(60, 4 * int(graph.get("newClosureEdges", 0)) +
               2 * int(graph.get("newClosureNodes", 0)) +
               int(graph.get("newClosureCoverageSites", 0)))


def _enqueue(state: dict[str, Any], result: dict[str, Any],
             prefix: list[dict[str, Any]]) -> int:
    evidence = result.get("evidence", {})
    last_seq = evidence.get("last_fault_seq") or 0
    if len(prefix) >= state["budget"]["max_faults_per_trial"]:
        return 0
    seen = set(state["seen_plan_keys"])
    added = 0
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for door in evidence.get("eligible_doors", []):
        tier = door.get("tier")
        if (tier not in TIER_WEIGHT or tier == "after_target" or
                door.get("seq", 0) <= last_seq or
                not all(door.get(key) for key in PLAN_FIELDS)):
            continue
        groups.setdefault((door["siteId"], door["node"], tier), []).append(door)
    sampled: list[dict[str, Any]] = []
    for group in groups.values():
        group.sort(key=lambda door: door["seq"])
        # Five quantile points cover early and late repeated I/O calls without
        # filling the queue with every heartbeat or polling occurrence.
        n = len(group)
        sampled.extend(group[(n - 1) * bucket // 4] for bucket in range(5))
    by_tier = {tier: deque(sorted((door for door in sampled if door["tier"] == tier),
                                  key=lambda door: door["seq"]))
               for tier in ("observed_closure", "static_may_observed", "outside_closure")}
    # Reserve queue capacity for conservative static and exploratory sites.
    # Their priority during execution remains lower than exact closure sites.
    ordered = []
    schedule = ("observed_closure", "observed_closure", "observed_closure",
                "static_may_observed", "outside_closure")
    while any(by_tier.values()) and len(ordered) < MAX_QUEUE:
        for tier in schedule:
            if by_tier[tier]:
                ordered.append(by_tier[tier].popleft())
    for door in ordered:
        if len(state["queue"]) >= MAX_QUEUE:
            break
        tier = door["tier"]
        fault = {key: door[key] for key in PLAN_FIELDS}
        faults = [*prefix, fault]
        key = _plan_key(faults)
        if key in seen:
            continue
        seen.add(key)
        state["queue"].append({"key": key, "faults": faults, "tier": tier,
                               "novelty": _novelty(result),
                               "enqueued_at": state["completed_fault_trials"]})
        added += 1
    state["seen_plan_keys"] = sorted(seen)
    return added


def _new_state(config: dict[str, Any], budget: dict[str, int]) -> dict[str, Any]:
    return {"schema_version": SCHEMA, "case_id": config["case_id"],
            "config_sha256": config["config_sha256"], "budget": budget,
            "target_site_rows": config.get("target_site_rows", []),
            "status": "running", "terminal": False,
            "started_at": _now(), "updated_at": _now(),
            "completed_fault_trials": 0, "trial_elapsed_seconds": 0.0,
            "healthy": None, "trials": [], "queue": [], "seen_plan_keys": [],
            "active": None, "next_trial_index": 1}


def _trial_record(name: str, result: dict[str, Any]) -> dict[str, Any]:
    evidence = result.get("evidence", {})
    return {"name": name, "status": result["status"],
            "result": f"trials/{name}/result.json",
            "elapsed_seconds": result["elapsed_seconds"],
            "faults": result["fault_plan"],
            "strict_injection": evidence.get("strict_injection", False),
            "post_fault_target_reached": evidence.get("post_fault_target_reached", False),
            "target_exception_triggered": result["target_exception_triggered"],
            "target_exception_candidate": result["target_exception_candidate"],
            "junit_passed": result["junit_passed"]}


def _accept_result(state: dict[str, Any], name: str,
                   result: dict[str, Any]) -> None:
    active = state["active"]
    if active is None or active["name"] != name:
        raise ValueError("checkpoint active trial disagrees with result")
    record = _trial_record(name, result)
    state["trial_elapsed_seconds"] = round(
        state["trial_elapsed_seconds"] + result["elapsed_seconds"], 3)
    if active["index"] == 0:
        state["healthy"] = record
        if result["status"] == "invalid_graphchecker_trace":
            state["status"] = "blocked_healthy_trace"
        elif not result["junit_passed"]:
            state["status"] = "blocked_healthy_junit"
        elif not result.get("evidence", {}).get("target_reached"):
            state["status"] = "no_healthy_target"
        else:
            _enqueue(state, result, [])
            if not state["queue"]:
                state["status"] = "no_observed_fault_door"
    else:
        state["trials"].append(record)
        state["completed_fault_trials"] += 1
        evidence = result.get("evidence", {})
        if evidence.get("strict_injection") and (
                evidence.get("post_fault_target_reached") or
                result.get("target_exception_triggered")):
            _enqueue(state, result, active["faults"])
    state["active"] = None
    state["updated_at"] = _now()
    state["terminal"] = state["status"] != "running"


def _resume_active(state: dict[str, Any], root: Path,
                   config: dict[str, Any], prepared: Path) -> None:
    active = state.get("active")
    if active is None:
        return
    name = active["name"]
    trial = root / "trials" / name
    result_file = trial / "result.json"
    if result_file.is_file():
        result = _json(result_file)
        if result.get("case_id") != state["case_id"] or result.get("fault_plan") != active["faults"]:
            raise ValueError("completed active trial does not match checkpoint")
        _accept_result(state, name, result)
        _write_json(root / "checkpoint.json", state)
        return
    if _live_process(trial):
        raise RuntimeError(f"trial JVM is still running; refusing duplicate: {trial}")
    if trial.exists():
        archive = root / "interrupted"
        archive.mkdir(exist_ok=True)
        suffix = 1
        while (archive / f"{name}-attempt{suffix}").exists():
            suffix += 1
        trial.rename(archive / f"{name}-attempt{suffix}")
        active["interrupted_attempts"] = suffix
    prior = root / "trials" / "r0000" / "graphchecker-trace.jsonl"
    result = run_trial(config, prepared, trial, {"faults": active["faults"]},
                       prior if active["index"] > 0 else None)
    _accept_result(state, name, result)
    _write_json(root / "checkpoint.json", state)


def _finish(state: dict[str, Any], root: Path) -> dict[str, Any]:
    if state["status"] == "running":
        if state["completed_fault_trials"] >= state["budget"]["fault_trials"]:
            state["status"] = "complete_trial_budget"
        elif state["trial_elapsed_seconds"] >= state["budget"]["seconds"]:
            state["status"] = "complete_time_budget"
        elif not state["queue"]:
            state["status"] = "complete_queue"
    state["updated_at"] = _now()
    state["terminal"] = state["status"] != "running"
    _write_json(root / "checkpoint.json", state)
    if state["status"] != "running":
        trials = state["trials"]
        summary = {"schema_version": SCHEMA, "case_id": state["case_id"],
                   "status": state["status"], "terminal": True,
                   "config_sha256": state["config_sha256"],
                   "target_site_rows": state.get("target_site_rows", []),
                   "budget": state["budget"],
                   "completed_fault_trials": state["completed_fault_trials"],
                   "trial_elapsed_seconds": state["trial_elapsed_seconds"],
                   "healthy": state["healthy"],
                   "strict_trials": sum(row["strict_injection"] for row in trials),
                   "post_fault_target_trials": sum(row["post_fault_target_reached"]
                                                   for row in trials),
                   "target_exception_triggered_trials": sum(
                       row["target_exception_triggered"] for row in trials),
                   "differential_candidates": sum(
                       row["target_exception_candidate"] for row in trials),
                   "first_target_exception_trial": next(
                       (row["name"] for row in trials
                        if row["target_exception_triggered"]), None),
                   "updated_at": state["updated_at"]}
        _write_json(root / "summary.json", summary)
    return state


def run_campaign(config_path: Path, root: Path) -> dict[str, Any]:
    config = load_config(config_path)
    budget = _budget(config_path)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".campaign.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as failure:
            raise RuntimeError(f"campaign already owned by another worker: {root}") from failure
        checkpoint = root / "checkpoint.json"
        if checkpoint.is_file():
            state = _json(checkpoint)
            if (state.get("schema_version") != SCHEMA or
                    state.get("case_id") != config["case_id"] or
                    state.get("config_sha256") != config["config_sha256"] or
                    state.get("budget") != budget):
                raise ValueError("campaign checkpoint does not match immutable config")
        else:
            state = _new_state(config, budget)
            _write_json(checkpoint, state)
        if state["status"] != "running":
            return _finish(state, root)
        prepared = root / "prepared"
        if not (prepared / "weave-receipt.json").is_file():
            if prepared.exists():
                raise ValueError("incomplete weave preparation; preserve it and use a new case root")
            prepare(config, prepared)
        (root / "trials").mkdir(exist_ok=True)
        if state["healthy"] is None and state["active"] is None:
            state["active"] = {"index": 0, "name": "r0000", "faults": []}
            _write_json(checkpoint, state)
        _resume_active(state, root, config, prepared)
        while state["status"] == "running":
            if (state["completed_fault_trials"] >= budget["fault_trials"] or
                    state["trial_elapsed_seconds"] >= budget["seconds"] or
                    not state["queue"]):
                break
            selected = _pick(state["queue"], state["completed_fault_trials"])
            index = state["next_trial_index"]
            state["next_trial_index"] += 1
            state["active"] = {"index": index, "name": f"r{index:04d}",
                               "faults": selected["faults"],
                               "selection_tier": selected["tier"],
                               "selection_score": _score(selected, state["completed_fault_trials"])}
            _write_json(checkpoint, state)
            _resume_active(state, root, config, prepared)
        return _finish(state, root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    state = run_campaign(args.config, args.out)
    print(json.dumps({"case_id": state["case_id"], "status": state["status"],
                      "completed_fault_trials": state["completed_fault_trials"],
                      "summary": str((args.out / "summary.json").resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
