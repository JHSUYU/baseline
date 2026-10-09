#!/usr/bin/env python3
"""Attest, but do not promote, the epoch-mismatched ZK02 full campaign."""

import argparse
import hashlib
import json
from pathlib import Path


CHECK = "org.apache.zookeeper.server.SessionTrackerImpl#checkSession(JLjava/lang/Object;)V@325:branch:4"
THROW = "org.apache.zookeeper.server.SessionTrackerImpl#checkSession(JLjava/lang/Object;)V@326:throw:1"
TARGET_CLASS = "org.apache.zookeeper.server.SessionTrackerImpl"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(value: bool, reason: str) -> None:
    if not value:
        raise RuntimeError(reason)


def attest(campaign: Path, receipt_path: Path, class_path: Path,
           audit_path: Path, output: Path) -> dict:
    result_path = campaign / "result.json"
    config_path = campaign / "config.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    config = json.loads(config_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    require(result["case_id"] == config["case_id"] == "ZOOKEEPER-02", "case identity drift")
    require(result["status"] in {"budget_exhausted", "queue_exhausted"}, "campaign not terminal")
    require(config["target"]["check_sites"] == [CHECK] and
            config["target"]["throw_site"] == THROW, "exact target site drift")
    require(result["healthy_seed_valid"] and result["runtime_attestation"]["valid"],
            "target class/identity healthy attestation missing")
    require(result["fault_trials_completed"] == 80 and len(result["trials"]) == 81,
            "expected full budget is incomplete")
    require(receipt["patched_root"] == config["cwd"] and
            sha(receipt_path) == config["source_overlay_receipt_sha256"],
            "source overlay receipt drift")
    class_sha = sha(class_path)
    require(class_sha == config["expected_target_class_sha256"],
            "executed target class differs from pinned class")
    require(any(row["sha256"] == class_sha and row["path"] == str(class_path)
                for row in receipt["compiled_artifacts"]),
            "target class absent from overlay receipt")
    require(audit["campaign_result_sha256"] == sha(result_path) and
            audit["archive_integrity_valid"] and audit["applied_fault_identity_valid"] and
            audit["target_claims_reverified"] and audit["guidance_consistent"],
            "offline raw/identity/feedback audit failed")
    require(not audit["healthy_closure_proven"] and
            audit["healthy_closure_observed_edges"] == 0 and
            audit["healthy_closure_included_named_doors"] == 0 and
            audit["healthy_observed_path_doors"] == 0 and
            not audit["report_gate_passed"],
            "expected causal closure gap was not reproduced")
    loaded = set()
    loaders = set()
    for row in result["trials"]:
        trial_id = row["trial_id"]
        trial = campaign / "trials" / f"r{trial_id:04d}"
        catalog_path = trial / "sites.jsonl"
        trial_result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
        require(sha(catalog_path) == trial_result["site_catalog_sha256"],
                f"trial {trial_id} catalog hash mismatch")
        catalog = [json.loads(line) for line in catalog_path.read_text().splitlines() if line]
        exact = [item for item in catalog if item.get("type") in
                 {"TARGET_CHECK", "TARGET_THROW"} and item.get("site") in {CHECK, THROW}]
        require({(item["type"], item["site"]) for item in exact} ==
                {("TARGET_CHECK", CHECK), ("TARGET_THROW", THROW)},
                f"trial {trial_id} exact target catalog missing")
        require(all(item.get("class_name") == TARGET_CLASS and
                    item.get("bytecode_sha256") == class_sha and
                    item.get("class_loader_id") for item in exact),
                f"trial {trial_id} target loaded class drift")
        loaded.update(item["bytecode_sha256"] for item in exact)
        loaders.update(item["class_loader_id"] for item in exact)
    require(loaded == {class_sha}, "target class hash ambiguous")
    summary = {
        "schema_version": 1, "case_id": "ZOOKEEPER-02", "status": "provenance_limited",
        "scientific_limit": "The healthy target closure is singleton: SessionTrackerImpl REGION_ENTER used receiver epoch 0 while the preceding request task and TARGET_CHECK used peer epoch 1. No healthy I/O door has an observed path into T; this 80-trial attempt does not count as closure-guided completion.",
        "campaign_status": result["status"], "duration_seconds": result["duration_seconds"],
        "fault_trials_completed": result["fault_trials_completed"],
        "strict_injected_trials": result["strict_injected_trials"],
        "strict_target_trials": result["strict_target_trials"],
        "exact_exception_trials": result["exact_exception_trials"],
        "campaign_result_sha256": sha(result_path), "campaign_config_sha256": sha(config_path),
        "overlay_receipt_sha256": sha(receipt_path),
        "offline_audit_sha256": sha(audit_path),
        "loaded_target_class_sha256": class_sha,
        "loaded_target_class_loader_ids": sorted(loaders),
        "exact_check_site": CHECK, "exact_throw_site": THROW,
        "trials_catalog_attested": len(result["trials"]),
        "healthy_closure_observed_edges": audit["healthy_closure_observed_edges"],
        "healthy_closure_included_named_doors": audit["healthy_closure_included_named_doors"],
        "healthy_observed_path_doors": audit["healthy_observed_path_doors"],
    }
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("compiled_class", type=Path)
    parser.add_argument("offline_audit", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    row = attest(args.campaign.resolve(), args.receipt.resolve(),
                 args.compiled_class.resolve(), args.offline_audit.resolve(),
                 args.output.resolve())
    print(json.dumps({key: row[key] for key in
                      ("status", "fault_trials_completed", "strict_injected_trials",
                       "strict_target_trials", "exact_exception_trials")}))
