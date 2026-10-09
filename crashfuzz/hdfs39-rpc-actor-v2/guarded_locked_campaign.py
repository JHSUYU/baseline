#!/usr/bin/env python3
"""Resume HDFS-39 V2 under the shared JVM launch lock, one original JUnit at a time."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from build_offline import HERE
from campaign_v2 import ROOT, STATE
from guarded_campaign import read_state, verify_row


LOCK = HERE.parent / "jvm-start.lock"
CONTROLLER_LOCK = ROOT / "campaign-v2/guarded-locked-controller.lock"
LEDGER = ROOT / "campaign-v2/guarded-locked-ledger.jsonl"
MIN_FREE = 10 * 1024**3
MAX_JAVA_BEFORE_LAUNCH = 3  # At most four including this original JUnit.
TARGET = "FSDirAppendOp.appendFile:131"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def append(row: dict) -> None:
    with LEDGER.open("a") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def java_count() -> int:
    result = subprocess.run(["pgrep", "-c", "java"], capture_output=True,
                            text=True, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    return int(result.stdout.strip() or 0)


def postfault_target_exception(run_id: str, target: dict) -> bool:
    events = [json.loads(line) for line in
              (ROOT / run_id / "trace/runtime_trace.jsonl").read_text().splitlines()
              if line]
    applied = [event["seq"] for event in events if event.get("event") == "FAULT_APPLIED"]
    if not applied:
        return False
    last = max(applied)
    committed = {(event.get("threadId"), event.get("ordinal")) for event in events
                 if event.get("event") == "TARGET_GUARD" and
                 event.get("seq", -1) > last and event.get("committed") and
                 event.get("site") == TARGET and
                 event.get("path") == target["path"] and
                 event.get("blockId") == target["block_id"]}
    return any(event.get("event") == "TARGET_EXCEPTION" and
               event.get("seq", -1) > last and event.get("site") == TARGET and
               event.get("path") == target["path"] and
               event.get("blockId") == target["block_id"] and
               event.get("type") == "org.apache.hadoop.ipc.RetriableException" and
               (event.get("threadId"), event.get("ordinal")) in committed
               for event in events)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-completed", type=int, required=True)
    parser.add_argument("--expected-checkpoint-sha256", required=True)
    parser.add_argument("--new-completions-cap", type=int, default=0)
    parser.add_argument("--wall-seconds", type=int, default=24 * 3600)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if args.expected_completed < 0 or args.new_completions_cap < 0:
        parser.error("completion counts must be nonnegative")
    if args.wall_seconds <= 0 or args.poll_seconds <= 0:
        parser.error("wall and poll seconds must be positive")
    state = read_state()
    if (len(state["completed"]) != args.expected_completed or
            state["current"] is not None or
            sha(STATE) != args.expected_checkpoint_sha256):
        raise RuntimeError("complete-boundary handoff checkpoint differs")
    if state["completed"]:
        verify_row(state["completed"][-1], state["target"])
    if args.check_only:
        print(json.dumps({"handoff_pass": True, "completed": args.expected_completed,
                          "checkpoint_sha256": sha(STATE)}), flush=True)
        return
    deadline = time.monotonic() + args.wall_seconds
    with CONTROLLER_LOCK.open("a+") as controller:
        fcntl.flock(controller, fcntl.LOCK_EX | fcntl.LOCK_NB)
        append({"at_utc": stamp(), "status": "handoff", "completed": args.expected_completed,
                "checkpoint_sha256": args.expected_checkpoint_sha256,
                "shared_lock": str(LOCK), "minimum_free_bytes": MIN_FREE,
                "max_java_before_launch": MAX_JAVA_BEFORE_LAUNCH})
        while time.monotonic() < deadline:
            state = read_state()
            completed = len(state["completed"])
            if state["current"] is not None:
                raise RuntimeError("in-flight trial requires reconciliation")
            if state["status"] != "running":
                append({"at_utc": stamp(), "status": "terminal", "completed": completed,
                        "effective": sum(bool(row["effective"]) for row in state["completed"]),
                        "campaign_status": state["status"], "checkpoint_sha256": sha(STATE)})
                break
            if args.new_completions_cap and completed - args.expected_completed >= args.new_completions_cap:
                append({"at_utc": stamp(), "status": "pilot_complete_boundary",
                        "completed": completed, "checkpoint_sha256": sha(STATE)})
                break
            if (ROOT / "campaign-v2/pause.request").exists():
                append({"at_utc": stamp(), "status": "requested_complete_boundary_pause",
                        "completed": completed, "checkpoint_sha256": sha(STATE)})
                break
            gate_wait = False
            with LOCK.open("a+") as lock:
                # Queue as a blocking waiter so repeated JUnit launches by
                # other controllers cannot starve this complete checkpoint.
                fcntl.flock(lock, fcntl.LOCK_EX)
                # The shared lock covers this gate and the entire child process.
                count = java_count()
                free = shutil.disk_usage(HERE).free
                if count > MAX_JAVA_BEFORE_LAUNCH or free < MIN_FREE:
                    append({"at_utc": stamp(), "status": "resource_gate_wait",
                            "completed": completed, "java_before": count,
                            "free_bytes": free, "checkpoint_sha256": sha(STATE)})
                    gate_wait = True
                else:
                    before = sha(STATE)
                    command = [sys.executable, str(HERE / "campaign_v2.py"), "--once", "1"]
                    child = subprocess.run(command, cwd=HERE, check=False)
                    after = read_state()
                    if (child.returncode or len(after["completed"]) != completed + 1 or
                            after["current"] is not None):
                        append({"at_utc": stamp(), "status": "child_error_pause",
                                "completed_before": completed,
                                "completed_after": len(after["completed"]),
                                "child_returncode": child.returncode,
                                "checkpoint_sha256": sha(STATE)})
                        raise RuntimeError("campaign step did not complete one distinct trial")
                    last = verify_row(after["completed"][-1], after["target"])
                    observed = postfault_target_exception(last["run"], after["target"])
                    row = {"at_utc": stamp(), "status": "complete_trial",
                           "completed": completed + 1,
                           "effective": sum(bool(item["effective"]) for item in after["completed"]),
                           "java_before": count, "free_bytes_before": free,
                           "checkpoint_before_sha256": before,
                           "checkpoint_after_sha256": sha(STATE),
                           "raw": last, "postfault_target_exception": observed,
                           "campaign_status": after["status"]}
                    append(row)
                    print(json.dumps(row, sort_keys=True), flush=True)
                    if observed:
                        append({"at_utc": stamp(), "status": "target_exception_review_pause",
                                "run": last["run"], "completed": completed + 1})
                        break
            if gate_wait:
                time.sleep(args.poll_seconds)
        else:
            append({"at_utc": stamp(), "status": "wall_cap_complete_boundary",
                    "completed": len(read_state()["completed"]),
                    "checkpoint_sha256": sha(STATE)})


if __name__ == "__main__":
    main()
