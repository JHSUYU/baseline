#!/usr/bin/env python3
"""Promote only HDFS-48's independently actor-joined historical evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from audit_heartbeat_actor import CASE, HERE, LEDGER


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    actor_path = HERE / "heartbeat-actor-audit.json"
    coverage_path = HERE / "heartbeat-actor-coverage.json"
    actor = json.loads(actor_path.read_text())
    coverage = json.loads(coverage_path.read_text())
    ledger = list(csv.DictReader(LEDGER.open()))
    ids = actor["admitted_trial_ids"]
    first80 = actor["raw_trial_receipts"][:80]
    last8 = coverage["first_80_last_8"]
    if (len(ledger) != 183 or len(ids) != 107 or len(first80) != 80
            or [row["trial"] for row in first80] != ids[:80]
            or [row["trial"] for row in last8] != ids[72:80]
            or ids[79] != 153):
        raise AssertionError("actor audit and coverage order disagree")
    if any(row["junit_returncode"] != 0 for row in actor["raw_trial_receipts"]):
        raise AssertionError("admitted original JUnit failure")
    if (coverage["late_exact_probe_novelty"]
            or coverage["late_method_or_branch_novelty"]
            or any(row["new_exact_probes"] or row["new_methods"]
                   or row["new_branch_count_buckets"] for row in last8)):
        raise AssertionError("base budget has late coverage novelty")
    if any(int(row["new_io_families"]) for row in ledger
           if int(row["trial"]) in set(ids[72:80])):
        raise AssertionError("base budget has late I/O novelty")
    healthy_elapsed = json.loads((CASE / "independent/evidence/instrumented-healthy-01/manifest.json").read_text())["elapsed_seconds"]
    result_path = CASE / "result.json"
    result = json.loads(result_path.read_text())
    if result["case_id"] != "HDFS-48":
        raise AssertionError("wrong result")
    if "prior_quality_review" not in result:
        result["prior_quality_review"] = result.pop("quality_review")
    result["legacy_coarse_actor"] = {
        "historical_attempts": 183,
        "historical_target_retaining": 128,
        "historical_fully_applied": 179,
        "historical_coverage_gain": 2069,
        "note": "Coarse thread/ordinal counts are retained for provenance; 21 target-retaining trials without raw RPC endpoint join are excluded from current actor-identified counts."
    }
    result.update({
        "status": "quality_complete",
        "campaign_budget": {"base_effective": 80, "base_max_faults": 8,
                            "extension_effective": 128, "extension_max_faults": 10,
                            "extended": False},
        "fault_trials": 183,
        "fully_applied_trials": 107,
        "strict_injections": 107,
        "target_after_fault": 107,
        "effective_trials": 107,
        "max_faults": 2,
        "coverage_gain": coverage["at_107"]["exact_probes"] - coverage["healthy"]["exact_probes"],
        "coverage_gain_unit": "production_JaCoCo_exact_probe_ids",
        "selected_target_throws": 0,
        "stop_reason": "base_80_effective_met_without_last_8_coverage_or_io_novelty; 27 additional historical actor-joined trials audited",
        "reason": "Archived original-JUnit raw traces independently join every admitted BPServiceActor exception to the sole NameNode RPC port and the selected postfault handler port. The first 80 actor-identified effective trials meet the base budget; the final eight add no exact production JaCoCo probe, method, branch-count bucket, or I/O family. No selected IllegalStateException occurred.",
        "actor_identity_audit": {
            "audit": str(actor_path.relative_to(CASE)),
            "audit_sha256": sha(actor_path),
            "coverage": str(coverage_path.relative_to(CASE)),
            "coverage_sha256": sha(coverage_path),
            "actor_joined_effective": 107,
            "excluded_unverified_target_retaining": 21,
            "first_80_ends_at_historical_attempt": 153,
            "first_80_junit_seconds": round(sum(row["elapsed_seconds"] for row in first80), 3),
            "budget_reached_elapsed_seconds": round(healthy_elapsed +
                                                    sum(float(row["elapsed_seconds"]) for row in ledger[:153]), 3),
            "first_80_exact_probe_gain": coverage["at_80"]["exact_probes"] - coverage["healthy"]["exact_probes"],
            "all_107_exact_probe_gain": coverage["at_107"]["exact_probes"] - coverage["healthy"]["exact_probes"],
            "last_8_exact_probe_gain": sum(row["new_exact_probes"] for row in last8),
            "late_io_family_gain": 0,
        },
    })
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(result_path)


if __name__ == "__main__":
    main()
