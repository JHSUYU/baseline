#!/usr/bin/env python3
"""Resumable, actor-bound, coverage-guided campaign for three shared alias guards.

This file is intentionally case-local. It does not write the 104-check checklist or
replace the historical coarse results. Run only after calibrate.py completes and
cluster slots are assigned.
"""

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from deps import asm_jars
from feedback import (CASES, actor_relation, atomic_json, checked_target_identity, events,
                      io_behavior_key, io_family, io_identity, runtime_actor,
                      strict_sequence, target_after, target_after_any_actor,
                      target_counts, target_relations)


CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"
CAMPAIGN = EVIDENCE / "campaign-v4"
STATE = CAMPAIGN / "state.json"
HEALTHY = ("healthy-actor-v4-001", "healthy-actor-v4-002")
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
DIST = "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist"
BASE_ATTEMPTS, BASE_VALID_PER_SITE, BASE_FAULTS = 720, 80, 8
EXTENDED_ATTEMPTS, EXTENDED_VALID_PER_SITE, EXTENDED_FAULTS = 1152, 128, 10
V4_SCHEDULER_SHA256 = "0ad2cc385e4839af4be8ebadc72eac24262b95f2cc083c1eb7469f62e8f79742"
V7_SCHEDULER_SHA256 = "15b4a3a5d6351163b15bd10aa9184edc059ca86efee545a134642661cc933a68"
V8_SCHEDULER_SHA256 = "a3cb548fec2807323df258dbd1f649162ec177d86c44738aa91048decb5a6b8e"
HANDOFF_HEALTHY = "campaign-v4/node1-handoff-calibration/actor"


def relevant(key: tuple[str, str, str, str]) -> bool:
    _, path, _, actor = key
    return ((actor.startswith("actor=jetty:node") or actor == "actor=alias-writer") and
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
    solr_cp = (CASE / "classpath.txt").read_text().strip()
    cp = ":".join([str(CASE / "classes"),
                   str(CASE.parent / "work/lib/jacoco-core.jar"),
                   *map(str, asm_jars()), solr_cp])
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
                if any(e["seq"] > event["seq"] and
                       actor_relation(event, e) for e in targets):
                    hits[key].append((counts[key], event["seq"], event))
        for key, occurrences in hits.items():
            sample = {0, len(occurrences) // 4, len(occurrences) // 2,
                      3 * len(occurrences) // 4, len(occurrences) - 1}
            for index in sorted(sample):
                ordinal, seq, source_event = occurrences[index]
                plan = [selector(key, ordinal)]
                encoded = ";".join(plan)
                if encoded in seen:
                    continue
                seen.add(encoded)
                future = {e["parts"][1] for e in targets if e["seq"] > seq and
                          actor_relation(source_event, e)}
                seeds.append((-len(future), rank(key), -seq, plan))
    seeds.sort(key=lambda item: item[:3])
    return [plan for _, _, _, plan in seeds]


def seed_target_sites(traces: list[list[dict]]) -> dict[str, list[str]]:
    """Source/actor-linked future guards for each healthy single-fault seed."""
    site_map = defaultdict(set)
    for trace in traces:
        targets = [event for event in trace if event["kind"] == "TARGET_CHECK" and
                   len(event["parts"]) > 1 and event["parts"][1] in CASES]
        counts = Counter()
        for event in trace:
            key = io_identity(event)
            if key is None:
                continue
            counts[key] += 1
            if not relevant(key):
                continue
            plan = selector(key, counts[key])
            site_map[plan].update(target["parts"][1] for target in targets
                                  if target["seq"] > event["seq"] and
                                  actor_relation(event, target))
    return {plan: sorted(sites) for plan, sites in site_map.items() if sites}


def untested_lazy_roots(state: dict, traces: list[list[dict]],
                        names: tuple[str, ...] = HEALTHY) -> dict[str, list[dict]]:
    """Find real healthy I/O occurrences that precede SOLR-39 on one live reader."""
    known = set(state["seen_plans"]) | {";".join(plan) for plan in state["queue"]}
    observed = defaultdict(list)
    for name, trace in zip(names, traces):
        targets = [event for event in trace if event["kind"] == "TARGET_CHECK" and
                   len(event["parts"]) > 1 and event["parts"][1] == "SOLR-39"]
        counts = Counter()
        for event in trace:
            key = io_identity(event)
            if key is None:
                continue
            counts[key] += 1
            operation, path, caller, actor = key
            if (operation != "EXISTS_WATCH" or
                    not path.startswith("/collections/myalias__TRA__") or
                    not path.endswith("/state.json") or
                    "LazyCollectionRef#get:" not in caller or
                    not actor.startswith("actor=jetty:node")):
                continue
            plan = selector(key, counts[key])
            if plan in known:
                continue
            for target in targets:
                if (target["seq"] <= event["seq"] or
                        actor_relation(event, target) != "same_live_client_manager"):
                    continue
                observed[plan].append({
                    "healthy_trace": name, "io_seq": event["seq"],
                    "target_seq": target["seq"],
                    "io_runtime_actor": list(runtime_actor(event)),
                    "target_runtime_actor": list(runtime_actor(target)),
                    "event_gap": target["seq"] - event["seq"],
                })
                break
    return {plan: observed[plan] for plan in sorted(observed)}


def initialize() -> dict:
    summary = json.loads((EVIDENCE / "healthy-summary-v4.json").read_text())
    if not summary.get("calibration_complete"):
        raise RuntimeError("Two healthy actor-aware calibrations must complete first")
    build_hash = hashlib.sha256((CASE / "build-receipt.json").read_bytes()).hexdigest()
    if summary.get("build_receipt_sha256") != build_hash:
        raise RuntimeError("Healthy seeds were generated by a different actor-hook build")
    for name in HEALTHY:
        receipt = json.loads((EVIDENCE / name / "manifest.json").read_text())
        if receipt.get("build_receipt_sha256") != build_hash:
            raise RuntimeError(f"Healthy trace {name} does not match the active actor-hook build")
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
        "build_receipt_sha256": build_hash,
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
                                 "extension": "pending", "last_eight_effective": [],
                                 "stop_reason": "running"}
                          for site in CASES},
        "queue": initial_queue(traces), "seen_plans": [], "trials": [],
        "seed_target_sites": seed_target_sites(traces),
        "scheduler_version": "balanced_watch_reads_v4",
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


def update_stop_reasons(state: dict) -> None:
    attempts_exhausted = len(state["trials"]) >= state["budget"]["max_attempts"]
    queue_exhausted = not state["queue"] and state["inflight"] is None
    for site in CASES:
        progress = state["site_progress"][site]
        if progress["effective"] >= progress["goal"]:
            reason = "goal_met"
        elif attempts_exhausted:
            reason = "attempt_cap_before_goal"
        elif queue_exhausted:
            reason = "queue_exhausted_before_goal"
        else:
            reason = "running"
        progress["stop_reason"] = reason


def reclaim_completed_scratch(state: dict) -> None:
    """After interruption, remove scratch only for completed non-candidates."""
    for trial in state["trials"]:
        if not trial.get("scratch_retained", True):
            scratch = CAMPAIGN / f"trial-{trial['number']:03d}" / "scratch"
            if scratch.exists():
                shutil.rmtree(scratch)


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
    number = len(state["trials"]) + 1
    # Once the other two checks are complete, spend alternate rounds on
    # untested roots with a healthy-trace relation to SOLR-10's live target.
    # Odd rounds retain the existing queue and multi-fault mutation order.
    if (state.get("solr10_focus_v10") and number % 2 == 0 and
            state["site_progress"]["SOLR-10"]["effective"] <
            state["site_progress"]["SOLR-10"]["goal"]):
        targets = state.get("seed_target_sites", {})
        seen = set(state["seen_plans"])
        candidates = [(index, plan[0]) for index, plan in enumerate(queue)
                      if len(plan) == 1 and plan[0] not in seen and
                      "SOLR-10" in targets.get(plan[0], [])]
        if state.get("solr10_rank_v10b"):
            def rank(selector: str) -> int:
                if (selector.startswith("EXISTS_WATCH|/collections/myalias") and
                        "/state.json|" in selector and
                        "LazyCollectionRef#get:" in selector):
                    return 0
                if (selector.startswith("GET_CHILDREN_STAT|/collections/myalias") and
                        "/state.json|" in selector):
                    return 1
                if selector.startswith("GET_DATA|/aliases.json|"):
                    return 2
                return 3
            root = min(candidates, key=lambda entry: (rank(entry[1]), entry[0]))[0] if candidates else None
        else:
            root = candidates[0][0] if candidates else None
        if root is not None:
            return queue.pop(root)
    # The first V4 tranche showed that SOLR-39 retained its exact reader only
    # under single-fault plans. Keep exploring the mutated queue on alternate
    # rounds, while spending the other rounds on previously unseen roots whose
    # healthy actor/target trace establishes the same-client relation.
    if (state.get("scheduler_version") in
            ("solr39_root_balance_v5", "solr39_lazy_occurrence_v7",
             "solr39_lazy_retry_v8", "solr39_handoff_roots_v9") and
            state["site_progress"]["SOLR-39"]["effective"] <
            state["site_progress"]["SOLR-39"]["goal"] and number % 2 == 0):
        targeted = state.get("seed_target_sites", {})
        seen = set(state["seen_plans"])
        candidates = []
        for index, plan in enumerate(queue):
            if len(plan) != 1 or "SOLR-39" not in targeted.get(plan[0], []):
                continue
            selector = plan[0]
            parts = selector.split("|")
            # Two observed effective roots were reads through LazyCollectionRef.
            # Other target-linked collection-state roots remain eligible, then
            # the remaining healthy same-reader candidates follow.
            if ("LazyCollectionRef#get:" in selector and
                    parts[0] == "EXISTS_WATCH" and
                    parts[1].startswith("/collections/myalias")):
                family = 0
            elif (parts[1].startswith("/collections/myalias") and
                  parts[1].endswith("/state.json")):
                family = 1
            else:
                family = 2
            ordinal = int(parts[2]) if parts[2].isdigit() else 100000
            # V8 exhausts distinct healthy roots before bounded replays of
            # exact selectors whose fault succeeded but missed this reader.
            replay = (int(selector in seen)
                      if state.get("scheduler_version") in
                      ("solr39_lazy_retry_v8", "solr39_handoff_roots_v9") else 0)
            candidates.append((family, replay, ordinal, index))
        if candidates:
            return queue.pop(min(candidates)[3])
    if number % 3 == 0:
        priority = min(("SOLR-39", "SOLR-10", "SOLR-40"),
                       key=lambda site: state["site_progress"][site]["effective"] /
                       state["site_progress"][site]["goal"])
        targets = state.get("seed_target_sites", {})
        read = next((index for index, plan in enumerate(queue)
                     if len(plan) == 1 and plan[0].startswith("GET_DATA|/aliases.json|") and
                     "AliasesManager#process:" in plan[0] and
                     priority in targets.get(plan[0], [])), None)
        if read is not None:
            return queue.pop(read)
    if (len(state["trials"]) + 1) % 4 == 0:
        root = next((i for i, plan in enumerate(queue) if len(plan) == 1), None)
        if root is not None:
            return queue.pop(root)
    return queue.pop(0)


def migrate_solr10_focus(state: dict) -> None:
    """Record the V10 picker change without changing the queue or trial ledger."""
    if state.get("solr10_focus_v10"):
        if not (CAMPAIGN / "solr10-focus-v10.json").exists():
            raise RuntimeError("V10 picker checkpoint lacks its boundary receipt")
        return
    if (state.get("scheduler_version") != "solr39_handoff_roots_v9" or
            state["inflight"] is not None):
        raise RuntimeError("V10 picker requires a completed V9 trial boundary")
    progress = state["site_progress"]
    if (progress["SOLR-39"]["effective"] < progress["SOLR-39"]["goal"] or
            progress["SOLR-40"]["effective"] < progress["SOLR-40"]["goal"] or
            progress["SOLR-10"]["effective"] >= progress["SOLR-10"]["goal"]):
        raise RuntimeError("V10 picker requires only SOLR-10 to remain open")
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ledger = {"trials": state["trials"], "seen_plans": state["seen_plans"]}
    queue_sha = hashlib.sha256(canonical(state["queue"])).hexdigest()
    ledger_sha = hashlib.sha256(canonical(ledger)).hexdigest()
    targets = state.get("seed_target_sites", {})
    seen = set(state["seen_plans"])
    roots = [plan[0] for plan in state["queue"] if len(plan) == 1 and
             plan[0] not in seen and "SOLR-10" in targets.get(plan[0], [])]
    if not roots:
        raise RuntimeError("No untested healthy SOLR-10 target-linked root")
    before_sha = hashlib.sha256(STATE.read_bytes()).hexdigest()
    receipt = {
        "checkpoint_sha256_before": before_sha,
        "trials_before": len(state["trials"]),
        "queue_sha256_before_and_after": queue_sha,
        "ledger_sha256_before_and_after": ledger_sha,
        "untried_solr10_linked_roots": len(roots),
        "first_scheduled_root": roots[0],
        "scheduler_sha256_before": "ca51bcd7c64fdf8220d14ce80c4a29ec82afaadbab6d85ba1d6dee793598ddce",
        "scheduler_sha256_after": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rule": "alternate untested healthy-trace SOLR-10 linked single faults with the existing multi-fault queue",
    }
    state["solr10_focus_v10"] = {"version": "solr10_target_roots_v10",
                                 "trials_before": len(state["trials"]),
                                 "receipt": str(CAMPAIGN / "solr10-focus-v10.json")}
    if (hashlib.sha256(canonical(state["queue"])).hexdigest() != queue_sha or
            hashlib.sha256(canonical({"trials": state["trials"],
                                     "seen_plans": state["seen_plans"]})).hexdigest() != ledger_sha):
        raise RuntimeError("V10 picker changed the queue or completed trial ledger")
    atomic_json(STATE, state)
    atomic_json(CAMPAIGN / "solr10-focus-v10.json", {
        **receipt,
        "checkpoint_sha256_after": hashlib.sha256(STATE.read_bytes()).hexdigest(),
    })


def migrate_solr10_rank_v10b(state: dict) -> None:
    """Rank already queued target-linked roots using observed per-family yield."""
    receipt_path = CAMPAIGN / "solr10-rank-v10b.json"
    if state.get("solr10_rank_v10b"):
        if not receipt_path.exists():
            raise RuntimeError("V10b picker checkpoint lacks its boundary receipt")
        return
    if (not state.get("solr10_focus_v10") or state["inflight"] is not None or
            len(state["trials"]) < 525):
        raise RuntimeError("V10b picker requires the completed V10 pilot boundary")
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ledger = {"trials": state["trials"], "seen_plans": state["seen_plans"]}
    ledger_sha = hashlib.sha256(canonical(ledger)).hexdigest()
    queue_sha = hashlib.sha256(canonical(state["queue"])).hexdigest()
    targets = state.get("seed_target_sites", {})
    seen = set(state["seen_plans"])
    roots = [plan[0] for plan in state["queue"] if len(plan) == 1 and
             plan[0] not in seen and "SOLR-10" in targets.get(plan[0], [])]
    lazy = [name for name in roots if name.startswith("EXISTS_WATCH|/collections/myalias")
            and "/state.json|" in name and "LazyCollectionRef#get:" in name]
    if not lazy:
        raise RuntimeError("No untried target-linked LazyCollectionRef state roots")
    before_sha = hashlib.sha256(STATE.read_bytes()).hexdigest()
    receipt = {
        "checkpoint_sha256_before": before_sha,
        "trials_before": len(state["trials"]),
        "queue_sha256_before_and_after": queue_sha,
        "ledger_sha256_before_and_after": ledger_sha,
        "solr10_linked_roots": len(roots),
        "lazy_state_roots_ranked_first": len(lazy),
        "first_lazy_root": lazy[0],
        "scheduler_sha256_before": "5a69c1d451a8de66586ab1aa18887a0eefc07dfe135a50ccb33426a72f52c06a",
        "scheduler_sha256_after": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "rule": "use feedback to rank target-linked LazyCollectionRef state roots ahead of lower-yield I/O families; preserve all queued plans",
    }
    state["solr10_rank_v10b"] = {"version": "solr10_ranked_roots_v10b",
                                   "trials_before": len(state["trials"]),
                                   "receipt": str(receipt_path)}
    if (hashlib.sha256(canonical(state["queue"])).hexdigest() != queue_sha or
            hashlib.sha256(canonical({"trials": state["trials"],
                                     "seen_plans": state["seen_plans"]})).hexdigest() != ledger_sha):
        raise RuntimeError("V10b picker changed the queue or completed trial ledger")
    atomic_json(STATE, state)
    atomic_json(receipt_path, {
        **receipt,
        "checkpoint_sha256_after": hashlib.sha256(STATE.read_bytes()).hexdigest(),
    })


def migrate_root_balance(state: dict) -> None:
    """Document the actor-retaining scheduler change without recounting trials."""
    if state.get("scheduler_version") in ("solr39_root_balance_v5",
                                          "solr39_lazy_occurrence_v7",
                                          "solr39_lazy_retry_v8",
                                          "solr39_handoff_roots_v9"):
        return
    if state["inflight"] is not None:
        return  # Finish the already selected plan before changing selection.
    before = hashlib.sha256(STATE.read_bytes()).hexdigest()
    source = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    state["root_balance_migration"] = {
        "trials_before": len(state["trials"]),
        "seen_plans_before": len(state["seen_plans"]),
        "queue_before": len(state["queue"]),
        "checkpoint_sha256_before": before,
        "scheduler_sha256_before": V4_SCHEDULER_SHA256,
        "scheduler_sha256_after": source,
        "reason": "SOLR-39 exact-actor postfault reach occurred only in single-fault roots in the audited first tranche",
        "rule": "alternate target-linked roots and the existing multi-fault queue; do not replay completed plans",
    }
    state["scheduler_version"] = "solr39_root_balance_v5"
    atomic_json(STATE, state)
    atomic_json(CAMPAIGN / "root-balance-migration.json", {
        **state["root_balance_migration"],
        "checkpoint_sha256_after": hashlib.sha256(STATE.read_bytes()).hexdigest(),
    })


def migrate_reader_schedule(state: dict) -> None:
    """Annotate a stopped pilot checkpoint without replaying any old trial."""
    if state.get("scheduler_version") in ("balanced_watch_reads_v4", "solr39_root_balance_v5",
                                          "solr39_lazy_occurrence_v7",
                                          "solr39_lazy_retry_v8",
                                          "solr39_handoff_roots_v9"):
        return
    if state["inflight"] is not None:
        raise RuntimeError("Scheduler migration requires a completed-trial boundary")
    before = hashlib.sha256(STATE.read_bytes()).hexdigest()
    traces = [events(EVIDENCE / name / "events.tsv") for name in HEALTHY]
    state["seed_target_sites"] = seed_target_sites(traces)
    state["scheduler_version"] = "balanced_watch_reads_v4"
    state["scheduler_migration"] = {"trials_before": len(state["trials"]),
                                    "checkpoint_sha256_before": before,
                                    "reason": "Overseer writer faults lost SOLR-39; sample bounded callback reads"}
    atomic_json(STATE, state)
    atomic_json(CAMPAIGN / "scheduler-migration.json", state["scheduler_migration"])


def retryable_reader_plan(plan: list[str], state: dict) -> bool:
    return (len(plan) == 1 and plan[0].startswith("GET_DATA|/aliases.json|") and
            "AliasesManager#process:" in plan[0] and
            "SOLR-39" in state.get("seed_target_sites", {}).get(plan[0], []))


def migrate_reader_retries(state: dict) -> None:
    """Keep bounded role-drift replays without changing earlier trial verdicts."""
    if state.get("reader_retry_version") == "v1_max_two_extra":
        return
    if state["inflight"] is not None:
        raise RuntimeError("Reader retry migration requires a completed-trial boundary")
    before = hashlib.sha256(STATE.read_bytes()).hexdigest()
    state["reader_retry_version"] = "v1_max_two_extra"
    state["reader_retry_counts"] = {}
    queued = {";".join(plan) for plan in state["queue"]}
    backfilled = []
    for trial in state["trials"]:
        plan = trial["plan"]
        key = ";".join(plan)
        if (retryable_reader_plan(plan, state) and trial["strict"] and
                trial["target_after_fault_any_actor"]["SOLR-39"] and
                not trial["target_after_fault"]["SOLR-39"] and key not in queued):
            state["reader_retry_counts"][key] = 1
            state["queue"].insert(min(8, len(state["queue"])), plan)
            queued.add(key)
            backfilled.append(trial["number"])
    state["reader_retry_migration"] = {
        "trials_before": len(state["trials"]), "checkpoint_sha256_before": before,
        "backfilled_trial_numbers": backfilled,
        "max_extra_runs_per_plan": 2,
        "reason": "Revisit matched watch-read faults when the target executes on a different live reader",
    }
    atomic_json(STATE, state)
    atomic_json(CAMPAIGN / "reader-retry-migration.json", state["reader_retry_migration"])


def migrate_lazy_occurrences(state: dict) -> None:
    """Add untried healthy same-reader watch occurrences; retain the V5 queue."""
    if state.get("scheduler_version") in ("solr39_lazy_occurrence_v7",
                                          "solr39_lazy_retry_v8",
                                          "solr39_handoff_roots_v9"):
        return
    if state.get("scheduler_version") != "solr39_root_balance_v5" or state["inflight"] is not None:
        raise RuntimeError("Lazy occurrence migration requires a stopped V5 trial boundary")
    before_state_sha = hashlib.sha256(STATE.read_bytes()).hexdigest()
    before_queue = list(state["queue"])
    ledger = {"trials": state["trials"], "seen_plans": state["seen_plans"]}
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ledger_sha = hashlib.sha256(canonical(ledger)).hexdigest()
    traces = [events(EVIDENCE / name / "events.tsv") for name in HEALTHY]
    roots = untested_lazy_roots(state, traces)
    if not roots:
        raise RuntimeError("No untested healthy same-reader LazyCollectionRef roots")
    new_plans = [[name] for name in roots]
    state["queue"].extend(new_plans)
    state["scheduler_version"] = "solr39_lazy_occurrence_v7"
    source_sha = {name: hashlib.sha256((EVIDENCE / name / "events.tsv").read_bytes()).hexdigest()
                  for name in HEALTHY}
    state["lazy_root_expansion"] = {
        "trials_before": len(state["trials"]),
        "effective_before": {site: state["site_progress"][site]["effective"] for site in CASES},
        "state_sha256_before": before_state_sha,
        "ledger_sha256_before_and_after": ledger_sha,
        "queue_sha256_before": hashlib.sha256(canonical(before_queue)).hexdigest(),
        "queue_sha256_after": hashlib.sha256(canonical(state["queue"])).hexdigest(),
        "queue_length_before": len(before_queue), "queue_length_after": len(state["queue"]),
        "new_root_count": len(new_plans), "new_roots": roots,
        "healthy_trace_sha256": source_sha,
        "scheduler_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    if hashlib.sha256(canonical({"trials": state["trials"],
                                 "seen_plans": state["seen_plans"]})).hexdigest() != ledger_sha:
        raise RuntimeError("Trial ledger changed during root expansion")
    atomic_json(STATE, state)
    receipt = dict(state["lazy_root_expansion"])
    receipt["state_sha256_after"] = hashlib.sha256(STATE.read_bytes()).hexdigest()
    atomic_json(CAMPAIGN / "lazy-root-expansion-v7.json", receipt)


def target_linked_lazy_root(plan: list[str], state: dict) -> bool:
    """A healthy-observed state watch on the same actor as SOLR-39."""
    if len(plan) != 1:
        return False
    selector = plan[0]
    parts = selector.split("|")
    return (len(parts) >= 5 and parts[0] == "EXISTS_WATCH" and
            parts[1].startswith("/collections/myalias__TRA__") and
            parts[1].endswith("/state.json") and
            "LazyCollectionRef#get:" in parts[3] and
            parts[4].startswith("actor=jetty:node") and
            "SOLR-39" in state.get("seed_target_sites", {}).get(selector, []))


def migrate_lazy_retries(state: dict) -> None:
    """Backfill bounded replays only for exactly injected, ineffective roots."""
    receipt_path = CAMPAIGN / "lazy-retry-migration-v8.json"
    if state.get("scheduler_version") in ("solr39_lazy_retry_v8",
                                          "solr39_handoff_roots_v9"):
        if not receipt_path.exists():
            raise RuntimeError("V8 checkpoint lacks immutable migration receipt")
        return
    if state.get("scheduler_version") != "solr39_lazy_occurrence_v7" or state["inflight"] is not None:
        raise RuntimeError("Lazy retry migration requires a stopped V7 trial boundary")
    before_state_sha = hashlib.sha256(STATE.read_bytes()).hexdigest()
    before_queue = list(state["queue"])
    ledger = {"trials": state["trials"], "seen_plans": state["seen_plans"]}
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ledger_sha = hashlib.sha256(canonical(ledger)).hexdigest()
    grouped = defaultdict(list)
    for trial in state["trials"]:
        if target_linked_lazy_root(trial["plan"], state):
            grouped[trial["plan"][0]].append(trial)
    queued = {";".join(plan) for plan in before_queue}
    retries = []
    counts = {}
    excluded = Counter()
    for selector, runs in sorted(grouped.items()):
        if any(trial["strict"] and trial["target_after_fault"]["SOLR-39"]
               for trial in runs):
            excluded["already_effective"] += 1
            continue
        latest = runs[-1]
        if not latest["strict"]:
            excluded["unmatched_injection"] += 1
            continue
        if len(runs) >= 3:
            excluded["two_extra_attempts_used"] += 1
            continue
        if selector in queued:
            excluded["already_queued"] += 1
            continue
        # Counts mean extra runs *scheduled*. The just-enqueued attempt is
        # one of at most two after the original run.
        counts[selector] = len(runs)
        state["queue"].append([selector])
        queued.add(selector)
        retries.append({"selector": selector,
                        "previous_trial_numbers": [trial["number"] for trial in runs],
                        "last_target_after_fault_any_actor":
                            latest["target_after_fault_any_actor"]["SOLR-39"],
                        "scheduled_extra_run": counts[selector]})
    if not retries:
        raise RuntimeError("No strictly injected, ineffective healthy Lazy roots to retry")
    if state["queue"][:len(before_queue)] != before_queue:
        raise RuntimeError("V8 migration changed an existing queued plan")
    if hashlib.sha256(canonical({"trials": state["trials"],
                                 "seen_plans": state["seen_plans"]})).hexdigest() != ledger_sha:
        raise RuntimeError("V8 migration changed the completed trial ledger")
    state["lazy_retry_counts"] = counts
    state["lazy_retry_version"] = "v8_max_two_extra_strict_only"
    state["scheduler_version"] = "solr39_lazy_retry_v8"
    receipt = {
        "trials_before": len(state["trials"]),
        "effective_before": {site: state["site_progress"][site]["effective"] for site in CASES},
        "state_sha256_before": before_state_sha,
        "ledger_sha256_before_and_after": ledger_sha,
        "queue_sha256_before": hashlib.sha256(canonical(before_queue)).hexdigest(),
        "queue_sha256_after": hashlib.sha256(canonical(state["queue"])).hexdigest(),
        "queue_length_before": len(before_queue),
        "queue_length_after": len(state["queue"]),
        "queue_prefix_preserved": True,
        "old_scheduler_sha256": V7_SCHEDULER_SHA256,
        "new_scheduler_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "max_extra_runs_per_selector": 2,
        "exclusions": dict(excluded),
        "retries": retries,
    }
    state["lazy_retry_migration"] = {key: value for key, value in receipt.items()
                                     if key != "retries"}
    atomic_json(STATE, state)
    receipt["state_sha256_after"] = hashlib.sha256(STATE.read_bytes()).hexdigest()
    atomic_json(receipt_path, receipt)


def schedule_lazy_retry(state: dict, trial: dict) -> bool:
    """Retry an exact root only when SOLR-39 missed this live reader."""
    if (state.get("scheduler_version") not in
            ("solr39_lazy_retry_v8", "solr39_handoff_roots_v9") or
            state["site_progress"]["SOLR-39"]["effective"] >=
            state["site_progress"]["SOLR-39"]["goal"] or
            not target_linked_lazy_root(trial["plan"], state) or
            not trial["strict"] or trial["target_after_fault"]["SOLR-39"]):
        return False
    selector = trial["plan"][0]
    if any(old["plan"] == trial["plan"] and old["strict"] and
           old["target_after_fault"]["SOLR-39"] for old in state["trials"]):
        return False
    counts = state["lazy_retry_counts"]
    if counts.get(selector, 0) >= 2 or any(plan == trial["plan"] for plan in state["queue"]):
        return False
    counts[selector] = counts.get(selector, 0) + 1
    state["queue"].append(list(trial["plan"]))
    return True


def migrate_handoff_healthy_roots(state: dict) -> None:
    """Append only new same-reader roots from the existing original no-fault JUnit."""
    receipt_path = CAMPAIGN / "handoff-healthy-roots-v9.json"
    if state.get("scheduler_version") == "solr39_handoff_roots_v9":
        if not receipt_path.exists():
            raise RuntimeError("V9 checkpoint lacks immutable migration receipt")
        return
    if (state.get("scheduler_version") != "solr39_lazy_retry_v8" or
            state["inflight"] is not None):
        raise RuntimeError("Handoff healthy root migration requires a stopped V8 trial boundary")
    source = EVIDENCE / HANDOFF_HEALTHY
    manifest = json.loads((source / "manifest.json").read_text())
    baseline = json.loads((EVIDENCE / HEALTHY[0] / "manifest.json").read_text())
    build_sha = hashlib.sha256((CASE / "build-receipt.json").read_bytes()).hexdigest()
    identity_fields = ("build_receipt_sha256", "source_commit",
                       "original_test_class_sha256", "actor_probe_class_sha256")
    if (any(manifest.get(key) != baseline.get(key) for key in identity_fields) or
            manifest.get("build_receipt_sha256") != build_sha or
            manifest.get("original_classes") is not False or
            manifest.get("faults") != "" or manifest.get("exit_code") != 0):
        raise RuntimeError("Handoff no-fault JUnit differs from the campaign binary")
    trace = events(source / "events.tsv")
    before_queue = list(state["queue"])
    ledger = {"trials": state["trials"], "seen_plans": state["seen_plans"]}
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ledger_sha = hashlib.sha256(canonical(ledger)).hexdigest()
    before_state_sha = hashlib.sha256(STATE.read_bytes()).hexdigest()
    roots = untested_lazy_roots(state, [trace], names=(HANDOFF_HEALTHY,))
    if not roots:
        raise RuntimeError("No untested same-reader handoff healthy roots")
    target_sites = seed_target_sites([trace])
    for selector_name in roots:
        if "SOLR-39" not in target_sites.get(selector_name, []):
            raise RuntimeError("Root lost its verified same-reader SOLR-39 target")
        sites = set(state["seed_target_sites"].get(selector_name, []))
        state["seed_target_sites"][selector_name] = sorted(sites | set(target_sites[selector_name]))
        state["queue"].append([selector_name])
    if (state["queue"][:len(before_queue)] != before_queue or
            hashlib.sha256(canonical({"trials": state["trials"],
                                      "seen_plans": state["seen_plans"]})).hexdigest() != ledger_sha):
        raise RuntimeError("V9 migration changed the old queue prefix or trial ledger")
    state["scheduler_version"] = "solr39_handoff_roots_v9"
    receipt = {
        "trials_before": len(state["trials"]),
        "effective_before": {site: state["site_progress"][site]["effective"] for site in CASES},
        "state_sha256_before": before_state_sha,
        "ledger_sha256_before_and_after": ledger_sha,
        "queue_sha256_before": hashlib.sha256(canonical(before_queue)).hexdigest(),
        "queue_sha256_after": hashlib.sha256(canonical(state["queue"])).hexdigest(),
        "queue_length_before": len(before_queue),
        "queue_length_after": len(state["queue"]),
        "queue_prefix_preserved": True,
        "source_trace": str((source / "events.tsv").relative_to(CASE)),
        "source_trace_sha256": hashlib.sha256((source / "events.tsv").read_bytes()).hexdigest(),
        "source_manifest_sha256": hashlib.sha256((source / "manifest.json").read_bytes()).hexdigest(),
        "source_binary_identity": {key: manifest[key] for key in identity_fields},
        "source_faults": manifest["faults"],
        "source_exit_code": manifest["exit_code"],
        "old_scheduler_sha256": V8_SCHEDULER_SHA256,
        "new_scheduler_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "new_root_count": len(roots), "new_roots": roots,
    }
    state["handoff_healthy_root_expansion"] = {key: value for key, value in receipt.items()
                                                if key != "new_roots"}
    atomic_json(STATE, state)
    receipt["state_sha256_after"] = hashlib.sha256(STATE.read_bytes()).hexdigest()
    atomic_json(receipt_path, receipt)


def schedule_reader_retry(state: dict, trial: dict) -> bool:
    """At most two extra runs of a strict reader fault with postfault actor drift."""
    plan = trial["plan"]
    if not (retryable_reader_plan(plan, state) and trial["strict"] and
            trial["target_after_fault_any_actor"]["SOLR-39"] and
            not trial["target_after_fault"]["SOLR-39"]):
        return False
    key = ";".join(plan)
    counts = state["reader_retry_counts"]
    if counts.get(key, 0) >= 2 or any(";".join(item) == key for item in state["queue"]):
        return False
    counts[key] = counts.get(key, 0) + 1
    state["queue"].insert(min(8, len(state["queue"])), list(plan))
    return True


def mutate(state: dict, plan: list[str], trace: list[dict], trial: dict) -> None:
    if (len(plan) >= state["budget"]["max_faults"] or not trial["strict"] or
            not any(trial["target_after_fault"].values())):
        return
    final = max(e["seq"] for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS")
    faults = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
    targets = [e for e in trace if e["kind"] == "TARGET_CHECK" and e["seq"] > final
               and any(actor_relation(fault, e) for fault in faults)]
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
        future = {e["parts"][1] for e in targets if e["seq"] > event["seq"] and
                  actor_relation(event, e)}
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


def run(max_new_trials: int | None = None) -> None:
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    active_build = hashlib.sha256((CASE / "build-receipt.json").read_bytes()).hexdigest()
    if state.get("build_receipt_sha256") != active_build:
        raise RuntimeError("Checkpoint build differs from current actor hooks")
    migrate_reader_schedule(state)
    migrate_reader_retries(state)
    migrate_root_balance(state)
    if (len(state["trials"]) >= 189 and
            (CAMPAIGN / "node1-handoff-calibration/handoff-calibration.json").exists()):
        migrate_lazy_occurrences(state)
        migrate_lazy_retries(state)
        migrate_handoff_healthy_roots(state)
    if (state.get("solr10_focus_v10") or
            (state["site_progress"]["SOLR-39"]["effective"] >=
             state["site_progress"]["SOLR-39"]["goal"] and
             state["site_progress"]["SOLR-40"]["effective"] >=
             state["site_progress"]["SOLR-40"]["goal"] and
             state["site_progress"]["SOLR-10"]["effective"] <
             state["site_progress"]["SOLR-10"]["goal"])):
        migrate_solr10_focus(state)
    if state.get("solr10_focus_v10") and len(state["trials"]) >= 525:
        migrate_solr10_rank_v10b(state)
    starting_trials = len(state["trials"])
    reclaim_completed_scratch(state)
    update_stop_reasons(state)
    write_checkpoints(state)
    while not done(state) and (max_new_trials is None or
                               len(state["trials"]) - starting_trials < max_new_trials):
        if shutil.disk_usage(CASE).free < 8 * 1024 ** 3:
            print(json.dumps({"paused_at_boundary": "node_disk_below_8_gib",
                              "completed_trials": len(state["trials"])}), flush=True)
            break
        # node1 runs several independent campaigns. Start this embedded JUnit
        # only while fewer than five JVMs already exist on the host. Wait
        # before selecting a plan, so a resource pause preserves a clean
        # checkpoint boundary and never consumes a fault trial.
        waiting = False
        while True:
            java_pids = []
            for proc in Path("/proc").glob("[0-9]*/comm"):
                try:
                    if proc.read_text().strip() == "java":
                        java_pids.append(int(proc.parent.name))
                except OSError:
                    continue
            if len(java_pids) < 5:
                break
            if shutil.disk_usage(CASE).free < 8 * 1024 ** 3:
                print(json.dumps({"paused_at_boundary": "node_disk_below_8_gib",
                                  "completed_trials": len(state["trials"])}), flush=True)
                return
            if not waiting:
                print(json.dumps({"waiting_for_node1_jvm_slot": True,
                                  "java_pids": sorted(java_pids),
                                  "completed_trials": len(state["trials"])}), flush=True)
                waiting = True
            time.sleep(5)
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
        final_fault = max((e["seq"] for e in applied), default=-1)
        raw_after, raw_exception = target_after_any_actor(trace, final_fault)
        after, exception = target_after(trace, final_fault)
        relations = target_relations(trace, final_fault)
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
            "target_checks": target_counts(trace),
            "target_after_fault_any_actor": raw_after,
            "target_exception_any_actor": raw_exception,
            "target_lost_runtime_relation": {site: strict and raw_after[site] and not after[site]
                                             for site in CASES},
            "fault_actors": [list(runtime_actor(e)) for e in applied],
            "target_after_fault": after, "target_exception": exception,
            "target_relations": relations,
            "new_coverage": novelty_cov,
            "new_methods": novelty_methods, "new_branches": novelty_branches,
            "new_io": novelty_io, "new_io_families": novelty_families,
            "elapsed_seconds": round(time.time() - started, 3),
            "evidence": str(output.relative_to(CASE)),
            "scratch_retained": bool(strict and any(raw_exception.values())),
        }
        prior_lazy_runs = ([old["number"] for old in state["trials"] if old["plan"] == plan]
                           if target_linked_lazy_root(plan, state) else [])
        trial["lazy_retry_of_trial_numbers"] = prior_lazy_runs
        trial["lazy_retry_attempt_index"] = len(prior_lazy_runs)
        update_progress(state, trial)
        mutate(state, plan, trace, trial)
        trial["reader_role_retry_scheduled"] = schedule_reader_retry(state, trial)
        trial["lazy_root_retry_scheduled"] = schedule_lazy_retry(state, trial)
        state["trials"].append(trial)
        state["seen_plans"].append(";".join(plan))
        state["elapsed_seconds"] += trial["elapsed_seconds"]
        state["inflight"] = None
        update_stop_reasons(state)
        atomic_json(output / "trial.json", trial)
        atomic_json(STATE, state)
        migrate_root_balance(state)
        write_checkpoints(state)
        if not trial["scratch_retained"]:
            scratch = output / "scratch"
            if scratch.exists():
                shutil.rmtree(scratch)
        print(json.dumps({"trial": number, "strict": strict, "after": after,
                          "exception": exception, "valid": {site: valid_count(state, site)
                                                          for site in CASES},
                          "goals": {site: state["site_progress"][site]["goal"]
                                    for site in CASES},
                          "stop_reasons": {site: state["site_progress"][site]["stop_reason"]
                                           for site in CASES}}), flush=True)
    print(json.dumps({"pilot_boundary": max_new_trials is not None,
                      "completed_new_trials": len(state["trials"]) - starting_trials,
                      "inflight": state["inflight"],
                      "effective": {site: valid_count(state, site) for site in CASES}}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new-trials", type=int)
    args = parser.parse_args()
    if args.max_new_trials is not None and args.max_new_trials < 1:
        parser.error("--max-new-trials must be positive")
    run(args.max_new_trials)
