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
                      io_behavior_key, io_family, io_identity, strict_sequence,
                      target_after, target_counts)


CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"
CAMPAIGN = EVIDENCE / "campaign"
STATE = CAMPAIGN / "state.json"
HEALTHY = ("healthy-actor-001", "healthy-actor-002")
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
DIST = "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist"
BASE_ATTEMPTS, BASE_VALID_PER_SITE, BASE_FAULTS = 240, 80, 8
EXTENDED_ATTEMPTS, EXTENDED_VALID_PER_SITE, EXTENDED_FAULTS = 384, 128, 10


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


def method_branch_coverage(directory: Path) -> tuple[set[str], dict[str, int]]:
    """Return covered production methods and covered branch counts per method.

    JaCoCo's method counter identifies a newly covered method. An increase in
    a method's covered branch count is a conservative branch-novelty signal;
    equal counts do not prove that the exact same branch outcomes executed.
    """
    execution = directory / "jacoco.exec"
    if not execution.exists():
        return set(), {}
    asm = "/users/ZhenyuLi/.m2/repository/org/ow2/asm"
    jars = [f"{asm}/{module}/9.10.1/{module}-9.10.1.jar"
            for module in ("asm", "asm-tree", "asm-commons")]
    cp = ":".join([str(CASE / "classes"),
                   str(CASE.parent / "work/lib/jacoco-core.jar"), *jars])
    output = subprocess.check_output([JAVA, "-cp", cp,
                                      "baseline.solr103940.CoverageFeedback",
                                      DIST, str(CASE / "classes"), str(execution)], text=True)
    branches = {}
    for line in output.splitlines():
        method, covered = line.rsplit("\t", 1)
        branches[method] = int(covered)
    return set(branches), branches


def merge_branches(*maps: dict[str, int]) -> dict[str, int]:
    result = {}
    for values in maps:
        for method, count in values.items():
            result[method] = max(result.get(method, 0), count)
    return result


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
    healthy_methods = [method_branch_coverage(EVIDENCE / name) for name in HEALTHY]
    base_methods = set().union(*(methods for methods, _ in healthy_methods))
    base_branches = merge_branches(*(branches for _, branches in healthy_methods))
    base_io = {key for trace in traces for event in trace
               if (key := io_behavior_key(event)) is not None}
    base_families = {family for trace in traces for event in trace
                     if (family := io_family(event)) is not None}
    state = {
        "identity_version": "actor-v2", "case_ids": CASES,
        "test": "TimeRoutedAliasUpdateProcessorTest.test",
        "budget": {"base_attempts": BASE_ATTEMPTS,
                   "base_valid_per_site": BASE_VALID_PER_SITE,
                   "base_max_faults": BASE_FAULTS,
                   "extended_attempts": EXTENDED_ATTEMPTS,
                   "extended_valid_per_site": EXTENDED_VALID_PER_SITE,
                   "extended_max_faults": EXTENDED_FAULTS,
                   "max_attempts": BASE_ATTEMPTS, "max_faults": BASE_FAULTS},
        "started_at": time.time(), "elapsed_seconds": 0.0,
        "healthy_target_checks": {
            site: sum(target_counts(trace)[site] for trace in traces) for site in CASES},
        "healthy_coverage": sorted(base_coverage), "healthy_io": sorted(base_io),
        "healthy_methods": sorted(base_methods), "healthy_branches": base_branches,
        "healthy_io_families": sorted(base_families),
        "seen_coverage": {site: sorted(base_coverage) for site in CASES},
        "seen_io": {site: sorted(base_io) for site in CASES},
        "seen_methods": {site: sorted(base_methods) for site in CASES},
        "seen_branches": {site: dict(base_branches) for site in CASES},
        "seen_io_families": {site: sorted(base_families) for site in CASES},
        "site_progress": {site: {"effective": 0, "goal": BASE_VALID_PER_SITE,
                                 "extension": "pending", "last_eight_effective": []}
                          for site in CASES},
        "queue": initial_queue(traces), "seen_plans": [], "trials": [],
        "inflight": None,
    }
    if not state["queue"]:
        raise RuntimeError("No actor-bound relevant I/O before exact guards")
    atomic_json(STATE, state)
    write_checkpoints(state)
    return state


def valid_count(state: dict, site: str) -> int:
    return state["site_progress"][site]["effective"]


def write_checkpoints(state: dict) -> None:
    """Case-specific mirrors; state.json remains authoritative after a crash."""
    for site in CASES:
        atomic_json(CAMPAIGN / "checkpoints" / f"{site}.json", {
            "case_id": site, "identity_version": "actor-v2",
            "authoritative_state": str(STATE),
            "attempts": len(state["trials"]),
            "max_attempts": state["budget"]["max_attempts"],
            "max_faults": state["budget"]["max_faults"],
            **state["site_progress"][site],
        })


def update_progress(state: dict, trial: dict) -> None:
    for site in CASES:
        if not (trial["strict"] and trial["target_after_fault"][site]):
            continue
        progress = state["site_progress"][site]
        progress["effective"] += 1
        recent = {
            "trial": trial["number"],
            "new_methods": trial["new_methods"][site],
            "new_branches": trial["new_branches"][site],
            "new_io_families": trial["new_io_families"][site],
        }
        progress["last_eight_effective"] = (progress["last_eight_effective"] + [recent])[-8:]
        if (progress["effective"] >= BASE_VALID_PER_SITE and
                progress["extension"] == "pending"):
            novel = any(item["new_methods"] > 0 or item["new_branches"] > 0 or
                        item["new_io_families"] > 0
                        for item in progress["last_eight_effective"])
            progress["extension"] = "extended" if novel else "not_extended"
            progress["goal"] = EXTENDED_VALID_PER_SITE if novel else BASE_VALID_PER_SITE
            if novel:
                state["budget"]["max_attempts"] = EXTENDED_ATTEMPTS
                state["budget"]["max_faults"] = EXTENDED_FAULTS


def done(state: dict) -> bool:
    return (len(state["trials"]) >= state["budget"]["max_attempts"] or
            all(valid_count(state, site) >= state["site_progress"][site]["goal"]
                for site in CASES) or
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
    novelty = (any(trial["new_coverage"].values()) or
               any(trial["new_methods"].values()) or
               any(trial["new_branches"].values()) or
               any(trial["new_io"].values()) or
               any(trial["new_io_families"].values()))
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
    write_checkpoints(state)
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
        current_methods, current_branches = (method_branch_coverage(output)
                                             if strict and any(after.values()) else (set(), {}))
        current_io = {key for event in trace if (key := io_behavior_key(event)) is not None}
        current_families = {family for event in trace
                            if (family := io_family(event)) is not None}
        novelty_cov, novelty_io = {}, {}
        novelty_methods, novelty_branches, novelty_families = {}, {}, {}
        for site in CASES:
            eligible = strict and after[site]
            old_cov = set(state["seen_coverage"][site])
            old_io = set(state["seen_io"][site])
            old_methods = set(state["seen_methods"][site])
            old_branches = state["seen_branches"][site]
            old_families = set(state["seen_io_families"][site])
            novelty_cov[site] = len(current_cov - old_cov) if eligible else 0
            novelty_io[site] = len(current_io - old_io) if eligible else 0
            novelty_methods[site] = len(current_methods - old_methods) if eligible else 0
            novelty_branches[site] = (sum(max(0, count - old_branches.get(method, 0))
                                          for method, count in current_branches.items())
                                      if eligible else 0)
            novelty_families[site] = len(current_families - old_families) if eligible else 0
            if eligible:
                state["seen_coverage"][site] = sorted(old_cov | current_cov)
                state["seen_io"][site] = sorted(old_io | current_io)
                state["seen_methods"][site] = sorted(old_methods | current_methods)
                state["seen_branches"][site] = merge_branches(old_branches, current_branches)
                state["seen_io_families"][site] = sorted(old_families | current_families)
        trial = {
            "number": number, "plan": plan, "strict": strict,
            "faults_applied": len(applied), "junit_exit": manifest["exit_code"],
            "target_checks": target_counts(trace), "target_after_fault": after,
            "target_exception": exception, "new_coverage": novelty_cov,
            "new_methods": novelty_methods, "new_branches": novelty_branches,
            "new_io": novelty_io, "new_io_families": novelty_families,
            "elapsed_seconds": round(time.time() - started, 3),
            "evidence": str(output.relative_to(CASE)),
        }
        update_progress(state, trial)
        mutate(state, plan, trace, trial)
        state["trials"].append(trial)
        state["seen_plans"].append(";".join(plan))
        state["elapsed_seconds"] += trial["elapsed_seconds"]
        state["inflight"] = None
        atomic_json(output / "trial.json", trial)
        atomic_json(STATE, state)
        write_checkpoints(state)
        print(json.dumps({"trial": number, "strict": strict, "after": after,
                          "exception": exception, "valid": {site: valid_count(state, site)
                                                          for site in CASES},
                          "goals": {site: state["site_progress"][site]["goal"]
                                    for site in CASES}}), flush=True)


if __name__ == "__main__":
    run()
