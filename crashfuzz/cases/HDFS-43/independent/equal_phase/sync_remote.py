#!/usr/bin/env python3
"""Pull atomic campaign checkpoints/results from an isolated remote node."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent.parent
SSH = "ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes"
RSYNC = ["rsync", "-a", "-e", SSH]
ROOT = "/users/ZhenyuLi/baseline/crashfuzz/cases"
GROUPS = {"equal43": (43,)}


def pull(node: str, source: str, destination: Path, *options: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([*RSYNC, *options, f"ZhenyuLi@{node}:{source}", str(destination)],
                   check=True, stdout=subprocess.DEVNULL)


def sync_once(node: str, group: str, include_runs: bool) -> dict:
    anchor = GROUPS[group][0]
    remote = f"{ROOT}/HDFS-{anchor}/independent/equal_phase/evidence"
    local = BASE / f"HDFS-{anchor}/independent/equal_phase/evidence"
    pull(node, remote + "/campaign-state.json", local / "campaign-state.json")
    if include_runs:
        pull(node, remote + "/runs/", local / "runs/",
             "--exclude=scratch/", "--exclude=covered_*.txt", "--exclude=*.tmp")
    counts = {}
    for number in GROUPS[group]:
        case = BASE / f"HDFS-{number}"
        result = case / "independent/equal_phase/equal-result.json"
        pull(node, f"{ROOT}/HDFS-{number}/independent/equal_phase/equal-result.json", result)
        data = json.loads(result.read_text())
        counts[data["case_id"]] = {
            "trials": data["fault_trials"], "exact": data["strict_injections"],
            "post_fault_target": data["target_after_fault"], "status": data["status"]}
        pull(node, f"{ROOT}/HDFS-{number}/independent/equal_phase/evidence/healthy/",
             case / "independent/equal_phase/evidence/healthy/")
    report = {"source": node, "destination": "node0",
              "synced_at_utc": datetime.now(timezone.utc).isoformat(),
              "cases": counts}
    path = local / f"{node}-sync-status.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, indent=2) + "\n")
    temp.replace(path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", choices=("node1", "node2"), required=True)
    parser.add_argument("--group", choices=GROUPS, required=True)
    parser.add_argument("--interval", type=float, default=20)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--include-runs", action="store_true")
    args = parser.parse_args()
    previous = None
    while True:
        try:
            report = sync_once(args.node, args.group, args.include_runs)
            counts = tuple((v["trials"], v["exact"], v["post_fault_target"])
                           for v in report["cases"].values())
            if counts != previous:
                print(json.dumps(report), flush=True)
                previous = counts
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
            print("sync retry: " + str(error), flush=True)
            if args.once:
                raise
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
