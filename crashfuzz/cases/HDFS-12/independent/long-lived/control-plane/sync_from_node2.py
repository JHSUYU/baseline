#!/usr/bin/env python3
"""Mirror the node2 HDFS-12 key-delivery campaign into the 102-case table."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parents[2]
REMOTE = "ZhenyuLi@node2:" + str(HERE)
SSH = "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes"
RSYNC = ["rsync", "-a", "-e", SSH]


def sync_once() -> dict:
    state_snapshot = HERE / "campaign-state.node2.snapshot"
    result_snapshot = HERE / "result.node2.snapshot"
    subprocess.run([*RSYNC, REMOTE + "/campaign-state.json", str(state_snapshot)],
                   check=True, stdout=subprocess.DEVNULL)
    state = json.loads(state_snapshot.read_text())
    for name in ("healthy-01", "smoke-heartbeat", "smoke-keyupdate", "runs"):
        (HERE / name).mkdir(exist_ok=True)
        subprocess.run([*RSYNC, "--exclude=scratch/", "--exclude=*.tmp",
                        REMOTE + "/" + name + "/", str(HERE / name) + "/"],
                       check=True, stdout=subprocess.DEVNULL)
    for trial in state["completed"]:
        run = Path(trial["run"])
        if not (run / "manifest.json").is_file() or not (run / "runtime_trace.jsonl").is_file():
            raise RuntimeError("checkpoint names missing evidence: " + str(run))
    subprocess.run([*RSYNC, REMOTE + "/result.json", str(result_snapshot)],
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run([*RSYNC, REMOTE + "/trial-ledger.csv", str(HERE / "trial-ledger.csv")],
                   check=True, stdout=subprocess.DEVNULL)
    remote_result = json.loads(result_snapshot.read_text())
    os.replace(state_snapshot, HERE / "campaign-state.json")
    os.replace(result_snapshot, HERE / "result.json")
    case_result_path = CASE / "result.json"
    case_result = json.loads(case_result_path.read_text())
    case_result["long_lived_control_plane"] = {
        "cluster_test": remote_result["cluster_test"],
        "status": remote_result["status"],
        "fault_trials": remote_result["fault_trials"],
        "strict_injections": remote_result["strict_injections"],
        "target_after_fault": remote_result["target_after_fault"],
        "target_exception_after_fault_trials":
            remote_result["target_exception_after_fault_trials"],
        "budget": remote_result["independent_campaign"]["budget"],
        "elapsed_seconds": remote_result["elapsed_seconds"],
        "result": str(HERE / "result.json"),
        "trial_ledger": str(HERE / "trial-ledger.csv"),
    }
    if remote_result["bug_mark"] != "none":
        case_result["bug_mark"] = remote_result["bug_mark"]
    if remote_result["status"] == "running":
        case_result["status"] = "running_supplemental"
    temp = case_result_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(case_result, indent=2, sort_keys=True) + "\n")
    os.replace(temp, case_result_path)
    subprocess.run(["python3", str(CASE.parent.parent / "checklist.py"), "render"],
                   check=True, stdout=subprocess.DEVNULL)
    return {"completed": len(state["completed"]),
            "strict": remote_result["strict_injections"],
            "target_after_fault": remote_result["target_after_fault"],
            "active": state["active"]["id"] if state["active"] else None,
            "budget": state["budget"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=30.0)
    args = parser.parse_args()
    with (HERE / "sync.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        last = None
        while True:
            try:
                status = sync_once()
                if status["completed"] != last:
                    print(json.dumps(status), flush=True)
                    last = status["completed"]
            except (OSError, subprocess.CalledProcessError, json.JSONDecodeError,
                    RuntimeError) as error:
                print("node2 sync retry: " + str(error), flush=True)
                if args.once:
                    raise
            if args.once:
                return
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
