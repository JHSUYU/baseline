#!/usr/bin/env python3
"""Read-only terminal count receipt for one HDFS-31/32 full campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


TERMINAL = {"budget_exhausted", "queue_exhausted"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("HDFS-31", "HDFS-32"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = json.loads((args.out / "result.json").read_text())
    checkpoint = json.loads((args.out / "checkpoint.json").read_text())
    rows = result.get("trials", [])
    fault_ids = [row["trial_id"] for row in rows if row.get("trial_id", 0) > 0]
    completed = checkpoint.get("completed_trials", [])
    if (result.get("case_id") != args.case or checkpoint.get("case_id") != args.case or
            fault_ids != [trial for trial in completed if trial > 0] or
            result.get("fault_trials_completed") != len(fault_ids)):
        raise SystemExit("result/checkpoint trial count mismatch")
    status = result.get("status")
    receipt = {
        "case_id": args.case,
        "status": status,
        "terminal_complete": status in TERMINAL,
        "fault_trials_completed": len(fault_ids),
        "strict_injected_trials": result.get("strict_injected_trials"),
        "strict_target_trials": result.get("strict_target_trials"),
        "target_exception_trials": result.get("exact_exception_trials"),
        "queue_remaining": len(checkpoint.get("queue", [])),
        "duration_seconds": result.get("duration_seconds"),
        "completion_rule": "budget_exhausted or queue_exhausted; graph and target retention are outcomes"
    }
    print(json.dumps(receipt, sort_keys=True))
    if status not in TERMINAL:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
