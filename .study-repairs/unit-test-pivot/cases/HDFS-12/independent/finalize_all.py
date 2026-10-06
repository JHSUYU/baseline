#!/usr/bin/env python3
"""Publish HDFS-12 after both original-JUnit campaigns pass raw-event audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
MAIN = HERE / "campaign-state.json"
CONTROL = HERE / "long-lived/control-plane/campaign-state.json"
CONTROL_RESULT = HERE / "long-lived/control-plane/result.json"
AUDIT = HERE / "audit-all.json"
RESULT = CASE / "result.json"
ARCHIVE = CASE / "HDFS-12-independent-evidence.tar.gz"
MANIFEST = CASE / "independent-archive-manifest.json"
KEEP = {"manifest.json", "runtime_trace.jsonl", "jacoco.exec", "junit.log",
        "fault-plan.tsv", "driver.log", "campaign-state.json", "trial-ledger.csv",
        "audit-all.json"}


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def archive_evidence(states: list[dict]) -> dict:
    paths = {AUDIT, MAIN, CONTROL, CASE / "independent-trial-ledger.csv",
             HERE / "long-lived/control-plane/trial-ledger.csv"}
    for state in states:
        for trial in state["completed"]:
            directory = Path(trial["run"])
            paths.update(path for path in directory.iterdir()
                         if path.is_file() and path.name in KEEP)
    for directory in (HERE / "healthy-instrumented-01",
                      HERE / "healthy-instrumented-02",
                      HERE / "long-lived/healthy-01",
                      HERE / "long-lived/control-plane/healthy-01"):
        if directory.is_dir():
            paths.update(path for path in directory.iterdir()
                         if path.is_file() and path.name in KEEP)
    assert all(path.is_file() and path.is_relative_to(CASE) for path in paths)
    temporary = ARCHIVE.with_suffix(ARCHIVE.suffix + ".tmp")
    with tarfile.open(temporary, "w:gz") as output:
        for path in sorted(paths):
            output.add(path, arcname=str(path.relative_to(CASE)), recursive=False)
    temporary.replace(ARCHIVE)
    sha = hashlib.sha256()
    with ARCHIVE.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            sha.update(chunk)
    summary = {"archive": ARCHIVE.name, "sha256": sha.hexdigest(),
               "bytes": ARCHIVE.stat().st_size, "file_count": len(paths),
               "contents": "Original-JUnit healthy and fault trial plans, manifests, traces, logs, raw JaCoCo, checkpoint, audit and ledgers; no cluster scratch data"}
    atomic_json(MANIFEST, summary)
    return summary


def main() -> None:
    main_state = json.loads(MAIN.read_text())
    control_state = json.loads(CONTROL.read_text())
    assert len(main_state["completed"]) == main_state["budget"]["max_trials"] == 128
    assert len(control_state["completed"]) == control_state["budget"]["max_trials"] == 128
    assert not control_state.get("active")
    subprocess.run([sys.executable, str(HERE / "audit_all.py")], check=True)
    audit = json.loads(AUDIT.read_text())
    ordinary = audit["ordinary_sasl"]
    control = audit["long_lived_control"]
    assert ordinary["completed"] == control["completed"] == 128
    assert ordinary["target_retaining"] >= 20 and control["target_retaining"] >= 20
    assert ordinary["target_throw_events"] == control["target_throw_events"] == 0
    assert all(trial["bug_mark"] == "none"
               for state in (main_state, control_state) for trial in state["completed"])
    archive = archive_evidence([main_state, control_state])

    extra = json.loads(CONTROL_RESULT.read_text())
    assert extra["fault_trials"] == 128
    extra["status"] = "quality_complete"
    extra["bug_mark"] = "none"
    extra["audit"] = {"file": "independent/audit-all.json",
                      "strict": control["strict"],
                      "target_retaining": control["target_retaining"],
                      "target_throw_events": 0}
    extra["source_review"] = (
        "The original long-lived-client JUnit rotates block-token keys, then "
        "reads the file and verifies its checksum after the old keys expire. "
        "The selected null-key InvalidToken throw was absent after all exact "
        "target-retaining control-plane I/O faults.")
    atomic_json(CONTROL_RESULT, extra)

    result = json.loads(RESULT.read_text())
    assert result["fault_trials"] in (128, 256)
    if result["fault_trials"] == 128:
        result["fault_trials"] += extra["fault_trials"]
        result["strict_injections"] += extra["strict_injections"]
        result["fully_applied_trials"] += extra["strict_injections"]
        result["target_after_fault"] += extra["target_after_fault"]
        result["elapsed_seconds"] = round(result["elapsed_seconds"] +
                                          extra["elapsed_seconds"], 3)
    result["status"] = "quality_complete"
    result["bug_mark"] = "none"
    result["methodology"] = "coverage_io_case_local_asm_jacoco_two_original_junits"
    result["cluster_test"] = [
        "org.apache.hadoop.hdfs.TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[0]",
        "org.apache.hadoop.hdfs.TestEncryptedTransfer#testLongLivedClient[0]",
    ]
    result["reason"] = (
        "Two original embedded-cluster JUnits completed independent observed-I/O "
        "and coverage-guided campaigns with no selected null-key throw.")
    result["long_lived_control_plane"] = {
        "result": "independent/long-lived/control-plane/result.json",
        "trial_ledger": "independent/long-lived/control-plane/trial-ledger.csv",
        "fault_trials": 128, "strict_injections": control["strict"],
        "target_after_fault": control["target_retaining"],
        "elapsed_seconds": control["elapsed_seconds"],
        "target_exception_after_fault_trials": 0,
        "coverage_gain": extra["coverage_gain"],
    }
    result["raw_event_audit"] = "independent/audit-all.json"
    result["raw_evidence_archive"] = archive
    result["source_review"] = (
        "BlockTokenSecretManager.retrievePassword first rejects expired tokens, "
        "then looks up keyId in allKeys and throws InvalidToken if absent. "
        "The long-lived original test rotates keys and verifies later reads and "
        "checksums. No selected null-key throw followed a strict, target-retaining "
        "fault sequence in either workload. Fault-induced JUnit failures are "
        "recorded separately from this selected throw.")
    atomic_json(RESULT, result)
    print({"fault_trials": result["fault_trials"],
           "strict_injections": result["strict_injections"],
           "target_after_fault": result["target_after_fault"],
           "target_throw_events": 0, "archive_bytes": archive["bytes"]})


if __name__ == "__main__":
    main()
