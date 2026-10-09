"""Build the Mallory checklist from the case inventory and actual run results.

The inventory says what was selected.  Only a result.json written by the
Mallory campaign can say what was run.  Historical CrashFuzz outcomes are
deliberately not imported into this report.
"""

from __future__ import annotations

import argparse
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
            "root_free_door_unmatched"}
    )
    return ("causal_precision_unverified" if valid else "invalid"), receipt_path


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
        "new_bug": None,
    }
    if result is None:
        source_gap = _source_gap(results, case_id, calibration)
        if source_gap in {"no_suitable_cluster_test",
                          "source_review_no_suitable_test"}:
            row["report_status"] = source_gap
            row["source_gap_receipt"] = str(results / "source_gaps" / case_id / "receipt.json")
        elif source_gap == "invalid_source_gap":
            row["source_gap_error"] = "source-gap receipt or healthy evidence mismatch"
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
        "high_quality_completed": (quality_counts["target_exercised"] +
                                   quality_counts["target_exercised_posthoc"]),
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
             'post-fault target exercise. '
             f'{report["counts"].get("completed_campaign", 0)} campaigns are terminal; '
             'a terminal campaign may still fail a quality gate.', "",
             "Rows are generated from `Mallory/cases/inventory.json` and "
             "`data/mallory/cases/<ID>/result.json`. Pending rows are not run results. "
             "`source_review_no_suitable_test` records a hash-checked source review, "
             "not a healthy-run causal audit. `Target after fault (generic)` can count "
             "another actor; local-timeline-only quality also requires a same-actor, "
             "same-epoch, same-occurrence target check after an admitted fault door. "
             "A SHA-bound causal precision review can supersede a previously verified "
             "audit when every apparent path relies on actor-wide root aggregation.", "",
             "| ID | System | Exact check | Function | Check code | Inventory cluster test | Calibrated cluster test | Campaign cluster test | Calibration | Cal. time (s) | Status | Quality | Causal audit | Precision review | Closure evidence | Local doors | Posthoc audit | Campaign time (s) | Strict injected trials | Target after fault (generic) | Same actor target after fault | Exact exceptions | Coverage IDs | Closure edges | Source review | Source gap receipt | New bug |",
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
