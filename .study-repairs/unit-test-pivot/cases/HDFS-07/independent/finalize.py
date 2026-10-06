#!/usr/bin/env python3
"""Finalize the original-JUnit HDFS-07 campaign from audited raw events."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
EVIDENCE = HERE / "evidence"
STATE = EVIDENCE / "campaign-state.json"
AUDIT = EVIDENCE / "audit-result.json"
LEDGER = CASE / "independent-trial-ledger.csv"
ARCHIVE = CASE / "HDFS-07-independent-evidence.tar.gz"
ARCHIVE_MANIFEST = CASE / "independent-archive-manifest.json"
RESULT = CASE / "result.json"
KEEP = {"manifest.json", "runtime_trace.jsonl", "faults.tsv", "junit.log",
        "jacoco.exec", "runner-console.log"}


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def completion_order(state: dict) -> list[str]:
    log = EVIDENCE / "campaign.log"
    ordered = []
    for line in log.read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "completed" in entry and "id" in entry:
            ordered.append(entry["id"])
    assert len(ordered) == len(set(ordered)) == len(state["completed"])
    assert set(ordered) == set(state["completed"])
    return ordered


def write_ledger(state: dict, order: list[str]) -> None:
    fields = ("trial", "id", "elapsed_seconds", "requested_faults", "matched_faults",
              "applied_faults", "exact_order_applied", "target_after_fault",
              "target_exception_after_fault", "junit_exit", "coverage_probes_gain",
              "coverage_branches_gain", "new_io_families", "bug_mark", "manifest")
    temporary = LEDGER.with_suffix(".csv.tmp")
    with temporary.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, identity in enumerate(order, 1):
            trial = state["completed"][identity]
            writer.writerow({"trial": index, "id": identity,
                             "elapsed_seconds": trial["elapsed_seconds"],
                             "requested_faults": trial["requested_faults"],
                             "matched_faults": trial["matched_faults"],
                             "applied_faults": trial["applied_faults"],
                             "exact_order_applied": trial["exact_order_applied"],
                             "target_after_fault": trial["target_after_fault"],
                             "target_exception_after_fault": trial["target_exception_after_fault"],
                             "junit_exit": trial["junit_exit"],
                             "coverage_probes_gain": trial["coverage_gain"]["probes"],
                             "coverage_branches_gain": trial["coverage_gain"]["branch_counts"],
                             "new_io_families": trial["new_io_families"],
                             "bug_mark": trial["bug_mark"],
                             "manifest": str(Path(trial["manifest"]).relative_to(CASE))})
    temporary.replace(LEDGER)


def archive_evidence() -> dict:
    paths = [path for path in EVIDENCE.rglob("*") if path.is_file() and
             ("runs" not in path.relative_to(EVIDENCE).parts or path.name in KEEP)
             and "scratch" not in path.relative_to(EVIDENCE).parts]
    temporary = ARCHIVE.with_suffix(ARCHIVE.suffix + ".tmp")
    with tarfile.open(temporary, "w:gz") as archive:
        for path in sorted(paths):
            archive.add(path, arcname=str(path.relative_to(CASE)), recursive=False)
    temporary.replace(ARCHIVE)
    digest = hashlib.sha256()
    with ARCHIVE.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    manifest = {"archive": ARCHIVE.name, "sha256": digest.hexdigest(),
                "bytes": ARCHIVE.stat().st_size, "file_count": len(paths),
                "contents": "healthy and fault trial manifests, runtime traces, raw JaCoCo, logs, plans, and campaign audit; no scratch data"}
    atomic_json(ARCHIVE_MANIFEST, manifest)
    return manifest


def main() -> None:
    state = json.loads(STATE.read_text())
    audit = json.loads(AUDIT.read_text())
    completed = state["completed"]
    assert len(completed) == audit["completed"]
    assert len(completed) == state["budget"]["max_trials"] or not state["queue"]
    assert audit["target_retaining"] >= 20
    assert audit["target_throw_events"] == 0
    assert all(trial["bug_mark"] == "none" for trial in completed.values())
    order = completion_order(state)
    write_ledger(state, order)
    archive = archive_evidence()
    result = json.loads(RESULT.read_text())
    assert result["fault_trials"] == len(completed)
    result["status"] = "quality_complete"
    result["bug_mark"] = "none"
    result["reason"] = (
        "Original three-JournalNode JUnit finished a coverage and observed-I/O "
        "campaign; the post-fault selected assertion did not fire.")
    result["source_review"] = (
        "Journal.acceptRecovery rejects a shorter replacement only when the old "
        "range contains an already-committed transaction that the proposed range "
        "omits. The original test writes transaction 5 to only one JournalNode, "
        "then verifies recovery to transaction 4; the selected JN2 epoch-3 "
        "guard was reached after fault injection without throwing. JUnit failures "
        "caused by injected I/O/quorum loss are recorded separately from target throws.")
    result["audit"] = {"file": "independent/evidence/audit-result.json",
                       "strict": audit["strict"],
                       "target_retaining": audit["target_retaining"],
                       "target_throw_events": 0,
                       "max_faults_applied": audit["max_faults"]}
    result["trial_ledger"] = LEDGER.name
    result["raw_evidence_archive"] = archive
    atomic_json(RESULT, result)
    print({"completed": len(completed), "target_retaining": audit["target_retaining"],
           "target_throw_events": 0, "archive_bytes": archive["bytes"]})


if __name__ == "__main__":
    main()
