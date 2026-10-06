#!/usr/bin/env python3
"""Start the isolated TableState I/O audit after the B3 RPC budget finishes."""

from pathlib import Path
import json
import os
import sys
import time


HERE = Path(__file__).resolve().parent
RPC = HERE.parent / "unique"


def rpc_progress() -> tuple[str, int, int]:
    path = RPC / "campaign-state.json"
    if not path.exists():
        return "waiting_for_rpc_state", 0, 80
    state = json.loads(path.read_text())
    maximum = state["max_faults"]
    effective = 0
    for name in state["completed"]:
        checkpoint = RPC / "campaign-checkpoints" / (name + ".json")
        if not checkpoint.exists():
            continue
        row = json.loads(checkpoint.read_text())
        if (0 < row["requested"] <= maximum
                and row["requested"] == row["matched"] == row["applied"]
                and row["target_after_fault"]
                and row["elapsed_seconds"] is not None):
            effective += 1
    return state["stop_reason"], effective, state["budget_total"]


def main() -> None:
    check_only = "--check" in sys.argv
    while True:
        reason, effective, budget = rpc_progress()
        print("RPC_GATE", "reason=" + (reason or "running"),
              "effective=" + str(effective), "budget=" + str(budget), flush=True)
        if check_only:
            return
        if reason:
            if reason != "budget_reached" or effective < budget:
                raise SystemExit("RPC phase stopped short of its authorized budget; review first")
            os.chdir(HERE)
            os.execv(sys.executable, [sys.executable, "-u", str(HERE / "campaign.py")])
        time.sleep(30)


if __name__ == "__main__":
    main()
