#!/usr/bin/env python3
"""Audit the stopped HDFS-52 original-JUnit trials and preserve raw evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tarfile

import campaign

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
STATE = HERE / "evidence/campaign-state.json"
AUDIT = HERE / "evidence/source-exclusion-audit.json"
ARCHIVE = CASE / "HDFS-52-independent-evidence.tar.gz"
INDEX = CASE / "independent-archive-manifest.json"
RESULT = CASE / "result.json"


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> None:
    state = json.loads(STATE.read_text())
    assert len(state["completed"]) >= 20
    audited = []
    archive_files = {STATE, HERE / "trial-ledger.csv"}
    healthy = HERE / "evidence/instrumented-healthy-01"
    archive_files.update(path for path in healthy.iterdir() if path.is_file())
    for trial in state["completed"]:
        directory = CASE / trial["run_dir"]
        manifest = json.loads((directory / "manifest.json").read_text())
        rows = campaign.events(directory / "runtime_trace.tsv")
        matched = [row for row in rows if row[1] == "FAULT_MATCHED"]
        applied = [row for row in rows if row[1] == "FAULT_APPLIED"]
        actual = ["|".join((*row[2][:3], row[2][4])) for row in applied]
        exact = actual == trial["plan"] and len(matched) == len(trial["plan"])
        last_fault = applied[-1][0] if exact else 0
        target = campaign.first_target(rows, last_fault) if exact else None
        false = [row for row in rows if row[1] == "TARGET_FALSE"
                 and row[0] > last_fault
                 and (int(row[2][2]) > 0 or int(row[2][3]) > 0)] if target else []
        assert exact == trial["exact_order_applied"], trial["trial"]
        assert (target is not None) == trial["target_after_fault"], trial["trial"]
        assert len(false) == trial["selected_target_throw"], trial["trial"]
        assert len(matched) == trial["matched_faults"], trial["trial"]
        assert len(applied) == trial["applied_faults"], trial["trial"]
        assert manifest["returncode"] == trial["junit_exit"], trial["trial"]
        assert manifest["elapsed_seconds"] == trial["elapsed_seconds"], trial["trial"]
        audited.append({"trial": trial["trial"], "exact": exact,
                        "target_after_fault": target is not None,
                        "selected_target_throw": len(false),
                        "junit_exit": manifest["returncode"],
                        "elapsed_seconds": manifest["elapsed_seconds"],
                        "plan": trial["plan"]})
        archive_files.update(path for path in directory.iterdir() if path.is_file())
        driver = directory.parent / (directory.name + "-driver.log")
        if driver.is_file():
            archive_files.add(driver)
    summary = {"case_id": "HDFS-52", "completed_attempts": len(audited),
               "strict_trials": sum(row["exact"] for row in audited),
               "target_retaining_trials": sum(row["exact"] and row["target_after_fault"]
                                              for row in audited),
               "selected_target_throws": sum(row["selected_target_throw"] for row in audited),
               "trials": audited}
    assert summary["selected_target_throws"] == 0
    atomic_json(AUDIT, summary)
    archive_files.add(AUDIT)
    temporary = ARCHIVE.with_suffix(ARCHIVE.suffix + ".tmp")
    with tarfile.open(temporary, "w:gz") as output:
        for path in sorted(archive_files):
            assert path.is_file() and path.is_relative_to(CASE)
            output.add(path, arcname=str(path.relative_to(CASE)), recursive=False)
    os.replace(temporary, ARCHIVE)
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    atomic_json(INDEX, {"archive": ARCHIVE.name, "sha256": digest,
                        "bytes": ARCHIVE.stat().st_size,
                        "file_count": len(archive_files),
                        "contents": "Healthy and completed-trial original JUnit plans, traces, raw JaCoCo, logs, checkpoint and independent audit; interrupted active trial excluded"})

    result = json.loads(RESULT.read_text())
    assert result["fault_trials"] == summary["completed_attempts"]
    assert result["strict_injections"] == summary["strict_trials"]
    assert result["target_after_fault"] == summary["target_retaining_trials"]
    result.update({
        "status": "source_excluded",
        "stop_reason": "source_proven_fault_model_cannot_change_count_guard_in_original_test",
        "bug_mark": "none",
        "source_review": (
            "The original test holds FSNamesystem.readLock around Saver.save "
            "(TestFSImageWithSnapshot.java:143-155). Snapshot creation changes "
            "SnapshotManager.numSnapshots under FSNamesystem.writeLock "
            "(FSNamesystem.java:7175-7192). Saver serializes the in-memory "
            "snapshot list and compares its count with that manager count "
            "(FSImageFormatPBSnapshot.java:435-468). A checked IOException "
            "at writeDelimitedTo aborts serialization before the guard; "
            "heartbeat/RPC faults do not modify the locked snapshot count. "
            "The selected equality was true in every fault-retaining trace. "
            "This site is outside the current checked-I/O fault model for "
            "ad hoc coordination in this unchanged JUnit, so the campaign "
            "was source-excluded rather than reported as a negative bug proof."
        ),
        "raw_event_audit": "independent/evidence/source-exclusion-audit.json",
        "raw_evidence_archive": json.loads(INDEX.read_text()),
    })
    atomic_json(RESULT, result)
    print({key: summary[key] for key in
           ("completed_attempts", "strict_trials", "target_retaining_trials",
            "selected_target_throws")})


if __name__ == "__main__":
    main()
