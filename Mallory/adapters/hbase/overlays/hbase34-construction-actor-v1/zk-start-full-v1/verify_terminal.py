#!/usr/bin/env python3
"""Verify a natural full terminal without making a bug claim."""

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
    require(summary.get("case_id") == audit.get("case_id") == "HBASE-34" and
            status in {"budget_exhausted", "queue_exhausted"} and
            isinstance(count, int) and 0 < count <= 80 and
            audit.get("terminal_status") == status and
            audit.get("trial_count") == count + 1 and
            summary.get("target_binding") == {"nodes": ["rs0"]} and
            summary.get("calibration_only") is False,
            "HBASE-34 full-v1 has no consistent natural terminal")
    verdict = {
        "schema_version": 1, "case_id": "HBASE-34",
        "kind": "natural_full_terminal", "status": status,
        "full_campaign_completed": True, "fault_trials_completed": count,
        "budget": {"trials": 80, "seconds": 3600, "max_faults_per_trial": 3},
        "healthy_gate_sha256": sha(campaign / "healthy-gate.json"),
        "healthy_target_actor": gate["target_actor"],
        "healthy_state_edge_certainty": gate["state_edge_certainty"],
        "campaign_result_sha256": sha(summary_path),
        "offline_audit_sha256": sha(audit_path),
        "strict_injected_trials": summary.get("strict_injected_trials"),
        "strict_target_trials": summary.get("strict_target_trials"),
        "exact_exception_trials": summary.get("exact_exception_trials"),
        "reproduced_candidates": len(summary.get("reproduced_candidates", [])),
        "new_bug": None,
        "source_interpretation": (
            "A one-shot KeeperException in ZKSecretWatcher.start is caught by "
            "AuthenticationTokenSecretManager.start. retrievePassword later "
            "refreshes keys before the exact null guard. Any InvalidToken, "
            "target-absent trial, or JUnit failure requires separate source and "
            "replay review before a bug claim."),
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
        raise SystemExit(f"HBASE-34 full-v1 terminal gap: {exc}")
