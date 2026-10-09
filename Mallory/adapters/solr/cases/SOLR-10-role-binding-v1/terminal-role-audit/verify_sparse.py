#!/usr/bin/env python3
"""Fail-closed local witness for the sparse SOLR-10 role-aware publication.

The full 81-trial export remains on node2.  The offhost verifier audited every
member; this check binds that immutable receipt and recomputes one faulted
role-to-target path from SHA-matched raw events available on node0.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from verify import (MANIFEST_SHA, SOURCE_SHA, load_events, read_json, require,
                    sha, verify_fault, verify_path)


BASE = Path(__file__).resolve().parents[6]
ROLE_RECEIPT_SHA = "ab2f3b900b9ac01410f75cacf74b7ee598a8449a313c27ffbc6e8ab159d7cdc2"
ARCHIVE_SHA = "52150109d51767113c8e63367cd9fcfa4f7ae58667583ce446a40e51b63c6a01"
ARCHIVE_RECEIPT_SHA = "aa06cab0b6530ec648e8c47b9926f7f6ba8ae02cde86c3f4e48d775815cafbbf"
TRIAL_ID = 2


def verify_sparse(base: Path, canonical: Path, index_path: Path) -> dict:
    index = read_json(index_path)
    require(index.get("schema_version") == 1 and index.get("case_id") == "SOLR-10"
            and index.get("classification") == "observed_event_path"
            and index.get("scope") == "sparse_role_aware_terminal_export"
            and index.get("sparse_verifier_sha256") == sha(Path(__file__))
            and index.get("local_witness_trial") == TRIAL_ID
            and index.get("offhost_role_faults") == 152
            and index.get("offhost_postfault_path_trials") == 77,
            "review index identity mismatch")
    actual = canonical.resolve(strict=True)
    expected = base / "data/mallory/replays/SOLR-10-role-v1-full-metadata"
    require(actual == expected.resolve(strict=True), "canonical path is not sparse export")
    role_dir = base / "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1/terminal-role-audit"
    role_path = role_dir / "receipt.json"
    role_manifest_path = role_dir / "audit-manifest.json"
    role_verifier_path = role_dir / "verify.py"
    role_test_path = role_dir / "test_verify.py"
    export_manifest_path = actual / "evidence-manifest.json"
    result_path = actual / "result.json"
    config_path = actual / "config.json"
    static_audit_path = actual / "SOLR-10-offline-audit.json"
    archive_receipt_path = actual / "SOLR-10-role-v1-export-receipt.json"
    sync_receipt_path = actual / "metadata-sync-receipt.json"
    trial_dir = actual / f"trials/r{TRIAL_ID:04d}"
    trial_files = {name: trial_dir / name for name in
                   ("plan.json", "result.json", "events.jsonl.gz")}
    paths = {"role_receipt": role_path, "role_manifest": role_manifest_path,
             "role_verifier": role_verifier_path, "role_tests": role_test_path,
             "export_manifest": export_manifest_path, "result": result_path,
             "config": config_path, "static_audit": static_audit_path,
             "archive_receipt": archive_receipt_path,
             "metadata_sync_receipt": sync_receipt_path}
    require(all(path.is_file() and index.get(f"{name}_sha256") == sha(path)
                for name, path in paths.items()), "review file SHA mismatch")
    require(index["role_receipt_sha256"] == ROLE_RECEIPT_SHA
            and index["export_manifest_sha256"] == MANIFEST_SHA
            and index["archive_receipt_sha256"] == ARCHIVE_RECEIPT_SHA
            and index.get("archive_sha256") == ARCHIVE_SHA
            and index.get("static_audit_status") ==
            "diagnostic_role_point_unsupported", "pinned review identity mismatch")
    for relative, expected_sha in SOURCE_SHA.items():
        require(sha(base / relative) == expected_sha,
                f"pinned role-audit source changed: {relative}")
    role_manifest, role = read_json(role_manifest_path), read_json(role_path)
    export_manifest = read_json(export_manifest_path)
    result, config = read_json(result_path), read_json(config_path)
    static_audit = read_json(static_audit_path)
    archive_receipt, sync_receipt = (read_json(archive_receipt_path),
                                     read_json(sync_receipt_path))
    require(role_manifest.get("receipt_sha256") == ROLE_RECEIPT_SHA
            and role_manifest.get("export_manifest_sha256") == MANIFEST_SHA
            and role_manifest.get("verifier_sha256") == sha(role_verifier_path)
            and role_manifest.get("total_python_tests_passed") == 13
            and role_manifest.get("negative_tamper_tests_passed") == 12,
            "role audit manifest mismatch")
    require(role.get("case_id") == "SOLR-10"
            and role.get("export_manifest_sha256") == MANIFEST_SHA
            and role.get("verifier_sha256") == sha(role_verifier_path)
            and role.get("pinned_source_sha256") == SOURCE_SHA
            and role.get("fault_trials") == 80
            and role.get("planned_and_applied_faults") == 152
            and role.get("postfault_observed_path_trials") == 77
            and role.get("target_reached_fault_trials") == 77
            and role.get("target_lost_trials") == [1, 24, 54]
            and role.get("target_throw_fault_trials") == 0
            and role.get("target_exception_candidates") == 0
            and role.get("role_receipt_failures") == 0
            and role.get("guidance_mismatches") == 0,
            "offhost role-aware audit summary mismatch")
    rows = role.get("trials")
    require(isinstance(rows, list) and len(rows) == 81
            and [row.get("trial_id") for row in rows] == list(range(81))
            and sum(bool(row.get("postfault_path")) for row in rows) == 77
            and sum(row.get("faults", 0) for row in rows) == 152
            and all(row.get("role_receipts_valid") is True
                    and row.get("target_threw") is False for row in rows),
            "role-aware trial index mismatch")
    require(export_manifest.get("case_id") == "SOLR-10"
            and export_manifest.get("trials") == 81
            and len(export_manifest.get("files", [])) == 489
            and export_manifest.get("table_sha256") ==
            sha(actual / "terminal-table.csv"), "export manifest mismatch")
    entries = {row.get("path"): row for row in export_manifest["files"]}
    require(len(entries) == 489, "duplicate exported file path")
    for name, path in trial_files.items():
        relative = f"trials/r{TRIAL_ID:04d}/{name}"
        entry = entries.get(relative)
        require(isinstance(entry, dict) and path.is_file()
                and path.stat().st_size == entry.get("bytes")
                and sha(path) == entry.get("sha256")
                and index.get(f"witness_{name.replace('.', '_')}_sha256") == sha(path),
                f"local witness export mismatch: {relative}")
    require(entries["result.json"]["sha256"] == sha(result_path)
            and entries["config.json"]["sha256"] == sha(config_path)
            and archive_receipt.get("archive_sha256") == ARCHIVE_SHA
            and archive_receipt.get("source_manifest_sha256") == MANIFEST_SHA
            and archive_receipt.get("source_result_sha256") == sha(result_path)
            and archive_receipt.get("verified_members") == 491
            and archive_receipt.get("source_unchanged_after_archive") is True,
            "offhost archive binding mismatch")
    require(sync_receipt.get("full_raw_on_node0") is False
            and sync_receipt.get("static_offline_audit_scope") ==
            "diagnostic_role_point_unsupported"
            and sync_receipt.get("offhost_archive_sha256") == ARCHIVE_SHA
            and all(sync_receipt["files"].get(name, {}).get("sha256") == sha(path)
                    for name, path in (("result.json", result_path),
                                       ("config.json", config_path),
                                       ("evidence-manifest.json", export_manifest_path),
                                       ("SOLR-10-offline-audit.json", static_audit_path),
                                       ("SOLR-10-role-v1-export-receipt.json", archive_receipt_path))),
            "sparse transfer receipt mismatch")
    require(static_audit.get("report_gate_passed") is False
            and static_audit.get("applied_fault_identity_valid") is False
            and static_audit.get("guidance_consistent") is False,
            "generic audit diagnostic classification changed")
    require(result.get("status") == "budget_exhausted"
            and result.get("case_id") == "SOLR-10"
            and result.get("healthy_seed_valid") is True
            and result.get("runtime_attestation", {}).get("valid") is True
            and result.get("fault_trials_completed") == 80
            and result.get("strict_injected_trials") == 80
            and result.get("strict_target_trials") == 77
            and result.get("exact_exception_trials") == 0
            and config.get("budget", {}).get("trials") == 80
            and len(result.get("trials", [])) == 81,
            "terminal result does not match role audit")
    trial = read_json(trial_files["result.json"])
    faults = read_json(trial_files["plan.json"])["faults"]
    require(trial.get("trial_id") == TRIAL_ID and trial.get("plan") == faults
            and result["trials"][TRIAL_ID]["result"] ==
            f"trials/r{TRIAL_ID:04d}/result.json", "witness trial plan mismatch")
    evidence = trial.get("events_evidence", {})
    require(evidence.get("gzip_sha256") == sha(trial_files["events.jsonl.gz"])
            and evidence.get("gzip_bytes") == trial_files["events.jsonl.gz"].stat().st_size,
            "compressed witness trace mismatch")
    events = load_events(trial_dir, trial)
    fault_rows = [verify_fault(events, fault) for fault in faults]
    witness = verify_path(events, trial, config["target"], fault_rows)
    require(witness is not None and witness == rows[TRIAL_ID].get("witness")
            and rows[TRIAL_ID].get("postfault_path") is True
            and rows[TRIAL_ID].get("target_reached") is True,
            "local role-aware fault-to-target path mismatch")
    return {"case_id": "SOLR-10", "classification": "observed_event_path",
            "verified_full_fault_trials": 80, "verified_role_fault_chains": 152,
            "offhost_postfault_paths": 77, "local_witness_trial": TRIAL_ID,
            "local_witness": witness}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    parser.add_argument("--canonical", type=Path)
    parser.add_argument("--index", type=Path)
    args = parser.parse_args()
    base = args.base.resolve(strict=True)
    canonical = args.canonical or base / "data/mallory/cases/SOLR-10"
    index_path = args.index or base / "data/mallory/quality_reviews/solr10_role_v1_full/index.json"
    print(json.dumps(verify_sparse(base, canonical, index_path), sort_keys=True))


if __name__ == "__main__":
    main()
