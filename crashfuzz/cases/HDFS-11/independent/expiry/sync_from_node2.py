#!/usr/bin/env python3
"""Mirror the node2 expired-key campaign without duplicating completed trials."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
CASE = HERE.parent.parent
REMOTE = "ZhenyuLi@node2:/users/ZhenyuLi/baseline/crashfuzz/cases/HDFS-11/independent/expiry"
SSH = "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes"
RSYNC = ["rsync", "-a", "-e", SSH]


def sync_once() -> dict:
    snapshot = HERE / "campaign-state.node2.snapshot"
    subprocess.run([*RSYNC, REMOTE + "/campaign-state.json", str(snapshot)],
                   check=True, stdout=subprocess.DEVNULL)
    state = json.loads(snapshot.read_text())
    # Fetch trial evidence before publishing a checkpoint that names it.
    (HERE / "runs").mkdir(exist_ok=True)
    subprocess.run([*RSYNC, "--exclude=scratch/", "--exclude=*.tmp",
                    REMOTE + "/runs/", str(HERE / "runs/")],
                   check=True, stdout=subprocess.DEVNULL)
    for trial in state["completed"]:
        run = Path(trial["run"])
        if not (run / "manifest.json").is_file() or not (run / "runtime_trace.jsonl").is_file():
            raise RuntimeError("checkpoint references missing trial evidence: " + str(run))
    os.replace(snapshot, HERE / "campaign-state.json")
    # Derive the case result and row ledger from exactly the mirrored state.
    import campaign
    campaign.write_result(state)
    subprocess.run(["python3", str(HERE.parents[3] / "checklist.py"), "render"],
                   check=True, stdout=subprocess.DEVNULL)
    return {"completed": len(state["completed"]),
            "active": state["active"]["id"] if state["active"] else None,
            "budget": state["budget"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=30)
    args = parser.parse_args()
    with (HERE / "campaign.lock").open("a+") as lock:
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
