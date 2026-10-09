#!/usr/bin/env python3
"""Resource-gated, resumable supervisor for the HDFS-39 original-JUnit queue."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from build_offline import HERE
from campaign_v2 import ROOT, STATE, read_events, write_json
from strict_receipt import audit


RECEIPT = ROOT / "campaign-v2/guarded-supervisor.json"
MIN_FREE = 8 * 1024**3
MAX_JAVA_BEFORE_LAUNCH = 3
TEST = "org.apache.hadoop.hdfs.TestFileAppend#testMultipleAppends"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def java_count() -> int:
    result = subprocess.run(["pgrep", "-c", "java"], capture_output=True,
                            text=True, check=False)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    return int(result.stdout.strip() or 0)


def verify_row(row: dict, target: dict) -> dict:
    name = row["run"]
    directory = ROOT / name
    result = json.loads((directory / "trial-result.json").read_text())
    manifest = json.loads((directory / "manifest.json").read_text())
    if result != row or manifest["test"] != TEST or manifest["exit"] != row["junit_exit"]:
        raise AssertionError(f"{name}: checkpoint/raw manifest mismatch")
    trace = directory / "trace/runtime_trace.jsonl"
    if manifest["trace_sha256"] != sha(trace):
        raise AssertionError(f"{name}: raw trace SHA mismatch")
    plan = [[str(point[key]) for key in ("marker", "api", "endpoint", "ordinal", "exception")]
            for point in row["sequence"]]
    independently = audit(read_events(trace), plan, target)
    if independently != row["receipt"]:
        raise AssertionError(f"{name}: independent strict receipt differs")
    return {"run": name, "effective": row["effective"],
            "junit_exit": row["junit_exit"], "candidate": row["candidate"],
            "seconds": row["elapsed_seconds"], "trace_sha256": sha(trace),
            "manifest_sha256": sha(directory / "manifest.json"),
            "trial_result_sha256": sha(directory / "trial-result.json")}


def read_state() -> dict:
    if not STATE.is_file():
        raise FileNotFoundError("initialize and calibrate before launching")
    state = json.loads(STATE.read_text())
    if (state.get("case") != "HDFS-39" or state.get("legacy_effective_imported") != 0
            or state["budget"]["attempt_cap"] not in (320, 512)):
        raise AssertionError("unexpected HDFS-39 V2 checkpoint/budget")
    return state


def snapshot(state: dict, last: dict | None, started: str) -> None:
    write_json(RECEIPT, {
        "case": "HDFS-39", "started_at_utc": started,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "checkpoint_sha256": sha(STATE), "status": state["status"],
        "completed": len(state["completed"]),
        "effective": sum(bool(row["effective"]) for row in state["completed"]),
        "budget": state["budget"], "queued": len(state["queue"]),
        "current": state.get("current", {}).get("run_id") if state.get("current") else None,
        "last_verified": last,
        "node": "node1", "minimum_free_bytes": MIN_FREE,
        "max_java_before_launch": MAX_JAVA_BEFORE_LAUNCH,
    })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wall-seconds", type=int, default=24 * 3600)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    state = read_state()
    last = verify_row(state["completed"][-1], state["target"]) if state["completed"] else None
    started = datetime.now(timezone.utc).isoformat()
    snapshot(state, last, started)
    if args.check_only:
        print(json.dumps({"status": state["status"], "completed": len(state["completed"]),
                          "effective": sum(bool(row["effective"]) for row in state["completed"]),
                          "last_verified": last is not None}), flush=True)
        return
    deadline = time.monotonic() + args.wall_seconds
    while state["status"] == "running" and time.monotonic() < deadline:
        if java_count() > MAX_JAVA_BEFORE_LAUNCH or shutil.disk_usage(HERE).free < MIN_FREE:
            time.sleep(args.poll_seconds)
            continue
        before = len(state["completed"])
        subprocess.run([sys.executable, str(HERE / "campaign_v2.py"), "--once", "1"],
                       cwd=HERE, check=True)
        state = read_state()
        if len(state["completed"]) != before + 1:
            raise AssertionError("campaign step did not complete exactly one distinct plan")
        last = verify_row(state["completed"][-1], state["target"])
        snapshot(state, last, started)
        print(json.dumps({"completed": len(state["completed"]),
                          "effective": sum(bool(row["effective"]) for row in state["completed"]),
                          "last": last["run"], "candidate": last["candidate"],
                          "status": state["status"]}), flush=True)
        if last["candidate"]:
            print("candidate requires source review and clean same-plan replay", flush=True)
            return
    if state["status"] == "running":
        print("wall cap reached at complete checkpoint; resume same supervisor", flush=True)
    else:
        print("terminal checkpoint: " + state["status"], flush=True)


if __name__ == "__main__":
    main()
