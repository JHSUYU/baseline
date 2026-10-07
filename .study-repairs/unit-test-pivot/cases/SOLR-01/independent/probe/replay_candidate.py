#!/usr/bin/env python3
"""Replay one exact selected-throw candidate from the saved checkpoint."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


WORK = Path(__file__).resolve().parents[1]
STATE = WORK / "evidence/campaign/state.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trial", type=int, help="Candidate trial number; default first")
    args = parser.parse_args()
    state = json.loads(STATE.read_text())
    candidates = [trial for trial in state["trials"]
                  if trial["all_faults_applied"] and
                  trial["target_after_fault"] and
                  trial["target_exception"]]
    if not candidates:
        raise RuntimeError("No exact selected-throw candidate in checkpoint")
    trial = next((item for item in candidates if item["number"] == args.trial), None)
    if trial is None:
        if args.trial is not None:
            raise ValueError(f"Trial {args.trial} is not an exact target-throw candidate")
        trial = candidates[0]
    output = WORK / "evidence" / f"replay-trial-{trial['number']:03d}"
    command = [sys.executable, str(WORK / "probe/run.py"), str(output),
               "--coverage", "--faults", ";".join(trial["plan"]),
               "--timeout", "180"]
    subprocess.run(command, check=False)


if __name__ == "__main__":
    main()
