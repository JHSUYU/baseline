#!/usr/bin/env python3
"""Run exactly one original JUnit from a durable HDFS storage campaign plan.

The selected plan remains in_flight. campaign.py later consumes the saved
manifest and trace, so this gate does not repeat the JUnit or credit an
unreviewed attempt to any case's effective budget.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import campaign


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=campaign.GROUPS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--max-attempts", type=int, default=600)
    args = parser.parse_args()
    anchor = args.output.resolve()
    receipt = json.loads((anchor / "healthy_receipt.json").read_text())
    if not receipt["pass"] or receipt["group"] != args.group:
        raise RuntimeError("two healthy calibrations have not passed")
    state = campaign.load_state(anchor, args.group, receipt, args.max_attempts)
    if state["completion_order"]:
        raise RuntimeError("pilot_once is only for the first completed JUnit")
    item = campaign.pick(state)
    if item is None:
        raise RuntimeError("no eligible plan in initial queue")
    run = anchor / "runs" / item["id"] / "attempt-1"
    run.mkdir(parents=True, exist_ok=True)
    plan = run / "faults.tsv"
    if plan.exists() and plan.read_text() != campaign.plan_text(item["sequence"]):
        raise RuntimeError("existing plan differs from checkpoint")
    if not plan.exists():
        plan.write_text(campaign.plan_text(item["sequence"]))
    state["status"] = "pilot_junit_in_flight"
    campaign.write_json(anchor / "campaign-state.json", state)
    if not (run / "manifest.json").exists():
        with (run / "runner-console.log").open("w") as log:
            subprocess.run([sys.executable, str(campaign.HERE / "run_original.py"),
                            "--case", campaign.GROUPS[args.group][0],
                            "--output", str(run), "--plan", str(plan),
                            "--timeout", str(args.timeout)], stdout=log,
                           stderr=subprocess.STDOUT, check=False)
    if not (run / "manifest.json").exists() or not (run / "runtime_trace.jsonl").exists():
        raise RuntimeError("original JUnit did not leave a durable manifest and trace")
    summary = campaign.summarize_attempt(anchor, item, run,
                                         campaign.GROUPS[args.group][1], state)
    review = {"schema": "hdfs-storage-actor-v2-first-junit-review-1",
              "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
              "group": args.group, "plan": item,
              "campaign_checkpoint": str(anchor / "campaign-state.json"),
              "summary": summary,
              "credited_to_effective_budget": False}
    campaign.write_json(anchor / "pilot-first-junit-review.json", review)
    state["status"] = "pilot_junit_complete_pending_audit"
    campaign.write_json(anchor / "campaign-state.json", state)
    print(json.dumps({"plan_id": item["id"], "junit_exit": summary["junit_exit"],
                      "elapsed_seconds": summary["elapsed_seconds"],
                      "exact_order_applied": summary["exact_order_applied"],
                      "by_case": {case: {"post_target": result["same_actor_post_target"],
                                         "target_throws": result["target_exception_after_fault"],
                                         "valid_for_feedback": result["valid_for_feedback"]}
                                  for case, result in summary["by_case"].items()}},
                     sort_keys=True))


if __name__ == "__main__":
    main()
