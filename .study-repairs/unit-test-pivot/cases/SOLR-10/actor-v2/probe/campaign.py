#!/usr/bin/env python3
"""Resumable, actor-bound, coverage-guided campaign for three shared alias guards.

This file is intentionally case-local. It does not write the 104-check checklist or
replace the historical coarse results. Run only after calibrate.py completes and
cluster slots are assigned.
"""

from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
import sys
import time

from feedback import (CASES, atomic_json, checked_target_identity, events,
                      io_behavior_key, io_identity, strict_sequence,
                      target_after, target_counts)


CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"
CAMPAIGN = EVIDENCE / "campaign"
STATE = CAMPAIGN / "state.json"
HEALTHY = ("healthy-actor-001", "healthy-actor-002")
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
DIST = "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist"
MAX_ATTEMPTS = 240
VALID_PER_SITE = 40
MAX_FAULTS = 10


def relevant(key: tuple[str, str, str, str]) -> bool:
    _, path, _, actor = key
    return (actor.startswith("actor=jetty:node") and
            (path == "/aliases.json" or path == "/collections" or
             path.startswith("/collections/myalias") or
             path.startswith("/overseer") or path == "/live_nodes"))


def rank(key: tuple[str, str, str, str]) -> int:
    operation, path, _, _ = key
    if path == "/aliases.json":
        return 0 if operation == "SET_DATA" else 1
    if path.startswith("/collections/myalias") and path.endswith("/state.json"):
        return 2
    if path.startswith("/collections/myalias") and path.endswith("/collectionprops.json"):
        return 3
    if path.startswith("/collections/myalias"):
        return 4
    if path.startswith("/overseer"):
        return 5
    return 6


def coverage(directory: Path) -> set[str]:
    execution = directory / "jacoco.exec"
    if not execution.exists():
        return set()
    cp = str(CASE / "classes") + ":" + str(CASE.parent / "work/lib/jacoco-core.jar")
    output = subprocess.check_output([JAVA, "-cp", cp,
                                      "baseline.solr103940.CoverageProbes",
                                      str(execution), DIST], text=True)
    return set(output.splitlines())


def selector(key: tuple[str, str, str, str], ordinal: int,
             after: str | None = None, global_hit: int = 0) -> str:
    operation, path, caller, actor = key
    fields = [operation, path, ("@" if after else "") + str(ordinal), caller, actor]
    if after:
        fields.extend(("after=" + after, "seed_global=" + str(global_hit)))
    return "|".join(fields)


def initial_queue(traces: list[list[dict]]) -> list[list[str]]:
    seeds = []
    seen = set()
    for trace in traces:
        targets = [e for e in trace if e["kind"] == "TARGET_CHECK" and
                   len(e["parts"]) > 1 and e["parts"][1] in CASES]
        if not targets or any(target_counts(trace)[site] == 0 for site in CASES):
            raise RuntimeError("Healthy seed has no exact targets")
        last_target = max(e["seq"] for e in targets)
        counts = Counter()
        hits = defaultdict(list)
        for event in trace:
            key = io_identity(event)
            if key is None:
                continue
            counts[key] += 1
            if relevant(key) and event["seq"] < last_target:
                hits[key].append((counts[key], event["seq"]))
        for key, occurrences in hits.items():
            sample = {0, len(occurrences) // 4, len(occurrences) // 2,
                      3 * len(occurrences) // 4, len(occurrences) - 1}
            for index in sorted(sample):
                ordinal, seq = occurrences[index]
                plan = [selector(key, ordinal)]
                encoded = ";".join(plan)
                if encoded in seen:
                    continue
                seen.add(encoded)
                future = {e["parts"][1] for e in targets if e["seq"] > seq}
                seeds.append((-len(future), rank(key), -seq, plan))
    seeds.sort(key=lambda item: item[:3])
    return [plan for _, _, _, plan in seeds]


def initialize() -> dict:
    summary = json.loads((EVIDENCE / "healthy-summary.json").read_text())
    if not summary.get("calibration_complete"):
        raise RuntimeError("Two healthy actor-aware calibrations must complete first")
    traces = [events(EVIDENCE / name / "events.tsv") for name in HEALTHY]
    base_coverage = set().union(*(coverage(EVIDENCE / name) for name in HEALTHY))
    base_io = {key for trace in traces for event in trace
               if (key := io_behavior_key(event)) is not None}
    state = {
        "identity_version": "actor-v2", "case_ids": CASES,
        "test": "TimeRoutedAliasUpdateProcessorTest.test",
        "budget": {"max_attempts": MAX_ATTEMPTS,
                   "valid_per_site": VALID_PER_SITE, "max_faults": MAX_FAULTS},
        "started_at": time.time(), "elapsed_seconds": 0.0,
        "healthy_target_checks": {
            site: sum(target_counts(trace)[site] for trace in traces) for site in CASES},
        "healthy_coverage": sorted(base_coverage), "healthy_io": sorted(base_io),
        "seen_coverage": {site: sorted(base_coverage) for site in CASES},
        "seen_io": {site: sorted(base_io) for site in CASES},
        "queue": initial_queue(traces), "seen_plans": [], "trials": [],
        "inflight": None,
    }
    if not state["queue"]:
        raise RuntimeError("No actor-bound relevant I/O before exact guards")
    atomic_json(STATE, state)
    return state


def valid_count(state: dict, site: str) -> int:
    return sum(t["strict"] and t["target_after_fault"][site] for t in state["trials"])


def done(state: dict) -> bool:
    return (len(state["trials"]) >= state["budget"]["max_attempts"] or
            all(valid_count(state, site) >= state["budget"]["valid_per_site"] for site in CASES) or
            (not state["queue"] and state["inflight"] is None))


def pick(state: dict) -> list[str]:
    queue = state["queue"]
    if (len(state["trials"]) + 1) % 4 == 0:
        root = next((i for i, plan in enumerate(queue) if len(plan) == 1), None)
        if root is not None:
            return queue.pop(root)
    return queue.pop(0)


def mutate(state: dict, plan: list[str], trace: list[dict], trial: dict) -> None:
    if (len(plan) >= state["budget"]["max_faults"] or not trial["strict"] or
            not any(trial["target_after_fault"].values())):
        return
    final = max(e["seq"] for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS")
    targets = [e for e in trace if e["kind"] == "TARGET_CHECK" and e["seq"] > final]
    final_target = max(e["seq"] for e in targets)
    global_count, relative_count = Counter(), Counter()
    candidates = []
    known = set(state["seen_plans"]) | {";".join(p) for p in state["queue"]}
    for event in trace:
        key = io_identity(event)
        if key is None:
            continue
        global_count[key] += 1
        if event["seq"] > final:
            relative_count[key] += 1
        if not (final + 2 < event["seq"] < final_target - 2 and relevant(key)):
            continue
        future = {e["parts"][1] for e in targets if e["seq"] > event["seq"]}
        if not future:
            continue
        child = plan + [selector(key, relative_count[key],
                                 after="F" + str(len(plan) - 1),
                                 global_hit=global_count[key])]
        encoded = ";".join(child)
        if encoded not in known:
            candidates.append((-len(future), rank(key), event["seq"], child))
            known.add(encoded)
    candidates.sort(key=lambda item: item[:3])
    novelty = any(trial["new_coverage"].values()) or any(trial["new_io"].values())
    limit = 3 if novelty or len(plan) == 1 else 1
    children = []
    families = set()
    for _, _, _, child in candidates:
        op, path = child[-1].split("|", 2)[:2]
        family = (op, path if path == "/aliases.json" else "/".join(path.split("/")[:3]))
        if family in families:
            continue
        families.add(family)
        children.append(child)
        if len(children) >= limit:
            break
    state["queue"] = children + state["queue"]


def run() -> None:
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    while not done(state):
        if state["inflight"] is None:
            plan = pick(state)
            state["inflight"] = {"number": len(state["trials"]) + 1, "plan": plan}
            atomic_json(STATE, state)
        number = state["inflight"]["number"]
        plan = state["inflight"]["plan"]
        output = CAMPAIGN / f"trial-{number:03d}"
        started = time.time()
        subprocess.run([sys.executable, str(CASE / "probe/run.py"), str(output),
                        "--coverage", "--faults", ";".join(plan), "--timeout", "360"],
                       check=False)
        manifest = json.loads((output / "manifest.json").read_text())
        trace = events(output / "events.tsv")
        strict = strict_sequence(plan, trace) and checked_target_identity(trace)
        applied = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        after, exception = target_after(trace, max((e["seq"] for e in applied), default=-1))
        current_cov = coverage(output) if strict and any(after.values()) else set()
        current_io = {key for event in trace if (key := io_behavior_key(event)) is not None}
        novelty_cov, novelty_io = {}, {}
        for site in CASES:
            eligible = strict and after[site]
            old_cov = set(state["seen_coverage"][site])
            old_io = set(state["seen_io"][site])
            novelty_cov[site] = len(current_cov - old_cov) if eligible else 0
            novelty_io[site] = len(current_io - old_io) if eligible else 0
            if eligible:
                state["seen_coverage"][site] = sorted(old_cov | current_cov)
                state["seen_io"][site] = sorted(old_io | current_io)
        trial = {
            "number": number, "plan": plan, "strict": strict,
            "faults_applied": len(applied), "junit_exit": manifest["exit_code"],
            "target_checks": target_counts(trace), "target_after_fault": after,
            "target_exception": exception, "new_coverage": novelty_cov,
            "new_io": novelty_io, "elapsed_seconds": round(time.time() - started, 3),
            "evidence": str(output.relative_to(CASE)),
        }
        mutate(state, plan, trace, trial)
        state["trials"].append(trial)
        state["seen_plans"].append(";".join(plan))
        state["elapsed_seconds"] += trial["elapsed_seconds"]
        state["inflight"] = None
        atomic_json(output / "trial.json", trial)
        atomic_json(STATE, state)
        print(json.dumps({"trial": number, "strict": strict, "after": after,
                          "exception": exception, "valid": {site: valid_count(state, site)
                                                          for site in CASES}}), flush=True)


if __name__ == "__main__":
    run()
