#!/usr/bin/env python3
"""Resume the original HDFS recovery JUnit until per-check effective quotas."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

import campaign


HERE = Path(__file__).resolve().parent
RECEIPT = HERE / "effective-resume-receipt.json"
BACKUP = HERE / "campaign-state.before-effective-resume.json.gz"
START_LOCK = HERE.parents[2] / "jvm-start.lock"
OLD_SHA = "c990b52036d45f25a4370c611a2254fa3bdd580853a392226909ad04dd3a2b1b"
BASE = 80
EXTENDED = 128
ATTEMPT_CAP = 512
MIN_FREE = 8 * 1024**3
MAX_JAVA_BEFORE_LAUNCH = 4


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def effective(state: dict) -> dict[str, list[dict]]:
    strict = [row for row in state["completed"] if row["exact_order_applied"]]
    return {case: [row for row in strict
                   if row["post_fault_target_checks"][case]]
            for case in campaign.CASES}


def preview(state: dict) -> dict:
    valid = effective(state)
    return {
        "completed": len(state["completed"]),
        "effective": {case: len(rows) for case, rows in valid.items()},
        "queue": len(state["queue"]),
        "active": state["active"] is not None,
        "stop_reason": state["stop_reason"],
        "checkpoint_sha256": digest(campaign.STATE),
        "goals": state.get("effective_resume", {}).get("goals"),
    }


def initialize(state: dict) -> dict:
    if "effective_resume" in state:
        if not BACKUP.is_file():
            raise RuntimeError("resume checkpoint has no original backup")
        return state
    if (digest(campaign.STATE) != OLD_SHA or len(state["completed"]) != 128
            or state["active"] is not None or state["stop_reason"] != "budget"
            or state["budget"] != {"max_trials": 128, "max_faults": 10}):
        raise RuntimeError("unexpected historical checkpoint; refuse migration")
    observed = {case: len(rows) for case, rows in effective(state).items()}
    if observed != {"HDFS-28": 18, "HDFS-29": 39, "HDFS-30": 39}:
        raise RuntimeError("historical actor-qualified counts changed")
    with gzip.open(BACKUP, "wb") as out:
        out.write(campaign.STATE.read_bytes())
    state["effective_resume"] = {
        "schema": 1, "started_at_utc": utc(), "original_checkpoint_sha256": OLD_SHA,
        "original_completed": 128, "original_effective": observed,
        "goals": {case: BASE for case in campaign.CASES},
        "extension_decisions": {}, "attempt_cap": ATTEMPT_CAP,
        "last_completed": 128,
    }
    state["budget"] = {"max_trials": ATTEMPT_CAP, "max_faults": 10,
                       "base_effective_per_case": BASE,
                       "extended_effective_per_case": EXTENDED}
    state["stop_reason"] = None
    campaign.atomic_json(campaign.STATE, state)
    snapshot(state)
    return state


def update_goals(state: dict) -> None:
    policy = state["effective_resume"]
    valid = effective(state)
    for case in campaign.CASES:
        if len(valid[case]) < BASE or case in policy["extension_decisions"]:
            continue
        tail = valid[case][BASE - 8:BASE]
        novelty = any(row["coverage_gain"][case]["methods"]
                      or row["coverage_gain"][case]["branch_counts"]
                      or row["new_io_families"][case] for row in tail)
        policy["extension_decisions"][case] = {
            "at_completed": len(state["completed"]),
            "last_eight_ids": [row["id"] for row in tail],
            "late_method_branch_or_io_novelty": bool(novelty),
        }
        if novelty:
            policy["goals"][case] = EXTENDED


def terminal(state: dict) -> str | None:
    valid = effective(state)
    if any(row["target_exceptions_after_fault"][case]
           for row in state["completed"] for case in campaign.CASES):
        return "target_candidate_review"
    if all(len(valid[case]) >= state["effective_resume"]["goals"][case]
           for case in campaign.CASES):
        return "effective_budget_reached_pending_raw_audit"
    if len(state["completed"]) >= ATTEMPT_CAP:
        return "attempt_cap_inconclusive"
    if not state["queue"] and state["active"] is None:
        return "queue_exhausted_inconclusive"
    return None


def snapshot(state: dict) -> None:
    info = preview(state)
    info.update({"case_ids": list(campaign.CASES), "updated_at_utc": utc(),
                 "policy": state.get("effective_resume"),
                 "node": os.uname().nodename,
                 "minimum_free_bytes": MIN_FREE,
                 "max_java_before_launch": MAX_JAVA_BEFORE_LAUNCH})
    campaign.atomic_json(RECEIPT, info)


def java_count() -> int:
    result = subprocess.run(["pgrep", "-c", "java"], capture_output=True,
                            text=True, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    return int(result.stdout.strip() or 0)


def trial_java_started(run: Path) -> bool:
    needle = str(run).encode()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if b"/java\0" in cmdline and needle in cmdline:
            return True
    return False


def one_trial(state: dict) -> None:
    if state["active"] is None:
        state["active"] = state["queue"].pop(campaign.choose(state))
        campaign.atomic_json(campaign.STATE, state)
    run = HERE / "runs" / ("trial-%03d" % (len(state["completed"]) + 1))
    with START_LOCK.open("a+") as startup:
        fcntl.flock(startup, fcntl.LOCK_EX)
        if java_count() > MAX_JAVA_BEFORE_LAUNCH or shutil.disk_usage(HERE).free < MIN_FREE:
            return
        error: list[BaseException] = []

        def execute() -> None:
            try:
                campaign.run_one(state, state["active"])
            except BaseException as exc:
                error.append(exc)

        worker = threading.Thread(target=execute)
        worker.start()
        while worker.is_alive() and not trial_java_started(run):
            time.sleep(0.2)
    worker.join()
    if error:
        raise error[0]
    if len(state["completed"]) != int(run.name[-3:]):
        raise AssertionError("one trial did not atomically complete")
    state["effective_resume"]["last_completed"] = len(state["completed"])
    update_goals(state)
    reason = terminal(state)
    if reason:
        state["stop_reason"] = reason
    campaign.atomic_json(campaign.STATE, state)
    snapshot(state)
    print(json.dumps({"completed": len(state["completed"]),
                      "effective": {case: len(rows) for case, rows in effective(state).items()},
                      "goals": state["effective_resume"]["goals"],
                      "last": state["completed"][-1]["id"],
                      "stop_reason": state["stop_reason"]}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--wall-seconds", type=int, default=24 * 3600)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--max-new-attempts", type=int, default=0,
                        help="0 means continue until the effective budget or wall cap")
    args = parser.parse_args()
    if not args.run and not args.preview:
        parser.error("choose --preview or --run")
    if args.preview:
        print(json.dumps(preview(json.loads(campaign.STATE.read_text()))), flush=True)
        return
    deadline = time.monotonic() + args.wall_seconds
    with campaign.LOCK.open("a+") as case_lock:
        fcntl.flock(case_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = initialize(json.loads(campaign.STATE.read_text()))
        snapshot(state)
        new_attempts = 0
        while time.monotonic() < deadline:
            update_goals(state)
            reason = terminal(state)
            if reason or state["stop_reason"]:
                state["stop_reason"] = reason or state["stop_reason"]
                campaign.atomic_json(campaign.STATE, state)
                snapshot(state)
                print("terminal " + state["stop_reason"], flush=True)
                return
            before = len(state["completed"])
            one_trial(state)
            if len(state["completed"]) > before:
                new_attempts += 1
                if args.max_new_attempts and new_attempts >= args.max_new_attempts:
                    print("bounded pilot ended at complete checkpoint", flush=True)
                    return
            else:
                time.sleep(args.poll_seconds)
        print("wall cap reached at complete checkpoint; resume same script", flush=True)


if __name__ == "__main__":
    main()
