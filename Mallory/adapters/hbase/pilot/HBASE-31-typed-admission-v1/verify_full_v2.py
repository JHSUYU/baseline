#!/usr/bin/env python3
"""Record terminal HBASE-31 full results without inferring a bug from target reach."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from preflight import HERE, check, require, sha


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    require(args.out.resolve().parent == campaign, "verdict must stay in campaign")
    stage = json.loads((HERE / "full-v2-stage-receipt.json").read_text())
    check(campaign / "config.json", stage["config_sha256"])
    summary = json.loads((campaign / "result.json").read_text())
    audit = json.loads((campaign / "offline-causal-audit.json").read_text())
    require(summary["case_id"] == audit["case_id"] == "HBASE-31" and
            summary["status"] in {"queue_exhausted", "budget_exhausted"},
            "campaign has not reached a natural terminal")
    require(audit["campaign_result_sha256"] == sha(campaign / "result.json"),
            "audit result hash mismatch")
    junit = summary.get("healthy_junit_validation") or {}
    receipt = {
        "schema_version": 1,
        "case_id": "HBASE-31",
        "kind": "typed_dispatch_v2_full_terminal",
        "status": summary["status"],
        "duration_seconds": summary["duration_seconds"],
        "fault_trials_completed": summary["fault_trials_completed"],
        "healthy_junit_status": junit.get("status"),
        "healthy_seed_valid": summary.get("healthy_seed_valid"),
        "strict_injected_trials": summary.get("strict_injected_trials"),
        "strict_target_trials": summary.get("strict_target_trials"),
        "exact_exception_trials": summary.get("exact_exception_trials"),
        "target_exception_candidate_trials": summary.get("target_exception_candidate_trials"),
        "audit_report_gate_passed": audit.get("report_gate_passed"),
        "audit_target_claims_reverified": audit.get("target_claims_reverified"),
        "audit_applied_fault_identity_valid": audit.get("applied_fault_identity_valid"),
        "config_sha256": stage["config_sha256"],
        "result_sha256": sha(campaign / "result.json"),
        "audit_sha256": sha(campaign / "offline-causal-audit.json"),
        "source_gap_receipt_sha256": stage["predicate_source_gap_sha256"],
        "source_gap": "A pre-send plain IOException can retry the same ServerName but does not itself change the selected wrong-start-code predicate.",
        "bug_claim": False,
        "bug_claim_condition": "Require an exact selected throw, source confirmation, and strict postfault event-time path before any bug claim."
    }
    args.out.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in ("status", "duration_seconds",
                                            "fault_trials_completed", "bug_claim")}))


if __name__ == "__main__":
    main()
