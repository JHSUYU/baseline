#!/usr/bin/env python3
"""Resumable B3-targeted original-JUnit I/O fuzzer, with HBASE-31 oracle."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys


BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE.parent))
import mirror as b3  # noqa: E402; parser for the shared HBASE-12 target semantics
HBASE10_SOURCE = BASE.parents[2] / "HBASE-10" / "independent"
STATE = BASE / "campaign-state.json"
CHECKPOINTS = BASE / "campaign-checkpoints"
PLANS = BASE / "campaign-plans"
DEFAULT_TRIALS = 80
DEFAULT_MAX_FAULTS = 8
EXTENDED_TRIALS = 128
EXTENDED_MAX_FAULTS = 10
EXTENSION_WINDOW = 16
COVERAGE_SCOPE = [
    "org/apache/hadoop/hbase/master/assignment/AssignmentManager",
    "org/apache/hadoop/hbase/master/assignment/RegionStateNode",
    "org/apache/hadoop/hbase/master/assignment/TransitRegionStateProcedure",
    "org/apache/hadoop/hbase/master/MasterRpcServices",
    "org/apache/hadoop/hbase/client/HBaseAdmin",
    "org/apache/hadoop/hbase/client/RpcRetryingCallerImpl",
    "org/apache/hadoop/hbase/client/MasterCallable",
    "org/apache/hadoop/hbase/ipc/AbstractRpcClient",
    "org/apache/hadoop/hbase/regionserver/RSRpcServices",
]


def b3_events(path: Path) -> list[dict]:
    return [event for event in b3.trace(path)["targets"] if b3.selected(event)]


def rs_events(path: Path) -> list[dict]:
    entries = {}
    for position, line in enumerate(path.open(errors="replace")):
        if line.startswith("HBASE31 TARGET_ENTER "):
            event = parse_fields(line, "HBASE31 TARGET_ENTER ")
            event["enter_position"] = position
            entries[event["ordinal"]] = event
        elif line.startswith("HBASE31 TARGET_EXIT "):
            event = parse_fields(line, "HBASE31 TARGET_EXIT ")
            prior = entries.get(event["ordinal"])
            if prior is not None:
                prior.update(event)
                prior["exit_position"] = position
    return sorted((event for event in entries.values()
                   if event.get("duringTest") == "true"
                   and event.get("relevantTable") == "true"
                   and "exit_position" in event),
                  key=lambda event: event["exit_position"])


def tested_by_hbase10() -> set[str]:
    state_path = HBASE10_SOURCE / "campaign-state.json"
    if not state_path.exists():
        return set()
    source = json.loads(state_path.read_text())
    result = set()
    for name in source.get("completed", []):
        checkpoint = HBASE10_SOURCE / "campaign-checkpoints" / (name + ".json")
        if checkpoint.exists():
            result.add(sequence_key(json.loads(checkpoint.read_text())["faults"]))
    return result


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
    junit = None
    elapsed = None
    for position, line in enumerate(path.open(errors="replace")):
        line = line.rstrip("\n")
        if line.startswith("HBASE10 IO "):
            point = parse_fields(line, "HBASE10 IO ")
            point["position"] = position
            points.append(point)
            if point.get("applied") == "true":
                applied.append(point)
        elif line.startswith("HBASE10 TARGET_ENTER "):
            target_enters.append({**parse_fields(line, "HBASE10 TARGET_ENTER "),
                                  "position": position})
        elif line.startswith("HBASE10 TARGET_EXIT "):
            target_exits.append({**parse_fields(line, "HBASE10 TARGET_EXIT "),
                                 "position": position})
        elif "JUNIT found=" in line:
            junit = line.strip()
        elif line.startswith("ELAPSED_SECONDS="):
            match = re.search(r"ELAPSED_SECONDS=([0-9.]+)", line)
            if match:
                elapsed = float(match.group(1))
    return {"points": points, "applied": applied, "target_enters": target_enters,
            "target_exits": target_exits, "junit": junit,
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
    if marker == "RPC_REQUEST":
        return ("ConnectException", "IOException")
    if marker == "RPC_RESPONSE":
        return ("SocketTimeoutException", "IOException")
    return ()


def source_score(point: dict) -> int:
    marker = point.get("marker", "")
    step = point.get("step", "")
    method = point.get("method", "")
    if method.endswith("UnassignRegion"):
        return 30 if marker == "RPC_RESPONSE" else 100
    if method.endswith("AssignRegion"):
        return 25 if marker == "RPC_RESPONSE" else 98
    if method.endswith("MoveRegion") and step == "move#1":
        return 70 if marker == "RPC_REQUEST" else 28
    if method.endswith("MoveRegion") and step == "move#2":
        return 55 if marker == "RPC_REQUEST" else 10
    if method.endswith("DisableTable"):
        return 65 if marker == "RPC_REQUEST" else 35
    if method.endswith("Get"):
        return 75 if marker == "RPC_REQUEST" else 40
    return 65 if marker == "RPC_REQUEST" else 35


def point_spec(point: dict, kind: str) -> dict:
    return {key: point.get(key, "") for key in (
        "id", "family", "marker", "ordinal", "step", "method", "destination")
    } | {"kind": kind}


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


def choose(state: dict) -> dict | None:
    # The adjacent HBASE-10 check already executed these exact ordered faults.
    # Keep its completed executions as independent HBASE-12 evidence, and only
    # launch sequences that have not yet been run there.
    previous = tested_by_hbase10()
    state["queue"] = [item for item in state["queue"]
                      if sequence_key(item["faults"]) not in previous]
    if not state["queue"]:
        return None
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
    data_dir = BASE / ("data-" + name)
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
        proc = subprocess.run([str(BASE / "run.sh"), "run", name,
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
    targets = b3_events(BASE / "gf_healthy.log")
    rs_targets = rs_events(BASE / "gf_healthy.log")
    print("END healthy rc", rc, "B3", len(targets), "RS", len(rs_targets),
          "io", len(obs["points"]), "probes", len(covered),
          "seconds", obs["elapsed_seconds"], flush=True)
    if rc != 0 or len(targets) != 2 or len(rs_targets) < 1:
        raise RuntimeError("original JUnit did not pass and reach both B3 and RS checks")
    if any(b3.thrown(target) for target in targets):
        raise RuntimeError("selected B3 exception already appears in healthy JUnit")
    if any(target["mismatch"] != "false" for target in rs_targets):
        raise RuntimeError("RS startcode mismatch already appears in healthy JUnit")
    if not obs["points"] or not covered:
        raise RuntimeError("graph-free healthy seed did not record I/O and production JaCoCo probes")
    last_target_exit = max(p["exit_position"] for p in targets)
    relevant_points = [p for p in obs["points"] if p["position"] < last_target_exit]
    state = {
        "schema_version": 3, "methodology": "coverage_io_independent_bytebuddy_jacoco",
        "coverage_scope_version": "hbase12_b3_rs_production_v1",
        "coverage_scope": COVERAGE_SCOPE,
        "created_utc": now(), "budget_total": DEFAULT_TRIALS,
        "max_faults": DEFAULT_MAX_FAULTS, "completed": [], "inflight": None,
        "queue": [], "seen_sequences": [],
        "seen_stable_families": sorted({p["family"] for p in relevant_points}),
        "seen_io_ids": sorted({p["id"] for p in relevant_points}),
        "target_table": "testDisableAndMove",
        "target_check": "AssignmentManager.preTransitCheck B3 isTableDisabled",
        "shared_oracle_check": "RSRpcServices.throwOnWrongStartCode",
        "coverage_probes": sorted(covered), "family_tests": {},
        "bug_candidates": [], "stop_reason": "",
        "healthy": {"exit_code": rc, "elapsed_seconds": obs["elapsed_seconds"],
                    "target_exits": len(targets),
                    "target_checks": len(targets),
                    "target_guard_outcomes": [p.get("exception") for p in targets],
                    "rs_target_checks": len(rs_targets),
                    "rs_target_guard_outcomes": [p.get("mismatch") for p in rs_targets],
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
    target_events = b3_events(BASE / (name + ".log"))
    rs_targets = rs_events(BASE / (name + ".log"))
    target_after = strict and any(p["exit_position"] > last_applied for p in target_events)
    target_exception = strict and any(
        p["exit_position"] > last_applied and b3.thrown(p)
        for p in target_events)
    rs_after = strict and any(p["exit_position"] > last_applied for p in rs_targets)
    rs_exception = strict and any(
        p["exit_position"] > last_applied
        and p.get("mismatch") == "true"
        and p.get("exception") == "org.apache.hbase.thirdparty.com.google.protobuf.ServiceException"
        and p.get("cause") == "org.apache.hadoop.hbase.DoNotRetryIOException"
        for p in rs_targets)
    eligible_run = strict and target_after and obs["elapsed_seconds"] is not None
    # Only I/O before this check can influence the selected B3 outcome.
    # The original JUnit continues through table disable and a final move,
    # whose later RPCs must not appear as new B3-guiding families.
    last_b3_exit = max((p["exit_position"] for p in target_events), default=-1)
    relevant_points = [p for p in obs["points"] if p["position"] < last_b3_exit]
    current_families = {p["family"] for p in relevant_points}
    new_families = sorted(current_families - set(state["seen_stable_families"])) if eligible_run else []
    new_probes = sorted(covered - set(state["coverage_probes"])) if eligible_run else []
    row = {
        "trial": name, "parent": item["parent"], "started_utc": state["inflight"]["started_utc"],
        "ended_utc": now(), "faults": faults,
        "requested": len(faults), "matched": matched, "applied": len(applied),
        "strict_identity_match": strict, "target_after_fault": target_after,
        "target_exception_after_fault": target_exception,
        "target_check_hits": len(target_events),
        "target_check_outcomes": [point.get("exception") for point in target_events],
        "target_exit_outcomes": [point.get("exception") for point in target_events],
        "target_exit_hits": len(target_events),
        "rs_target_check_hits": len(rs_targets),
        "rs_target_after_fault": rs_after,
        "rs_target_exception_after_fault": rs_exception,
        "rs_target_outcomes": [{key: point.get(key) for key in (
            "ordinal", "mismatch", "requestedStartCode", "actualStartCode",
            "exception", "cause", "exit_position")}
            for point in rs_targets],
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
        last_target_exit = last_b3_exit
        seen_in_trial = set()
        candidates = sorted(
            (p for p in relevant_points
             if last_index < p["position"] < last_target_exit),
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
    if os.environ.get("HBASE12_SEED_ONLY") == "1":
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
            if item is None:
                state["stop_reason"] = "queue_exhausted_after_prior_completed_sequence_filter"
                break
            name = "gf_%04d" % (len(state["completed"]) + 1)
            state["inflight"] = {"trial": name, "item": item, "started_utc": now()}
            save(STATE, state)
        print("START", name, "depth", len(item["faults"]),
              item["faults"][-1]["marker"], "queue", len(state["queue"]), flush=True)
        rc, obs, covered, counts = run_junit(name, item["faults"])
        row = finish(state, name, item, rc, obs, covered, counts)
        print("END", name, "applied", row["applied"], "/", row["requested"],
              "B3", row["target_after_fault"],
              "B3_exception", row["target_exception_after_fault"],
              "RS", row["rs_target_after_fault"],
              "RS_exception", row["rs_target_exception_after_fault"],
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
