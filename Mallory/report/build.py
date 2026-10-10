"""Build the Mallory checklist from the case inventory and actual run results.

The inventory says what was selected.  Only a result.json written by the
Mallory campaign can say what was run.  Historical CrashFuzz outcomes are
deliberately not imported into this report.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


TERMINAL = {"budget_exhausted", "queue_exhausted"}


def _quality(result: dict[str, Any]) -> str | None:
    """Separate a terminal budget from a verified target exercise."""
    if result.get("status") not in TERMINAL:
        return None
    if result.get("healthy_seed_valid") is not True:
        return "healthy_seed_unproven"
    attestation = result.get("runtime_attestation")
    if not isinstance(attestation, dict) or attestation.get("valid") is not True:
        return "runtime_attestation_unproven"
    injected = result.get("strict_injected_trials")
    retained = result.get("strict_target_trials")
    if not isinstance(injected, int) or not isinstance(retained, int):
        return "fault_effect_unproven"
    if injected <= 0:
        return "no_effective_fault"
    if retained <= 0:
        return "target_lost_after_fault"
    return "target_exercised"


def _causal_audit(result_path: Path, result: dict[str, Any]) -> str | None:
    """Bind a fixed-core replay audit to the immutable campaign summary."""
    audit = _json(result_path.with_name("offline-causal-audit.json"))
    if audit is None:
        return None
    trials = result.get("fault_trials_completed")
    observed_paths = audit.get("healthy_observed_path_doors")
    local_doors = audit.get("healthy_local_timeline_doors")
    graph_proven = (isinstance(observed_paths, int) and
                    not isinstance(observed_paths, bool) and observed_paths > 0)
    local_proven = (audit.get("allow_local_timeline_doors") is True and
                    isinstance(local_doors, int) and not isinstance(local_doors, bool) and
                    local_doors > 0 and result.get("healthy_local_timeline_doors") == local_doors)
    evidence_types = audit.get("healthy_closure_evidence_types")
    expected_types = (["observed_graph_path"] if graph_proven else []) + (
        ["observed_local_timeline"] if local_proven else [])
    types_valid = (evidence_types is None and graph_proven and not local_proven or
                   isinstance(evidence_types, list) and evidence_types == expected_types)
    local_only = local_proven and not graph_proven
    same_actor_count = audit.get("same_actor_target_trials")
    trial_rows = audit.get("trials")
    same_actor_proof_valid = (not local_only or (
        audit.get("local_timeline_only") is True
        and audit.get("same_actor_target_required") is True
        and audit.get("same_actor_target_gate_passed") is True
        and isinstance(same_actor_count, int) and not isinstance(same_actor_count, bool)
        and same_actor_count > 0
        and isinstance(result.get("strict_target_trials"), int)
        and same_actor_count <= result["strict_target_trials"]
        and isinstance(trial_rows, list)
        and same_actor_count == sum(row.get("same_actor_target_after_fault") is True
                                    for row in trial_rows)
        and all(isinstance(row.get("same_actor_target_followups"), list)
                and any(isinstance(proof, dict)
                        and proof.get("door_event_id")
                        and proof.get("fault_event_id")
                        and proof.get("target_check_event_id")
                        and isinstance(proof.get("fault_seq"), int)
                        and isinstance(proof.get("target_check_seq"), int)
                        and proof["fault_seq"] < proof["target_check_seq"]
                        and proof.get("node") not in (None, "", "unknown")
                        and proof.get("occurrence")
                        for proof in row["same_actor_target_followups"])
                for row in trial_rows if row.get("same_actor_target_after_fault") is True)))
    valid = (
        audit.get("schema_version") == 1
        and audit.get("audit_kind") == "offline_causal_quality"
        and audit.get("case_id") == result.get("case_id")
        and audit.get("terminal_status") == result.get("status")
        and audit.get("campaign_result_sha256") ==
        hashlib.sha256(result_path.read_bytes()).hexdigest()
        and isinstance(trials, int)
        and audit.get("trial_count") == trials + 1
        and audit.get("archive_integrity_valid") is True
        and audit.get("applied_fault_identity_valid") is True
        and audit.get("target_claims_reverified") is True
        and audit.get("guidance_consistent") is True
        and audit.get("healthy_closure_proven") is True
        and (graph_proven or local_proven)
        and types_valid
        and same_actor_proof_valid
        and audit.get("unknown_applied_faults") == 0
        and audit.get("target_retained_fault_trials") == result.get("strict_target_trials")
        and audit.get("report_gate_passed") is True
    )
    return "verified" if valid else "invalid"


def _solr38_corrected_audit(results: Path, result_path: Path,
                            result: dict[str, Any]) -> tuple[str, str | None]:
    """Check the sealed offline correction without changing the original audit."""
    if result.get("case_id") != "SOLR-38":
        return "not_applicable", None
    root = Path(__file__).resolve().parents[2]
    canonical = result_path.parent
    receipt_path = canonical / "canonical-import-receipt.json"
    correction_path = canonical / "causal-audit-correction.json"
    archive = results / "evidence_archives/SOLR-38-strict-fault-node1-v3.tar.gz"
    manifest = results / "evidence_archives/SOLR-38-strict-fault-node1-v3.members.json"
    original_seal = results / "evidence_archives/SOLR-38-strict-fault-node1-v3.receipt.json"
    auditor = root / "Mallory/adapters/solr/cases/SOLR-38/election-v3-offline-salvage-v4/audit.py"
    try:
        receipt, correction = _json(receipt_path), _json(correction_path)
        original = _json(result_path.with_name("offline-causal-audit.json"))
        if not all(isinstance(item, dict) for item in (receipt, correction, original)):
            return "invalid", str(receipt_path)
        hashes = ((result_path, "canonical_result_sha256"),
                  (canonical / "config.json", "canonical_config_sha256"),
                  (canonical / "checkpoint.json", "canonical_checkpoint_sha256"),
                  (canonical / "offline-causal-audit.json", "canonical_audit_sha256"),
                  (correction_path, "salvage_receipt_sha256"),
                  (auditor, "salvage_auditor_sha256"),
                  (archive, "archive_sha256"),
                  (manifest, "archive_manifest_sha256"),
                  (original_seal, "archive_receipt_sha256"))
        if (any(not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() !=
                receipt.get(key) for path, key in hashes)
                or receipt.get("case_id") != "SOLR-38"
                or not (receipt.get("status") == result.get("status") == "queue_exhausted")
                or correction.get("archive_sha256") != receipt["archive_sha256"]
                or correction.get("archive_receipt_sha256") != receipt["archive_receipt_sha256"]
                or correction.get("old_offline_audit_sha256") != receipt["canonical_audit_sha256"]
                or correction.get("eligible_for_canonical_completed_row") is not True
                or correction.get("configured_campaign_complete") is not True
                or correction.get("same_actor_postfault_strict_target_trials") != 2
                or not (correction.get("fault_trials_run") == result.get("fault_trials_completed") == 2)
                or not (correction.get("exact_target_exception_trials") == result.get("exact_exception_trials") == 0)
                or correction.get("new_bug_confirmed") is not False
                or original.get("report_gate_passed") is not False):
            return "invalid", str(receipt_path)
        return "verified_corrected_offline", str(correction_path)
    except (OSError, KeyError, TypeError, ValueError):
        return "invalid", str(receipt_path)


def _solr39_offline_completion(results: Path, result_path: Path,
                               result: dict[str, Any]) -> tuple[str, str | None]:
    """Bind the finite fault queue to sealed raw bytes and the corrected path audit."""
    if result.get("case_id") != "SOLR-39":
        return "not_applicable", None
    base = Path(__file__).resolve().parents[2]
    canonical = result_path.parent
    package = base / "Mallory/adapters/solr/cases/SOLR-39/preemptive-fault-v6"
    receipt_path = canonical / "canonical-import-receipt.json"
    audit_path = canonical / "case-local-causal-audit.json"
    archive = results / "evidence_archives/SOLR-39-preemptive-fault-node1-v5.tar.gz"
    manifest = results / "evidence_archives/SOLR-39-preemptive-fault-node1-v5.members.json"
    seal = results / "evidence_archives/SOLR-39-preemptive-fault-node1-v5.receipt.json"
    try:
        receipt = _json(receipt_path)
        audit = _json(audit_path)
        checkpoint = _json(canonical / "checkpoint.json")
        depth = _json(canonical / "fault-depth-review.json")
        if not all(isinstance(item, dict) for item in (receipt, audit, checkpoint, depth)):
            return "invalid", str(receipt_path)
        hashes = ((result_path, "result_sha256"),
                  (canonical / "config.json", "config_sha256"),
                  (canonical / "checkpoint.json", "checkpoint_sha256"),
                  (audit_path, "causal_audit_sha256"),
                  (canonical / "fault-depth-review.json", "depth_review_sha256"),
                  (canonical / "import-proposal.json", "proposal_sha256"),
                  (archive, "v5_archive_sha256"),
                  (manifest, "v5_manifest_sha256"),
                  (seal, "v5_seal_sha256"),
                  (package / "reconcile.py", "v6_reconciler_sha256"),
                  (package / "audit_trial.py", "v6_auditor_sha256"),
                  (package / "stage-request.json", "v6_stage_sha256"))
        if any(not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() !=
               receipt.get(key) for path, key in hashes):
            return "invalid", str(receipt_path)
        stages = [item.get("qualification") for item in checkpoint.get("trials", [])]
        if (receipt.get("completion_criterion") !=
                "finite_strict_queue_exhausted_after_sealed_reclassification"
                or not (receipt.get("valid_trials") == checkpoint.get("valid_trials") == [3])
                or not (receipt.get("invalid_trials") == checkpoint.get("invalid_trials") == [1, 2])
                or stages != ["postfault_bound_actor_prior_reference_target_missing",
                              "postfault_bound_actor_prior_reference_target_missing",
                              "strict_prior_reference_target_retained"]
                or checkpoint.get("queue") != []
                or checkpoint.get("completed_fault_trials") != [1, 2, 3]
                or checkpoint.get("status") != audit.get("status") !=
                "queue_exhausted_after_strict_reclassification"
                or audit.get("r0003_exact_prior_reference_witness") != {
                    "aliases_ref": 81, "cache_write_seq": 32094, "epoch": 0,
                    "fault_applied_seq": 32106, "manager_object": "o10", "node": "node2",
                    "observed_edge_kinds": ["program_return", "state_exact_ref"],
                    "owner_ref": 1, "target_check_seq": 32895,
                    "target_read_seq": 32892, "zk_version": 15}
                or audit.get("exact_target_exception_candidates") != []
                or audit.get("new_bug_confirmed") is not False
                or audit.get("elapsed_seconds") != 142.739
                or depth.get("depth_distribution") != {"1": 3}
                or depth.get("campaign_result_sha256") != receipt["result_sha256"]
                or result.get("status") != receipt.get("status") != "queue_exhausted"
                or result.get("fault_trials_completed") != 3
                or result.get("strict_injected_trials") != 3
                or result.get("strict_target_trials") != 1
                or result.get("exact_exception_trials") != 0
                or result.get("new_bug") is not False):
            return "invalid", str(receipt_path)
        return "verified_sealed_queue_exhaustion", str(audit_path)
    except (OSError, KeyError, TypeError, ValueError):
        return "invalid", str(receipt_path)


def _hdfs48_case_audit(results: Path, result_path: Path,
                       result: dict[str, Any]) -> tuple[str, str | None]:
    """Bind the finite v6 continuation to its case-local postfault path audit."""
    if result.get("case_id") != "HDFS-48":
        return "not_applicable", None
    root = Path(__file__).resolve().parents[2]
    canonical = result_path.parent
    receipt_path = canonical / "canonical-import-receipt.json"
    audit_path = canonical / "case-local-causal-audit.json"
    archive = results / "evidence_archives/HDFS-48-rename-presend-full-v6.tar.gz"
    manifest = results / "evidence_archives/HDFS-48-rename-presend-full-v6.members.json"
    seal = results / "evidence_archives/HDFS-48-rename-presend-full-v6.receipt.json"
    auditor = root / "Mallory/adapters/hdfs/cases/hdfs48-rename-presend-node2-v6/audit_terminal.py"
    depth = results / "quality_reviews/fault_depth/HDFS-48.json"
    try:
        receipt, audit, sealed = _json(receipt_path), _json(audit_path), _json(seal)
        if not all(isinstance(x, dict) for x in (receipt, audit, sealed)):
            return "invalid", str(receipt_path)
        hashes = ((result_path, "canonical_result_sha256"),
                  (canonical / "config.json", "canonical_config_sha256"),
                  (canonical / "checkpoint.json", "canonical_checkpoint_sha256"),
                  (audit_path, "case_local_audit_sha256"),
                  (archive, "archive_sha256"),
                  (manifest, "archive_manifest_sha256"),
                  (seal, "archive_receipt_sha256"),
                  (depth, "depth_review_sha256"),
                  (auditor, "strict_auditor_sha256"))
        if (any(not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() !=
                receipt.get(key) for path, key in hashes)
                or not (receipt.get("status") == result.get("status") == "queue_exhausted")
                or receipt.get("valid_fault_trials") != 2
                or receipt.get("invalid_fault_trials") != 1
                or sealed.get("strict_audit_sha256") != receipt["case_local_audit_sha256"]
                or sealed.get("result_sha256") != receipt["canonical_result_sha256"]
                or audit.get("strict_gate_passed") is not True
                or audit.get("errors")
                or audit.get("campaign_result_sha256") != receipt["canonical_result_sha256"]
                or audit.get("valid_fault_trials") != 2
                or audit.get("invalid_fault_trials") != 1
                or audit.get("new_bug") is not False
                or [row.get("classification") for row in audit.get("rows", [])] != [
                    "healthy_seed", "strict_multifault_retry_rpc_target",
                    "strict_multifault_retry_rpc_target", "postfault_retry_door_missing"]
                or result.get("fault_trials_completed") != 3
                or result.get("strict_injected_trials") != 3
                or result.get("strict_target_trials") != 2
                or result.get("exact_exception_trials") != 0):
            return "invalid", str(receipt_path)
        return "verified_case_local", str(audit_path)
    except (OSError, KeyError, TypeError, ValueError):
        return "invalid", str(receipt_path)


def _solr34_bootstrap_quality(results: Path, result_path: Path,
                              result: dict[str, Any]) -> tuple[str, str | None]:
    """Credit the natural budget while retaining its absent-target finding."""
    if result.get("case_id") != "SOLR-34":
        return "not_applicable", None
    canonical = result_path.parent
    receipt_path = canonical / "canonical-import-receipt.json"
    audit_path = canonical / "case-local-quality-audit.json"
    name = "SOLR-34-fault-bootstrap-node1-v6"
    archive = results / "evidence_archives" / f"{name}.tar.gz"
    manifest = results / "evidence_archives" / f"{name}.members.json"
    seal = results / "evidence_archives" / f"{name}.receipt.json"
    depth = results / "quality_reviews/fault_depth/SOLR-34.json"
    try:
        receipt, audit, sealed = _json(receipt_path), _json(audit_path), _json(seal)
        if not all(isinstance(x, dict) for x in (receipt, audit, sealed)):
            return "invalid", str(receipt_path)
        hashes = ((result_path, "canonical_result_sha256"),
                  (canonical / "config.json", "canonical_config_sha256"),
                  (canonical / "checkpoint.json", "canonical_checkpoint_sha256"),
                  (audit_path, "case_local_audit_sha256"),
                  (archive, "archive_sha256"),
                  (manifest, "archive_manifest_sha256"),
                  (seal, "archive_receipt_sha256"),
                  (depth, "depth_review_sha256"))
        if (any(not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() !=
                receipt.get(key) for path, key in hashes)
                or not (receipt.get("status") == result.get("status") == "budget_exhausted")
                or receipt.get("quality_classification") != "target_not_activated_under_faults"
                or audit.get("check_completed") is not False
                or audit.get("fully_attributed_fault_trials") != 11
                or audit.get("partially_applied_fault_trials") != 1
                or audit.get("junit_passed_trials") != 13
                or audit.get("exact_target_check_events") != 0
                or audit.get("exact_target_throw_events") != 0
                or audit.get("new_bug_confirmed") is not False
                or sealed.get("bootstrap_outcome_audit_sha256") != receipt["case_local_audit_sha256"]
                or sealed.get("result_sha256") != receipt["canonical_result_sha256"]
                or result.get("fault_trials_completed") != 12
                or result.get("strict_injected_trials") != 11
                or result.get("strict_target_trials") != 0
                or result.get("target_reached_trials") != 0
                or result.get("exact_exception_trials") != 0):
            return "invalid", str(receipt_path)
        return "verified_target_absent_budget", str(audit_path)
    except (OSError, KeyError, TypeError, ValueError):
        return "invalid", str(receipt_path)


def _solr15_continuation_quality(results: Path, result_path: Path,
                                 result: dict[str, Any]) -> tuple[str, str | None]:
    """Verify the exhausted bounded continuation and its protective guard."""
    if result.get("case_id") != "SOLR-15":
        return "not_applicable", None
    canonical = result_path.parent
    receipt_path = canonical / "canonical-import-receipt.json"
    audit_path = canonical / "case-local-quality-audit.json"
    review_path = canonical / "source-review.json"
    name = "SOLR-15-fault-bootstrap-node0-v3"
    archive = results / "evidence_archives" / f"{name}.tar.gz"
    manifest = results / "evidence_archives" / f"{name}.members.json"
    seal = results / "evidence_archives" / f"{name}.receipt.json"
    depth = results / "quality_reviews/fault_depth/SOLR-15.json"
    try:
        receipt, audit, review, sealed = [
            _json(path) for path in (receipt_path, audit_path, review_path, seal)]
        if not all(isinstance(x, dict) for x in (receipt, audit, review, sealed)):
            return "invalid", str(receipt_path)
        hashes = ((result_path, "canonical_result_sha256"),
                  (canonical / "config.json", "canonical_config_sha256"),
                  (canonical / "checkpoint.json", "canonical_checkpoint_sha256"),
                  (audit_path, "case_local_audit_sha256"),
                  (review_path, "source_review_sha256"),
                  (depth, "depth_review_sha256"),
                  (archive, "archive_sha256"),
                  (manifest, "archive_manifest_sha256"),
                  (seal, "archive_receipt_sha256"))
        if any(not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() !=
               receipt.get(key) for path, key in hashes):
            return "invalid", str(receipt_path)
        config = _json(canonical / "config.json")
        source_root = Path(review["source_root"])
        if (not isinstance(config, dict) or
                review.get("source_root") != config.get("mapping", {}).get("source_root") or
                review.get("source_revision") !=
                config.get("mapping", {}).get("source_git_revision") or
                review.get("source_review_status") != "expected_guard" or
                review.get("classification") != "protective_leader_live_znode_guard" or
                review.get("new_bug") is not False or
                review.get("same_resource_guard_trials") != [2, 3, 5, 6] or
                review.get("uncredited_trials") != [4, 7, 8, 9, 10, 11, 12] or
                any(not (source_root / review[name]).is_file() or
                    hashlib.sha256((source_root / review[name]).read_bytes()).hexdigest() !=
                    review[digest] for name, digest in
                    (("source_file", "source_sha256"), ("test_file", "test_sha256"))) or
                sealed.get("result_sha256") != receipt["canonical_result_sha256"] or
                sealed.get("quality_sidecar_sha256") != receipt["case_local_audit_sha256"] or
                sealed.get("campaign_completion_credited") is not True or
                audit.get("campaign_completion_credited") is not True or
                audit.get("strict_candidate_trials") != [2, 3, 5, 6] or
                audit.get("prior_uncredited_trial") != 4 or
                audit.get("new_dropped_uncredited_trials") != list(range(7, 13)) or
                audit.get("new_bug") is not False or
                result.get("status") != "budget_exhausted" or
                result.get("fault_trials_completed") != 12 or
                result.get("strict_injected_trials") != 5 or
                result.get("strict_target_trials") != 4 or
                result.get("exact_exception_trials") != 4):
            return "invalid", str(receipt_path)
        campaign = canonical / "campaigns/continuation-v3"
        for number in range(1, 13):
            trial = _json(campaign / "trials" / f"r{number:04d}" / "result.json")
            if not isinstance(trial, dict) or trial.get("trial_id") != number:
                return "invalid", str(receipt_path)
            resource = trial.get("resource_attestation", {})
            if number in (2, 3, 5, 6):
                if (resource.get("valid") is not True or
                        trial.get("feedback", {}).get("target_threw") is not True or
                        trial.get("junit_validation", {}).get("status") != "passed"):
                    return "invalid", str(receipt_path)
            elif number in (4, 7, 8, 9, 10, 11, 12) and resource.get("valid") is not False:
                return "invalid", str(receipt_path)
        return "verified_expected_guard_bounded_budget", str(review_path)
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return "invalid", str(receipt_path)


def _zk13_legacy_integrity_review(results: Path, result_path: Path,
                                  result: dict[str, Any], audit: dict[str, Any]) -> str | None:
    """Recognize the older audit's integrity gate without claiming a graph path."""
    if result.get("case_id") != "ZOOKEEPER-13":
        return None
    seal_path = result_path.with_name("terminal-seal.json")
    if not seal_path.is_file():
        return None
    invalid = "invalid_legacy_integrity_review"
    try:
        seal = _json(seal_path)
        archive = results / "evidence_archives/ZOOKEEPER-13-connectpath-retry-full-v1.tar.gz"
        manifest = results / "evidence_archives/ZOOKEEPER-13-connectpath-retry-full-v1.manifest.json"
        files = ((result_path, "result_sha256"),
                 (result_path.with_name("config.json"), "config_sha256"),
                 (result_path.with_name("checkpoint.json"), "checkpoint_sha256"),
                 (result_path.with_name("offline-causal-audit.json"), "audit_sha256"),
                 (archive, "archive_sha256"),
                 (manifest, "archive_manifest_sha256"))
        if (not isinstance(seal, dict) or seal.get("case_id") != "ZOOKEEPER-13" or
                seal.get("status") != result.get("status") or
                seal.get("fault_trials_completed") != result.get("fault_trials_completed") or
                any(not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() !=
                    seal.get(key) for path, key in files)):
            return invalid
        listed = _json(manifest)
        if (not isinstance(listed, dict) or listed.get("case_id") != "ZOOKEEPER-13" or
                listed.get("archive_sha256") != seal["archive_sha256"] or
                listed.get("member_count") != seal.get("archive_members") or
                len(listed.get("members", [])) != seal.get("archive_members")):
            return invalid
        if (audit.get("audit_kind") != "offline_causal_quality" or
                audit.get("campaign_result_sha256") != seal["result_sha256"] or
                audit.get("terminal_status") != result.get("status") or
                audit.get("trial_count") != result.get("fault_trials_completed", -1) + 1 or
                any(audit.get(key) is not True for key in (
                    "archive_integrity_valid", "applied_fault_identity_valid",
                    "target_claims_reverified", "guidance_consistent", "report_gate_passed")) or
                audit.get("unknown_applied_faults") != 0 or
                audit.get("target_retained_fault_trials") != result.get("strict_target_trials") or
                any(key in audit for key in ("healthy_closure_proven",
                                             "healthy_observed_path_doors",
                                             "healthy_closure_evidence_types"))):
            return invalid
        return "legacy_integrity_verified_path_unclassified"
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return invalid


def _causal_precision_review(results: Path, result_path: Path,
                             result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Bind a superseding causal precision review to unchanged campaign evidence.

    The review can narrow a path-evidence claim; it cannot change completion. A
    listed but damaged review fails closed so a stale or truncated sidecar
    cannot silently restore an unsupported path classification.
    """
    review_root = results / "quality_reviews" / "causal_precision_v2"
    case_id = result.get("case_id")
    expected_path = review_root / f"{case_id}.json"
    receipt_path = str(expected_path)
    index = _json(review_root / "index.json")
    if index is None:
        return ("invalid", receipt_path) if expected_path.is_file() else (None, None)
    weak_ids = index.get("weak_case_ids")
    if not isinstance(weak_ids, list) or case_id not in weak_ids:
        return ("invalid", receipt_path) if expected_path.is_file() else (None, None)
    entries = index.get("cases")
    if (index.get("schema_version") != 2 or
            index.get("review_status") != "provisional_scientific_classification" or
            not all(isinstance(value, str) for value in weak_ids) or
            len(weak_ids) != len(set(weak_ids)) or
            not isinstance(entries, list)):
        return "invalid", receipt_path
    matching = [entry for entry in entries if isinstance(entry, dict) and
                entry.get("case_id") == case_id]
    if len(matching) != 1:
        return "invalid", receipt_path
    entry = matching[0]
    receipt = _json(expected_path)
    if receipt is None:
        return "invalid", receipt_path
    audit_path = result_path.with_name("offline-causal-audit.json")
    if not audit_path.is_file():
        return "invalid", receipt_path
    result_hash = hashlib.sha256(result_path.read_bytes()).hexdigest()
    audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    receipt_hash = hashlib.sha256(expected_path.read_bytes()).hexdigest()
    canonical_result = f"data/mallory/cases/{case_id}/result.json"
    canonical_audit = f"data/mallory/cases/{case_id}/offline-causal-audit.json"
    valid = (
        entry.get("classification") == "causal_precision_unverified"
        and entry.get("sidecar") == f"data/mallory/quality_reviews/causal_precision_v2/{case_id}.json"
        and entry.get("sha256") == receipt_hash
        and entry.get("result_sha256") == result_hash
        and entry.get("audit_sha256") == audit_hash
        and receipt.get("schema_version") == 2
        and receipt.get("case_id") == case_id
        and receipt.get("classification") == "causal_precision_unverified"
        and receipt.get("canonical_files_modified") is False
        and receipt.get("canonical_result") == canonical_result
        and receipt.get("canonical_audit") == canonical_audit
        and receipt.get("canonical_result_sha256") == result_hash
        and receipt.get("canonical_audit_sha256") == audit_hash
        and receipt.get("campaign_status") == result.get("status")
        and receipt.get("duration_seconds") == result.get("duration_seconds")
        and receipt.get("fault_trials_completed") == result.get("fault_trials_completed")
        and receipt.get("strict_postfault_target_trials") == result.get("strict_target_trials")
        and receipt.get("root_free_qualifying_trial_ids") == []
        and receipt.get("evidence_category") in {
            "coarse_root_origin_fault", "root_intermediary_only",
            "root_free_door_unmatched", "faulted_path_unverified"}
    )
    return ("causal_precision_unverified" if valid else "invalid"), receipt_path


def _faulted_path_review(results: Path, result_path: Path,
                         result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Verify an explicit, immutable review of faulted-run continuation.

    Older traces can establish a named, ordered same-region continuation,
    which is labeled as local timeline evidence. Thread-name equality alone
    is never a positive proof. Unreviewed terminal runs remain completed with
    a pending path-evidence annotation.
    """
    case_id = result.get("case_id")
    root = results / "quality_reviews" / "faulted_path_v1"
    locations = [root, root / "terminal_delta_4"]
    found = []
    for location in locations:
        index = _json(location / "index.json")
        if index is None:
            if (location / f"{case_id}.json").is_file():
                return "invalid", str(location / f"{case_id}.json")
            continue
        rows = index.get("rows")
        if not isinstance(rows, list):
            return "invalid", str(location / "index.json")
        matches = [row for row in rows if isinstance(row, dict) and
                   row.get("case_id") == case_id]
        if matches:
            found.extend((location, index, row) for row in matches)
    if not found:
        return None, None
    if len(found) != 1:
        return "invalid", str(found[0][0] / "index.json")
    location, index, entry = found[0]
    ops = Path(__file__).resolve().parents[1] / "ops"
    audit_source = ops / "audit_faulted_precision.py"
    if (not audit_source.is_file() or
            index.get("source_sha256", index.get("frozen_audit_source_sha256")) !=
            hashlib.sha256(audit_source.read_bytes()).hexdigest()):
        return "invalid", str(location / "index.json")
    if location.name == "terminal_delta_4":
        wrapper = ops / "audit_faulted_precision_delta.py"
        if (not wrapper.is_file() or index.get("wrapper_source_sha256") !=
                hashlib.sha256(wrapper.read_bytes()).hexdigest()):
            return "invalid", str(location / "index.json")
    receipt_path = location / f"{case_id}.json"
    receipt = _json(receipt_path)
    config_path = result_path.with_name("config.json")
    audit_path = result_path.with_name("offline-causal-audit.json")
    if receipt is None or not config_path.is_file() or not audit_path.is_file():
        return "invalid", str(receipt_path)
    result_hash = hashlib.sha256(result_path.read_bytes()).hexdigest()
    audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    receipt_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    classification = entry.get("classification")
    positive = classification == "legacy_faulted_region_evidence"
    negative = classification == "faulted_path_unverified"
    recommendation = ("retain_legacy_faulted_region_evidence" if positive
                      else "downgrade_to_faulted_path_unverified")
    trials = receipt.get("trials")
    counts = ("strict_target_trials", "same_region_continuation_trials",
              "same_actor_named_thread_order_trials",
              "ordered_root_free_region_path_trials")
    count_match = all(entry.get(key) == receipt.get(key) for key in counts)
    valid_trials = (
        isinstance(trials, list)
        and len(trials) == result.get("strict_target_trials")
        and len({row.get("trial_id") for row in trials if isinstance(row, dict)}) == len(trials)
        and all(isinstance(row, dict)
                and isinstance(row.get("trial_result_sha256"), str)
                and len(row["trial_result_sha256"]) == 64
                and isinstance(row.get("raw_trace_sha256"), str)
                and len(row["raw_trace_sha256"]) == 64
                and isinstance(row.get("applied_event_ids"), list)
                and row["applied_event_ids"]
                and isinstance(row.get("postfault_target_check_count"), int)
                and row["postfault_target_check_count"] > 0
                for row in trials)
        and sum(row.get("same_region_continuation") is True for row in trials)
            == receipt.get("same_region_continuation_trials")
        and sum(row.get("ordered_root_free_region_path") is True for row in trials)
            == receipt.get("ordered_root_free_region_path_trials")
    )
    valid = (
        index.get("schema_version") == 1
        and receipt.get("schema_version") == 1
        and case_id in index.get("cohort", [])
        and entry.get("review_sha256") == receipt_hash
        and receipt.get("case_id") == case_id
        and (positive or negative)
    )
    valid = (valid and count_match and valid_trials
             and receipt.get("classification") == classification
             and entry.get("recommended_quality_status") == recommendation
             and receipt.get("recommended_quality_status") == recommendation
             and receipt.get("canonical_result_sha256") == result_hash
             and receipt.get("canonical_audit_sha256") == audit_hash
             and receipt.get("canonical_config_sha256") == config_hash
             and entry.get("canonical_result_sha256", result_hash) == result_hash
             and entry.get("canonical_audit_sha256", audit_hash) == audit_hash
             and receipt.get("strict_target_trials") == result.get("strict_target_trials")
             and ((positive and receipt.get("same_region_continuation_trials", 0) > 0
                   and receipt.get("root_free_occurrence_path_trials", 0) > 0)
                  or (negative and receipt.get("same_region_continuation_trials") == 0
                      and receipt.get("root_free_occurrence_path_trials") == 0
                      and receipt.get("ordered_root_free_region_path_trials") == 0)))
    if not valid:
        return "invalid", str(receipt_path)
    return ("observed_local_timeline" if positive else "faulted_path_unverified"), str(receipt_path)


def _hdfs24_retry_review(results: Path, result_path: Path,
                         result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Recompute the exact DN retry and NN RPC path for a terminal HDFS-24 run."""
    if result.get("case_id") != "HDFS-24":
        return None, None
    root = results / "quality_reviews/hdfs24_v3_retry"
    path = root / "HDFS-24.json"
    if not path.is_file():
        return None, None
    invalid = ("invalid", str(path))
    try:
        baseline = results.resolve().parent.parent
        index = _json(root / "index.json")
        review = _json(path)
        verifier = baseline / "Mallory/adapters/hdfs/cases/io-version-retry-v3-owner-binding/audit_hdfs24_full_retry.py"
        helper = verifier.with_name("verify_hdfs24_retry_v3.py")
        audit_path = result_path.with_name("offline-causal-audit.json")
        if (not isinstance(index, dict) or not isinstance(review, dict)
                or not verifier.is_file() or not helper.is_file()
                or not audit_path.is_file()):
            return invalid
        digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
        proven = review.get("strict_witness_trials")
        if not (
            index.get("schema_version") == 1
            and index.get("case_id") == "HDFS-24"
            and index.get("receipt_path") == str(path.resolve().relative_to(baseline))
            and index.get("receipt_sha256") == digest(path)
            and index.get("verifier_sha256") == digest(verifier)
            and index.get("helper_sha256") == digest(helper)
            and index.get("result_sha256") == digest(result_path)
            and index.get("audit_sha256") == digest(audit_path)
            and index.get("strict_witness_trials") == proven
            and isinstance(proven, int) and proven >= 0
            and review.get("schema_version") == 1
            and review.get("case_id") == "HDFS-24"
            and review.get("status") == "terminal_event_time_rpc_retry_audit"
            and review.get("scope") == "causal_path_only_no_bug_claim"
            and review.get("result_sha256") == digest(result_path)
            and review.get("offline_audit_sha256") == digest(audit_path)
            and review.get("fault_trials_completed") == result.get("fault_trials_completed")
            and result.get("status") in TERMINAL
        ):
            return invalid
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary) / "review.json"
            check = subprocess.run(
                ["python3", str(verifier), str(result_path.parent),
                 "--out", str(generated)], cwd=baseline,
                capture_output=True, text=True, timeout=300)
            if check.returncode != 0 or generated.read_bytes() != path.read_bytes():
                return invalid
        return ("observed_event_path" if proven > 0 else
                "faulted_path_unverified"), str(path)
    except (OSError, ValueError, TypeError, KeyError, EOFError, subprocess.TimeoutExpired):
        return invalid


def _solr01_recovery_review(results: Path, result_path: Path,
                            result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Verify a faulted retry that returns to the exact guard in one invocation."""
    if result.get("case_id") != "SOLR-01":
        return None, None
    root = results / "quality_reviews/solr01_v39f_recovery"
    index_path = root / "index.json"
    path = results / "audit_sidecars/SOLR-01-v39f-recovery-full.json"
    if not path.is_file():
        return None, None
    invalid = ("invalid", str(path))
    try:
        baseline = results.resolve().parent.parent
        digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
        index = _json(index_path)
        receipt = _json(path)
        replay = results / "replays/SOLR-01-v39f-lane1"
        verifier = baseline / "Mallory/adapters/solr/releases/v39/verify_solr01_recovery_full.py"
        source = baseline / "Mallory/adapters/solr/releases/v39/source/BaseHttpClusterStateProvider.solr-8.11.4.java"
        release = baseline / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
        files = (path, verifier, source, release / "manifest.json",
                 replay / "config.json", replay / "result.json",
                 replay / "offline-causal-audit.json", replay / "sync-receipt.json")
        if (not isinstance(index, dict) or not isinstance(receipt, dict)
                or any(not file.is_file() for file in files)):
            return invalid
        positives = receipt.get("strict_same_invocation_retry_trials")
        if not (
            index.get("schema_version") == 1
            and index.get("case_id") == "SOLR-01"
            and index.get("receipt_path") == str(path.resolve().relative_to(baseline))
            and index.get("receipt_sha256") == digest(path)
            and index.get("verifier_sha256") == digest(verifier)
            and index.get("source_snapshot_sha256") == digest(source)
            and index.get("core_manifest_sha256") == digest(release / "manifest.json")
            and index.get("result_sha256") == digest(result_path) == digest(replay / "result.json")
            and index.get("audit_sha256") == digest(replay / "offline-causal-audit.json")
            and index.get("qualifying_trial_count") == len(positives)
            and isinstance(positives, list)
            and all(isinstance(number, int) and number > 0 for number in positives)
            and len(set(positives)) == len(positives)
            and receipt.get("schema_version") == 1
            and receipt.get("case_id") == "SOLR-01"
            and receipt.get("classification") ==
                ("terminal_recovery_precision_proven" if positives else
                 "terminal_recovery_precision_unproven")
            and receipt.get("canonical_quality_claim") is False
            and receipt.get("new_bug_confirmed") is False
            and receipt.get("evidence_kind") == "observed_local_timeline"
            and receipt.get("campaign_result_sha256") == digest(result_path)
            and receipt.get("offline_audit_sha256") == digest(replay / "offline-causal-audit.json")
            and receipt.get("sync_receipt_sha256") == digest(replay / "sync-receipt.json")
            and receipt.get("config_sha256") == digest(replay / "config.json")
            and receipt.get("source_snapshot_sha256") == digest(source)
            and receipt.get("fault_trials_completed") == result.get("fault_trials_completed")
            and len(receipt.get("trials", [])) == result.get("fault_trials_completed")
            and result.get("status") in TERMINAL
        ):
            return invalid
        environment = dict(os.environ, PYTHONPATH=f"{release}:{baseline}")
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            generated_audit = temporary / "audit.json"
            generated_review = temporary / "review.json"
            audit_check = subprocess.run(
                ["python3", "-m", "Mallory.core.audit", "--campaign", str(replay),
                 "--out", str(generated_audit)], cwd=baseline, env=environment,
                capture_output=True, text=True, timeout=300)
            review_check = subprocess.run(
                ["python3", str(verifier), "--campaign", str(replay),
                 "--source", str(source), "--out", str(generated_review)],
                cwd=baseline, capture_output=True, text=True, timeout=180)
            if (audit_check.returncode not in (0, 2) or review_check.returncode != 0
                    or generated_audit.read_bytes() !=
                        (replay / "offline-causal-audit.json").read_bytes()
                    or generated_review.read_bytes() != path.read_bytes()):
                return invalid
        return ("observed_local_timeline" if positives else
                "faulted_path_unverified"), str(path)
    except (OSError, ValueError, TypeError, KeyError, EOFError, subprocess.TimeoutExpired):
        return invalid


def _solr18_badversion_recovery_review(results: Path, result_path: Path,
                                       result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Replay exact fault-created BadVersion recovery paths on the frozen graph."""
    if result.get("case_id") != "SOLR-18":
        return None, None
    path = results / "audit_sidecars/SOLR-18-v45-badversion-full.json"
    if not path.is_file():
        return None, None
    invalid = ("invalid", str(path))
    try:
        baseline = results.resolve().parent.parent
        replay = results / "replays/SOLR-18-v45-lane4"
        index = _json(results / "quality_reviews/solr18_v45_badversion_recovery/index.json")
        receipt = _json(path)
        verifier = baseline / "Mallory/adapters/solr/releases/v45/verify_solr18_badversion_full.py"
        helper = verifier.with_name("verify_solr18_badversion_recovery.py")
        source = verifier.parent / "source/ZkStateReader.solr-8.11.4.java"
        test_source = verifier.parent / "source/AliasIntegrationTest.solr-8.11.4.java"
        release = baseline / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
        names = ("config.json", "result.json", "offline-causal-audit.json",
                 "sync-receipt.json")
        files = (path, verifier, helper, source, test_source,
                 release / "manifest.json", release / "Mallory/core/graph.py")
        if (not isinstance(index, dict) or not isinstance(receipt, dict)
                or any(not file.is_file() for file in files)
                or any(not (replay / name).is_file() or
                       not (result_path.parent / name).is_file() for name in names)):
            return invalid
        digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
        if any((replay / name).read_bytes() !=
               (result_path.parent / name).read_bytes() for name in names):
            return invalid
        config = _json(replay / "config.json")
        positives = receipt.get("strict_recovery_trials")
        trials = result.get("fault_trials_completed")
        if not (
            index.get("schema_version") == receipt.get("schema_version") == 1
            and index.get("case_id") == receipt.get("case_id") == "SOLR-18"
            and index.get("receipt_path") == str(path.resolve().relative_to(baseline))
            and index.get("receipt_sha256") == digest(path)
            and index.get("verifier_sha256") == digest(verifier)
            and index.get("helper_sha256") == digest(helper)
            and index.get("source_snapshot_sha256") == digest(source)
            and index.get("test_source_snapshot_sha256") == digest(test_source)
            and index.get("core_manifest_sha256") == digest(release / "manifest.json")
            and index.get("result_sha256") == digest(result_path)
            and index.get("audit_sha256") == digest(replay / "offline-causal-audit.json")
            and index.get("sync_sha256") == digest(replay / "sync-receipt.json")
            and isinstance(config, dict)
            and Path(config.get("core_release", "")).resolve() == release.resolve()
            and receipt.get("classification") ==
                ("terminal_badversion_recovery_precision_proven" if positives else
                 "terminal_badversion_recovery_precision_unproven")
            and receipt.get("canonical_quality_claim") is False
            and receipt.get("new_bug_confirmed") is False
            and receipt.get("offline_audit_gate") is False
            and receipt.get("campaign_result_sha256") == digest(result_path)
            and receipt.get("config_sha256") == digest(replay / "config.json")
            and receipt.get("offline_audit_sha256") == digest(replay / "offline-causal-audit.json")
            and receipt.get("sync_receipt_sha256") == digest(replay / "sync-receipt.json")
            and receipt.get("source_sha256") == digest(source)
            and receipt.get("test_source_sha256") == digest(test_source)
            and receipt.get("core_graph_sha256") == digest(release / "Mallory/core/graph.py")
            and isinstance(trials, int) and not isinstance(trials, bool) and trials > 0
            and receipt.get("fault_trials_completed") == trials
            and isinstance(receipt.get("trials"), list)
            and len(receipt["trials"]) == trials
            and isinstance(positives, list) and positives
            and all(isinstance(number, int) and not isinstance(number, bool)
                    and 1 <= number <= trials for number in positives)
            and len(set(positives)) == len(positives)
            and index.get("qualifying_trial_count") == len(positives)
            and len(receipt.get("effective_target_trials", [])) ==
                result.get("strict_target_trials")
            and receipt.get("exact_target_exception_candidate_trials") == []
            and result.get("exact_exception_trials") == 0
            and result.get("status") in TERMINAL
        ):
            return invalid
        environment = dict(os.environ, PYTHONPATH=f"{release}:{baseline}")
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            generated_audit = temporary / "audit.json"
            generated_review = temporary / "review.json"
            audit_check = subprocess.run(
                ["python3", "-m", "Mallory.core.audit", "--campaign", str(replay),
                 "--out", str(generated_audit)], cwd=baseline, env=environment,
                capture_output=True, text=True, timeout=300)
            review_check = subprocess.run(
                ["python3", str(verifier), "--campaign", str(replay),
                 "--source", str(source), "--test-source", str(test_source),
                 "--out", str(generated_review), "--require-witness"],
                cwd=baseline, env=environment,
                capture_output=True, text=True, timeout=300)
            if (audit_check.returncode not in (0, 2) or review_check.returncode != 0
                    or generated_audit.read_bytes() !=
                        (replay / "offline-causal-audit.json").read_bytes()
                    or generated_review.read_bytes() != path.read_bytes()):
                return invalid
        return "observed_event_path", str(path)
    except (OSError, ValueError, TypeError, KeyError, EOFError, subprocess.TimeoutExpired):
        return invalid


def _event_path_review(results: Path, result_path: Path,
                       result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Verify a named, ordered fault-to-target witness from a completed run."""
    root = results / "quality_reviews" / "causal_precision_v3"
    index = _json(root / "index.json")
    if index is None:
        return None, None
    entries = index.get("cases")
    if not isinstance(entries, list):
        return "invalid", str(root / "index.json")
    case_id = result.get("case_id")
    matches = [entry for entry in entries if isinstance(entry, dict) and
               entry.get("case_id") == case_id]
    if not matches:
        return None, None
    if len(matches) != 1:
        return "invalid", str(root / "index.json")
    entry = matches[0]
    relative = entry.get("receipt")
    prefix = "data/mallory/quality_reviews/causal_precision_v3/"
    if (not isinstance(relative, str) or not relative.startswith(prefix) or
            Path(relative).name != relative[len(prefix):]):
        return "invalid", str(root / "index.json")
    receipt_path = root / Path(relative).name
    receipt = _json(receipt_path)
    audit_path = result_path.with_name("offline-causal-audit.json")
    config_path = result_path.with_name("config.json")
    archive = results / "evidence_archives/campaign" / f"{case_id}.tar.gz"
    manifest_path = archive.with_suffix(".manifest.json")
    if (receipt is None or not audit_path.is_file() or not config_path.is_file()
            or not archive.is_file() or not manifest_path.is_file()):
        return "invalid", str(receipt_path)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    result_hash, audit_hash = digest(result_path), digest(audit_path)
    config_hash, archive_hash = digest(config_path), digest(archive)
    receipt_hash, manifest_hash = digest(receipt_path), digest(manifest_path)
    manifest = _json(manifest_path)
    rows = receipt.get("trials")
    trial_count = result.get("fault_trials_completed", -1) + 1
    valid_rows = (isinstance(rows, list) and len(rows) == trial_count
                  and {row.get("trial_id") for row in rows if isinstance(row, dict)}
                  == set(range(trial_count)))
    proven = 0
    if valid_rows:
        for row in rows:
            trial_id = row["trial_id"]
            trial_path = result_path.parent / "trials" / f"r{trial_id:04d}" / "result.json"
            trial = _json(trial_path)
            if (trial is None or digest(trial_path) != row.get("trial_result_sha256")
                    or trial.get("events_evidence", {}).get("raw_sha256") !=
                    row.get("trace_raw_sha256")):
                valid_rows = False
                break
            paths = row.get("postfault_retry_target_paths")
            if not isinstance(paths, list):
                valid_rows = False
                break
            if paths:
                proven += 1
            for witness in paths:
                if not isinstance(witness, dict):
                    valid_rows = False
                    break
                prefix_id = f"{case_id}-r{trial_id:04d}:"
                names = ("fault_event", "submit_event", "new_enter_event",
                         "claim_event", "target_enter_event", "target_check_event")
                if any(not isinstance(witness.get(name), str) or
                       not witness[name].startswith(prefix_id) for name in names):
                    valid_rows = False
                    break
                try:
                    fault, submit, enter, claim, target_enter, target_check = (
                        int(witness[name][len(prefix_id):]) for name in names)
                except ValueError:
                    valid_rows = False
                    break
                edges = row.get("verified_retry_edges")
                matched_edge = (isinstance(edges, list) and any(
                    isinstance(edge, dict) and
                    edge.get("producer_event") == witness["submit_event"] and
                    edge.get("consumer_event") == witness["claim_event"] and
                    edge.get("token") == witness.get("token") and
                    all(edge.get(key) == witness.get(key)
                        for key in ("node", "epoch", "thread"))
                    for edge in edges))
                if (not fault < submit < enter < claim < target_enter < target_check
                        or witness["fault_event"] not in row.get("applied_fault_event_ids", [])
                        or witness.get("node") in (None, "", "unknown")
                        or not witness.get("thread") or not matched_edge
                        or witness.get("evidence_type") !=
                        "observed_task_edge_and_same_thread_retry_continuation"):
                    valid_rows = False
                    break
            if valid_rows and paths and not _verify_retry_path_trace(
                    trial_path.parent, trial, row, result):
                valid_rows = False
            if not valid_rows:
                break
    valid = (
        index.get("schema_version") == 1
        and index.get("review_status") == "verified_faulted_event_path"
        and entry.get("classification") == "observed_event_path"
        and entry.get("receipt_sha256") == receipt_hash
        and entry.get("result_sha256") == result_hash
        and entry.get("audit_sha256") == audit_hash
        and entry.get("config_sha256") == config_hash
        and entry.get("archive_sha256") == archive_hash
        and entry.get("archive_manifest_sha256") == manifest_hash
        and receipt.get("schema_version") == 1
        and receipt.get("case_id") == case_id
        and receipt.get("status") == "postfault_retry_target_proven"
        and receipt.get("campaign_result_sha256") == result_hash
        and receipt.get("offline_audit_sha256") == audit_hash
        and receipt.get("config_sha256") == config_hash
        and manifest is not None
        and manifest.get("case_id") == case_id
        and manifest.get("archive_sha256") == archive_hash
        and manifest.get("campaign_result_sha256") == result_hash
        and manifest.get("offline_audit_sha256") == audit_hash
        and manifest.get("config_sha256") == config_hash
        and manifest.get("continuation_receipt_sha256") == receipt_hash
        and valid_rows
        and proven == receipt.get("proven_postfault_path_trials")
        and proven == entry.get("qualifying_trial_count")
        and proven == manifest.get("strict_path_trials")
        and 0 < proven <= result.get("strict_target_trials", 0)
    )
    return ("observed_event_path" if valid else "invalid"), str(receipt_path)


def _hbase07_client_event_review(results: Path, result_path: Path,
                                result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Recompute the client-only faulted paths before accepting its new canonical run."""
    if result.get("case_id") != "HBASE-07":
        return None, None
    baseline = Path(__file__).resolve().parents[2]
    root = results / "quality_reviews/hbase07_client_only_v1"
    index_path, review_path = root / "index.json", root / "HBASE-07.json"
    index, review = _json(index_path), _json(review_path)
    if not isinstance(index, dict) or not isinstance(review, dict):
        return "invalid", str(review_path)
    release = (baseline / "Mallory/dispatch/releases/"
               "96dd5cda2fe8e3f67130c8232fb98fa316a1eeac9a2ff3237075d7d8fe95538d")
    verifier = baseline / "Mallory/adapters/hbase/pilot/verify-HBASE-07-client-only-v1-review.py"
    campaign = results / "HBASE-07/campaigns/client-only-v1"
    legacy = results / "HBASE-07/campaigns/legacy-pre-client-only"
    legacy_review = results / "HBASE-07/campaigns/legacy-pre-client-only-causal-precision-v2.json"
    archive = results / "evidence_archives/campaign_client_only_v1/HBASE-07.tar.gz"
    collector = results / "HBASE-07/campaigns/client-only-v1-receipt.json"
    audit_path, config_path = campaign / "offline-causal-audit.json", campaign / "config.json"
    healthy_trial = campaign / "trials/r0000/result.json"
    needed = (verifier, release / "manifest.json", review_path, result_path,
              audit_path, config_path, archive, collector, legacy_review,
              legacy / "result.json", legacy / "offline-causal-audit.json",
              healthy_trial)
    if any(not path.is_file() for path in needed):
        return "invalid", str(review_path)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    valid = (
        index.get("schema_version") == 1
        and index.get("case_id") == "HBASE-07"
        and index.get("classification") == "observed_event_path"
        and index.get("receipt") == "data/mallory/quality_reviews/hbase07_client_only_v1/HBASE-07.json"
        and index.get("receipt_sha256") == digest(review_path)
        and index.get("verifier_sha256") == digest(verifier)
        and index.get("result_sha256") == digest(result_path) == digest(campaign / "result.json")
        and index.get("audit_sha256") == digest(audit_path)
        and index.get("config_sha256") == digest(config_path)
        and index.get("archive_sha256") == digest(archive)
        and index.get("collector_receipt_sha256") == digest(collector)
        and index.get("core_manifest_sha256") == digest(release / "manifest.json")
        and index.get("legacy_v2_review_sha256") == digest(legacy_review)
        and index.get("legacy_v2_result_sha256") == digest(legacy / "result.json")
        and index.get("legacy_v2_audit_sha256") == digest(legacy / "offline-causal-audit.json")
        and index.get("strict_postfault_event_path_trials") == 27
        and review.get("schema_version") == 1
        and review.get("case_id") == "HBASE-07"
        and review.get("classification") == "observed_event_path"
        and review.get("status") == "positive_frozen_96dd_review"
        and review.get("campaign_result_sha256") == digest(result_path)
        and review.get("campaign_audit_sha256") == digest(audit_path)
        and review.get("campaign_config_sha256") == digest(config_path)
        and review.get("archive_sha256") == digest(archive)
        and review.get("collector_receipt_sha256") == digest(collector)
        and review.get("core_manifest_sha256") == digest(release / "manifest.json")
        and review.get("core_release_id") == release.name
        and review.get("versioned_campaign_path") == "data/mallory/HBASE-07/campaigns/client-only-v1"
        and review.get("healthy_trial_result_sha256") == digest(healthy_trial)
        and review.get("legacy_negative_review_sha256") == digest(legacy_review)
        and review.get("legacy_result_sha256") == digest(legacy / "result.json")
        and review.get("legacy_audit_sha256") == digest(legacy / "offline-causal-audit.json")
        and review.get("canonical_result_path") == "data/mallory/cases/HBASE-07/result.json"
        and review.get("canonical_audit_path") == "data/mallory/cases/HBASE-07/offline-causal-audit.json"
        and result_path.resolve() == (campaign / "result.json").resolve()
        and result.get("status") == review.get("campaign_status") == "queue_exhausted"
        and result.get("duration_seconds") == review.get("duration_seconds")
        and result.get("fault_trials_completed") == review.get("fault_trials_completed") == 27
        and result.get("strict_injected_trials") == review.get("strict_injected_trials") == 27
        and result.get("strict_target_trials") == review.get("strict_postfault_event_path_trials") == 27
        and result.get("exact_exception_trials") == review.get("selected_exception_trials") == 0
        and review.get("qualifying_trial_ids") == list(range(1, 28)))
    if not valid:
        return "invalid", str(review_path)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = f"{release}:{baseline}"
    try:
        check = subprocess.run(
            ["python3", str(verifier), "--repo", str(baseline), "--review", str(review_path)],
            cwd=baseline, env=environment, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return "invalid", str(review_path)
    return ("observed_event_path" if check.returncode == 0 else "invalid"), str(review_path)


def _solr10_role_event_review(results: Path, result_path: Path,
                              result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Admit symbolic leader points only through their separate pinned audit.

    The frozen generic auditor expects a static physical point and correctly
    rejects this campaign's role-bound plans.  Its negative is retained as a
    diagnostic; the role-aware verifier checks all 80 trials offhost and this
    local gate recomputes one SHA-matched fault-to-target path.
    """
    if result.get("case_id") != "SOLR-10":
        return None, None
    baseline = Path(__file__).resolve().parents[2]
    index_path = results / "quality_reviews/solr10_role_v1_full/index.json"
    index = _json(index_path)
    verifier = (baseline / "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1/"
                "terminal-role-audit/verify_sparse.py")
    if (not isinstance(index, dict) or not verifier.is_file()
            or index.get("sparse_verifier_sha256") !=
            hashlib.sha256(verifier.read_bytes()).hexdigest()
            or result_path.resolve() !=
            (results / "replays/SOLR-10-role-v1-full-metadata/result.json").resolve()):
        return "invalid", str(index_path)
    try:
        # The role receipt pins the historical core audit source.  Current
        # Mallory/core/audit.py may evolve, so expose that pinned release in a
        # read-only verification root while leaving the campaign files in place.
        frozen_audit = (baseline / "Mallory/dispatch/releases/"
                        "4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4/"
                        "Mallory/core/audit.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replay = root / "data/mallory/replays/SOLR-10-role-v1-full-metadata"
            replay.parent.mkdir(parents=True)
            replay.symlink_to(result_path.parent.resolve(), target_is_directory=True)
            case = root / "Mallory/adapters/solr/cases/SOLR-10-role-binding-v1"
            case.parent.mkdir(parents=True)
            case.symlink_to(verifier.parents[1], target_is_directory=True)
            audit = root / "Mallory/core/audit.py"
            audit.parent.mkdir(parents=True)
            audit.symlink_to(frozen_audit)
            check = subprocess.run(
                ["python3", str(verifier), "--base", str(root), "--canonical",
                 str(result_path.parent), "--index", str(index_path)],
                cwd=baseline, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "invalid", str(index_path)
    return ("observed_event_path" if check.returncode == 0 else "invalid"), str(index_path)


def _zk12_filenotfound_review(results: Path, result_path: Path,
                             result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Recheck every archived FNF fault and same-occurrence selected guard."""
    if result.get("case_id") != "ZOOKEEPER-12":
        return None, None
    baseline = Path(__file__).resolve().parents[2]
    root = results / "quality_reviews/zk12_filenotfound_full"
    index_path, receipt_path = root / "index.json", root / "ZOOKEEPER-12.json"
    index, receipt = _json(index_path), _json(receipt_path)
    verifier = baseline / "Mallory/adapters/zookeeper/verify_zk12_terminal.py"
    paths = {
        "verifier": verifier,
        "receipt": receipt_path,
        "result": result_path,
        "audit": result_path.with_name("offline-causal-audit.json"),
        "config": result_path.with_name("config.json"),
        "sync": result_path.with_name("sync-receipt.json"),
        "archive": results / "evidence_archives/campaign/ZOOKEEPER-12.tar.gz",
        "archive_manifest": results / "evidence_archives/campaign/ZOOKEEPER-12.tar.manifest.json",
        "prior_review": results / "admissions/ZOOKEEPER-12-fa5f-filenotfound-v1-full-review.json",
    }
    if (not isinstance(index, dict) or not isinstance(receipt, dict)
            or any(not path.is_file() or
                   index.get(f"{name}_sha256") != hashlib.sha256(path.read_bytes()).hexdigest()
                   for name, path in paths.items())):
        return "invalid", str(index_path)
    if not (
        index.get("schema_version") == 1
        and index.get("case_id") == "ZOOKEEPER-12"
        and index.get("classification") == "observed_local_timeline"
        and index.get("qualifying_trial_count") == 14
        and result_path.resolve() == (results / "cases/ZOOKEEPER-12/result.json").resolve()
        and result.get("status") == "queue_exhausted"
        and result.get("fault_trials_completed") == 18
        and result.get("strict_injected_trials") == 18
        and result.get("strict_target_trials") == 14
        and result.get("exact_exception_trials") == 0
        and receipt.get("status") == "terminal_verified_no_selected_exception"
        and receipt.get("classification") == "target_exercised_local_timeline"
        and receipt.get("fault_trials") == 18
        and receipt.get("faults_matched_and_applied") == 36
        and receipt.get("strict_same_actor_postfault_check_trials") == 14
        and receipt.get("target_lost_trials") == 4
        and receipt.get("selected_target_exception_trials") == 0
        and isinstance(receipt.get("trial_evidence"), list)
        and len(receipt["trial_evidence"]) == 18
        and sum(row.get("classification") == "target_retained_no_throw"
                for row in receipt["trial_evidence"]) == 14
        and all(row.get("classification") in {"target_retained_no_throw", "target_lost"}
                for row in receipt["trial_evidence"])
    ):
        return "invalid", str(index_path)
    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary) / "independent.json"
        try:
            check = subprocess.run(
                ["python3", str(verifier), "--root", str(baseline),
                 "--output", str(output)], cwd=baseline, capture_output=True,
                text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return "invalid", str(index_path)
        if (check.returncode != 0 or not output.is_file()
                or output.read_bytes() != receipt_path.read_bytes()):
            return "invalid", str(index_path)
    return "observed_local_timeline", str(receipt_path)


def _hdfs11_faulted_event_review(results: Path, result_path: Path,
                                 result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Recompute the exact NN error-response-to-DN path from frozen raw traces."""
    if result.get("case_id") != "HDFS-11":
        return None, None
    review_root = results / "quality_reviews/hdfs11_v27_faulted_path"
    index_path = review_root / "index.json"
    if not index_path.is_file():
        return None, None
    receipt_path = review_root / "HDFS-11.json"
    index, receipt = _json(index_path), _json(receipt_path)
    if not isinstance(index, dict) or not isinstance(receipt, dict):
        return "invalid", str(receipt_path)
    baseline = Path(__file__).resolve().parents[2]
    verifier = baseline / "Mallory/ops/audit_hdfs11_v27_full.py"
    release = (baseline / "Mallory/dispatch/releases/"
               "fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f")
    manifest = release / "manifest.json"
    graph = release / "Mallory/core/graph.py"
    archive_path = results / "evidence_archives/campaign/HDFS-11.tar.gz"
    archive_manifest = results / "evidence_archives/campaign/HDFS-11.tar.manifest.json"
    needed = (verifier, manifest, graph, archive_path, archive_manifest,
              result_path, result_path.with_name("config.json"),
              result_path.with_name("offline-causal-audit.json"))
    if any(not path.is_file() for path in needed):
        return "invalid", str(receipt_path)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    valid = (
        index.get("schema_version") == 1 and
        index.get("case_id") == "HDFS-11" and
        index.get("classification") == "observed_event_path" and
        index.get("receipt_sha256") == digest(receipt_path) and
        index.get("verifier_sha256") == digest(verifier) and
        index.get("core_manifest_sha256") == digest(manifest) and
        receipt.get("graph_source_sha256") == digest(graph) and
        receipt.get("classification") == "observed_event_path" and
        receipt.get("campaign_result_sha256") == digest(result_path) and
        receipt.get("offline_audit_sha256") ==
            digest(result_path.with_name("offline-causal-audit.json")) and
        receipt.get("config_sha256") == digest(result_path.with_name("config.json")) and
        receipt.get("archive_sha256") == digest(archive_path) and
        receipt.get("archive_manifest_sha256") == digest(archive_manifest) and
        receipt.get("strict_injected_trials") == result.get("strict_injected_trials") and
        receipt.get("strict_target_trials") == result.get("strict_target_trials") and
        isinstance(receipt.get("qualifying_trial_count"), int) and
        0 < receipt["qualifying_trial_count"] <= result.get("strict_target_trials", 0) and
        index.get("qualifying_trial_count") == receipt["qualifying_trial_count"])
    if not valid:
        return "invalid", str(receipt_path)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = f"{release}:{baseline}"
    check = subprocess.run(
        ["python3", str(verifier), "--campaign", str(result_path.parent.resolve()),
         "--out", str(receipt_path.resolve()), "--verify"],
        cwd=baseline, env=environment, capture_output=True, text=True, timeout=30)
    return ("observed_event_path" if check.returncode == 0 else "invalid"), str(receipt_path)


def _verify_retry_path_trace(trial_dir: Path, trial: dict[str, Any],
                             row: dict[str, Any], result: dict[str, Any]) -> bool:
    """Recheck a positive task-handoff witness against SHA-verified raw events."""
    evidence = trial.get("events_evidence")
    if not isinstance(evidence, dict):
        return False
    name = evidence.get("gzip_path") or evidence.get("raw_path")
    if not isinstance(name, str) or Path(name).name != name:
        return False
    path = trial_dir / name
    if not path.is_file():
        return False
    if evidence.get("gzip_path") and (
            hashlib.sha256(path.read_bytes()).hexdigest() != evidence.get("gzip_sha256") or
            path.stat().st_size != evidence.get("gzip_bytes")):
        return False
    witnesses = row["postfault_retry_target_paths"]
    event_ids = {witness[name] for witness in witnesses for name in (
        "fault_event", "old_enter_event", "submit_event", "old_exit_event",
        "new_enter_event", "claim_event", "target_enter_event", "target_check_event")}
    tokens = {witness["token"] for witness in witnesses}
    found: dict[str, dict[str, Any]] = {}
    token_events: dict[tuple[str, str], list[str]] = {}
    raw = hashlib.sha256()
    raw_bytes = 0
    try:
        opener = gzip.open if evidence.get("gzip_path") else open
        with opener(path, "rb") as source:
            for line in source:
                raw.update(line)
                raw_bytes += len(line)
                event = json.loads(line)
                event_id = event.get("id")
                if event_id in event_ids:
                    found[event_id] = event
                token = event.get("correlation")
                kind = event.get("type")
                if token in tokens and kind in {"TASK_SUBMIT", "TASK_CLAIM"}:
                    token_events.setdefault((token, kind), []).append(event_id)
    except (OSError, EOFError, ValueError, TypeError):
        return False
    if (raw.hexdigest() != row.get("trace_raw_sha256") or
            raw_bytes != evidence.get("raw_bytes") or len(found) != len(event_ids)):
        return False
    check_sites = result.get("target", {}).get("check_sites", [])
    for witness in witnesses:
        token = witness["token"]
        token_parts = token.split(":") if isinstance(token, str) else []
        if (len(token_parts) != 6 or token_parts[0] != "zk-following-retry" or
                not token_parts[3].isdigit() or not token_parts[4].isdigit() or
                int(token_parts[3]) <= 0 or int(token_parts[4]) <= 0 or
                token_events.get((token, "TASK_SUBMIT")) != [witness["submit_event"]] or
                token_events.get((token, "TASK_CLAIM")) != [witness["claim_event"]]):
            return False
        fault, old_enter, submit, old_exit, new_enter, claim, target_enter, check = (
            found[witness[name]] for name in (
                "fault_event", "old_enter_event", "submit_event", "old_exit_event",
                "new_enter_event", "claim_event", "target_enter_event",
                "target_check_event"))
        kinds = ("FAULT_APPLIED", "REGION_ENTER", "TASK_SUBMIT", "REGION_EXIT",
                 "REGION_ENTER", "TASK_CLAIM", "REGION_ENTER", "TARGET_CHECK")
        if tuple(event.get("type") for event in (
                fault, old_enter, submit, old_exit, new_enter, claim,
                target_enter, check)) != kinds:
            return False
        if any(event.get(key) != witness.get(key) for event in (
                fault, old_enter, submit, old_exit, new_enter, claim,
                target_enter, check) for key in ("node", "epoch", "thread")):
            return False
        if (fault.get("occurrence") != old_enter.get("occurrence") or
                submit.get("occurrence") != fault.get("occurrence") or
                old_exit.get("occurrence") != fault.get("occurrence") or
                new_enter.get("occurrence") != claim.get("occurrence") or
                submit.get("correlation") != token or claim.get("correlation") != token or
                claim.get("parent_id") != token or
                target_enter.get("parent_id") != claim.get("occurrence") or
                check.get("occurrence") != target_enter.get("occurrence") or
                check.get("site") not in check_sites):
            return False
    return True


def _local_timeline_review(results: Path, result_path: Path,
                           result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Recheck a named-thread continuation within one unique region occurrence."""
    root = results / "quality_reviews" / "local_timeline_v1"
    case_id = result.get("case_id")
    receipt_path = root / f"{case_id}.json"
    index = _json(root / "index.json")
    if index is None:
        return ("invalid", str(receipt_path)) if receipt_path.is_file() else (None, None)
    entries = index.get("cases")
    if not isinstance(entries, list):
        return "invalid", str(root / "index.json")
    matches = [row for row in entries if isinstance(row, dict)
               and row.get("case_id") == case_id]
    if not matches:
        return ("invalid", str(receipt_path)) if receipt_path.is_file() else (None, None)
    if len(matches) != 1:
        return "invalid", str(root / "index.json")
    try:
        entry = matches[0]
        receipt = _json(receipt_path)
        if receipt is None:
            return "invalid", str(receipt_path)
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        audit_path = result_path.with_name("offline-causal-audit.json")
        config_path = result_path.with_name("config.json")
        archive_path = results / "evidence_archives/campaign" / f"{case_id}.tar.gz"
        manifest_path = archive_path.with_suffix(".manifest.json")
        sync_path = result_path.with_name("sync-receipt.json")
        result_hash, audit_hash = sha(result_path), sha(audit_path)
        config_hash, archive_hash = sha(config_path), sha(archive_path)
        manifest_hash, sync_hash = sha(manifest_path), sha(sync_path)
        receipt_hash = sha(receipt_path)
        audit = _json(audit_path)
        manifest = _json(manifest_path)
        sync = _json(sync_path)

        def sidecar(name: str) -> tuple[dict[str, Any], str]:
            if (not isinstance(name, str) or Path(name).is_absolute() or
                    Path(name).parent != Path("data/mallory/audit_sidecars")):
                raise ValueError("sidecar path escapes audit_sidecars")
            path = (results.resolve().parent.parent / name).resolve()
            if not path.is_relative_to((results / "audit_sidecars").resolve()):
                raise ValueError("sidecar path escapes results")
            value = _json(path)
            if value is None:
                raise ValueError("sidecar missing")
            return value, sha(path)

        prior, prior_hash = sidecar(receipt["prior_precision_receipt"])
        witness, witness_hash = sidecar(receipt["trial_witnesses_receipt"])
        rows = witness.get("trials")
        if (index.get("schema_version") != 1 or
                index.get("review_status") != "verified_faulted_local_timeline" or
                entry.get("classification") != "observed_local_timeline" or
                entry.get("receipt_sha256") != receipt_hash or
                entry.get("result_sha256") != result_hash or
                entry.get("audit_sha256") != audit_hash or
                entry.get("archive_sha256") != archive_hash or
                receipt.get("schema_version") != 1 or
                receipt.get("kind") != "verified_faulted_local_timeline_v1" or
                receipt.get("case_id") != case_id or
                receipt.get("campaign_result_sha256") != result_hash or
                receipt.get("offline_audit_sha256") != audit_hash or
                receipt.get("config_sha256") != config_hash or
                receipt.get("archive_sha256") != archive_hash or
                receipt.get("archive_manifest_sha256") != manifest_hash or
                receipt.get("sync_receipt_sha256") != sync_hash or
                receipt.get("prior_precision_receipt_sha256") != prior_hash or
                receipt.get("trial_witnesses_receipt_sha256") != witness_hash or
                receipt.get("thread_identity") !=
                "thread_name_plus_unique_reload_occurrence" or
                receipt.get("numeric_thread_id_proven") is not False or
                receipt.get("one_region_enter_per_witness_actor") is not True or
                audit is None or audit.get("report_gate_passed") is not True or
                audit.get("local_timeline_only") is not True or
                audit.get("same_actor_target_gate_passed") is not True or
                audit.get("campaign_result_sha256") != result_hash or
                manifest is None or manifest.get("case_id") != case_id or
                manifest.get("source_result_sha256") != result_hash or
                manifest.get("config_sha256") != config_hash or
                manifest.get("archive_sha256") != archive_hash or
                sync is None or sync.get("result_sha256") != result_hash or
                manifest.get("members") != {
                    **sync["retained_files"], **sync["remote_only_scratch_files"]} or
                witness.get("case_id") != case_id or
                witness.get("campaign_result_sha256") != result_hash or
                witness.get("offline_causal_audit_sha256") != audit_hash or
                witness.get("prior_precision_receipt_sha256") != prior_hash or
                prior.get("campaign_result_sha256") != result_hash or
                prior.get("offline_causal_audit_sha256") != audit_hash or
                not isinstance(rows, list) or not rows or
                len(rows) != witness.get("qualifying_trials") or
                len(rows) != receipt.get("qualifying_trial_count") or
                len(rows) != entry.get("qualifying_trial_count") or
                len(rows) != audit.get("same_actor_target_trials") or
                len(rows) > result.get("strict_target_trials", 0) or
                len({row.get("trial_id") for row in rows}) != len(rows)):
            return "invalid", str(receipt_path)

        check_sites = set(result["target"]["check_sites"])
        proven = 0
        for row in rows:
            trial_id = row["trial_id"]
            if not isinstance(trial_id, int) or not 1 <= trial_id <= result["fault_trials_completed"]:
                return "invalid", str(receipt_path)
            trial_dir = result_path.parent / "trials" / f"r{trial_id:04d}"
            trial_path = trial_dir / "result.json"
            trace_path = trial_dir / "events.jsonl.gz"
            trial = _json(trial_path)
            if (trial is None or sha(trial_path) != row.get("trial_result_sha256") or
                    sha(trace_path) != row.get("trace_gzip_sha256") or
                    trace_path.stat().st_size != row.get("trace_gzip_bytes") or
                    trial.get("events_evidence", {}).get("gzip_sha256") !=
                    row.get("trace_gzip_sha256") or
                    trial["events_evidence"].get("raw_sha256") !=
                    row.get("trace_raw_sha256")):
                return "invalid", str(receipt_path)
            feedback = trial.get("feedback", {})
            if (feedback.get("target_reached") is not True or
                    feedback.get("all_faults_effective") is not True or
                    feedback.get("all_faults_applied") is not True or
                    feedback.get("target_identity_complete") is not True):
                return "invalid", str(receipt_path)
            witnesses = row.get("witnesses")
            if not isinstance(witnesses, list) or not witnesses:
                return "invalid", str(receipt_path)
            ids = {part["id"] for item in witnesses for part in
                   (item["door"], item["fault"], item["target_check"])}
            actors = {(item["node"], item["epoch"], item["occurrence"], item["thread"])
                      for item in witnesses}
            found = {}
            enter_counts = Counter()
            thread_ids: set[Any] = set()
            raw = hashlib.sha256()
            raw_bytes = 0
            with gzip.open(trace_path, "rb") as stream:
                for line in stream:
                    raw.update(line)
                    raw_bytes += len(line)
                    event = json.loads(line)
                    event_actor = (event.get("node"), event.get("epoch"),
                                   event.get("occurrence"), event.get("thread"))
                    if event_actor in actors:
                        thread_ids.add(event.get("thread_id"))
                        if event.get("type") == "REGION_ENTER":
                            enter_counts[event_actor] += 1
                    if event.get("id") in ids:
                        if event["id"] in found:
                            return "invalid", str(receipt_path)
                        found[event["id"]] = event
            if (raw.hexdigest() != row.get("trace_raw_sha256") or
                    raw_bytes != row.get("trace_raw_bytes") or
                    found.keys() != ids or thread_ids != {None} or
                    any(enter_counts[actor] != 1 for actor in actors)):
                return "invalid", str(receipt_path)
            for item in witnesses:
                door = found[item["door"]["id"]]
                fault = found[item["fault"]["id"]]
                check = found[item["target_check"]["id"]]
                actor = (item["node"], item["epoch"], item["occurrence"], item["thread"])
                if (not isinstance(item["node"], str) or item["node"] in ("", "unknown") or
                        not isinstance(item["thread"], str) or not item["thread"] or
                        not item["occurrence"] or
                        item["occurrence"].startswith("unscoped:") or
                        item["occurrence"].endswith(":root") or
                        tuple(event.get("type") for event in (door, fault, check)) !=
                        ("DOOR_OBSERVED", "FAULT_APPLIED", "TARGET_CHECK") or
                        not door["seq"] < fault["seq"] < check["seq"] or
                        check["seq"] <= feedback.get("last_fault_seq", -1) or
                        door.get("site") != item["door"]["site"] or
                        fault.get("site") != item["fault"]["site"] or
                        door.get("site") != fault.get("site") or
                        check.get("site") != item["target_check"]["site"] or
                        check.get("site") not in check_sites or
                        fault.get("fault_id") != item["fault"]["fault_id"] or
                        fault.get("fault_id") not in feedback.get("applied_fault_ids", []) or
                        any((event.get("node"), event.get("epoch"),
                             event.get("occurrence"), event.get("thread")) != actor
                            for event in (door, fault, check))):
                    return "invalid", str(receipt_path)
            proven += 1
        return ("observed_local_timeline" if proven > 0 else "invalid"), str(receipt_path)
    except (OSError, KeyError, TypeError, ValueError, AttributeError, EOFError):
        return "invalid", str(receipt_path)


def _posthoc_attestation(result_path: Path, case: dict[str, Any],
                         result: dict[str, Any]) -> str | None:
    """Recognize a separate audit without changing the campaign's raw result."""
    path = result_path.with_name("posthoc-attestation.json")
    audit = _json(path)
    if audit is None:
        return None
    target = result.get("target")
    if not isinstance(target, dict):
        return "invalid"
    root = result_path.parent.resolve()

    def archived_hash(path_key: str, hash_key: str) -> bool:
        relative = audit.get(path_key)
        expected = audit.get(hash_key)
        if not isinstance(relative, str) or not isinstance(expected, str):
            return False
        path = (root / relative).resolve()
        return (path.is_relative_to(root) and path.is_file() and
                hashlib.sha256(path.read_bytes()).hexdigest() == expected)

    trials = result.get("fault_trials_completed")
    class_hash = audit.get("archived_compiled_target_sha256")
    checks = audit.get("target_class_loader_per_trial")
    trial_rows = result.get("trials")
    catalogs_valid = False
    if isinstance(trial_rows, list) and isinstance(checks, list) and len(trial_rows) == len(checks):
        try:
            target_class = target["throw_site"].split("#", 1)[0]
            catalogs_valid = True
            for trial, expected_loaders in zip(trial_rows, checks):
                trial_result = (root / trial["result"]).resolve()
                if not trial_result.is_relative_to(root):
                    catalogs_valid = False
                    break
                catalog = trial_result.with_name("sites.jsonl")
                rows = [json.loads(line) for line in catalog.read_text(encoding="utf-8").splitlines()
                        if line.strip()]
                target_rows = [row for row in rows if row.get("class_name") == target_class]
                sites = {(row.get("type"), row.get("site")) for row in target_rows}
                hashes = {row.get("bytecode_sha256") for row in target_rows}
                loaders = sorted({row.get("class_loader_id") for row in target_rows})
                if (not target_rows or hashes != {class_hash} or
                        loaders != expected_loaders or
                        any(("TARGET_CHECK", site) not in sites
                            for site in target.get("check_sites", [])) or
                        ("TARGET_THROW", target["throw_site"]) not in sites):
                    catalogs_valid = False
                    break
        except (OSError, ValueError, TypeError, KeyError):
            catalogs_valid = False
    valid = (
        audit.get("schema_version") == 1 and audit.get("attestation") == "passed"
        and audit.get("case_id") == case["case_id"]
        and audit.get("campaign_status") == result.get("status")
        and audit.get("campaign_result_sha256") == hashlib.sha256(result_path.read_bytes()).hexdigest()
        and isinstance(audit.get("target_source_sha256"), str)
        and len(audit["target_source_sha256"]) == 64
        and audit.get("exact_check_site") in target.get("check_sites", [])
        and audit.get("exact_throw_site") == target.get("throw_site")
        and isinstance(trials, int) and audit.get("trials_audited") == trials + 1
        and isinstance(audit.get("counts"), dict)
        and audit["counts"].get("effective_fault") == result.get("strict_injected_trials")
        and isinstance(class_hash, str) and len(class_hash) == 64
        and audit.get("loaded_target_class_sha256") == [class_hash]
        and archived_hash("archived_compiled_target_path", "archived_compiled_target_sha256")
        and archived_hash("agent_jar_path", "agent_jar_sha256")
        and archived_hash("source_snapshot_path", "source_snapshot_sha256")
        and isinstance(checks, list) and len(checks) == trials + 1
        and all(isinstance(loaders, list) and len(loaders) == 1 and
                isinstance(loaders[0], str) and loaders[0] for loaders in checks)
        and catalogs_valid
    )
    return "verified" if valid else "invalid"


def _source_review(results: Path, result_path: Path,
                   result: dict[str, Any]) -> dict[str, Any] | None:
    """Read a review only when it is bound to the terminal raw result and evidence."""
    if result.get("status") not in TERMINAL:
        return None
    case_id = result.get("case_id")
    if not isinstance(case_id, str):
        return None
    root = (results / "triage" / case_id).resolve()
    receipt_path = root / "review.json"
    receipt = _json(receipt_path)
    if receipt is None:
        return None
    triage_path = root / "triage.json"
    triage = _json(triage_path)
    if triage is None:
        return {"status": "invalid_review", "new_bug": None,
                "error": "missing triage manifest"}
    allowed = {"expected_guard", "confirmed_new_bug", "inconclusive"}
    status = receipt.get("source_review_status")
    bug = receipt.get("new_bug")
    valid = (
        receipt.get("schema_version") == 1
        and receipt.get("case_id") == case_id
        and receipt.get("campaign_result_sha256") ==
        hashlib.sha256(result_path.read_bytes()).hexdigest()
        and receipt.get("triage_sha256") ==
        hashlib.sha256(triage_path.read_bytes()).hexdigest()
        and triage.get("case_id") == case_id
        and receipt.get("classification") == triage.get("classification")
        and status in allowed
        and isinstance(bug, bool)
        and (bug is (status == "confirmed_new_bug"))
    )
    files = triage.get("files")
    if not isinstance(files, list) or not files:
        valid = False
    else:
        for item in files:
            if not isinstance(item, dict):
                valid = False
                break
            relative = item.get("path")
            expected_hash = item.get("sha256")
            expected_size = item.get("bytes")
            if (not isinstance(relative, str) or not isinstance(expected_hash, str)
                    or not isinstance(expected_size, int) or isinstance(expected_size, bool)):
                valid = False
                break
            path = (root / relative).resolve()
            if (not path.is_relative_to(root) or not path.is_file()
                    or path.stat().st_size != expected_size
                    or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash):
                valid = False
                break
    if not valid:
        return {"status": "invalid_review", "new_bug": None,
                "error": "review receipt or preserved evidence mismatch"}
    return {"status": status, "new_bug": bug,
            "receipt_path": str(receipt_path),
            "classification": receipt["classification"]}


def _unstable_existing_workload_gap(results: Path, case_id: str,
                                    receipt: dict[str, Any]) -> str:
    """Verify the versioned ZK13 existing-test stability finding and raw runs."""
    root = (results / "calibration" / case_id).resolve()
    project_root = results.resolve().parent.parent

    def bound(relative: str, expected_hash: str) -> Path:
        path = (project_root / relative).resolve()
        if (not path.is_relative_to(root) or not path.is_file() or
                hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash):
            raise ValueError("unstable-workload evidence hash or path mismatch")
        return path

    def standalone_raw(path: Path, attestation: dict[str, Any]) -> None:
        for name, expected_hash in attestation["evidence_sha256"].items():
            if (Path(name).name != name or
                    hashlib.sha256((path.parent / name).read_bytes()).hexdigest() != expected_hash):
                raise ValueError("standalone trace or command differs")
        reports = list(path.parent.glob("TEST-*.xml"))
        outputs = list(path.parent.glob("*-output.txt"))
        if (len(reports) != 1 or len(outputs) != 1 or
                hashlib.sha256(reports[0].read_bytes()).hexdigest() !=
                attestation["junit_report_sha256"] or
                hashlib.sha256(outputs[0].read_bytes()).hexdigest() !=
                attestation["junit_output_sha256"]):
            raise ValueError("standalone JUnit report differs")

    try:
        relative = receipt["stability_path"]
        expected = receipt["stability_sha256"]
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("stability receipt fields missing")
        stability = _json(bound(relative, expected))
        if stability is None:
            raise ValueError("stability assessment missing")
        rows = stability["selected_selector_runs"]
        if (case_id != "ZOOKEEPER-13" or receipt.get("schema_version") != 1 or
                receipt.get("case_id") != case_id or
                receipt.get("status") != "no_suitable_cluster_test" or
                stability.get("schema_version") != 1 or
                stability.get("case_id") != case_id or
                stability.get("status") != "no_stable_existing_cluster_test" or
                stability.get("selected_selector") != "ReadOnlyModeTest#testConnectionEvents" or
                len(rows) != 6 or stability.get("selected_selector_total_runs") != 6 or
                stability.get("selected_selector_target_reached_runs") != 3 or
                sum(row.get("target_reached") is True for row in rows) != 3 or
                {row.get("source") for row in rows} != {"standalone_junit", "campaign_r0000"}):
            raise ValueError("unstable-workload summary inconsistent")
        source_archive = root / "workload-review/receipt/source-class-agent.tar.gz"
        if (not source_archive.is_file() or
                hashlib.sha256(source_archive.read_bytes()).hexdigest() !=
                _json(root / "workload-review/receipt/workload-suitability-receipt.json")[
                    "source_archive_sha256"]):
            raise ValueError("source snapshot differs")
        with tarfile.open(source_archive) as archive:
            source_hashes = stability["source_sha256"]
            for name, expected_hash in source_hashes.items():
                member = archive.extractfile(name)
                if member is None or hashlib.sha256(member.read()).hexdigest() != expected_hash:
                    raise ValueError("archived source or class differs")
            for name, expected_hash in (
                    ("mallory-agent.jar", stability["agent_jar_sha256"]),
                    ("source-overlay-receipt.json", stability["source_overlay_receipt_sha256"])):
                member = archive.extractfile(name)
                if member is None or hashlib.sha256(member.read()).hexdigest() != expected_hash:
                    raise ValueError("archived agent or overlay receipt differs")
        loaded_class = stability["loaded_target_class_sha256"]
        if loaded_class != source_hashes[
                "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.class"]:
            raise ValueError("loaded target class differs from archived class")
        for key, expected_status in (("original_expected_refusal", "original_expected_target_throw_observed"),
                                     ("other_alternate_target_miss", "alternate_target_missed")):
            item = stability[key]
            evidence_path = bound(item["evidence"], item["evidence_sha256"])
            evidence = _json(evidence_path)
            if (evidence is None or evidence.get("status") != expected_status or
                    evidence.get("loaded_target_class_sha256") != loaded_class or
                    evidence.get("target_source_sha256") != source_hashes[
                        "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java"] or
                    evidence.get("test_source_sha256") != stability["test_source_sha256"]):
                raise ValueError("other selector evidence differs")
            standalone_raw(evidence_path, evidence)
        if (stability["original_expected_refusal"]["exact_throws"] <= 0 or
                stability["other_alternate_target_miss"]["exact_checks"] != 0):
            raise ValueError("expected-throw or target-miss conclusion differs")
        campaign_rows = {}
        for row in rows:
            evidence_path = bound(row["evidence"], row["evidence_sha256"])
            evidence = _json(evidence_path)
            if evidence is None:
                raise ValueError("run evidence missing")
            if row["source"] == "standalone_junit":
                if (evidence.get("loaded_target_class_sha256") != loaded_class or
                        evidence.get("target_source_sha256") != source_hashes[
                            "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer.java"] or
                        evidence.get("test_source_sha256") != stability["test_source_sha256"] or
                        (evidence.get("target_check_count", 0) > 0) is not row["target_reached"] or
                        evidence.get("target_throw_count") != 0):
                    raise ValueError("standalone target claim differs")
                standalone_raw(evidence_path, evidence)
            else:
                if (evidence.get("case_id") != case_id or
                        evidence.get("cluster_test") != "org.apache.zookeeper.test.ReadOnlyModeTest#testConnectionEvents" or
                        evidence["trials"][0].get("target_reached") is not row["target_reached"]):
                    raise ValueError("campaign healthy target claim differs")
                campaign_rows[row["name"]] = evidence
        short = campaign_rows["short_campaign_healthy"]
        invalid = campaign_rows["full_attempt_healthy"]
        pilot = stability["strict_fault_pilot"]
        bound(pilot["raw_archive"]["path"], pilot["raw_archive"]["sha256"])
        bound(stability["aborted_full_attempt"]["raw_archive"]["path"],
              stability["aborted_full_attempt"]["raw_archive"]["sha256"])
        pilot_audit = _json(bound(pilot["offline_audit"], pilot["offline_audit_sha256"]))
        if (short.get("healthy_seed_valid") is not True or
                short.get("fault_trials_completed") != pilot["fault_trials_completed"] or
                short.get("strict_injected_trials") != pilot["strict_injected_trials"] or
                short.get("strict_target_trials") != pilot["strict_target_trials"] != 0 or
                short.get("exact_exception_trials") != pilot["exact_exception_trials"] or
                pilot_audit is None or pilot_audit.get("report_gate_passed") is not True or
                pilot_audit.get("campaign_result_sha256") !=
                next(row["evidence_sha256"] for row in rows
                     if row["name"] == "short_campaign_healthy") or
                invalid.get("status") != "healthy_seed_invalid" or
                invalid.get("fault_trials_completed") != 0 or
                stability["aborted_full_attempt"]["driver_exit_code"] != 2):
            raise ValueError("pilot or invalid full seed differs")
        for name, value in (("short_campaign_healthy", short),
                            ("full_attempt_healthy", invalid)):
            config = _json(root / ("connectpath-short/config.json" if name.startswith("short")
                                   else "full-attempt-invalid-seed/config.json"))
            if (config is None or config.get("expected_target_class_sha256") != loaded_class or
                    config.get("source_overlay_receipt_sha256") !=
                    stability["source_overlay_receipt_sha256"] or
                    config["mapping"]["test_source_sha256"] != stability["test_source_sha256"] or
                    config["runtime_artifacts"][0]["sha256"] != stability["agent_jar_sha256"]):
                raise ValueError("campaign source or agent pin differs")
        return "no_suitable_cluster_test"
    except (OSError, KeyError, TypeError, ValueError, tarfile.TarError, StopIteration):
        return "invalid_source_gap"


def _source_gap(results: Path, case_id: str,
                calibration: dict[str, Any] | None) -> str | None:
    """Accept a no-workload finding only when its versioned evidence matches."""
    receipt_path = results / "source_gaps" / case_id / "receipt.json"
    receipt = _json(receipt_path)
    if receipt is None:
        return None
    if receipt.get("kind") == "unstable_existing_workload_v1":
        return _unstable_existing_workload_gap(results, case_id, receipt)
    if receipt.get("kind") == "source_review_no_suitable_test_v1":
        return _source_only_gap(results, case_id, receipt)
    if calibration is None:
        return None
    project_root = results.resolve().parent.parent
    revision_root = (project_root / "Mallory" / "cases" / "revisions").resolve()
    review_name = receipt.get("review_path")
    if not isinstance(review_name, str) or Path(review_name).is_absolute():
        return "invalid_source_gap"
    review_path = (project_root / review_name).resolve()
    healthy_path = Path(calibration["path"])
    audit_path = healthy_path.with_name("offline-causal-audit.json")
    if (not review_path.is_relative_to(revision_root)
            or not review_path.is_file() or not healthy_path.is_file()
            or not audit_path.is_file()):
        return "invalid_source_gap"
    review = _json(review_path)
    healthy = _json(healthy_path)
    audit = _json(audit_path)
    if review is None or healthy is None or audit is None:
        return "invalid_source_gap"
    review_case = next((entry for entry in review.get("cases", [])
                        if isinstance(entry, dict) and entry.get("case_id") == case_id), None)
    healthy_hash = hashlib.sha256(healthy_path.read_bytes()).hexdigest()
    audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    valid = (
        receipt.get("schema_version") == 1
        and receipt.get("case_id") == case_id
        and receipt.get("status") == "no_suitable_cluster_test"
        and receipt.get("review_sha256") == hashlib.sha256(review_path.read_bytes()).hexdigest()
        and receipt.get("healthy_result_sha256") == healthy_hash
        and receipt.get("audit_sha256") == audit_hash
        and review.get("status") == "no_suitable_existing_cluster_test_identified"
        and review_case is not None
        and review_case.get("current_healthy_result_sha256") == healthy_hash
        and review_case.get("current_offline_audit_sha256") == audit_hash
        and healthy.get("case_id") == case_id
        and healthy.get("status") == "calibration_complete"
        and healthy.get("healthy_seed_valid") is True
        and healthy.get("fault_trials_completed") == 0
        and audit.get("campaign_result_sha256") == healthy_hash
        and audit.get("healthy_observed_path_doors") == 0
        and audit.get("report_gate_passed") is False
    )
    return "no_suitable_cluster_test" if valid else "invalid_source_gap"


def _hbase19_20_existing_junit_review(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Bind the observed exact healthy guards without rewriting the older RPC review."""
    if case_id not in {"HBASE-19", "HBASE-20"}:
        return None, None
    root = results.resolve().parent.parent
    receipt_path = results / "quality_reviews/hbase19_20_existing_junit" / f"{case_id}.json"
    receipt = _json(receipt_path)
    if receipt is None:
        return None, None
    evidence = {
        "legacy_source_gap": results / "source_gaps" / case_id / "receipt.json",
        "source_review": root / "Mallory/cases/revisions/HBASE-19-20-remote-modify-gap-v1.json",
        "calibration_receipt": results / "calibration_v8" / case_id / "calibration-receipt.json",
        "healthy_result": results / "calibration_v8" / case_id / "result.json",
        "healthy_audit": results / "calibration_v8" / case_id / "offline-causal-audit.json",
        "trial_result": results / "calibration_v8" / case_id / "trials/r0000/result.json",
        "junit_receipt": results / "calibration_v8" / case_id / "trials/r0000/junit-receipt.json",
    }
    try:
        if (receipt.get("schema_version") != 1 or
                receipt.get("kind") != "existing_cluster_junit_exact_guard_review" or
                receipt.get("case_id") != case_id or
                receipt.get("status") != "healthy_exact_guard_observed" or
                receipt.get("legacy_interpretation") != "no_remote_modify_rpc_selector_identified" or
                receipt.get("eligible_doors_before_target") != 46 or
                receipt.get("observed_path_doors") != 0 or
                receipt.get("fault_trials_completed") != 0):
            raise ValueError("review metadata mismatch")
        for name, path in evidence.items():
            if receipt["evidence_sha256"][name] != hashlib.sha256(path.read_bytes()).hexdigest():
                raise ValueError(f"{name} SHA mismatch")
        legacy = _json(evidence["legacy_source_gap"])
        review = _json(evidence["source_review"])
        calibration_receipt = _json(evidence["calibration_receipt"])
        healthy = _json(evidence["healthy_result"])
        audit = _json(evidence["healthy_audit"])
        trial = _json(evidence["trial_result"])
        junit = _json(evidence["junit_receipt"])
        review_case = next(entry for entry in review["cases"] if entry["case_id"] == case_id)
        feedback = trial["feedback"]
        if (legacy["status"] != "no_suitable_cluster_test" or
                review_case["existing_remote_selector"] is not None or
                review_case["current_validated_selector"] != healthy["cluster_test"] or
                calibration_receipt["result_sha256"] != receipt["evidence_sha256"]["healthy_result"] or
                calibration_receipt["audit_sha256"] != receipt["evidence_sha256"]["healthy_audit"] or
                healthy["case_id"] != case_id or
                healthy["status"] != "calibration_complete" or
                healthy["healthy_seed_valid"] is not True or
                healthy["fault_trials_completed"] != 0 or
                healthy["target_node_named"] is not True or
                audit["campaign_result_sha256"] != receipt["evidence_sha256"]["healthy_result"] or
                audit["healthy_observed_path_doors"] != 0 or
                audit["report_gate_passed"] is not False or
                feedback["target_reached"] is not True or
                feedback["target_threw"] is not False or
                feedback["target_identity_complete"] is not True or
                feedback["eligible_doors_before_target"] != 46 or
                trial["junit_validation"]["status"] != "passed" or
                junit["status"] != "passed"):
            raise ValueError("healthy exact-guard evidence mismatch")
    except (OSError, KeyError, TypeError, ValueError, StopIteration):
        return "invalid_existing_junit_review", str(receipt_path)
    return "healthy_exact_guard_observed", str(receipt_path)


def _fault_model_target_lost(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Recognize a bounded effective fault that bypasses its exact target."""
    candidates = sorted((results / "admissions").glob(
        f"{case_id}-*-fault-model-target-lost.json"))
    if not candidates:
        return None, None
    if len(candidates) != 1:
        return "invalid_fault_model_receipt", str(results / "admissions")
    path = candidates[0]
    receipt = _json(path)
    if receipt is None:
        return "invalid_fault_model_receipt", str(path)
    digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
    project_root = results.resolve().parent.parent

    def bound(relative: Any, expected: Any) -> Path | None:
        if (not isinstance(relative, str) or not relative.startswith("data/mallory/")
                or not isinstance(expected, str) or len(expected) != 64):
            return None
        candidate = (project_root / relative).resolve()
        if (not candidate.is_relative_to(results.resolve()) or not candidate.is_file()
                or digest(candidate) != expected):
            return None
        return candidate

    healthy, pilot = receipt.get("healthy"), receipt.get("pilot")
    if not isinstance(healthy, dict) or not isinstance(pilot, dict):
        return "invalid_fault_model_receipt", str(path)
    healthy_root = results / "calibration_fa5f_lane2" / case_id
    pilot_root = results / "pilot_fa5f_lane2" / case_id
    healthy_config = bound(healthy.get("config"), healthy.get("config_sha256"))
    pilot_config = bound(pilot.get("config"), pilot.get("config_sha256"))
    healthy_result_path = healthy_root / "result.json"
    healthy_audit_path = healthy_root / "offline-causal-audit.json"
    pilot_result_path = pilot_root / "result.json"
    pilot_audit_path = pilot_root / "offline-causal-audit.json"
    fault_result_path = pilot_root / "trials/r0001/result.json"
    files = ((healthy_result_path, healthy.get("result_sha256")),
             (healthy_audit_path, healthy.get("audit_sha256")),
             (pilot_result_path, pilot.get("result_sha256")),
             (pilot_audit_path, pilot.get("audit_sha256")),
             (fault_result_path, pilot.get("fault_trial_result_sha256")))
    if (healthy_config is None or pilot_config is None or
            any(not file.is_file() or digest(file) != expected for file, expected in files)):
        return "invalid_fault_model_receipt", str(path)
    healthy_result = _json(healthy_result_path)
    healthy_audit = _json(healthy_audit_path)
    pilot_result = _json(pilot_result_path)
    pilot_audit = _json(pilot_audit_path)
    trial = _json(fault_result_path)
    if any(item is None for item in (
            healthy_result, healthy_audit, pilot_result, pilot_audit, trial)):
        return "invalid_fault_model_receipt", str(path)
    evidence = trial.get("events_evidence", {})
    gzip_name = evidence.get("gzip_path")
    if not isinstance(gzip_name, str) or Path(gzip_name).name != gzip_name:
        return "invalid_fault_model_receipt", str(path)
    trace = fault_result_path.parent / gzip_name
    if (not trace.is_file() or digest(trace) != evidence.get("gzip_sha256") or
            trace.stat().st_size != evidence.get("gzip_bytes") or
            evidence.get("raw_sha256") != pilot.get("fault_trace_sha256")):
        return "invalid_fault_model_receipt", str(path)
    fault = pilot.get("fault_event", {})
    raw = hashlib.sha256()
    applied = None
    later_target = False
    try:
        with gzip.open(trace, "rb") as stream:
            for line in stream:
                raw.update(line)
                event = json.loads(line)
                if event.get("id") == fault.get("id"):
                    applied = event
                if (event.get("type") == "TARGET_CHECK" and
                        event.get("site") == receipt.get("target", {}).get("check_site") and
                        isinstance(event.get("seq"), int) and
                        event["seq"] > fault.get("seq", -1)):
                    later_target = True
    except (OSError, EOFError, ValueError, TypeError):
        return "invalid_fault_model_receipt", str(path)
    valid = (
        receipt.get("schema_version") == 1
        and receipt.get("case_id") == case_id
        and receipt.get("status") == "fault_model_target_lost"
        and healthy_result.get("case_id") == case_id
        and healthy_result.get("status") == "calibration_complete"
        and healthy_result.get("healthy_seed_valid") is True
        and healthy_audit.get("report_gate_passed") is True
        and healthy_audit.get("healthy_local_timeline_doors", 0) > 0
        and pilot_result.get("case_id") == case_id
        and pilot_result.get("fault_trials_completed") == 1
        and pilot_result.get("strict_injected_trials") == 1
        and pilot_result.get("strict_target_trials") == 0
        and pilot_audit.get("report_gate_passed") is False
        and trial.get("trial_id") == 1
        and raw.hexdigest() == pilot.get("fault_trace_sha256")
        and isinstance(applied, dict)
        and applied.get("type") == "FAULT_APPLIED"
        and all(applied.get(key) == fault.get(key) for key in (
            "id", "seq", "site", "node", "epoch", "occurrence"))
        and not later_target
    )
    return ("fault_model_target_lost" if valid else "invalid_fault_model_receipt"), str(path)


def _zk04_zxid_influence_gap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Keep the current ZK04 fault-model gap separate from a completed campaign.

    This receipt establishes a healthy reconnect check and a bounded readBool
    pilot. It does not establish a fault that changes either zxid operand.
    """
    if case_id != "ZOOKEEPER-04":
        return None, None
    path = (results / "admissions" /
            "ZOOKEEPER-04-fa5f-write-reconnect-v1-fault-model-gap.json")
    if not path.is_file():
        return None, None
    invalid = ("invalid_fault_model_receipt", str(path))
    receipt = _json(path)
    if not isinstance(receipt, dict):
        return invalid

    healthy_dir = results / "calibration_fa5f_lane2" / "ZOOKEEPER-04-write-reconnect-v1"
    paths = {
        "healthy_result": healthy_dir / "result.json",
        "healthy_audit": healthy_dir / "offline-causal-audit.json",
        "healthy_attestation": results / "admissions" /
            "ZOOKEEPER-04-fa5f-write-reconnect-v1-healthy.json",
        "prior_pilot": results / "pilot_fa5f_lane2" / "ZOOKEEPER-04-readbool-v2" /
            "result.json",
        "config": healthy_dir / "config.json",
        "trial": healthy_dir / "trials/r0000/result.json",
    }
    hashes = {
        "healthy_result": "healthy_result_sha256",
        "healthy_audit": "healthy_offline_audit_sha256",
        "healthy_attestation": "healthy_attestation_sha256",
        "prior_pilot": "prior_readbool_pilot_result_sha256",
    }
    def digest(file: Path) -> str:
        return hashlib.sha256(file.read_bytes()).hexdigest()

    try:
        if any(not file.is_file() for file in paths.values()):
            return invalid
        if any(digest(paths[name]) != receipt.get(field)
               for name, field in hashes.items()):
            return invalid
        healthy = _json(paths["healthy_result"])
        audit = _json(paths["healthy_audit"])
        attestation = _json(paths["healthy_attestation"])
        pilot = _json(paths["prior_pilot"])
        config = _json(paths["config"])
        trial = _json(paths["trial"])
        if not all(isinstance(item, dict) for item in
                   (healthy, audit, attestation, pilot, config, trial)):
            return invalid
        selector = "org.apache.zookeeper.test.WatchEventWhenAutoResetTest#testNodeDataChanged"
        witness = attestation.get("post_restart_witness")
        fact = receipt.get("healthy_trace_fact")
        mapping = config.get("mapping")
        evidence = trial.get("events_evidence")
        if not all(isinstance(item, dict) for item in
                   (witness, fact, mapping, evidence)):
            return invalid
        overlay_path = Path(config.get("source_overlay_receipt", ""))
        if (not overlay_path.is_absolute() or not overlay_path.is_file() or
                digest(overlay_path) != config.get("source_overlay_receipt_sha256")):
            return invalid
        overlay = _json(overlay_path)
        if not isinstance(overlay, dict):
            return invalid
        base_root = Path(overlay.get("base_root", ""))
        if not base_root.is_absolute() or not base_root.is_dir():
            return invalid
        commit = subprocess.run(["git", "-C", str(base_root), "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True).stdout.strip()
        source_files = receipt.get("source_files")
        required_sources = {
            "zookeeper-server/src/test/java/org/apache/zookeeper/test/WatchEventWhenAutoResetTest.java",
            "zookeeper-server/src/main/java/org/apache/zookeeper/ClientCnxn.java",
            "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java",
            "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Learner.java",
            "zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java",
            "zookeeper-server/src/main/java/org/apache/zookeeper/server/persistence/FileTxnSnapLog.java",
        }
        if (not isinstance(source_files, dict) or
                not required_sources.issubset(source_files) or len(source_files) < 12):
            return invalid
        for relative, expected in source_files.items():
            if not isinstance(relative, str) or not isinstance(expected, str):
                return invalid
            source = (base_root / relative).resolve()
            if (not source.is_relative_to(base_root.resolve()) or
                    not source.is_file() or digest(source) != expected):
                return invalid
        target_source = "zookeeper-server/src/main/java/org/apache/zookeeper/server/ZooKeeperServer.java"
        target_class = "zookeeper-server/target/classes/org/apache/zookeeper/server/ZooKeeperServer.class"
        compiled = overlay.get("compiled_artifacts")
        trace = paths["trial"].parent / evidence.get("gzip_path", "")
        if (Path(evidence.get("gzip_path", "")).name != evidence.get("gzip_path") or
                not trace.is_file() or digest(trace) != evidence.get("gzip_sha256") or
                trace.stat().st_size != evidence.get("gzip_bytes") or
                not isinstance(compiled, list)):
            return invalid
        raw = hashlib.sha256()
        door = target = None
        with gzip.open(trace, "rb") as stream:
            for line in stream:
                raw.update(line)
                event = json.loads(line)
                if event.get("id") == witness.get("door_event_id"):
                    door = event
                if event.get("id") == witness.get("target_check_event_id"):
                    target = event
        valid = (
            receipt.get("schema_version") == 1
            and receipt.get("case_id") == case_id
            and receipt.get("status") ==
                "no_target_preserving_zxid_changing_io_fault_demonstrated"
            and receipt.get("full_campaign_admission") is False
            and selector.split(".")[-1] in receipt.get("scope", "")
            and "current IOException-at-I/O fault model" in receipt.get("scope", "")
            and isinstance(receipt.get("source_findings"), list)
            and len(receipt["source_findings"]) >= 7
            and healthy.get("case_id") == case_id
            and healthy.get("cluster_test") == selector
            and healthy.get("status") == "calibration_complete"
            and healthy.get("healthy_seed_valid") is True
            and healthy.get("fault_trials_completed") == 0
            and audit.get("case_id") == case_id
            and audit.get("campaign_result_sha256") == receipt["healthy_result_sha256"]
            and audit.get("report_gate_passed") is True
            and audit.get("healthy_observed_path_doors") == 0
            and audit.get("healthy_local_timeline_doors", 0) > 0
            and attestation.get("case_id") == case_id
            and attestation.get("selected_junit") == selector
            and attestation.get("result_sha256") == receipt["healthy_result_sha256"]
            and attestation.get("offline_audit_sha256") ==
                receipt["healthy_offline_audit_sha256"]
            and attestation.get("config_sha256") == digest(paths["config"])
            and config.get("case_id") == case_id
            and config.get("cluster_test") == selector
            and mapping.get("target_source_sha256") ==
                receipt.get("patched_target_source_sha256") ==
                attestation.get("target_source_sha256") ==
                overlay.get("modified_files", {}).get(target_source)
            and mapping.get("compiled_class_sha256") ==
                receipt.get("loaded_target_class_sha256") ==
                attestation.get("loaded_target_class_sha256")
            and any(isinstance(item, dict) and
                    item.get("path", "").endswith(target_class) and
                    item.get("sha256") == receipt["loaded_target_class_sha256"]
                    for item in compiled)
            and commit == overlay.get("base_commit") ==
                "9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae"
            and attestation.get("test_source_sha256") ==
                source_files["zookeeper-server/src/test/java/org/apache/zookeeper/test/WatchEventWhenAutoResetTest.java"]
            and pilot.get("case_id") == case_id
            and pilot.get("status") in TERMINAL
            and pilot.get("healthy_seed_valid") is True
            and pilot.get("cluster_test") ==
                "org.apache.zookeeper.server.ConnectionMetricsTest#testRevalidateCount"
            and pilot.get("fault_trials_completed") == 2
            and pilot.get("strict_injected_trials") == 2
            and pilot.get("strict_target_trials") == 2
            and pilot.get("exact_exception_trials") == 0
            and fact.get("post_restart_node") == witness.get("node") == "zk1"
            and fact.get("post_restart_epoch") == witness.get("epoch") == 1
            and fact.get("door_event_id") == witness.get("door_event_id")
            and fact.get("target_check_event_id") == witness.get("target_check_event_id")
            and fact.get("evidence_type") == witness.get("evidence_type") ==
                "observed_local_timeline"
            and fact.get("observed_graph_path_doors") == 0
            and isinstance(door, dict) and isinstance(target, dict)
            and door.get("type") == "DOOR_OBSERVED"
            and target.get("type") == "TARGET_CHECK"
            and target.get("site") in config.get("target", {}).get("check_sites", [])
            and all(door.get(key) == target.get(key) == witness.get(key)
                    for key in ("node", "epoch", "thread_id", "occurrence"))
            and door.get("seq") == witness.get("door_seq")
            and target.get("seq") == witness.get("target_check_seq")
            and door["seq"] < target["seq"]
            and raw.hexdigest() == evidence.get("raw_sha256") ==
                attestation.get("trace_raw_sha256")
            and digest(trace) == attestation.get("trace_gzip_sha256")
        )
        return ("fault_model_zxid_influence_unproven" if valid else
                "invalid_fault_model_receipt"), str(path)
    except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError):
        return invalid


def _fault_model_no_target_path(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Record a bounded pilot whose retained checks have no observed fault path."""
    path = results / "quality_reviews" / "solr37_v29p_gap" / f"{case_id}.json"
    if not path.is_file():
        return None, None
    receipt = _json(path)
    if not isinstance(receipt, dict):
        return "invalid_fault_model_receipt", str(path)
    project_root = results.resolve().parent.parent
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict):
        return "invalid_fault_model_receipt", str(path)
    files: dict[str, Path] = {}
    for name in ("healthy_result", "healthy_audit", "pilot_result", "pilot_audit",
                 "pilot_sync_receipt", "postfault_path_sidecar",
                 "source_request_order_review"):
        entry = artifacts.get(name)
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            return "invalid_fault_model_receipt", str(path)
        candidate = (project_root / entry["path"]).resolve()
        if (not candidate.is_relative_to(project_root) or not candidate.is_file()
                or candidate.stat().st_size != entry.get("bytes")
                or hashlib.sha256(candidate.read_bytes()).hexdigest() != entry.get("sha256")):
            return "invalid_fault_model_receipt", str(path)
        files[name] = candidate
    healthy = _json(files["healthy_result"])
    healthy_audit = _json(files["healthy_audit"])
    pilot = _json(files["pilot_result"])
    pilot_audit = _json(files["pilot_audit"])
    sidecar = _json(files["postfault_path_sidecar"])
    if not all(isinstance(item, dict) for item in (
            healthy, healthy_audit, pilot, pilot_audit, sidecar)):
        return "invalid_fault_model_receipt", str(path)
    trial_rows = sidecar.get("trials")
    valid = (
        receipt.get("schema_version") == 1
        and receipt.get("case_id") == case_id == "SOLR-37"
        and receipt.get("classification") == "fault_model_no_target_path"
        and receipt.get("full_campaign_promoted") is False
        and receipt.get("healthy_junit_pass") is True
        and receipt.get("healthy_named_exact_target") is True
        and receipt.get("time_respecting_observed_postfault_paths") == 0
        and healthy.get("case_id") == case_id
        and healthy.get("status") == "calibration_complete"
        and healthy_audit.get("report_gate_passed") is True
        and pilot.get("case_id") == case_id
        and pilot.get("status") in TERMINAL
        and pilot_audit.get("report_gate_passed") is True
        and pilot.get("fault_trials_completed") == receipt.get("pilot_fault_trials")
        and pilot.get("strict_injected_trials") == receipt.get("pilot_strict_applied")
        and pilot.get("strict_target_trials") == receipt.get("pilot_target_retained")
        and pilot.get("exact_exception_trials") == receipt.get("exact_target_exception_trials")
        and sidecar.get("case_id") == case_id
        and sidecar.get("campaign_result_sha256") == artifacts["pilot_result"]["sha256"]
        and sidecar.get("offline_causal_audit_sha256") == artifacts["pilot_audit"]["sha256"]
        and sidecar.get("fault_trials_completed") == pilot.get("fault_trials_completed")
        and sidecar.get("trials_with_time_respecting_observed_path") == 0
        and isinstance(trial_rows, list)
        and len(trial_rows) == pilot.get("fault_trials_completed")
        and receipt.get("source_file_sha256_as_attested_in_review") in
            files["source_request_order_review"].read_text()
    )
    if not valid:
        return "invalid_fault_model_receipt", str(path)
    trial_root = files["pilot_result"].parent / "trials"
    seen_ids: set[int] = set()
    for row in trial_rows:
        trial_id = row.get("trial_id") if isinstance(row, dict) else None
        if (not isinstance(trial_id, int) or isinstance(trial_id, bool)
                or trial_id in seen_ids):
            return "invalid_fault_model_receipt", str(path)
        seen_ids.add(trial_id)
        trial_dir = trial_root / f"r{trial_id:04d}"
        trial_result = trial_dir / "result.json"
        trace = trial_dir / "events.jsonl.gz"
        if (not trial_result.is_file() or not trace.is_file()
                or hashlib.sha256(trial_result.read_bytes()).hexdigest() !=
                row.get("trial_result_sha256")
                or hashlib.sha256(trace.read_bytes()).hexdigest() !=
                row.get("trace_gzip_sha256")):
            return "invalid_fault_model_receipt", str(path)
        evidence = (_json(trial_result) or {}).get("events_evidence", {})
        faults = row.get("applied_faults")
        if (not isinstance(evidence, dict) or not isinstance(faults, list)
                or not all(isinstance(fault, dict) for fault in faults)):
            return "invalid_fault_model_receipt", str(path)
        raw = hashlib.sha256()
        raw_bytes = 0
        try:
            with gzip.open(trace, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    raw.update(chunk)
                    raw_bytes += len(chunk)
        except (OSError, EOFError):
            return "invalid_fault_model_receipt", str(path)
        if (raw.hexdigest() != row.get("trace_raw_sha256")
                or raw_bytes != row.get("trace_raw_bytes")
                or evidence.get("raw_sha256") != row.get("trace_raw_sha256")
                or evidence.get("raw_bytes") != row.get("trace_raw_bytes")
                or evidence.get("gzip_sha256") != row.get("trace_gzip_sha256")
                or any(fault.get("time_respecting_observed_path") is not None
                       for fault in faults)):
            return "invalid_fault_model_receipt", str(path)
    if seen_ids != set(range(1, pilot["fault_trials_completed"] + 1)):
        return "invalid_fault_model_receipt", str(path)
    return "fault_model_no_target_path", str(path)


def _solr22_dynamic_bounded_gap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Attach the later bounded pilot without replacing SOLR22's terminal row."""
    if case_id != "SOLR-22":
        return None, None
    root = results / "quality_reviews/solr22_v33g2p_gap"
    path = root / "SOLR-22.json"
    if not path.is_file():
        return None, None
    invalid = ("invalid_bounded_fault_model_gap", str(path))
    try:
        baseline = results.resolve().parent.parent
        digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
        index = _json(root / "index.json")
        receipt = _json(path)
        replay = results / "replays/SOLR-22-v33g2p-lane4"
        strict_path = results / "audit_sidecars/SOLR-22-v33g2p-dynamic-pilot.json"
        verifier = baseline / "Mallory/adapters/solr/releases/v33/verify_solr22_dynamic_gap.py"
        release = baseline / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
        manifest = release / "manifest.json"
        files = (path, strict_path, verifier, manifest,
                 replay / "result.json", replay / "offline-causal-audit.json",
                 replay / "sync-receipt.json", replay / "config.json")
        if (not isinstance(index, dict) or not isinstance(receipt, dict) or
                any(not file.is_file() for file in files)):
            return invalid
        strict = _json(strict_path)
        result = _json(replay / "result.json")
        audit = _json(replay / "offline-causal-audit.json")
        if not all(isinstance(item, dict) for item in (strict, result, audit)):
            return invalid
        valid = (
            index.get("schema_version") == 1
            and index.get("case_id") == receipt.get("case_id") == "SOLR-22"
            and index.get("classification") == receipt.get("classification") ==
                "bounded_no_current_same_request_injectable_door"
            and index.get("receipt_path") == str(path.resolve().relative_to(baseline))
            and index.get("receipt_sha256") == digest(path)
            and index.get("verifier_path") == str(verifier.relative_to(baseline))
            and index.get("verifier_sha256") == digest(verifier)
            and index.get("core_manifest_path") == str(manifest.relative_to(baseline))
            and index.get("core_manifest_sha256") == digest(manifest)
            and receipt.get("full_campaign_promoted") is False
            and receipt.get("healthy_bound_actor_door_to_target_path_count") == 0
            and receipt.get("result_sha256") == digest(replay / "result.json")
            and receipt.get("offline_audit_sha256") ==
                digest(replay / "offline-causal-audit.json")
            and receipt.get("sync_receipt_sha256") ==
                digest(replay / "sync-receipt.json")
            and receipt.get("strict_sidecar_sha256") == digest(strict_path)
            and strict.get("classification") == "postfault_causal_path_unverified"
            and strict.get("qualified_root_free_rpc_trial_ids") == []
            and strict.get("strict_injected_trials") == 7
            and strict.get("strict_target_trials") == 3
            and result.get("status") in TERMINAL
            and result.get("fault_trials_completed") == 8
            and audit.get("report_gate_passed") is True
            and len(strict.get("trials", [])) == 8
        )
        if not valid:
            return invalid
        healthy_path = replay / "trials/r0000"
        if (digest(healthy_path / "result.json") !=
                strict.get("healthy_trial_result_sha256") or
                digest(healthy_path / "events.jsonl.gz") !=
                strict.get("healthy_trace_gzip_sha256")):
            return invalid
        for number, witness in enumerate(strict["trials"], 1):
            trial_dir = replay / f"trials/r{number:04d}"
            trial_path = trial_dir / "result.json"
            trace_path = trial_dir / "events.jsonl.gz"
            if (witness.get("trial_id") != number or
                    not trial_path.is_file() or not trace_path.is_file() or
                    digest(trial_path) != witness.get("trial_result_sha256") or
                    digest(trace_path) != witness.get("events_gzip_sha256")):
                return invalid
            raw = gzip.decompress(trace_path.read_bytes())
            trial = _json(trial_path)
            if (not isinstance(trial, dict) or
                    len(raw) != witness.get("events_raw_bytes") or
                    hashlib.sha256(raw).hexdigest() !=
                        witness.get("events_raw_sha256") or
                    trial.get("events_evidence", {}).get("raw_sha256") !=
                        witness.get("events_raw_sha256")):
                return invalid
        for filename, source in receipt.get("source_review", {}).items():
            file = Path(filename)
            if (not file.is_absolute() or not file.is_file() or
                    digest(file) != source.get("sha256")):
                return invalid
        with tempfile.TemporaryDirectory() as temporary:
            generated = Path(temporary) / "review.json"
            check = subprocess.run(
                ["python3", str(verifier), "--campaign", str(replay),
                 "--strict-sidecar", str(strict_path), "--out", str(generated)],
                cwd=baseline, env=dict(os.environ, PYTHONPATH=f"{release}:{baseline}"),
                capture_output=True, text=True, timeout=60)
            if check.returncode != 0 or _json(generated) != receipt:
                return invalid
        return "bounded_fault_model_gap_verified", str(path)
    except (OSError, ValueError, TypeError, KeyError, EOFError, subprocess.TimeoutExpired):
        return invalid


def _zk10_packet_fault_gap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Bind the observer source gap to its named, packet-door healthy trace."""
    if case_id != "ZOOKEEPER-10":
        return None, None
    path = results / "admissions/ZOOKEEPER-10-fa5f-observer-v1-fault-model-gap.json"
    if not path.is_file():
        return None, None
    invalid = ("invalid_fault_model_receipt", str(path))
    try:
        baseline = results.resolve().parent.parent
        digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
        receipt = _json(path)
        healthy_path = results / "admissions/ZOOKEEPER-10-fa5f-observer-v1-healthy.json"
        campaign = results / "calibration_fa5f_node0/ZOOKEEPER-10-observer-v1"
        result_path = campaign / "result.json"
        audit_path = campaign / "offline-causal-audit.json"
        trial_path = campaign / "trials/r0000/result.json"
        trace_path = campaign / "trials/r0000/events.jsonl.gz"
        config_path = baseline / "Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-fa5f-observer-healthy.json"
        site_path = baseline / "Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-fa5f-observer-healthy.sites.json"
        review_path = baseline / "Mallory/adapters/zookeeper/cases/ZOOKEEPER-10-fa5f-observer-source-review.json"
        files = (healthy_path, result_path, audit_path, trial_path, trace_path,
                 config_path, site_path, review_path)
        if not isinstance(receipt, dict) or any(not file.is_file() for file in files):
            return invalid
        healthy = _json(healthy_path)
        result = _json(result_path)
        audit = _json(audit_path)
        trial = _json(trial_path)
        if not all(isinstance(item, dict) for item in
                   (healthy, result, audit, trial)):
            return invalid
        artifacts = healthy.get("artifact_sha256")
        if not isinstance(artifacts, dict):
            return invalid
        mapped = {"result": result_path, "offline_audit": audit_path,
                  "trial_result": trial_path, "trial_events_gzip": trace_path,
                  "config": config_path, "site_file": site_path,
                  "source_review": review_path}
        if any(digest(file) != artifacts.get(name) for name, file in mapped.items()):
            return invalid
        packed = trace_path.read_bytes()
        raw = gzip.decompress(packed)
        if (hashlib.sha256(raw).hexdigest() != artifacts.get("trial_events_raw") or
                trial.get("events_evidence", {}).get("raw_sha256") !=
                    artifacts.get("trial_events_raw")):
            return invalid
        source_root = Path("/users/ZhenyuLi/.graphchecker-sources/zookeeper-3.8.7")
        source_dir = source_root / "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum"
        sources = receipt.get("pristine_source_sha256")
        if not isinstance(sources, dict) or len(sources) != 4:
            return invalid
        for name, expected in sources.items():
            file = (source_dir / name).resolve()
            if (not file.is_relative_to(source_dir.resolve()) or
                    not file.is_file() or digest(file) != expected or
                    healthy.get("pristine_source_sha256", {}).get(name) != expected):
                return invalid
        events = tuple(json.loads(line) for line in raw.splitlines() if line.strip())
        target = healthy.get("target", {})
        checks = [event for event in events if event.get("type") == "TARGET_CHECK"
                  and event.get("site") == target.get("check_site")]
        throws = [event for event in events if event.get("type") == "TARGET_THROW"
                  and event.get("site") == target.get("throw_site")]
        doors = [door for door in trial.get("feedback", {}).get("doors", [])
                 if door.get("in_closure")]
        allowed = {"zookeeper.quorum.archive.readRecord",
                   "zookeeper.quorum.archive.writeRecord"}
        valid = (
            receipt.get("schema_version") == 1
            and receipt.get("case_id") == healthy.get("case_id") ==
                result.get("case_id") == "ZOOKEEPER-10"
            and receipt.get("status") ==
                "no_target_retaining_packet_io_fault_demonstrated"
            and receipt.get("full_campaign_admission") is False
            and receipt.get("pilot_fault_trials") == 0
            and receipt.get("healthy_receipt_sha256") == digest(healthy_path)
            and receipt.get("healthy_result_sha256") == digest(result_path)
            and receipt.get("healthy_offline_audit_sha256") == digest(audit_path)
            and receipt.get("healthy_trace_raw_sha256") ==
                hashlib.sha256(raw).hexdigest()
            and result.get("status") == "calibration_complete"
            and result.get("healthy_seed_valid") is True
            and result.get("healthy_junit_validation", {}).get("status") == "passed"
            and result.get("healthy_junit_validation", {}).get("tests") == 2
            and audit.get("report_gate_passed") is True
            and audit.get("healthy_observed_path_doors") == len(doors) == 13
            and target.get("node") == "zk1"
            and len(checks) == target.get("check_count") == 7
            and all(event.get("node") == "zk1" for event in checks)
            and not throws
            and {door.get("site") for door in doors} == allowed
            and len(receipt.get("source_findings", [])) >= 4
        )
        return ("fault_model_packet_io_no_target_retention" if valid else
                "invalid_fault_model_receipt"), str(path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, EOFError):
        return invalid


def _hdfs48_target_retention_gap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Verify that ten effective pretarget faults lost the named NN target."""
    if case_id != "HDFS-48":
        return None, None
    path = results / "admissions/HDFS-48-v14-fault-model-no-target-retaining-pretarget-door.json"
    if not path.is_file():
        return None, None
    invalid = ("invalid_fault_model_receipt", str(path))
    try:
        baseline = results.resolve().parent.parent
        digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
        receipt = _json(path)
        if not isinstance(receipt, dict):
            return invalid
        review_file = (baseline / receipt["review_path"]).resolve()
        if (not review_file.is_relative_to(baseline) or not review_file.is_file() or
                digest(review_file) != receipt.get("review_sha256")):
            return invalid
        review = _json(review_file)
        if not isinstance(review, dict):
            return invalid
        def bound(record: dict[str, Any]) -> Path:
            file = (baseline / record["path"]).resolve()
            if (not file.is_relative_to(baseline) or not file.is_file() or
                    file.stat().st_size != record["bytes"] or
                    digest(file) != record["sha256"]):
                raise ValueError("HDFS-48 evidence hash or size mismatch")
            return file
        healthy_files = review["healthy_evidence"]["files"]
        pilot_files = review["pilot_evidence"]["files"]
        for record in (*healthy_files.values(), *pilot_files.values(),
                       review["pilot_evidence"]["decision"]):
            bound(record)
        healthy = _json(bound(healthy_files["result"]))
        pilot = _json(bound(pilot_files["result"]))
        config = _json(bound(pilot_files["config"]))
        healthy_audit = _json(bound(healthy_files["audit"]))
        if not all(isinstance(item, dict) for item in
                   (healthy, pilot, config, healthy_audit)):
            return invalid
        source_root = Path(review["source_root"]).resolve()
        if not source_root.is_dir():
            # The clean smoke worktree was reclaimed for disk space. The
            # immutable upstream snapshot has the same pinned file bytes.
            source_root = Path("/users/ZhenyuLi/.graphchecker-sources/hadoop-3.4.3").resolve()
        for record in review["source_files"]:
            file = (source_root / record["path"]).resolve()
            if (not file.is_relative_to(source_root) or not file.is_file() or
                    digest(file) != record["sha256"]):
                return invalid
        checks = set(config.get("target", {}).get("check_sites", []))
        trials = review["pilot_evidence"]["trial_evidence"]
        valid = (
            receipt.get("schema_version") == 1
            and receipt.get("kind") == "fault_model_no_target_retaining_pretarget_door_v1"
            and receipt.get("case_id") == review.get("case_id") == "HDFS-48"
            and receipt.get("status") == review.get("classification") ==
                "fault_model_no_target_retaining_pretarget_door"
            and receipt.get("full_campaign_promoted") is False
            and receipt.get("new_bug") is None
            and receipt.get("healthy_result_sha256") == digest(bound(healthy_files["result"]))
            and receipt.get("healthy_audit_sha256") == digest(bound(healthy_files["audit"]))
            and receipt.get("pilot_result_sha256") == digest(bound(pilot_files["result"]))
            and receipt.get("pilot_decision_sha256") ==
                digest(bound(review["pilot_evidence"]["decision"]))
            and healthy.get("case_id") == pilot.get("case_id") == "HDFS-48"
            and healthy.get("status") == "calibration_complete"
            and healthy.get("healthy_seed_valid") is True
            and healthy_audit.get("report_gate_passed") is True
            and healthy_audit.get("healthy_observed_path_doors") == 11
            and pilot.get("status") in TERMINAL
            and pilot.get("healthy_seed_valid") is True
            and pilot.get("fault_trials_completed") == 10
            and pilot.get("strict_injected_trials") == 10
            and pilot.get("strict_target_trials") == 0
            and pilot.get("exact_exception_trials") == 0
            and receipt.get("pilot_effective_injected_trials") == 10
            and receipt.get("pilot_postfault_named_target_trials") == 0
            and isinstance(trials, list) and len(trials) == 10
            and bool(checks)
        )
        if not valid:
            return invalid
        for index, evidence in enumerate(trials, 1):
            if (evidence.get("trial_id") != index or
                    evidence.get("effective") is not True or
                    evidence.get("postfault_named_target") is not False):
                return invalid
            trial = _json(bound(evidence["result"]))
            packed = bound(evidence["trace_gzip"]).read_bytes()
            raw = gzip.decompress(packed)
            if (not isinstance(trial, dict) or trial.get("trial_id") != index or
                    len(raw) != evidence.get("trace_raw_bytes") or
                    hashlib.sha256(raw).hexdigest() != evidence.get("trace_raw_sha256") or
                    trial.get("events_evidence", {}).get("raw_sha256") !=
                        evidence.get("trace_raw_sha256") or
                    trial.get("feedback", {}).get("status") != "target_lost"):
                return invalid
            events = tuple(json.loads(line) for line in raw.splitlines() if line.strip())
            faults = [event for event in events if event.get("type") == "FAULT_APPLIED"]
            if (len(faults) != 1 or faults[0].get("id") !=
                    evidence.get("fault_event_id") or faults[0].get("seq") !=
                    evidence.get("fault_applied_seq") or faults[0].get("node") !=
                    evidence.get("fault_node")):
                return invalid
            if any(event.get("type") == "TARGET_CHECK" and
                   event.get("site") in checks and event.get("node") ==
                   evidence["fault_node"] and event.get("seq", -1) >
                   faults[0].get("seq", 10**12) for event in events):
                return invalid
        return "fault_model_no_target_retaining_pretarget_door", str(path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, EOFError):
        return invalid


def _hbase37_source_fault_gap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Record a source-backed fault gap while named healthy binding is pending."""
    if case_id != "HBASE-37":
        return None, None
    path = results / "fault_model_gaps/HBASE-37/receipt.json"
    if not path.is_file():
        return None, None
    invalid = ("invalid_fault_model_receipt", str(path))
    try:
        receipt = _json(path)
        if not isinstance(receipt, dict):
            return invalid
        baseline = results.resolve().parent.parent
        digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
        for key, sha_key in (("review_path", "review_sha256"),
                             ("source_review_path", "source_review_sha256"),
                             ("typed_sites_path", "typed_sites_sha256")):
            file = (baseline / receipt[key]).resolve()
            if (not file.is_relative_to(baseline) or not file.is_file() or
                    digest(file) != receipt[sha_key]):
                return invalid
        source_root = Path("/users/ZhenyuLi/.graphchecker-sources/hbase-2.6.6")
        hashes = receipt.get("source_hashes")
        if not isinstance(hashes, dict) or len(hashes) != 4:
            return invalid
        for name, expected in hashes.items():
            file = (source_root / name).resolve()
            if (not file.is_relative_to(source_root.resolve()) or
                    not file.is_file() or digest(file) != expected):
                return invalid
        prior = receipt.get("prior_evidence")
        if not isinstance(prior, dict):
            return invalid
        result_file = (baseline / prior["result_path"]).resolve()
        archive_file = (baseline / prior["archive_path"]).resolve()
        if any(not file.is_relative_to(baseline) or not file.is_file()
               for file in (result_file, archive_file)):
            return invalid
        if (digest(result_file) != prior.get("result_sha256") or
                digest(archive_file) != prior.get("archive_sha256")):
            return invalid
        result = _json(result_file)
        review = _json(baseline / receipt["review_path"])
        sites = _json(baseline / receipt["typed_sites_path"])
        if not all(isinstance(item, dict) for item in (result, review, sites)):
            return invalid
        with tarfile.open(archive_file, "r:gz") as archive:
            packed = archive.extractfile(prior["trace_member"]).read()
            config = json.load(archive.extractfile("config.json"))
        raw = gzip.decompress(packed)
        checks = [event for line in raw.splitlines() if line.strip()
                  for event in (json.loads(line),)
                  if event.get("type") == "TARGET_CHECK" and
                  event.get("site") in config.get("target", {}).get("check_sites", [])]
        valid = (
            receipt.get("schema_version") == 1
            and receipt.get("kind") == "source_review_fault_model_gap_v1"
            and receipt.get("case_id") == result.get("case_id") == "HBASE-37"
            and receipt.get("status") == "source_review_fault_model_gap"
            and receipt.get("terminal") is False
            and prior.get("named_healthy_valid") is False
            and prior.get("exact_target_event_count") == len(checks) == 1
            and prior.get("target_nodes") == ["unknown"]
            and {event.get("node") for event in checks} == {"unknown"}
            and hashlib.sha256(packed).hexdigest() == prior.get("trace_gzip_sha256")
            and hashlib.sha256(raw).hexdigest() == prior.get("trace_raw_sha256")
            and review.get("case_id") == "HBASE-37"
            and any(target.get("clazz") ==
                    "org.apache.hadoop.hbase.zookeeper.MasterAddressTracker" and
                    target.get("method") == "getMasterInfoPort"
                    for target in sites.get("targets", []))
        )
        return ("source_review_fault_model_gap" if valid else
                "invalid_fault_model_receipt"), str(path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, tarfile.TarError):
        return invalid


def _solr_fault_discovery_bootstrap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Supersede an obsolete no-healthy-guard label with pinned cluster evidence."""
    if case_id not in {"SOLR-15", "SOLR-16", "SOLR-34"}:
        return None, None
    baseline = results.resolve().parent.parent
    index_path = results / "quality_reviews/solr_fault_discovered_target_v1/index.json"
    if not index_path.is_file():
        return None, None
    invalid = ("invalid_fault_discovery_bootstrap_review", str(index_path))
    try:
        index = _json(index_path)
        if (not isinstance(index, dict) or index.get("schema_version") != 1 or
                index.get("kind") != "fault_discovered_target_bootstrap_review" or
                index.get("classification") != "pending_fault_discovery_bootstrap" or
                index.get("completed_campaign_count_delta") != 0 or
                set(index.get("cases", {})) != {"SOLR-15", "SOLR-16", "SOLR-34"}):
            return invalid
        review_path = (baseline / index["review_path"]).resolve()
        if (not review_path.is_relative_to(baseline) or not review_path.is_file() or
                hashlib.sha256(review_path.read_bytes()).hexdigest() != index["review_sha256"]):
            return invalid
        for reviewed_case, evidence in index["cases"].items():
            calibration_path = results / "calibration" / reviewed_case / "result.json"
            archive_path = results / "evidence_archives/calibration" / f"{reviewed_case}.tar.gz"
            if (not calibration_path.is_file() or not archive_path.is_file() or
                    hashlib.sha256(calibration_path.read_bytes()).hexdigest() !=
                    evidence["calibration_result_sha256"] or
                    hashlib.sha256(archive_path.read_bytes()).hexdigest() !=
                    evidence["calibration_archive_sha256"]):
                return invalid
            calibration = _json(calibration_path)
            if (calibration.get("case_id") != reviewed_case or
                    calibration.get("cluster_test") != evidence["cluster_test"] or
                    calibration.get("calibration_only") is not True or
                    calibration.get("status") != "healthy_seed_invalid" or
                    calibration.get("fault_trials_completed") != 0):
                return invalid
        return "pending_fault_discovery_bootstrap", str(index_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return invalid


def _hbase34_cluster_stage(results: Path, case_id: str) -> tuple[str | None, str | None, str | None]:
    """Check the alternate passing token JUnit that reaches the selected guard."""
    if case_id != "HBASE-34":
        return None, None, None
    baseline = results.resolve().parent.parent
    package = baseline / "Mallory/adapters/hbase/pilot/hbase32-34-broad-review-v1"
    stage_path = package / "hbase34/stage-receipt.json"
    review_path = package / "review-receipt.json"
    if not stage_path.is_file():
        return None, None, None
    invalid = ("invalid_cluster_stage_receipt", str(stage_path), None)
    try:
        stage, review = _json(stage_path), _json(review_path)
        if (not isinstance(stage, dict) or not isinstance(review, dict) or
                stage.get("schema_version") != 1 or stage.get("case_id") != case_id or
                stage.get("status") != "staged_no_jvm" or
                stage.get("jvm_trials_started") != 0 or
                hashlib.sha256(review_path.read_bytes()).hexdigest() !=
                stage.get("review_receipt_sha256")):
            return invalid
        if any(not (package / "hbase34" / name).is_file() or
               hashlib.sha256((package / "hbase34" / name).read_bytes()).hexdigest() != digest
               for name, digest in stage["files"].items()):
            return invalid
        case_review = review["cases"][case_id]
        archive_path = baseline / case_review["archive"]
        if (case_review.get("classification") !=
                "prior_skip_contradicted_guard_reached_package_staged" or
                not archive_path.is_file() or
                hashlib.sha256(archive_path.read_bytes()).hexdigest() !=
                case_review["archive_sha256"]):
            return invalid
        healthy = _json(package / "hbase34/healthy.json")
        full = _json(package / "hbase34/full.json")
        selector = "org.apache.hadoop.hbase.security.token.TestTokenAuthentication#testTokenCreation"
        if (healthy.get("case_id") != case_id or full.get("case_id") != case_id or
                healthy.get("cluster_test") != selector or
                full.get("cluster_test") != selector or
                full.get("budget") != stage.get("full_budget") or
                selector.split(".")[-1] not in case_review["passing_existing_test"]):
            return invalid
        return "pending_seed", str(stage_path), selector
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return invalid


def _zk08_09_cluster_junit_review(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Attach the pinned source review without treating it as campaign evidence."""
    if case_id not in {"ZOOKEEPER-08", "ZOOKEEPER-09"}:
        return None, None
    path = (results.resolve().parent.parent / "Mallory/adapters/zookeeper/cases"
            / "ZOOKEEPER-08-09-cluster-junit-source-audit-v2.md")
    if not path.is_file():
        return None, None
    expected = "fcef7f81aec905cf4661214a28ea1f895fe5073ffa76551324b86c9cf331a96f"
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        return "invalid_cluster_junit_source_review", str(path)
    return "source_review_no_mapped_cluster_test", str(path)


def _hbase32_target_discovery_stage(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Recognize the pinned unrun bootstrap, which supersedes the old skip."""
    if case_id != "HBASE-32":
        return None, None
    baseline = results.resolve().parent.parent
    package = baseline / "Mallory/adapters/hbase/cases/HBASE-32/target-discovery-v1"
    manifest_path = package / "sha-manifest.json"
    if not manifest_path.is_file():
        return None, None
    invalid = ("invalid_target_discovery_stage", str(manifest_path))
    try:
        expected = "bf21b73c5ac9eea9dfea46c32570d6492691dfa6bd4df1686adfa8e8144e7151"
        if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != expected:
            return invalid
        manifest = _json(manifest_path)
        if not isinstance(manifest, dict) or manifest.get("case_id") != case_id:
            return invalid
        for name, digest in manifest["case_files"].items():
            file = (package / name).resolve()
            if (not file.is_relative_to(package.resolve()) or not file.is_file() or
                    hashlib.sha256(file.read_bytes()).hexdigest() != digest):
                return invalid
        for name, digest in {
            "preflight.py": "ed64d3d87822f0558ea5487c9af8a7cc12c601551a888339791a63f5379faa57",
            "run_campaign.py": "9a5ce7cfe14d44e8dbd18425a3c5452b569cf65a209e9599cc6dd8096844cfd3",
        }.items():
            if hashlib.sha256((package / name).read_bytes()).hexdigest() != digest:
                return invalid
        prior = results / "calibration_v19/HBASE-32/result.json"
        if hashlib.sha256(prior.read_bytes()).hexdigest() != manifest["prior_negative_sha256"]:
            return invalid
        healthy = _json(package / "config-healthy.json")
        full = _json(package / "config-full.json")
        if (healthy.get("case_id") != case_id or full.get("case_id") != case_id or
                healthy.get("calibration_only") is not True or
                full.get("calibration_only") is not False or
                full.get("budget", {}).get("trials") != 80):
            return invalid
        return "pending_fault_discovery_bootstrap", str(manifest_path)
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return invalid


def _hbase34_environment_repair(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Keep a real cluster JUnit pending while its MiniKdc setup is repaired."""
    if case_id != "HBASE-34":
        return None, None
    baseline = results.resolve().parent.parent
    path = (baseline / "Mallory/adapters/hbase/pilot"
            / "hbase34-37-independent-admission-v1/receipt.json")
    if not path.is_file():
        return None, None
    invalid = ("invalid_environment_repair_review", str(path))
    try:
        if hashlib.sha256(path.read_bytes()).hexdigest() != (
                "4cfd06853d4b7bbee4ff9faedbdee1fca14f1200649064db13ed6de9c49deda2"):
            return invalid
        review = _json(path)
        item = review[case_id]
        if (review.get("kind") != "independent_hbase34_37_source_and_static_admission" or
                item.get("classification") !=
                "true_LocalHBaseCluster_JUnit_exists_but_original_calibration_blocked_before_test" or
                item.get("selected_original_test") !=
                "org.apache.hadoop.hbase.security.token.TestGenerateDelegationToken#testOnlyToken"):
            return invalid
        source = Path(review["source_root"])
        for entry in review["source_files"].values():
            file = (source / entry["path"]).resolve()
            if (not file.is_relative_to(source.resolve()) or not file.is_file() or
                    hashlib.sha256(file.read_bytes()).hexdigest() != entry["sha256"]):
                return invalid
        prior = item["original_calibration"]
        for name, expected in ((prior["archive"], prior["archive_sha256"]),
                               (prior["result"], prior["result_sha256"])):
            file = (baseline / name).resolve()
            if (not file.is_relative_to(baseline) or not file.is_file() or
                    hashlib.sha256(file.read_bytes()).hexdigest() != expected):
                return invalid
        return "pending_environment_repair", str(path)
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return invalid


def _hbase23_28_source_audit(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Attach the immutable source finding without changing pending status."""
    expected = {
        "HBASE-23": "c7128fb2a477b19a2b88ddc55b1e1f78a45e310798dbb2ca41d425fa4833c4ce",
        "HBASE-28": "85eaa927600f03b9949a114179d75e807d533d97192103bff26235bd98a63d14",
    }
    if case_id not in expected:
        return None, None
    path = (results.resolve().parent.parent / "Mallory/adapters/hbase/pilot"
            / "original102-source-audit-v1" / f"{case_id}.source-audit.json")
    if not path.is_file():
        return None, None
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected[case_id]:
        return "invalid_source_audit_receipt", str(path)
    receipt = _json(path)
    if not isinstance(receipt, dict) or receipt.get("case_id") != case_id:
        return "invalid_source_audit_receipt", str(path)
    return "source_audit_verified_pending", str(path)


def _hdfs13_18_37_source_audit(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Check the superseding source review before relabeling adapted tests."""
    if case_id not in {"HDFS-13", "HDFS-18", "HDFS-37"}:
        return None, None
    baseline = results.resolve().parent.parent
    path = baseline / "Mallory/adapters/hdfs/cases/original102-source-audit-v2/review.json"
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != (
            "140ab3ebfc92a5abf8167d8c101ce2075a6b580700f5ddd3be6e8de29c9e71f8"):
        return "invalid_source_audit_receipt", str(path)
    review = _json(path)
    expected = {
        "HDFS-13": "no_unchanged_cluster_junit_identified",
        "HDFS-18": "unchanged_cluster_junit_not_proven_to_reach_selected_duplicate_branch",
        "HDFS-37": "existing_cluster_junit_reaches_guard_but_is_not_zero_throw_healthy",
    }
    if (not isinstance(review, dict) or
            {item.get("case_id"): item.get("assessment") for item in review.get("cases", [])}
            != expected):
        return "invalid_source_audit_receipt", str(path)
    for artifact in review.get("artifacts", []):
        target = Path(artifact["path"])
        if not target.is_absolute():
            target = baseline / target
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != artifact["sha256"]:
            return "invalid_source_audit_receipt", str(path)
    return ("adapted_cluster_healthy_pending" if case_id != "HDFS-13" else
            "source_review_no_suitable_test"), str(path)


def _hbase27_no_door_review(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Distinguish the passing target seed from a runnable fault campaign."""
    if case_id != "HBASE-27":
        return None, None
    baseline = results.resolve().parent.parent
    calibration = results / "calibration_hbase27_boot_order_v1/HBASE-27"
    receipt_path = calibration / "negative-receipt.json"
    review_path = (baseline / "Mallory/adapters/hbase/pilot"
                   / "HBASE-27-boot-order-monitor-v1/full-v1/healthy-audit.json")
    if not receipt_path.is_file():
        return None, None
    invalid = ("invalid_healthy_no_injectable_door_review", str(receipt_path))
    try:
        if (hashlib.sha256(receipt_path.read_bytes()).hexdigest() !=
                "9637398f1d2ff9ecaced22a728494cdf5a16c3a1af53c6e70bd8464ae443afbf" or
                not review_path.is_file() or
                hashlib.sha256(review_path.read_bytes()).hexdigest() !=
                "be2b4de5855d5347de2b5ed57ee18ba98bbbf80deb8ac9c26b99f252d8757829"):
            return invalid
        receipt = _json(receipt_path)
        result_path = calibration / "result.json"
        result = _json(result_path)
        review = _json(review_path)
        if (receipt.get("case_id") != case_id or
                receipt.get("counts_as_completed_campaign") is not False or
                receipt.get("result_sha256") !=
                hashlib.sha256(result_path.read_bytes()).hexdigest() or
                result.get("status") != "healthy_no_injectable_door" or
                result.get("fault_trials_completed") != 0 or
                result.get("healthy_junit_validation", {}).get("status") != "passed" or
                result.get("target_node_named") is not True or
                result.get("healthy_eligible_doors") != 0 or
                review.get("doors", {}).get("eligible_before_target") != 0):
            return invalid
        for member in receipt["members"]:
            path = (calibration / member["path"]).resolve()
            if (not path.is_relative_to(calibration.resolve()) or not path.is_file() or
                    hashlib.sha256(path.read_bytes()).hexdigest() != member["sha256"]):
                return invalid
        return "healthy_no_injectable_door", str(receipt_path)
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return invalid


def _hbase37_cluster_stage(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Recognize the newer cluster workload without rewriting the older gap."""
    if case_id != "HBASE-37":
        return None, None
    baseline = results.resolve().parent.parent
    package = baseline / "Mallory/adapters/hbase/pilot/HBASE-37-cluster-status-v1/full-v1"
    receipt_path = package / "stage-receipt.json"
    if not receipt_path.is_file():
        return None, None
    invalid = ("invalid_cluster_stage_receipt", str(receipt_path))
    try:
        receipt = _json(receipt_path)
        if not isinstance(receipt, dict):
            return invalid
        files = {
            "config.json": "config_sha256",
            "run_full_node1.sh": "runner_sha256",
            "preflight.py": "preflight_sha256",
            "sites.json": "site_sha256",
            "prior-healthy-result.json": "prior_healthy_result_sha256",
            "verify_terminal.py": "verifier_sha256",
        }
        if any(not (package / name).is_file() or
               hashlib.sha256((package / name).read_bytes()).hexdigest() != receipt.get(key)
               for name, key in files.items()):
            return invalid
        config = _json(package / "config.json")
        prior = _json(package / "prior-healthy-result.json")
        if (receipt.get("schema_version") != 1 or
                receipt.get("kind") != "immutable_cluster_full_v1_stage" or
                receipt.get("case_id") != "HBASE-37" or
                receipt.get("status") != "staged_no_jvm" or
                receipt.get("jvm_started_from_this_stage") is not False or
                receipt.get("prior_healthy_evidence", {}).get("exact_target_reached") is not True or
                config.get("case_id") != "HBASE-37" or
                config.get("cluster_test") !=
                "org.apache.hadoop.hbase.regionserver.http.TestRSStatusPage#testStatusPage" or
                config.get("budget") != receipt.get("budget") or
                prior.get("case_id") != "HBASE-37"):
            return invalid
        return "pending_seed", str(receipt_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return invalid


def _zk05_epoch_influence_gap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Verify the archived six-trial ZK05 fault-model gap from raw events."""
    if case_id != "ZOOKEEPER-05":
        return None, None
    path = results / "admissions/ZOOKEEPER-05-5820-fault-model-gap-v2.json"
    if not path.is_file():
        return None, None
    invalid = ("invalid_fault_model_receipt", str(path))
    try:
        from Mallory.core.graph import OccurrenceGraph

        digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
        receipt = _json(path)
        v1 = results / "admissions/ZOOKEEPER-05-5820-fault-model-gap-v1.json"
        actor_path = results / "admissions/ZOOKEEPER-05-5820-actor-retention-v2.json"
        healthy_dir = results / "calibration_core5820/ZOOKEEPER-05"
        pilot_dir = results / "pilot_core5820/ZOOKEEPER-05"
        bindings = {
            "source_gap_v1_sha256": v1,
            "strict_actor_receipt_sha256": actor_path,
            "healthy_result_sha256": healthy_dir / "result.json",
            "healthy_offline_audit_sha256": healthy_dir / "offline-causal-audit.json",
            "pilot_result_sha256": pilot_dir / "result.json",
            "pilot_offline_audit_sha256": pilot_dir / "offline-causal-audit.json",
        }
        if not isinstance(receipt, dict) or any(
                not file.is_file() or digest(file) != receipt.get(field)
                for field, file in bindings.items()):
            return invalid
        v1_data = _json(v1)
        actor = _json(actor_path)
        healthy = _json(bindings["healthy_result_sha256"])
        pilot = _json(bindings["pilot_result_sha256"])
        healthy_audit = _json(bindings["healthy_offline_audit_sha256"])
        pilot_audit = _json(bindings["pilot_offline_audit_sha256"])
        config = _json(pilot_dir / "config.json")
        if not all(isinstance(item, dict) for item in
                   (v1_data, actor, healthy, pilot, healthy_audit, pilot_audit, config)):
            return invalid
        selector = "org.apache.zookeeper.test.QuorumRestartTest#testRollingRestart"
        source_root = Path("/users/ZhenyuLi/.graphchecker-sources/zookeeper-3.8.7")
        patched_root = Path("/users/ZhenyuLi/.mallory-worktrees/zookeeper")
        sources = receipt.get("source_files")
        if not isinstance(sources, dict) or len(sources) != 4:
            return invalid
        for relative, expected in sources.items():
            file = (source_root / relative).resolve()
            if (not file.is_relative_to(source_root.resolve()) or
                    not file.is_file() or digest(file) != expected):
                return invalid
        patched = patched_root / "zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/Follower.java"
        compiled = patched_root / "zookeeper-server/target/classes/org/apache/zookeeper/server/quorum/Follower.class"
        if (not patched.is_file() or not compiled.is_file() or
                digest(patched) != receipt.get("patched_follower_source_sha256") or
                digest(compiled) != receipt.get("compiled_follower_class_sha256")):
            return invalid
        valid = (
            receipt.get("schema_version") == 1
            and receipt.get("case_id") == "ZOOKEEPER-05"
            and receipt.get("status") ==
                "no_target_retaining_epoch_increase_fault_demonstrated"
            and receipt.get("full_campaign_admission") is False
            and receipt.get("new_jvm_runs_for_this_review") == 0
            and receipt.get("pilot_exact_injections") == 6
            and receipt.get("pilot_same_occurrence_postfault_checks") == 0
            and receipt.get("pilot_time_respecting_fault_to_target_paths") == 0
            and {key: receipt.get(key) for key in v1_data} == v1_data
            and healthy.get("case_id") == pilot.get("case_id") == "ZOOKEEPER-05"
            and healthy.get("cluster_test") == pilot.get("cluster_test") == selector
            and healthy.get("status") == "calibration_complete"
            and healthy.get("healthy_seed_valid") is True
            and healthy.get("fault_trials_completed") == 0
            and pilot.get("status") in TERMINAL
            and pilot.get("healthy_seed_valid") is True
            and pilot.get("fault_trials_completed") == 6
            and pilot.get("strict_injected_trials") == 6
            and pilot.get("exact_exception_trials") == 0
            and healthy_audit.get("report_gate_passed") is True
            and pilot_audit.get("report_gate_passed") is True
            and healthy_audit.get("campaign_result_sha256") ==
                receipt["healthy_result_sha256"]
            and pilot_audit.get("campaign_result_sha256") ==
                receipt["pilot_result_sha256"]
            and actor.get("status") == "no_proven_postfault_target_causality"
            and actor.get("applied_fault_count") == 6
            and actor.get("exact_same_occurrence_count") == 0
            and actor.get("time_respecting_observed_path_count") == 0
            and config.get("case_id") == "ZOOKEEPER-05"
        )
        evidence = receipt.get("trial_evidence")
        if not valid or not isinstance(evidence, list) or len(evidence) != 6:
            return invalid
        sites = set(config.get("target", {}).get("check_sites", []))
        if not sites:
            return invalid
        for expected_id, entry in enumerate(evidence, 1):
            if not isinstance(entry, dict) or entry.get("trial_id") != expected_id:
                return invalid
            trial_dir = pilot_dir / f"trials/r{expected_id:04d}"
            trial_path = trial_dir / "result.json"
            trace_path = trial_dir / "events.jsonl.gz"
            if (not trial_path.is_file() or not trace_path.is_file() or
                    digest(trial_path) != entry.get("trial_result_sha256") or
                    digest(trace_path) != entry.get("trace_gzip_sha256")):
                return invalid
            trial = _json(trial_path)
            packed = trace_path.read_bytes()
            raw = gzip.decompress(packed)
            if (not isinstance(trial, dict) or trial.get("trial_id") != expected_id or
                    hashlib.sha256(raw).hexdigest() != entry.get("trace_raw_sha256") or
                    trial.get("events_evidence", {}).get("raw_sha256") !=
                        entry.get("trace_raw_sha256") or
                    trial.get("events_evidence", {}).get("gzip_sha256") !=
                        entry.get("trace_gzip_sha256")):
                return invalid
            events = tuple(json.loads(line) for line in raw.splitlines() if line.strip())
            faults = [event for event in events if event.get("type") == "FAULT_APPLIED"]
            checks = [event for event in events if event.get("type") == "TARGET_CHECK"
                      and event.get("site") in sites]
            if (len(faults) != 1 or faults[0].get("id") !=
                    entry.get("applied_fault_event_id") or not checks):
                return invalid
            fault = faults[0]
            if any(check.get("seq", -1) > fault.get("seq", 10**12) and
                   all(check.get(key) == fault.get(key)
                       for key in ("node", "epoch", "occurrence"))
                   for check in checks):
                return invalid
            graph = OccurrenceGraph(events, reject_coarse_roots=True)
            if any(graph.event_path(fault, check, require_edge=True)
                   for check in checks):
                return invalid
        return "fault_model_epoch_influence_unproven", str(path)
    except (OSError, ValueError, TypeError, KeyError, EOFError):
        return invalid


def _solr18_v40p_fault_gap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Recompute the bounded v40p verdict from its frozen graph-order release."""
    if case_id != "SOLR-18":
        return None, None
    root = results / "quality_reviews/solr18_v40p_gap"
    path = root / "SOLR-18.json"
    if not path.is_file():
        return None, None
    invalid = ("invalid_bounded_fault_model_gap", str(path))
    try:
        baseline = results.resolve().parent.parent
        digest = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
        index = _json(root / "index.json")
        receipt = _json(path)
        healthy = results / "replays/SOLR-18-v40-lane4"
        pilot = results / "replays/SOLR-18-v40p-lane4"
        release = baseline / "Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4"
        manifest = release / "manifest.json"
        verifier = baseline / "Mallory/adapters/solr/releases/v40/verify_solr18_pilot_gap.py"
        source = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4/solr/solrj/src/java/org/apache/solr/common/cloud/ZkStateReader.java")
        files = (path, verifier, manifest, source,
                 healthy / "result.json", healthy / "offline-causal-audit.json",
                 healthy / "sync-receipt.json", pilot / "result.json",
                 pilot / "offline-causal-audit.json", pilot / "sync-receipt.json",
                 pilot / "config.json")
        if (not isinstance(index, dict) or not isinstance(receipt, dict)
                or any(not file.is_file() for file in files)):
            return invalid
        healthy_result = _json(healthy / "result.json")
        pilot_result = _json(pilot / "result.json")
        audit = _json(pilot / "offline-causal-audit.json")
        if not all(isinstance(item, dict) for item in (healthy_result, pilot_result, audit)):
            return invalid
        valid = (
            index.get("schema_version") == 1
            and index.get("case_id") == receipt.get("case_id") == "SOLR-18"
            and index.get("classification") == receipt.get("classification") ==
                "fault_model_no_same_actor_postfault_target"
            and index.get("receipt_path") == str(path.resolve().relative_to(baseline))
            and index.get("receipt_sha256") == digest(path)
            and index.get("verifier_sha256") == digest(verifier)
            and index.get("core_manifest_sha256") == digest(manifest)
            and receipt.get("full_campaign_promoted") is False
            and receipt.get("new_bug_confirmed") is False
            and receipt.get("healthy_result_sha256") == digest(healthy / "result.json")
            and receipt.get("healthy_audit_sha256") == digest(healthy / "offline-causal-audit.json")
            and receipt.get("healthy_sync_receipt_sha256") == digest(healthy / "sync-receipt.json")
            and receipt.get("pilot_result_sha256") == digest(pilot / "result.json")
            and receipt.get("pilot_audit_sha256") == digest(pilot / "offline-causal-audit.json")
            and receipt.get("pilot_sync_receipt_sha256") == digest(pilot / "sync-receipt.json")
            and receipt.get("pilot_config_sha256") == digest(pilot / "config.json")
            and receipt.get("source_sha256") == digest(source)
            and healthy_result.get("status") == "calibration_complete"
            and pilot_result.get("status") == "budget_exhausted"
            and pilot_result.get("fault_trials_completed") == 8
            and pilot_result.get("strict_injected_trials") == 5
            and audit.get("report_gate_passed") is True
            and audit.get("target_retained_fault_trials") == 4
            and audit.get("same_actor_target_trials") == 0
            and len(receipt.get("trials", [])) == 8
        )
        if not valid:
            return invalid
        for number, trial in enumerate(receipt["trials"], 1):
            result_file = pilot / f"trials/r{number:04d}/result.json"
            trace_file = pilot / f"trials/r{number:04d}/events.jsonl.gz"
            if (trial.get("trial_id") != number or not result_file.is_file()
                    or not trace_file.is_file()
                    or trial.get("trial_result_sha256") != digest(result_file)):
                return invalid
            trial_result = _json(result_file)
            evidence = trial_result.get("events_evidence", {}) if isinstance(trial_result, dict) else {}
            if (evidence.get("gzip_sha256") != digest(trace_file)
                    or evidence.get("raw_sha256") !=
                        hashlib.sha256(gzip.decompress(trace_file.read_bytes())).hexdigest()):
                return invalid
        environment = dict(os.environ, PYTHONPATH=f"{release}:{baseline}")
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            generated_audit = temporary / "audit.json"
            generated_review = temporary / "review.json"
            audit_check = subprocess.run(
                ["python3", "-m", "Mallory.core.audit", "--campaign", str(pilot),
                 "--out", str(generated_audit)], cwd=baseline, env=environment,
                capture_output=True, text=True, timeout=120)
            review_check = subprocess.run(
                ["python3", str(verifier), "--healthy", str(healthy),
                 "--pilot", str(pilot), "--source", str(source),
                 "--out", str(generated_review)], cwd=baseline,
                capture_output=True, text=True, timeout=60)
            if (audit_check.returncode != 0 or review_check.returncode != 0
                    or generated_audit.read_bytes() !=
                        (pilot / "offline-causal-audit.json").read_bytes()
                    or generated_review.read_bytes() != path.read_bytes()):
                return invalid
        return "fault_model_no_same_actor_postfault_target", str(path)
    except (OSError, ValueError, TypeError, KeyError, EOFError, subprocess.TimeoutExpired):
        return invalid


def _solr18_scope_gap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Recheck a bounded healthy trace with incomplete actor/path instrumentation."""
    if case_id != "SOLR-18":
        return None, None
    root = results / "quality_reviews" / "solr18_v34_gap"
    receipt_path = root / "SOLR-18.json"
    if not receipt_path.is_file():
        return None, None
    baseline = results.resolve().parent.parent
    index = _json(root / "index.json")
    receipt = _json(receipt_path)
    campaign = results / "calibration_v34_lane1" / case_id
    release = baseline / "Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f"
    manifest = release / "manifest.json"
    verifier = baseline / "Mallory/adapters/solr/releases/v34/verify_solr18_scope_gap.py"
    result_path = campaign / "result.json"
    audit_path = campaign / "offline-causal-audit.json"
    sync_path = campaign / "sync-receipt.json"
    config_path = campaign / "config.json"
    trial_path = campaign / "trials/r0000/result.json"
    trace_path = campaign / "trials/r0000/events.jsonl.gz"
    needed = (manifest, verifier, result_path, audit_path, sync_path,
              config_path, trial_path, trace_path)
    if (not isinstance(index, dict) or not isinstance(receipt, dict)
            or any(not path.is_file() for path in needed)):
        return "invalid_instrumentation_gap", str(receipt_path)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    result = _json(result_path)
    audit = _json(audit_path)
    trial = _json(trial_path)
    if not all(isinstance(value, dict) for value in (result, audit, trial)):
        return "invalid_instrumentation_gap", str(receipt_path)
    evidence = trial.get("events_evidence")
    if not isinstance(evidence, dict):
        return "invalid_instrumentation_gap", str(receipt_path)
    valid = (
        index.get("schema_version") == 1
        and index.get("case_id") == case_id
        and index.get("classification") == "instrumentation_identity_and_causal_path_gap"
        and index.get("receipt_path") == str(receipt_path.resolve().relative_to(baseline))
        and index.get("receipt_sha256") == digest(receipt_path)
        and index.get("verifier_path") == str(verifier.relative_to(baseline))
        and index.get("verifier_sha256") == digest(verifier)
        and index.get("core_manifest_path") == str(manifest.relative_to(baseline))
        and index.get("core_manifest_sha256") == digest(manifest)
        and receipt.get("schema_version") == 1
        and receipt.get("case_id") == result.get("case_id") == case_id
        and receipt.get("classification") == "instrumentation_identity_and_causal_path_gap"
        and receipt.get("full_campaign_promoted") is False
        and receipt.get("new_bug") is None
        and receipt.get("root_free_time_respecting_door_to_node2_target_paths") == 0
        and receipt.get("identity_gap_reason") == "unregistered_receiver"
        and receipt.get("named_node2_exact_check_count", 0) > 0
        and result.get("status") == "calibration_complete"
        and result.get("healthy_junit_validation", {}).get("status") == "passed"
        and audit.get("report_gate_passed") is True
        and receipt.get("healthy_result_sha256") == digest(result_path)
        and receipt.get("healthy_audit_sha256") == digest(audit_path)
        and receipt.get("sync_receipt_sha256") == digest(sync_path)
        and receipt.get("config_sha256") == digest(config_path)
        and receipt.get("trial_result_sha256") == digest(trial_path)
        and receipt.get("raw_trace_gzip_sha256") == digest(trace_path)
        and evidence.get("gzip_sha256") == receipt.get("raw_trace_gzip_sha256")
        and evidence.get("raw_sha256") == receipt.get("raw_trace_sha256")
        and evidence.get("raw_bytes") == receipt.get("raw_trace_bytes")
    )
    if not valid:
        return "invalid_instrumentation_gap", str(receipt_path)
    environment = dict(os.environ, PYTHONPATH=f"{release}:{baseline}")
    check = subprocess.run(
        ["python3", str(verifier), "--verify-only"], cwd=baseline,
        env=environment, capture_output=True, text=True, timeout=30)
    return ("instrumentation_identity_and_causal_path_gap"
            if check.returncode == 0 else "invalid_instrumentation_gap"), str(receipt_path)


def _source_only_gap(results: Path, case_id: str,
                     receipt: dict[str, Any]) -> str:
    """Label a source-only workload gap without claiming a healthy-run audit."""
    try:
        project_root = results.resolve().parent.parent
        review_name = receipt["review_path"]
        if not isinstance(review_name, str) or Path(review_name).is_absolute():
            return "invalid_source_gap"
        review_path = (project_root / review_name).resolve()
        mallory_root = (project_root / "Mallory").resolve()
        if (not review_path.is_relative_to(mallory_root) or
                not review_path.is_file() or
                hashlib.sha256(review_path.read_bytes()).hexdigest() !=
                receipt.get("review_sha256")):
            return "invalid_source_gap"
        review = _json(review_path)
        if review is None:
            return "invalid_source_gap"
        entry = (review if review.get("case_id") == case_id else
                 next((item for item in review.get("cases", [])
                       if isinstance(item, dict) and item.get("case_id") == case_id), None))
        hdfs_review = (entry is not None and
                       entry.get("type") == "source_only_existing_cluster_test_review" and
                       entry.get("status") == "source_review_no_suitable_test" and
                       entry.get("proof_tier") ==
                       "source_review_plus_one_executed_original_junit" and
                       isinstance(entry.get("source_conclusion"), str) and
                       bool(entry["source_conclusion"]))
        if (entry is None or receipt.get("schema_version") != 1 or
                receipt.get("case_id") != case_id or
                receipt.get("status") != "source_review_no_suitable_test" or
                not (hdfs_review or entry.get("classification", entry.get("category")) in {
                    "no_suitable_existing_cluster_test_found",
                    "no_suitable_existing_cluster_test_proven"})):
            return "invalid_source_gap"
        source_root = Path(review["source_root"]).resolve()
        commit = review["source_commit"]
        if (not source_root.is_dir() or not isinstance(commit, str) or
                subprocess.run(["git", "-C", str(source_root), "rev-parse", "HEAD"],
                               capture_output=True, text=True, check=True).stdout.strip() != commit):
            return "invalid_source_gap"
        references = entry.get("source_refs")
        if references is None and hdfs_review:
            references = entry.get("source_evidence")
        if references is None:
            references = list(entry["survey"]["reviewed_source_sha256"].values())
        if not isinstance(references, list) or not references:
            return "invalid_source_gap"
        for reference in references:
            name, expected = reference["path"], reference["sha256"]
            if not isinstance(name, str) or Path(name).is_absolute():
                return "invalid_source_gap"
            path = (source_root / name).resolve()
            if (not path.is_relative_to(source_root) or not path.is_file() or
                    hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                return "invalid_source_gap"
        old = (entry.get("old_calibration") or entry.get("prior_healthy") or
               entry.get("executed_original_junit"))
        if not isinstance(old, dict):
            return "invalid_source_gap"
        old_name = old.get("result_path", old.get("trial_result_path"))
        old_hash = old.get("result_sha256", old.get("trial_result_sha256"))
        if (not isinstance(old_name, str) or Path(old_name).is_absolute() or
                not isinstance(old_hash, str)):
            return "invalid_source_gap"
        old_path = (project_root / old_name).resolve()
        if (not old_path.is_relative_to(results.resolve()) or
                not old_path.is_file() or
                hashlib.sha256(old_path.read_bytes()).hexdigest() != old_hash):
            return "invalid_source_gap"
        if old.get("exact_target_reached") is True:
            trial = _json(old_path)
            feedback = trial.get("feedback", {}) if isinstance(trial, dict) else {}
            junit = trial.get("junit_validation", {}) if isinstance(trial, dict) else {}
            if (feedback.get("target_reached") is not True or
                    not any(item.get("node") == old.get("named_target")
                            for item in feedback.get("target_instances", [])) or
                    (junit.get("tests"), junit.get("failures"), junit.get("errors")) !=
                    (old.get("junit_tests"), old.get("junit_failures"),
                     old.get("junit_errors")) or junit.get("status") != "passed"):
                return "invalid_source_gap"
        source_receipt = entry.get("source_receipt")
        if source_receipt is not None:
            name = source_receipt["path"]
            if not isinstance(name, str) or Path(name).is_absolute():
                return "invalid_source_gap"
            path = (project_root / name).resolve()
            if (not path.is_relative_to(mallory_root) or not path.is_file() or
                    hashlib.sha256(path.read_bytes()).hexdigest() !=
                    source_receipt.get("sha256")):
                return "invalid_source_gap"
            verifier_name = source_receipt.get("verifier")
            if verifier_name is not None:
                if not isinstance(verifier_name, str) or Path(verifier_name).is_absolute():
                    return "invalid_source_gap"
                verifier = (project_root / verifier_name).resolve()
                if not verifier.is_relative_to(mallory_root) or not verifier.is_file():
                    return "invalid_source_gap"
                check = subprocess.run(["python3", "-B", str(verifier)],
                                       capture_output=True, text=True, timeout=30)
                if check.returncode != 0 or json.loads(check.stdout).get("status") != \
                        source_receipt.get("verifier_status"):
                    return "invalid_source_gap"
        archive = entry.get("healthy_archive")
        if archive is not None:
            for name_key, hash_key in (("path", "sha256"),
                                       ("receipt_path", "receipt_sha256")):
                name = archive[name_key]
                if not isinstance(name, str) or Path(name).is_absolute():
                    return "invalid_source_gap"
                path = (project_root / name).resolve()
                if (not path.is_relative_to(results.resolve()) or not path.is_file() or
                        hashlib.sha256(path.read_bytes()).hexdigest() != archive[hash_key]):
                    return "invalid_source_gap"
        for reference in entry.get("evidence_refs", []):
            name, expected = reference["path"], reference["sha256"]
            if not isinstance(name, str) or Path(name).is_absolute():
                return "invalid_source_gap"
            path = (project_root / name).resolve()
            if (not path.is_relative_to(project_root) or not path.is_file() or
                    hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                return "invalid_source_gap"
        if hdfs_review:
            if (old.get("exact_target_reached") is not False or
                    old.get("junit_tests") != 1 or old.get("junit_failures") != 0 or
                    old.get("junit_errors") != 0 or
                    old.get("target_site_catalog_valid") is not True):
                return "invalid_source_gap"
            for name_key, hash_key in (("campaign_result_path", "campaign_result_sha256"),
                                       ("stdout_path", "stdout_sha256")):
                name, expected = old.get(name_key), old.get(hash_key)
                if (not isinstance(name, str) or Path(name).is_absolute() or
                        not isinstance(expected, str)):
                    return "invalid_source_gap"
                path = (project_root / name).resolve()
                if (not path.is_relative_to(results.resolve()) or not path.is_file() or
                        hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                    return "invalid_source_gap"
        return "source_review_no_suitable_test"
    except (OSError, KeyError, TypeError, ValueError, AttributeError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired):
        return "invalid_source_gap"


def _source_weak_candidate(results: Path, case_id: str) -> str | None:
    """Recognize a hash-bound source finding without claiming no suitable test."""
    try:
        project_root = results.resolve().parent.parent
        receipt_path = results / "source_weak" / case_id / "receipt-v1.json"
        receipt = _json(receipt_path)
        if receipt is None:
            return None
        if (receipt.get("schema_version") != 1 or
                receipt.get("kind") != "source_weak_candidate_v1" or
                receipt.get("case_id") != case_id or
                receipt.get("status") != "source_weak_candidate"):
            return "invalid_source_weak"
        review_name = receipt.get("review_path")
        if not isinstance(review_name, str) or Path(review_name).is_absolute():
            return "invalid_source_weak"
        review_path = (project_root / review_name).resolve()
        if (not review_path.is_relative_to((project_root / "Mallory").resolve()) or
                hashlib.sha256(review_path.read_bytes()).hexdigest() !=
                receipt.get("review_sha256")):
            return "invalid_source_weak"
        review = _json(review_path)
        if (review is None or review.get("case_id") != case_id or
                review.get("classification") !=
                "configuration_local_weak_static_candidate"):
            return "invalid_source_weak"
        source_root = Path(review["source_root"]).resolve()
        if (not source_root.is_dir() or
                subprocess.run(["git", "-C", str(source_root), "rev-parse", "HEAD"],
                               capture_output=True, text=True, check=True).stdout.strip() !=
                review.get("source_commit")):
            return "invalid_source_weak"
        for reference in review["source_refs"]:
            name = reference["path"]
            if not isinstance(name, str) or Path(name).is_absolute():
                return "invalid_source_weak"
            path = (source_root / name).resolve()
            if (not path.is_relative_to(source_root) or
                    hashlib.sha256(path.read_bytes()).hexdigest() !=
                    reference.get("sha256")):
                return "invalid_source_weak"
        for evidence in (review["prior_calibration"], review["prior_triage"]):
            name = evidence.get("result_path", evidence.get("path"))
            expected = evidence.get("result_sha256", evidence.get("sha256"))
            if (not isinstance(name, str) or Path(name).is_absolute() or
                    not isinstance(expected, str)):
                return "invalid_source_weak"
            path = (project_root / name).resolve()
            if (not path.is_relative_to(project_root) or
                    hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                return "invalid_source_weak"
        prior = _json(project_root / review["prior_calibration"]["result_path"])
        if (prior is None or prior.get("case_id") != case_id or
                prior.get("status") != review["prior_calibration"]["status"] or
                prior.get("fault_trials_completed") != 0):
            return "invalid_source_weak"
        return "source_weak_candidate"
    except (OSError, KeyError, TypeError, ValueError, subprocess.CalledProcessError):
        return "invalid_source_weak"


def _healthy_target_unreliable(results: Path, case_id: str) -> str | None:
    """Record repeated healthy target misses while preserving a prior target hit."""
    try:
        project_root = results.resolve().parent.parent
        receipt = _json(results / "target_unreliable" / case_id / "receipt.json")
        if receipt is None:
            return None
        if (receipt.get("schema_version") != 1 or
                receipt.get("kind") != "healthy_target_unreliable_v1" or
                receipt.get("case_id") != case_id or
                receipt.get("status") != "healthy_target_unreliable" or
                receipt.get("terminal_classification") is not False or
                receipt.get("fault_trials_completed") != 0):
            return "invalid_target_unreliable"

        def evidence(name: str, expected: str) -> Path:
            if not isinstance(name, str) or Path(name).is_absolute():
                raise ValueError("invalid evidence path")
            path = (project_root / name).resolve()
            if (not path.is_relative_to(results.resolve()) or
                    hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                raise ValueError("evidence hash mismatch")
            return path

        positive = receipt["prior_positive_target_evidence"]
        old_result = _json(evidence(positive["result_path"],
                                    positive["result_sha256"]))
        old_trial = _json(evidence(positive["trial_result_path"],
                                   positive["trial_result_sha256"]))
        if (old_result is None or old_trial is None or
                old_result.get("case_id") != case_id or
                old_result.get("status") != "calibration_complete" or
                old_result.get("healthy_seed_valid") is not True or
                old_result.get("fault_trials_completed") != 0 or
                old_result.get("runtime_attestation", {}).get("valid") is not True or
                old_result["runtime_attestation"].get("exact_site_catalog_valid") is not True or
                not old_result["runtime_attestation"].get("bound_nodes") or
                old_trial.get("feedback", {}).get("target_reached") is not True or
                old_trial["feedback"].get("target_identity_complete") is not True or
                old_trial["feedback"].get("target_threw") is not False or
                positive.get("target_reached") is not True):
            return "invalid_target_unreliable"
        attempts = receipt.get("new_hook_attempts")
        if not isinstance(attempts, list) or len(attempts) != 3 or len({
                item.get("cohort") for item in attempts}) != 3:
            return "invalid_target_unreliable"
        for attempt in attempts:
            result = _json(evidence(attempt["result_path"],
                                    attempt["result_sha256"]))
            audit = _json(evidence(attempt["audit_path"],
                                   attempt["audit_sha256"]))
            junit = _json(evidence(attempt["junit_receipt_path"],
                                   attempt["junit_receipt_sha256"]))
            evidence(attempt["trace_path"], attempt["trace_sha256"])
            if (result is None or audit is None or junit is None or
                    result.get("case_id") != case_id or
                    result.get("status") != "healthy_seed_invalid" or
                    result.get("fault_trials_completed") != 0 or
                    result.get("healthy_seed_valid") is not False or
                    len(result.get("trials", [])) != 1 or
                    result["trials"][0].get("status") != "healthy_target_missing" or
                    result["trials"][0].get("target_reached") is not False or
                    audit.get("campaign_result_sha256") != attempt["result_sha256"] or
                    audit.get("archive_integrity_valid") is not True or
                    audit.get("report_gate_passed") is not False or
                    audit.get("healthy_observed_path_doors") != 0 or
                    junit.get("status") != "passed" or junit.get("tests") != 1 or
                    junit.get("failures") != 0 or junit.get("errors") != 0 or
                    attempt.get("exact_target_reached") is not False or
                    attempt.get("junit_passed") is not True or
                    attempt.get("target_site_catalog_valid") is not True):
                return "invalid_target_unreliable"
        return "healthy_target_unreliable"
    except (OSError, KeyError, TypeError, ValueError, AttributeError):
        return "invalid_target_unreliable"


def _json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _calibrations(results: Path, case_id: str) -> list[dict[str, Any]]:
    paths = [(1, results / "calibration" / case_id / "result.json")]
    for candidate in results.glob(f"calibration_v*/{case_id}/result.json"):
        version = candidate.parent.parent.name.removeprefix("calibration_v")
        if version.isdigit() and int(version) > 1:
            paths.append((int(version), candidate))
    rows = []
    for version, path in sorted(paths):
        value = _json(path)
        if value is None:
            continue
        valid = (value.get("case_id") == case_id and isinstance(value.get("status"), str))
        rows.append({"version": version, "path": str(path),
                     "status": value["status"] if valid else "invalid_calibration",
                     "cluster_test": value.get("cluster_test") if valid else None,
                     "duration_seconds": value.get("duration_seconds") if valid else None})
    return rows


def _hbase02_offhost_review(results: Path, result_path: Path,
                           result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Validate the compact canonical result against every offhost archive member."""
    if result.get("case_id") != "HBASE-02":
        return None, None
    baseline = Path(__file__).resolve().parents[2]
    verifier = baseline / "Mallory/report/verify_hbase02_offhost.py"
    index_path = results / "quality_reviews/hbase02_v4_offhost/index.json"
    receipt_path = (results / "HBASE-02/campaigns/"
                    "request-token-scoped-v4-full-offhost/negative-receipt.json")
    index = _json(index_path)
    if (not isinstance(index, dict)
            or result_path.resolve() != (results / "cases/HBASE-02/result.json").resolve()
            or not verifier.is_file() or not receipt_path.is_file()
            or index.get("verifier_sha256") != hashlib.sha256(verifier.read_bytes()).hexdigest()
            or index.get("receipt_sha256") != hashlib.sha256(receipt_path.read_bytes()).hexdigest()):
        return "invalid", str(index_path)
    try:
        check = subprocess.run(
            ["python3", str(verifier), "--data-root", str(results)],
            cwd=baseline, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "invalid", str(index_path)
    return ("faulted_path_unverified" if check.returncode == 0 else "invalid"), str(index_path)


def _hbase12_legacy_review(results: Path, result_path: Path,
                          result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Rehash the lane8 archive and keep its expected-exception oracle caveat."""
    if result.get("case_id") != "HBASE-12":
        return None, None
    baseline = Path(__file__).resolve().parents[2]
    verifier = baseline / "Mallory/report/verify_hbase12_legacy.py"
    index_path = results / "quality_reviews/hbase12_legacy_lane8/index.json"
    index = _json(index_path)
    if (not isinstance(index, dict)
            or result_path.resolve() != (results / "cases/HBASE-12/result.json").resolve()
            or not verifier.is_file()
            or index.get("verifier_sha256") != hashlib.sha256(verifier.read_bytes()).hexdigest()):
        return "invalid", str(index_path)
    try:
        check = subprocess.run(
            ["python3", str(verifier), "--data-root", str(results),
             "--baseline", str(baseline)],
            cwd=baseline, capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return "invalid", str(index_path)
    return ("expected_exception_oracle_confounded" if check.returncode == 0
            else "invalid"), str(index_path)


def _solr38_39_source_gap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Recheck the source-backed typed-I/O gap against pinned prior runs."""
    if case_id not in {"SOLR-38", "SOLR-39"}:
        return None, None
    baseline = Path(__file__).resolve().parents[2]
    source_root = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
    verifier = baseline / "Mallory/adapters/solr/releases/v42/verify_solr38_39_source_gaps.py"
    tag = case_id.lower().replace("-", "")
    root = results / f"quality_reviews/{tag}_source_gap"
    index_path, receipt_path = root / "index.json", root / f"{case_id}.json"
    index, receipt = _json(index_path), _json(receipt_path)
    classification = {"SOLR-38": "current_typed_io_fault_model_no_retained_target",
                      "SOLR-39": "current_selector_and_typed_io_path_unproven"}[case_id]
    status = {"SOLR-38": "fault_model_current_typed_io_no_retained_target",
              "SOLR-39": "source_review_selector_and_io_path_unproven"}[case_id]
    if (not isinstance(index, dict) or not isinstance(receipt, dict)
            or not verifier.is_file() or not source_root.is_dir()
            or index.get("schema_version") != 1
            or index.get("case_id") != case_id
            or index.get("classification") != classification
            or index.get("verifier_sha256") != hashlib.sha256(verifier.read_bytes()).hexdigest()
            or index.get("receipt_sha256") != hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            or receipt.get("case_id") != case_id
            or receipt.get("classification") != classification
            or receipt.get("full_campaign_promoted") is not False
            or receipt.get("new_bug_confirmed") is not False):
        return "invalid_fault_model_receipt", str(index_path)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "receipt.json"
        try:
            check = subprocess.run(
                ["python3", str(verifier), "--base", str(baseline),
                 "--source-root", str(source_root), "--case-id", case_id,
                 "--out", str(output)], cwd=baseline, capture_output=True,
                text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return "invalid_fault_model_receipt", str(index_path)
        if (check.returncode != 0 or not output.is_file()
                or output.read_bytes() != receipt_path.read_bytes()):
            return "invalid_fault_model_receipt", str(index_path)
    return status, str(receipt_path)


def _solr37_retry_source_review(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Bind the bounded no-path pilot to its zero-retry source finding."""
    if case_id != "SOLR-37":
        return None, None
    baseline = Path(__file__).resolve().parents[2]
    source_root = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
    verifier = baseline / "Mallory/adapters/solr/releases/v43/verify_solr37_retry_gap.py"
    root = results / "quality_reviews/solr37_retry_gap"
    index_path, receipt_path = root / "index.json", root / "SOLR-37.json"
    index, receipt = _json(index_path), _json(receipt_path)
    if (not isinstance(index, dict) or not isinstance(receipt, dict)
            or not verifier.is_file() or not source_root.is_dir()
            or index.get("schema_version") != 1
            or index.get("case_id") != "SOLR-37"
            or index.get("classification") != "subshard_http_fault_has_no_configured_retry"
            or index.get("verifier_sha256") != hashlib.sha256(verifier.read_bytes()).hexdigest()
            or index.get("receipt_sha256") != hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            or receipt.get("classification") != index.get("classification")
            or receipt.get("full_campaign_promoted") is not False):
        return "invalid_fault_model_receipt", str(index_path)
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "receipt.json"
        try:
            check = subprocess.run(
                ["python3", str(verifier), "--base", str(baseline),
                 "--source-root", str(source_root), "--out", str(output)],
                cwd=baseline, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return "invalid_fault_model_receipt", str(index_path)
        if (check.returncode != 0 or not output.is_file()
                or output.read_bytes() != receipt_path.read_bytes()):
            return "invalid_fault_model_receipt", str(index_path)
    return "source_review_no_configured_retry", str(receipt_path)


def _zk06_retry_guard_gap(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Require the exact retry packet trace before recording a skipped guard."""
    if case_id != "ZOOKEEPER-06":
        return None, None
    baseline = Path(__file__).resolve().parents[2]
    verifier = baseline / "Mallory/report/verify_zk06_retry_gap.py"
    index_path = results / "quality_reviews/zk06_ackepoch_retry_gap/index.json"
    receipt_path = (results / "admissions/"
                    "ZOOKEEPER-06-ackepoch-retry-door-node1-source-gap-v1.json")
    index = _json(index_path)
    if (not isinstance(index, dict) or not verifier.is_file() or not receipt_path.is_file()
            or index.get("verifier_sha256") != hashlib.sha256(verifier.read_bytes()).hexdigest()
            or index.get("source_gap_receipt_sha256") != hashlib.sha256(receipt_path.read_bytes()).hexdigest()):
        return "invalid_fault_model_receipt", str(index_path)
    try:
        check = subprocess.run(
            ["python3", str(verifier), "--data-root", str(results),
             "--baseline", str(baseline)], cwd=baseline,
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return "invalid_fault_model_receipt", str(index_path)
    return ("fault_model_target_guard_skipped_on_retry" if check.returncode == 0
            else "invalid_fault_model_receipt"), str(receipt_path)


def _zk_independent_source_review(results: Path, case_id: str) -> tuple[str | None, str | None]:
    """Attach later source review while preserving each case's primary outcome."""
    groups = {
        "ZOOKEEPER-02": "ZOOKEEPER-02-03", "ZOOKEEPER-03": "ZOOKEEPER-02-03",
        "ZOOKEEPER-04": "ZOOKEEPER-04-05", "ZOOKEEPER-05": "ZOOKEEPER-04-05",
        "ZOOKEEPER-10": "ZOOKEEPER-10-11", "ZOOKEEPER-11": "ZOOKEEPER-10-11",
    }
    group = groups.get(case_id)
    if group is None:
        return None, None
    baseline = Path(__file__).resolve().parents[2]
    source_root = Path("/users/ZhenyuLi/.graphchecker-sources/zookeeper-3.8.7")
    index = _json(results / "quality_reviews/zk_independent_source_v1/index.json")
    entry = (index.get("receipts", {}).get(group) if isinstance(index, dict) else None)
    if not isinstance(entry, dict) or index.get("schema_version") != 1:
        return "invalid_supplementary_source_review", None
    receipt_name = entry.get("path")
    if (not isinstance(receipt_name, str)
            or not receipt_name.startswith("data/mallory/admissions/")):
        return "invalid_supplementary_source_review", None
    receipt_path = (results / receipt_name.removeprefix("data/mallory/")).resolve()
    if (not receipt_path.is_relative_to(results.resolve()) or not receipt_path.is_file()
            or hashlib.sha256(receipt_path.read_bytes()).hexdigest() != entry.get("sha256")):
        return "invalid_supplementary_source_review", str(receipt_path)
    receipt = _json(receipt_path)
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        return "invalid_supplementary_source_review", str(receipt_path)
    expected_status = ("no_new_target_retaining_request_path_identified"
                       if group == "ZOOKEEPER-02-03" else "no_new_full_campaign_admission")
    cases = receipt.get("cases", receipt.get("case_ids"))
    identifiers = [item.get("case_id") if isinstance(item, dict) else item
                   for item in cases] if isinstance(cases, list) else []
    if receipt.get("status") != expected_status:
        return "invalid_supplementary_source_review", str(receipt_path)
    suffixes = group.removeprefix("ZOOKEEPER-").split("-")
    if identifiers != [f"ZOOKEEPER-{suffix}" for suffix in suffixes]:
        return "invalid_supplementary_source_review", str(receipt_path)
    evidence = receipt.get("source_evidence")
    sources = ([{"path": path, "sha256": value} for path, value in evidence.items()]
               if isinstance(evidence, dict) else evidence)
    if not isinstance(sources, list) or not sources:
        return "invalid_supplementary_source_review", str(receipt_path)
    for item in sources:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            return "invalid_supplementary_source_review", str(receipt_path)
        path = (source_root / item["path"]).resolve()
        if (not path.is_relative_to(source_root) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256")):
            return "invalid_supplementary_source_review", str(receipt_path)
    records = receipt.get("previous_evidence", receipt.get("cases"))
    if not isinstance(records, list) or len(records) != 2:
        return "invalid_supplementary_source_review", str(receipt_path)
    for record in records:
        if not isinstance(record, dict):
            return "invalid_supplementary_source_review", str(receipt_path)
        if record.get("full_campaign_admission") is True:
            return "invalid_supplementary_source_review", str(receipt_path)
        for key, value in record.items():
            if not key.endswith("_sha256") or not isinstance(value, str):
                continue
            ref = record.get(key.removesuffix("_sha256"))
            if not isinstance(ref, str):
                continue
            path = (baseline / ref).resolve()
            if (not path.is_relative_to(baseline) or not path.is_file()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != value):
                return "invalid_supplementary_source_review", str(receipt_path)
        if record.get("proven_postfault_target_paths", 0) != 0:
            return "invalid_supplementary_source_review", str(receipt_path)
    if group == "ZOOKEEPER-02-03" and receipt.get("decision", {}).get("full_campaign_admission") is not False:
        return "invalid_supplementary_source_review", str(receipt_path)
    return "supplementary_source_review_verified", str(receipt_path)


def _case_local_fault_depth_review(result_path: Path, result: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Verify a campaign whose pinned core has file hashes but no release ID."""
    canonical = result_path.parent
    path = canonical / "fault-depth-review.json"
    if not path.is_file():
        return None, None
    try:
        review = _json(path)
        config_path = canonical / "config.json"
        checkpoint_path = canonical / "checkpoint.json"
        config = _json(config_path)
        pinned = config.get("mapping", {}).get("pinned_core")
        if pinned is not None:
            core_root = Path(pinned["root"])
            core_files = pinned["files"]
        elif result["case_id"] == "SOLR-13":
            # This release predates config.core_release. Its immutable runner
            # selects the release, and the archive receipt pins that runner.
            release_id = review["controller_release_id"]
            assert release_id == Path(release_id).name
            root = Path(__file__).resolve().parents[2]
            core_root = root / "Mallory/dispatch/releases" / release_id
            manifest_path = core_root / "manifest.json"
            manifest = _json(manifest_path)
            assert manifest["release_id"] == release_id
            assert review["controller_release_manifest_sha256"] == hashlib.sha256(
                manifest_path.read_bytes()).hexdigest()
            core_files = manifest["files"]
            package = root / "Mallory/adapters/solr/cases/SOLR-13/source-exploratory-full-node0-v1"
            package_manifest = _json(package / "sha-manifest.json")
            runner = package / "run_campaign.py"
            runner_sha = hashlib.sha256(runner.read_bytes()).hexdigest()
            receipt = _json(root / "data/mallory/evidence_archives/"
                            "SOLR-13-source-exploratory-full-node0-v1.receipt.json")
            assert package_manifest["files"]["run_campaign.py"]["sha256"] == runner_sha
            assert receipt["package_runner_sha256"] == runner_sha
            assert f"Mallory/dispatch/releases/{release_id}" in runner.read_text()
        else:
            raise ValueError("case-local controller provenance is absent")
        assert review["schema_version"] == 1
        assert review["case_id"] == result["case_id"] == config["case_id"]
        assert review["status"] == result["status"] in TERMINAL
        assert review["fault_trials_completed"] == result["fault_trials_completed"]
        assert review["campaign_result_sha256"] == hashlib.sha256(result_path.read_bytes()).hexdigest()
        assert review["campaign_config_sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
        assert review["campaign_checkpoint_sha256"] == hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
        if pinned is not None:
            assert review["pinned_core_root"] == str(core_root)
            assert review["pinned_core_files_sha256"] == core_files
        assert review["scheduler_sha256"] == core_files["Mallory/core/scheduler.py"]
        for relative, digest in core_files.items():
            name = Path(relative)
            assert name.parts[0] == "Mallory" and ".." not in name.parts
            if pinned is not None:
                assert name.parts[:2] == ("Mallory", "core")
            assert hashlib.sha256((core_root / name).read_bytes()).hexdigest() == digest

        campaign_dir = canonical / "campaigns"
        if campaign_dir.is_dir():
            candidates = list(campaign_dir.iterdir())
        else:
            seal = _json(canonical / "terminal-seal.json")
            assert seal["case_id"] == result["case_id"] and seal["status"] == result["status"]
            assert seal["compact_files_sha256"]["fault-depth-review.json"] == hashlib.sha256(path.read_bytes()).hexdigest()
            source = Path(seal["source_campaign"])
            if not source.is_absolute():
                source = Path(__file__).resolve().parents[2] / source
            assert source.resolve().is_relative_to(Path(__file__).resolve().parents[2] / "data/mallory")
            candidates = [source]
        campaigns = [candidate for candidate in candidates
                     if candidate.is_dir() and (candidate / "result.json").is_file()
                     and hashlib.sha256((candidate / "result.json").read_bytes()).hexdigest()
                     == review["campaign_result_sha256"]]
        assert len(campaigns) == 1
        distribution: dict[str, int] = {}
        trials = review["trials"]
        assert len(trials) == review["fault_trials_completed"]
        for expected_id, trial in enumerate(trials, start=1):
            assert trial["trial_id"] == expected_id
            trial_path = campaigns[0] / "trials" / f"r{expected_id:04d}" / "result.json"
            assert hashlib.sha256(trial_path.read_bytes()).hexdigest() == trial["result_sha256"]
            depth = trial["depth"]
            assert isinstance(depth, int) and 1 <= depth <= config["budget"]["max_faults_per_trial"]
            distribution[str(depth)] = distribution.get(str(depth), 0) + 1
        assert distribution == review["depth_distribution"]
        return dict(review, controller_release_id=(review["controller_release_id"]
                  if pinned is None else None), scheduler_policy_commit=None), str(path)
    except (AssertionError, KeyError, TypeError, ValueError, OSError):
        return None, str(path)


def _fault_depth_review(results: Path, result_path: Path, result: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Verify an offhost depth review against the terminal result and raw SHA index."""
    case_id = result["case_id"]
    path = results / "quality_reviews/fault_depth" / f"{case_id}.json"
    if not path.is_file():
        return _case_local_fault_depth_review(result_path, result)
    try:
        review = _json(path)
        canonical = result_path.parent
        config_path = canonical / "config.json"
        config = _json(config_path)
        assert review["case_id"] == case_id
        assert review["status"] == result["status"] in TERMINAL
        assert review["fault_trials_completed"] == result["fault_trials_completed"]
        assert review["campaign_config_sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
        release = config["core_release"]
        if isinstance(release, dict) and "path" not in release:
            release_id = release["release_id"]
            assert release_id == Path(release_id).name
            release_path = Path(__file__).resolve().parents[2] / "Mallory/dispatch/releases" / release_id
        else:
            release_path = Path(release["path"] if isinstance(release, dict) else release)
        manifest_path = release_path / "manifest.json"
        manifest = _json(manifest_path)
        assert manifest["release_id"] == review["controller_release_id"] == release_path.name
        assert review["controller_release_manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if isinstance(release, dict):
            assert release.get("release_id", release_path.name) == release_path.name
            assert release.get("manifest_sha256", review["controller_release_manifest_sha256"]) == review["controller_release_manifest_sha256"]
        assert review["scheduler_sha256"] == manifest["files"]["Mallory/core/scheduler.py"]
        assert review["scheduler_policy_commit"] == config.get("mapping", {}).get("scheduler_policy_commit")

        raw_copy = _json(canonical / "raw-copy-receipt.json")
        trial_prefix = "trials/"
        if raw_copy is not None:
            raw_files = raw_copy["files"]
            sync = _json(canonical / "sync-receipt.json")
            assert raw_files["result.json"] == sync["remote_raw_result_sha256"] == review["campaign_result_sha256"]
            assert raw_files["checkpoint.json"] == review["campaign_checkpoint_sha256"]
            assert raw_files["config.json"] == review["campaign_config_sha256"]
            trial_hashes = raw_files
        elif (canonical / "canonical-import-receipt.json").is_file():
            receipt = _json(canonical / "canonical-import-receipt.json")
            if "canonical_result_sha256" in receipt:
                assert receipt["canonical_result_sha256"] == review["campaign_result_sha256"]
                assert receipt["canonical_config_sha256"] == review["campaign_config_sha256"]
                assert receipt["canonical_checkpoint_sha256"] == review["campaign_checkpoint_sha256"]
                matches = []
                for candidate in (canonical / "campaigns").iterdir():
                    if (candidate.is_dir() and
                            all((candidate / name).is_file() for name in
                                ("result.json", "config.json", "checkpoint.json")) and
                            hashlib.sha256((candidate / "result.json").read_bytes()).hexdigest() ==
                            review["campaign_result_sha256"] and
                            hashlib.sha256((candidate / "config.json").read_bytes()).hexdigest() ==
                            review["campaign_config_sha256"] and
                            hashlib.sha256((candidate / "checkpoint.json").read_bytes()).hexdigest() ==
                            review["campaign_checkpoint_sha256"]):
                        matches.append(candidate)
                assert len(matches) == 1
                source = matches[0]
                trial_hashes = {
                    f"trials/r{number:04d}/result.json": hashlib.sha256(
                        (source / "trials" / f"r{number:04d}" / "result.json").read_bytes()
                    ).hexdigest()
                    for number in range(1, review["fault_trials_completed"] + 1)
                }
            else:
                archive_path = path.with_name(f"{case_id}.archive-manifest.json")
                archive = _json(archive_path)
                assert receipt["result_sha256"] == review["campaign_result_sha256"]
                assert receipt["checkpoint_sha256"] == review["campaign_checkpoint_sha256"]
                assert receipt["manifest_sha256"] == hashlib.sha256(archive_path.read_bytes()).hexdigest()
                trial_hashes = {item["path"].split("/trials/", 1)[-1]: item["sha256"]
                                for item in archive["members"] if "/trials/" in item["path"]}
                trial_prefix = ""
        else:
            seal = _json(canonical / "terminal-seal.json")
            assert seal["case_id"] == case_id and seal["status"] == result["status"]
            source = results.parent.parent / seal["source_campaign"]
            assert source.resolve().is_relative_to(results.resolve())
            assert hashlib.sha256((source / "result.json").read_bytes()).hexdigest() == review["campaign_result_sha256"]
            assert hashlib.sha256((source / "config.json").read_bytes()).hexdigest() == review["campaign_config_sha256"]
            assert hashlib.sha256((source / "checkpoint.json").read_bytes()).hexdigest() == review["campaign_checkpoint_sha256"]
            assert seal["compact_files_sha256"]["result.json"] == review["campaign_result_sha256"]
            trial_hashes = {
                f"trials/r{number:04d}/result.json": hashlib.sha256(
                    (source / "trials" / f"r{number:04d}" / "result.json").read_bytes()).hexdigest()
                for number in range(1, review["fault_trials_completed"] + 1)
            }
        distribution: dict[str, int] = {}
        trials = review["trials"]
        assert len(trials) == review["fault_trials_completed"]
        for expected_id, trial in enumerate(trials, start=1):
            assert trial["trial_id"] == expected_id
            key = f"{trial_prefix}r{expected_id:04d}/result.json"
            assert trial_hashes[key] == trial["result_sha256"]
            depth = trial["depth"]
            assert isinstance(depth, int) and 1 <= depth <= config["budget"]["max_faults_per_trial"]
            distribution[str(depth)] = distribution.get(str(depth), 0) + 1
        assert distribution == review["depth_distribution"]
        return review, str(path)
    except (AssertionError, KeyError, TypeError, ValueError, OSError):
        return None, str(path)


def _row(case: dict[str, Any], results: Path) -> dict[str, Any]:
    case_id = case["case_id"]
    target = case["target"]
    workload = case["workload"]
    result_path = results / "cases" / case_id / "result.json"
    result = _json(result_path)
    calibrations = _calibrations(results, case_id)
    calibration = calibrations[-1] if calibrations else None
    eligibility = case["eligibility"]
    mapped = bool(eligibility.get("may_dispatch_healthy_seed",
                                  eligibility.get("may_attempt_seed")))
    if mapped:
        initial_status = "pending_seed"
    elif eligibility.get("state") in {"source_infeasible_healthy_guard",
                                       "workload_oracle_unfit"}:
        initial_status = eligibility["state"]
    elif eligibility.get("state") == "no_mapped_cluster_test":
        initial_status = "no_mapped_cluster_test"
    elif eligibility.get("state") == "build_tool_unavailable":
        initial_status = "runner_pending"
    else:
        initial_status = "target_mapping_gap"
    row: dict[str, Any] = {
        "case_id": case_id,
        "cohort": case["cohort"],
        "system": case["system"],
        "system_version": case["system_version"],
        "source_path": target["source_path"],
        "source_line": target["source_line"],
        "function": target["function"],
        "site_id": target["site_id"],
        "check_code": target["check_code"],
        "target_exception": target["target_exception"],
        "cluster_test": workload.get("selected_selector"),
        "calibration_cluster_test": (calibration["cluster_test"]
                                     if calibration is not None else None),
        "campaign_cluster_test": None,
        "inventory_state": eligibility["state"],
        "bytecode_mapping_status": eligibility.get("bytecode_mapping_status"),
        "mapping_gaps": eligibility.get("mapping_gaps", []),
        "result_path": str(result_path) if result is not None else None,
        "calibration_path": calibration["path"] if calibration is not None else None,
        "calibration_status": calibration["status"] if calibration is not None else None,
        "calibration_duration_seconds": (calibration["duration_seconds"]
                                         if calibration is not None else None),
        "calibration_history": calibrations,
        "report_status": initial_status,
        "skipped_no_suitable_cluster_test": False,
        "quality_status": None,
        "causal_audit": None,
        "causal_precision_review": None,
        "causal_precision_receipt": None,
        "healthy_closure_evidence_types": None,
        "healthy_local_timeline_doors": None,
        "local_timeline_only": None,
        "same_actor_target_trials": None,
        "posthoc_attestation": None,
        "campaign_status": None,
        "duration_seconds": None,
        "fault_trials_completed": None,
        "fault_depth_distribution": None,
        "controller_release_id": None,
        "controller_scheduler_sha256": None,
        "controller_scheduler_policy_commit": None,
        "fault_depth_review_receipt": None,
        "strict_injected_trials": None,
        "strict_target_trials": None,
        "target_reached_trials": None,
        "exact_exception_trials": None,
        "coverage_ids_seen": None,
        "closure_coverage_ids_seen": None,
        "closure_edge_fingerprints_seen": None,
        "target_node_named": None,
        "source_review_status": None,
        "source_review_receipt": None,
        "source_review_classification": None,
        "source_gap_receipt": None,
        "fault_model_receipt": None,
        "supplementary_fault_model_status": None,
        "new_bug": None,
    }
    supplementary, supplementary_receipt = _zk_independent_source_review(results, case_id)
    if supplementary == "supplementary_source_review_verified":
        row["supplementary_fault_model_status"] = supplementary
        row["source_review_receipt"] = supplementary_receipt
    elif supplementary is not None:
        row["source_gap_error"] = "independent source review or referenced evidence mismatch"
    cluster_review, cluster_review_path = _zk08_09_cluster_junit_review(results, case_id)
    if cluster_review == "source_review_no_mapped_cluster_test":
        row["source_review_status"] = cluster_review
        row["source_review_receipt"] = cluster_review_path
    elif cluster_review is not None:
        row["source_gap_error"] = "cluster JUnit source review hash mismatch"
    hbase_audit, hbase_audit_path = _hbase23_28_source_audit(results, case_id)
    if hbase_audit == "source_audit_verified_pending":
        row["source_review_status"] = hbase_audit
        row["source_review_receipt"] = hbase_audit_path
    elif hbase_audit is not None:
        row["source_gap_error"] = "HBase source audit receipt hash mismatch"
    hdfs_audit, hdfs_audit_path = _hdfs13_18_37_source_audit(results, case_id)
    if hdfs_audit in {"adapted_cluster_healthy_pending", "source_review_no_suitable_test"}:
        row["source_review_status"] = hdfs_audit
        row["source_review_receipt"] = hdfs_audit_path
    elif hdfs_audit is not None:
        row["source_gap_error"] = "HDFS source audit receipt or referenced artifact mismatch"
    if result is None:
        if hdfs_audit == "adapted_cluster_healthy_pending":
            row["report_status"] = "pending_seed"
            row["source_review_classification"] = "adapted_cluster_junit_unexecuted"
            row["source_gap_receipt"] = hdfs_audit_path
            return row
        hbase32_status, hbase32_receipt = _hbase32_target_discovery_stage(results, case_id)
        if hbase32_status == "pending_fault_discovery_bootstrap":
            row["report_status"] = hbase32_status
            row["source_review_status"] = "prior_healthy_guard_absent_bootstrap_staged"
            row["source_review_receipt"] = hbase32_receipt
            row["source_gap_receipt"] = hbase32_receipt
            return row
        if hbase32_status is not None:
            row["source_gap_error"] = "HBASE-32 discovery package or prior evidence mismatch"
        if case_id == "SOLR-16":
            source_gap = _source_gap(results, case_id, calibration)
            if source_gap == "source_review_no_suitable_test":
                row["report_status"] = source_gap
                row["source_gap_receipt"] = str(results / "source_gaps" / case_id / "receipt.json")
                row["skipped_no_suitable_cluster_test"] = True
                return row
            if source_gap == "invalid_source_gap":
                row["source_gap_error"] = "source-gap receipt or healthy evidence mismatch"
        bootstrap_status, bootstrap_receipt = _solr_fault_discovery_bootstrap(results, case_id)
        if bootstrap_status is not None:
            row["report_status"] = bootstrap_status
            row["source_review_status"] = bootstrap_status
            row["source_review_receipt"] = bootstrap_receipt
            if bootstrap_status.startswith("invalid_"):
                row["source_gap_error"] = "fault-discovery bootstrap review or pinned evidence mismatch"
            return row
        no_door_status, no_door_receipt = _hbase27_no_door_review(results, case_id)
        if no_door_status is not None:
            row["report_status"] = no_door_status
            row["source_review_status"] = no_door_status
            row["source_review_receipt"] = no_door_receipt
            if no_door_status.startswith("invalid_"):
                row["source_gap_error"] = "healthy no-door receipt or pinned evidence mismatch"
            return row
        environment_status, environment_receipt = _hbase34_environment_repair(
            results, case_id)
        if environment_status is not None:
            row["report_status"] = environment_status
            row["source_review_status"] = "true_cluster_junit_setup_blocked"
            row["source_review_receipt"] = environment_receipt
            row["source_gap_receipt"] = environment_receipt
            row["source_review_classification"] = "MiniKdc_dependency_failure_before_junit"
            if environment_status.startswith("invalid_"):
                row["source_gap_error"] = "HBASE-34 source or calibration evidence mismatch"
            return row
        hbase34_status, hbase34_receipt, hbase34_selector = _hbase34_cluster_stage(results, case_id)
        if hbase34_status is not None:
            row["report_status"] = hbase34_status
            row["source_review_status"] = "prior_skip_contradicted_guard_reached"
            row["source_review_receipt"] = hbase34_receipt
            row["source_gap_receipt"] = hbase34_receipt
            if hbase34_selector is not None:
                row["inventory_cluster_test"] = row["cluster_test"]
                row["cluster_test"] = hbase34_selector
                row["source_review_classification"] = "alternate_passing_existing_cluster_junit_staged"
            else:
                row["source_gap_error"] = "alternate token JUnit stage or pinned archive mismatch"
            return row
        staged_status, staged_receipt = _hbase37_cluster_stage(results, case_id)
        if staged_status is not None:
            row["report_status"] = staged_status
            row["source_review_status"] = "prior_healthy_exact_target_actor_unknown"
            row["source_review_receipt"] = staged_receipt
            row["source_gap_receipt"] = staged_receipt
            return row
        zk06_status, zk06_receipt = _zk06_retry_guard_gap(results, case_id)
        if zk06_status is not None:
            row["report_status"] = zk06_status
            row["fault_model_receipt"] = zk06_receipt
            return row
        source_status, source_receipt = _solr38_39_source_gap(results, case_id)
        if source_status is not None:
            row["report_status"] = source_status
            row["fault_model_receipt"] = source_receipt
            return row
        v40p_status, v40p_receipt = _solr18_v40p_fault_gap(results, case_id)
        if v40p_status is not None:
            row["report_status"] = v40p_status
            row["fault_model_receipt"] = v40p_receipt
            return row
        for review in (_hbase37_source_fault_gap,
                       _hdfs48_target_retention_gap,
                       _zk10_packet_fault_gap):
            model_status, model_receipt = review(results, case_id)
            if model_status is not None:
                row["report_status"] = model_status
                row["fault_model_receipt"] = model_receipt
                return row
        epoch_status, epoch_receipt = _zk05_epoch_influence_gap(results, case_id)
        if epoch_status is not None:
            row["report_status"] = epoch_status
            row["fault_model_receipt"] = epoch_receipt
            return row
        scope_status, scope_receipt = _solr18_scope_gap(results, case_id)
        if scope_status is not None:
            row["report_status"] = scope_status
            row["fault_model_receipt"] = scope_receipt
            return row
        zxid_status, zxid_receipt = _zk04_zxid_influence_gap(results, case_id)
        if zxid_status is not None:
            row["report_status"] = zxid_status
            row["fault_model_receipt"] = zxid_receipt
            return row
        no_path_status, no_path_receipt = _fault_model_no_target_path(results, case_id)
        if no_path_status is not None:
            row["report_status"] = no_path_status
            row["fault_model_receipt"] = no_path_receipt
            source_status, source_receipt = _solr37_retry_source_review(results, case_id)
            if source_status == "source_review_no_configured_retry":
                row["supplementary_fault_model_status"] = source_status
                row["source_review_receipt"] = source_receipt
                row["source_gap_receipt"] = source_receipt
            elif source_status is not None:
                row["source_gap_error"] = "retry source review or evidence mismatch"
            return row
        model_status, model_receipt = _fault_model_target_lost(results, case_id)
        if model_status is not None:
            row["report_status"] = model_status
            row["fault_model_receipt"] = model_receipt
            return row
        target_status = _healthy_target_unreliable(results, case_id)
        if target_status == "healthy_target_unreliable":
            row["report_status"] = target_status
            row["source_gap_receipt"] = str(
                results / "target_unreliable" / case_id / "receipt.json")
            return row
        if target_status == "invalid_target_unreliable":
            row["source_gap_error"] = "target-unreliable receipt or evidence mismatch"
            return row
        source_gap = _source_gap(results, case_id, calibration)
        if source_gap in {"no_suitable_cluster_test",
                          "source_review_no_suitable_test"}:
            row["report_status"] = source_gap
            row["source_gap_receipt"] = str(results / "source_gaps" / case_id / "receipt.json")
            row["skipped_no_suitable_cluster_test"] = True
            if case_id in {"HDFS-31", "HDFS-32", "HDFS-33"}:
                row["source_review_status"] = "existing_junit_reaches_target"
                row["source_review_classification"] = {
                    "HDFS-31": (
                        "no_existing_junit_and_pinned_typed_io_fault_model_"
                        "changes_dn0_block_pool_map_while_retaining_target"),
                    "HDFS-32": (
                        "no_existing_junit_and_pinned_typed_io_fault_model_"
                        "changes_bpid2_mapping_while_retaining_target"),
                    "HDFS-33": (
                        "no_existing_junit_and_pinned_typed_io_fault_model_"
                        "combines_retained_builder_with_same_bpid_map_removal"),
                }[case_id]
        elif source_gap == "invalid_source_gap":
            row["source_gap_error"] = "source-gap receipt or healthy evidence mismatch"
        if source_gap is None:
            source_weak = _source_weak_candidate(results, case_id)
            if source_weak == "source_weak_candidate":
                row["report_status"] = source_weak
                row["source_gap_receipt"] = str(
                    results / "source_weak" / case_id / "receipt-v1.json")
            elif source_weak == "invalid_source_weak":
                row["source_gap_error"] = "source-weak receipt or evidence mismatch"
        existing_junit, review_receipt = _hbase19_20_existing_junit_review(results, case_id)
        if existing_junit == "healthy_exact_guard_observed":
            row["report_status"] = existing_junit
            row["source_review_status"] = existing_junit
            row["source_review_classification"] = "remote_modify_rpc_selector_unproven"
            row["source_review_receipt"] = review_receipt
            row["source_gap_receipt"] = review_receipt
            row["skipped_no_suitable_cluster_test"] = False
        elif existing_junit == "invalid_existing_junit_review":
            row["report_status"] = existing_junit
            row["source_gap_error"] = "superseding exact-JUnit review or pinned evidence mismatch"
        return row
    if result.get("case_id") != case_id:
        row["report_status"] = "invalid_result"
        row["result_error"] = "case_id mismatch"
        return row
    status = result.get("status")
    if not isinstance(status, str):
        row["report_status"] = "invalid_result"
        row["result_error"] = "missing campaign status"
        return row
    row["campaign_status"] = status
    row["campaign_cluster_test"] = result.get("cluster_test")
    row["quality_status"] = _quality(result)
    row["causal_audit"] = _causal_audit(result_path, result)
    audit = _json(result_path.with_name("offline-causal-audit.json")) or {}
    if row["causal_audit"] == "invalid" and case_id == "ZOOKEEPER-13":
        legacy_review = _zk13_legacy_integrity_review(results, result_path, result, audit)
        if legacy_review == "legacy_integrity_verified_path_unclassified":
            row["causal_audit"] = legacy_review
            row["causal_precision_review"] = legacy_review
            row["causal_precision_receipt"] = str(result_path.with_name("terminal-seal.json"))
    if audit.get("local_timeline_only") is True:
        row["local_timeline_only"] = True
        row["same_actor_target_trials"] = audit.get("same_actor_target_trials")
    if row["causal_audit"] == "verified":
        row["healthy_closure_evidence_types"] = (
            audit.get("healthy_closure_evidence_types") or
            (["observed_graph_path"] if audit.get("healthy_observed_path_doors", 0) > 0 else []))
        row["healthy_local_timeline_doors"] = audit.get("healthy_local_timeline_doors", 0)
    row["posthoc_attestation"] = _posthoc_attestation(result_path, case, result)
    if (row["quality_status"] == "runtime_attestation_unproven" and
            row["posthoc_attestation"] == "verified" and
            isinstance(result.get("strict_target_trials"), int) and
            result["strict_target_trials"] > 0):
        row["quality_status"] = "target_exercised_posthoc"
    if row["quality_status"] in {"target_exercised", "target_exercised_posthoc"}:
        if case_id == "SOLR-10":
            row["static_causal_audit"] = row["causal_audit"]
            precision, receipt = _solr10_role_event_review(results, result_path, result)
            row["causal_precision_review"] = precision
            row["causal_precision_receipt"] = receipt
            if precision == "observed_event_path":
                row["causal_audit"] = "role_aware_verified"
                row["quality_status"] = precision
            else:
                row["quality_status"] = "causal_precision_review_invalid"
        elif case_id == "SOLR-01":
            row["static_causal_audit"] = row["causal_audit"]
            precision, receipt = _solr01_recovery_review(results, result_path, result)
            row["causal_precision_review"] = precision
            row["causal_precision_receipt"] = receipt
            if precision == "observed_local_timeline":
                row["causal_audit"] = "recovery_path_verified"
                row["quality_status"] = precision
            elif precision == "faulted_path_unverified":
                row["quality_status"] = precision
            elif precision == "invalid":
                row["quality_status"] = "causal_precision_review_invalid"
            else:
                row["quality_status"] = "causal_precision_pending"
        elif case_id == "SOLR-18":
            row["static_causal_audit"] = row["causal_audit"]
            precision, receipt = _solr18_badversion_recovery_review(
                results, result_path, result)
            row["causal_precision_review"] = precision
            row["causal_precision_receipt"] = receipt
            if precision == "observed_event_path":
                row["causal_audit"] = "recovery_graph_path_verified"
                row["quality_status"] = precision
            elif precision == "invalid":
                row["quality_status"] = "causal_precision_review_invalid"
            else:
                row["quality_status"] = "causal_precision_pending"
        elif row["causal_audit"] is None:
            row["quality_status"] = "causal_audit_unproven"
        elif row["causal_audit"] == "legacy_integrity_verified_path_unclassified":
            row["quality_status"] = "causal_path_unclassified"
        elif (case_id == "SOLR-13" and row["causal_audit"] == "invalid"
              and audit.get("archive_integrity_valid") is True
              and audit.get("applied_fault_identity_valid") is True
              and audit.get("target_claims_reverified") is True
              and audit.get("guidance_consistent") is True
              and audit.get("healthy_closure_proven") is False
              and audit.get("healthy_observed_path_doors") == 0
              and (_json(result_path.with_name("terminal-quality.json")) or {}).get(
                  "offline_audit_sha256") == hashlib.sha256(
                      result_path.with_name("offline-causal-audit.json").read_bytes()).hexdigest()):
            row["quality_status"] = "causal_path_unverified"
            row["causal_precision_review"] = "faulted_path_unverified"
            row["causal_precision_receipt"] = str(result_path.with_name("terminal-quality.json"))
        elif (case_id == "SOLR-14" and row["causal_audit"] == "invalid"
              and audit.get("archive_integrity_valid") is True
              and audit.get("applied_fault_identity_valid") is True
              and audit.get("target_claims_reverified") is True
              and audit.get("guidance_consistent") is True
              and audit.get("healthy_closure_proven") is True
              and audit.get("same_actor_target_required") is True
              and audit.get("same_actor_target_gate_passed") is False
              and (_json(result_path.with_name("terminal-quality.json")) or {}).get(
                  "classification") == "postfault_same_actor_unverified"
              and (_json(result_path.with_name("terminal-quality.json")) or {}).get(
                  "campaign_result_sha256") == hashlib.sha256(result_path.read_bytes()).hexdigest()
              and (_json(result_path.with_name("terminal-quality.json")) or {}).get(
                  "offline_audit_sha256") == hashlib.sha256(
                      result_path.with_name("offline-causal-audit.json").read_bytes()).hexdigest()):
            row["quality_status"] = "postfault_same_actor_unverified"
            row["causal_precision_review"] = "postfault_same_actor_unverified"
            row["causal_precision_receipt"] = str(result_path.with_name("terminal-quality.json"))
        elif row["causal_audit"] != "verified":
            row["quality_status"] = "causal_audit_invalid"
        else:
            precision, receipt = _hdfs24_retry_review(results, result_path, result)
            if precision is None:
                precision, receipt = _hbase07_client_event_review(results, result_path, result)
            if precision is None:
                precision, receipt = _causal_precision_review(results, result_path, result)
            row["causal_precision_review"] = precision
            row["causal_precision_receipt"] = receipt
            if precision in {"causal_precision_unverified", "observed_event_path"}:
                row["quality_status"] = precision
            elif precision == "invalid":
                row["quality_status"] = "causal_precision_review_invalid"
            else:
                precision, receipt = _faulted_path_review(results, result_path, result)
                if precision is None:
                    precision, receipt = _event_path_review(results, result_path, result)
                if precision is None:
                    precision, receipt = _hdfs11_faulted_event_review(results, result_path, result)
                if precision is None:
                    precision, receipt = _zk12_filenotfound_review(results, result_path, result)
                if precision is None:
                    precision, receipt = _local_timeline_review(results, result_path, result)
                row["causal_precision_review"] = precision
                row["causal_precision_receipt"] = receipt
                if precision in {"observed_local_timeline", "observed_event_path",
                                 "faulted_path_unverified"}:
                    row["quality_status"] = precision
                elif precision == "invalid":
                    row["quality_status"] = "causal_precision_review_invalid"
                else:
                    row["quality_status"] = "causal_precision_pending"
    if status in TERMINAL:
        row["report_status"] = "completed_campaign"
    elif status.startswith("healthy_"):
        row["report_status"] = "seed_invalid"
    else:
        row["report_status"] = "in_progress"
    for key in ("duration_seconds", "fault_trials_completed",
                "strict_injected_trials", "strict_target_trials",
                "target_reached_trials", "exact_exception_trials",
                "coverage_ids_seen", "closure_coverage_ids_seen",
                "closure_edge_fingerprints_seen", "target_node_named",
                "source_review_status", "new_bug"):
        row[key] = result.get(key)
    depth_review, depth_path = _fault_depth_review(results, result_path, result)
    if depth_review is not None:
        row["fault_depth_distribution"] = depth_review["depth_distribution"]
        row["controller_release_id"] = depth_review["controller_release_id"]
        row["controller_scheduler_sha256"] = depth_review["scheduler_sha256"]
        row["controller_scheduler_policy_commit"] = depth_review["scheduler_policy_commit"]
        row["fault_depth_review_receipt"] = depth_path
    elif depth_path is not None:
        row["fault_depth_review_error"] = "depth review or raw SHA index mismatch"
    review = _source_review(results, result_path, result)
    if review is not None:
        row["source_review_status"] = review["status"]
        row["new_bug"] = review["new_bug"]
        row["source_review_receipt"] = review.get("receipt_path")
        row["source_review_classification"] = review.get("classification")
        if "error" in review:
            row["source_review_error"] = review["error"]
    if row["new_bug"] is True and row["source_review_status"] != "confirmed_new_bug":
        row["report_status"] = "invalid_result"
        row["quality_status"] = None
        row["result_error"] = "new bug mark requires source review confirmation"
    bounded, bounded_receipt = _solr22_dynamic_bounded_gap(results, case_id)
    if bounded is not None:
        row["supplementary_fault_model_status"] = bounded
        if bounded == "bounded_fault_model_gap_verified":
            row["fault_model_receipt"] = bounded_receipt
        else:
            row["source_gap_error"] = "bounded fault-model receipt or raw evidence mismatch"
    if case_id == "HBASE-02":
        precision, receipt = _hbase02_offhost_review(results, result_path, result)
        row["causal_precision_review"] = precision
        row["causal_precision_receipt"] = receipt
        if precision == "faulted_path_unverified":
            row["quality_status"] = precision
        else:
            row["report_status"] = "invalid_result"
            row["quality_status"] = None
            row["result_error"] = "HBASE-02 offhost archive or negative review mismatch"
    if case_id == "HBASE-12":
        precision, receipt = _hbase12_legacy_review(results, result_path, result)
        row["causal_precision_review"] = precision
        row["causal_precision_receipt"] = receipt
        if precision == "expected_exception_oracle_confounded":
            row["quality_status"] = precision
            row["source_review_classification"] = precision
            row["source_review_receipt"] = str(result_path.with_name(
                "legacy-preservation-receipt.json"))
        else:
            row["report_status"] = "invalid_result"
            row["quality_status"] = None
            row["result_error"] = "HBASE-12 archive or expected-exception review mismatch"
    if case_id == "SOLR-38":
        corrected, corrected_receipt = _solr38_corrected_audit(results, result_path, result)
        if corrected == "verified_corrected_offline":
            row["original_causal_audit"] = row["causal_audit"]
            row["causal_audit"] = corrected
            row["causal_precision_review"] = "observed_event_path"
            row["causal_precision_receipt"] = corrected_receipt
            row["quality_status"] = "observed_event_path_corrected_offline"
            row["source_review_status"] = "source_reviewed_no_new_bug"
            row["source_review_classification"] = "postfault_guard_fallthrough"
            row["new_bug"] = False
        else:
            row["report_status"] = "invalid_result"
            row["quality_status"] = None
            row["result_error"] = "SOLR-38 sealed offline correction or import receipt mismatch"
    if case_id == "SOLR-39":
        completed, completed_receipt = _solr39_offline_completion(results, result_path, result)
        if completed == "verified_sealed_queue_exhaustion":
            row["inventory_cluster_test"] = row["cluster_test"]
            row["cluster_test"] = result["cluster_test"]
            row["causal_audit"] = completed
            row["causal_precision_review"] = "observed_prior_reference_path"
            row["causal_precision_receipt"] = completed_receipt
            row["quality_status"] = "one_bound_actor_retained_two_bound_actor_lost"
            row["same_actor_target_trials"] = 1
            row["fault_depth_distribution"] = {"1": 3}
            row["fault_depth_review_receipt"] = str(result_path.with_name(
                "fault-depth-review.json"))
            row.pop("fault_depth_review_error", None)
            row["source_review_status"] = "no_exact_target_throw_observed"
            row["source_review_classification"] = "no_exact_throw_one_prior_reference_path"
            row["new_bug"] = False
        else:
            row["report_status"] = "invalid_result"
            row["quality_status"] = None
            row["result_error"] = "SOLR-39 sealed queue, prior-reference audit, or import receipt mismatch"
    if case_id == "HDFS-48":
        checked, checked_receipt = _hdfs48_case_audit(results, result_path, result)
        if checked == "verified_case_local":
            row["original_causal_audit"] = row["causal_audit"]
            row["causal_audit"] = checked
            row["causal_precision_review"] = "observed_event_path"
            row["causal_precision_receipt"] = checked_receipt
            row["quality_status"] = "observed_rpc_retry_path_with_invalid_depth3"
            row["same_actor_target_trials"] = 2
            row["source_review_classification"] = "no_exact_throw_one_invalid_postfault_retry"
            row["new_bug"] = False
        else:
            row["report_status"] = "invalid_result"
            row["quality_status"] = None
            row["result_error"] = "HDFS-48 case-local path audit or archive mismatch"
    if case_id == "SOLR-34":
        quality, quality_receipt = _solr34_bootstrap_quality(results, result_path, result)
        if quality == "verified_target_absent_budget":
            row["quality_status"] = "bounded_budget_target_not_activated"
            row["causal_precision_review"] = "target_absent_after_fault"
            row["causal_precision_receipt"] = quality_receipt
            row["source_review_classification"] = "eleven_attributed_one_partial_zero_target_checks"
            row["new_bug"] = False
        else:
            row["report_status"] = "invalid_result"
            row["quality_status"] = None
            row["result_error"] = "SOLR-34 target-absent bootstrap seal or quality mismatch"
    if case_id == "SOLR-15":
        quality, quality_receipt = _solr15_continuation_quality(results, result_path, result)
        if quality == "verified_expected_guard_bounded_budget":
            row["quality_status"] = "bounded_budget_four_guard_trials_seven_uncredited"
            row["causal_precision_review"] = "resource_qualified_guard_trials"
            row["causal_precision_receipt"] = quality_receipt
            row["source_review_status"] = "expected_guard"
            row["source_review_receipt"] = quality_receipt
            row["source_review_classification"] = "protective_leader_live_znode_guard"
            row["same_actor_target_trials"] = 4
            row["new_bug"] = False
        else:
            row["report_status"] = "invalid_result"
            row["quality_status"] = None
            row["result_error"] = "SOLR-15 continuation seal, resource audit, or source review mismatch"
    return row


def build(inventory_path: Path, results: Path) -> dict[str, Any]:
    inventory = _json(inventory_path)
    if inventory is None:
        raise FileNotFoundError(inventory_path)
    cases = inventory["cases"]
    controls = inventory.get("known_issue_controls", [])
    if len(cases) != 102 or len({case["case_id"] for case in cases}) != 102:
        raise ValueError("inventory must contain 102 unique original checks")
    rows = [_row(case, results) for case in cases]
    control_rows = [_row(case, results) for case in controls]
    for row in rows:
        source_gap_skip = (row["report_status"] in {
            "source_review_no_suitable_test", "no_suitable_cluster_test"}
            and bool(row["source_gap_receipt"]) and not row.get("source_gap_error"))
        mapped_test_skip = (row["report_status"] == "no_mapped_cluster_test"
            and row["source_review_status"] == "source_review_no_mapped_cluster_test"
            and bool(row["source_review_receipt"]) and not row.get("source_gap_error"))
        row["skipped_no_suitable_cluster_test"] = bool(source_gap_skip or mapped_test_skip)
    status_counts = Counter(row["report_status"] for row in rows)
    evidence_counts = Counter(row["quality_status"] for row in rows
                              if row["quality_status"] is not None)
    skipped_checks = sum(row["skipped_no_suitable_cluster_test"] for row in rows)
    completed_checks = status_counts["completed_campaign"]
    if completed_checks + skipped_checks > len(rows):
        raise ValueError("completed campaigns and source-proven skips overlap")
    return {
        "schema_version": 2,
        "method": "Mallory",
        "original_selection_count": 102,
        "known_issue_control_count": len(control_rows),
        "counts": dict(status_counts),
        "completed_checks": completed_checks,
        "skipped_no_suitable_cluster_test": skipped_checks,
        "handled_checks": completed_checks + skipped_checks,
        "not_completed_checks": len(rows) - completed_checks,
        "remaining_unhandled_checks": len(rows) - completed_checks - skipped_checks,
        "calibration_counts": dict(Counter(row["calibration_status"] for row in rows
                                           if row["calibration_status"] is not None)),
        "evidence_counts": dict(evidence_counts),
        "rows": rows,
        "known_issue_controls": control_rows,
    }


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def markdown(report: dict[str, Any]) -> str:
    lines = ["# Mallory check results", "",
             f'{report["completed_checks"]} of 102 original checks have completed '
             f'a fault-injection campaign; {report["not_completed_checks"]} have not. '
             'Completion means the campaign ended at its configured budget or '
             'exhausted its fault queue. Fault-to-target evidence and selected '
             'exceptions are recorded as outcomes, not extra completion gates. '
             f'{report["skipped_no_suitable_cluster_test"]} checks have a '
             'source-proven no-suitable-cluster-test skip; '
             f'{report["handled_checks"]} are handled in total and '
             f'{report["remaining_unhandled_checks"]} remain unhandled.', "",
             "Rows are generated from `Mallory/cases/inventory.json` and "
             "`data/mallory/cases/<ID>/result.json`. Pending rows are not run results. "
             "`source_review_no_suitable_test` records a hash-checked source review, "
             "not a healthy-run causal audit. "
             "`source_weak_candidate` records a hash-checked source finding "
             "with an undemonstrated fault relation, and "
             "`pending_fault_discovery_bootstrap` records passing cluster "
             "JUnits whose exact selected guard is absent in healthy traces; "
             "fault-discovery admission and a full campaign remain pending. "
             "`skipped_no_suitable_cluster_test` is true only for a verified "
             "source review with no suitable existing cluster JUnit; a staged "
             "but unrun bootstrap is pending, not skipped. "
             "`healthy_exact_guard_observed` records a passing existing JUnit "
             "that reached the exact nonthrowing HBASE-19/20 guard, with no "
             "observed pretarget graph-path door or completed fault campaign. "
             "`healthy_target_unreliable` records repeated healthy target misses "
             "despite an earlier hit. "
             "`Target after fault (generic)` can count "
             "another actor. `fault_model_target_lost` records a SHA-checked "
             "healthy seed and effective bounded fault whose affected target disappeared; "
             "it is not a completed campaign. `fault_model_no_target_path` records "
             "a SHA-checked bounded pilot with retained checks but no observed "
             "fault-to-target path; it is also not a completed campaign. "
             "`fault_model_zxid_influence_unproven` means the existing ZK04 "
             "cluster JUnit reaches the guard, but current I/O exception evidence "
             "does not show a target-preserving change to either zxid operand; "
             "it is neither an impossibility claim nor a completed campaign. "
             "`fault_model_epoch_influence_unproven` means the existing ZK05 "
             "six-fault pilot has no same-occurrence or observed fault-to-target "
             "continuation and source review identifies no current "
             "target-retaining acceptedEpoch-changing fault; it is not a "
             "completed campaign. "
             "HBASE37 `pending_seed` records a newer staged LocalHBaseCluster "
             "workload; its prior exact target had unknown actor identity and "
             "the new typed door still needs a fresh healthy run. "
             "HBASE34 `pending_environment_repair` records a real "
             "LocalHBaseCluster JUnit blocked during MiniKdc setup before any "
             "test or target event; a pinned classpath repair awaits a fresh "
             "healthy run. "
             "ZOOKEEPER13 `legacy_integrity_verified_path_unclassified` means "
             "its older audit verifies archive and fault identities but does not "
             "contain the later graph-path fields. "
             "`fault_model_no_target_retaining_pretarget_door` records ten "
             "effective HDFS48 faults that all lose the named target. "
             "`fault_model_packet_io_no_target_retention` records that ZK10 "
             "healthy packet doors are caught by connection-ending handlers, "
             "without a target-retaining fault trial. "
             "Local timeline evidence requires a same-actor, "
             "same-epoch, same-occurrence target check after an admitted fault door. "
             "A SHA-bound faulted-path review supports the reported path evidence. "
             "`observed_local_timeline` means an ordered same-region continuation "
             "in a legacy trace, not an inter-region path. Terminal runs without "
             "a positive path review remain completed; their path evidence stays "
             "unverified.", "",
             "| ID | System | Exact check | Function | Check code | Inventory cluster test | Calibrated cluster test | Campaign cluster test | Calibration | Cal. time (s) | Status | Source-proven skip | Fault-to-target evidence | Causal audit | Precision review | Closure evidence | Local doors | Posthoc audit | Campaign time (s) | Strict injected trials | Target after fault (generic) | Same actor target after fault | Exact exceptions | Coverage IDs | Closure edges | Source review | Source disposition receipt | New bug |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |"]
    for row in report["rows"]:
        location = f'{row["source_path"]}:{row["source_line"]}'
        source_receipts = row["source_gap_receipt"]
        if (row["source_review_status"] in {"source_audit_verified_pending",
                                               "source_review_no_suitable_test"}
                and row["source_review_receipt"]):
            source_receipts = ", ".join(
                value for value in (source_receipts, row["source_review_receipt"]) if value)
        values = [row["case_id"], row["system"], location, row["function"],
                  row["check_code"],
                  row["cluster_test"], row["calibration_cluster_test"],
                  row["campaign_cluster_test"], row["calibration_status"],
                  row["calibration_duration_seconds"], row["report_status"],
                  row["skipped_no_suitable_cluster_test"],
                  row["quality_status"], row["causal_audit"],
                  row["causal_precision_review"],
                  ", ".join(row["healthy_closure_evidence_types"] or []),
                  row["healthy_local_timeline_doors"], row["posthoc_attestation"],
                  row["duration_seconds"], row["strict_injected_trials"],
                  row["strict_target_trials"], row["same_actor_target_trials"],
                  row["exact_exception_trials"],
                  row["coverage_ids_seen"], row["closure_edge_fingerprints_seen"],
                  row["source_review_status"], source_receipts,
                  row["new_bug"]]
        lines.append("| " + " | ".join(_cell(value) for value in values) + " |")
    if report["known_issue_controls"]:
        lines += ["", "## Known issue controls", ""]
        for row in report["known_issue_controls"]:
            lines.append(f'- {row["case_id"]}: {row["report_status"]}')
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path,
                        default=Path("Mallory/cases/inventory.json"))
    parser.add_argument("--results", type=Path, default=Path("data/mallory"))
    args = parser.parse_args()
    report = build(args.inventory, args.results)
    _atomic(args.results / "checklist102.json", json.dumps(report, indent=2) + "\n")
    _atomic(args.results / "checklist102.md", markdown(report))
    print(json.dumps(report["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
