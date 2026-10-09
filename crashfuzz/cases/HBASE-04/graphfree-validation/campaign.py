#!/usr/bin/env python3
"""Resumable graph-free HBASE-04 original-JUnit I/O and coverage fuzzer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess


BASE = Path(__file__).resolve().parent
STATE = BASE / "campaign-state.json"
CHECKPOINTS = BASE / "campaign-checkpoints"
PLANS = BASE / "campaign-plans"
DEFAULT_TRIALS = 80
DEFAULT_MAX_FAULTS = 8
EXTENDED_TRIALS = 128
EXTENDED_MAX_FAULTS = 10
EXTENSION_WINDOW = 16
COVERAGE_SCOPE = [
    "org/apache/hadoop/hbase/client/HBaseAdmin",
    "org/apache/hadoop/hbase/MetaTableAccessor",
    "org/apache/hadoop/hbase/ipc/AbstractRpcClient",
    "org/apache/hadoop/hbase/client/RpcRetryingCallerImpl",
    "org/apache/hadoop/hbase/client/ConnectionImplementation",
    "org/apache/hadoop/hbase/client/ClientServiceCallable",
    "org/apache/hadoop/hbase/client/MasterCallable",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def parse_fields(line: str, prefix: str) -> dict[str, str]:
    if not line.startswith(prefix):
        return {}
    fields = {}
    for token in line[len(prefix):].strip().split():
        if "=" in token:
            key, value = token.split("=", 1)
            fields[key] = value
    return fields


def observations(path: Path) -> dict:
    points = []
    applied = []
    target_enters = []
    target_exits = []
    checks = []
    junit = None
    elapsed = None
    for position, line in enumerate(path.open(errors="replace")):
        line = line.rstrip("\n")
        if line.startswith("HBASE04 IO "):
            point = parse_fields(line, "HBASE04 IO ")
            point["position"] = position
            points.append(point)
            if point.get("applied") == "true":
                applied.append(point)
        elif line.startswith("HBASE04 TARGET_ENTER "):
            target_enters.append({**parse_fields(line, "HBASE04 TARGET_ENTER "),
                                  "position": position})
        elif line.startswith("HBASE04 TARGET_EXIT "):
            target_exits.append({**parse_fields(line, "HBASE04 TARGET_EXIT "),
                                 "position": position})
        elif line.startswith("HBASE04 CHECK "):
            checks.append({**parse_fields(line, "HBASE04 CHECK "),
                           "position": position})
        elif "JUNIT found=" in line:
            junit = line.strip()
        elif line.startswith("ELAPSED_SECONDS="):
            match = re.search(r"ELAPSED_SECONDS=([0-9.]+)", line)
            if match:
                elapsed = float(match.group(1))
    return {"points": points, "applied": applied, "target_enters": target_enters,
            "target_exits": target_exits, "checks": checks, "junit": junit,
            "elapsed_seconds": elapsed}


def probes(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.open(errors="replace")
            if line.startswith("PROBE class=")}


def coverage_counts(path: Path) -> dict[str, int]:
    totals = {"methods": 0, "branches": 0, "lines": 0}
    if not path.exists():
        return totals
    for line in path.open(errors="replace"):
        if not line.startswith("COVERAGE class="):
            continue
        fields = parse_fields(line, "COVERAGE ")
        for key in totals:
            totals[key] += int(fields.get(key, 0))
    return totals


def kinds(marker: str) -> tuple[str, ...]:
    if marker == "META_READ":
        return ("IOException", "SocketTimeoutException")
    if marker == "META_WRITE":
        return ("IOException",)
    if marker == "RPC_REQUEST":
        return ("ConnectException", "IOException")
    if marker == "RPC_RESPONSE":
        return ("SocketTimeoutException", "IOException")
    return ()


def source_score(point: dict) -> int:
    marker = point.get("marker", "")
    stage = point.get("stage", "")
    if marker == "META_READ":
        return 95
    if marker == "META_WRITE":
        return 78
    if stage == "meta":
        return 87 if marker == "RPC_REQUEST" else 83
    if marker == "RPC_REQUEST":
        return 61
    return 55


def point_spec(point: dict, kind: str) -> dict:
    return {key: point.get(key, "") for key in (
        "id", "family", "marker", "ordinal", "table", "flushIndex", "stage",
        "method", "destination", "state") } | {"kind": kind}


def sequence_key(faults: list[dict]) -> str:
    return hashlib.sha256("\n".join(f["id"] + " " + f["kind"] for f in faults)
                          .encode()).hexdigest()


def add_candidate(state: dict, faults: list[dict], parent: str, bonus: int) -> None:
    if len(faults) > state["max_faults"]:
        return
    key = sequence_key(faults)
    if key in state["seen_sequences"]:
        return
    state["seen_sequences"].append(key)
    state["queue"].append({"faults": faults, "parent": parent,
                           "base_score": source_score(faults[-1]) + bonus,
                           "queued_round": len(state["completed"])})


def choose(state: dict) -> dict:
    family_tests = state["family_tests"]
    def score(item: dict) -> tuple[int, int]:
        last = item["faults"][-1]
        tested = family_tests.get(last["family"], 0)
        age = len(state["completed"]) - item["queued_round"]
        return (item["base_score"] + 5 * min(len(item["faults"]), 6)
                + (15 if tested == 0 else 0) - 3 * tested + min(age // 8, 12),
                -item["queued_round"])
    index = max(range(len(state["queue"])), key=lambda i: score(state["queue"][i]))
    return state["queue"].pop(index)


def run_junit(name: str, faults: list[dict]) -> tuple[int, dict, set[str], dict[str, int]]:
    if not re.fullmatch(r"gf_(?:healthy|[0-9]{4})", name):
        raise ValueError("unexpected campaign trial name: " + name)
    # A checkpointed inflight trial can be retried after a crash. Start its
    # embedded cluster from an empty, case-local test data directory.
    data_dir = BASE / ("data-campaign-" + name)
    if data_dir.exists():
        shutil.rmtree(data_dir)
    plan = PLANS / (name + ".plan")
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("".join(f["id"] + " " + f["kind"] + "\n" for f in faults))
    log = BASE / (name + ".log")
    coverage_log = BASE / (name + ".coverage")
    (BASE / (name + ".exec")).unlink(missing_ok=True)
    coverage_log.unlink(missing_ok=True)
    with log.open("w") as stream:
        proc = subprocess.run([str(BASE / "run.sh"), "run-campaign", name,
                               str(plan)], stdout=stream, stderr=subprocess.STDOUT)
    if (BASE / (name + ".exec")).exists():
        with coverage_log.open("w") as stream:
            subprocess.run([str(BASE / "run.sh"), "coverage", name],
                           stdout=stream, stderr=subprocess.STDOUT)
    return proc.returncode, observations(log), probes(coverage_log), coverage_counts(coverage_log)


def eligible(row: dict, max_faults: int) -> bool:
    return (0 < row["requested"] <= max_faults
            and row["requested"] == row["matched"] == row["applied"]
            and row["target_after_fault"]
            and row["elapsed_seconds"] is not None)


def effective_count(state: dict) -> int:
    return sum(eligible(json.loads((CHECKPOINTS / (name + ".json")).read_text()),
                        state["max_faults"]) for name in state["completed"])


def initialize() -> dict:
    print("START healthy", now(), flush=True)
    rc, obs, covered, counts = run_junit("gf_healthy", [])
    print("END healthy rc", rc, "targets", len(obs["target_exits"]),
          "checks", len(obs["checks"]), "io", len(obs["points"]),
          "probes", len(covered), "seconds", obs["elapsed_seconds"], flush=True)
    if rc != 0 or len(obs["target_exits"]) != 4 or len(obs["checks"]) != 4:
        raise RuntimeError("graph-free original JUnit healthy seed did not pass and reach four target checks")
    if not obs["points"] or not covered:
        raise RuntimeError("graph-free healthy seed did not record I/O and production JaCoCo probes")
    target_tables = {entry["table"] for entry in obs["target_enters"]}
    relevant_points = [point for point in obs["points"]
                       if point.get("marker") != "META_WRITE"
                       or point.get("table") in target_tables]
    state = {
        "schema_version": 2, "methodology": "coverage_io_independent_bytebuddy_jacoco",
        "coverage_scope_version": "hbase04_production_retry_v2",
        "coverage_scope": COVERAGE_SCOPE,
        "created_utc": now(), "budget_total": DEFAULT_TRIALS,
        "max_faults": DEFAULT_MAX_FAULTS, "completed": [], "inflight": None,
        "queue": [], "seen_sequences": [],
        "seen_stable_families": sorted({p["family"] for p in relevant_points}),
        "seen_io_ids": sorted({p["id"] for p in relevant_points}),
        "target_tables": sorted(target_tables),
        "coverage_probes": sorted(covered), "family_tests": {},
        "bug_candidates": [], "stop_reason": "",
        "healthy": {"exit_code": rc, "elapsed_seconds": obs["elapsed_seconds"],
                    "target_exits": len(obs["target_exits"]),
                    "target_checks": len(obs["checks"]),
                    "io_points": len(relevant_points),
                    "stable_io_families": len({p["family"] for p in relevant_points}),
                    "coverage_probes": len(covered),
                    "production_methods_covered": counts["methods"],
                    "production_branches_covered": counts["branches"],
                    "production_lines_covered": counts["lines"],
                    "log": str(BASE / "gf_healthy.log"),
                    "coverage_log": str(BASE / "gf_healthy.coverage")},
    }
    unique = {p["id"]: p for p in relevant_points}
    for point in unique.values():
        for kind in kinds(point.get("marker", "")):
            add_candidate(state, [point_spec(point, kind)], "healthy", 0)
    save(STATE, state)
    print("INIT queue", len(state["queue"]), "families",
          len(state["seen_stable_families"]), flush=True)
    return state


def finish(state: dict, name: str, item: dict, rc: int,
           obs: dict, covered: set[str], counts: dict[str, int]) -> dict:
    faults = item["faults"]
    applied = obs["applied"]
    exact = [(p["id"], p.get("fault", "")) for p in applied]
    wanted = [(f["id"], f["kind"]) for f in faults]
    matched = sum(1 for wanted_fault, actual in zip(wanted, exact)
                  if wanted_fault == actual)
    strict = exact == wanted
    last_applied = applied[-1]["position"] if applied else -1
    target_after = strict and any(p["position"] > last_applied for p in obs["checks"])
    target_exception = strict and any(
        p["position"] > last_applied and "TableNotEnabledException" in p.get("exception", "")
        for p in obs["target_exits"])
    eligible_run = strict and target_after and obs["elapsed_seconds"] is not None
    relevant_points = [point for point in obs["points"]
                       if point.get("marker") != "META_WRITE"
                       or point.get("table") in state["target_tables"]]
    current_families = {p["family"] for p in relevant_points}
    new_families = sorted(current_families - set(state["seen_stable_families"])) if eligible_run else []
    new_probes = sorted(covered - set(state["coverage_probes"])) if eligible_run else []
    row = {
        "trial": name, "parent": item["parent"], "started_utc": state["inflight"]["started_utc"],
        "ended_utc": now(), "faults": faults,
        "requested": len(faults), "matched": matched, "applied": len(applied),
        "strict_identity_match": strict, "target_after_fault": target_after,
        "target_exception_after_fault": target_exception,
        "target_check_hits": len(obs["checks"]),
        "target_check_outcomes": [point.get("enabled") for point in obs["checks"]],
        "target_exit_hits": len(obs["target_exits"]),
        "junit_result": obs["junit"], "exit_code": rc,
        "elapsed_seconds": obs["elapsed_seconds"],
        "observed_io_points": len(relevant_points),
        "observed_stable_families": len(current_families),
        "new_stable_families": new_families,
        "new_production_probes": new_probes,
        "coverage_probe_count": len(covered),
        "production_methods_covered": counts["methods"],
        "production_branches_covered": counts["branches"],
        "production_lines_covered": counts["lines"],
        "log": str(BASE / (name + ".log")),
        "coverage_log": str(BASE / (name + ".coverage")),
        "plan": str(PLANS / (name + ".plan")),
    }
    save(CHECKPOINTS / (name + ".json"), row)
    state["completed"].append(name)
    state["inflight"] = None
    state["family_tests"][faults[-1]["family"]] = state["family_tests"].get(faults[-1]["family"], 0) + 1
    if eligible_run:
        state["seen_stable_families"] = sorted(set(state["seen_stable_families"]) | current_families)
        state["seen_io_ids"] = sorted(set(state["seen_io_ids"]) | {p["id"] for p in relevant_points})
        state["coverage_probes"] = sorted(set(state["coverage_probes"]) | covered)
        last_index = applied[-1]["position"]
        seen_in_trial = set()
        candidates = sorted(
            (p for p in relevant_points if p["position"] > last_index),
            key=lambda p: (source_score(p), p["position"]), reverse=True)
        extra = 20
        for point in candidates:
            if point["id"] in seen_in_trial or point["id"] in {f["id"] for f in faults}:
                continue
            seen_in_trial.add(point["id"])
            bonus = min(20, 4 * len(new_probes) + 5 * len(new_families))
            for kind in kinds(point.get("marker", "")):
                add_candidate(state, faults + [point_spec(point, kind)], name, bonus)
            if len(seen_in_trial) >= extra:
                break
    if target_exception:
        state["bug_candidates"].append(name)
    save(STATE, state)
    return row


def maybe_extend(state: dict) -> None:
    if effective_count(state) != DEFAULT_TRIALS or state["budget_total"] != DEFAULT_TRIALS:
        return
    valid = [json.loads((CHECKPOINTS / (name + ".json")).read_text())
             for name in state["completed"]]
    recent = [row for row in valid if eligible(row, DEFAULT_MAX_FAULTS)][-EXTENSION_WINDOW:]
    new_coverage = sum(bool(row["new_production_probes"]) for row in recent)
    new_families = sum(bool(row["new_stable_families"]) for row in recent)
    state["extension_checkpoint"] = {
        "recent_effective_trials": [row["trial"] for row in recent],
        "recent_new_production_coverage_trials": new_coverage,
        "recent_new_stable_io_family_trials": new_families,
        "extended": bool(new_coverage or new_families),
    }
    if new_coverage or new_families:
        state["budget_total"] = EXTENDED_TRIALS
        state["max_faults"] = EXTENDED_MAX_FAULTS
        print("EXTEND coverage_trials", new_coverage,
              "stable_io_trials", new_families, flush=True)
    save(STATE, state)


def main() -> None:
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    if os.environ.get("HBASE04_SEED_ONLY") == "1":
        print("SEED_ONLY healthy validated", flush=True)
        return
    while effective_count(state) < state["budget_total"]:
        if len(state["completed"]) >= state["budget_total"] * 3:
            state["stop_reason"] = "attempt_limit"
            break
        if state["inflight"]:
            name = state["inflight"]["trial"]
            item = state["inflight"]["item"]
        else:
            if not state["queue"]:
                state["stop_reason"] = "queue_exhausted"
                break
            item = choose(state)
            name = "gf_%04d" % (len(state["completed"]) + 1)
            state["inflight"] = {"trial": name, "item": item, "started_utc": now()}
            save(STATE, state)
        print("START", name, "depth", len(item["faults"]),
              item["faults"][-1]["marker"], "queue", len(state["queue"]), flush=True)
        rc, obs, covered, counts = run_junit(name, item["faults"])
        row = finish(state, name, item, rc, obs, covered, counts)
        print("END", name, "applied", row["applied"], "/", row["requested"],
              "target", row["target_after_fault"],
              "target_exception", row["target_exception_after_fault"],
              "new_stable", len(row["new_stable_families"]),
              "new_probes", len(row["new_production_probes"]),
              "seconds", row["elapsed_seconds"], flush=True)
        maybe_extend(state)
    if not state["stop_reason"]:
        state["stop_reason"] = "budget_reached"
    save(STATE, state)
    print("STOP", state["stop_reason"], "attempts", len(state["completed"]),
          "effective", effective_count(state), flush=True)


if __name__ == "__main__":
    main()
