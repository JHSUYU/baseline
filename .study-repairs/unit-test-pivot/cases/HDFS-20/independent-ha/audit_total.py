#!/usr/bin/env python3
"""Audit HDFS-20's two original-JUnit phase totals and pivot boundary."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time


CASE = Path(__file__).resolve().parent
ROOT = CASE.parent
OOB = ROOT / "independent-coverage-io"
HA = CASE


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    for phase in (OOB, HA):
        subprocess.run([sys.executable,
                        str(phase / "campaign/audit_case.py")], check=True)
    for _ in range(20):
        oob = read(OOB / "campaign/phase-result-oob.json")
        ha = read(HA / "campaign/phase-result.json")
        root = read(ROOT / "result.json")
        os = read(OOB / "campaign/checkpoint.json")
        hs = read(HA / "campaign/checkpoint.json")
        if root["fault_trials"] == len(os["completed"]) + len(hs["completed"]):
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("case total did not agree with phase checkpoints")
    assert oob["fault_trials"] == len(os["completed"]) == 14
    assert ha["fault_trials"] == len(hs["completed"])
    pivot = read(OOB / "campaign/phase-pivot.json")
    assert pivot["completed_oob_trials"] == 14
    assert pivot["aborted_uncompleted_trial"] == 15
    assert pivot["aborted_counted"] is False
    assert root["case_id"] == oob["case_id"] == ha["case_id"] == "HDFS-20"
    for key in ("fault_trials", "requested_fault_events", "matched_fault_events",
                "applied_fault_events", "strict_injection_trials",
                "fully_applied_trials", "post_fault_target_reach_trials",
                "target_exception_after_fault_trials", "workload_timeout_trials",
                "oracle_candidates"):
        assert root[key] == oob.get(key, 0) + ha.get(key, 0), key
    assert root["baseline_trial_budget"] == 14 + hs["budget"]["max_trials"]
    assert root["baseline_max_faults_per_sequence"] == hs["budget"]["max_faults"]
    assert root["elapsed_seconds"] == round(
        oob["elapsed_seconds"] + ha["elapsed_seconds"], 3)
    gains = set()
    for rows in (os["completed"], hs["completed"]):
        for row in rows:
            gains.update(row["new_coverage_ids"])
    for kind in ("METHOD", "BRANCH_UNIT", "PROBE"):
        assert root["coverage_gain"][kind] == sum(
            identifier.startswith(kind + "\t") for identifier in gains)
    assert root["cluster_tests"][0]["trials"] == 14
    assert root["cluster_tests"][1]["trials"] == ha["fault_trials"]
    assert root["runtime_identity"].startswith("RPC API, stable BPOS/actor")
    print(json.dumps({"case_id": "HDFS-20", "oob_trials": 14,
                      "ha_trials": ha["fault_trials"],
                      "total_trials": root["fault_trials"],
                      "all_checks_passed": True}))


if __name__ == "__main__":
    main()
