#!/usr/bin/env python3
"""Independently check HDFS-40 actor-aware trial evidence, read-only."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import sys


BASE = Path(__file__).resolve().parents[1]
CASE = BASE.parents[1]
CAMP = BASE / "campaign"
TEST = "org.apache.hadoop.hdfs.TestFileAppend#testFailedAppendBlockRejection"
SITE = "FSDirAppendOp.appendFile:136-139"
BLOCK = 1073741825
POINT = ("marker", "api", "endpoint", "ordinal")
SELECTOR = POINT + ("exception",)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def trace(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    if [row.get("seq") for row in rows] != list(range(1, len(rows) + 1)):
        raise ValueError(f"noncontiguous trace: {path}")
    return rows


def key(row: dict, fields: tuple[str, ...]) -> tuple:
    return tuple(row.get(field) for field in fields)


def point_id(row: dict) -> str:
    return "|".join(str(row.get(field)) for field in POINT)


def family_id(row: dict) -> str:
    return "|".join(str(row.get(field)) for field in POINT[:-1])


def io_relevant(row: dict) -> bool:
    if row.get("event") != "IO_OBSERVED":
        return False
    if row.get("marker") in ("RPC_SEND", "RPC_RESPONSE_WAIT"):
        return ("[append:/test]" in row.get("api", "") or
                "[blockReceivedAndDeleted:block=1073741825]" in row.get("api", ""))
    return row.get("marker") == "FILE_FLUSH" and row.get("api") == "editLog:durable"


def guards(rows: list[dict], after: int = -1) -> list[dict]:
    return [r for r in rows if r.get("event") == "TARGET_GUARD" and
            r.get("site") == SITE and r.get("path") == "/test" and
            r.get("blockId") == BLOCK and r.get("complete") is True and
            r["seq"] > after]


def target_throws(rows: list[dict], selected_guards: list[dict], after: int,
                  errors: list[str], name: str) -> list[dict]:
    fatal = {(g["path"], g["blockId"], g["ordinal"]): g
             for g in selected_guards if g.get("fatal") is True}
    exact = []
    for event in rows:
        if event.get("event") != "TARGET_EXCEPTION" or event.get("seq", -1) <= after:
            continue
        identity = (event.get("path"), event.get("blockId"), event.get("ordinal"))
        guard = fatal.get(identity)
        if guard is None or event.get("site") != SITE or event["seq"] <= guard["seq"]:
            continue
        message = event.get("message", "")
        matched = (event.get("type") == "java.io.IOException" and
                   event.get("fatal") is True and event.get("sufficient") is False and
                   message.startswith(f"append: lastBlock=blk_{BLOCK}_") and
                   message.endswith("of src=/test is not sufficiently replicated yet."))
        if matched:
            exact.append(event)
        else:
            errors.append(f"{name}: target throw fields/message differ at seq {event['seq']}")
    return exact


def check(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


def audit_queue_migration(state: dict, errors: list[str]) -> dict:
    receipt_path = CAMP / "client-send-prune.json"
    receipt = read(receipt_path)
    before_gz = CAMP / "checkpoint.before-client-send-prune.json.gz"
    after_gz = CAMP / receipt["after_backup_file"]
    before_bytes = gzip.decompress(before_gz.read_bytes())
    after_bytes = gzip.decompress(after_gz.read_bytes())
    before, after = json.loads(before_bytes), json.loads(after_bytes)
    queue_hash = lambda queue: digest(json.dumps(
        queue, sort_keys=True, separators=(",", ":")).encode())
    excluded = lambda item: any(
        point.get("marker") == "RPC_SEND" and
        "[append:/test]" in point.get("api", "")
        for point in item.get("sequence", []))
    check(digest(before_bytes) == receipt.get("checkpoint_before_sha256") and
          digest(after_bytes) == receipt.get("checkpoint_after_sha256") and
          digest(before_gz.read_bytes()) == receipt.get("backup_sha256") and
          digest(after_gz.read_bytes()) == receipt.get("after_backup_sha256"),
          errors, "queue migration checkpoint hashes differ")
    check(queue_hash(before["queue"]) == receipt.get("queue_before_sha256") and
          queue_hash(after["queue"]) == receipt.get("queue_after_sha256"),
          errors, "queue migration queue hashes differ")
    filtered = [item for item in before["queue"] if not excluded(item)]
    check(after["queue"] == filtered and
          receipt.get("queue_before") == len(before["queue"]) and
          receipt.get("queue_after") == len(filtered) and
          receipt.get("queue_removed") == len(before["queue"]) - len(filtered),
          errors, "queue migration filter/count differs")
    check(before.get("active") is None and after.get("active") is None and
          len(before["completed"]) == 46 and
          before["completed"] == after["completed"] == state["completed"][:46],
          errors, "queue migration changed completed trials")
    check(state.get("selection_policy_version") ==
          "actor_v2_exclude_uncaught_append_send" and
          not any(excluded(item) for item in state.get("queue", [])),
          errors, "current queue reintroduced excluded append sends")
    return {"receipt_sha256": digest(receipt_path.read_bytes()),
            "queue_before": len(before["queue"]),
            "queue_after": len(after["queue"]),
            "removed": len(before["queue"]) - len(after["queue"])}


def audit_budget_migration(state: dict, errors: list[str]) -> dict:
    receipt_path = CAMP / "actor-budget-migration.json"
    receipt = read(receipt_path)
    before_gz = CAMP / "checkpoint.before-actor-budget.json.gz"
    after_gz = CAMP / "checkpoint.after-actor-budget.json.gz"
    before_bytes = gzip.decompress(before_gz.read_bytes())
    after_bytes = gzip.decompress(after_gz.read_bytes())
    before, after = json.loads(before_bytes), json.loads(after_bytes)
    check(digest(before_bytes) == receipt.get("checkpoint_before_sha256") and
          digest(after_bytes) == receipt.get("checkpoint_after_sha256") and
          digest(before_gz.read_bytes()) == receipt.get("before_backup_sha256") and
          digest(after_gz.read_bytes()) == receipt.get("after_backup_sha256"),
          errors, "actor budget migration checkpoint hashes differ")
    check(before.get("active") is None and after.get("active") is None and
          len(before["completed"]) == 52 and
          before["completed"] == after["completed"] == state["completed"][:52] and
          before["queue"] == after["queue"], errors,
          "actor budget migration changed queue or completed trials")
    check(before.get("budget") == {"max_attempts": 67, "max_faults": 8} and
          after.get("budget") == {"max_attempts": 80, "max_faults": 8} and
          before.get("extension") == {"max_attempts": 115, "max_faults": 10} and
          after.get("extension") == {"max_attempts": 128, "max_faults": 10} and
          state.get("budget_policy_version") ==
          "actor_aware_budget_80_plus_13_separate_pilot", errors,
          "actor budget migration values differ")
    return {"receipt_sha256": digest(receipt_path.read_bytes()),
            "completed_at_migration": 52,
            "actor_budget": 80, "actor_extension": 128,
            "semantic_pilot_separate": 13}


def audit_result_migration(state: dict, errors: list[str]) -> dict:
    receipt_path = CAMP / "actor-only-result-counters.json"
    receipt = read(receipt_path)
    before_gz = CAMP / "result.before-actor-only-counters.json.gz"
    after_gz = CAMP / "result.after-actor-only-counters.json.gz"
    before_bytes = gzip.decompress(before_gz.read_bytes())
    after_bytes = gzip.decompress(after_gz.read_bytes())
    before, after = json.loads(before_bytes), json.loads(after_bytes)
    check(digest(before_bytes) == receipt.get("result_before_sha256") and
          digest(after_bytes) == receipt.get("result_after_sha256") and
          digest(before_gz.read_bytes()) == receipt.get("before_backup_sha256") and
          digest(after_gz.read_bytes()) == receipt.get("after_backup_sha256"),
          errors, "actor-only result migration hashes differ")
    check(len(state["completed"]) >= 70 and
          after.get("fault_trials") == 70 and
          before.get("fault_trials") == 83 and
          after.get("semantic_single_fault_pilot", {}).get("attempts") == 13 and
          after.get("fault_trials") + 13 == before.get("fault_trials") and
          after.get("total_elapsed_seconds_all_phases") ==
          before.get("elapsed_seconds"), errors,
          "actor-only result migration counters differ")
    return {"receipt_sha256": digest(receipt_path.read_bytes()),
            "actor_attempts_at_migration": 70,
            "pilot_attempts_excluded": 13}


def audit_extension_decision(state: dict, errors: list[str]) -> dict:
    receipt_path = CAMP / "extension-decision-080.json"
    receipt = read(receipt_path)
    first_eighty = state.get("completed", [])[:80]
    valid = [row for row in first_eighty if row.get("strict_injection") and
             row.get("target_after_fault")]
    window = []
    for row in valid[-8:]:
        window.append({
            "trial": row["trial"],
            "new_methods": [item for item in row["new_coverage_ids"]
                            if item.startswith("METHOD\t")],
            "new_branch_units": [item for item in row["new_coverage_ids"]
                                 if item.startswith("BRANCH_UNIT\t")],
            "new_io_families": row["new_io_family_ids"],
        })
    trigger = [item["trial"] for item in window if
               item["new_methods"] or item["new_branch_units"] or
               item["new_io_families"]]
    audit_path = CAMP / "audit_snapshot_080.json"
    check(len(first_eighty) == 80 and receipt.get("last_eight_valid") == window and
          receipt.get("extension_trigger_trials") == trigger == [76] and
          digest(audit_path.read_bytes()) == receipt.get("audit_snapshot_sha256"),
          errors, "actor 80 extension decision window differs")
    check(receipt.get("actor_strict_injections") == 75 and
          receipt.get("actor_target_retaining") == 74 and
          receipt.get("actor_target_exception_candidates") == 0,
          errors, "actor 80 extension count differs")
    if state.get("extended"):
        check(state.get("budget") == {"max_attempts": 128, "max_faults": 10},
              errors, "extended budget differs from decision")
    return {"receipt_sha256": digest(receipt_path.read_bytes()),
            "trigger_trials": trigger, "window_trials": [item["trial"] for item in window]}


def audit_trial(number: int, row: dict, coverage_union: set[str],
                io_union: set[str], family_union: set[str], errors: list[str]) -> dict:
    name = f"trial-{number:03d}"
    out = CAMP / name
    paths = {label: out / filename for label, filename in (
        ("manifest", "manifest.json"), ("trace", "trace/runtime_trace.jsonl"),
        ("jacoco", "jacoco.exec"), ("junit", "junit.log.gz"),
        ("coverage", "coverage.tsv.gz"), ("row", "trial-result.json"))}
    plan = CAMP / "plans" / (name + ".tsv")
    missing = [label for label, path in paths.items() if not path.is_file()]
    if not plan.is_file():
        missing.append("plan")
    if missing:
        errors.append(f"{name}: missing {missing}")
        return {"trial": number, "missing": missing}
    stored = read(paths["row"])
    check(stored == row, errors, f"{name}: checkpoint and trial row differ")
    check(row.get("trial") == number and row.get("id") == name, errors,
          f"{name}: trial number/ID differ")
    sequence = row.get("sequence", [])
    check(bool(sequence), errors, f"{name}: empty selector sequence")
    sequence_id = digest(json.dumps(sequence, sort_keys=True,
                                   separators=(",", ":")).encode())[:20]
    check(row.get("sequence_id") == sequence_id, errors,
          f"{name}: selector sequence hash differs")
    expected_plan = "".join("\t".join(str(p[k]) for k in SELECTOR) + "\n"
                            for p in sequence)
    check(plan.read_text() == expected_plan, errors, f"{name}: plan differs")
    manifest = read(paths["manifest"])
    check(manifest.get("test") == TEST and manifest.get("compile_exit") == 0 and
          manifest.get("probe") is True and manifest.get("coverage") is True,
          errors, f"{name}: not the original instrumented JUnit")
    check(row.get("junit_exit") == manifest.get("exit"), errors,
          f"{name}: JUnit exit differs")
    check(row.get("elapsed_seconds", -1) + .001 >= manifest.get("elapsed_seconds", 1e20),
          errors, f"{name}: elapsed time shorter than JUnit")
    check(paths["jacoco"].stat().st_size > 0, errors, f"{name}: empty JaCoCo raw data")
    try:
        junit_log = gzip.decompress(paths["junit"].read_bytes()).decode(errors="replace")
        check((f"ORIGINAL_JUNIT_PASS {TEST}" in junit_log) ==
              (manifest.get("exit") == 0), errors,
              f"{name}: original JUnit pass marker/exit differ")
    except OSError as error:
        errors.append(f"{name}: unreadable JUnit gzip: {error}")
    rows = trace(paths["trace"])
    roles = {r.get("role") for r in rows if r.get("event") == "DN_ROLE_MAP"}
    check(roles == {"dn0", "dn1", "dn2"}, errors,
          f"{name}: physical DataNode map incomplete")
    matched = [r for r in rows if r.get("event") == "FAULT_MATCHED"]
    applied = [r for r in rows if r.get("event") == "FAULT_APPLIED"]
    requested = [key(p, SELECTOR) for p in sequence]
    actual = [key(p, SELECTOR) for p in applied]
    for event in matched:
        preceding = rows[event["seq"] - 2] if event["seq"] >= 2 else {}
        following = rows[event["seq"]] if event["seq"] < len(rows) else {}
        check(preceding.get("event") == "IO_OBSERVED" and
              key(preceding, POINT) == key(event, POINT) and
              following.get("event") == "FAULT_APPLIED" and
              key(following, POINT) == key(event, POINT), errors,
              f"{name}: fault lacks adjacent observed/matched/applied events")
    actor_identity = all(
        "blockReceivedAndDeleted" not in p["api"] or
        (p["endpoint"].startswith("nn0<-") and p["endpoint"].split("<-")[-1] in roles)
        for p in sequence)
    observed_source = all(
        p.get("phase") == "afterDn0Stop" and
        ("blockReceivedAndDeleted" not in p.get("api", "") or
         p.get("sourceRole") == p.get("endpoint", "").split("<-")[-1])
        for p in applied)
    strict = (actual == requested and len(matched) == len(requested) and
              actor_identity and observed_source)
    after = max((p["seq"] for p in applied), default=-1)
    post = guards(rows, after) if after >= 0 else []
    exact_throws = target_throws(rows, post, after, errors, name)
    candidate = strict and bool(post) and bool(exact_throws)
    status = ("unmatched_or_partial" if not strict else
              "target_exception_candidate" if candidate else
              "lost_target" if not post else
              "workload_timeout" if manifest["exit"] == 124 else "checked")
    compressed = paths["coverage"].read_bytes()
    plain = gzip.decompress(compressed)
    check(digest(plain) == row.get("coverage_tsv_sha256"), errors,
          f"{name}: coverage export hash differs")
    covered_lines = [line for line in plain.decode().splitlines() if line]
    covered = set(covered_lines)
    check(len(covered) == len(covered_lines), errors,
          f"{name}: duplicate coverage IDs")
    observed = [p for p in rows if io_relevant(p)]
    admitted = strict and bool(post)
    new_coverage = covered - coverage_union if admitted else set()
    new_io = {point_id(p) for p in observed} - io_union if admitted else set()
    new_families = {family_id(p) for p in observed} - family_union if admitted else set()
    expected = {
        "matched_faults": len(matched), "applied_faults": len(applied),
        "strict_injection": strict, "actor_identity_confirmed": actor_identity,
        "observed_source_confirmed": observed_source,
        "last_applied_seq": after, "target_after_fault": bool(post),
        "post_fault_guard_ordinals": [p["ordinal"] for p in post],
        "post_fault_fatal_count": sum(p["fatal"] for p in post),
        "post_fault_target_exception_count": len(exact_throws),
        "status": status, "bug_mark": "candidate" if candidate else "none",
        "coverage_ids": len(covered), "new_coverage_ids": sorted(new_coverage),
        "new_coverage_count": len(new_coverage),
        "new_io_point_ids": sorted(new_io),
        "new_io_family_ids": sorted(new_families),
        "source_role_map": sorted(roles),
    }
    for label, value in expected.items():
        check(row.get(label) == value, errors, f"{name}: {label} differs from raw evidence")
    for label, field in (("trace", "trace"), ("jacoco", "jacoco"),
                         ("junit", "junit_log_gzip"), ("manifest", "manifest")):
        check(Path(row.get(field, "")).resolve() == paths[label].resolve(), errors,
              f"{name}: {field} points elsewhere")
    coverage_union.update(new_coverage)
    io_union.update(new_io)
    family_union.update(new_families)
    artifact_hashes = {label: digest(path.read_bytes())
                       for label, path in paths.items()}
    artifact_hashes["plan"] = digest(plan.read_bytes())
    return {"trial": number, "status": status, "strict": strict,
            "target_after_fault": bool(post), "target_exception_candidate": candidate,
            "source_roles": sorted(roles), "coverage_gain": len(new_coverage),
            "artifact_sha256": artifact_hashes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    errors: list[str] = []
    checkpoint_bytes = (CAMP / "checkpoint.json").read_bytes()
    state = json.loads(checkpoint_bytes)
    check(state.get("case_id") == "HDFS-40" and state.get("seed_test") == TEST,
          errors, "wrong checkpoint/JUnit identity")
    queue_migration = audit_queue_migration(state, errors)
    budget_migration = audit_budget_migration(state, errors)
    result_migration = audit_result_migration(state, errors)
    extension_decision = audit_extension_decision(state, errors)
    if args.final:
        check(state.get("stop_reason") is not None and state.get("active") is None,
              errors, "campaign has not stopped at a clean checkpoint")
    provenance_path = BASE / "source-provenance.json"
    provenance = read(provenance_path)
    for rel, expected in provenance["case_local_files_sha256"].items():
        path = BASE / rel
        check(path.is_file() and digest(path.read_bytes()) == expected, errors,
              f"source provenance mismatch: {rel}")
    seed = BASE / "healthy/actor-seed"
    seed_manifest = read(seed / "manifest.json")
    seed_rows = trace(seed / "trace/runtime_trace.jsonl")
    seed_guards = guards(seed_rows)
    check(seed_manifest.get("test") == TEST and seed_manifest.get("exit") == 0 and
          len(seed_guards) == 3 and not any(g.get("fatal") for g in seed_guards),
          errors, "healthy original JUnit target calibration differs")
    check({r.get("role") for r in seed_rows if r.get("event") == "DN_ROLE_MAP"} ==
          {"dn0", "dn1", "dn2"}, errors, "healthy physical role mapping incomplete")
    coverage_union = set((seed / "coverage.tsv").read_text().splitlines())
    io_union = {point_id(p) for p in seed_rows if io_relevant(p)}
    family_union = {family_id(p) for p in seed_rows if io_relevant(p)}
    completed = state.get("completed", [])
    limit = min(args.limit, len(completed)) if args.limit else len(completed)
    summaries = []
    for number, row in enumerate(completed[:limit], 1):
        try:
            summaries.append(audit_trial(number, row, coverage_union,
                                         io_union, family_union, errors))
        except (OSError, ValueError, TypeError, KeyError, EOFError) as error:
            errors.append(f"trial-{number:03d}: audit could not parse evidence: {error}")
    ledger_path = CAMP / "trial-ledger.csv"
    ledger_bytes = ledger_path.read_bytes()
    ledger_rows = list(csv.DictReader(ledger_bytes.decode().splitlines()))
    check(len(ledger_rows) >= limit, errors,
          "trial ledger has fewer rows than audited checkpoint prefix")
    if args.final:
        check(len(ledger_rows) == len(completed), errors,
              "final trial ledger/checkpoint counts differ")
    for index, ledger_row in enumerate(ledger_rows[:limit]):
        checkpoint_row = completed[index]
        for field in ("trial", "id", "status", "requested_faults",
                      "matched_faults", "applied_faults", "strict_injection",
                      "target_after_fault", "post_fault_fatal_count",
                      "post_fault_target_exception_count", "junit_exit",
                      "elapsed_seconds", "new_coverage_count", "bug_mark",
                      "sequence_id"):
            check(ledger_row.get(field) == str(checkpoint_row.get(field, "")),
                  errors, f"ledger row {index + 1} {field} differs")
        check(ledger_row.get("new_io_family_ids") == ";".join(
              checkpoint_row.get("new_io_family_ids", [])), errors,
              f"ledger row {index + 1} I/O families differ")
    if args.final:
        check(limit == len(completed), errors, "final audit used a truncated trial limit")
        legacy = read(BASE.parent / "campaign/checkpoint.json")["completed"]
        check(len(legacy) == 13 and all(len(r["sequence"]) == 1 for r in legacy),
              errors, "legacy semantic pilot changed")
        legacy_audit = read(BASE.parent / "campaign/audit_snapshot.json")
        check(legacy_audit.get("integrity_passed") is True and
              legacy_audit.get("completed_attempts") == 13, errors,
              "legacy pilot independent audit is missing or failed")
        published = read(CASE / "result.json")
        strict = sum(r.get("strict_injection") is True for r in completed)
        valid = sum(r.get("strict_injection") is True and r.get("target_after_fault") is True
                    for r in completed)
        for field, expected in (("fault_trials", len(completed)),
                                ("strict_injections", strict),
                                ("fully_applied_trials", strict),
                                ("target_after_fault", valid),
                                ("strict_physical_identity_trials", strict),
                                ("target_after_fault_physical_identity_trials", valid)):
            check(published.get(field) == expected, errors,
                  f"published result {field} differs")
        valid_rows = [row for row in completed if row.get("strict_injection") and
                      row.get("target_after_fault")]
        for field, expected in (
            ("target_retaining_junit_pass_trials",
             sum(row.get("junit_exit") == 0 for row in valid_rows)),
            ("target_retaining_junit_non_target_failure_trials",
             sum(row.get("junit_exit") != 0 and
                 row.get("post_fault_target_exception_count") == 0
                 for row in valid_rows)),
            ("junit_non_target_failure_trials",
             sum(row.get("junit_exit") != 0 and
                 row.get("post_fault_target_exception_count") == 0
                 for row in completed)),
            ("lost_target_trials",
             sum(row.get("strict_injection") and not row.get("target_after_fault")
                 for row in completed)),
            ("unmatched_or_partial_trials", len(completed) - strict)):
            check(published.get(field) == expected, errors,
                  f"published result {field} differs")
        actor_seconds = round(sum(read(path)["elapsed_seconds"] for path in
                                  (BASE / "healthy").glob("*/manifest.json")) +
                              sum(row["elapsed_seconds"] for row in completed), 3)
        pilot_seconds = round(sum(read(path)["elapsed_seconds"] for path in
                                  (BASE.parent / "healthy").glob("*/manifest.json")) +
                              sum(row["elapsed_seconds"] for row in legacy), 3)
        check(published.get("elapsed_seconds") == actor_seconds and
              published.get("total_elapsed_seconds_all_phases") ==
              round(actor_seconds + pilot_seconds, 3), errors,
              "published actor/all-phase elapsed seconds differ")
        pilot = published.get("semantic_single_fault_pilot", {})
        check(pilot.get("attempts") == 13 and
              pilot.get("elapsed_seconds") == pilot_seconds, errors,
              "published separate semantic pilot counts/time differ")
    report = {"case_id": "HDFS-40", "mode": "final" if args.final else "snapshot",
              "checkpoint_sha256": digest(checkpoint_bytes),
              "ledger_sha256": digest(ledger_bytes),
              "source_provenance_sha256": digest(provenance_path.read_bytes()),
              "queue_migration": queue_migration,
              "budget_migration": budget_migration,
              "result_migration": result_migration,
              "extension_decision": extension_decision,
              "healthy_seed_sha256": {
                  rel: digest((seed / rel).read_bytes()) for rel in
                  ("manifest.json", "trace/runtime_trace.jsonl", "jacoco.exec",
                   "coverage.tsv")},
              "audited_trials": limit, "completed_trials_at_snapshot": len(completed),
              "stop_reason": state.get("stop_reason"),
              "physical_identity_strict": sum(s.get("strict") is True for s in summaries),
              "target_retaining": sum(s.get("strict") is True and
                                      s.get("target_after_fault") is True for s in summaries),
              "target_exception_candidates": sum(
                  s.get("target_exception_candidate") is True for s in summaries),
              "junit_non_target_failures": sum(
                  row.get("junit_exit") != 0 and
                  row.get("post_fault_target_exception_count") == 0
                  for row in completed[:limit]),
              "trials": summaries, "errors": errors, "integrity_passed": not errors}
    body = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(body)
    else:
        sys.stdout.write(body)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
