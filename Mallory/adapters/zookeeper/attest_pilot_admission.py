#!/usr/bin/env python3
"""Record why a ZooKeeper pilot can enter a separate full fault budget."""

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def attest(healthy: Path, pilot: Path, full_config: Path, output: Path) -> None:
    h_result_path, h_audit_path = healthy / "result.json", healthy / "offline-causal-audit.json"
    p_result_path, p_audit_path = pilot / "result.json", pilot / "offline-causal-audit.json"
    h_result, h_audit = read(h_result_path), read(h_audit_path)
    p_result, p_audit, config = read(p_result_path), read(p_audit_path), read(full_config)
    case = config["case_id"]
    if not (h_result["case_id"] == h_audit["case_id"] ==
            p_result["case_id"] == p_audit["case_id"] == case):
        raise ValueError("case IDs differ")
    if not (h_result["status"] == "calibration_complete" and
            p_result["status"] in {"budget_exhausted", "queue_exhausted"} and
            h_audit["report_gate_passed"] is True and
            p_audit["report_gate_passed"] is True and
            h_audit["campaign_result_sha256"] == sha(h_result_path) and
            p_audit["campaign_result_sha256"] == sha(p_result_path) and
            h_result["runtime_attestation"]["valid"] is True and
            p_result["runtime_attestation"]["valid"] is True and
            h_audit["healthy_target_nonthrowing"] is True and
            p_result["strict_target_trials"] > 0 and
            not p_result["target_exception_candidate_trials"] and
            not p_result["exact_exception_trials"]):
        raise ValueError("pilot has not met strict full-budget admission")
    if not (config["target"] == read(pilot / "config.json")["target"] and
            config["target"] == read(healthy / "config.json")["target"] and
            config["expected_target_class_sha256"] ==
            p_result["runtime_attestation"]["observed_target_class_sha256"]):
        raise ValueError("full config target differs from attested pilot")
    strict_in_closure = 0
    strict_target_in_closure = 0
    for trial in p_result["trials"]:
        if trial.get("trial_id") == 0:
            continue
        path = pilot / "trials" / f"r{trial['trial_id']:04d}" / "result.json"
        row = read(path)
        feedback = row.get("feedback", {})
        if row.get("selection_reason") == "dynamic_closure" and feedback.get("all_faults_effective"):
            strict_in_closure += 1
            strict_target_in_closure += bool(feedback.get("target_reached"))
    receipt = {
        "schema_version": 1, "case_id": case,
        "status": "full_budget_admissible",
        "healthy_result": str(h_result_path.resolve()),
        "healthy_result_sha256": sha(h_result_path),
        "healthy_audit": str(h_audit_path.resolve()),
        "healthy_audit_sha256": sha(h_audit_path),
        "pilot_result": str(p_result_path.resolve()),
        "pilot_result_sha256": sha(p_result_path),
        "pilot_audit": str(p_audit_path.resolve()),
        "pilot_audit_sha256": sha(p_audit_path),
        "full_config": str(full_config.resolve()),
        "full_config_sha256": sha(full_config),
        "healthy_closure_evidence_types": h_audit["healthy_closure_evidence_types"],
        "healthy_local_timeline_doors": h_audit["healthy_local_timeline_doors"],
        "healthy_observed_path_doors": h_audit["healthy_observed_path_doors"],
        "pilot_fault_trials": p_result["fault_trials_completed"],
        "pilot_strict_injected_trials": p_result["strict_injected_trials"],
        "pilot_strict_target_trials": p_result["strict_target_trials"],
        "pilot_strict_in_closure_trials": strict_in_closure,
        "pilot_strict_target_in_closure_trials": strict_target_in_closure,
        "pilot_target_exception_trials": len(p_result["target_exception_candidate_trials"]),
        "full_budget": config["budget"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("healthy", type=Path)
    parser.add_argument("pilot", type=Path)
    parser.add_argument("full_config", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    attest(args.healthy, args.pilot, args.full_config, args.output)
