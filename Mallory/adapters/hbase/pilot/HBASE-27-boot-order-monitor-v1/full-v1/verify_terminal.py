#!/usr/bin/env python3
"""Classify an HBASE-27 terminal without treating path gaps as full completion."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

FULL_TERMINALS = {"budget_exhausted", "queue_exhausted"}
GAP_TERMINALS = {"healthy_no_injectable_door", "healthy_node_identity_missing",
                 "healthy_seed_ambiguous", "healthy_attestation_failed",
                 "fault_trials_not_attested"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(campaign: Path) -> None:
    summary_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    summary = json.loads(summary_path.read_text())
    audit = json.loads(audit_path.read_text())
    status = summary["status"]
    count = summary["fault_trials_completed"]
    if (summary["case_id"] != "HBASE-27" or
            audit["case_id"] != "HBASE-27" or
            status not in FULL_TERMINALS | GAP_TERMINALS or
            not 0 <= count <= 80 or
            audit["terminal_status"] != status or
            audit["trial_count"] != count + 1 or
            (status in FULL_TERMINALS and count == 0)):
        raise SystemExit("HBASE-27 has no consistent terminal")
    completed = status in FULL_TERMINALS
    verdict = {
        "schema_version": 1,
        "case_id": "HBASE-27",
        "kind": "natural_full_terminal" if completed else "path_or_attestation_gap",
        "status": status,
        "full_campaign_completed": completed,
        "fault_trials_completed": count,
        "budget": {"trials": 80, "seconds": 3600, "max_faults_per_trial": 3},
        "campaign_result_sha256": sha(summary_path),
        "offline_audit_sha256": sha(audit_path),
        "audit_report_gate_passed": audit.get("report_gate_passed"),
        "healthy_observed_path_doors": audit.get("healthy_observed_path_doors"),
        "same_actor_target_trials": audit.get("same_actor_target_trials"),
        "exact_exception_trials": summary.get("exact_exception_trials"),
        "completion_independent_of_path_quality": True,
        "source_interpretation": "Selected IOException is the source's shutdown response; a JUnit pass alone does not establish recovery.",
    }
    (campaign / "terminal-verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print(json.dumps(verdict, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True, type=Path)
    main(parser.parse_args().campaign)
