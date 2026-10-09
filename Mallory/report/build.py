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


def _causal_precision_review(results: Path, result_path: Path,
                             result: dict[str, Any]) -> tuple[str | None, str | None]:
    """Bind a superseding causal precision review to unchanged campaign evidence.

    The review can lower a quality claim; it cannot promote a campaign.  A
    listed but damaged review fails closed so a stale or truncated sidecar
    cannot silently restore the old high-quality classification.
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
    is never a positive proof. Unreviewed terminal runs remain pending.
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
    except (OSError, KeyError, TypeError, ValueError, subprocess.CalledProcessError):
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
        "new_bug": None,
    }
    if result is None:
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
        if row["causal_audit"] is None:
            row["quality_status"] = "causal_audit_unproven"
        elif row["causal_audit"] != "verified":
            row["quality_status"] = "causal_audit_invalid"
        else:
            precision, receipt = _causal_precision_review(results, result_path, result)
            row["causal_precision_review"] = precision
            row["causal_precision_receipt"] = receipt
            if precision == "causal_precision_unverified":
                row["quality_status"] = precision
            elif precision == "invalid":
                row["quality_status"] = "causal_precision_review_invalid"
            else:
                precision, receipt = _faulted_path_review(results, result_path, result)
                if precision is None:
                    precision, receipt = _event_path_review(results, result_path, result)
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
    quality_counts = Counter(row["quality_status"] for row in rows
                             if row["quality_status"] is not None)
    return {
        "schema_version": 1,
        "method": "Mallory",
        "original_selection_count": 102,
        "known_issue_control_count": len(control_rows),
        "counts": dict(Counter(row["report_status"] for row in rows)),
        "calibration_counts": dict(Counter(row["calibration_status"] for row in rows
                                           if row["calibration_status"] is not None)),
        "quality_counts": dict(quality_counts),
        "high_quality_completed": (quality_counts["observed_local_timeline"] +
                                   quality_counts["observed_event_path"]),
        "rows": rows,
        "known_issue_controls": control_rows,
    }


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def markdown(report: dict[str, Any]) -> str:
    lines = ["# Mallory check results", "",
             f'{report["high_quality_completed"]} of 102 original checks have verified '
             'fault-to-target continuation. '
             f'{report["counts"].get("completed_campaign", 0)} campaigns are terminal; '
             'a terminal campaign may still fail a quality gate.', "",
             "Rows are generated from `Mallory/cases/inventory.json` and "
             "`data/mallory/cases/<ID>/result.json`. Pending rows are not run results. "
             "`source_review_no_suitable_test` records a hash-checked source review, "
             "not a healthy-run causal audit. "
             "`source_weak_candidate` records a hash-checked source finding "
             "with an undemonstrated fault relation, and "
             "`healthy_target_unreliable` records repeated healthy target misses "
             "despite an earlier hit. "
             "`Target after fault (generic)` can count "
             "another actor. `fault_model_target_lost` records a SHA-checked "
             "healthy seed and effective bounded fault whose affected target disappeared; "
             "it is not a completed campaign. "
             "Local-timeline-only quality also requires a same-actor, "
             "same-epoch, same-occurrence target check after an admitted fault door. "
             "A SHA-bound faulted-path review is required for high-quality status. "
             "`observed_local_timeline` means an ordered same-region continuation "
             "in a legacy trace, not an inter-region path. Terminal runs without a "
             "positive review remain pending; unsupported paths retain their raw "
             "results under an unverified label.", "",
             "| ID | System | Exact check | Function | Check code | Inventory cluster test | Calibrated cluster test | Campaign cluster test | Calibration | Cal. time (s) | Status | Quality | Causal audit | Precision review | Closure evidence | Local doors | Posthoc audit | Campaign time (s) | Strict injected trials | Target after fault (generic) | Same actor target after fault | Exact exceptions | Coverage IDs | Closure edges | Source review | Source disposition receipt | New bug |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |"]
    for row in report["rows"]:
        location = f'{row["source_path"]}:{row["source_line"]}'
        values = [row["case_id"], row["system"], location, row["function"],
                  row["check_code"],
                  row["cluster_test"], row["calibration_cluster_test"],
                  row["campaign_cluster_test"], row["calibration_status"],
                  row["calibration_duration_seconds"], row["report_status"],
                  row["quality_status"], row["causal_audit"],
                  row["causal_precision_review"],
                  ", ".join(row["healthy_closure_evidence_types"] or []),
                  row["healthy_local_timeline_doors"], row["posthoc_attestation"],
                  row["duration_seconds"], row["strict_injected_trials"],
                  row["strict_target_trials"], row["same_actor_target_trials"],
                  row["exact_exception_trials"],
                  row["coverage_ids_seen"], row["closure_edge_fingerprints_seen"],
                  row["source_review_status"], row["source_gap_receipt"],
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
