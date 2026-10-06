#!/usr/bin/env python3
"""Audit HDFS-16 checkpoint, ordered faults, target identity and coverage."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tarfile
import time


CASE = Path(__file__).resolve().parents[1]
RESULT = CASE.parent / "result.json"
TARGET = "BlockInfo.setGenerationStampAndVerifyReplicas:428"


def events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def tuple_of(row: dict) -> tuple:
    return tuple(row[key] for key in
                 ("marker", "api", "ordinal", "exception"))


def same_context(row: dict, expected: dict) -> bool:
    return (row.get("blockId") == expected["block_id"] and
            row.get("caller") == expected["caller"] and
            row.get("proposedGenerationStamp") ==
            expected["proposed_generation_stamp"])


def main() -> None:
    # The live publisher atomically replaces these three files in sequence.
    # Read a consistent prefix before checking any per-trial artifacts.
    for _ in range(20):
        state = json.loads((CASE / "campaign/checkpoint.json").read_text())
        result = json.loads(RESULT.read_text())
        ledger = list(csv.DictReader(
            (CASE / "campaign/trial-ledger.csv").open()))
        rows = state["completed"]
        if len(rows) == result["fault_trials"] == len(ledger):
            break
        time.sleep(0.2)
    else:
        raise RuntimeError("live checkpoint, result and ledger did not agree")
    assert state["case_id"] == result["case_id"] == "HDFS-16"
    assert [row["number"] for row in rows] == list(range(1, len(rows) + 1))
    assert len({row["sequence_id"] for row in rows}) == len(rows)
    archive_path = CASE / "coverage-evidence.tar.gz"
    archive = tarfile.open(archive_path, "r:gz") if archive_path.is_file() else None
    expected_archive = set()
    for row in rows:
        directory = CASE / "campaign" / row["trial"]
        assert json.loads((directory / "trial-result.json").read_text()) == row
        manifest = json.loads((directory / "manifest.json").read_text())
        assert manifest["exit"] == row["junit_exit"]
        assert manifest["elapsed_seconds"] == row["junit_seconds"]
        assert manifest["test"].endswith("#" + row["test_method"])
        assert row["seconds"] >= row["junit_seconds"]
        plan = (CASE / "campaign/plans" / (row["trial"] + ".tsv")).read_text()
        expected_plan = "".join(
            f"{p['marker']}\t{p['api']}\t{p['ordinal']}\t{p['exception']}\n"
            for p in row["sequence"])
        assert plan == expected_plan
        trace = events(directory / "trace/runtime_trace.jsonl")
        matched = [event for event in trace
                   if event.get("event") == "FAULT_MATCHED"]
        applied = [event for event in trace
                   if event.get("event") == "FAULT_APPLIED"]
        assert row["requested_faults"] == len(row["sequence"])
        assert row["matched_faults"] == len(matched)
        assert row["applied_faults"] == len(applied)
        strict = ([tuple_of(event) for event in applied] ==
                  [tuple_of(event) for event in row["sequence"]] and
                  len(matched) == len(row["sequence"]))
        assert row["strict_injection"] == strict
        after = max((event["seq"] for event in applied), default=-1)
        guards = [event for event in trace
                  if event.get("event") == "TARGET_GUARD" and
                  event.get("site") == TARGET and event["seq"] > after >= 0 and
                  same_context(event, row["target_context_expected"])]
        assert row["target_guard_after_last_fault"] == bool(guards)
        assert row["target_outcomes_after_fault"] == [
            event["allowed"] for event in guards]
        false_guards = {(event["ordinal"], event["blockId"])
                        for event in guards if not event["allowed"]}
        exact = [event for event in trace
                 if event.get("event") == "TARGET_EXCEPTION" and
                 event.get("site") == TARGET and
                 event.get("type") == "java.lang.IllegalStateException" and
                 event.get("seq", -1) > after >= 0 and
                 (event.get("ordinal"), event.get("blockId")) in false_guards]
        assert row["target_exception_after_fault_count"] == len(exact)
        assert row["bug_mark"] == (
            "candidate" if strict and guards and exact else "none")
        assert row["status"] == (
            "unmatched" if not strict else
            "lost_target" if not guards else
            "target_exception_candidate" if exact else
            "workload_timeout" if manifest["exit"] == 124 else "checked")
        coverage = directory / "coverage.tsv"
        if archive is not None:
            member = f"campaign/{row['trial']}/coverage.tsv"
            packed = archive.extractfile(member)
            assert packed is not None
            packed_bytes = packed.read()
            if coverage.is_file():
                assert packed_bytes == coverage.read_bytes()
            identifiers = packed_bytes.decode().splitlines()
            expected_archive.add(member)
        else:
            assert coverage.is_file()
            identifiers = coverage.read_text().splitlines()
        assert len(identifiers) == row["coverage_ids"]
        assert all(identifier.startswith(("METHOD\t", "BRANCH_UNIT\t",
                                          "PROBE\t")) and
                   "org/apache/hadoop/hdfs/" in identifier and
                   "hdfs16independent" not in identifier
                   for identifier in identifiers)
    if archive is not None:
        assert set(archive.getnames()) == expected_archive
        archive.close()
    assert [int(row["number"]) for row in ledger] == list(
        range(1, len(rows) + 1))
    assert result["fault_trials"] == len(rows)
    assert result["requested_fault_events"] == sum(
        row["requested_faults"] for row in rows)
    assert result["applied_fault_events"] == sum(
        row["applied_faults"] for row in rows)
    assert result["strict_injection_trials"] == sum(
        row["strict_injection"] for row in rows)
    assert result["post_fault_target_reach_trials"] == sum(
        row["strict_injection"] and row["target_guard_after_last_fault"]
        for row in rows)
    assert result["target_exception_after_fault_trials"] == sum(
        row["strict_injection"] and row["target_exception_after_fault_count"] > 0
        for row in rows)
    report = {"case_id": "HDFS-16", "audited_trials": len(rows),
              "all_checks_passed": True,
              "audited_at_utc": datetime.now(timezone.utc).isoformat()}
    output = CASE / "audit.json"
    temp = output.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temp.replace(output)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
