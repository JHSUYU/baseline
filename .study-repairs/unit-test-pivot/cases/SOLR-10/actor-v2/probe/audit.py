#!/usr/bin/env python3
"""Recompute the shared campaign's per-check counts from retained raw receipts."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from feedback import (CASES, atomic_json, checked_target_identity, events,
                      strict_sequence, target_after, target_after_any_actor,
                      target_counts, target_relations)


CASE = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    state = json.loads((campaign / "state.json").read_text())
    issues = []
    effective = Counter()
    strict_count = 0
    target_exceptions = Counter()
    relations = {case: Counter() for case in CASES}
    raw = []
    for expected_number, saved in enumerate(state["trials"], 1):
        number = saved["number"]
        if number != expected_number:
            issues.append(f"trial numbering differs: {number} != {expected_number}")
        directory = campaign / f"trial-{number:03d}"
        trace_file, manifest_file = directory / "events.tsv", directory / "manifest.json"
        if not trace_file.exists() or not manifest_file.exists():
            issues.append(f"trial {number}: raw trace or manifest missing")
            continue
        trace = events(trace_file)
        manifest = json.loads(manifest_file.read_text())
        if manifest.get("build_receipt_sha256") != state.get("build_receipt_sha256"):
            issues.append(f"trial {number}: build digest differs from checkpoint")
        applied = [event for event in trace if event["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        final = max((event["seq"] for event in applied), default=-1)
        strict = strict_sequence(saved["plan"], trace) and checked_target_identity(trace)
        post, exception = target_after(trace, final)
        any_post, any_exception = target_after_any_actor(trace, final)
        relation = target_relations(trace, final)
        if strict != saved["strict"] or post != saved["target_after_fault"] or \
                exception != saved["target_exception"] or \
                any_post != saved["target_after_fault_any_actor"] or \
                any_exception != saved["target_exception_any_actor"] or \
                target_counts(trace) != saved["target_checks"] or \
                relation != saved.get("target_relations"):
            issues.append(f"trial {number}: raw event recount disagrees with saved trial")
        if strict:
            strict_count += 1
            for case in CASES:
                if post[case]:
                    effective[case] += 1
                    relations[case].update(relation[case])
                    if exception[case]:
                        target_exceptions[case] += 1
        raw.append({"trial": number, "trace_sha256": digest(trace_file),
                    "manifest_sha256": digest(manifest_file),
                    "junit_log_sha256": digest(directory / "junit.log"),
                    "jacoco_sha256": digest(directory / "jacoco.exec")
                    if (directory / "jacoco.exec").exists() else None,
                    "strict": strict, "effective": {case: bool(strict and post[case]) for case in CASES},
                    "elapsed_seconds": saved["elapsed_seconds"]})
    for case in CASES:
        if effective[case] != state["site_progress"][case]["effective"]:
            issues.append(f"{case}: raw effective {effective[case]} differs from checkpoint")
    result = {
        "campaign": str(campaign), "trial_count": len(state["trials"]),
        "strict_injections": strict_count,
        "effective": {case: effective[case] for case in CASES},
        "target_exception_candidates": {case: target_exceptions[case] for case in CASES},
        "runtime_relations": {case: dict(relations[case]) for case in CASES},
        "elapsed_seconds": round(sum(item["elapsed_seconds"] for item in raw), 3),
        "build_receipt_sha256": state.get("build_receipt_sha256"),
        "raw": raw, "issues": issues,
    }
    atomic_json(campaign / "audit.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "raw"},
                     sort_keys=True), flush=True)
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
