#!/usr/bin/env python3
"""Hold the shared host JVM lock through each original HDFS31 JUnit trial."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import campaign
import run_original

LOCK = Path("/users/ZhenyuLi/baseline/crashfuzz/jvm-start.lock")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(path: Path, row: dict) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def gate(anchor: Path, expected_sha: str, min_gib: float) -> dict:
    java = subprocess.run([str(run_original.JDK / "jps"), "-l"],
                          text=True, capture_output=True)
    if java.returncode != 0:
        return {"at_utc": now(), "ready": False,
                "reason": "jps failed", "stdout": java.stdout, "stderr": java.stderr}
    processes = [line.strip() for line in java.stdout.splitlines()
                 if line.strip() and "sun.tools.jps.Jps" not in line]
    free = shutil.disk_usage(anchor).free
    current_sha = run_original.instrumentation_digest()
    ready = len(processes) <= 4 and free >= min_gib * 1024**3 and current_sha == expected_sha
    return {"at_utc": now(), "ready": ready, "java_before": len(processes),
            "jps": processes, "disk_free_bytes": free, "min_free_gib": min_gib,
            "expected_overlay_sha256": expected_sha, "actual_overlay_sha256": current_sha,
            "reason": "ready" if ready else "java_disk_or_overlay_gate"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchor", type=Path, default=campaign.HERE / "evidence")
    parser.add_argument("--max-attempts", type=int, default=320)
    parser.add_argument("--max-hours", type=float, default=8)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--min-free-gib", type=float, default=10)
    parser.add_argument("--gate-retry-seconds", type=float, default=30)
    parser.add_argument("--max-new-completions", type=int,
                        help="stop at a complete checkpoint after this many new plans")
    parser.add_argument("--pause-at-base", action="store_true",
                        help="stop at 80 effective for source/coverage review before any extension")
    args = parser.parse_args()
    if (args.max_attempts < 1 or args.max_attempts > 512 or args.max_hours <= 0
            or args.gate_retry_seconds <= 0 or
            (args.max_new_completions is not None and args.max_new_completions < 1)):
        parser.error("invalid attempt/time/retry bound")
    anchor = args.anchor.resolve()
    anchor.mkdir(parents=True, exist_ok=True)
    receipt = json.loads((anchor / "healthy_receipt.json").read_text())
    if receipt.get("schema") != "hdfs31-actor-v3-healthy-1" or not receipt.get("pass"):
        raise RuntimeError("two original healthy seeds have not passed")
    expected = receipt["seeds"][0]["instrumentation_digest_sha256"]
    run_original.build()
    if run_original.instrumentation_digest() != expected:
        raise RuntimeError("host overlay differs from healthy calibration")
    state = campaign.load_state(anchor, receipt, args.max_attempts)
    initial_completed = len(state["completion_order"])
    ledger = anchor / "guarded-ledger.jsonl"
    with (anchor / "controller.lock").open("a+") as controller:
        fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            state = json.loads((anchor / "campaign-state.json").read_text())
            completed = len(state["completion_order"])
            if args.pause_at_base and state["effective"] >= state["budget"]["base_effective"]:
                append(ledger, {"at_utc": now(), "status": "base_review_pause",
                                "completed": completed, "effective": state["effective"],
                                "goal": state["budget"]["goal"]})
                break
            if (args.max_new_completions is not None and
                    completed - initial_completed >= args.max_new_completions):
                append(ledger, {"at_utc": now(), "status": "complete_boundary_cap",
                                "completed": completed, "effective": state["effective"],
                                "new_completed": completed - initial_completed})
                break
            if state["effective"] >= state["budget"]["goal"]:
                append(ledger, {"at_utc": now(), "status": "effective_budget_met",
                                "completed": completed, "effective": state["effective"]})
                break
            if completed >= state["budget"]["max_attempts"] or (
                    not state["queue"] and state.get("in_flight") is None):
                state["status"] = "budget_recheck_pending"
                state["stop_reason"] = "attempt_cap" if completed >= state["budget"]["max_attempts"] else "queue_exhausted"
                campaign.save(anchor / "campaign-state.json", state)
                append(ledger, {"at_utc": now(), "status": "queue_or_attempt_cap",
                                "completed": completed, "effective": state["effective"]})
                break
            started = datetime.fromisoformat(state["started_at_utc"])
            if (datetime.now(timezone.utc) - started).total_seconds() >= args.max_hours * 3600:
                state["status"] = "budget_recheck_pending"
                state["stop_reason"] = "wall_time_cap"
                campaign.save(anchor / "campaign-state.json", state)
                append(ledger, {"at_utc": now(), "status": "wall_time_cap",
                                "completed": completed, "effective": state["effective"]})
                break
            if (anchor / "pause.request").exists():
                append(ledger, {"at_utc": now(), "status": "requested_boundary_pause",
                                "completed": completed, "effective": state["effective"]})
                break
            inflight = state.get("in_flight")
            if inflight is not None:
                run = anchor / "runs" / inflight["id"] / "attempt-1"
                if not (run / "manifest.json").is_file():
                    append(ledger, {"at_utc": now(), "status": "unresolved_inflight_pause",
                                    "completed": completed, "run": str(run)})
                    break
            with LOCK.open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                sample = gate(anchor, expected, args.min_free_gib)
                sample["completed_before"] = completed
                if not sample["ready"]:
                    append(ledger, {"at_utc": now(), "status": "resource_gate_wait", **sample})
                else:
                    log = anchor / f"controller-{completed + 1:04d}.log"
                    command = [sys.executable, str(campaign.HERE / "campaign.py"),
                               "--anchor", str(anchor), "--max-attempts", str(args.max_attempts),
                               "--timeout", str(args.timeout), "--once", "1"]
                    with log.open("w") as output:
                        child = subprocess.run(command, stdout=output,
                                               stderr=subprocess.STDOUT, check=False)
                    after = json.loads((anchor / "campaign-state.json").read_text())
                    count = len(after["completion_order"])
                    row = {"at_utc": now(), "status": "complete_plan" if child.returncode == 0
                           and count == completed + 1 and after["in_flight"] is None
                           else "trial_error_pause", "completed": count,
                           "effective": after["effective"], "goal": after["budget"]["goal"],
                           "child_returncode": child.returncode, "log": str(log), "gate": sample}
                    if row["status"] == "complete_plan":
                        entry = after["completed"][after["completion_order"][-1]]
                        result = entry["result"]
                        row.update({"plan_id": entry["item"]["id"],
                                    "junit_exit": result["junit_exit"],
                                    "elapsed_seconds": result["elapsed_seconds"],
                                    "exact": result["exact_order_applied"],
                                    "same_dn_bp_post_target": result["same_dn_bp_post_target"],
                                    "novel_target_throw": result["target_exceptions_with_novel_signature"],
                                    "trace_sha256": result["trace_sha256"]})
                    append(ledger, row)
                    print(json.dumps(row, sort_keys=True), flush=True)
                    if row["status"] != "complete_plan":
                        break
                    if result["junit_exit"] != 0 or result["target_exceptions_with_novel_signature"]:
                        append(ledger, {"at_utc": now(), "status": "candidate_review_pause",
                                        "completed": count, "plan_id": row["plan_id"]})
                        break
            if not sample["ready"]:
                time.sleep(args.gate_retry_seconds)


if __name__ == "__main__":
    main()
