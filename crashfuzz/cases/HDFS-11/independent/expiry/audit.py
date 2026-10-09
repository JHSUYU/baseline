#!/usr/bin/env python3
"""Audit expired-key trials against the original JUnit's expected retry path."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECK = "BlockTokenSecretManager.retrieveDataEncryptionKey#L552"
THROW = "BlockTokenSecretManager.retrieveDataEncryptionKey#L553"
EXCEPTION = "org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException"


def trace(directory: Path) -> list[dict]:
    return [json.loads(line) for line in (directory / "runtime_trace.jsonl").read_text().splitlines()
            if line]


def audit(trial: dict) -> dict:
    events = trace(Path(trial["run"]))
    checks = [event for event in events
              if event["event"] == "TARGET_CHECK" and event.get("siteId") == CHECK]
    throws = [event for event in events
              if event["event"] == "TARGET_THROW" and event.get("siteId") == THROW
              and event.get("exception") == EXCEPTION]
    after_fault = [event for event in throws
                   if trial["last_applied_seq"] is not None
                   and event["seq"] > trial["last_applied_seq"]]
    # The original test deliberately uses an expired client key, observes one
    # rejection, clears its cached key, and then succeeds with a new key.
    recovery_seen = all(any(check["seq"] > thrown["seq"]
                            and check.get("keyPresent") is True
                            for check in checks) for thrown in throws)
    paired = all(any(check["thread"] == thrown["thread"]
                         and check["seq"] < thrown["seq"]
                         and check.get("keyPresent") is False
                         for check in checks) for thrown in throws)
    valid = trial["exact_order_applied"] and trial["target_after_fault"]
    reasons = []
    if valid and len(throws) > 1:
        reasons.append("more_than_one_selected_exception")
    if valid and throws and not recovery_seen:
        reasons.append("no_successful_key_lookup_after_selected_exception")
    if valid and throws and trial["junit_exit"] != 0:
        reasons.append("original_junit_failed_after_selected_exception")
    if valid and throws and not paired:
        reasons.append("selected_exception_missing_absent_key_check")
    return {
        "id": trial["id"], "run": trial["run"], "valid": valid,
        "junit_exit": trial["junit_exit"],
        "target_checks": len(checks), "target_throws": len(throws),
        "target_throws_after_fault": len(after_fault),
        "key_absent_checks": sum(check.get("keyPresent") is False for check in checks),
        "retry_with_present_key_after_each_throw": recovery_seen,
        "throw_paired_with_absent_key_check": paired,
        "candidate_reasons": reasons,
    }


def main() -> None:
    state = json.loads((HERE / "campaign-state.json").read_text())
    reports = [audit(trial) for trial in state["completed"]]
    summary = {
        "completed": len(reports),
        "valid": sum(report["valid"] for report in reports),
        "candidates": [report for report in reports if report["candidate_reasons"]],
        "trials": reports,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
