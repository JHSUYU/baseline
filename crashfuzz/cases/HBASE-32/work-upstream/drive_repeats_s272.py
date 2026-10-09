#!/usr/bin/env python3
"""Continue bounded s272 replays without repeating a completed original JUnit."""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LOGS = HERE / "logs"
ROLLUP = HERE / "evidence-s272-bounded-repeat-rollup.json"


def summary(index: int) -> dict:
    name = "replay-s272" if index == 1 else f"replay-s272-{index}"
    path = LOGS / f"{name}.summary.json"
    return json.loads(path.read_text())


def save_rollup(results: list[dict], status: str) -> None:
    payload = {"source_trial": "s272", "updated_utc":
               datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "max_total_replays": 6, "stop_after_meta_host_strict_replays": 2,
               "fuzz_budget_admitted": False, "status": status, "runs": results}
    temporary = ROLLUP.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(ROLLUP)


def detail(index: int, result: dict) -> dict:
    if index == 1:
        meta = False  # audited from original replay log and SCP carryingMeta=false
    else:
        meta = result["selected_server_carried_meta_at_fault"]
    return {"index": index, "label": "replay-s272" if index == 1 else
            f"replay-s272-{index}", "exit": result["exit"],
            "elapsed_seconds": result["elapsed_seconds"], "junit": result["junit"],
            "fully_applied": result["fully_applied"],
            "same_actor_b7": result["same_actor_b7"],
            "selected_server_carried_meta": meta,
            "selected_server": (result.get("selected_master_report_server") or
                                result["applied_faults"][0].get("server")),
            "raw_archived_node1": (HERE / f"evidence-s272-repeat{index}-remote-receipt.json")
            .exists() if index > 1 else
            (HERE / "evidence-s272-replay1-remote-receipt.json").exists()}


def main() -> None:
    results = [detail(i, summary(i)) for i in (1, 2)]
    if not results[1]["raw_archived_node1"]:
        raise RuntimeError("Repeat 2 raw has not been mirrored to node1")
    meta_count = sum(r["fully_applied"] and r["selected_server_carried_meta"]
                     for r in results)
    save_rollup(results, "running")
    for index in range(3, 7):
        if meta_count >= 2:
            break
        if any((LOGS / f"replay-s272-{index}{suffix}").exists()
               for suffix in (".log", ".exec", ".summary.json")):
            raise RuntimeError(f"Repeat {index} has output; refusing another JUnit")
        env = os.environ.copy()
        env["HBASE32U_REPLAY_SPEC"] = str(HERE / f"replay-s272-repeat-{index}-plan.json")
        with (LOGS / f"replay-s272-{index}.controller.log").open("w") as stream:
            subprocess.run([sys.executable, str(HERE / "replay_repeat_s272.py")],
                           cwd=HERE, env=env, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        run = summary(index)
        subprocess.run([sys.executable, str(HERE / "audit_lock_trace.py"),
                        str(LOGS / f"replay-s272-{index}.log"),
                        str(LOGS / f"replay-s272-{index}.lock-audit.json")],
                       cwd=HERE, check=True)
        subprocess.run([sys.executable, str(HERE / "archive_repeat_s272.py"),
                        str(index)], cwd=HERE, check=True)
        current = detail(index, run)
        results.append(current)
        if current["fully_applied"] and current["selected_server_carried_meta"]:
            meta_count += 1
        save_rollup(results, "running")
        if (current["exit"] == 124 or not current["fully_applied"]
                or current["junit"] != {"found": 1, "succeeded": 1, "failed": 0}):
            save_rollup(results, "stopped_for_review")
            return
    save_rollup(results, "two_meta_hosts" if meta_count >= 2 else "six_replays")


if __name__ == "__main__":
    main()
