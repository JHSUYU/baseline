#!/usr/bin/env python3
"""Graph-free, checkpointed LISTALIASES I/O campaign for SOLR-01."""

from collections import Counter
import json
from pathlib import Path
import subprocess
import time

from feedback import (atomic_json, events, io_behavior_key, io_identity,
                      sequence_applied_in_order)


WORK = Path(__file__).resolve().parents[1]
ROOT = WORK.parents[1]
CAMPAIGN = WORK / "evidence/campaign"
HEALTHY = WORK / "evidence/healthy-instrumented"
STATE = CAMPAIGN / "state.json"
CID = "SOLR-01"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
DIST = "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist"
OPERATION = "LISTALIASES_HTTP"
RESOURCE = "/admin/collections?action=LISTALIASES"
KINDS = ("IO_EXCEPTION", "SOLR_SERVER_EXCEPTION")
BASE_VALID, EXTENDED_VALID = 80, 128
BASE_FAULTS, EXTENDED_FAULTS = 8, 10


def metadata(event: dict) -> dict[str, str]:
    return dict(part.split("=", 1) for part in event["parts"]
                if "=" in part)


def site(event: dict) -> tuple[int, int] | None:
    if io_identity(event) != (OPERATION, RESOURCE):
        return None
    info = metadata(event)
    try:
        return int(info["call"]), int(info["attempt"])
    except (KeyError, ValueError):
        return None


def selector(call: int, attempt: int, kind: str) -> str:
    return f"{OPERATION}|{RESOURCE}|{call}|{attempt}|{kind}"


def coverage(directory: Path) -> set[str]:
    execution = directory / "jacoco.exec"
    if not execution.exists():
        return set()
    cp = str(WORK / "classes") + ":" + str(WORK / "lib/jacoco-core.jar")
    command = [JAVA, "-cp", cp, "baseline.solr01.CoverageProbes",
               str(execution), DIST]
    return set(subprocess.check_output(command, text=True).splitlines())


def target_counts(trace: list[dict]) -> int:
    return sum(e["kind"] == "TARGET_CHECK" and len(e["parts"]) >= 2
               and e["parts"][1] == CID for e in trace)


def after_target(trace: list[dict], last_fault: int) -> tuple[bool, bool]:
    if last_fault < 0:
        return False, False
    after = any(e["seq"] > last_fault and e["kind"] == "TARGET_CHECK" and
                len(e["parts"]) >= 2 and e["parts"][1] == CID for e in trace)
    exception = any(e["seq"] > last_fault and e["kind"] == "TARGET_EXCEPTION" and
                    e["parts"] and e["parts"][0] == CID for e in trace)
    return after, exception


def plan_key(plan: list[str]) -> str:
    return ";".join(plan)


def initial_queue(trace: list[dict]) -> list[list[str]]:
    targets = [e for e in trace if e["kind"] == "TARGET_CHECK" and
               len(e["parts"]) >= 2 and e["parts"][1] == CID]
    if not targets:
        raise RuntimeError("Healthy JUnit never reached selected getAliases outcome")
    sites = []
    for event in trace:
        parsed = site(event)
        if parsed is None:
            continue
        call, attempt = parsed
        if any(e["seq"] > event["seq"] and f"call={call}" in e["parts"]
               for e in targets):
            sites.append((call, attempt))
    # Explore different getAliases HTTP invocations before mutating deeper.
    unique = list(dict.fromkeys(sites))
    return [[selector(call, attempt, kind)]
            for call, attempt in unique for kind in KINDS]


def valid(trial: dict) -> bool:
    return trial["all_faults_applied"] and trial["target_after_fault"]


def write_result(state: dict) -> None:
    trials = state["trials"]
    valid_trials = [t for t in trials if valid(t)]
    done = (len(valid_trials) >= state["budget"]["max_valid_trials"] or
            len(trials) >= state["budget"]["max_attempts"] or
            not state["queue"])
    base_cov = set(state["healthy_coverage"])
    base_io = set(state["healthy_io"])
    previous = ROOT / CID / "result.json"
    legacy = json.loads(previous.read_text()).get("legacy_evidence") if previous.exists() else None
    value = {
        "case_id": CID, "system": "Solr 8.11.4",
        "source_file": "solr/solrj/src/java/org/apache/solr/client/solrj/impl/BaseHttpClusterStateProvider.java",
        "source_line": 267, "function": "BaseHttpClusterStateProvider.getAliases",
        "check_code": "after LISTALIASES fails at every known live node, throw RuntimeException",
        "cluster_test": "CloudHttp2SolrClientTest.testAliasHandling",
        "status": "pending_result_review" if done else "running",
        "target_reached": True, "healthy_target_checks": state["healthy_target_checks"],
        "fault_trials": len(trials), "valid_trials": len(valid_trials),
        "strict_injections": sum(t["all_faults_applied"] for t in trials),
        "target_after_fault": len(valid_trials),
        "target_exception_candidates": sum(t["target_exception"] for t in valid_trials),
        "coverage_gain": len(set(state["seen_coverage"]) - base_cov),
        "new_io_identities": len(set(state["seen_io"]) - base_io),
        "elapsed_seconds": round(state["elapsed_seconds"], 3),
        "campaign_workspace": "cases/SOLR-01/independent",
        "budget": state["budget"],
        "bug_mark": "candidate_needs_source_review" if any(t["target_exception"] for t in valid_trials) else "none",
        "evidence": str(STATE.relative_to(ROOT.parents[2])),
        "methodology": "independent_graph_free_coverage_http_io_exception",
        "legacy_evidence": legacy,
    }
    atomic_json(previous, value)


def initialize() -> dict:
    manifest = json.loads((HEALTHY / "manifest.json").read_text())
    trace = events(HEALTHY / "events.tsv")
    if manifest["exit_code"] != 0 or not trace:
        raise RuntimeError("Unchanged instrumented cluster JUnit must pass")
    checks = target_counts(trace)
    if checks == 0:
        raise RuntimeError("Selected getAliases outcome absent in healthy run")
    base_cov = coverage(HEALTHY)
    base_io = {key for event in trace
               if (key := io_behavior_key(event)) is not None}
    state = {
        "case_id": CID, "started_at": time.time(), "elapsed_seconds": 0.0,
        "budget": {"max_valid_trials": BASE_VALID, "max_faults": BASE_FAULTS,
                   "max_attempts": 3 * BASE_VALID},
        "healthy_target_checks": checks,
        "healthy_coverage": sorted(base_cov), "healthy_io": sorted(base_io),
        "seen_coverage": sorted(base_cov), "seen_io": sorted(base_io),
        "queue": initial_queue(trace), "seen_plans": [], "trials": [],
    }
    atomic_json(STATE, state)
    write_result(state)
    return state


def select_plan(state: dict) -> list[str]:
    queue = state["queue"]
    # Every fourth run tries a fresh root I/O invocation. The intervening
    # runs follow new post-fault I/O attempts in the actual prior execution.
    if (len(state["trials"]) + 1) % 4 == 0:
        root = next((i for i, plan in enumerate(queue) if len(plan) == 1), None)
        if root is not None:
            return queue.pop(root)
    return queue.pop(0)


def mutate(state: dict, plan: list[str], trace: list[dict], trial: dict) -> None:
    if len(plan) >= state["budget"]["max_faults"] or not valid(trial):
        return
    last_fault = max(e["seq"] for e in trace if e["kind"] == "IO_APPLIED")
    later_targets = [e for e in trace if e["kind"] == "TARGET_CHECK" and
                     e["seq"] > last_fault and len(e["parts"]) >= 2 and
                     e["parts"][1] == CID]
    last_target = max(e["seq"] for e in later_targets)
    known = set(state["seen_plans"]) | {plan_key(p) for p in state["queue"]}
    prior_call = int(plan[-1].split("|")[2])
    candidates = []
    for event in trace:
        if not (last_fault < event["seq"] < last_target):
            continue
        parsed = site(event)
        if parsed is None:
            continue
        call, attempt = parsed
        if not any(e["seq"] > event["seq"] and f"call={call}" in e["parts"]
                   for e in later_targets):
            continue
        for kind in KINDS:
            child = plan + [selector(call, attempt, kind)]
            if plan_key(child) not in known:
                candidates.append((0 if call == prior_call else 1,
                                   event["seq"], child))
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    novel = trial["new_coverage"] > 0 or trial["new_io"] > 0
    limit = 4 if novel or len(plan) == 1 else 2
    children = []
    for _, _, child in candidates:
        key = plan_key(child)
        if key in known:
            continue
        known.add(key)
        children.append(child)
        if len(children) >= limit:
            break
    state["queue"] = children + state["queue"]


def run_campaign() -> None:
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else initialize()
    while (sum(valid(t) for t in state["trials"]) < state["budget"]["max_valid_trials"] and
           len(state["trials"]) < state["budget"]["max_attempts"] and
           state["queue"]):
        plan = select_plan(state)
        key = plan_key(plan)
        if key in state["seen_plans"]:
            continue
        state["seen_plans"].append(key)
        number = len(state["trials"]) + 1
        output = CAMPAIGN / f"trial-{number:03d}"
        started = time.time()
        command = ["/usr/bin/python3", str(WORK / "probe/run.py"), str(output),
                   "--coverage", "--faults", key, "--timeout", "180"]
        subprocess.run(command, stdout=subprocess.DEVNULL,
                       stderr=subprocess.STDOUT, check=False)
        manifest = json.loads((output / "manifest.json").read_text())
        trace = events(output / "events.tsv")
        matched = [e for e in trace if e["kind"] == "IO_MATCHED"]
        applied = [e for e in trace if e["kind"] == "IO_APPLIED"]
        strict = sequence_applied_in_order(plan, applied, matched, trace)
        last = max((e["seq"] for e in applied), default=-1)
        after, exception = after_target(trace, last)
        eligible = strict and after
        current_cov = coverage(output) if eligible else set()
        current_io = {key for e in trace
                      if (key := io_behavior_key(e)) is not None} if eligible else set()
        old_cov, old_io = set(state["seen_coverage"]), set(state["seen_io"])
        trial = {
            "number": number, "plan": plan,
            "elapsed_seconds": round(time.time() - started, 3),
            "junit_exit": manifest["exit_code"],
            "faults_matched": len(matched), "faults_applied": len(applied),
            "all_faults_applied": strict,
            "target_checks": target_counts(trace),
            "target_after_fault": after, "target_exception": exception,
            "new_coverage": len(current_cov - old_cov) if eligible else 0,
            "new_io": len(current_io - old_io) if eligible else 0,
            "evidence": str(output.relative_to(WORK)),
        }
        if eligible:
            state["seen_coverage"] = sorted(old_cov | current_cov)
            state["seen_io"] = sorted(old_io | current_io)
        state["trials"].append(trial)
        state["elapsed_seconds"] += trial["elapsed_seconds"]
        mutate(state, plan, trace, trial)
        atomic_json(output / "trial.json", trial)
        atomic_json(STATE, state)
        write_result(state)
        count = sum(valid(t) for t in state["trials"])
        print(f"{CID} run={number} valid={count}/{state['budget']['max_valid_trials']} "
              f"applied={len(applied)}/{len(plan)} target_after={after} "
              f"target_exception={exception} coverage+={trial['new_coverage']} "
              f"io+={trial['new_io']} elapsed={trial['elapsed_seconds']}", flush=True)
        if count == BASE_VALID:
            recent = [t for t in state["trials"] if valid(t)][-8:]
            if any(t["new_coverage"] or t["new_io"] for t in recent):
                state["budget"] = {
                    "max_valid_trials": EXTENDED_VALID,
                    "max_faults": EXTENDED_FAULTS,
                    "max_attempts": 3 * EXTENDED_VALID,
                }
                state["extension_reason"] = (
                    "New production coverage or stable HTTP I/O family "
                    "in the last eight strict target-retaining trials")
                atomic_json(STATE, state)
                write_result(state)
    state["finished_at"] = time.time()
    atomic_json(STATE, state)
    write_result(state)


if __name__ == "__main__":
    run_campaign()
