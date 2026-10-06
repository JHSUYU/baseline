#!/usr/bin/env python3
"""Export compact trial timing and outcome evidence from the node2 checkpoint."""

from __future__ import annotations

import collections
import csv
import json
import os
from pathlib import Path

CASE = Path("/users/ZhenyuLi/zk03-case/campaign/ZOOKEEPER-03")
OUT = Path("/users/ZhenyuLi/zk03-case/export")
VALID = {"checked", "target_exception_candidate",
         "baseline_exception_recurrence"}


def atomic_json(path: Path, value: object) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    state = json.loads((CASE / "state.json").read_text())
    result = json.loads((CASE / "result.json").read_text())
    files = sorted((CASE / "trials").glob("*/result.json"))
    admitted = set(state["seed"]["feedback"]["coverage"])
    ledger = []
    for file in files:
        trial = json.loads(file.read_text())
        fault_plan = json.loads((file.parent / "fault-trial.json").read_text())
        attempts = [json.loads(path.read_text()) for path in
                    sorted(file.parent.glob("attempt-*/result.json"))]
        new = (set(trial.get("coverage", [])) - admitted
               if trial.get("status") in VALID else set())
        if trial.get("status") in VALID:
            admitted.update(trial.get("coverage", []))
        ledger.append({
            "trial": int(file.parent.name.split("-", 1)[0]),
            "status": trial.get("status"),
            "fault_count": trial.get("fault_count"),
            "fault_markers": ";".join(f["marker"] for f in fault_plan["faults"]),
            "fault_ids": ";".join(f["faultId"] for f in fault_plan["faults"]),
            "strict_injection": bool(trial.get("strict_injection")),
            "applied_count": trial.get("applied_count", 0),
            "target_after_fault": bool(trial.get("target_reached_after_fault")),
            "target_branch_outcomes_after_fault": ";".join(
                str(v) for v in trial.get("target_outcomes_after_fault", [])),
            "target_exception": bool(trial.get("oracle")),
            "new_methods": sum(x.startswith("METHOD:") for x in new),
            "new_branch_outcomes": sum(x.startswith("BRANCH:") for x in new),
            "new_call_site_ids": sum(x.startswith("CALL_SITE:") for x in new),
            "junit_exit": trial.get("exit"),
            "attempt_count": len(attempts),
            "elapsed_seconds": round(sum(float(a.get("elapsed_seconds", 0))
                                         for a in attempts), 3),
            "last_attempt_seconds": trial.get("elapsed_seconds"),
        })
    path = OUT / "trial-ledger.csv"
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(ledger[0]) if ledger else [],
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(ledger)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    summary = {
        "case_id": "ZOOKEEPER-03",
        "trial_count": len(ledger),
        "status_counts": dict(collections.Counter(r["status"] for r in ledger)),
        "depth_counts": dict(collections.Counter(str(r["fault_count"]) for r in ledger)),
        "strict_injections": sum(r["strict_injection"] for r in ledger),
        "post_fault_target_reaches": sum(r["target_after_fault"] for r in ledger),
        "exact_target_exception_candidates": sum(r["target_exception"] for r in ledger),
        "fault_trial_seconds": round(sum(float(r["elapsed_seconds"] or 0)
                                           for r in ledger), 3),
        "campaign_result": result,
        "checkpoint_finished": state.get("finished"),
        "checkpoint_queue_length": len(state["queue"]),
        "checkpoint_active": state["active"] is not None,
        "extension_reason": state.get("extension_reason"),
    }
    atomic_json(OUT / "campaign-summary.json", summary)


if __name__ == "__main__":
    main()
