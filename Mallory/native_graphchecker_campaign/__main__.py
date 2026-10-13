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
    args = parser.parse_args()
    state = run_campaign(args.config, args.output)
    print(json.dumps({"case_id": state["case_id"], "status": state["status"],
                      "completed_fault_trials": state["completed_fault_trials"],
                      "elapsed_seconds": state["elapsed_seconds"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
