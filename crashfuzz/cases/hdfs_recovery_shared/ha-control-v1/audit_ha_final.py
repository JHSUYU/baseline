#!/usr/bin/env python3
"""Independently audit all raw HDFS-30 HA heartbeat campaign evidence.

Reads the final local mirror of the node2 original-JUnit campaign. It never
runs Hadoop or changes campaign state, trial evidence, results, or ledgers.
Only ha-final-audit.json is written.
"""

from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys


HERE = Path(__file__).resolve().parent
OUT = HERE / "ha-final-audit.json"
EXPECTED_TEST = ("org.apache.hadoop.hdfs.server.namenode.ha."
                 "TestPipelinesFailover#testFailoverRightBeforeCommitSynchronization")
TARGET_SITE = ("<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: "
               "org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB "
               "getActiveNamenodeForBP(java.lang.String)>#u23")
PLAN_FIELDS = ("marker", "siteId", "sourceKey", "occurrenceAddress",
               "hitOrdinal", "faultType", "filePhase")
ALLOWED_FAULTS = {"IOException", "EOFException", "SocketTimeoutException"}
COVERAGE = ("probes", "methods", "branch_counts", "lines")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def error(report: dict, message: str) -> None:
    report["errors"].append(message)


def warning(report: dict, message: str) -> None:
    report["warnings"].append(message)


def read_json(path: Path, report: dict) -> dict:
    if not path.is_file():
        error(report, "missing JSON file: " + str(path))
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        error(report, "invalid JSON " + str(path) + ": " + str(exc))
        return {}


def read_trace(path: Path, report: dict) -> list[dict]:
    if not path.is_file():
        error(report, "missing trace: " + str(path))
        return []
    rows = []
    prior_seq = 0
    with path.open() as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                error(report, f"{path.name}:{line_number}: blank JSONL row")
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                error(report, f"{path.name}:{line_number}: invalid complete JSONL row: {exc}")
                continue
            if not isinstance(row, dict):
                error(report, f"{path.name}:{line_number}: JSONL row is not an object")
                continue
            seq = row.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool) or seq <= prior_seq:
                error(report, f"{path.name}:{line_number}: non-monotonic seq {seq!r} after {prior_seq}")
            else:
                prior_seq = seq
            rows.append(row)
    return rows


def read_plan(path: Path, report: dict) -> list[dict]:
    if not path.is_file():
        error(report, "missing plan: " + str(path))
        return []
    points = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        fields = line.split("\t")
        if len(fields) != 7:
            error(report, f"{path.name}:{line_number}: expected 7 TSV columns, got {len(fields)}")
            continue
        point = dict(zip(PLAN_FIELDS, fields))
        try:
            point["hitOrdinal"] = int(point["hitOrdinal"])
        except ValueError:
            error(report, f"{path.name}:{line_number}: non-integer hitOrdinal")
            continue
        if (not point["marker"].startswith("FAULT:HDFS_HA_HEARTBEAT:")
                or point["faultType"] not in ALLOWED_FAULTS
                or point["filePhase"] != ""
                or point["hitOrdinal"] < 1):
            error(report, f"{path.name}:{line_number}: invalid HA heartbeat selector")
        expected_tail = ("/heartbeat-response" if point["marker"].endswith(":RESPONSE")
                         else "/heartbeat-request")
        if ("/phase:active1/" not in point["occurrenceAddress"]
                or not point["occurrenceAddress"].endswith(expected_tail)
                or not point["occurrenceAddress"].startswith(point["sourceKey"] + "/actor:")):
            error(report, f"{path.name}:{line_number}: incoherent runtime identity")
        points.append(point)
    if not 1 <= len(points) <= 2:
        error(report, f"{path.name}: expected 1 or 2 heartbeat fault rows")
    return points


def matching_event(row: dict, point: dict, index: int) -> bool:
    return (row.get("planIndex") == index
            and row.get("haPhase") == "active1"
            and row.get("originSourceKey") == point["sourceKey"]
            and all(row.get(key) == point[key] for key in PLAN_FIELDS[:-1]))


def independent_exact(trace: list[dict], plan: list[dict]) -> tuple[bool, list[dict]]:
    starts = [row["seq"] for row in trace
              if row.get("event") == "HA_TRANSITION"
              and row.get("nnIndex") == 1 and row.get("active") is True
              and row.get("haPhase") == "active1"
              and isinstance(row.get("seq"), int)]
    matched = [row for row in trace if row.get("event") == "FAULT_MATCHED"]
    applied = [row for row in trace if row.get("event") == "FAULT_APPLIED"]
    if not starts or len(matched) != len(plan) or len(applied) != len(plan):
        return False, applied
    start = min(starts)
    for index, point in enumerate(plan):
        match, apply = matched[index], applied[index]
        if (not matching_event(match, point, index)
                or not matching_event(apply, point, index)
                or not (start < match.get("seq", -1) < apply.get("seq", -1))
                or (index and not applied[index - 1]["seq"] < match["seq"])):
            return False, applied
        observed = any(row.get("event") == "FAULT_POINT_OBSERVED"
                       and row.get("seq", -1) < match["seq"]
                       and all(row.get(key) == point[key] for key in
                               ("marker", "siteId", "sourceKey",
                                "occurrenceAddress", "hitOrdinal"))
                       for row in trace)
        if not observed:
            return False, applied
    return True, applied


def independent_oracle(trace: list[dict], target: dict | None,
                       exact: bool, applied: list[dict]) -> dict:
    if not exact or not applied or not target:
        return {"checks": [], "true_checks": [], "throws": [],
                "actual_target_root": None}
    last = applied[-1]
    owners = [row for row in trace if row.get("event") == "RECOVERY_BEGIN"]
    checks = []
    for row in trace:
        if (row.get("event") != "TARGET_CHECK"
                or row.get("caseId") != "HDFS-30"
                or row.get("siteId") != TARGET_SITE
                or row.get("seq", -1) <= last.get("seq", -1)
                or any(row.get(key) != target.get(key) for key in
                       ("sourceKey", "blockId", "recoveryId"))
                or row.get("bpid") != last.get("bpid")
                or any(fault.get("bpid") != row.get("bpid") for fault in applied)):
            continue
        if any(owner.get("seq", -1) < row["seq"]
               and all(owner.get(key) == row.get(key) for key in
                       ("sourceKey", "blockId", "recoveryId", "occurrenceAddress"))
               for owner in owners):
            checks.append(row)
    true_checks = [row for row in checks if row.get("outcome") is True]
    throws = []
    for row in trace:
        if (row.get("event") != "TARGET_THROW"
                or row.get("caseId") != "HDFS-30"
                or row.get("siteId") != TARGET_SITE
                or row.get("runtimeType") != "java.io.IOException"
                or any(row.get(key) != target.get(key) for key in
                       ("sourceKey", "blockId"))):
            continue
        if any(check.get("seq", -1) < row.get("seq", -1)
               and check.get("occurrenceAddress") == row.get("occurrenceAddress")
               for check in true_checks):
            throws.append(row)
    return {"checks": checks, "true_checks": true_checks,
            "throws": throws,
            "actual_target_root": checks[0].get("occurrenceAddress") if checks else None}


def expected_status(manifest: dict, trace: list[dict], exact: bool,
                    matched_count: int, applied_count: int, oracle: dict) -> str:
    active1 = any(row.get("event") == "HA_TRANSITION"
                  and row.get("active") is True and row.get("nnIndex") == 1
                  for row in trace)
    if not manifest:
        return "runner_incomplete"
    if not exact and not matched_count and not applied_count and not active1 \
            and manifest.get("returncode") != 0:
        return "original_junit_pre_failover_flake"
    if not exact and not matched_count and not applied_count and active1:
        return "unmatched_schedule"
    if not exact:
        return "unmatched_or_partial"
    if not oracle["checks"]:
        return "target_lost_or_owner_changed"
    if oracle["throws"]:
        return "target_exception_candidate"
    return "target_retained_nonfatal"


def verify_trial(number: int, state_trial: dict, ledger: dict,
                 campaign_exact, report: dict) -> dict:
    label = f"trial-{number:03d}"
    directory = HERE / label
    result = {"trial": number, "run": label, "errors": [], "warnings": []}
    if not directory.is_dir():
        error(result, "missing trial directory: " + str(directory))
        return result
    manifest = read_json(directory / "manifest.json", result)
    trace = read_trace(directory / "runtime_trace.jsonl", result)
    plan = read_plan(HERE / (label + ".plan.tsv"), result)
    if manifest:
        if manifest.get("test") != EXPECTED_TEST:
            error(result, "manifest test is not the unchanged original HA JUnit")
        if (manifest.get("instrumented") is not True
                or manifest.get("graphchecker_runtime_used") is not False):
            error(result, "manifest instrumentation provenance mismatch")
        if not isinstance(manifest.get("elapsed_seconds"), (int, float)) \
                or manifest["elapsed_seconds"] <= 0:
            error(result, "invalid manifest elapsed_seconds")
        if not isinstance(manifest.get("returncode"), int):
            error(result, "invalid manifest returncode")
        resources = manifest.get("test_resources")
        if not resources or not str(resources).endswith("hadoop-hdfs/src/test/resources"):
            error(result, "missing original HDFS test resources")
        for field in ("trace", "log", "coverage", "plan"):
            recorded = manifest.get(field)
            if recorded and not Path(recorded).exists():
                warning(result, f"copied manifest has stale absolute {field} path: {recorded}")
    driver = (HERE / (label + "-driver.log") if number <= 3
              else directory / "driver.log")
    required = [directory / "junit.log", directory / "jacoco.exec", driver]
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            error(result, "missing or empty raw evidence: " + str(path))
    for category in COVERAGE:
        path = directory / ("covered_" + category + ".txt")
        if not path.is_file() or path.stat().st_size == 0:
            error(result, "missing or empty production coverage: " + str(path))
            continue
        count = sum(1 for _ in path.open())
        if manifest.get("covered_" + category + "_count") != count:
            error(result, f"manifest covered_{category}_count differs: "
                  f"{manifest.get('covered_' + category + '_count')} vs {count}")
    if plan != state_trial.get("sequence"):
        error(result, "plan selector differs from checkpoint sequence")
    try:
        ledger_plan = json.loads(ledger.get("selector", "[]"))
        if ledger_plan != plan:
            error(result, "plan selector differs from CSV ledger")
    except json.JSONDecodeError as exc:
        error(result, "invalid CSV selector JSON: " + str(exc))
    exact, applied = independent_exact(trace, plan) if plan else (False, [])
    if plan:
        try:
            campaign_result, _ = campaign_exact(trace, plan)
            if exact != campaign_result:
                error(result, "independent exact-injection result disagrees with ha_campaign")
        except Exception as exc:
            error(result, "ha_campaign.exact_injection raised: " + repr(exc))
    target = state_trial.get("target")
    oracle = independent_oracle(trace, target, exact, applied)
    matched_count = sum(row.get("event") == "FAULT_MATCHED" for row in trace)
    applied_count = sum(row.get("event") == "FAULT_APPLIED" for row in trace)
    status = expected_status(manifest, trace, exact, matched_count,
                             applied_count, oracle)
    comparison = {
        "junit_exit": manifest.get("returncode"),
        "matched_faults": matched_count,
        "applied_faults": applied_count,
        "exact_order_applied": exact,
        "post_fault_hdfs30_checks": len(oracle["checks"]),
        "hdfs30_true_checks": len(oracle["true_checks"]),
        "hdfs30_ioexception_throws": len(oracle["throws"]),
        "actual_target_root": oracle["actual_target_root"],
        "status": status,
        "bug_mark": ("candidate_needs_replay_source_review"
                     if oracle["throws"] else "none"),
    }
    for field, computed in comparison.items():
        if state_trial.get(field) != computed:
            error(result, f"checkpoint {field}: {state_trial.get(field)!r} != {computed!r}")
    for field, computed in (("junit_exit", manifest.get("returncode")),
                            ("matched_faults", matched_count),
                            ("applied_faults", applied_count),
                            ("exact_order_applied", exact),
                            ("target_checks_after_fault", len(oracle["checks"])),
                            ("target_true_checks", len(oracle["true_checks"])),
                            ("target_ioexception_throws", len(oracle["throws"])),
                            ("status", status),
                            ("bug_mark", comparison["bug_mark"]),
                            ("actual_target_root", oracle["actual_target_root"])):
        ledger_value = ledger.get(field, "")
        expected = "" if computed is None else str(computed)
        if ledger_value != expected:
            error(result, f"CSV {field}: {ledger_value!r} != {expected!r}")
    if manifest and state_trial.get("elapsed_seconds") != manifest.get("elapsed_seconds"):
        error(result, "checkpoint elapsed_seconds differs from manifest")
    if manifest and ledger.get("elapsed_seconds") != str(manifest.get("elapsed_seconds")):
        error(result, "CSV elapsed_seconds differs from manifest")
    result.update({"adapter_version": state_trial.get("adapter_version"),
                   "seed_run": state_trial.get("seed_run"),
                   "junit_exit": manifest.get("returncode"),
                   "elapsed_seconds": manifest.get("elapsed_seconds"),
                   "matched_faults": matched_count, "applied_faults": applied_count,
                   "strict_applied": exact,
                   "same_semantic_target_checks": len(oracle["checks"]),
                   "target_true_checks": len(oracle["true_checks"]),
                   "target_ioexception_throws": len(oracle["throws"]),
                   "seed_target_root": target.get("occurrenceAddress") if target else None,
                   "actual_target_root": oracle["actual_target_root"],
                   "status": status,
                   "raw_target_throws": sum(row.get("event") == "TARGET_THROW"
                                            and row.get("caseId") == "HDFS-30"
                                            for row in trace),
                   "trace_rows": len(trace),
                   "trace_seq_first": trace[0].get("seq") if trace else None,
                   "trace_seq_last": trace[-1].get("seq") if trace else None,
                   "sha256": {path.name: sha256(path) for path in
                              (directory / "manifest.json", directory / "runtime_trace.jsonl",
                               HERE / (label + ".plan.tsv"), directory / "jacoco.exec")
                              if path.is_file()}})
    return result


def verify_seed(directory: Path) -> dict:
    result = {"seed": directory.name, "errors": [], "warnings": []}
    manifest = read_json(directory / "manifest.json", result)
    trace = read_trace(directory / "runtime_trace.jsonl", result)
    for path in (directory / "junit.log", directory / "jacoco.exec"):
        if not path.is_file() or path.stat().st_size == 0:
            error(result, "missing or empty seed evidence: " + str(path))
    if manifest:
        if (manifest.get("test") != EXPECTED_TEST
                or manifest.get("instrumented") is not True
                or manifest.get("graphchecker_runtime_used") is not False):
            error(result, "seed original-JUnit instrumentation provenance mismatch")
        if (not isinstance(manifest.get("elapsed_seconds"), (int, float))
                or manifest["elapsed_seconds"] <= 0
                or not isinstance(manifest.get("returncode"), int)):
            error(result, "seed manifest has invalid time or return code")
        for category in COVERAGE:
            path = directory / ("covered_" + category + ".txt")
            if not path.is_file() or path.stat().st_size == 0:
                error(result, "missing or empty seed coverage: " + str(path))
            elif manifest.get("covered_" + category + "_count") != sum(
                    1 for _ in path.open()):
                error(result, "seed coverage count differs: " + category)
    result.update({"junit_exit": manifest.get("returncode"),
                   "elapsed_seconds": manifest.get("elapsed_seconds"),
                   "trace_rows": len(trace),
                   "trace_seq_first": trace[0].get("seq") if trace else None,
                   "trace_seq_last": trace[-1].get("seq") if trace else None,
                   "sha256": {path.name: sha256(path) for path in
                              (directory / "manifest.json", directory / "runtime_trace.jsonl",
                               directory / "jacoco.exec") if path.is_file()}})
    return result


def main() -> int:
    report = {"schema_version": 1, "audited_at_utc":
              datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "test": EXPECTED_TEST, "target_site": TARGET_SITE,
              "errors": [], "warnings": [], "trials": [], "seeds": []}
    for directory in sorted(HERE.glob("healthy*")):
        if not directory.is_dir():
            continue
        seed = verify_seed(directory)
        report["seeds"].append(seed)
        report["errors"].extend(f"{directory.name}: {message}"
                                for message in seed["errors"])
        report["warnings"].extend(f"{directory.name}: {message}"
                                  for message in seed["warnings"])
    if {seed["seed"] for seed in report["seeds"]} != {
            "healthy", "healthy-b", "healthy-node2", "healthy-active1-v2"}:
        error(report, "healthy seed set differs from four original runs")
    if any(seed["seed"] == "healthy-active1-v2" and seed["junit_exit"] != 0
           for seed in report["seeds"]):
        error(report, "selected active1-v2 healthy seed did not pass original JUnit")
    state = read_json(HERE / "ha-campaign-state.json", report)
    summary = read_json(HERE / "ha-campaign-summary.json", report)
    ledger_path = HERE / "ha-trial-ledger.csv"
    if not ledger_path.is_file():
        error(report, "missing CSV ledger")
        ledger = {}
    else:
        with ledger_path.open(newline="") as stream:
            ledger = {int(row["trial"]): row for row in csv.DictReader(stream)}
    completed = state.get("completed", [])
    if (len(completed) != 24 or state.get("active") is not None
            or state.get("stop_reason") != "attempt_budget_reached"):
        error(report, "campaign is not a completed 24/24 checkpoint")
    state_by_number = {row.get("trial"): row for row in completed}
    if (set(state_by_number) != set(range(1, 25))
            or set(ledger) != set(range(1, 25))):
        error(report, "checkpoint or CSV trial numbers are not exactly 1..24")
    campaign = runpy.run_path(str(HERE / "ha_campaign.py"))
    for number in range(1, 25):
        state_trial = state_by_number.get(number)
        ledger_row = ledger.get(number)
        if state_trial is None or ledger_row is None:
            continue
        trial = verify_trial(number, state_trial, ledger_row,
                             campaign["exact_injection"], report)
        report["trials"].append(trial)
        report["errors"].extend(f"trial-{number:03d}: {message}"
                                for message in trial["errors"])
        report["warnings"].extend(f"trial-{number:03d}: {message}"
                                  for message in trial["warnings"])
    counts = Counter(row["status"] for row in report["trials"])
    totals = {
        "attempts": len(report["trials"]),
        "legacy_pilots": sum(row["adapter_version"] == "pre_gate"
                             for row in report["trials"]),
        "active1_gate_v2_attempts": sum(row["adapter_version"] == "active1_gate_v2"
                                        for row in report["trials"]),
        "strict_applied": sum(row["strict_applied"] for row in report["trials"]),
        "target_retaining": sum(row["same_semantic_target_checks"] > 0
                                for row in report["trials"]),
        "target_exception_candidates": sum(row["target_ioexception_throws"] > 0
                                           for row in report["trials"]),
        "junit_elapsed_seconds": round(sum(row["elapsed_seconds"] or 0
                                           for row in report["trials"]), 3),
        "status_counts": dict(counts),
    }
    report["totals"] = totals
    report["completed_attempts"] = totals["attempts"]
    for field, computed in (("attempts_used", totals["attempts"]),
                            ("legacy_pilots", totals["legacy_pilots"]),
                            ("strict_applied", totals["strict_applied"]),
                            ("target_retaining", totals["target_retaining"]),
                            ("target_exception_candidates", totals["target_exception_candidates"]),
                            ("status_counts", totals["status_counts"])):
        if summary.get(field) != computed:
            error(report, f"summary {field}: {summary.get(field)!r} != {computed!r}")
    if summary.get("attempt_budget") != 24 or summary.get("stop_reason") != "attempt_budget_reached":
        error(report, "summary budget/stop reason mismatch")
    report["integrity_passed"] = not report["errors"]
    temporary = OUT.with_name(OUT.name + ".tmp")
    with temporary.open("w") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, OUT)
    print(json.dumps({"integrity_passed": report["integrity_passed"],
                      "totals": totals, "errors": len(report["errors"]),
                      "warnings": len(report["warnings"]),
                      "audit": str(OUT)}, sort_keys=True))
    return 0 if report["integrity_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
