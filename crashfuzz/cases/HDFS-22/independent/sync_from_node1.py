#!/usr/bin/env python3
"""Pull one isolated node1 campaign's atomic checkpoints into node0 checklist rows."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent
REMOTE = "ZhenyuLi@node1:"
SSH = "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes"
RSYNC = ["rsync", "-a", "-e", SSH]
CASES = (22, 23, 25, 34, 35)
REMOTE_HERE = "/users/ZhenyuLi/baseline/crashfuzz/cases/HDFS-22/independent"


def pull(source: str, destination: Path, *options: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([*RSYNC, *options, REMOTE + source, str(destination)], check=True,
                   stdout=subprocess.DEVNULL)


def sync_once() -> dict:
    evidence = HERE / "evidence"
    # Keep runnable traces, plans, JaCoCo bytes, coverage sets and JUnit logs.
    # Cluster scratch trees are recreated for every trial and are not feedback.
    pull(REMOTE_HERE + "/evidence/runs/", evidence / "runs/",
         "--exclude=scratch/", "--exclude=*.tmp")
    pull(REMOTE_HERE + "/evidence/campaign-state.json", evidence / "campaign-state.json")
    counts = {}
    for number in CASES:
        case = BASE / ("HDFS-" + str(number))
        result = case / "result.json"
        pull(str(case / "result.json"), result)
        data = json.loads(result.read_text())
        counts[data["case_id"]] = {"trials": data["fault_trials"],
                                   "exact": data["strict_injections"],
                                   "post_fault_target": data["target_after_fault"],
                                   "status": data["status"]}
    status = {"source": "node1", "destination": "node0",
              "synced_at_utc": datetime.now(timezone.utc).isoformat(),
              "cases": counts}
    temporary = evidence / "node1-sync-status.json.tmp"
    temporary.write_text(json.dumps(status, indent=2) + "\n")
    temporary.replace(evidence / "node1-sync-status.json")
    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=20)
    args = parser.parse_args()
    last = None
    while True:
        try:
            status = sync_once()
            count = status["cases"]["HDFS-22"]["trials"]
            if count != last:
                print(json.dumps(status), flush=True)
                last = count
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            print("node1 sync retry: " + str(error), flush=True)
            if args.once:
                raise
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
