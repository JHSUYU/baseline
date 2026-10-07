#!/usr/bin/env python3
"""Audit exact ordered faults, same-block target identity and published totals."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

import run_campaign as campaign

CASE = Path(__file__).resolve().parents[1]
STATE = CASE / "campaign/checkpoint.json"
RESULT = CASE.parent / "result.json"
SITE = "FSDirAppendOp.appendFile:131"
EXCEPTION = "org.apache.hadoop.ipc.RetriableException"
KEYS = ("marker", "api", "endpoint", "ordinal", "exception")


def trace(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


def main() -> None:
    state = json.loads(STATE.read_text())
    rows = state["completed"]
    result = json.loads(RESULT.read_text())
    ledger = list(csv.DictReader((CASE / "campaign/trial-ledger.csv").open()))
    assert state["case_id"] == result["case_id"] == "HDFS-39"
    assert len(rows) == result["fault_trials"] == len(ledger)
    assert [row["number"] for row in rows] == list(range(1, len(rows) + 1))
    assert [int(row["number"]) for row in ledger] == list(
        range(1, len(rows) + 1))
    assert len({row["sequence_id"] for row in rows}) == len(rows)
    archive_path = CASE / "coverage-evidence.tar.gz"
    archive = tarfile.open(archive_path, "r:gz") if archive_path.is_file() else None
    archive_members = set()
    healthy_dirs = (CASE / "healthy/probed", CASE / "healthy/probed-v2")
    union_coverage = set().union(*(
        campaign.coverage_ids(path / "coverage.tsv") for path in healthy_dirs))
    healthy_io = [event for path in healthy_dirs
                  for event in campaign.events(path / "trace/runtime_trace.jsonl")
                  if campaign.relevant(event)]
    union_io = {campaign.point_id(event) for event in healthy_io}
    union_families = {campaign.family_id(event) for event in healthy_io}
    for row in rows:
        directory = CASE / "campaign" / row["trial"]
        assert json.loads((directory / "trial-result.json").read_text()) == row
        manifest = json.loads((directory / "manifest.json").read_text())
        assert manifest["exit"] == row["junit_exit"]
        assert manifest["elapsed_seconds"] == row["junit_seconds"]
        assert manifest["test"].endswith("#testMultipleAppends")
        assert row["seconds"] >= row["junit_seconds"]
        expected_plan = "".join(
            "\t".join(str(point[key]) for key in KEYS) + "\n"
            for point in row["sequence"])
        assert (CASE / "campaign/plans" /
                (row["trial"] + ".tsv")).read_text() == expected_plan
        events = trace(directory / "trace/runtime_trace.jsonl")
        matched = [event for event in events
                   if event.get("event") == "FAULT_MATCHED"]
        applied = [event for event in events
                   if event.get("event") == "FAULT_APPLIED"]
        strict = ([tuple(event[key] for key in KEYS) for event in applied] ==
                  [tuple(point[key] for key in KEYS)
                   for point in row["sequence"]] and
                  len(matched) == len(row["sequence"]))
        assert row["requested_faults"] == len(row["sequence"])
        assert row["matched_faults"] == len(matched)
        assert row["applied_faults"] == len(applied)
        assert row["strict_injection"] == strict
        last_fault = max((event["seq"] for event in applied), default=-1)
        assert row["last_applied_seq"] == last_fault
        all_guards = [event for event in events
                      if event.get("event") == "TARGET_GUARD" and
                      event.get("site") == SITE and
                      event["seq"] > last_fault >= 0]
        expected = row["target_context_expected"]
        guards = [event for event in all_guards
                  if event.get("path") == expected["path"] and
                  event.get("blockId") == expected["block_id"]]
        assert row["target_guard_after_last_fault"] == bool(guards)
        assert row["target_guard_after_last_fault_count"] == len(guards)
        assert row["other_context_guard_after_last_fault_count"] == (
            len(all_guards) - len(guards))
        assert row["target_states_after_fault"] == [
            event["state"] for event in guards]
        assert row["target_actual_guard_ordinals_after_fault"] == [
            event["ordinal"] for event in guards]
        committed = {(event["ordinal"], event["path"], event["blockId"])
                     for event in guards if event["committed"]}
        exact = [event for event in events
                 if event.get("event") == "TARGET_EXCEPTION" and
                 event.get("site") == SITE and
                 event.get("type") == EXCEPTION and
                 event.get("seq", -1) > last_fault >= 0 and
                 (event.get("ordinal"), event.get("path"),
                  event.get("blockId")) in committed]
        any_context = [event for event in events
                       if event.get("event") == "TARGET_EXCEPTION" and
                       event.get("site") == SITE and
                       event.get("seq", -1) > last_fault >= 0]
        assert row["target_exception_after_fault_count"] == len(exact)
        assert row["target_exception_any_context_after_fault_count"] == len(
            any_context)
        candidate = strict and bool(guards) and bool(exact) and manifest["exit"] != 0
        other_candidate = strict and bool(any_context) and manifest["exit"] != 0 and not candidate
        assert row["bug_mark"] == (
            "candidate" if candidate or other_candidate else "none")
        assert row["status"] == (
            "unmatched" if not strict else
            "target_exception_candidate" if candidate else
            "other_context_exception_candidate" if other_candidate else
            "lost_target" if not guards else
            "workload_timeout" if manifest["exit"] == 124 else
            "checked_expected_retry" if exact else "checked")
        member = f"campaign/{row['trial']}/coverage.tsv"
        if archive:
            packed = archive.extractfile(member)
            assert packed is not None
            coverage = packed.read()
            local_file = directory / "coverage.tsv"
            if local_file.is_file():
                assert local_file.read_bytes() == coverage
            archive_members.add(member)
        else:
            coverage = (directory / "coverage.tsv").read_bytes()
        ids = coverage.decode().splitlines()
        assert len(ids) == row["coverage_ids"]
        assert all(identifier.startswith(("METHOD\t", "BRANCH_UNIT\t",
                                          "PROBE\t")) and
                   "org/apache/hadoop/hdfs/" in identifier and
                   "hdfs39independent" not in identifier
                   for identifier in ids)
        admitted = strict and bool(guards)
        expected_new = set(ids) - union_coverage if admitted else set()
        assert row["new_coverage_ids"] == sorted(expected_new)
        assert row["new_coverage_count"] == len(expected_new)
        observed = [event for event in events if campaign.relevant(event)]
        observed_io = {campaign.point_id(event) for event in observed}
        observed_families = {campaign.family_id(event) for event in observed}
        expected_new_io = observed_io - union_io if admitted else set()
        expected_new_families = (
            observed_families - union_families if admitted else set())
        assert row["new_io_point_ids"] == sorted(expected_new_io)
        assert row["new_io_family_ids"] == sorted(expected_new_families)
        if admitted:
            union_coverage.update(expected_new)
            union_io.update(expected_new_io)
            union_families.update(expected_new_families)
    if archive:
        assert set(archive.getnames()) == archive_members
        archive.close()
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
    reviews_path = CASE / "campaign/candidate-reviews.json"
    reviews = json.loads(reviews_path.read_text()) if reviews_path.is_file() else {}
    candidates = [row for row in rows if row["bug_mark"] == "candidate"]
    assert set(reviews) <= {row["trial"] for row in candidates}
    for trial, review in reviews.items():
        for name, digest_name in (("original_trace", "original_trace_sha256"),
                                  ("replay_trace", "replay_trace_sha256"),
                                  ("replay_runtime_log", "replay_runtime_log_sha256"),
                                  ("prefix3_trace", "prefix3_trace_sha256")):
            if name not in review:
                continue
            path = CASE / review[name]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == review[digest_name]
        original = next(row for row in candidates if row["trial"] == trial)
        replay_trace = CASE / review["replay_trace"]
        replay_dir = replay_trace.parent.parent
        replay_manifest = json.loads((replay_dir / "manifest.json").read_text())
        replay_events = trace(replay_trace)
        replay_applied = [event for event in replay_events
                          if event.get("event") == "FAULT_APPLIED"]
        assert [tuple(event[key] for key in KEYS) for event in replay_applied] == [
            tuple(point[key] for key in KEYS) for point in original["sequence"]]
        assert replay_manifest["exit"] == review["junit_exit_in_original_and_replay"]
        replay_last_fault = max(event["seq"] for event in replay_applied)
        same_context_guards = [event for event in replay_events
                               if event.get("event") == "TARGET_GUARD" and
                               event.get("site") == SITE and
                               event["seq"] > replay_last_fault and
                               event.get("path") == original["target_context_expected"]["path"] and
                               event.get("blockId") == original["target_context_expected"]["block_id"]]
        assert bool(same_context_guards) == review["target_after_fault_in_original_and_replay"]
        replay_exact = [event for event in replay_events
                        if event.get("event") == "TARGET_EXCEPTION" and
                        event.get("site") == SITE and
                        event.get("type") == EXCEPTION and
                        event["seq"] > replay_last_fault and
                        event.get("path") == original["target_context_expected"]["path"] and
                        event.get("blockId") == original["target_context_expected"]["block_id"]]
        assert bool(replay_exact) == review["exact_target_exception_reproduced"]
        replay_log = (CASE / review["replay_runtime_log"]).read_text()
        assert "HDFS-39 injected at RPC_RESPONSE" in replay_log
        assert "Client.getRpcResponse" in replay_log
        if "prefix3_trace" in review:
            prefix_trace = CASE / review["prefix3_trace"]
            prefix_manifest = json.loads((prefix_trace.parent.parent / "manifest.json").read_text())
            prefix_events = trace(prefix_trace)
            prefix_applied = [event for event in prefix_events
                              if event.get("event") == "FAULT_APPLIED"]
            assert [tuple(event[key] for key in KEYS) for event in prefix_applied] == [
                tuple(point[key] for key in KEYS) for point in original["sequence"][:3]]
            assert prefix_manifest["exit"] == review["prefix3_junit_exit"] == 0
            if "prefix3_target_exception_after_fault_count" in review:
                prefix_last_fault = max(event["seq"] for event in prefix_applied)
                assert review["prefix3_target_exception_after_fault_count"] == sum(
                    event.get("event") == "TARGET_EXCEPTION" and
                    event.get("site") == SITE and
                    event.get("type") == EXCEPTION and
                    event["seq"] > prefix_last_fault and
                    event.get("path") == original["target_context_expected"]["path"] and
                    event.get("blockId") == original["target_context_expected"]["block_id"]
                    for event in prefix_events)
    source_provenance = json.loads((CASE / "source-provenance.json").read_text())
    assert source_provenance["graphchecker_artifacts_used"] is False
    for entry in source_provenance["files"]:
        snapshot = (CASE / entry["snapshot"]).read_bytes()
        with zipfile.ZipFile(entry["source_jar"]) as release:
            assert release.read(entry["member"]) == snapshot
        assert hashlib.sha256(snapshot).hexdigest() == entry["sha256"]
    open_candidates = [row for row in candidates if row["trial"] not in reviews]
    confirmed = [row for row in candidates if reviews.get(row["trial"], {}).get("new_bug")]
    assert result["oracle_candidates"] == len(candidates)
    assert result["unreviewed_candidates"] == len(open_candidates)
    assert result["validated_new_bug_candidates"] == len(confirmed)
    assert result["reviewed_rejected_candidates"] == sum(
        row["trial"] in reviews and reviews[row["trial"]].get("new_bug") is False
        for row in candidates)
    assert result["bug_mark"] == (
        "new_bug" if confirmed else "candidate" if open_candidates else "none")
    report = {"case_id": "HDFS-39", "audited_trials": len(rows),
              "all_checks_passed": True,
              "audited_at_utc": datetime.now(timezone.utc).isoformat()}
    path = CASE / "audit.json"
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    temp.replace(path)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
