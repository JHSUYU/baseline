#!/usr/bin/env python3
"""Independently audit raw identity/JUnit receipts without launching Java.

This deliberately does not recheck JaCoCo branch or cumulative coverage.
Run audit_case.py separately when a JVM slot is available.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import controller


HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actor(event):
    return event.get("actor_raw"), event.get("manager")


def audit(case):
    checkpoint = HERE / "campaigns" / case / "checkpoint.json"
    state = json.loads(checkpoint.read_text())
    errors = []
    selected = Counter()
    exits = Counter()
    identities = set()
    records = []
    seen = set()
    for index, trial in enumerate(state["trials"], 1):
        ident = "r%03d" % index
        if trial["id"] != ident:
            errors.append(ident + ": ledger ID differs")
        plan = trial["plan"]
        if tuple(plan) in seen:
            errors.append(ident + ": duplicate exact plan")
        seen.add(tuple(plan))
        directory = HERE / trial["raw_run"]
        needed = ["trial.log", "trial.exit", "trial.plan", "agent.sha256"]
        absent = [name for name in needed if not (directory / name).is_file()]
        if absent:
            errors.append(ident + ": missing " + repr(absent))
            continue
        if (directory / "trial.plan").read_text().strip() != ";".join(plan):
            errors.append(ident + ": raw plan differs")
        exit_code = int((directory / "trial.exit").read_text().strip())
        exits[str(exit_code)] += 1
        if exit_code != trial["junit_exit"]:
            errors.append(ident + ": raw exit differs")
        identities.add((directory / "agent.sha256").read_text().split()[0])
        log = directory / "trial.log"
        trace = controller.parse(log.read_text(errors="replace"))
        applied = trace["FAULT_APPLIED"]
        exact = len(applied) == len(plan) == trial["applied_count"]
        for step, (event, wanted) in enumerate(zip(applied, plan), 1):
            selector, kind = wanted.rsplit("~", 1)
            if (event.get("step"), event.get("selector"), event.get("kind")) != (step, selector, kind):
                exact = False
            related = [x for x in trace["IO_ATTEMPT"] if x.get("seq") == event.get("seq")]
            if not related or related[0].get("role") != "ACTIVE_MASTER" or actor(related[0]) != actor(event):
                exact = False
        if applied and len({actor(x) for x in applied}) != 1:
            exact = False
        if exact != trial["strict"]:
            errors.append(ident + ": strict identity differs")
        last = applied[-1]["seq"] if applied else -1
        matched = []
        for target in trace["TARGET_EXIT"]:
            if (target.get("point"), target.get("subject")) != (case, controller.CASES[case][1]):
                continue
            selected[target.get("outcome")] += 1
            if not exact or not applied or target.get("bound_match") != "true" or actor(target) != actor(applied[-1]) or target.get("role") != "ACTIVE_MASTER":
                continue
            guards = [g for g in trace["GUARD_OPERAND"] if
                      (g.get("point"), g.get("subject"), g.get("seq")) ==
                      (case, target.get("subject"), target.get("seq")) and
                      actor(g) == actor(target) and g.get("event_seq", -1) > last]
            if guards:
                matched.append(target)
        if trial["target_after_final_fault"] and not matched:
            errors.append(ident + ": admitted target missing from raw actor/guard trace")
        if "target_outcomes" in trial and [x.get("outcome") for x in matched] != trial["target_outcomes"]:
            errors.append(ident + ": raw selected outcomes differ")
        if trial["effective"] != (trial["strict"] and trial["target_after_final_fault"]):
            errors.append(ident + ": effective admission differs")
        if trial["effective"] and not (directory / "trial.exec").is_file():
            errors.append(ident + ": admitted trial lacks JaCoCo exec")
        if trace["junit"] != trial["junit"] or trace["elapsed_seconds"] != trial["elapsed_seconds"]:
            errors.append(ident + ": raw JUnit/time differs")
        records.append({"id": ident, "log_sha256": sha(log),
                        "exec_sha256": sha(directory / "trial.exec") if (directory / "trial.exec").is_file() else None,
                        "strict": exact, "postfault_actor_guard_count": len(matched),
                        "junit_exit": exit_code})
    if state["effective"] != sum(t["effective"] for t in state["trials"]):
        errors.append("Effective total differs")
    if identities != {sha(HERE / "agent.jar")}:
        errors.append("Agent SHA set differs")
    return {"case": case, "checkpoint_sha256": sha(checkpoint),
            "attempts": len(state["trials"]), "effective": state["effective"],
            "strict": sum(t["strict"] for t in state["trials"]),
            "selected_outcomes_all_raw": dict(selected), "junit_exits": dict(exits),
            "agent_sha256": sorted(identities), "errors": errors,
            "coverage_recheck": "deferred; no Java process launched", "raw_receipts": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=controller.CASES)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = audit(args.case)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: report[key] for key in
                      ("case", "attempts", "effective", "strict", "selected_outcomes_all_raw", "errors")}, sort_keys=True))
    if report["errors"]:
        raise SystemExit(1)
