#!/usr/bin/env python3
"""Recheck pinned all-trial reviews and one raw fault sample per weak HDFS case."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
RECEIPT = ROOT / "Mallory/adapters/hdfs/cases/hdfs-weak-terminal-retrospective-v1.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if digest(data) != expected:
        raise ValueError(f"SHA mismatch: {path}")
    return data


def verify() -> int:
    receipt = json.loads(RECEIPT.read_text())
    cases = receipt["case_evidence"]
    if (receipt["schema_version"] != 1 or len(cases) != 21 or
            receipt["prior_all_trial_review_categories"] !=
            {"faulted_path_v1": 14, "causal_precision_v2": 7}):
        raise ValueError("wrong retrospective case inventory")
    for case_id, row in cases.items():
        root = ROOT / "data/mallory/cases" / case_id
        result = json.loads(checked(root / "result.json", row["result_sha256"]))
        checked(root / "offline-causal-audit.json", row["audit_sha256"])
        if (result["case_id"] != case_id or
                result["fault_trials_completed"] != row["fault_trials_completed"] or
                result["strict_target_trials"] != row["strict_target_trials"]):
            raise ValueError(f"campaign summary changed: {case_id}")
        prior = row["prior_all_trial_review"]
        review = json.loads(checked(ROOT / prior["path"], prior["sha256"]))
        if review["case_id"] != case_id:
            raise ValueError(f"prior review identity changed: {case_id}")
        if prior["kind"] == "historical_faulted_run_precision_read_only":
            if (review["classification"] != "faulted_path_unverified" or
                    any(review[key] != 0 for key in
                        ("same_region_continuation_trials",
                         "root_free_occurrence_path_trials",
                         "ordered_root_free_region_path_trials"))):
                raise ValueError(f"prior root-free finding changed: {case_id}")
        elif prior["kind"] == "causal_precision_v2":
            if (review["classification"] != "causal_precision_unverified" or
                    review.get("root_free_qualifying_trial_ids") != [] or
                    review.get("faulted_applied_in_target_closure_trial_ids", []) != []):
                raise ValueError(f"prior closure finding changed: {case_id}")
        else:
            raise ValueError(f"unknown review kind: {case_id}")
        sample = row["sample_effective_target_trial"]
        trial_dir = root / "trials" / f"r{sample['trial_id']:04d}"
        trial = json.loads(checked(trial_dir / "result.json",
                                   sample["trial_result_sha256"]))
        if (trial["feedback"]["all_faults_effective"] is not True or
                trial["feedback"]["target_reached"] is not True):
            raise ValueError(f"sample is not an effective target trial: {case_id}")
        packed = checked(trial_dir / "events.jsonl.gz", sample["trace_gzip_sha256"])
        raw = gzip.decompress(packed)
        if (digest(raw) != sample["trace_raw_sha256"] or
                digest(raw) != trial["events_evidence"]["raw_sha256"]):
            raise ValueError(f"raw trace changed: {case_id}")
        events = [json.loads(line) for line in raw.splitlines() if line]
        faults = [event for event in events if event.get("type") == "FAULT_APPLIED"]
        checks = [event for event in events if event.get("type") == "TARGET_CHECK"]
        numeric = lambda event: isinstance(event.get("thread_id"), int) and not isinstance(
            event.get("thread_id"), bool)
        if (len(faults) != sample["applied_fault_events"] or
                len(checks) != sample["target_check_events"] or
                sum(map(numeric, faults)) != sample["numeric_thread_applied_fault_events"] or
                sum(map(numeric, checks)) != sample["numeric_thread_target_check_events"] or
                any(map(numeric, faults + checks))):
            raise ValueError(f"numeric thread evidence changed: {case_id}")
    return len(cases)


if __name__ == "__main__":
    print(f"verified {verify()} weak HDFS campaigns")
