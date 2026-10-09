#!/usr/bin/env python3
"""Independent graph-free I/O fault campaign for SOLR-06."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import subprocess
import time

from feedback import (atomic_json, events, io_identity, io_behavior_key,
                      sequence_applied_in_order)


WORK = Path(__file__).resolve().parents[1]
ROOT = WORK.parents[1]
CAMPAIGN = WORK / "evidence/campaign"
HEALTHY = WORK / "evidence/healthy-instrumented"
STATE = CAMPAIGN / "state.json"
CASES = ("SOLR-06",)
SITES = {
    "SOLR-06": ("solr/core/src/java/org/apache/solr/cloud/ZkController.java", 1315,
                "ZkController.register",
                "assert !(isLeader && replica.getType() == Type.PULL)"),
}
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
DIST = "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist"
BASE_TRIALS, BASE_FAULTS = 80, 8
EXTENDED_TRIALS, EXTENDED_FAULTS = 128, 10


def relevant(identity: tuple[str, str]) -> bool:
    _, path = identity
    return (path == "/collections" or
            path.startswith("/collections/pull_replica_test_create_delete") or
            path.startswith("/overseer") or path == "/live_nodes")


def rank(identity: tuple[str, str]) -> int:
    operation, path = identity
    if (operation == "GET_DATA" and
            "/leaders/" in path and path.endswith("/leader")):
        return 0
    if path.endswith("/state.json"):
        return 2 if operation in ("GET_DATA", "EXISTS_WATCH") else 3
    if "/terms/" in path:
        return 4
    if "/leaders/" in path or "/leader_elect/" in path:
        return 5
    if path.startswith("/collections/pull_replica_test_create_delete"):
        return 4
    if path == "/live_nodes":
        return 5
    if path.startswith("/overseer/collection-queue-work"):
        return 6
    if path.startswith("/overseer"):
        return 7
    return 8


def family(identity: tuple[str, str]) -> str:
    operation, path = identity
    if path.endswith("/state.json"):
        return operation + ":collection-state"
    if "/terms/" in path or "/leaders/" in path or "/leader_elect/" in path:
        return operation + ":collection-control"
    if path.startswith("/collections/pull_replica_test_create_delete"):
        return operation + ":collection-other"
    if path.startswith("/overseer"):
        return operation + ":overseer"
    return operation + ":other"


def coverage(directory: Path) -> set[str]:
    execution = directory / "jacoco.exec"
    if not execution.exists():
        return set()
    cp = str(WORK / "classes") + ":" + str(WORK / "lib/jacoco-core.jar")
    command = [JAVA, "-cp", cp, "baseline.solr06.CoverageProbes",
               str(execution), DIST]
    return set(subprocess.check_output(command, text=True).splitlines())


def target_counts(trace: list[dict]) -> dict[str, int]:
    return {cid: sum(event["kind"] == "TARGET_CHECK" and
                     len(event["parts"]) >= 2 and event["parts"][1] == cid
                     for event in trace) for cid in CASES}


def after_target(trace: list[dict], last_fault: int) -> tuple[dict, dict]:
    after = {cid: False for cid in CASES}
    exception = {cid: False for cid in CASES}
    if last_fault < 0:
        return after, exception
    fault_event = next((event for event in trace
                        if event["seq"] == last_fault and
                        event["kind"] == "IO_APPLIED_CONNECTION_LOSS"), None)
    if fault_event is None:
        return after, exception
    path = fault_event["parts"][1]
    shard_match = re.search(r"/(shard\d+)(?:/|$)", path)
    required_shard = shard_match.group(1) if shard_match else None
    required_collection = "pull_replica_test_create_delete"
    for event in trace:
        if event["seq"] <= last_fault:
            continue
        parts = event["parts"]
        if event["kind"] == "TARGET_CHECK" and len(parts) >= 6 and parts[1] in after:
            if (parts[2] == required_collection and parts[5] == "PULL"
                    and (required_shard is None or parts[3] == required_shard)):
                after[parts[1]] = True
        elif event["kind"] == "TARGET_EXCEPTION" and len(parts) >= 8 and parts[0] in exception:
            if (parts[1] == required_collection and parts[4] == "PULL"
                    and (required_shard is None or parts[2] == required_shard)
                    and parts[7] == "java.lang.AssertionError"):
                exception[parts[0]] = True
    return after, exception


def initial_queue(trace: list[dict]) -> list[list[str]]:
    target_events = [e for e in trace if e["kind"] == "TARGET_CHECK"]
    target_seq = [e["seq"] for e in target_events]
    if not target_seq:
        raise RuntimeError("No selected target reached in healthy test")
    last_target = max(target_seq)
    occurrences = defaultdict(list)
    global_count = Counter()
    for event in trace:
        identity = io_identity(event)
        if identity is None:
            continue
        global_count[identity] += 1
        if relevant(identity) and event["seq"] < last_target:
            occurrences[identity].append((global_count[identity], event["seq"],
                                          event["parts"][2]))
    queue = []
    for identity, hits in occurrences.items():
        indices = {0, len(hits) // 4, len(hits) // 2,
                   3 * len(hits) // 4, len(hits) - 1}
        for index in indices:
            ordinal, seq, caller = hits[index]
            operation, path = identity
            future_cases = {e["parts"][1] for e in target_events
                            if e["seq"] > seq and len(e["parts"]) >= 2}
            queue.append((-len(future_cases), rank(identity), -seq,
                          [f"{operation}|{path}|{ordinal}|{caller}"]))
    queue.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return [plan for _, _, _, plan in queue]


def plan_key(plan: list[str]) -> str:
    return ";".join(plan)


def select_next_plan(state: dict) -> list[str]:
    """Interleave feedback descendants with different observed healthy I/O sites."""
    queue = state["queue"]
    # Direct leader reads immediately precede the selected assertion in the
    # healthy trace. Keep them represented even when state.json descendants
    # repeatedly prepend themselves to the feedback queue.
    if (len(state["trials"]) + 1) % 3 == 1:
        leader_singles = []
        tried_shards = Counter()
        for trial in state["trials"]:
            first = trial["plan"][0]
            if "ZkController#getLeaderProps" in first and "/leaders/" in first:
                shard = re.search(r"/leaders/(shard\d+)/", first)
                if shard:
                    tried_shards[shard.group(1)] += 1
        for index, plan in enumerate(queue):
            if len(plan) != 1 or "ZkController#getLeaderProps" not in plan[0]:
                continue
            fields = plan[0].split("|")
            shard = re.search(r"/leaders/(shard\d+)/", fields[1])
            if shard is None:
                continue
            leader_singles.append(((tried_shards[shard.group(1)],
                                    abs(int(fields[2]) - 5), index), index))
        if leader_singles:
            return queue.pop(min(leader_singles)[1])
    if (len(state["trials"]) + 1) % 4 or not any(len(p) == 1 for p in queue):
        return queue.pop(0)

    retained = {cid: sum(t["all_faults_applied"] and
                         t["target_after_fault"][cid] for t in state["trials"])
                for cid in CASES}
    need = min(CASES, key=lambda cid: (retained[cid], CASES.index(cid)))
    healthy = events(HEALTHY / "events.tsv")
    last_target = max(e["seq"] for e in healthy
                      if e["kind"] == "TARGET_CHECK" and
                      len(e["parts"]) >= 2 and e["parts"][1] == need)
    counts = Counter()
    ordinal_seq = {}
    for event in healthy:
        identity = io_identity(event)
        if identity is not None:
            counts[identity] += 1
            ordinal_seq[(identity, counts[identity])] = event["seq"]

    tried = Counter()
    tried_families = Counter()
    for trial in state["trials"]:
        operation, path = trial["plan"][0].split("|", 2)[:2]
        identity = operation, path
        tried[identity] += 1
        tried_families[family(identity)] += 1
    candidates = []
    for index, plan in enumerate(queue):
        if len(plan) != 1:
            continue
        operation, path, ordinal = plan[0].split("|", 3)[:3]
        identity = operation, path
        seq = ordinal_seq.get((identity, int(ordinal)))
        if seq is None or seq >= last_target:
            continue
        distance = last_target - seq
        # A few hundred trace events leaves room for an I/O failure to be
        # handled before the selected check, while sampling distinct sites.
        score = (tried[identity], tried_families[family(identity)],
                 rank(identity), abs(distance - 300), index)
        candidates.append((score, index))
    if not candidates:
        return queue.pop(0)
    _, index = min(candidates)
    return queue.pop(index)


def initialize() -> dict:
    manifest = json.loads((HEALTHY / "manifest.json").read_text())
    trace = events(HEALTHY / "events.tsv")
    if manifest["exit_code"] != 0 or not trace:
        raise RuntimeError("The original, instrumented cluster JUnit must pass")
    counts = target_counts(trace)
    if any(count == 0 for count in counts.values()):
        raise RuntimeError(f"Healthy test missed a selected check: {counts}")
    base_coverage = coverage(HEALTHY)
    base_io = {identity for event in trace
               if (identity := io_behavior_key(event)) is not None}
    state = {
        "case_ids": CASES, "started_at": time.time(), "elapsed_seconds": 0.0,
        "budget": {"max_trials": BASE_TRIALS, "max_faults": BASE_FAULTS},
        "healthy_target_checks": counts,
        "healthy_coverage": sorted(base_coverage), "healthy_io": sorted(base_io),
        "seen_coverage": {cid: sorted(base_coverage) for cid in CASES},
        "seen_io": {cid: sorted(base_io) for cid in CASES},
        "queue": initial_queue(trace), "seen_plans": [], "trials": [],
    }
    atomic_json(STATE, state)
    write_results(state)
    return state


def write_results(state: dict) -> None:
    trials = state["trials"]
    budget_done = (len(trials) >= state["budget"]["max_trials"] or
                   not state["queue"])
    base_cov = set(state["healthy_coverage"])
    base_io = set(state["healthy_io"])
    strict = sum(t["all_faults_applied"] for t in trials)
    for cid in CASES:
        retained = sum(t["all_faults_applied"] and t["target_after_fault"][cid]
                       for t in trials)
        candidates = sum(t["all_faults_applied"] and
                         t["target_after_fault"][cid] and
                         t["target_exception"][cid] for t in trials)
        previous = ROOT / cid / "result.json"
        legacy = json.loads(previous.read_text()).get("legacy_evidence") if previous.exists() else None
        result = {
            "case_id": cid, "system": "Solr 8.11.4",
            "source_file": SITES[cid][0], "source_line": SITES[cid][1],
            "function": SITES[cid][2], "check_code": SITES[cid][3],
            "cluster_test": "TestPullReplica.testCreateDelete",
            "status": "pending_result_review" if budget_done else "running",
            "target_reached": True,
            "healthy_target_checks": state["healthy_target_checks"][cid],
            "fault_trials": len(trials), "strict_injections": strict,
            "target_after_fault": retained,
            "target_exception_candidates": candidates,
            "coverage_gain": len(set(state["seen_coverage"][cid]) - base_cov),
            "new_io_identities": len(set(state["seen_io"][cid]) - base_io),
            "elapsed_seconds": round(state["elapsed_seconds"], 3),
            "campaign_workspace": "cases/SOLR-06/independent",
            "budget": state["budget"],
            "bug_mark": "candidate_needs_source_review" if candidates else "none",
            "evidence": str(STATE.relative_to(ROOT.parents[2])),
            "methodology": "independent_graph_free_coverage_io_exception",
            "legacy_evidence": legacy,
        }
        output = ROOT / cid / "result.json"
        atomic_json(output, result)


def mutate(state: dict, plan: list[str], trace: list[dict], trial: dict) -> None:
    # A timed-out JVM has no complete JaCoCo feedback. Repeatedly extending
    # that same non-novel recovery path consumes the per-check budget without
    # evidence that it approaches the selected guard.
    if (trial["junit_exit"] == 124 and
            not any(trial["new_coverage"].values()) and
            not any(trial["new_io"].values())):
        return
    if (len(plan) >= state["budget"]["max_faults"] or
            not trial["all_faults_applied"] or
            not any(trial["target_after_fault"].values())):
        return
    last = max(e["seq"] for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS")
    next_targets = [e for e in trace if e["kind"] == "TARGET_CHECK"
                    and e["seq"] > last]
    if not next_targets:
        return
    last_target = max(e["seq"] for e in next_targets)
    global_count, relative_count = Counter(), Counter()
    candidates = []
    prior = {(p.split("|", 2)[0], p.split("|", 2)[1]) for p in plan}
    for event in trace:
        identity = io_identity(event)
        if identity is None:
            continue
        global_count[identity] += 1
        if event["seq"] > last:
            relative_count[identity] += 1
        if not (last + 3 < event["seq"] < last_target - 3 and relevant(identity)):
            continue
        future_cases = {e["parts"][1] for e in next_targets
                        if e["seq"] > event["seq"] and len(e["parts"]) >= 2}
        if not future_cases:
            continue
        operation, path = identity
        caller = event["parts"][2]
        selector = (f"{operation}|{path}|@{relative_count[identity]}|{caller}|"
                    f"after=F{len(plan)-1}|seed_global={global_count[identity]}")
        penalty = 2 if identity in prior else 0
        candidates.append((-len(future_cases), rank(identity) + penalty,
                           event["seq"], plan + [selector]))
    candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    novel = any(trial["new_coverage"].values()) or any(trial["new_io"].values())
    limit = 3 if novel or len(plan) == 1 else 1
    known = set(state["seen_plans"]) | {plan_key(p) for p in state["queue"]}
    picked_families = set()
    children = []
    for _, _, _, child in candidates:
        operation, path = child[-1].split("|", 2)[:2]
        group = family((operation, path))
        key = plan_key(child)
        if group in picked_families or key in known:
            continue
        picked_families.add(group)
        known.add(key)
        children.append(child)
        if len(children) >= limit:
            break
    state["queue"] = children + state["queue"]


def run_campaign() -> None:
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    while len(state["trials"]) < state["budget"]["max_trials"] and state["queue"]:
        plan = select_next_plan(state)
        key = plan_key(plan)
        if key in state["seen_plans"]:
            continue
        state["seen_plans"].append(key)
        number = len(state["trials"]) + 1
        output = CAMPAIGN / f"trial-{number:03d}"
        started = time.time()
        command = ["/usr/bin/python3", str(WORK / "probe/run.py"), str(output),
                   "--coverage", "--faults", key,
                   "--timeout", "240"]
        subprocess.run(command, stdout=subprocess.DEVNULL,
                       stderr=subprocess.STDOUT, check=False)
        manifest = json.loads((output / "manifest.json").read_text())
        trace = events(output / "events.tsv")
        applied = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
        strict = sequence_applied_in_order(plan, applied, matched, trace)
        last = max((e["seq"] for e in applied), default=-1)
        target_after, exception = after_target(trace, last)
        current_cov = coverage(output) if strict and any(target_after.values()) else set()
        current_io = {identity for e in trace
                      if (identity := io_behavior_key(e)) is not None}
        novelty_cov, novelty_io = {}, {}
        for cid in CASES:
            eligible = strict and target_after[cid]
            old_cov = set(state["seen_coverage"][cid])
            old_io = set(state["seen_io"][cid])
            novelty_cov[cid] = len(current_cov - old_cov) if eligible else 0
            novelty_io[cid] = len(current_io - old_io) if eligible else 0
            if eligible:
                state["seen_coverage"][cid] = sorted(old_cov | current_cov)
                state["seen_io"][cid] = sorted(old_io | current_io)
        trial = {
            "number": number, "plan": plan,
            "elapsed_seconds": round(time.time() - started, 3),
            "junit_exit": manifest["exit_code"],
            "faults_matched": len(matched), "faults_applied": len(applied),
            "all_faults_applied": strict,
            "target_checks": target_counts(trace),
            "target_after_fault": target_after, "target_exception": exception,
            "new_coverage": novelty_cov, "new_io": novelty_io,
            "evidence": str(output.relative_to(WORK)),
        }
        state["trials"].append(trial)
        state["elapsed_seconds"] += trial["elapsed_seconds"]
        mutate(state, plan, trace, trial)
        atomic_json(output / "trial.json", trial)
        atomic_json(STATE, state)
        write_results(state)
        print(f"SOLR-06 {number}/{state['budget']['max_trials']} "
              f"applied={len(applied)}/{len(plan)} strict={strict} "
              f"target_after={target_after} exception={exception} "
              f"coverage+={novelty_cov} io+={novelty_io} "
              f"elapsed={trial['elapsed_seconds']}", flush=True)
        if len(state["trials"]) == BASE_TRIALS:
            recent = state["trials"][-8:]
            if any(t["all_faults_applied"] and
                   any(t["target_after_fault"].values()) and
                   (any(t["new_coverage"].values()) or any(t["new_io"].values()))
                   for t in recent):
                state["budget"] = {"max_trials": EXTENDED_TRIALS,
                                   "max_faults": EXTENDED_FAULTS}
                state["extension_reason"] = (
                    "Production probe or stable callsite-operation-resource I/O "
                    "novelty in strict, target-retaining trials 73-80")
                atomic_json(STATE, state)
                write_results(state)
    state["finished_at"] = time.time()
    atomic_json(STATE, state)
    write_results(state)


if __name__ == "__main__":
    run_campaign()
