#!/usr/bin/env python3
"""Summarize the bounded pre-COMMITTED selection pivot from saved trials."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "checkpoint.json"
OUT = HERE / "precommitted-phase-report.json"


def summarize(rows: list[dict]) -> dict:
    admitted = [row for row in rows if row["strict_injection"] and
                row["target_guard_after_last_fault"]]
    return {
        "attempted_trials": len(rows),
        "strict_injection_trials": sum(row["strict_injection"] for row in rows),
        "effective_post_fault_target_trials": len(admitted),
        "committed_true_branch_after_fault_trials": sum(
            "COMMITTED" in row["target_states_after_fault"] for row in admitted),
        "exact_target_exception_after_fault_trials": sum(
            row["target_exception_after_fault_count"] > 0 for row in admitted),
        "new_production_method_ids": sum(
            identifier.startswith("METHOD\t") for row in admitted
            for identifier in row["new_coverage_ids"]),
        "new_production_branch_ids": sum(
            identifier.startswith("BRANCH_UNIT\t") for row in admitted
            for identifier in row["new_coverage_ids"]),
    }


def main() -> None:
    state = json.loads(STATE.read_text())
    phase = state["pre_committed_phase"]
    before_end = phase["after_reserved_trial"]
    phase_end = before_end + phase["selected_attempts"]
    rows = state["completed"]
    before = [row for row in rows if row["number"] <= before_end]
    during = [row for row in rows if before_end < row["number"] <= phase_end]
    after = [row for row in rows if row["number"] > phase_end]
    assert len(during) <= phase["selected_attempts"]
    assert all("bounded pre-COMMITTED observed-I/O stratum" in
               row["selection_reason"] for row in during)
    report = {
        "case_id": "HDFS-39",
        "healthy_first_committed_guard_seq": phase["healthy_first_committed_guard_seq"],
        "first_stratum_trial": before_end + 1,
        "selected_stratum_attempts": phase["selected_attempts"],
        "stratum_attempt_limit": phase["max_selected_attempts"],
        "prior_policy_and_already_reserved": summarize(before),
        "pre_committed_stratum": summarize(during),
        "subsequent_policy": summarize(after),
        "whole_campaign": summarize(rows),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    temp = OUT.with_name(OUT.name + f".tmp.{os.getpid()}")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    os.replace(temp, OUT)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
