#!/usr/bin/env python3
"""Classify a natural HBASE-27 full terminal without inflating graph quality."""

import argparse
import hashlib
import json
from pathlib import Path


FULL_TERMINALS = {"budget_exhausted", "queue_exhausted"}
GAP_TERMINALS = {"healthy_no_injectable_door", "healthy_node_identity_missing",
                 "healthy_seed_ambiguous", "healthy_attestation_failed",
                 "fault_trials_not_attested"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(campaign):
    summary_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    summary = json.loads(summary_path.read_text())
    audit = json.loads(audit_path.read_text())
    status = summary["status"]
    count = summary["fault_trials_completed"]
    if (summary["case_id"] != "HBASE-27" or audit["case_id"] != "HBASE-27" or
            status not in FULL_TERMINALS | GAP_TERMINALS or
            not 0 <= count <= 80 or audit["terminal_status"] != status or
            audit["trial_count"] != count + 1 or
            (status in FULL_TERMINALS and count == 0)):
        raise SystemExit("HBASE-27 full-v3 has no consistent terminal")
    healthy = summary["healthy_junit_validation"]
    attestation = summary["runtime_attestation"]
    if (healthy["tests"] != 1 or healthy["failures"] != 0 or healthy["errors"] != 0 or
            attestation["bound_nodes"] != ["rs0"] or
            attestation["eligible_doors_before_target"] <= 0):
        raise SystemExit("HBASE-27 full-v3 healthy JUnit/actor/door gate failed")
    verdict = {
        "schema_version": 1, "case_id": "HBASE-27",
        "kind": "natural_full_terminal" if status in FULL_TERMINALS else "attestation_gap",
        "status": status, "full_campaign_completed": status in FULL_TERMINALS,
        "fault_trials_completed": count,
        "budget": {"trials": 80, "seconds": 3600, "max_faults_per_trial": 3},
        "campaign_result_sha256": sha(summary_path),
        "offline_audit_sha256": sha(audit_path),
        "audit_report_gate_passed": audit.get("report_gate_passed"),
        "healthy_observed_path_doors": audit.get("healthy_observed_path_doors"),
        "target_retained_fault_trials": audit.get("target_retained_fault_trials"),
        "exact_exception_trials": summary.get("exact_exception_trials"),
        "completion_independent_of_path_quality": True,
        "new_bug": None,
        "source_interpretation": "An IOException from the selected guard is the explicit shutdown response; source review and replay are required for a bug claim.",
    }
    (campaign / "terminal-verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    return verdict


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True, type=Path)
    print(json.dumps(verify(parser.parse_args().campaign), sort_keys=True))
