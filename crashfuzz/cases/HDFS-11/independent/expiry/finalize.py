#!/usr/bin/env python3
"""Publish HDFS-11 only after the original-test oracle and trace audit pass."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE.parent.parent


def atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> None:
    state = json.loads((HERE / "campaign-state.json").read_text())
    audit = json.loads((HERE / "audit-result.json").read_text())
    trials = state["completed"]
    valid = [trial for trial in trials if trial["valid_for_feedback"]]
    assert len(trials) == state["budget"]["max_trials"] == audit["completed"] == 128
    assert len(valid) == audit["valid"] == 46
    assert not audit["candidates"]
    assert all(trial["junit_exit"] == 0 for trial in valid)
    assert all(trial["total_target_exceptions"] == 1 for trial in valid)
    assert all(report["retry_with_present_key_after_each_throw"]
               and report["throw_paired_with_absent_key_check"]
               for report in audit["trials"] if report["valid"])

    expiry = json.loads((CASE / "expiry-result.json").read_text())
    assert expiry["fault_trials"] == 128 and expiry["bug_mark"] == "none"
    expiry["status"] = "quality_complete"
    expiry["audit"] = {
        "completed": 128, "strict": sum(trial["exact_order_applied"] for trial in trials),
        "valid_target_retaining": len(valid), "source_review_candidates": 0,
        "file": "independent/expiry/audit-result.json",
        "expected_exception_per_successful_run": 1,
    }
    expiry["source_review"] = (
        "The original TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey "
        "waits for the old key to expire, expects one InvalidEncryptionKeyException, "
        "clears the client's cached key, then retries the checksum successfully. "
        "All 46 strict target-retaining fault runs followed this same pattern."
    )
    atomic(CASE / "expiry-result.json", expiry)

    primary = json.loads((CASE / "result.json").read_text())
    if primary["status"] == "quality_complete":
        assert primary["fault_trials"] == 208
        return
    assert primary["fault_trials"] == 80 and primary["bug_mark"] == "none"
    primary["status"] = "quality_complete"
    primary["reason"] = "Two original embedded-cluster JUnit workloads completed with independent runtime I/O and JaCoCo feedback."
    primary["methodology"] = "coverage_io_case_local_asm_jacoco_two_original_junits"
    primary["cluster_test"] = [
        "org.apache.hadoop.hdfs.TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]",
        "org.apache.hadoop.hdfs.TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey[0]",
    ]
    primary["fault_trials"] += expiry["fault_trials"]
    primary["strict_injections"] += expiry["strict_injections"]
    primary["fully_applied_trials"] += expiry["strict_injections"]
    primary["target_after_fault"] += expiry["target_after_fault"]
    primary["elapsed_seconds"] = round(primary["elapsed_seconds"] + expiry["elapsed_seconds"], 3)
    primary["expired_key_supplement"] = {
        "result": "expiry-result.json", "trial_ledger": "expiry-trial-ledger.csv",
        "audit": "independent/expiry/audit-result.json", "fault_trials": 128,
        "strict_injections": expiry["strict_injections"],
        "target_after_fault": expiry["target_after_fault"],
        "elapsed_seconds": expiry["elapsed_seconds"],
        "expected_target_exception_per_successful_run": 1,
        "unexpected_target_exception_candidates": 0,
    }
    primary["source_review"] = expiry["source_review"]
    atomic(CASE / "result.json", primary)


if __name__ == "__main__":
    main()
