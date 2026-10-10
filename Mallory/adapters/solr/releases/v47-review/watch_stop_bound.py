#!/usr/bin/env python3
"""Watch the authorized supplemental bound without changing the live core."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from stop_supplemental import exact_repeat


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--controller-pid", type=int, required=True)
    args = parser.parse_args()
    root = args.campaign.resolve()
    seen_candidates = set()
    while True:
        result = json.loads((root / "result.json").read_text())
        if result["status"] != "running":
            print(json.dumps({"status": "natural_terminal", "result_status": result["status"]}),
                  flush=True)
            return
        effective = sum(bool(row.get("all_faults_effective"))
                        for row in result["trials"][1:])
        reason = None
        witness_trial = None
        for row in result["trials"][1:]:
            trial_id = row["trial_id"]
            if not row.get("target_exception_candidate") or trial_id in seen_candidates:
                continue
            seen_candidates.add(trial_id)
            if exact_repeat(root, trial_id, result):
                reason, witness_trial = "strict_repeat", trial_id
                break
        if reason is None and effective >= 7:
            reason = "effective_cap"
        if reason is not None:
            command = [sys.executable, str(Path(__file__).with_name("stop_supplemental.py")),
                       str(root), "--controller-pid", str(args.controller_pid),
                       "--reason", reason, "--execute"]
            if witness_trial is not None:
                command += ["--witness-trial", str(witness_trial)]
            print(json.dumps({"status": "stop_bound_hit", "reason": reason,
                              "effective_completed": effective,
                              "witness_trial": witness_trial}), flush=True)
            subprocess.run(command, check=True)
            return
        time.sleep(2)


if __name__ == "__main__":
    main()
