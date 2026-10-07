#!/usr/bin/env python3
"""Check the two HBASE-22 pilot receipts and restore the original attempt cap."""
import hashlib
import json
import os
import shutil
from pathlib import Path

import controller

HERE = Path(__file__).resolve().parent
CASE = "HBASE-22"
CAMPAIGN = HERE / "campaigns" / CASE
EVIDENCE = HERE / "evidence" / CASE


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actor(event):
    return event.get("actor_raw"), event.get("manager")


def main():
    checkpoint = CAMPAIGN / "checkpoint.json"
    state = json.loads(checkpoint.read_text())
    if (len(state["trials"]), state["effective"], state["max_attempts"], state["status"]) != (
            59, 44, 59, "attempt_cap_pending_audit"):
        raise RuntimeError("Pilot has not stopped at its complete boundary")
    if (CAMPAIGN / "inflight.json").exists():
        raise RuntimeError("Pilot still has an in-flight plan")
    receipts = []
    for trial in state["trials"][-2:]:
        directory = HERE / trial["raw_run"]
        plan = (directory / "trial.plan").read_text().strip()
        log = directory / "trial.log"
        trace = controller.parse(log.read_text(errors="replace"))
        applied = trace["FAULT_APPLIED"]
        if plan != ";".join(trial["plan"]) or len(applied) != len(trial["plan"]):
            raise RuntimeError(trial["id"] + ": plan or applied count differs")
        if any((e.get("step"), e.get("selector"), e.get("kind")) !=
               (index, *wanted.rsplit("~", 1))
               for index, (e, wanted) in enumerate(zip(applied, trial["plan"]), 1)):
            raise RuntimeError(trial["id"] + ": applied identity differs")
        for event in applied:
            matching = [x for x in trace["IO_ATTEMPT"] if x.get("seq") == event.get("seq")]
            if not matching or matching[0].get("role") != "ACTIVE_MASTER" or actor(matching[0]) != actor(event):
                raise RuntimeError(trial["id"] + ": I/O actor differs")
        if len({actor(e) for e in applied}) != 1:
            raise RuntimeError(trial["id"] + ": multiple fault actors")
        targets = [x for x in trace["TARGET_EXIT"] if
                   x.get("point") == CASE and
                   x.get("subject") == controller.CASES[CASE][1] and
                   x.get("seq", -1) > applied[-1]["seq"] and
                   x.get("bound_match") == "true" and
                   x.get("role") == "ACTIVE_MASTER" and
                   actor(x) == actor(applied[-1])]
        guards = [g for g in trace["GUARD_OPERAND"] if any(
            g.get("point") == CASE and g.get("subject") == t.get("subject") and
            g.get("seq") == t.get("seq") and actor(g) == actor(t) and
            g.get("event_seq", -1) > applied[-1]["seq"] for t in targets)]
        if not targets or not guards or [t.get("outcome") for t in targets] != trial["target_outcomes"]:
            raise RuntimeError(trial["id"] + ": postfault target/guard differs")
        if (directory / "trial.exit").read_text().strip() != "0" or trace["junit"] != [1, 1, 0]:
            raise RuntimeError(trial["id"] + ": original JUnit did not pass")
        if not (trial["strict"] and trial["target_after_final_fault"] and trial["effective"]):
            raise RuntimeError(trial["id"] + ": checkpoint admission differs")
        if trial["target_exception_review"] != "healthy_expected":
            raise RuntimeError(trial["id"] + ": new candidate needs separate review")
        receipts.append({"id": trial["id"], "plan_sha256": sha(directory / "trial.plan"),
                         "log_sha256": sha(log), "exec_sha256": sha(directory / "trial.exec"),
                         "agent_sha256": (directory / "agent.sha256").read_text().split()[0],
                         "faults_applied": len(applied), "actor": list(actor(applied[-1])),
                         "postfault_selected_outcomes": [t.get("outcome") for t in targets],
                         "junit": trace["junit"], "junit_exit": 0,
                         "elapsed_seconds": trace["elapsed_seconds"]})
    archive = EVIDENCE / "checkpoint-after-two-round-pilot.json"
    if archive.exists():
        if sha(archive) != sha(checkpoint):
            raise RuntimeError("Pilot evidence already exists with different content")
    else:
        shutil.copyfile(checkpoint, archive)
    old_inflight = json.loads((EVIDENCE / "unstarted-inflight-before-loss-priority.json").read_text())
    retained = sum(x["plan"] == old_inflight["plan"] for x in state["queue"])
    executed = sum(x["plan"] == old_inflight["plan"] for x in state["trials"])
    if retained + executed != 1:
        raise RuntimeError("Unstarted original plan must remain queued or run exactly once")
    receipt = {"checkpoint_sha256": sha(archive), "attempts": len(state["trials"]),
               "effective": state["effective"], "status": state["status"],
               "unstarted_original_plan_retained": retained,
               "unstarted_original_plan_executed": executed,
               "pilot_trials": receipts, "coverage_note":
               "Controller admitted these trials only after JaCoCo selected branch coverage; full offline JaCoCo re-audit waits for JVM slot."}
    (EVIDENCE / "two-round-pilot-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    state["max_attempts"] = state.pop("pilot_original_max_attempts")
    state["status"] = "running"
    state["pilot_verified_at_attempt"] = len(state["trials"])
    target = checkpoint.with_suffix(".json.tmp")
    target.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    os.replace(target, checkpoint)
    print(json.dumps({"pilot_attempts": [x["id"] for x in receipts],
                      "effective": state["effective"], "budget_restored": state["max_attempts"],
                      "queue": len(state["queue"]), "original_plan_retained": retained,
                      "original_plan_executed": executed}))


if __name__ == "__main__":
    main()
