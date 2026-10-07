#!/usr/bin/env python3
"""Independent CoreAdmin HTTP plus ZooKeeper I/O campaign for SOLR-09."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import subprocess
import time

from feedback import (atomic_json, events, io_identity, io_behavior_key,
                      sequence_applied_in_order)


WORK = Path(__file__).resolve().parents[1]
ROOT = WORK.parents[1]
CAMPAIGN = WORK / "evidence/campaign"
HEALTHY = WORK / "evidence/healthy-instrumented"
HEALTHY_SEEDS = ("healthy-instrumented", "healthy-alt-001", "healthy-alt-002")
STATE = CAMPAIGN / "state.json"
CASES = ("SOLR-09",)
SITES = {
    "SOLR-09": ("solr/core/src/java/org/apache/solr/cloud/api/collections/DeleteReplicaCmd.java", 278,
                "DeleteReplicaCmd.deleteCore",
                "if (!callable.call()) throw SolrException(Could not remove replica)"),
}
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
DIST = "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist"
BASE_TRIALS, BASE_FAULTS = 80, 8
EXTENDED_TRIALS, EXTENDED_FAULTS = 128, 10


def valid(trial: dict) -> bool:
    return (trial["all_faults_applied"] and
            trial["target_after_fault"]["SOLR-09"])


def loss_reason(output: Path, strict: bool, target_after: bool,
                junit_exit: int) -> str | None:
    if strict and target_after:
        return None
    if not strict:
        return "injection_not_strict"
    if junit_exit == 124:
        return "jvm_timeout"
    log = (output / "junit.log").read_text(errors="replace")
    if "Could not load collection from ZK" in log:
        return "collection_state_load_failed"
    if "Could not fully create collection" in log:
        return "collection_creation_incomplete"
    if "Timeout waiting for active collection" in log:
        return "collection_active_timeout"
    if "Timeout occurred while waiting response from server" in log:
        return "server_response_timeout"
    if "No registered leader was found" in log:
        return "leader_retry_timeout"
    if "SOLR05_JUNIT_FAILURE" in log:
        return "other_junit_failure"
    return "target_missing_without_junit_failure"


def relevant(identity: tuple[str, str]) -> bool:
    operation, path = identity
    if operation == "HTTP_POST":
        return path.startswith(
            "/admin/cores?action=UNLOAD&core=deletereplica_test_shard1_replica_")
    return (path == "/collections" or
            path.startswith("/collections/deletereplica_test") or
            path.startswith("/overseer") or path == "/live_nodes")


def rank(identity: tuple[str, str]) -> int:
    operation, path = identity
    if operation == "HTTP_POST":
        return -1
    if path.endswith("/state.json"):
        return 0 if operation in ("GET_DATA", "EXISTS_WATCH") else 1
    if "/terms/" in path:
        return 2
    if "/leaders/" in path or "/leader_elect/" in path:
        return 3
    if path.startswith("/collections/deletereplica_test"):
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
    if path.startswith("/collections/deletereplica_test"):
        return operation + ":collection-other"
    if path.startswith("/overseer"):
        return operation + ":overseer"
    return operation + ":other"


def coverage(directory: Path) -> set[str]:
    execution = directory / "jacoco.exec"
    if not execution.exists():
        return set()
    cp = str(WORK / "classes") + ":" + str(WORK / "lib/jacoco-core.jar")
    command = [JAVA, "-cp", cp, "baseline.solr09.CoverageProbes",
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
    for event in trace:
        if event["seq"] <= last_fault:
            continue
        parts = event["parts"]
        if event["kind"] == "TARGET_CHECK" and len(parts) >= 2 and parts[1] in after:
            after[parts[1]] = True
        elif event["kind"] == "TARGET_EXCEPTION" and parts and parts[0] in exception:
            exception[parts[0]] = True
    return after, exception


def initial_queue(traces: list[list[dict]]) -> list[list[str]]:
    """Seed exact CoreAdmin UNLOAD I/O identities from healthy cluster runs."""
    roots = []
    seen = set()
    for trace in traces:
        target = [e["seq"] for e in trace if e["kind"] == "TARGET_CHECK"
                  and len(e["parts"]) >= 2 and e["parts"][1] == "SOLR-09"]
        if not target:
            raise RuntimeError("A healthy seed missed selected target")
        last_target = max(target)
        occurrences = Counter()
        for event in trace:
            identity = io_identity(event)
            if identity is None:
                continue
            occurrences[identity] += 1
            if (event["seq"] < last_target and identity[0] == "HTTP_POST"
                    and relevant(identity) and len(event["parts"]) >= 3):
                operation, path = identity
                selector = (f"{operation}|{path}|{occurrences[identity]}|"
                            f"{event['parts'][2]}")
                if selector not in seen:
                    seen.add(selector)
                    roots.append([selector])
    if not roots:
        raise RuntimeError("No exact pre-target CoreAdmin UNLOAD I/O root")
    return roots


def plan_key(plan: list[str]) -> str:
    return ";".join(plan)


def select_next_plan(state: dict) -> list[str]:
    """Grow feedback descendants, but periodically visit another healthy root."""
    queue = state["queue"]
    if (len(state["trials"]) + 1) % 4 == 0:
        root = next((i for i, plan in enumerate(queue) if len(plan) == 1), None)
        if root is not None:
            return queue.pop(root)
    return queue.pop(0)


def initialize() -> dict:
    manifests = [json.loads((WORK / "evidence" / name / "manifest.json").read_text())
                 for name in HEALTHY_SEEDS]
    traces = [events(WORK / "evidence" / name / "events.tsv")
              for name in HEALTHY_SEEDS]
    if any(m["exit_code"] != 0 for m in manifests):
        raise RuntimeError("All unmodified cluster JUnit seeds must pass")
    if any(target_counts(trace)["SOLR-09"] == 0 for trace in traces):
        raise RuntimeError("A healthy seed missed the selected target")
    base_coverage = set().union(*(coverage(WORK / "evidence" / name)
                                  for name in HEALTHY_SEEDS))
    base_io = {identity for trace in traces for event in trace
               if (identity := io_behavior_key(event)) is not None}
    state = {
        "case_ids": CASES, "started_at": time.time(), "elapsed_seconds": 0.0,
        "budget": {"max_valid_trials": BASE_TRIALS,
                   "max_attempts": BASE_TRIALS * 3, "max_faults": BASE_FAULTS},
        "healthy_seed_names": HEALTHY_SEEDS,
        "healthy_target_checks": {"SOLR-09": sum(target_counts(t)["SOLR-09"]
                                                for t in traces)},
        "healthy_coverage": sorted(base_coverage), "healthy_io": sorted(base_io),
        "seen_coverage": {"SOLR-09": sorted(base_coverage)},
        "seen_io": {"SOLR-09": sorted(base_io)},
        "queue": initial_queue(traces), "seen_plans": [],
        "plan_attempts": {}, "trials": [],
    }
    atomic_json(STATE, state)
    write_results(state)
    return state


def write_results(state: dict) -> None:
    trials = state["trials"]
    budget_done = (sum(valid(t) for t in trials) >= state["budget"]["max_valid_trials"]
                   or len(trials) >= state["budget"]["max_attempts"]
                   or not state["queue"])
    base_cov = set(state["healthy_coverage"])
    base_io = set(state["healthy_io"])
    strict = sum(t["all_faults_applied"] for t in trials)
    adjustment = state.get("selection_adjustment")
    if adjustment:
        later = [t for t in trials if t["number"] >= adjustment["from_trial"]]
        adjustment_result = dict(adjustment)
        adjustment_result["after"] = {
            "attempts": len(later),
            "strict_injections": sum(t["all_faults_applied"] for t in later),
            "target_retained": sum(t["target_after_fault"]["SOLR-09"] for t in later),
            "valid_trials": sum(valid(t) for t in later),
            "production_probes_gained": sum(t["new_coverage"]["SOLR-09"] for t in later),
            "stable_io_gained": sum(t["new_io"]["SOLR-09"] for t in later),
        }
    else:
        adjustment_result = None
    retention_adjustment = state.get("retention_adjustment")
    if retention_adjustment:
        later = [t for t in trials if t["number"] >= retention_adjustment["from_trial"]]
        retention_result = dict(retention_adjustment)
        retention_result["after"] = {
            "attempts": len(later),
            "strict_injections": sum(t["all_faults_applied"] for t in later),
            "target_retained": sum(t["target_after_fault"]["SOLR-09"] for t in later),
            "valid_trials": sum(valid(t) for t in later),
            "production_probes_gained": sum(t["new_coverage"]["SOLR-09"] for t in later),
            "stable_io_gained": sum(t["new_io"]["SOLR-09"] for t in later),
            "target_loss_reasons": dict(Counter(t.get("loss_reason", "unclassified")
                                                for t in later if not valid(t))),
        }
    else:
        retention_result = None
    for cid in CASES:
        retained = sum(t["all_faults_applied"] and t["target_after_fault"][cid]
                       for t in trials)
        candidates = sum(t["all_faults_applied"] and
                         t["target_after_fault"][cid] and
                         t["target_exception"][cid] for t in trials)
        result = {
            "case_id": cid, "system": "Solr 8.11.4",
            "phase": "independent_http_coreadmin_plus_zk",
            "source_file": SITES[cid][0], "source_line": SITES[cid][1],
            "function": SITES[cid][2], "check_code": SITES[cid][3],
            "cluster_test": "DeleteReplicaTest.deleteReplicaAndVerifyDirectoryCleanup",
            "status": "pending_result_review" if budget_done else "running",
            "target_reached": True,
            "healthy_target_checks": state["healthy_target_checks"][cid],
            "fault_trials": len(trials), "strict_injections": strict,
            "valid_trials": sum(valid(t) for t in trials),
            "target_after_fault": retained,
            "target_exception_candidates": candidates,
            "coverage_gain": len(set(state["seen_coverage"][cid]) - base_cov),
            "new_io_identities": len(set(state["seen_io"][cid]) - base_io),
            "elapsed_seconds": round(state["elapsed_seconds"], 3),
            "campaign_workspace": "cases/SOLR-09/http-stage2",
            "budget": state["budget"],
            "bug_mark": "candidate_needs_source_review" if candidates else "none",
            "evidence": str(STATE.relative_to(ROOT.parents[2])),
            "methodology": "independent_graph_free_coverage_http_coreadmin_zk_io_exception",
            "selection_adjustment": adjustment_result,
            "retention_adjustment": retention_result,
            "incomplete_plan_retry_policy": state.get("incomplete_plan_retry_policy"),
        }
        output = WORK / "result.json"
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
    last = max(e["seq"] for e in trace if e["kind"].startswith("IO_APPLIED_"))
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
    if "incomplete_plan_retry_policy" not in state:
        state["incomplete_plan_retry_policy"] = {
            "from_trial": len(state["trials"]) + 1,
            "max_attempts_per_exact_plan": 3,
            "reason": "Original JUnit leader choice and later I/O can vary across runs; incomplete fault sequences remain invalid and are retried only within the attempt cap",
        }
        atomic_json(STATE, state)
        write_results(state)
    while (sum(valid(t) for t in state["trials"]) < state["budget"]["max_valid_trials"]
           and len(state["trials"]) < state["budget"]["max_attempts"]
           and state["queue"]):
        plan = select_next_plan(state)
        key = plan_key(plan)
        if key not in state["seen_plans"]:
            state["seen_plans"].append(key)
        state["plan_attempts"][key] = state["plan_attempts"].get(key, 0) + 1
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
        applied = [e for e in trace if e["kind"].startswith("IO_APPLIED_")]
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
            "loss_reason": loss_reason(output, strict, target_after["SOLR-09"],
                                       manifest["exit_code"]),
            "evidence": str(output.relative_to(WORK)),
        }
        state["trials"].append(trial)
        state["elapsed_seconds"] += trial["elapsed_seconds"]
        mutate(state, plan, trace, trial)
        # The original JUnit may choose the other leader core, or a later
        # observed I/O may disappear under a different schedule. Requeue a
        # plan whose full sequence was not applied, at most twice. Each miss
        # remains a separate attempt and never counts toward the valid budget.
        if not strict and state["plan_attempts"][key] < 3:
            state["queue"].append(plan)
        atomic_json(output / "trial.json", trial)
        atomic_json(STATE, state)
        write_results(state)
        valid_count = sum(valid(t) for t in state["trials"])
        print(f"SOLR-09 valid={valid_count}/{state['budget']['max_valid_trials']} attempt={number} "
              f"applied={len(applied)}/{len(plan)} strict={strict} "
              f"target_after={target_after} exception={exception} "
              f"coverage+={novelty_cov} io+={novelty_io} "
              f"elapsed={trial['elapsed_seconds']}", flush=True)
        if valid_count == BASE_TRIALS and state["budget"]["max_valid_trials"] == BASE_TRIALS:
            recent = [t for t in state["trials"] if valid(t)][-8:]
            if any(valid(t) and
                   (any(t["new_coverage"].values()) or any(t["new_io"].values()))
                   for t in recent):
                state["budget"] = {"max_valid_trials": EXTENDED_TRIALS,
                                   "max_attempts": EXTENDED_TRIALS * 3,
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
