#!/usr/bin/env python3
"""Resume one original JUnit plan at a time, with a resource gate between plans."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import campaign


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def state_at(anchor: Path) -> dict:
    return json.loads((anchor / "campaign-state.json").read_text())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=campaign.GROUPS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--max-attempts", type=int, default=600)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--max-hours", type=float, default=8)
    parser.add_argument("--min-free-gib", type=float, default=10)
    args = parser.parse_args()
    anchor = args.output.resolve()
    if args.max_hours <= 0 or args.max_attempts <= 0:
        parser.error("time and attempt caps must be positive")
    if args.min_free_gib < 8:
        parser.error("disk floor cannot be less than 8 GiB")
    receipt = json.loads((anchor / "healthy_receipt.json").read_text())
    if not receipt["pass"] or receipt["group"] != args.group:
        raise RuntimeError("two healthy calibrations have not passed")
    digest = receipt["seeds"][0]["instrumentation_digest_sha256"]
    lock_path = anchor / "guarded-campaign.lock"
    with lock_path.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deadline = time.monotonic() + args.max_hours * 3600
        ledger = anchor / "guarded-campaign-ledger.jsonl"
        while True:
            state = state_at(anchor)
            before = len(state["completion_order"])
            if all(state["effective_by_case"][case] >=
                   state["budget"]["goal_by_case"][case] for case in state["case_ids"]):
                append_jsonl(ledger, {"at_utc": stamp(), "status": "effective_budget_met",
                                      "completed": before, "effective": state["effective_by_case"]})
                break
            if before >= args.max_attempts or not state["queue"] and not state["in_flight"]:
                append_jsonl(ledger, {"at_utc": stamp(), "status": "queue_or_attempt_cap",
                                      "completed": before, "effective": state["effective_by_case"]})
                break
            if time.monotonic() >= deadline:
                append_jsonl(ledger, {"at_utc": stamp(), "status": "wall_time_cap",
                                      "completed": before, "effective": state["effective_by_case"]})
                break
            gate_dir = anchor / "gates" / f"before-plan-{before + 1:04d}-{int(time.time())}"
            gate = subprocess.run([sys.executable, str(campaign.HERE / "host_gate.py"),
                                   "--output", str(gate_dir), "--handoff", args.handoff,
                                   "--expected-overlay-sha256", digest,
                                   "--min-free-gib", str(args.min_free_gib)],
                                  capture_output=True, text=True)
            if gate.returncode:
                append_jsonl(ledger, {"at_utc": stamp(), "status": "resource_gate_pause",
                                      "completed": before, "gate": str(gate_dir / "launch_gate.json"),
                                      "stdout": gate.stdout, "stderr": gate.stderr})
                break
            log_path = anchor / f"guarded-batch-{before + 1:04d}.log"
            with log_path.open("w") as log:
                completed = subprocess.run([
                    sys.executable, str(campaign.HERE / "campaign.py"),
                    "--group", args.group, "--output", str(anchor),
                    "--max-attempts", str(args.max_attempts),
                    "--timeout", str(args.timeout), "--max-new-completions", "1",
                ], stdout=log, stderr=subprocess.STDOUT, check=False)
            state = state_at(anchor)
            after = len(state["completion_order"])
            if completed.returncode or after != before + 1:
                append_jsonl(ledger, {"at_utc": stamp(), "status": "campaign_error_pause",
                                      "completed_before": before, "completed_after": after,
                                      "returncode": completed.returncode, "log": str(log_path),
                                      "in_flight": state["in_flight"]})
                break
            entry = state["completed"][state["completion_order"][-1]]
            result = entry["result"]
            row = {"at_utc": stamp(), "status": "complete_plan", "plan_id": entry["item"]["id"],
                   "case_ids": entry["item"]["cases"], "gate": str(gate_dir / "launch_gate.json"),
                   "log": str(log_path), "completed": after,
                   "effective": state["effective_by_case"],
                   "exact": result["exact_order_applied"], "junit_exit": result["junit_exit"],
                   "elapsed_seconds": result["elapsed_seconds"],
                   "post_target": {case: data["same_actor_post_target"]
                                   for case, data in result["by_case"].items()},
                   "novel_target_throw": {case: data["target_exceptions_with_novel_signature"]
                                          for case, data in result["by_case"].items()},
                   "trace_sha256": result["trace_sha256"]}
            append_jsonl(ledger, row)
            print(json.dumps(row, sort_keys=True), flush=True)
            if result["junit_exit"] != 0 or any(row["novel_target_throw"].values()):
                append_jsonl(ledger, {"at_utc": stamp(), "status": "candidate_review_pause",
                                      "plan_id": row["plan_id"], "completed": after})
                break


if __name__ == "__main__":
    main()
