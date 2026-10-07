#!/usr/bin/env python3
"""Mirror authoritative node1 V5 checkpoints into three case results and 104 table."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import time

from feedback import atomic_json


CASE = Path(__file__).resolve().parents[1]
UNIT = CASE.parents[2]
RESULTS = UNIT / "cases"
REMOTE_STATE = CASE / "evidence/campaign-v4/state.json"
SSH_ID = Path.home() / ".ssh/id_ed25519_nodes"
REMOTE_HOST = "node1"
SITES = ("SOLR-10", "SOLR-39", "SOLR-40")
SOURCE_LINES = {"SOLR-10": 116, "SOLR-39": 246, "SOLR-40": 132}


def pull() -> dict:
    with tempfile.TemporaryDirectory(prefix="solr103940-v4-state-") as tmp:
        dest = Path(tmp) / "state.json"
        subprocess.run(["scp", "-q", "-i", str(SSH_ID),
                        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                        f"ZhenyuLi@{REMOTE_HOST}:{REMOTE_STATE}", str(dest)], check=True)
        return json.loads(dest.read_text())


def completion_time(trials: list[dict], site: str, goal: int) -> float | None:
    found = 0
    total = 0.0
    for trial in trials:
        total += trial["elapsed_seconds"]
        if trial["strict"] and trial["target_after_fault"][site]:
            found += 1
            if found >= goal:
                return round(total, 3)
    return None


def metrics(state: dict, site: str) -> dict:
    trials = state["trials"]
    eligible = [trial for trial in trials
                if trial["strict"] and trial["target_after_fault"][site]]
    strict = sum(trial["strict"] for trial in trials)
    progress = state["site_progress"][site]
    if progress["effective"] != len(eligible):
        raise ValueError(f"{site} effective count disagrees with raw trial records")
    exceptions = [trial["number"] for trial in eligible
                  if trial["target_exception"][site]]
    applied = set()
    for trial in eligible:
        for selector in trial["plan"]:
            tokens = selector.split("|")
            applied.add((tokens[0], tokens[1], tokens[3], tokens[4]))
    goal = progress["goal"]
    done = progress["effective"] >= goal
    if done:
        status = "quality_complete"
    elif progress["stop_reason"] == "attempt_cap_before_goal":
        status = "budget_exhausted_incomplete"
    elif progress["stop_reason"] == "queue_exhausted_before_goal":
        status = "queue_exhausted_incomplete"
    else:
        status = "fuzz_running"
    end_time = completion_time(trials, site, goal) if done else None
    reason = (f"V4 actor-aware unchanged JUnit campaign: {len(trials)} shared attempts, "
              f"{strict} strict, {len(eligible)}/{goal} effective for this guard; "
              f"stop={progress['stop_reason']}.")
    if site == "SOLR-40" and exceptions:
        reason += (" Strict target exception is a reproduced fault-induced "
                   "candidate; novelty remains pending. See candidate report and controls.")
    return {
        "budget": {"base_effective_goal": 80, "base_max_faults": 8,
                   "base_max_attempts": 720, "conditional_effective_goal": 128,
                   "conditional_max_faults": 10,
                   "conditional_max_attempts": 1152,
                   "current_effective_goal": goal,
                   "current_max_faults": state["budget"]["max_faults"],
                   "current_max_attempts": state["budget"]["max_attempts"]},
        "status": status,
        "quality_complete": done,
        "reason": reason,
        "source_line": SOURCE_LINES[site],
        "fault_trials": len(trials),
        "strict_injections": strict,
        "fully_applied_trials": strict,
        "effective_trials": len(eligible),
        "target_after_fault": len(eligible),
        "target_exception_candidates": len(exceptions),
        "target_exception_trial_numbers": exceptions,
        "target_guard_branch_taken": bool(exceptions),
        "coverage_gain": sum(trial["new_coverage"][site] for trial in eligible),
        "production_branches_gained": sum(trial["new_branches"][site] for trial in eligible),
        "production_methods_gained": sum(trial["new_methods"][site] for trial in eligible),
        "new_io_identities": sum(trial["new_io"][site] for trial in eligible),
        "new_io_families": sum(trial["new_io_families"][site] for trial in eligible),
        "unique_applied_callsite_operation_resource": len(applied),
        "max_applied_faults": max((trial["faults_applied"] for trial in trials), default=0),
        "elapsed_seconds": end_time if end_time is not None else round(state["elapsed_seconds"], 3),
        "case_completion_elapsed_seconds": end_time,
        "shared_elapsed_seconds_at_snapshot": round(state["elapsed_seconds"], 3),
        "shared_execution_group": "SOLR-10/39/40",
        "healthy_target_checks": state["healthy_target_checks"][site],
        "evidence": str(REMOTE_STATE) + f" ({REMOTE_HOST})",
        "v4_checkpoint": str(REMOTE_STATE) + " (node2, frozen at trial 189)",
        "v5_checkpoint": str(REMOTE_STATE) + f" ({REMOTE_HOST}, continuation)",
        "build_receipt_sha256": state["build_receipt_sha256"],
        "snapshot_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def publish(state: dict) -> None:
    if state["identity_version"] != "actor-v2":
        raise ValueError("Wrong identity model")
    for site in SITES:
        path = RESULTS / site / "result.json"
        result = json.loads(path.read_text())
        if result["case_id"] != site:
            raise ValueError(f"Wrong result file: {path}")
        result.update(metrics(state, site))
        reviewed = set(result.get("candidate_campaign_trials", []))
        pending = sorted(set(result["target_exception_trial_numbers"]) - reviewed)
        result["unreviewed_target_exception_trials"] = pending
        if site == "SOLR-40" and result["target_exception_candidates"] and not pending:
            result["bug_mark"] = "reproduced_candidate_novelty_pending"
            result["candidate_report"] = str(CASE / "CANDIDATE-SOLR-40.md")
            result["candidate_replay_summary"] = str(CASE / "evidence/candidate-solr40-v4/summary.json")
            result["candidate_control_summary"] = str(CASE / "evidence/causal-control-v4/summary.json")
            result["candidate_lowlevel_control_summary"] = str(CASE / "evidence/lowlevel-control-v4/summary.json")
        elif result["target_exception_candidates"]:
            result["bug_mark"] = "target_exception_candidate_unreviewed"
        atomic_json(path, result)
    subprocess.run(["python3", str(UNIT / "checklist.py"), "render"], check=True)
    print(json.dumps({"attempts": len(state["trials"]),
                      "effective": {site: state["site_progress"][site]["effective"]
                                    for site in SITES},
                      "stops": {site: state["site_progress"][site]["stop_reason"]
                                for site in SITES}}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=120)
    args = parser.parse_args()
    last = -1
    while True:
        try:
            state = pull()
            count = len(state["trials"])
            if count != last:
                publish(state)
                last = count
            if all(state["site_progress"][site]["stop_reason"] != "running"
                   for site in SITES):
                break
        except Exception as error:
            print(f"sync failed: {error}", flush=True)
            if not args.watch:
                raise
        if not args.watch:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
