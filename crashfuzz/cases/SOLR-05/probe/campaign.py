#!/usr/bin/env python3
"""Graph-free I/O-exception and coverage-guided campaign for SOLR-05."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import time


CASE = Path(__file__).resolve().parents[1]
EVIDENCE = CASE / "evidence"
CAMPAIGN = EVIDENCE / "campaign"
HEALTHY = EVIDENCE / "healthy-instrumented"
HEALTHY_CALLSITE = EVIDENCE / "healthy-callsite"
STATE = CAMPAIGN / "state.json"
RESULT = CASE / "result.json"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
RUN = CASE / "probe/run.py"
MAX_TRIALS = 64
MAX_FAULTS = 6


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def events(path: Path) -> list[dict]:
    output = []
    if not path.exists():
        return output
    for line in path.open():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 4:
            continue
        output.append({"seq": int(parts[0]), "kind": parts[2], "parts": parts[3:]})
    return output


def io_identity(event: dict) -> tuple[str, str] | None:
    if event["kind"] != "IO_OBSERVED" or len(event["parts"]) < 2:
        return None
    return event["parts"][0], event["parts"][1]


def feedback_identity(identity: tuple[str, str]) -> str:
    """Collapse ephemeral ZooKeeper sequence suffixes for novelty feedback only."""
    operation, path = identity
    path = re.sub(r"(?<=/)qn-\d+", "qn-*", path)
    path = re.sub(r"(?<=/election/)[^/]+", "<election>", path)
    path = re.sub(r"127\.0\.0\.1:\d+_solr", "<node>", path)
    path = re.sub(r"core_node\d+", "core_node*", path)
    path = re.sub(r"n_\d+", "n_*", path)
    return operation + "|" + path


def io_behavior_key(event: dict) -> str | None:
    """Stable I/O behavior: production caller, operation, normalized resource.

    The occurrence ordinal is used only to select the exact injection point.
    Older traces without caller identity cannot establish new I/O behavior.
    """
    identity = io_identity(event)
    if identity is None or len(event["parts"]) < 3:
        return None
    caller = event["parts"][2]
    if not caller.startswith("caller="):
        return None
    return caller[7:] + "|" + feedback_identity(identity)


def sequence_applied_in_order(plan: list[str], applied: list[dict],
                              matched: list[dict], trial_events: list[dict]) -> bool:
    if len(applied) != len(plan):
        return False
    seen_fault_ids = set()
    for index, (expected, event) in enumerate(zip(plan, applied)):
        fields = expected.split("|")
        if len(fields) not in (3, 5):
            return False
        parts = event["parts"]
        if len(parts) < 3 or not parts[2].startswith("ordinal="):
            return False
        if (parts[0], parts[1], parts[2].split("=", 1)[1]) != tuple(fields[:3]):
            return False
        metadata = dict(item.split("=", 1) for item in parts[3:] if "=" in item)
        if not metadata.get("fault_id"):
            # Historical, completed selectors predate phase anchors. Preserve
            # their original exact op/path/global-ordinal validation only.
            if len(fields) != 3:
                return False
            continue
        fault_id = f"F{index}"
        previous_id = f"F{index - 1}" if index else "<none>"
        if (metadata.get("fault_id") != fault_id or
                metadata.get("previous_fault_id") != previous_id or
                metadata.get("plan_index") != str(index) or
                fault_id in seen_fault_ids):
            return False
        seen_fault_ids.add(fault_id)
        try:
            global_hit = int(metadata["global_hit_ordinal"])
        except (KeyError, ValueError):
            return False
        if global_hit <= 0:
            return False
        observed = [item for item in trial_events
                    if item["kind"] == "IO_OBSERVED" and
                    item["seq"] < event["seq"] and
                    item["parts"][:2] == parts[:2]]
        if global_hit != len(observed):
            return False
        if len(fields) == 5:
            if (fields[3] != f"after={previous_id}" or
                    not fields[4].startswith("seed_global=") or
                    metadata.get("seed_global") != fields[4].split("=", 1)[1] or
                    metadata.get("relative_count") != fields[2][1:]):
                return False
            phase_start = applied[index - 1]["seq"]
            try:
                relative_hit = int(metadata["relative_count"])
            except (KeyError, ValueError):
                return False
            if relative_hit != sum(
                    item["seq"] > phase_start for item in observed):
                return False
        elif fields[2].startswith("@"):
            return False
    if any(any(part.startswith("fault_id=") for part in event["parts"])
           for event in applied):
        if len(seen_fault_ids) != len(plan) or len(matched) != len(plan):
            return False
        for match, injection in zip(matched, applied):
            if match["seq"] + 1 != injection["seq"] or match["parts"] != injection["parts"]:
                return False
    elif matched:
        return False
    return True


def relevant(identity: tuple[str, str]) -> bool:
    _, path = identity
    return ("/collections/testAddMultipleReplicas" in path or path == "/collections"
            or path == "/live_nodes" or path.startswith("/overseer"))


def identity_rank(identity: tuple[str, str]) -> int:
    operation, path = identity
    if path.endswith("/state.json"):
        return 0 if operation in ("GET_DATA", "EXISTS_WATCH") else 1
    if "/terms/shard1" in path:
        return 2
    if "/leaders/shard1" in path:
        return 3
    if path == "/live_nodes":
        return 4
    if path.startswith("/overseer"):
        return 5
    return 6


def io_family(identity: tuple[str, str]) -> str:
    operation, path = identity
    if path.startswith("/collections/testAddMultipleReplicas/state.json"):
        namespace = "collection-state"
    elif "/terms/" in path:
        namespace = "collection-terms"
    elif "/leaders/" in path or "/leader_elect/" in path:
        namespace = "collection-leadership"
    elif path.startswith("/collections/"):
        namespace = "collection-other"
    elif path.startswith("/overseer"):
        namespace = "overseer-control"
    elif path.startswith("/live_nodes"):
        namespace = "live-nodes"
    else:
        namespace = "other"
    return operation + ":" + namespace


def coverage(output: Path) -> set[str]:
    execution = output / "jacoco.exec"
    if not execution.exists():
        return set()
    command = [JAVA, "-cp", str(CASE / "classes") + ":" + str(CASE / "lib/jacoco-core.jar"),
               "baseline.solr05.CoverageProbes", str(execution),
               "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist"]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return set(result.stdout.splitlines())


def initial_queue(healthy_events: list[dict]) -> list[list[str]]:
    counts = Counter(identity for event in healthy_events
                     if (identity := io_identity(event)) is not None and relevant(identity))
    candidates = []
    for identity, count in counts.items():
        operation, path = identity
        # Exact observed runtime path and ordinal, with later occurrences to preserve T.
        ordinals = sorted(set((1, max(1, count // 4), max(1, count // 2), max(1, 3 * count // 4))))
        for ordinal in ordinals:
            candidates.append((identity_rank(identity), -ordinal, [f"{operation}|{path}|{ordinal}"]))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return [plan for _, _, plan in candidates]


def plan_key(plan: list[str]) -> str:
    return ";".join(plan)


def write_result(state: dict) -> None:
    trials = state["trials"]
    applied = sum(1 for item in trials if item["all_faults_applied"])
    retained = sum(1 for item in trials if item["all_faults_applied"]
                   and item["target_after_fault"])
    candidate = sum(1 for item in trials if item["target_exception"])
    result = {
        "case_id": "SOLR-05", "system": "Solr 8.11.4",
        "source_file": "solr/core/src/java/org/apache/solr/cloud/ZkController.java",
        "source_line": 1274,
        "function": "ZkController.register(String, CoreDescriptor, boolean, boolean, boolean)",
        "check_code": "if (replica == null) throw new SolrException(...replica is removed from clusterstate)",
        "cluster_test": "AddReplicaTest.testAddMultipleReplicas",
        "status": "running" if len(trials) < state["budget"]["max_trials"] else "pending_result_review",
        "target_reached": True,
        "healthy_target_checks": state["healthy_target_checks"],
        "elapsed_seconds": round(state["elapsed_seconds"], 3),
        "fault_trials": len(trials), "strict_injections": applied,
        "target_after_fault": retained,
        "coverage_gain": len(set(state["seen_coverage"]) - set(state["healthy_coverage"])),
        "new_io_identities": len(set(state["seen_io"]) - set(state["healthy_io"])),
        "target_exception_candidates": candidate,
        "bug_mark": "candidate_needs_source_review" if candidate else "none",
        "evidence": "crashfuzz/cases/SOLR-05/evidence/campaign/state.json",
        "budget": state["budget"],
    }
    atomic_json(RESULT, result)


def initialize() -> dict:
    healthy_events = events(HEALTHY / "events.tsv")
    if not healthy_events or not (HEALTHY / "jacoco.exec").exists():
        raise RuntimeError("Instrumented healthy seed must pass before campaign")
    manifest = json.loads((HEALTHY / "manifest.json").read_text())
    if manifest["exit_code"] != 0:
        raise RuntimeError("Healthy JUnit failed")
    target_checks = sum(event["kind"] == "TARGET_CHECK" for event in healthy_events)
    if target_checks == 0:
        raise RuntimeError("Original JUnit does not reach selected target")
    callsite_events = events(HEALTHY_CALLSITE / "events.tsv")
    callsite_manifest = json.loads((HEALTHY_CALLSITE / "manifest.json").read_text())
    if callsite_manifest["exit_code"] != 0 or not callsite_events:
        raise RuntimeError("Healthy callsite seed must pass before campaign")
    healthy_io = {key for event in callsite_events
                  if (key := io_behavior_key(event)) is not None}
    healthy_families = healthy_io
    healthy_coverage = coverage(HEALTHY)
    state = {
        "case_id": "SOLR-05", "started_at": time.time(),
        "budget": {"max_trials": MAX_TRIALS, "max_faults": MAX_FAULTS},
        "healthy_target_checks": target_checks,
        "healthy_io": sorted(healthy_io), "seen_io": sorted(healthy_io),
        "healthy_io_families": sorted(healthy_families),
        "seen_io_families": sorted(healthy_families),
        "healthy_coverage": sorted(healthy_coverage),
        "seen_coverage": sorted(healthy_coverage),
        "queue": initial_queue(healthy_events), "seen_plans": [], "trials": [],
        "elapsed_seconds": manifest["elapsed_seconds"],
        "feedback_schema": 8,
    }
    atomic_json(STATE, state)
    write_result(state)
    return state


def reassess_prior_trials(state: dict) -> None:
    """Normalize older checkpoints to final-fault target and feedback semantics."""
    if state.get("feedback_schema") == 8:
        return
    healthy_events = events(HEALTHY_CALLSITE / "events.tsv")
    healthy_manifest = json.loads((HEALTHY_CALLSITE / "manifest.json").read_text())
    if healthy_manifest["exit_code"] != 0 or not healthy_events:
        raise RuntimeError("Healthy callsite seed must pass before feedback reassessment")
    healthy_io = {key for event in healthy_events
                  if (key := io_behavior_key(event)) is not None}
    state["healthy_io"] = sorted(healthy_io)
    healthy_coverage = coverage(HEALTHY)
    state["healthy_coverage"] = sorted(healthy_coverage)
    seen_coverage = set(healthy_coverage)
    seen_io = set(healthy_io)
    state["healthy_io_families"] = sorted(healthy_io)
    seen_families = set(healthy_io)
    for trial in state["trials"]:
        output = CAMPAIGN / f"trial-{trial['number']:03d}"
        trace = events(output / "events.tsv")
        applied = [event for event in trace
                   if event["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        matched = [event for event in trace if event["kind"] == "IO_MATCHED"]
        last_fault = max((event["seq"] for event in applied), default=None)
        target_after = last_fault is not None and any(
            event["kind"] == "TARGET_CHECK" and event["seq"] > last_fault
            for event in trace)
        candidate = last_fault is not None and any(
            event["kind"] == "TARGET_EXCEPTION" and event["seq"] > last_fault
            for event in trace)
        ordered = sequence_applied_in_order(trial["plan"], applied, matched, trace)
        eligible = ordered and target_after
        trial["faults_applied"] = len(applied)
        trial["all_faults_applied"] = ordered
        trial["target_after_fault"] = target_after
        trial["target_exception"] = candidate
        trial["eligible_feedback"] = eligible
        current_coverage = coverage(output) if eligible else set()
        trial["new_coverage"] = len(current_coverage - seen_coverage)
        seen_coverage |= current_coverage
        current_io = {key for event in trace
                      if (key := io_behavior_key(event)) is not None} if eligible else set()
        trial["new_io"] = len(current_io - seen_io)
        seen_io |= current_io
        families = current_io
        trial["new_io_families"] = sorted(families - seen_families)
        seen_families |= families
        atomic_json(output / "trial.json", trial)
    state["seen_coverage"] = sorted(seen_coverage)
    state["seen_io"] = sorted(seen_io)
    state["seen_io_families"] = sorted(seen_families)
    state["feedback_schema"] = 8
    atomic_json(STATE, state)
    write_result(state)


def rebalance_pending_queue(state: dict) -> None:
    """Spread the remaining budget over state, terms, leadership and control I/O."""
    if state.get("queue_rebalanced") == 2:
        return
    multi = [plan for plan in state["queue"] if len(plan) > 1]
    groups: dict[str, list[list[str]]] = {}
    for plan in state["queue"]:
        if len(plan) != 1:
            continue
        operation, path, _ = plan[0].split("|", 2)
        groups.setdefault(io_family((operation, path)), []).append(plan)
    order = sorted(groups, key=lambda item: (
        0 if "collection-state" in item else
        1 if "collection-terms" in item else
        2 if "collection-leadership" in item else
        3 if "live-nodes" in item else
        4 if "overseer-control" in item else 5, item))
    balanced = []
    while any(groups.values()):
        for family in order:
            if groups[family]:
                balanced.append(groups[family].pop(0))
    # Keep existing promising multi-fault seeds near the front, then diversify.
    state["queue"] = multi[:4] + balanced + multi[4:]
    state["queue_rebalanced"] = 2
    atomic_json(STATE, state)


def mutate(state: dict, plan: list[str], trial_events: list[dict], trial: dict) -> None:
    if len(plan) >= state["budget"]["max_faults"]:
        return
    if not trial["all_faults_applied"] or not trial["target_after_fault"]:
        return
    novel = bool(trial["new_coverage"] or trial.get("new_io_families"))
    last_fault = max(event["seq"] for event in trial_events
                     if event["kind"] == "IO_APPLIED_CONNECTION_LOSS")
    target_after = [event["seq"] for event in trial_events
                    if event["kind"] == "TARGET_CHECK" and event["seq"] > last_fault]
    if not target_after:
        return
    first_target = min(target_after)
    phase_counts = Counter()
    global_counts = Counter()
    candidates = []
    existing = set(plan)
    prior_identities = {(item.split("|", 2)[0], item.split("|", 2)[1])
                        for item in plan}
    for event in trial_events:
        identity = io_identity(event)
        if identity is None:
            continue
        global_counts[identity] += 1
        if event["seq"] > last_fault:
            phase_counts[identity] += 1
        # Pick faults before the next selected check, leaving time for T to run.
        if not (last_fault + 5 < event["seq"] < first_target - 5
                and relevant(identity)):
            continue
        operation, path = identity
        # Relative occurrence avoids brittle global ordinals when earlier faults
        # change how often this same I/O point is reached before the next phase.
        child = plan + [f"{operation}|{path}|@{phase_counts[identity]}|"
                        f"after=F{len(plan) - 1}|seed_global={global_counts[identity]}"]
        if child[-1] in existing:
            continue
        # Prefer a distinct I/O site, but allow a later occurrence of one already
        # faulted: the intervening state can differ after earlier exceptions.
        rank = identity_rank(identity) + (2 if identity in prior_identities else 0)
        candidates.append((rank, event["seq"], child))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    taken = 0
    taken_families = set()
    known = set(state["seen_plans"]) | {plan_key(item) for item in state["queue"]}
    for _, _, child in candidates:
        op, path, _ = child[-1].split("|", 2)
        family = io_family((op, path))
        if family in taken_families:
            continue
        key = plan_key(child)
        if key not in known:
            state["queue"].insert(0, child)
            known.add(key)
            taken_families.add(family)
            taken += 1
        # A non-novel strict seed can still unlock behavior with one more fault;
        # this is bounded to one descendant to keep the expanded budget focused.
        if taken == (3 if novel or len(plan) == 1 else 1):
            break


def run_campaign() -> None:
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    if "healthy_io_families" not in state:
        healthy = {io_family(tuple(item.split("|", 1))) for item in state["healthy_io"]}
        seen = {io_family(tuple(item.split("|", 1))) for item in state["seen_io"]}
        state["healthy_io_families"] = sorted(healthy)
        state["seen_io_families"] = sorted(seen)
    reassess_prior_trials(state)
    rebalance_pending_queue(state)
    if state["budget"]["max_trials"] < MAX_TRIALS:
        state["budget"] = {"max_trials": MAX_TRIALS, "max_faults": MAX_FAULTS}
        atomic_json(STATE, state)
        write_result(state)
    if state["budget"]["max_trials"] >= 128 and state["budget"]["max_faults"] < 10:
        state["budget"]["max_faults"] = 10
        atomic_json(STATE, state)
        write_result(state)
    while len(state["trials"]) < state["budget"]["max_trials"] and state["queue"]:
        plan = state["queue"].pop(0)
        key = plan_key(plan)
        if key in state["seen_plans"]:
            continue
        state["seen_plans"].append(key)
        number = len(state["trials"]) + 1
        output = CAMPAIGN / f"trial-{number:03d}"
        command = ["/usr/bin/python3", str(RUN), str(output), "--coverage", "--faults", key]
        started = time.time()
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, check=False)
        manifest = json.loads((output / "manifest.json").read_text())
        trace = events(output / "events.tsv")
        applied = [event for event in trace if event["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        matched = [event for event in trace if event["kind"] == "IO_MATCHED"]
        last_fault = max((event["seq"] for event in applied), default=None)
        target_after_fault = last_fault is not None and any(
            event["kind"] == "TARGET_CHECK" and event["seq"] > last_fault for event in trace)
        target_exception = last_fault is not None and any(
            event["kind"] == "TARGET_EXCEPTION" and event["seq"] > last_fault
            for event in trace)
        ordered = sequence_applied_in_order(plan, applied, matched, trace)
        eligible_feedback = ordered and target_after_fault
        old_coverage = set(state["seen_coverage"])
        current_coverage = coverage(output)
        new_coverage = (current_coverage - old_coverage) if eligible_feedback else set()
        if eligible_feedback:
            state["seen_coverage"] = sorted(old_coverage | current_coverage)
        old_io = set(state["seen_io"])
        current_io = {key for event in trace
                      if (key := io_behavior_key(event)) is not None}
        new_io = (current_io - old_io) if eligible_feedback else set()
        if eligible_feedback:
            state["seen_io"] = sorted(old_io | current_io)
        old_families = set(state.get("seen_io_families", state["healthy_io_families"]))
        current_families = current_io
        new_families = (current_families - old_families) if eligible_feedback else set()
        if eligible_feedback:
            state["seen_io_families"] = sorted(old_families | current_families)
        trial = {
            "number": number, "plan": plan,
            "elapsed_seconds": round(time.time() - started, 3),
            "junit_exit": manifest["exit_code"],
            "faults_applied": len(applied),
            "faults_matched": len(matched),
            "all_faults_applied": ordered,
            "eligible_feedback": eligible_feedback,
            "target_checks": sum(event["kind"] == "TARGET_CHECK" for event in trace),
            "target_after_fault": target_after_fault,
            "target_exception": target_exception,
            "new_coverage": len(new_coverage), "new_io": len(new_io),
            "new_io_families": sorted(new_families),
            "evidence": str(output.relative_to(CASE)),
        }
        state["trials"].append(trial)
        state["elapsed_seconds"] += trial["elapsed_seconds"]
        mutate(state, plan, trace, trial)
        atomic_json(output / "trial.json", trial)
        atomic_json(STATE, state)
        write_result(state)
        print(f"SOLR-05 {number}/{state['budget']['max_trials']} "
              f"applied={len(applied)}/{len(plan)} target_after={target_after_fault} "
              f"target_exception={target_exception} coverage+{len(new_coverage)} "
              f"io+{len(new_io)} elapsed={trial['elapsed_seconds']}", flush=True)
        if len(state["trials"]) == MAX_TRIALS:
            recent = state["trials"][-8:]
            if any(item["eligible_feedback"] and
                   (item["new_coverage"] or item.get("new_io_families"))
                   for item in recent):
                state["budget"] = {"max_trials": 128, "max_faults": 10}
                state["extension_reason"] = ("new production coverage or stable "
                                             "callsite-operation-resource I/O behavior "
                                             "within strict target-retaining trials 57-64")
                atomic_json(STATE, state)
                write_result(state)
    state["finished_at"] = time.time()
    atomic_json(STATE, state)
    write_result(state)


if __name__ == "__main__":
    run_campaign()
