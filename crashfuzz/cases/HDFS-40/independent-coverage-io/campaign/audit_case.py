#!/usr/bin/env python3
"""Read-only, independent audit of completed HDFS-40 fault trials.

The checkpoint is snapshotted once. Only completed rows are examined, so the
script can run while the owner is executing the next trial. It does not import
run_campaign.py or modify campaign state. Use --final after the campaign stops
to require a complete ledger and matching published result counters.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys


CASE = Path(__file__).resolve().parents[1]
CAMPAIGN = CASE / "campaign"
SEED = CASE / "healthy/campaign-seed"
STATE = CAMPAIGN / "checkpoint.json"
LEDGER = CAMPAIGN / "trial-ledger.csv"
RESULT = CASE.parent / "result.json"
PROVENANCE = CASE / "source-provenance.json"
TEST = "org.apache.hadoop.hdfs.TestFileAppend#testFailedAppendBlockRejection"
SITE = "FSDirAppendOp.appendFile:136-139"
TARGET_PATH = "/test"
TARGET_BLOCK = 1073741825
KEYS = ("marker", "api", "endpoint", "ordinal", "exception")
POINT_KEYS = KEYS[:-1]
LEDGER_FIELDS = ("trial", "id", "status", "requested_faults",
                 "matched_faults", "applied_faults", "strict_injection",
                 "target_after_fault", "post_fault_fatal_count",
                 "post_fault_target_exception_count", "junit_exit",
                 "elapsed_seconds", "new_coverage_count", "new_io_family_ids",
                 "bug_mark", "sequence_id")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def read_trace(path: Path) -> list[dict]:
    rows = []
    with path.open() as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_number}: {error}") from error
    if [row.get("seq") for row in rows] != list(range(1, len(rows) + 1)):
        raise ValueError(f"{path}: trace seq is not contiguous from 1")
    return rows


def read_coverage(path: Path) -> set[str]:
    with path.open() as stream:
        lines = [line.rstrip("\n") for line in stream if line.strip()]
    if len(lines) != len(set(lines)):
        raise ValueError(f"{path}: duplicate coverage identifiers")
    return set(lines)


def signature(row: dict, keys: tuple[str, ...] = KEYS) -> tuple:
    return tuple(row.get(key) for key in keys)


def point_id(row: dict) -> str:
    return "|".join(str(row.get(key)) for key in POINT_KEYS)


def family_id(row: dict) -> str:
    return "|".join(str(row.get(key)) for key in POINT_KEYS[:-1])


def relevant(row: dict) -> bool:
    if row.get("event") != "IO_OBSERVED":
        return False
    marker = row.get("marker")
    api = row.get("api", "")
    if marker in ("RPC_SEND", "RPC_RESPONSE_WAIT"):
        return ("[append:/test]" in api or
                "[blockReceivedAndDeleted:block=1073741825]" in api)
    return marker == "FILE_FLUSH" and api == "editLog:durable"


def target_guards(trace: list[dict], after_seq: int = -1) -> list[dict]:
    return [row for row in trace if row.get("event") == "TARGET_GUARD"
            and row.get("site") == SITE and row.get("path") == TARGET_PATH
            and row.get("blockId") == TARGET_BLOCK and row.get("complete") is True
            and row["seq"] > after_seq]


def sequence_id(sequence: list[dict]) -> str:
    value = json.dumps(sequence, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()[:20]


class Audit:
    def __init__(self, final: bool) -> None:
        self.final = final
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def check(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)


def validate_provenance(audit: Audit) -> dict[str, str]:
    provenance = read_json(PROVENANCE)
    audit.check(provenance.get("case_id") == "HDFS-40", "provenance case ID")
    audit.check(provenance.get("hadoop_release") == "3.4.3",
                "provenance Hadoop release")
    digests = {}
    for relative, expected in provenance["case_local_files_sha256"].items():
        path = CASE / relative
        if not path.is_file():
            audit.check(False, f"provenance missing {relative}")
            continue
        actual = sha256(path)
        digests[relative] = actual
        audit.check(actual == expected, f"provenance hash mismatch {relative}")
    return digests


def validate_policy_migration(audit: Audit, state: dict,
                              provenance: dict) -> dict:
    history = provenance.get("selection_policy_history", [])
    audit.check(len(history) == 2,
                "selection policy history must identify both driver revisions")
    if len(history) != 2:
        return {}
    old, new = history
    audit.check(old.get("version") == "observed_io_v1" and
                old.get("trials") == "1-7" and
                old.get("file_flush_entry_eligible") is True,
                "old selection policy metadata differs")
    audit.check(new.get("version") == "rpc_semantic_v2" and
                new.get("trials") == "8 onward" and
                new.get("file_flush_entry_eligible") is False,
                "new selection policy metadata differs")
    for revision in history:
        path = CASE / revision["driver"]
        audit.check(path.is_file(), f"policy driver missing: {path}")
        if path.is_file():
            audit.check(sha256(path) == revision.get("sha256"),
                        f"policy driver hash differs: {path}")
    migration = CASE / new.get("migration", "missing")
    audit.check(migration.is_file(), "selection policy migration receipt missing")
    if not migration.is_file():
        return {}
    audit.check(sha256(migration) == new.get("migration_sha256"),
                "selection policy migration receipt hash differs")
    receipt = read_json(migration)
    backup = CAMPAIGN / "checkpoint.before-file-gate.json.gz"
    audit.check(backup.is_file(), "pre-migration checkpoint backup missing")
    if not backup.is_file():
        return {}
    before_bytes = gzip.decompress(backup.read_bytes())
    before = json.loads(before_bytes)
    audit.check(hashlib.sha256(before_bytes).hexdigest() ==
                receipt.get("before_checkpoint_sha256"),
                "pre-migration checkpoint backup hash differs")
    audit.check(receipt.get("case_id") == "HDFS-40" and
                receipt.get("completed_trials_preserved") == 7 and
                len(before.get("completed", [])) == 7,
                "migration boundary is not exactly after trial 7")
    audit.check(before.get("active") is None and
                before.get("stop_reason") == "paused_by_case_owner",
                "migration backup is not a clean completed-trial boundary")
    audit.check(state.get("completed", [])[:7] == before.get("completed", []),
                "first seven checkpoint trial rows changed after migration")
    audit.check(state.get("selection_policy_version") == "rpc_semantic_v2",
                "checkpoint does not declare revised selection policy")
    audit.check(state.get("file_marker_status") ==
                "observed_only_method_entry_can_return_without_write",
                "checkpoint file-marker status differs")
    old_queue = before.get("queue", [])
    filtered = [item for item in old_queue if all(
        point.get("marker") != "FILE_FLUSH"
        for point in item.get("sequence", []))]
    audit.check(receipt.get("queue_before") == len(old_queue) and
                receipt.get("queue_after") == len(filtered) and
                receipt.get("file_sequences_removed") ==
                len(old_queue) - len(filtered),
                "migration queue counts do not match backup and filter")
    for number, row in enumerate(state.get("completed", []), 1):
        audit.check(all(point.get("marker") in
                        ("RPC_SEND", "RPC_RESPONSE_WAIT")
                        for point in row.get("sequence", [])),
                    f"trial-{number:03d}: non-RPC injection after policy migration")
    for item in state.get("queue", []) + ([state["active"]] if state.get("active")
                                           else []):
        audit.check(all(point.get("marker") in
                        ("RPC_SEND", "RPC_RESPONSE_WAIT")
                        for point in item.get("sequence", [])),
                    f"queued sequence {item.get('id')}: non-RPC injection")
    return {"receipt_sha256": sha256(migration),
            "backup_sha256": sha256(backup),
            "backup_uncompressed_sha256":
                hashlib.sha256(before_bytes).hexdigest(),
            "completed_at_migration": len(before["completed"]),
            "queue_before": len(old_queue),
            "queue_after_filter": len(filtered),
            "file_sequences_removed": len(old_queue) - len(filtered)}


def validate_junit(audit: Audit, name: str, out: Path, manifest: dict,
                   row: dict, plan: Path) -> None:
    audit.check(manifest.get("test") == TEST, f"{name}: wrong original JUnit")
    audit.check(manifest.get("compile_exit") == 0, f"{name}: compile failed")
    audit.check(manifest.get("probe") is True and
                manifest.get("coverage") is True,
                f"{name}: probe/coverage disabled")
    audit.check(manifest.get("timeout_seconds") == 180,
                f"{name}: JUnit timeout changed")
    audit.check(Path(manifest.get("fault_plan") or "").name == plan.name,
                f"{name}: manifest plan basename differs")
    for key, suffix in (("trace", f"/campaign/{name}/trace/runtime_trace.jsonl"),
                        ("jacoco_exec", f"/campaign/{name}/jacoco.exec"),
                        ("runtime_log", f"/campaign/{name}/logs/runtime.log")):
        audit.check(str(manifest.get(key, "")).endswith(suffix),
                    f"{name}: manifest {key} belongs to a different run")
    audit.check(manifest.get("exit") == row.get("junit_exit"),
                f"{name}: JUnit exit differs from checkpoint")
    audit.check(manifest.get("elapsed_seconds") ==
                row.get("junit_elapsed_seconds"),
                f"{name}: JUnit elapsed differs from checkpoint")
    audit.check(isinstance(row.get("elapsed_seconds"), (int, float)) and
                row["elapsed_seconds"] + 0.001 >= manifest.get("elapsed_seconds", 1e99),
                f"{name}: campaign elapsed shorter than JUnit")
    log_path = out / "junit.log.gz"
    try:
        with gzip.open(log_path, "rt", errors="replace") as stream:
            log = stream.read()
    except (OSError, EOFError) as error:
        audit.check(False, f"{name}: invalid JUnit log gzip: {error}")
        return
    passed = f"ORIGINAL_JUNIT_PASS {TEST}" in log
    audit.check(passed == (manifest.get("exit") == 0),
                f"{name}: JUnit pass marker/exit mismatch")


def fault_events(audit: Audit, name: str, trace: list[dict],
                 sequence: list[dict]) -> tuple[bool, int, int, int]:
    requested = [signature(point) for point in sequence]
    matched = [row for row in trace if row.get("event") == "FAULT_MATCHED"]
    applied = [row for row in trace if row.get("event") == "FAULT_APPLIED"]
    match_positions = [i for i, row in enumerate(trace)
                       if row.get("event") == "FAULT_MATCHED"]
    for index in match_positions:
        event = trace[index]
        preceding = trace[index - 1] if index > 0 else {}
        following = trace[index + 1] if index + 1 < len(trace) else {}
        audit.check(preceding.get("event") == "IO_OBSERVED" and
                    signature(preceding, POINT_KEYS) ==
                    signature(event, POINT_KEYS) and
                    preceding.get("thread") == event.get("thread"),
                    f"{name}: matched fault has no identical preceding I/O "
                    f"at trace seq {event.get('seq')}")
        audit.check(following.get("event") == "FAULT_APPLIED" and
                    signature(following, POINT_KEYS) ==
                    signature(event, POINT_KEYS) and
                    following.get("thread") == event.get("thread"),
                    f"{name}: matched fault has no identical following injection "
                    f"at trace seq {event.get('seq')}")
    observed_applied = [signature(row) for row in applied]
    audit.check(len(matched) == len(applied),
                f"{name}: matched/applied fault counts differ")
    audit.check(len(applied) <= len(requested),
                f"{name}: extra applied faults")
    audit.check(observed_applied == requested[:len(applied)],
                f"{name}: applied faults differ from ordered five-field plan prefix")
    audit.check([signature(row, POINT_KEYS) for row in matched] ==
                [signature(row, POINT_KEYS) for row in sequence[:len(matched)]],
                f"{name}: matched faults differ from ordered four-field plan prefix")
    strict = (observed_applied == requested and len(matched) == len(requested))
    last_fault = max((row["seq"] for row in applied), default=-1)
    return strict, len(matched), len(applied), last_fault


def exact_target_throws(audit: Audit, name: str, trace: list[dict],
                        guards: list[dict], last_fault: int) -> list[dict]:
    fatal_by_identity = {
        (g["site"], g["path"], g["blockId"], g["ordinal"]): g
        for g in guards if g.get("fatal") is True
    }
    exact = []
    for event in trace:
        if event.get("event") != "TARGET_EXCEPTION" or not (
                event.get("seq", -1) > last_fault >= 0):
            continue
        identity = (event.get("site"), event.get("path"),
                    event.get("blockId"), event.get("ordinal"))
        guard = fatal_by_identity.get(identity)
        if guard is None or event["seq"] <= guard["seq"]:
            continue
        message = event.get("message", "")
        expected_suffix = (f"of src={guard['path']} is not sufficiently "
                           "replicated yet.")
        if (event.get("type") == "java.io.IOException" and
                event.get("fatal") is True and
                event.get("complete") is True and
                event.get("sufficient") is False and
                message.startswith(f"append: lastBlock=blk_{guard['blockId']}_") and
                message.endswith(expected_suffix)):
            exact.append(event)
        else:
            audit.check(False, f"{name}: target exception at seq {event['seq']} "
                        "does not match exact IOException site and message")
    return exact


def ledger_value(row: dict, key: str) -> str:
    if key == "new_io_family_ids":
        return ";".join(row.get(key, []))
    return str(row.get(key, ""))


def audit_trial(audit: Audit, number: int, row: dict,
                union_cov: set[str], union_io: set[str],
                union_families: set[str]) -> tuple[dict, set[str], set[str], set[str]]:
    name = f"trial-{number:03d}"
    out = CAMPAIGN / name
    plan = CAMPAIGN / "plans" / f"{name}.tsv"
    required = {
        "plan": plan,
        "manifest": out / "manifest.json",
        "trace": out / "trace/runtime_trace.jsonl",
        "jacoco": out / "jacoco.exec",
        "coverage": out / "coverage.tsv",
        "junit_gzip": out / "junit.log.gz",
        "trial_result": out / "trial-result.json",
    }
    missing = [label for label, path in required.items() if not path.is_file()]
    audit.check(not missing, f"{name}: missing {', '.join(missing)}")
    if missing:
        return {"trial": number, "missing": missing}, set(), set(), set()
    hashes = {label: sha256(path) for label, path in required.items()}
    audit.check(required["jacoco"].stat().st_size > 0,
                f"{name}: empty JaCoCo execution data")
    stored = read_json(required["trial_result"])
    audit.check(stored == row, f"{name}: trial-result/checkpoint row differ")
    audit.check(row.get("trial") == number and row.get("id") == name,
                f"{name}: checkpoint numbering differs")
    sequence = row.get("sequence", [])
    audit.check(isinstance(sequence, list) and bool(sequence),
                f"{name}: empty/malformed sequence")
    audit.check(row.get("sequence_id") == sequence_id(sequence),
                f"{name}: sequence ID hash differs")
    expected_plan = "".join("\t".join(str(p[key]) for key in KEYS) + "\n"
                            for p in sequence)
    audit.check(plan.read_text() == expected_plan,
                f"{name}: five-field plan differs from checkpoint")
    manifest = read_json(required["manifest"])
    validate_junit(audit, name, out, manifest, row, plan)
    trace = read_trace(required["trace"])
    strict, matched, applied, last_fault = fault_events(
        audit, name, trace, sequence)
    context = row.get("context", {})
    audit.check(context.get("path") == TARGET_PATH and
                context.get("block_id") == TARGET_BLOCK,
                f"{name}: unexpected target context")
    guards = target_guards(trace, last_fault) if last_fault >= 0 else []
    same = [g for g in guards if g["path"] == context.get("path") and
            g["blockId"] == context.get("block_id")]
    throws = exact_target_throws(audit, name, trace, same, last_fault)
    candidate = strict and bool(same) and bool(throws)
    status = ("unmatched_or_partial" if not strict else
              "target_exception_candidate" if candidate else
              "lost_target" if not same else
              "workload_timeout" if manifest["exit"] == 124 else "checked")
    observed = [event for event in trace if relevant(event)]
    identifiers = read_coverage(required["coverage"])
    admitted = strict and bool(same)
    new_cov = identifiers - union_cov if admitted else set()
    new_io = {point_id(event) for event in observed} - union_io if admitted else set()
    new_families = ({family_id(event) for event in observed} - union_families
                    if admitted else set())
    expected = {
        "requested_faults": len(sequence), "matched_faults": matched,
        "applied_faults": applied, "strict_injection": strict,
        "last_applied_seq": last_fault, "target_after_fault": bool(same),
        "post_fault_guard_ordinals": [g["ordinal"] for g in same],
        "post_fault_fatal_count": sum(g["fatal"] for g in same),
        "post_fault_target_exception_count": len(throws),
        "status": status, "bug_mark": "candidate" if candidate else "none",
        "junit_exit": manifest["exit"],
        "junit_elapsed_seconds": manifest["elapsed_seconds"],
        "coverage_ids": len(identifiers),
        "new_coverage_ids": sorted(new_cov),
        "new_coverage_count": len(new_cov),
        "new_io_point_ids": sorted(new_io),
        "new_io_family_ids": sorted(new_families),
    }
    for key, value in expected.items():
        audit.check(row.get(key) == value,
                    f"{name}: {key} differs from raw evidence")
    for key, path in (("trace", required["trace"]),
                      ("jacoco", required["jacoco"]),
                      ("junit_log_gzip", required["junit_gzip"]),
                      ("manifest", required["manifest"])):
        audit.check(Path(row.get(key, "")).resolve() == path.resolve(),
                    f"{name}: {key} points to different evidence")
    result = {"trial": number, "status": status, "strict": strict,
              "target_after_fault": bool(same), "candidate": candidate,
              "trace_events": len(trace), "coverage_ids": len(identifiers),
              "new_coverage_ids": len(new_cov), "artifact_sha256": hashes}
    return result, new_cov, new_io, new_families


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final", action="store_true",
                        help="require stopped campaign and fully published ledger")
    parser.add_argument("--output", type=Path,
                        help="write audit JSON; default is stdout only")
    args = parser.parse_args()
    audit = Audit(args.final)
    checkpoint_bytes = STATE.read_bytes()  # one atomic checkpoint snapshot
    checkpoint_sha = hashlib.sha256(checkpoint_bytes).hexdigest()
    state = json.loads(checkpoint_bytes)
    audit.check(state.get("case_id") == "HDFS-40" and
                state.get("seed_test") == TEST,
                "checkpoint belongs to another case/JUnit")
    if args.final:
        audit.check(state.get("stop_reason") is not None,
                    "final audit requested while campaign is still running")
        audit.check(state.get("active") is None,
                    "final audit has active in-progress trial")
    provenance = validate_provenance(audit)
    policy_migration = validate_policy_migration(
        audit, state, read_json(PROVENANCE))
    seed_manifest = read_json(SEED / "manifest.json")
    seed_trace = read_trace(SEED / "trace/runtime_trace.jsonl")
    seed_cov = read_coverage(SEED / "coverage.tsv")
    audit.check(seed_manifest.get("test") == TEST and
                seed_manifest.get("exit") == 0,
                "healthy seed is not the passing original JUnit")
    seed_guards = target_guards(seed_trace)
    audit.check(len(seed_guards) >= 2 and not any(g.get("fatal") for g in seed_guards),
                "healthy seed lacks repeated nonfatal target checks")
    audit.check(not any(g.get("event") == "TARGET_EXCEPTION" for g in seed_trace),
                "healthy seed already throws target exception")
    audit.check(state.get("seed_guards") == len(seed_guards),
                "checkpoint healthy guard count differs")
    seed_io = [event for event in seed_trace if relevant(event)]
    before_last = sum(event["seq"] < seed_guards[-1]["seq"] for event in seed_io)
    audit.check(state.get("seed_relevant_io") == before_last,
                "checkpoint healthy relevant I/O count differs")
    control = CASE / "healthy/append4-expected-fatal"
    control_manifest = read_json(control / "manifest.json")
    control_trace = read_trace(control / "trace/runtime_trace.jsonl")
    audit.check(control_manifest.get("test") ==
                "org.apache.hadoop.hdfs.TestFileAppend4#testAppendInsufficientLocations"
                and control_manifest.get("exit") == 0,
                "expected-fatal oracle control did not pass its original JUnit")
    control_pairs = [
        (guard, event) for guard in control_trace for event in control_trace
        if guard.get("event") == "TARGET_GUARD" and
        guard.get("site") == SITE and guard.get("fatal") is True and
        guard.get("complete") is True and guard.get("sufficient") is False and
        event.get("event") == "TARGET_EXCEPTION" and
        event.get("seq") == guard.get("seq", -2) + 1 and
        (event.get("site"), event.get("path"), event.get("blockId"),
         event.get("ordinal")) ==
        (guard.get("site"), guard.get("path"), guard.get("blockId"),
         guard.get("ordinal")) and
        event.get("type") == "java.io.IOException" and
        event.get("message", "").startswith(
            f"append: lastBlock=blk_{guard.get('blockId')}_") and
        event.get("message", "").endswith(
            f"of src={guard.get('path')} is not sufficiently replicated yet.")]
    audit.check(bool(control_pairs),
                "expected-fatal control lacks exact guard/IOException pair")
    union_cov = set(seed_cov)
    union_io = {point_id(event) for event in seed_io}
    union_families = {family_id(event) for event in seed_io}
    completed = state.get("completed", [])
    trial_summaries = []
    for number, row in enumerate(completed, 1):
        try:
            summary, new_cov, new_io, new_families = audit_trial(
                audit, number, row, union_cov, union_io, union_families)
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
            audit.check(False, f"trial-{number:03d}: audit could not parse: {error}")
            summary, new_cov, new_io, new_families = (
                {"trial": number, "parse_error": str(error)}, set(), set(), set())
        trial_summaries.append(summary)
        union_cov.update(new_cov)
        union_io.update(new_io)
        union_families.update(new_families)
    if LEDGER.is_file():
        ledger_bytes = LEDGER.read_bytes()
        ledger_rows = list(csv.DictReader(ledger_bytes.decode().splitlines()))
        common = min(len(ledger_rows), len(completed))
        for index in range(common):
            for key in LEDGER_FIELDS:
                audit.check(ledger_rows[index].get(key) ==
                            ledger_value(completed[index], key),
                            f"ledger row {index + 1} field {key} differs")
        if len(ledger_rows) != len(completed):
            message = (f"ledger/checkpoint snapshot counts differ: "
                       f"{len(ledger_rows)} vs {len(completed)}")
            (audit.check(False, message) if args.final else audit.warning(message))
        ledger_sha = hashlib.sha256(ledger_bytes).hexdigest()
    else:
        ledger_rows, ledger_sha = [], None
        audit.check(False, "trial ledger is missing")
    if args.final:
        published = read_json(RESULT)
        valid = [row for row in completed if row.get("strict_injection") and
                 row.get("target_after_fault")]
        counts = {"fault_trials": len(completed),
                  "strict_injections": sum(row.get("strict_injection") is True
                                           for row in completed),
                  "target_after_fault": len(valid),
                  "target_exception_after_fault_trials": sum(
                      row.get("post_fault_target_exception_count", 0) > 0
                      for row in valid)}
        for key, value in counts.items():
            audit.check(published.get(key) == value,
                        f"published result {key} differs: {published.get(key)} vs {value}")
        delta = union_cov - seed_cov
        coverage_gain = {kind: sum(identifier.startswith(kind + "\t")
                                   for identifier in delta)
                         for kind in ("METHOD", "BRANCH_UNIT", "PROBE")}
        audit.check(published.get("coverage_gain") == coverage_gain,
                    "published cumulative coverage gain differs")
        expected_elapsed = round(sum(
            read_json(path)["elapsed_seconds"] for path in
            (CASE / "healthy").glob("*/manifest.json")) + sum(
            row["elapsed_seconds"] for row in completed), 3)
        audit.check(published.get("elapsed_seconds") == expected_elapsed,
                    "published elapsed seconds differ")
    report = {"case_id": "HDFS-40", "mode": "final" if args.final else "snapshot",
              "checkpoint_sha256": checkpoint_sha, "ledger_sha256": ledger_sha,
              "completed_attempts": len(completed),
              "checkpoint_active": state.get("active") is not None,
              "stop_reason": state.get("stop_reason"),
              "strict_injections": sum(row.get("strict_injection") is True
                                       for row in completed),
              "target_retaining_trials": sum(
                  row.get("strict_injection") is True and
                  row.get("target_after_fault") is True for row in completed),
              "target_exception_candidates": sum(
                  summary.get("candidate") is True for summary in trial_summaries),
              "seed_sha256": {label: sha256(SEED / relative) for label, relative in
                              (("manifest", "manifest.json"),
                               ("trace", "trace/runtime_trace.jsonl"),
                               ("coverage", "coverage.tsv"),
                               ("jacoco", "jacoco.exec"))},
              "expected_fatal_control_sha256": {
                  label: sha256(control / relative) for label, relative in
                  (("manifest", "manifest.json"),
                   ("trace", "trace/runtime_trace.jsonl"),
                   ("jacoco", "jacoco.exec"))},
              "provenance_verified_sha256": provenance,
              "policy_migration": policy_migration,
              "trials": trial_summaries,
              "errors": audit.errors, "warnings": audit.warnings,
              "integrity_passed": not audit.errors}
    body = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(body)
    else:
        sys.stdout.write(body)
    return 0 if not audit.errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
