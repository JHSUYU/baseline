#!/usr/bin/env python3
"""Pin every raw trace and the terminal ZOOKEEPER-06 campaign outcome."""

import gzip
import hashlib
import json
from pathlib import Path


CASE = Path("/users/ZhenyuLi/baseline/data/mallory/cases/ZOOKEEPER-06")
HEALTHY = Path("/users/ZhenyuLi/baseline/data/mallory/admissions/ZOOKEEPER-06-ackepoch-retry-door-node0-healthy-v1.json")
TERMINAL = {"budget_exhausted", "queue_exhausted"}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def raw_sha(path):
    h = hashlib.sha256()
    with gzip.open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    receipt_path = CASE / "collection-receipt.json"
    if receipt_path.exists():
        raise FileExistsError(receipt_path)
    config, result, checkpoint, audit = (load(CASE / name) for name in
                                         ("config.json", "result.json", "checkpoint.json", "offline-causal-audit.json"))
    assert config["case_id"] == result["case_id"] == checkpoint["case_id"] == audit["case_id"] == "ZOOKEEPER-06"
    assert result["status"] == checkpoint["status"] in TERMINAL
    assert result["fault_trials_completed"] <= 80
    assert config["budget"]["trials"] == 80
    assert config["budget"]["seconds"] == 3600
    assert config["budget"]["max_faults_per_trial"] == 3
    assert result["healthy_junit_validation"]["status"] == "passed"
    assert result["runtime_attestation"]["valid"] is True
    assert result["runtime_attestation"]["observed_target_class_sha256"] == config["expected_target_class_sha256"]
    assert audit["campaign_result_sha256"] == sha(CASE / "result.json")
    assert sha(HEALTHY) == config["healthy_receipt_sha256"]
    trials = []
    for row in result["trials"]:
        trial_id = row["trial_id"]
        directory = CASE / "trials" / f"r{trial_id:04d}"
        trial = load(directory / "result.json")
        evidence = trial["events_evidence"]
        trace = directory / "events.jsonl.gz"
        assert trial["trial_id"] == trial_id
        assert sha(trace) == evidence["gzip_sha256"]
        assert raw_sha(trace) == evidence["raw_sha256"]
        assert row["result"] == str((directory / "result.json").relative_to(CASE))
        trials.append({
            "trial_id": trial_id,
            "result_sha256": sha(directory / "result.json"),
            "plan_sha256": sha(directory / "plan.json"),
            "junit_receipt_sha256": sha(directory / "junit-receipt.json"),
            "trace_gzip_sha256": evidence["gzip_sha256"],
            "trace_raw_sha256": evidence["raw_sha256"],
            "junit_status": trial["junit_validation"]["status"],
            "all_faults_effective": trial["feedback"].get("all_faults_effective"),
            "target_reached": trial["feedback"].get("target_reached"),
            "target_exception_candidate": trial["feedback"].get("target_exception_candidate"),
        })
    assert len(trials) == result["fault_trials_completed"] + 1
    assert [row["trial_id"] for row in trials] == list(range(len(trials)))
    assert result["strict_injected_trials"] == sum(row["all_faults_effective"] is True for row in trials[1:])
    assert result["target_reached_trials"] == sum(row["target_reached"] is True for row in trials[1:])
    assert result["exact_exception_trials"] == sum(row["target_exception_candidate"] is True for row in trials[1:])
    receipt = {
        "schema_version": 1,
        "case_id": "ZOOKEEPER-06",
        "terminal_status": result["status"],
        "completion_rule": "budget_exhausted_or_queue_exhausted",
        "cluster_test": config["cluster_test"],
        "budget": config["budget"],
        "duration_seconds": result["duration_seconds"],
        "fault_trials_completed": result["fault_trials_completed"],
        "strict_injected_trials": result["strict_injected_trials"],
        "target_reached_trials": result["target_reached_trials"],
        "exact_exception_trials": result["exact_exception_trials"],
        "new_bug": None,
        "source_review_status": "not_reviewed",
        "expected_target_class_sha256": config["expected_target_class_sha256"],
        "observed_target_class_sha256": result["runtime_attestation"]["observed_target_class_sha256"],
        "selected_check_site": config["target"]["check_sites"][0],
        "selected_throw_site": config["target"]["throw_site"],
        "config_sha256": sha(CASE / "config.json"),
        "result_sha256": sha(CASE / "result.json"),
        "checkpoint_sha256": sha(CASE / "checkpoint.json"),
        "offline_audit_sha256": sha(CASE / "offline-causal-audit.json"),
        "healthy_receipt_sha256": sha(HEALTHY),
        "trials": trials,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print("terminal", result["status"], "fault_trials", result["fault_trials_completed"],
          "receipt_sha256", sha(receipt_path))


if __name__ == "__main__":
    main()
