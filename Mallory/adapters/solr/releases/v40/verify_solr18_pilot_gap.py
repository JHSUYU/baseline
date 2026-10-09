#!/usr/bin/env python3
"""Bind the SOLR-18 v40p nonterminal postfault target gap to raw results."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(healthy: Path, pilot: Path, source: Path) -> dict:
    healthy_result = json.loads((healthy / "result.json").read_text())
    healthy_audit = json.loads((healthy / "offline-causal-audit.json").read_text())
    pilot_result = json.loads((pilot / "result.json").read_text())
    pilot_audit = json.loads((pilot / "offline-causal-audit.json").read_text())
    config = json.loads((pilot / "config.json").read_text())
    assert config["case_id"] == healthy_result["case_id"] == pilot_result["case_id"] == "SOLR-18"
    assert config["budget"]["trials"] == 8 and config["budget"]["max_faults_per_trial"] == 1
    assert pilot_result["status"] == "budget_exhausted"
    assert healthy_result["status"] == "calibration_complete"
    assert healthy_audit["campaign_result_sha256"] == sha(healthy / "result.json")
    assert pilot_audit["campaign_result_sha256"] == sha(pilot / "result.json")
    assert healthy_audit["report_gate_passed"] and pilot_audit["report_gate_passed"]
    assert healthy_audit["healthy_observed_path_doors"] == 17
    assert pilot_audit["archive_integrity_valid"] and pilot_audit["guidance_consistent"]
    assert sha(source) == config["mapping"]["target_source_sha256"]
    text = source.read_text()
    assert "final byte[] data = zkClient.getData(ALIASES, null, stat, true);" in text
    assert "final byte[] data = zkClient.getData(ALIASES, this, stat, true);" in text
    assert "return setIfNewer(Aliases.fromJSON(data, stat.getVersion()));" in text
    assert "setIfNewer(Aliases.fromJSON(data, stat.getVersion()));" in text
    assert "catch (KeeperException.ConnectionLossException | KeeperException.SessionExpiredException e)" in text
    rows = []
    for trial in pilot_audit["trials"]:
        trial_id = trial["trial_id"]
        if trial_id == 0:
            continue
        result_path = pilot / "trials" / f"r{trial_id:04d}" / "result.json"
        result = json.loads(result_path.read_text())
        fault = trial["faults"][0]
        assert result["plan"][0]["fault_id"] == fault["fault_id"]
        assert result["plan"][0]["point"] == fault["point"]
        rows.append({"trial_id": trial_id, "trial_result_sha256": sha(result_path),
                     "planned_point": fault["point"],
                     "exact_applied": fault["receipts_exact"] and fault["applied_receipts"] == 1,
                     "target_retained_anywhere": trial["target_retained"],
                     "same_actor_target_after_fault": trial["same_actor_target_after_fault"],
                     "junit_status": result.get("junit_validation", {}).get("status")})
    assert len(rows) == pilot_result["fault_trials_completed"] == 8
    assert sum(row["exact_applied"] for row in rows) == pilot_result["strict_injected_trials"] == 5
    assert sum(row["exact_applied"] and row["target_retained_anywhere"] for row in rows) == 4
    assert not any(row["same_actor_target_after_fault"] for row in rows)
    return {"schema_version": 1, "case_id": "SOLR-18",
            "classification": "fault_model_no_same_actor_postfault_target",
            "full_campaign_promoted": False, "new_bug_confirmed": False,
            "healthy_result_sha256": sha(healthy / "result.json"),
            "healthy_audit_sha256": sha(healthy / "offline-causal-audit.json"),
            "healthy_sync_receipt_sha256": sha(healthy / "sync-receipt.json"),
            "pilot_result_sha256": sha(pilot / "result.json"),
            "pilot_audit_sha256": sha(pilot / "offline-causal-audit.json"),
            "pilot_sync_receipt_sha256": sha(pilot / "sync-receipt.json"),
            "pilot_config_sha256": sha(pilot / "config.json"),
            "source_sha256": sha(source),
            "healthy_observed_path_doors": 17,
            "exact_applied_trials": 5,
            "generic_target_retained_trials": 4,
            "same_actor_postfault_target_trials": 0,
            "source_finding": ("AliasesManager.update reads ZK data before setIfNewer and "
                               "propagates the read exception. AliasesManager.process catches "
                               "ConnectionLossException and exits that callback before "
                               "setIfNewer. A target seen in another call does not establish "
                               "a fault-to-target path for these injected doors."),
            "trials": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--healthy", required=True, type=Path)
    parser.add_argument("--pilot", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    row = inspect(args.healthy, args.pilot, args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"classification": row["classification"],
                      "exact_applied_trials": row["exact_applied_trials"],
                      "same_actor_postfault_target_trials":
                          row["same_actor_postfault_target_trials"]}, sort_keys=True))


if __name__ == "__main__":
    main()
