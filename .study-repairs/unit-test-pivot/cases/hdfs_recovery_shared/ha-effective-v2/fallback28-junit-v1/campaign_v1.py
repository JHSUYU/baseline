#!/usr/bin/env python3
"""Independent HDFS-28 alternate-JUnit coverage/I/O-guided fault campaign."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
HA = HERE.parent
sys.path.insert(0, str(HA))
import campaign  # noqa: E402

TEST = ("org.apache.hadoop.hdfs.server.namenode.ha.TestPipelinesFailover"
        "#testLeaseRecoveryAfterFailover")
CASE = "HDFS-28"
TARGET_CLASS = "org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker"
PARENT_SHA = "824df96b2fbbcfeb2d29d444443a837f414d183f90e28fdf2789c8a07a40b93b"
RUNNER_SHA = "113bda1971e27d9d15eb4d71a54f914d5d1b2c37e0373bdc89af907e8b3a9188"
PILOT_AUDIT_SHA = "eb5b0efbacb1c02c3104e9eb24db8b0f8040eb84c9900a381463c3c613c93d73"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if sha(HA / "campaign.py") != PARENT_SHA or sha(HA / "run_original.py") != RUNNER_SHA:
    raise RuntimeError("shared released-JUnit runner or campaign source changed")
if sha(HERE / "pilot-audit.json") != PILOT_AUDIT_SHA:
    raise RuntimeError("two-pilot independent audit source changed")

campaign.HERE = HERE
campaign.RUNNER = HERE / "run_fallback.py"
campaign.STATE = HERE / "checkpoint.json"
campaign.LOCK = HERE / "campaign.lock"
campaign.HEALTHY = (HERE / "healthy-a", HERE / "healthy-b")
campaign.CASES = (CASE,)
campaign.MIN_FREE_BYTES = 10 * 1024**3

base_evaluate = campaign.evaluate
base_admit = campaign.admit
base_choose = campaign.choose


def stable_io(events: list[dict], last: dict | None = None) -> set[str]:
    return {campaign.family(event) for event in events
            if event.get("event") == "FAULT_POINT_OBSERVED"
            and event.get("marker", "").startswith("FAULT:")
            and (last is None or event.get("seq", 0) > last["seq"])
            and (last is None or (campaign.origin(event) == campaign.origin(last)
                                  and campaign.root(event) == campaign.root(last)))
            and campaign.identity_verified(events, event)
            and CASE in campaign.later_targets(event, events)}


def target_cov(directory: Path, metric: str) -> set[str]:
    return {value for value in campaign.covered(directory, metric)
            if value.startswith(TARGET_CLASS)}


def verify_healthy(directory: Path) -> list[dict]:
    manifest = json.loads((directory / "manifest.json").read_text())
    if (manifest.get("test") != TEST or manifest.get("returncode") != 0
            or manifest.get("instrumented") is not True
            or manifest.get("graphchecker_runtime_used") is not False):
        raise RuntimeError("alternate original JUnit healthy seed mismatch")
    events = campaign.trace(directory)
    if not any(event.get("event") == "CLUSTER_REGISTER"
               and event.get("dataNodes") == 3 for event in events):
        raise RuntimeError("missing three-DataNode original cluster")
    checks = [event for event in events if event.get("event") == "TARGET_CHECK"
              and event.get("caseId") == CASE
              and event.get("siteId") == campaign.SITES[CASE]]
    if not checks or any(event.get("outcome") is not False for event in checks):
        raise RuntimeError("healthy HDFS-28 guard absent or fatal")
    if not stable_io(events):
        raise RuntimeError("healthy lacks actor-bound pre-guard I/O")
    for metric in campaign.COVERAGE:
        if not (directory / ("covered_" + metric + ".txt")).is_file():
            raise RuntimeError("healthy missing production JaCoCo " + metric)
    return events


def calibrate() -> bool:
    validation = json.loads((HERE / "healthy-validation.json").read_text())
    receipt = json.loads((HERE / "healthy-receipt.json").read_text())
    if (validation.get("test") != TEST or receipt.get("test") != TEST
            or validation.get("receipt_sha256") != sha(HERE / "healthy-receipt.json")):
        raise RuntimeError("two-healthy independent validation mismatch")
    for directory in campaign.HEALTHY:
        verify_healthy(directory)
    return True


def evaluate(directory: Path, sequence: list[dict], state: dict) -> dict:
    trial = base_evaluate(directory, sequence, state)
    trial["raw_sha256"] = {name: sha(directory / name) for name in
                           ("manifest.json", "runtime_trace.jsonl", "junit.log",
                            "jacoco.exec", "fault-plan.tsv", "covered_probes.txt",
                            "covered_methods.txt", "covered_branch_counts.txt")}
    retained = bool(trial["exact_order_applied"] and trial["post_fault_target_checks"][CASE])
    trial["target_related_coverage_gain"] = {
        metric: len(target_cov(directory, metric)
                    - set(state["target_related_coverage"][metric])) if retained else 0
        for metric in ("methods", "branch_counts")}
    events = campaign.trace(directory)
    last = next((event for event in reversed(events)
                 if event.get("event") == "FAULT_APPLIED"), None) if retained else None
    trial["stable_actor_io_gain"] = sorted(
        stable_io(events, last) - set(state["stable_actor_io_families"])) if last else []
    return trial


def admit(state: dict, trial: dict) -> None:
    base_admit(state, trial)
    if not (trial["exact_order_applied"] and trial["post_fault_target_checks"][CASE]):
        return
    directory = Path(trial["run"])
    for metric in ("methods", "branch_counts"):
        state["target_related_coverage"][metric] = sorted(
            set(state["target_related_coverage"][metric]) | target_cov(directory, metric))
    state["stable_actor_io_families"] = sorted(
        set(state["stable_actor_io_families"]) | set(trial["stable_actor_io_gain"]))


def update_budget(state: dict) -> None:
    valid = campaign.effective(state)[CASE]
    if len(valid) < campaign.BASE or CASE in state["extensions"]:
        return
    tail = valid[campaign.BASE - 8:campaign.BASE]
    novelty = any(t["target_related_coverage_gain"]["methods"]
                  or t["target_related_coverage_gain"]["branch_counts"]
                  or t["stable_actor_io_gain"] for t in tail)
    state["extensions"][CASE] = {
        "decision_at_trial": len(state["completed"]),
        "last_eight_run_ids": [t["id"] for t in tail],
        "target_related_or_stable_io_novelty": bool(novelty)}
    if novelty:
        state["goals"][CASE] = campaign.EXTENDED
        state["attempt_cap"] = campaign.EXTENDED_ATTEMPTS
        state["max_faults"] = campaign.EXTENDED_DEPTH
        for prior in state["completed"]:
            if prior["exact_order_applied"] and len(prior["sequence"]) == campaign.BASE_DEPTH:
                admit(state, prior)


def choose(state: dict) -> int:
    # Exhaust both-seed, one-fault HDFS_RPC selectors before deeper mutations.
    early = [i for i, item in enumerate(state["queue"])
             if len(item["sequence"]) == 1
             and item["sequence"][0]["marker"] == "FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY"
             and CASE in item["eligible"]]
    if early:
        subset = {**state, "queue": [state["queue"][i] for i in early]}
        return early[base_choose(subset)]
    missed = state["pilot_history"]["missed_plan_id"]
    for i, item in enumerate(state["queue"]):
        if item["id"] == missed:
            return i
    return base_choose(state)


def build_state() -> dict:
    calibrate()
    audit = json.loads((HERE / "pilot-audit.json").read_text())
    plans = json.loads((HERE / "pilot-plans.json").read_text())["plans"]
    if (audit.get("fault_trials") != 2 or audit.get("effective_hdfs28") != 1
            or audit.get("errors") or audit.get("target_exception_candidates")
            or not audit["trials"][0]["exact_actor_bound"]
            or audit["trials"][1]["exact_actor_bound"]):
        raise RuntimeError("pilot feasibility receipt differs from expected")
    inputs = [(directory, verify_healthy(directory)) for directory in campaign.HEALTHY]
    baseline = {metric: sorted(set().union(*(
        campaign.covered(directory, metric) for directory, _ in inputs)))
        for metric in campaign.COVERAGE}
    families = {campaign.family(event) for _, events in inputs for event in events
                if event.get("event") == "FAULT_POINT_OBSERVED"
                and event.get("marker", "").startswith("FAULT:")}
    eligible_families = [
        {event["marker"] + "|" + event["siteId"] for event in events
         if event.get("event") == "FAULT_POINT_OBSERVED"
         and event.get("marker") == "FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY"
         and campaign.identity_verified(events, event)
         and CASE in campaign.later_targets(event, events)}
        for _, events in inputs]
    shared = eligible_families[0] & eligible_families[1]
    if not shared:
        raise RuntimeError("no shared actor-bound HDFS_RPC family in both healthy seeds")
    state = {"schema": 2, "test": TEST, "cases": (CASE,),
             "healthy": [{"run": str(directory),
                           "seconds": json.loads((directory / "manifest.json").read_text())["elapsed_seconds"],
                           "trace_sha256": sha(directory / "runtime_trace.jsonl")}
                          for directory, _ in inputs],
             "healthy_coverage": baseline,
             "coverage": {CASE: {metric: list(values) for metric, values in baseline.items()}},
             "io_families": {CASE: sorted(families)},
             "target_related_coverage": {
                 metric: sorted(set().union(*(target_cov(directory, metric)
                                             for directory, _ in inputs)))
                 for metric in ("methods", "branch_counts")},
             "stable_actor_io_families": sorted(set().union(*(
                 stable_io(events) for _, events in inputs))),
             "queue": [], "seen": [], "completed": [], "active": None,
             "started_at_utc": campaign.utc(), "goals": {CASE: campaign.BASE},
             "extensions": {}, "stop_reason": None,
             "attempt_cap": campaign.BASE_ATTEMPTS,
             "max_faults": campaign.BASE_DEPTH,
             "selection_policy": "shared_healthy_hdfs_rpc_then_pilot_miss_then_feedback_mutation",
             "pilot_history": {"audit_sha256": sha(HERE / "pilot-audit.json"),
                               "exact_plan_id": plans[0]["id"],
                               "missed_plan_id": plans[1]["id"],
                               "pilot_effective_outside_denominator": 1,
                               "pilot_attempts_outside_denominator": 2}}
    state["seen"].append(plans[0]["id"])
    for _, events in inputs:
        for event in events:
            if (event.get("event") != "FAULT_POINT_OBSERVED"
                    or event.get("marker") != "FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY"
                    or event["marker"] + "|" + event["siteId"] not in shared
                    or not campaign.identity_verified(events, event)
                    or CASE not in campaign.later_targets(event, events)):
                continue
            for kind in campaign.RPC_ERRORS:
                campaign.add(state, [campaign.point(event, kind)], priority=5,
                             eligible=(CASE,))
    missed = plans[1]
    if missed["id"] in state["seen"]:
        raise RuntimeError("missed pilot plan would duplicate healthy HDFS_RPC selector")
    state["seen"].append(missed["id"])
    state["queue"].append({"id": missed["id"], "sequence": missed["sequence"],
                           "priority": 0, "eligible": (CASE,),
                           "created": time.time(), "retries": 1,
                           "pilot_miss_retry": True})
    if plans[0]["id"] in {item["id"] for item in state["queue"]}:
        raise RuntimeError("already exact-tested pilot plan requeued")
    bootstrap = evaluate(HERE / "pilot-01", plans[0]["sequence"], state)
    if not (bootstrap["exact_order_applied"]
            and bootstrap["post_fault_target_checks"][CASE]
            and not bootstrap["candidate_needs_review"]):
        raise RuntimeError("pilot bootstrap not exact/target-retaining")
    admit(state, bootstrap)
    state["pilot_history"]["bootstrap_trace_sha256"] = bootstrap["raw_trace_sha256"]
    state["initial_queue"] = len(state["queue"])
    if not state["queue"] or len(state["seen"]) != len(set(state["seen"])):
        raise RuntimeError("empty or duplicate new campaign queue")
    return state


def start_state() -> dict:
    state = build_state()
    campaign.atomic_json(campaign.STATE, state)
    campaign.write_summary(state)
    return state


campaign.verify_healthy = verify_healthy
campaign.calibrate = calibrate
campaign.evaluate = evaluate
campaign.admit = admit
campaign.update_budget = update_budget
campaign.choose = choose
campaign.start_state = start_state

if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        state = build_state()
        print(json.dumps({"test": state["test"], "cases": state["cases"],
                          "queued": len(state["queue"]), "seen": len(state["seen"]),
                          "pilot_outside_denominator": state["pilot_history"],
                          "fresh_completed": len(state["completed"]),
                          "initial_one_fault_hdfs_rpc": sum(
                              len(x["sequence"]) == 1 and
                              x["sequence"][0]["marker"] ==
                              "FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY"
                              for x in state["queue"]),
                          "attempt_cap": state["attempt_cap"],
                          "goal": state["goals"][CASE]}, sort_keys=True))
    else:
        campaign.main()
