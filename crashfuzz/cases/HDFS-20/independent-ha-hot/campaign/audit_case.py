#!/usr/bin/env python3
"""Independently audit completed ordered-fault and target evidence."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tarfile
import time


CASE = Path(__file__).resolve().parents[1]
CASE_ID = CASE.parent.name
RESULT = CASE / "campaign/phase-result.json"
SITE = {"HDFS-20": "BPOfferService.updateActorStatesFromHeartbeat:606",
        "HDFS-21": "BPServiceActor.checkNNVersion:290"}[CASE_ID]
EXCEPTION = {"HDFS-20": "java.lang.AssertionError",
             "HDFS-21":
             "org.apache.hadoop.hdfs.server.common.IncorrectVersionException"}[CASE_ID]


def events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def selector(row: dict) -> tuple:
    return tuple(row[key] for key in
                 ("marker", "api", "endpoint", "ordinal", "exception"))


def context(row: dict, expected: dict) -> bool:
    if CASE_ID == "HDFS-20":
        return (row.get("bposInstance") == expected["bpos_instance"] and
                row.get("actorInstance") == expected["actor_instance"] and
                row.get("lastActiveClaimTxId", -1) >=
                expected["healthy_prior_claim"])
    return (row.get("actorInstance") == expected["actor_instance"] and
            row.get("nnVersion") == expected["nn_version"] and
            row.get("minimumNameNodeVersion") ==
            expected["minimum_namenode_version"])


def exception_key(row: dict) -> tuple:
    if CASE_ID == "HDFS-20":
        return (row.get("ordinal"), row.get("bposInstance"),
                row.get("actorInstance"))
    return (row.get("ordinal"), row.get("actorInstance"))


def main() -> None:
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
        raise RuntimeError("live checkpoint, result, and ledger disagree")
    assert state["case_id"] == result["case_id"] == CASE_ID
    assert [row["number"] for row in rows] == list(range(1, len(rows) + 1))
    assert len({row["sequence_id"] for row in rows}) == len(rows)
    archived = CASE / "coverage-evidence.tar.gz"
    archive = tarfile.open(archived, "r:gz") if archived.is_file() else None
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
        assert plan == "".join(
            f"{p['marker']}\t{p['api']}\t{p['endpoint']}\t"
            f"{p['ordinal']}\t{p['exception']}\n"
            for p in row["sequence"])
        trace = events(directory / "trace/runtime_trace.jsonl")
        matched = [event for event in trace
                   if event.get("event") == "FAULT_MATCHED"]
        applied = [event for event in trace
                   if event.get("event") == "FAULT_APPLIED"]
        assert row["requested_faults"] == len(row["sequence"])
        assert row["matched_faults"] == len(matched)
        assert row["applied_faults"] == len(applied)
        strict = ([selector(event) for event in applied] ==
                  [selector(event) for event in row["sequence"]] and
                  len(matched) == len(row["sequence"]))
        assert row["strict_injection"] == strict
        after = max((event["seq"] for event in applied), default=-1)
        all_guards = [event for event in trace
                      if event.get("event") == "TARGET_GUARD" and
                      event.get("site") == SITE and event["seq"] > after >= 0]
        guards = [event for event in all_guards if context(
            event, row["target_context_expected"])]
        assert row["target_guard_after_last_fault"] == bool(guards)
        assert row["target_guard_after_last_fault_count"] == len(guards)
        assert row["other_context_guard_after_last_fault_count"] == (
            len(all_guards) - len(guards))
        assert row["target_outcomes_after_fault"] == [
            event["allowed"] for event in guards]
        false_keys = {exception_key(event) for event in guards
                      if not event["allowed"]}
        all_exceptions = [event for event in trace
                          if event.get("event") == "TARGET_EXCEPTION" and
                          event.get("site") == SITE and
                          event.get("type") == EXCEPTION and
                          event["seq"] > after >= 0]
        exact = [event for event in all_exceptions
                 if exception_key(event) in false_keys]
        assert row["target_exception_after_fault_count"] == len(exact)
        assert row["target_exception_any_context_after_fault_count"] == len(
            all_exceptions)
        candidate = strict and bool(exact)
        other_candidate = strict and bool(all_exceptions) and not candidate
        assert row["bug_mark"] == (
            "candidate" if candidate or other_candidate else "none")
        assert row["status"] == (
            "unmatched" if not strict else
            "target_exception_candidate" if candidate else
            "other_context_exception_candidate" if other_candidate else
            "lost_target" if not guards else
            "workload_timeout" if manifest["exit"] == 124 else "checked")
        coverage = directory / "coverage.tsv"
        if archive:
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
                   CASE_ID.lower().replace("-", "") + "hotindependent" not in
                   identifier for identifier in identifiers)
    if archive:
        assert set(archive.getnames()) == expected_archive
        archive.close()
    assert [int(row["number"]) for row in ledger] == list(
        range(1, len(rows) + 1))
    assert result["fault_trials"] == len(rows)
    for result_key, row_key in (("requested_fault_events", "requested_faults"),
                                ("matched_fault_events", "matched_faults"),
                                ("applied_fault_events", "applied_faults")):
        assert result[result_key] == sum(row[row_key] for row in rows)
    strict_count = sum(row["strict_injection"] for row in rows)
    target_count = sum(row["strict_injection"] and
                       row["target_guard_after_last_fault"] for row in rows)
    assert result["strict_injection_trials"] == strict_count
    assert result["fully_applied_trials"] == strict_count
    assert result["post_fault_target_reach_trials"] == target_count
    assert result["target_exception_after_fault_trials"] == sum(
        row["strict_injection"] and row["target_exception_after_fault_count"] > 0
        for row in rows)
    report = {"case_id": CASE_ID, "audited_trials": len(rows),
              "all_checks_passed": True,
              "audited_at_utc": datetime.now(timezone.utc).isoformat()}
    output = CASE / "audit.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temporary.replace(output)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
