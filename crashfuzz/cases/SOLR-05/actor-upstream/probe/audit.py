#!/usr/bin/env python3
"""Recompute the SOLR-05 upstream trial ledger from per-run artifacts."""

import hashlib
import json
from pathlib import Path

from feedback import (atomic_json, checked_target_identity, events, strict_sequence,
                      target_after, target_after_any_actor, target_counts)

CASE = Path(__file__).resolve().parents[1]
CAMPAIGN = CASE / "evidence/campaign"
SITE = "SOLR-05"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    state = json.loads((CAMPAIGN / "state.json").read_text())
    errors = []
    receipts = []
    for saved in state["trials"]:
        number = saved["number"]
        directory = CAMPAIGN / f"trial-{number:03d}"
        trace_path = directory / "events.tsv"
        trace = events(trace_path)
        manifest = json.loads((directory / "manifest.json").read_text())
        ledger = json.loads((directory / "trial.json").read_text())
        applied = [e for e in trace if e["kind"] == "IO_APPLIED_CONNECTION_LOSS"]
        final = applied[-1]["seq"] if applied else -1
        strict = strict_sequence(saved["plan"], trace) and checked_target_identity(trace)
        after, exception = target_after(trace, final)
        any_after, any_exception = target_after_any_actor(trace, final)
        observed = {
            "strict": strict,
            "faults_applied": len(applied),
            "target_checks": target_counts(trace),
            "target_after_fault": after,
            "target_exception": exception,
            "target_after_fault_any_actor": any_after,
            "target_exception_any_actor": any_exception,
            "junit_exit": manifest["exit_code"],
        }
        for key, value in observed.items():
            if saved.get(key) != value or ledger.get(key) != value:
                errors.append(f"trial {number}: {key} differs from raw trace/manifest")
        if manifest.get("identity_version") != "actor-upstream-writer-replica-v1":
            errors.append(f"trial {number}: wrong agent identity version")
        if manifest.get("faults") != ";".join(saved["plan"]):
            errors.append(f"trial {number}: manifest plan differs")
        if not (directory / "junit.log").exists() or not (directory / "jacoco.exec").exists():
            errors.append(f"trial {number}: missing JUnit log or JaCoCo raw data")
        receipts.append({
            "trial": number, "strict": strict, "postfault_target": after[SITE],
            "target_exception": exception[SITE], "applied": len(applied),
            "elapsed_seconds": saved["elapsed_seconds"],
            "trace_sha256": digest(trace_path),
            "junit_log_sha256": digest(directory / "junit.log"),
            "jacoco_sha256": digest(directory / "jacoco.exec"),
        })
    if state.get("inflight") is not None:
        errors.append("Campaign still has an inflight trial")
    result = {
        "identity_version": "actor-upstream-writer-replica-v1",
        "state_sha256": digest(CAMPAIGN / "state.json"),
        "attempts": len(receipts),
        "strict": sum(x["strict"] for x in receipts),
        "effective": sum(x["strict"] and x["postfault_target"] for x in receipts),
        "target_exception_candidates": sum(x["strict"] and x["postfault_target"] and
                                           x["target_exception"] for x in receipts),
        "stop_reason": state["site_progress"][SITE]["stop_reason"],
        "errors": errors, "trials": receipts,
    }
    atomic_json(CAMPAIGN / "audit.json", result)
    if errors:
        raise RuntimeError("SOLR-05 upstream raw audit: " + "; ".join(errors))
    print(json.dumps({key: result[key] for key in (
        "attempts", "strict", "effective", "target_exception_candidates", "stop_reason")},
        sort_keys=True))


if __name__ == "__main__":
    main()
