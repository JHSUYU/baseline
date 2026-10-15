"""Run one isolated native GraphChecker campaign from a JSON manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .campaign import run_campaign


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--stop-after-fault-trials", type=int,
                        help="pause at this absolute completed-fault-trial count; 0 records only the healthy seed")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--admit-only", action="store_true",
                      help="validate and cache recording admission without running the JUnit workload")
    mode.add_argument("--import-only", action="store_true",
                        help="validate and seal a predecessor import without running the JUnit or fault workload")
    args = parser.parse_args()
    state = run_campaign(args.config, args.output, args.stop_after_fault_trials,
                         import_only=args.import_only,
                         admit_only=args.admit_only)
    print(json.dumps({"case_id": state["case_id"], "status": state["status"],
                      "completed_fault_trials": state["completed_fault_trials"],
                      "imported_completed_fault_trials": state.get(
                          "imported_completed_fault_trials", 0),
                      "elapsed_seconds": state["elapsed_seconds"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
