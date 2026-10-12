#!/usr/bin/env python3
"""Bounded fresh healthy seeds to locate a later same-reader watcher read."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from admit_healthy import admit


BASE = Path("/users/ZhenyuLi/baseline")
HERE = Path(__file__).resolve().parent
CORE = BASE / ("Mallory/dispatch/releases/"
               "4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4")
CONFIG = HERE / "config-v48-healthy-node2.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--max-seeds", type=int, default=3)
    parser.add_argument("--min-ordinal", type=int, default=4)
    args = parser.parse_args()
    if args.max_seeds < 1 or args.max_seeds > 5 or args.min_ordinal < 1:
        raise ValueError("bounded seed count and positive ordinal required")
    if args.out_root.exists():
        raise ValueError("output root must be fresh")
    args.out_root.mkdir(parents=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CORE) + ":" + str(BASE)
    lock_path = Path("/users/ZhenyuLi/.mallory-worktrees/solr31-v48-node2.lock")
    with lock_path.open("w") as lane:
        fcntl.flock(lane, fcntl.LOCK_EX)
        for number in range(1, args.max_seeds + 1):
            case_out = args.out_root / f"seed-{number:02d}" / "SOLR-31"
            case_out.parent.mkdir()
            command = [sys.executable, "-m", "Mallory.core.campaign",
                       "--config", str(CONFIG), "--out", str(case_out),
                       "--calibration-only"]
            with (case_out.parent / "controller.log").open("w") as log:
                result = subprocess.run(command, cwd=BASE, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=500, check=False)
            if result.returncode:
                print(json.dumps({"seed": number, "controller_return_code": result.returncode}),
                      flush=True)
                continue
            try:
                receipt = admit(case_out / "trials/r0000")
            except (ValueError, FileNotFoundError) as failure:
                print(json.dumps({"seed": number, "gate": "invalid", "reason": str(failure)}),
                      flush=True)
                continue
            (case_out / "healthy-receipt.json").write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n")
            binding = receipt["binding"]
            print(json.dumps({"seed": number, "gate": "passed",
                              "node": binding["node"],
                              "watch_read_ordinal": binding["watch_read_ordinal"],
                              "healthy_stat_version": binding["healthy_stat_version"],
                              "target_version": binding["target_version"],
                              "target_leader": binding["target_leader"]}), flush=True)
            if binding["watch_read_ordinal"] >= args.min_ordinal:
                break


if __name__ == "__main__":
    main()
