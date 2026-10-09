#!/usr/bin/env python3
"""Read-only audit of an actor-bound namespace campaign's raw receipts."""

import argparse
import hashlib
import json
from pathlib import Path
import re

import controller


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actor(event):
    return event.get("actor_raw"), event.get("manager")


def audit(case, allow_running=False):
    home = Path(__file__).resolve().parent
    cp = home / "campaigns" / case / "checkpoint.json"
    state = json.loads(cp.read_text())
    if state["status"] == "running" and not allow_running:
        raise ValueError("Wait for a complete checkpoint before final audit")
    errors = []
    raw = []
    effective = 0
    selected_outcomes = {}
    depths = {}
    fault_kinds = {}
    fault_families = {}
    junit_exits = {}
    strict_trials = 0
    seen = set()
    agent_shas = set()
    for index, trial in enumerate(state["trials"], 1):
        ident = "r%03d" % index
        if trial["id"] != ident:
            errors.append(f"{ident}: checkpoint trial ID differs")
        plan = trial["plan"]
        for step in plan:
            parts = step.split("~")
            fault_families[parts[1]] = fault_families.get(parts[1], 0) + 1
            fault_kinds[parts[-1]] = fault_kinds.get(parts[-1], 0) + 1
        if tuple(plan) in seen:
            errors.append(f"{ident}: duplicate exact plan")
        seen.add(tuple(plan))
        depths[len(plan)] = depths.get(len(plan), 0) + 1
        directory = home / trial["raw_run"]
        paths = {name: directory / name for name in
                 ("trial.log", "trial.exit", "trial.plan", "trial.exec", "agent.sha256")}
        missing = [name for name in ("trial.log", "trial.exit", "trial.plan", "agent.sha256")
                   if not paths[name].is_file()]
        if missing:
            errors.append(f"{ident}: missing {missing}")
            continue
        if paths["trial.plan"].read_text().strip() != ";".join(plan):
            errors.append(f"{ident}: raw plan differs")
        exit_code = int(paths["trial.exit"].read_text().strip())
        junit_exits[str(exit_code)] = junit_exits.get(str(exit_code), 0) + 1
        if exit_code != trial["junit_exit"]:
            errors.append(f"{ident}: raw exit differs")
        agent_sha = paths["agent.sha256"].read_text().split()[0]
        agent_shas.add(agent_sha)
        trace = controller.parse(paths["trial.log"].read_text(errors="replace"))
        applied = trace["FAULT_APPLIED"]
        if len(applied) != trial["applied_count"]:
            errors.append(f"{ident}: raw applied count differs")
        exact = len(applied) == len(plan)
        for step, (event, wanted) in enumerate(zip(applied, plan), 1):
            selector, kind = wanted.rsplit("~", 1)
            if (event.get("step"), event.get("selector"), event.get("kind")) != (
                    step, selector, kind):
                exact = False
            matching_io = [x for x in trace["IO_ATTEMPT"] if x.get("seq") == event.get("seq")]
            if not matching_io or matching_io[0].get("role") != "ACTIVE_MASTER" or actor(matching_io[0]) != actor(event):
                exact = False
        if applied and len({actor(x) for x in applied}) != 1:
            exact = False
        if bool(exact) != trial["strict"]:
            errors.append(f"{ident}: independent strict status differs")
        strict_trials += bool(exact)
        last = applied[-1]["seq"] if applied else -1
        branch_hit = True
        if case in controller.BRANCH_LINE:
            branch_hit = False
            if paths["trial.exec"].is_file():
                coverage_text, _, _ = controller.coverage([paths["trial.exec"]])
                line = controller.BRANCH_LINE[case]
                branch_hit = bool(re.search(
                    rf"BRANCH class={controller.TARGET_CLASS} line={line} covered=[1-9]",
                    coverage_text))
        matched = []
        for target in trace["TARGET_EXIT"]:
            if (target.get("point"), target.get("subject")) != (
                    case, controller.CASES[case][1]):
                continue
            selected_outcomes[target.get("outcome")] = selected_outcomes.get(target.get("outcome"), 0) + 1
            if not exact or not applied or target.get("bound_match") != "true" or actor(target) != actor(applied[-1]) or target.get("role") != "ACTIVE_MASTER":
                continue
            guards = [g for g in trace["GUARD_OPERAND"]
                      if (g.get("point"), g.get("subject"), g.get("seq")) ==
                      (case, target.get("subject"), target.get("seq"))
                      and actor(g) == actor(target) and g.get("event_seq", -1) > last]
            if not guards:
                continue
            if not branch_hit:
                continue
            matched.append(target)
        if bool(matched) != trial["target_after_final_fault"]:
            errors.append(f"{ident}: independent postfault actor/guard status differs")
        if "target_outcomes" in trial and [x.get("outcome") for x in matched] != trial["target_outcomes"]:
            errors.append(f"{ident}: raw selected outcomes differ")
        if trial["effective"] != (trial["strict"] and trial["target_after_final_fault"]):
            errors.append(f"{ident}: effective admission differs")
        effective += bool(trial["effective"])
        if trial["effective"] and not paths["trial.exec"].is_file():
            errors.append(f"{ident}: effective trial lacks JaCoCo data")
        if trace["junit"] != trial["junit"] or trace["elapsed_seconds"] != trial["elapsed_seconds"]:
            errors.append(f"{ident}: raw JUnit/elapsed receipt differs")
        raw.append({"id": ident, "sha256_log": sha(paths["trial.log"]),
                    "sha256_exec": sha(paths["trial.exec"]) if paths["trial.exec"].is_file() else None,
                    "effective": bool(trial["effective"]), "outcomes": [x.get("outcome") for x in matched]})
    if effective != state["effective"]:
        errors.append("effective trial total differs")
    if len(agent_shas) != 1 or agent_shas != {sha(home / "agent.jar")}:
        errors.append("agent SHA differs between raw runs or current JAR")
    methods = branches = None
    if not allow_running:
        _, method_set, branch_map = controller.coverage(state["coverage_execs"])
        methods, branches = len(method_set), branch_map
        if method_set != set(state["covered_methods"]) or branch_map != state["covered_branches"]:
            errors.append("JaCoCo cumulative coverage differs from checkpoint")
    recent = [x for x in state["trials"] if x["effective"]][-8:]
    return {"case_id": case, "checkpoint_sha256": sha(cp), "status": state["status"],
            "attempts": len(state["trials"]), "effective": effective,
            "strict_trials": strict_trials, "queue_length": len(state["queue"]),
            "depth_attempts": depths, "fault_kinds": fault_kinds,
            "fault_families": fault_families, "junit_exit_counts": junit_exits,
            "selected_outcomes_all_raw": selected_outcomes,
            "last8_effective_novelty": [{"id": x["id"], "new_methods": x.get("new_methods", 0),
                                         "new_branches": x.get("new_branches", 0),
                                         "new_stable_io_families": x.get("new_stable_io_families", 0)}
                                        for x in recent],
            "agent_sha256": sorted(agent_shas), "coverage_method_count": methods,
            "coverage_branch_lines": branches,
            "errors": errors, "raw_receipts": raw}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=controller.CASES)
    parser.add_argument("--allow-running", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = audit(args.case, args.allow_running)
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(output)
    print(json.dumps({key: report[key] for key in
                      ("case_id", "status", "attempts", "effective",
                       "selected_outcomes_all_raw", "errors")}, sort_keys=True))
    if report["errors"]:
        raise SystemExit(1)
