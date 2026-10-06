#!/usr/bin/env python3
"""Mirror node2's atomic ZK01 checkpoint into this case's result and ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time


CASE = Path(__file__).resolve().parent
EVIDENCE = CASE / "evidence"
SSH = ["ssh", "-i", str(Path.home() / ".ssh/id_ed25519_nodes"),
       "-o", "IdentitiesOnly=yes", "ZhenyuLi@node2",
       "python3 /users/ZhenyuLi/zk01-unit/status_snapshot.py"]


def atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp." + str(os.getpid()))
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def once() -> tuple[int, bool]:
    command = subprocess.run(SSH, capture_output=True, text=True, timeout=25)
    if command.returncode:
        raise RuntimeError(command.stderr.strip() or "node2 snapshot failed")
    snapshot = json.loads(command.stdout)
    remote = snapshot["result"]
    count = remote["fault_trials"]
    historical = snapshot["legacy"]
    result = {
        **remote,
        "methodology": "coverage_io_discovery_no_graph",
        "original_mapped_test":
            "org.apache.zookeeper.server.quorum.SessionUpgradeQuorumTest#testCloseSessionWhileUpgradeOnLearner",
        "historical_excluded_trials": historical["exact_applied_old_trials"],
        "historical_selector_compatibility": True,
        "historical_result": "cases/ZOOKEEPER-01/evidence/legacy-result.json",
        "new_fault_trials": count,
        "target_check_retained_trials": remote["post_fault_target_reach_trials"],
        "production_new_methods": snapshot["production_new_methods"],
        "production_new_branch_outcomes":
            snapshot["production_new_branch_outcomes"],
        "production_coverage_gain": (snapshot["production_new_methods"] +
                                     snapshot["production_new_branch_outcomes"]),
        "budget_max_trials": snapshot["budget"]["max_trials"],
        "budget_max_faults": snapshot["budget"]["max_faults"],
        "pending_queue": snapshot["pending_queue"],
        "remote_state": "/users/ZhenyuLi/zk01-unit/campaign/results/ZOOKEEPER-01/state.json",
        "trial_ledger": "cases/ZOOKEEPER-01/evidence/new-trial-ledger.json",
        "source_inventory_only": False,
        "updated_at": time.time(),
    }
    atomic(EVIDENCE / "new-trial-ledger.json", {
        "schema_version": 1, "case_id": "ZOOKEEPER-01",
        "methodology": "coverage_io_discovery_no_graph",
        "target_file": remote["target_source_file"],
        "target_line": remote["target_source_line"],
        "target_function": remote["target_method"],
        "target_code": remote["target_code"],
        "trials": snapshot["ledger"],
    })
    atomic(EVIDENCE / "legacy-reassessment.json", historical)
    atomic(CASE / "result.json", result)
    return count, bool(snapshot["finished"])


def main() -> None:
    previous = -1
    while True:
        try:
            count, finished = once()
            if count != previous:
                print(json.dumps({"mirrored_trials": count,
                                  "finished": finished}), flush=True)
                previous = count
            if finished:
                break
        except Exception as error:
            print("snapshot retry: " + str(error), flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
