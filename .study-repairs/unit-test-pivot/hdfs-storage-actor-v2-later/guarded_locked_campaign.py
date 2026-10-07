#!/usr/bin/env python3
"""Resume an HDFS storage V2 campaign one locked original JUnit at a time."""
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


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def append(path: Path, item: dict) -> None:
    with path.open("a") as stream:
        stream.write(json.dumps(item, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def archive_gate_pause(anchor: Path, receipt: Path, gate_result: dict) -> tuple[Path, Path | None]:
    """Move a failed pre-JUnit receipt away before retrying its plan number."""
    gate_archive = anchor / "gate-pauses"
    gate_archive.mkdir(exist_ok=True)
    receipt_copy = gate_archive / f"{receipt.stem}-{time.time_ns()}.json"
    raw_gate = Path(gate_result["gate"])
    raw_copy = receipt_copy.with_name(receipt_copy.stem + "-raw.json")
    if raw_gate.is_file():
        shutil.copy2(raw_gate, raw_copy)
    receipt.replace(receipt_copy)
    for saved in (receipt_copy, raw_copy):
        if saved.is_file():
            with saved.open("rb") as stream:
                os.fsync(stream.fileno())
    directory_fd = os.open(gate_archive, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return receipt_copy, raw_copy if raw_copy.is_file() else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=campaign.GROUPS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--expected-overlay-sha256", required=True)
    parser.add_argument("--max-attempts", type=int, default=600)
    parser.add_argument("--max-hours", type=float, default=8)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--min-free-gib", type=float, default=10)
    parser.add_argument("--gate-retry-seconds", type=float, default=30)
    args = parser.parse_args()
    if args.max_attempts > 600 or args.max_attempts < 1:
        parser.error("attempt cap must be 1..600")
    if args.max_hours <= 0:
        parser.error("time cap must be positive")
    if args.gate_retry_seconds <= 0:
        parser.error("gate retry interval must be positive")
    anchor = args.output.resolve()
    state_path = anchor / "campaign-state.json"
    receipt = json.loads((anchor / "healthy_receipt.json").read_text())
    if (not receipt.get("pass") or receipt.get("group") != args.group or
            receipt["seeds"][0]["instrumentation_digest_sha256"] !=
            args.expected_overlay_sha256):
        raise RuntimeError("healthy calibration or overlay gate failed")
    ledger = anchor / "guarded-locked-ledger.jsonl"
    deadline = time.monotonic() + args.max_hours * 3600
    with (anchor / "guarded-locked-controller.lock").open("a+") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            state = json.loads(state_path.read_text())
            completed = len(state["completion_order"])
            if state["group"] != args.group or state["in_flight"] is not None:
                raise RuntimeError("campaign state needs manual in-flight reconciliation")
            if state["instrumentation_digest_sha256"] != args.expected_overlay_sha256:
                raise RuntimeError("campaign overlay changed")
            if (anchor / "pause.request").exists():
                append(ledger, {"at_utc": stamp(), "status": "requested_boundary_pause",
                                "completed": completed})
                break
            if all(state["effective_by_case"][case] >=
                   state["budget"]["goal_by_case"][case] for case in state["case_ids"]):
                append(ledger, {"at_utc": stamp(), "status": "effective_budget_met",
                                "completed": completed, "effective": state["effective_by_case"]})
                break
            if completed >= args.max_attempts or not state["queue"]:
                append(ledger, {"at_utc": stamp(), "status": "queue_or_attempt_cap",
                                "completed": completed, "effective": state["effective_by_case"]})
                break
            if time.monotonic() >= deadline:
                append(ledger, {"at_utc": stamp(), "status": "wall_time_cap",
                                "completed": completed, "effective": state["effective_by_case"]})
                break
            # A missing receipt after a completed prior locked plan may mean
            # the supervisor died between durable state and receipt publication.
            # Preserve the run and stop for raw reconciliation rather than
            # silently continuing through a gap.
            if completed >= 2 and not (anchor / f"locked-plan-{completed:04d}.json").is_file():
                append(ledger, {"at_utc": stamp(), "status": "missing_prior_receipt_pause",
                                "completed": completed})
                break
            one_receipt = anchor / f"locked-plan-{completed + 1:04d}.json"
            if one_receipt.exists():
                stale = json.loads(one_receipt.read_text())
                if (stale.get("status") != "resource_gate_pause"
                        or stale.get("old_completed") != completed):
                    append(ledger, {"at_utc": stamp(), "status": "unexpected_existing_receipt_pause",
                                    "completed": completed, "receipt": str(one_receipt)})
                    break
                saved, raw = archive_gate_pause(anchor, one_receipt, stale)
                append(ledger, {"at_utc": stamp(), "status": "resource_gate_receipt_recovered",
                                "completed": completed, "reason": stale.get("gate_stdout", ""),
                                "receipt": str(saved), "raw_gate": str(raw) if raw else None})
            command = [sys.executable, str(campaign.HERE / "run_one_locked.py"),
                       "--group", args.group, "--output", str(anchor),
                       "--handoff", args.handoff,
                       "--expected-overlay-sha256", args.expected_overlay_sha256,
                       "--timeout", str(args.timeout),
                       "--min-free-gib", str(args.min_free_gib)]
            log = anchor / f"locked-controller-{completed + 1:04d}.log"
            with log.open("w") as stream:
                child = subprocess.run(command, stdout=stream,
                                       stderr=subprocess.STDOUT, check=False)
            after = json.loads(state_path.read_text())
            count = len(after["completion_order"])
            if one_receipt.exists():
                gate_result = json.loads(one_receipt.read_text())
                if (gate_result.get("status") == "resource_gate_pause"
                        and count == completed and after["in_flight"] is None):
                    # The locked launcher rejected this attempt before any
                    # JUnit or campaign mutation. Keep every failed gate's
                    # raw receipt even though the next retry reuses its plan
                    # number, then wait at this complete checkpoint boundary.
                    receipt_copy, raw_copy = archive_gate_pause(anchor, one_receipt, gate_result)
                    append(ledger, {"at_utc": stamp(), "status": "resource_gate_wait",
                                    "completed": completed, "effective": after["effective_by_case"],
                                    "reason": gate_result.get("gate_stdout", ""),
                                    "receipt": str(receipt_copy),
                                    "raw_gate": str(raw_copy) if raw_copy else None,
                                    "retry_seconds": args.gate_retry_seconds})
                    time.sleep(args.gate_retry_seconds)
                    continue
            if child.returncode or count != completed + 1 or not one_receipt.exists():
                append(ledger, {"at_utc": stamp(), "status": "locked_plan_pause",
                                "completed_before": completed, "completed_after": count,
                                "returncode": child.returncode, "log": str(log),
                                "receipt": str(one_receipt) if one_receipt.exists() else None})
                break
            entry = after["completed"][after["completion_order"][-1]]
            result = entry["result"]
            row = {"at_utc": stamp(), "status": "complete_plan", "plan_id": entry["item"]["id"],
                   "completed": count, "effective": after["effective_by_case"],
                   "goal": after["budget"]["goal_by_case"],
                   "junit_exit": result["junit_exit"],
                   "exact": result["exact_order_applied"],
                   "elapsed_seconds": result["elapsed_seconds"],
                   "same_actor_post_target": {case: x["same_actor_post_target"]
                                              for case, x in result["by_case"].items()},
                   "novel_target_throw": {case: x["target_exceptions_with_novel_signature"]
                                          for case, x in result["by_case"].items()},
                   "trace_sha256": result["trace_sha256"],
                   "receipt": str(one_receipt)}
            append(ledger, row)
            print(json.dumps(row, sort_keys=True), flush=True)
            if result["junit_exit"] != 0 or any(row["novel_target_throw"].values()):
                append(ledger, {"at_utc": stamp(), "status": "candidate_review_pause",
                                "completed": count, "plan_id": row["plan_id"]})
                break


if __name__ == "__main__":
    main()
