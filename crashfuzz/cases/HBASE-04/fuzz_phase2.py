#!/usr/bin/env python3
"""Resume a bounded, coverage and I/O guided HBASE-04 exception campaign.

This case runner consumes only runtime I/O points and method/branch coverage.
It never runs graph aggregation or uses a causal closure for selection.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys


BASE = Path(__file__).resolve().parent
PHASE1 = BASE.parent
TARGET_SITE = (
    "<org.apache.hadoop.hbase.client.HBaseAdmin: java.util.concurrent.Future "
    "flushAsync(org.apache.hadoop.hbase.TableName,java.util.List)>#u4"
)
DEFAULT_TOTAL = 64
EXPANDED_TOTAL = 128
DEFAULT_MAX_FAULTS = 6
EXPANDED_MAX_FAULTS = 8
PREVIOUS_TRIALS = 5
EXTENSION_WINDOW = 16
EXTENSION_MIN_NEW_IO_TRIALS = 2
POLICY = "64_6_to_128_8_recent_feedback"
STATE = BASE / "state.json"
CHECKPOINT = BASE / "checkpoint"
PLANS = BASE / "plans"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def events(path: Path):
    if not path.exists():
        return
    with path.open(errors="replace") as stream:
        for line in stream:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def point(row: dict) -> dict:
    return {
        "marker": row["marker"],
        "siteId": row["siteId"],
        "occurrence": row["occurrenceAddress"],
        "sourceKey": row.get("sourceKey", ""),
        "hitOrdinal": row["hitOrdinal"],
        "seq": row.get("seq", 0),
    }


def point_key(p: dict) -> str:
    return json.dumps([p[k] for k in
                       ("marker", "siteId", "occurrence", "sourceKey", "hitOrdinal")],
                      separators=(",", ":"))


def candidate_key(faults: list[dict]) -> str:
    return hashlib.sha256("\n".join(point_key(p) for p in faults)
                          .encode()).hexdigest()


def family(p: dict) -> str:
    parts = p["marker"].split(":")
    return ":".join(parts[:3])


def nearby(p: dict) -> bool:
    marker = p["marker"]
    if marker.startswith("FAULT:HBASE_META:"):
        return True
    if not marker.startswith("FAULT:HBASE_RPC:"):
        return False
    occurrence = p["occurrence"]
    return any(name in occurrence for name in (
        "flushAsync", "isTableEnabled", "checkTableExists", "getTableState",
        "updateTableState", "createTable", "MasterCallable", "testMobStoreScanner"))


def source_score(p: dict) -> int:
    marker = p["marker"]
    occurrence = p["occurrence"]
    if marker.startswith("FAULT:HBASE_RPC:"):
        base = 105 if "flushAsync" in occurrence else 83
        if "getTableState" in occurrence:
            base += 8
        if not p["sourceKey"]:
            base -= 14
        return base
    if "TABLE_STATE_READ" in marker:
        return 97
    if "TABLE_STATE_WRITE" in marker:
        return 82
    return 20


def observed_points(rows: list[dict]) -> list[dict]:
    found = []
    seen = set()
    for row in rows:
        if row.get("event") != "FAULT_POINT_OBSERVED":
            continue
        p = point(row)
        k = point_key(p)
        if nearby(p) and k not in seen:
            seen.add(k)
            found.append(p)
    return found


def synthetic_branch_sites(rows: list[dict]) -> set[str]:
    result = set()
    for row in rows:
        if row.get("event") != "FAULT_POINT_OBSERVED":
            continue
        site = row.get("siteId", "")
        match = re.search(r"#u(\d+)$", site)
        if match:
            result.add(site[:match.start(1)] + str(int(match.group(1)) + 1))
    return result


def coverage(rows: list[dict]) -> tuple[set[str], set[str]]:
    synthetic = synthetic_branch_sites(rows)
    methods = {r["method"] for r in rows
               if r.get("event") == "METHOD_ENTER"
               and r.get("method", "").startswith("<org.apache.hadoop.hbase.")}
    branches = {json.dumps([r["siteId"], r.get("outcome")]) for r in rows
                if r.get("event") == "BRANCH"
                and r.get("siteId", "").startswith("<org.apache.hadoop.hbase.")
                and r.get("siteId") not in synthetic}
    return methods, branches


def phase1_keys() -> set[str]:
    result = set()
    for path in sorted((PHASE1 / "fault-plans").glob("*.json")):
        data = json.loads(path.read_text())
        faults = []
        for row in data.get("faults", []):
            faults.append({**row, "seq": 0})
        if faults:
            result.add(candidate_key(faults))
    return result


def initialize() -> dict:
    if (BASE / "healthy.rc").read_text().strip() != "0":
        raise RuntimeError("instrumented original JUnit healthy seed did not pass")
    rows = list(events(BASE / "trace-healthy/runtime_trace.jsonl"))
    methods, branches = coverage(rows)
    points = observed_points(rows)
    if not points:
        raise RuntimeError("healthy seed observed no relevant I/O points")
    prior = phase1_keys()
    queue = []
    seen = set(prior)
    for p in points:
        faults = [p]
        key = candidate_key(faults)
        if key not in seen:
            queue.append({"faults": faults, "parent": "healthy", "base_score": source_score(p)})
            seen.add(key)
    state = {
        "schema_version": 1,
        "methodology": "coverage_io_no_graph",
        "created_utc": now(),
        "budget_total": DEFAULT_TOTAL,
        "max_faults": DEFAULT_MAX_FAULTS,
        "budget_policy": POLICY,
        "previous_trials": PREVIOUS_TRIALS,
        "completed": [],
        "inflight": None,
        "queue": queue,
        "seen_candidates": sorted(seen),
        "observed_points": sorted(point_key(p) for p in points),
        "coverage_methods": sorted(methods),
        "coverage_branches": sorted(branches),
        "family_tests": {},
        "bug_candidates": [],
        "stop_reason": "",
    }
    save(STATE, state)
    print("INIT healthy_points", len(points), "queued", len(queue),
          "excluded_prior", len(prior), flush=True)
    return state


def choose(state: dict) -> dict | None:
    if not state["queue"]:
        return None
    family_tests = state["family_tests"]
    def priority(item):
        last = item["faults"][-1]
        f = family(last)
        tested = family_tests.get(f, 0)
        return (item["base_score"] + 10 * (len(item["faults"]) - 1)
                - 10 * tested + (15 if tested == 0 else 0),
                -last.get("seq", 0))
    index = max(range(len(state["queue"])),
                key=lambda i: priority(state["queue"][i]))
    return state["queue"].pop(index)


def add_candidate(state: dict, faults: list[dict], parent: str,
                  bonus: int) -> None:
    if len(faults) > state["max_faults"]:
        return
    key = candidate_key(faults)
    if key in state["seen_candidates"]:
        return
    state["seen_candidates"].append(key)
    state["queue"].append({"faults": faults, "parent": parent,
                           "base_score": source_score(faults[-1]) + bonus})


def make_plan(item: dict, trial_id: str) -> dict:
    faults = []
    for index, p in enumerate(item["faults"], 1):
        faults.append({"faultId": f"HBASE04-{trial_id}-f{index}",
                       "marker": p["marker"], "siteId": p["siteId"],
                       "occurrence": p["occurrence"],
                       "sourceKey": p["sourceKey"],
                       "hitOrdinal": p["hitOrdinal"], "value": True})
    return {"schemaVersion": 1, "faults": faults,
            "targetSiteId": TARGET_SITE}


def is_effective(row: dict, max_faults: int) -> bool:
    return (0 < len(row.get("faults", [])) <= max_faults
            and row.get("requested") == row.get("matched") == row.get("applied")
            and row.get("target_after_fault") is True
            and row.get("elapsed_seconds") is not None)


def classify_result(row: dict, budget_total: int, max_faults: int) -> str:
    depth = len(row.get("faults", []))
    if depth > max_faults:
        return "exploratory_outside_default_budget"
    if is_effective(row, max_faults):
        return ("effective_default_budget" if budget_total == DEFAULT_TOTAL
                else "effective_extended_budget")
    return "discarded_unmatched_or_target_lost"


def migrate_classes(state: dict) -> None:
    for name in state["completed"]:
        path = CHECKPOINT / f"{name}.json"
        if not path.exists():
            continue
        row = json.loads(path.read_text())
        if "budget_class" in row:
            continue
        row["budget_class"] = classify_result(row, DEFAULT_TOTAL, DEFAULT_MAX_FAULTS)
        save(path, row)


def effective_count(state: dict) -> int:
    count = PREVIOUS_TRIALS
    for name in state["completed"]:
        path = CHECKPOINT / f"{name}.json"
        if not path.exists():
            continue
        row = json.loads(path.read_text())
        if is_effective(row, state["max_faults"]):
            count += 1
    return count


def finish_trial(state: dict, trial_id: str, item: dict,
                 exit_code: int | None) -> dict:
    trace = BASE / f"trace-{trial_id}/runtime_trace.jsonl"
    log = BASE / f"{trial_id}.log"
    rows = list(events(trace))
    summaries = [r for r in rows if r.get("event") == "FAULT_TRIAL_SUMMARY"]
    summary = summaries[-1] if summaries else None
    methods, branches = coverage(rows)
    new_methods = methods - set(state["coverage_methods"])
    new_branches = branches - set(state["coverage_branches"])
    points = observed_points(rows)
    old_points = set(state["observed_points"])
    new_points = [p for p in points if point_key(p) not in old_points]
    guards = [r for r in rows if r.get("event") == "BRANCH"
              and r.get("siteId") == TARGET_SITE]
    fatal_guards = sum(r.get("outcome") is False for r in guards)
    explicit_throws = [r for r in rows
                       if r.get("event") == "EXPLICIT_THROW"
                       and "HBaseAdmin" in json.dumps(r)
                       and "TableNotEnabledException" in json.dumps(r)]
    elapsed = re.findall(r"ELAPSED_SECONDS=([\d.]+)",
                         log.read_text(errors="replace") if log.exists() else "")
    result = {
        "case_id": "HBASE-04", "trial": trial_id,
        "parent": item["parent"], "plan": str(PLANS / f"{trial_id}.json"),
        "trace": str(trace), "log": str(log),
        "exit_code": exit_code,
        "elapsed_seconds": float(elapsed[-1]) if elapsed else None,
        "requested": len(item["faults"]),
        "matched": summary.get("matched", 0) if summary else 0,
        "applied": summary.get("applied", 0) if summary else 0,
        "target_after_fault": summary.get("targetAfterFault") if summary else None,
        "target_guard_hits": len(guards),
        "fatal_target_guard_hits": fatal_guards,
        "exact_target_throw_hits": len(explicit_throws),
        "new_production_methods": sorted(new_methods),
        "new_production_branches": sorted(new_branches),
        "new_io_points": len(new_points),
        "observed_io_points": len(points),
        "faults": item["faults"],
        "checkpoint_utc": now(),
    }
    result["budget_class"] = classify_result(result, state["budget_total"],
                                             state["max_faults"])
    save(CHECKPOINT / f"{trial_id}.json", result)
    if trial_id not in state["completed"]:
        state["completed"].append(trial_id)
        state["coverage_methods"] = sorted(set(state["coverage_methods"]) | methods)
        state["coverage_branches"] = sorted(set(state["coverage_branches"]) | branches)
        state["observed_points"] = sorted(old_points |
                                           {point_key(p) for p in points})
        last_family = family(item["faults"][-1])
        state["family_tests"][last_family] = state["family_tests"].get(last_family, 0) + 1
        applied = result["requested"] == result["matched"] == result["applied"]
        if applied and result["target_after_fault"] and not (fatal_guards or explicit_throws):
            applied_events = [r for r in rows if r.get("event") == "FAULT_APPLIED"]
            after = max((r["seq"] for r in applied_events), default=0)
            later = [p for p in points if p.get("seq", 0) > after]
            later.sort(key=lambda p: (point_key(p) not in old_points,
                                      family(p) != last_family,
                                      source_score(p)), reverse=True)
            limit = 3 if new_methods or new_branches else 2
            for p in later[:limit]:
                add_candidate(state, item["faults"] + [p], trial_id,
                              20 if point_key(p) not in old_points else 2)
        if fatal_guards or explicit_throws:
            state["bug_candidates"].append(trial_id)
            state["stop_reason"] = "target_exception_candidate_requires_source_review"
    state["inflight"] = None
    save(STATE, state)
    return result


def recover(state: dict) -> None:
    inflight = state.get("inflight")
    if not inflight:
        return
    trial_id = inflight["trial"]
    if trial_id in state["completed"]:
        state["inflight"] = None
        save(STATE, state)
        return
    trace = BASE / f"trace-{trial_id}/runtime_trace.jsonl"
    log = BASE / f"{trial_id}.log"
    if trace.exists() and log.exists() and "ELAPSED_SECONDS=" in log.read_text(errors="replace"):
        result = finish_trial(state, trial_id, inflight["item"],
                              json.loads((BASE / f"{trial_id}.exit.json").read_text())["exit_code"]
                              if (BASE / f"{trial_id}.exit.json").exists() else None)
        print("RECOVER", trial_id, result["applied"], flush=True)
    else:
        save(CHECKPOINT / f"{trial_id}.json",
             {"case_id": "HBASE-04", "trial": trial_id,
              "status": "interrupted_without_complete_run", "checkpoint_utc": now()})
        state["completed"].append(trial_id)
        state["inflight"] = None
        save(STATE, state)
        print("SKIP interrupted incomplete", trial_id, flush=True)


def main() -> None:
    CHECKPOINT.mkdir(exist_ok=True)
    PLANS.mkdir(exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    recover(state)
    if state.get("budget_policy") != POLICY:
        state["budget_total"] = DEFAULT_TOTAL
        state["max_faults"] = DEFAULT_MAX_FAULTS
        state["budget_policy"] = POLICY
        if state["stop_reason"] == "budget_reached":
            state["stop_reason"] = ""
        save(STATE, state)
    migrate_classes(state)
    while effective_count(state) < state["budget_total"]:
        if state["stop_reason"]:
            break
        item = choose(state)
        if item is None:
            state["stop_reason"] = "candidate_queue_exhausted"
            save(STATE, state)
            break
        trial_id = f"p2_{len(state['completed']) + 1:04d}"
        plan_path = PLANS / f"{trial_id}.json"
        save(plan_path, make_plan(item, trial_id))
        state["inflight"] = {"trial": trial_id, "item": item,
                             "started_utc": now()}
        save(STATE, state)
        log = BASE / f"{trial_id}.log"
        print("START", trial_id, "depth", len(item["faults"]),
              family(item["faults"][-1]), "queue", len(state["queue"]), flush=True)
        with log.open("w") as stream:
            proc = subprocess.run(["bash", str(BASE / "run-record.sh"), trial_id,
                                   str(plan_path)], stdout=stream,
                                  stderr=subprocess.STDOUT)
        save(BASE / f"{trial_id}.exit.json", {"exit_code": proc.returncode})
        result = finish_trial(state, trial_id, item, proc.returncode)
        print("END", trial_id, "matched", result["matched"],
              "applied", result["applied"], "target", result["target_after_fault"],
              "fatal", result["fatal_target_guard_hits"],
              "prod+", len(result["new_production_methods"]),
              len(result["new_production_branches"]),
              "newIO", result["new_io_points"],
              "sec", result["elapsed_seconds"], flush=True)
        if effective_count(state) == DEFAULT_TOTAL and state["budget_total"] == DEFAULT_TOTAL:
            valid = []
            for name in state["completed"]:
                row = json.loads((CHECKPOINT / f"{name}.json").read_text())
                if is_effective(row, state["max_faults"]):
                    valid.append(name)
            recent = valid[-EXTENSION_WINDOW:]
            production_gain_trials = 0
            new_io_trials = 0
            for name in recent:
                path = CHECKPOINT / f"{name}.json"
                if not path.exists():
                    continue
                row = json.loads(path.read_text())
                if row.get("new_production_methods") or row.get("new_production_branches"):
                    production_gain_trials += 1
                if row.get("new_io_points", 0) > 0:
                    new_io_trials += 1
            if production_gain_trials >= 1 or new_io_trials >= EXTENSION_MIN_NEW_IO_TRIALS:
                state["budget_total"] = EXPANDED_TOTAL
                state["max_faults"] = EXPANDED_MAX_FAULTS
                save(STATE, state)
                print("EXTEND recent_prod_gain_trials", production_gain_trials,
                      "recent_new_io_trials", new_io_trials, flush=True)
    if not state["stop_reason"]:
        state["stop_reason"] = "budget_reached"
    save(STATE, state)
    print("STOP", state["stop_reason"], "attempts", PREVIOUS_TRIALS + len(state["completed"]),
          "effective", effective_count(state), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr,
              flush=True)
        raise
