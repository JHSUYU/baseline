#!/usr/bin/env python3
"""Verify natural full terminal independently of graph quality or bug verdict."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from healthy_gate import require, sha, verify_promotion


def verify(campaign: Path) -> dict:
    gate = verify_promotion(campaign)
    summary_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    summary = json.loads(summary_path.read_text())
    audit = json.loads(audit_path.read_text())
    status = summary.get("status")
    count = summary.get("fault_trials_completed")
    require(summary.get("case_id") == audit.get("case_id") == "HBASE-28" and
            status in {"budget_exhausted", "queue_exhausted"} and
            isinstance(count, int) and 0 < count <= 80 and
            audit.get("terminal_status") == status and
            audit.get("trial_count") == count + 1 and
            summary.get("target_binding") == {"nodes": ["master0", "rs0"]} and
            summary.get("calibration_only") is False,
            "HBASE-28 full-v2 has no consistent natural terminal")
    verdict = {
        "schema_version": 1, "case_id": "HBASE-28",
        "kind": "natural_full_terminal", "status": status,
        "full_campaign_completed": True, "fault_trials_completed": count,
        "budget": {"trials": 80, "seconds": 3600, "max_faults_per_trial": 3},
        "healthy_gate_sha256": sha(campaign / "healthy-gate.json"),
        "healthy_target_actor": gate["target_actor"],
        "healthy_typed_door_seq": gate["door_seq"],
        "healthy_exact_check_seq": gate["target_seq"],
        "campaign_result_sha256": sha(summary_path),
        "offline_audit_sha256": sha(audit_path),
        "strict_injected_trials": summary.get("strict_injected_trials"),
        "strict_target_trials": summary.get("strict_target_trials"),
        "exact_exception_trials": summary.get("exact_exception_trials"),
        "reproduced_candidates": len(summary.get("reproduced_candidates", [])),
        "new_bug": None,
        "source_interpretation": (
            "The injected SocketException affects the OS interface lookup before "
            "the master UI bind guard. A selected IOException or JUnit failure "
            "requires independent source and outcome review before a bug claim."),
    }
    (campaign / "terminal-verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    return verdict


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.campaign), sort_keys=True))
    except (ValueError, KeyError, FileNotFoundError) as exc:
        raise SystemExit(f"HBASE-28 full-v2 terminal gap: {exc}")
