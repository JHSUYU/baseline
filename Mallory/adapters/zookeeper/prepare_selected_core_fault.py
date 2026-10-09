#!/usr/bin/env python3
"""Admit a fresh ZooKeeper fault run from a separately audited healthy seed."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(healthy: Path, output: Path, *, trials: int, seconds: int,
            max_faults_per_trial: int = 6) -> None:
    if trials < 1 or seconds < 1 or max_faults_per_trial < 1:
        raise ValueError("fault budget must be positive")
    result_path = healthy / "result.json"
    audit_path = healthy / "offline-causal-audit.json"
    config_path = healthy / "config.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    case = config["case_id"]
    evidence_types = audit.get("healthy_closure_evidence_types")
    if evidence_types is None:
        # The pinned 5820 audit predates this summary field. Derive only the
        # graph-path label from its independently recomputed path/edge counts.
        if (Path(config.get("core_release", "")).name !=
                "5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf"):
            raise ValueError("unrecognized audit schema without evidence types")
        evidence_types = (["observed_graph_path"] if
                          audit.get("healthy_observed_path_doors", 0) > 0 and
                          audit.get("healthy_closure_observed_edges", 0) > 0 else [])
    target_nonthrowing = audit.get("healthy_target_nonthrowing")
    if target_nonthrowing is None:
        target_nonthrowing = (result.get("exact_exception_trials") == 0 and
                              not result.get("target_exception_candidate_trials"))
    if not (result["case_id"] == audit["case_id"] == case and
            result["status"] == "calibration_complete" and
            result["healthy_seed_valid"] is True and
            result["runtime_attestation"]["valid"] is True and
            result["healthy_junit_validation"]["status"] == "passed" and
            audit["report_gate_passed"] is True and
            audit["healthy_closure_proven"] is True and
            target_nonthrowing is True and
            audit["campaign_result_sha256"] == sha(result_path)):
        raise ValueError("healthy target/causal audit is not an admissible seed")
    if config.get("allow_local_timeline_doors"):
        if not (audit["healthy_local_timeline_doors"] > 0 and
                "observed_local_timeline" in evidence_types):
            raise ValueError("missing exact same-occurrence timeline proof")
    elif not (audit["healthy_observed_path_doors"] > 0 and
              "observed_graph_path" in evidence_types):
        raise ValueError("missing observed graph path to target")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)
    sites = output.with_suffix(".sites.json")
    if sites.exists():
        raise FileExistsError(sites)
    original_site = config["site_file"]
    shutil.copyfile(Path(original_site), sites)
    config["site_file"] = str(sites.resolve())
    config["calibration_only"] = False
    config["auto_promote_if_healthy"] = True
    config["budget"].update(trials=trials, seconds=seconds,
                            max_faults_per_trial=max_faults_per_trial)
    config["mapping"].update(
        status="runtime_attested_healthy_seed",
        healthy_seed_verified=True,
        verified_healthy_probe={
            "scope": "fresh_core_healthy_seed_with_offline_causal_audit",
            "config": str(config_path.resolve()),
            "config_sha256": sha(config_path),
            "result": str(result_path.resolve()),
            "result_sha256": sha(result_path),
            "offline_audit": str(audit_path.resolve()),
            "offline_audit_sha256": sha(audit_path),
            "healthy_closure_evidence_types": evidence_types,
        })
    matched = 0
    for artifact in config["runtime_artifacts"]:
        if artifact["path"] == original_site:
            artifact.update(path=str(sites.resolve()), sha256=sha(sites))
            matched += 1
    if matched != 1:
        sites.unlink()
        raise ValueError("site artifact receipt is missing or ambiguous")
    output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("healthy_campaign", type=Path)
    parser.add_argument("output_config", type=Path)
    parser.add_argument("--trials", type=int, required=True)
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument("--max-faults-per-trial", type=int, default=6)
    args = parser.parse_args()
    prepare(args.healthy_campaign, args.output_config,
            trials=args.trials, seconds=args.seconds,
            max_faults_per_trial=args.max_faults_per_trial)
