#!/usr/bin/env python3
"""Independently check HDFS-08 trial evidence and the combined case row."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tarfile


CASE = Path(__file__).resolve().parents[1]
ROOT = CASE.parent / "result.json"
TARGET = "Journal.checkRequest:486"


def trace_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def exact_context(row: dict, expected: dict) -> bool:
    return (row.get("node") == expected["node"] and
            row.get("caller") == expected["caller"] and
            row.get("journalId") == expected["journal_id"] and
            row.get("segmentStartTxId") == expected["segment_start_txid"] and
            row.get("segmentEndTxId") == expected["segment_end_txid"])


def fault_tuple(row: dict) -> tuple:
    return tuple(row[key] for key in
                 ("marker", "api", "node", "ordinal", "exception"))


def main() -> None:
    case = json.loads(ROOT.read_text())
    archive = tarfile.open(CASE / "coverage-evidence.tar.gz", "r:gz")
    all_rows = []
    stages = {}
    for stage, directory in (("singlewriter", CASE / "campaign"),
                             ("multiwriter", CASE / "campaign-multiwriter")):
        state = json.loads((directory / "checkpoint.json").read_text())
        results = state["completed"]
        assert [row["number"] for row in results] == list(
            range(1, len(results) + 1)), stage
        assert len({row["sequence_id"] for row in results}) == len(results)
        for row in results:
            out = directory / row["trial"]
            assert json.loads((out / "trial-result.json").read_text()) == row
            manifest = json.loads((out / "manifest.json").read_text())
            assert manifest["exit"] == row["junit_exit"]
            assert manifest["elapsed_seconds"] == row["junit_seconds"]
            assert row["seconds"] >= row["junit_seconds"]
            assert manifest["test"].endswith("#" + row["test_method"])
            if stage == "multiwriter":
                expected_paxos = row["number"] >= 38
                assert manifest.get("paxos", False) == expected_paxos
                assert row.get("instrumentation_version",
                               "source_probes_v1") == (
                    "paxos_hook_v2" if expected_paxos else "source_probes_v1")
            trace = trace_rows(out / "trace/runtime_trace.jsonl")
            applied = [event for event in trace
                       if event.get("event") == "FAULT_APPLIED"]
            matched = [event for event in trace
                       if event.get("event") == "FAULT_MATCHED"]
            assert row["requested_faults"] == len(row["sequence"])
            assert row["applied_faults"] == len(applied)
            assert row["matched_faults"] == len(matched)
            strict = ([fault_tuple(event) for event in applied] ==
                      [fault_tuple(event) for event in row["sequence"]] and
                      len(matched) == len(row["sequence"]))
            assert row["strict_injection"] == strict
            after = max((event["seq"] for event in applied), default=-1)
            guards = [event for event in trace
                      if event.get("event") == "TARGET_GUARD" and
                      event.get("site") == TARGET and event["seq"] > after >= 0
                      and exact_context(event, row["target_context_expected"])]
            assert row["target_guard_after_last_fault"] == bool(guards)
            assert row["target_outcomes_after_fault"] == [
                event["allowed"] for event in guards]
            false_guards = {
                (event["ordinal"], event["node"],
                 event["segmentStartTxId"], event["segmentEndTxId"])
                for event in guards if not event["allowed"]}
            exact_exceptions = [event for event in trace
                                if event.get("event") == "TARGET_EXCEPTION" and
                                event.get("site") == TARGET and
                                event.get("type") == "java.io.IOException" and
                                event.get("message", "").startswith(
                                    "IPC's epoch ") and
                                event.get("seq", -1) > after >= 0 and
                                (event.get("ordinal"), event.get("node"),
                                 event.get("segmentStartTxId"),
                                 event.get("segmentEndTxId")) in false_guards]
            assert row["target_exception_after_fault_count"] == len(
                exact_exceptions)
            assert row["status"] == (
                "unmatched" if not strict else
                "lost_target" if not guards else
                "target_exception_candidate" if row["bug_mark"] == "candidate"
                else "checked")
            assert (directory / "plans" / (row["trial"] + ".tsv")).is_file()
            coverage_path = out / "coverage.tsv"
            if coverage_path.is_file():
                coverage = coverage_path.read_text().splitlines()
            else:
                member = (directory.relative_to(CASE) / row["trial"] /
                          "coverage.tsv").as_posix()
                packed = archive.extractfile(member)
                assert packed is not None
                coverage = packed.read().decode().splitlines()
            assert len(coverage) == row["coverage_ids"]
            assert all(line.startswith(("METHOD\t", "BRANCH_UNIT\t",
                                        "PROBE\t")) and
                       "org/apache/hadoop/hdfs/" in line and
                       "hdfs08independent" not in line
                       for line in coverage)
            all_rows.append((stage, row))
        stages[stage] = {"completed": len(results),
                         "strict": sum(row["strict_injection"] for row in results),
                         "target_after": sum(row["strict_injection"] and
                                             row["target_guard_after_last_fault"]
                                             for row in results),
                         "unmatched": sum(row["status"] == "unmatched"
                                          for row in results),
                         "lost_target": sum(row["status"] == "lost_target"
                                            for row in results)}
    ledger = list(csv.DictReader((CASE / "combined-trial-ledger.csv").open()))
    assert len(ledger) == len(all_rows)
    assert [(int(entry["global_number"]), entry["stage"], entry["trial"])
            for entry in ledger] == [
                (number, stage, row["trial"])
                for number, (stage, row) in enumerate(all_rows, 1)]
    assert case["fault_trials"] == len(all_rows)
    assert case["strict_injection_trials"] == sum(
        row["strict_injection"] for _, row in all_rows)
    assert case["post_fault_target_reach_trials"] == sum(
        row["strict_injection"] and row["target_guard_after_last_fault"]
        for _, row in all_rows)
    assert case["target_exception_after_fault_trials"] == sum(
        row["strict_injection"] and row["target_exception_after_fault_count"] > 0
        for _, row in all_rows)
    assert case["bug_mark"] == (
        "candidate" if any(row["bug_mark"] == "candidate"
                           for _, row in all_rows) else "none")
    assert set(archive.getnames()) == {
        (CASE / ("campaign" if stage == "singlewriter" else
                 "campaign-multiwriter") / row["trial"] /
         "coverage.tsv").relative_to(CASE).as_posix()
        for stage, row in all_rows}
    archive.close()
    report = {"case_id": "HDFS-08", "audited_trials": len(all_rows),
              "stages": stages, "all_checks_passed": True,
              "audited_at_utc": datetime.now(timezone.utc).isoformat()}
    target = CASE / "audit.json"
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temp.replace(target)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
