"""Promote a healthy calibration to a pinned fault-campaign configuration.

Promotion never infers a bug.  It only attests that the healthy run reached the
exact woven target on one named node and exposed a usable fault frontier.
"""

from __future__ import annotations

import json
import gzip
import hashlib
from pathlib import Path
import re

try:
    from .verify_sources import (case_expected_files, sha256_file,
                                 verify_from_reference)
    from .worker import atomic_json
except ImportError:
    from verify_sources import case_expected_files, sha256_file, verify_from_reference
    from worker import atomic_json


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _verified_log(trial_dir: Path, trial: dict, stream: str) -> str:
    receipt = trial.get(f"{stream}_evidence") or {}
    if not isinstance(receipt, dict):
        raise ValueError(f"healthy {stream} evidence receipt is missing")
    name = receipt.get("gzip_path") or receipt.get("raw_path")
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError(f"healthy {stream} evidence path is invalid")
    path = trial_dir / name
    payload = path.read_bytes()
    if receipt.get("gzip_path"):
        if hashlib.sha256(payload).hexdigest() != receipt.get("gzip_sha256"):
            raise ValueError(f"healthy {stream} compressed evidence hash differs")
        payload = gzip.decompress(payload)
    if (hashlib.sha256(payload).hexdigest() != trial.get(f"{stream}_sha256") or
            hashlib.sha256(payload).hexdigest() != receipt.get("raw_sha256") or
            (receipt.get("raw_bytes") is not None and len(payload) != receipt["raw_bytes"])):
        raise ValueError(f"healthy {stream} evidence hash differs")
    return payload.decode("utf-8", errors="replace")


def _test_attestation(system: str, trial_dir: Path, trial: dict,
                      case_id: str) -> dict:
    """Read a positive, passing JUnit count from the hash-bound runner log."""
    if trial.get("return_code") != 0 or trial.get("timed_out"):
        raise ValueError("healthy JUnit did not exit successfully")
    if system in ("hdfs", "zookeeper"):
        log = _verified_log(trial_dir, trial, "stdout")
        matches = re.findall(
            r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
            log)
        if (not matches or not any(int(run) > int(skipped) for run, _, _, skipped in matches)
                or any(int(failures) or int(errors) for _, failures, errors, _ in matches)
                or "BUILD SUCCESS" not in log):
            raise ValueError("healthy Surefire has no passing selected JUnit test")
        return {"runner": "surefire", "tests_run": max(int(row[0]) for row in matches),
                "log_sha256": trial["stdout_sha256"]}
    if system == "hbase":
        log = _verified_log(trial_dir, trial, "stderr")
        matches = re.findall(r"MALLORY_JUNIT found=(\d+) succeeded=(\d+) failed=(\d+)", log)
        if len(matches) != 1 or int(matches[0][1]) <= 0 or int(matches[0][2]):
            raise ValueError("healthy HBase JUnit did not run a passing test")
        found, succeeded, _ = map(int, matches[0])
        if found != succeeded:
            raise ValueError("healthy HBase JUnit count is inconsistent")
        return {"runner": "hbase_direct_junit", "tests_run": found,
                "log_sha256": trial["stderr_sha256"]}
    if system == "solr":
        log = _verified_log(trial_dir, trial, "stdout")
        rows = []
        for line in log.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("case_id") == case_id and "junit" in record:
                rows.append(record)
        if len(rows) != 1 or rows[0].get("exit_code") != 0:
            raise ValueError("healthy Solr JUnit result is missing or ambiguous")
        counts = rows[0]["junit"]
        if (not isinstance(counts, dict) or not isinstance(counts.get("run"), int)
                or counts["run"] <= 0 or counts.get("failures") != 0
                or counts.get("ignored", 0) >= counts["run"]):
            raise ValueError("healthy Solr JUnit did not run a passing test")
        return {"runner": "solr_direct_junit", "tests_run": counts["run"],
                "log_sha256": trial["stdout_sha256"]}
    raise ValueError(f"unsupported system JUnit runner: {system}")


def _calibration_causal_audit(calibration: Path, summary: dict) -> dict:
    """Require a fixed-core replay of the healthy frontier before mutation."""
    artifact = _read(calibration / "offline-causal-audit.json")
    from Mallory.core import audit as audit_module
    core_dir = Path(audit_module.__file__).parent
    current_core = {name: sha256_file(core_dir / name)
                    for name in ("audit.py", "events.py", "graph.py", "feedback.py", "campaign.py")}
    if (artifact.get("schema_version") != 1
            or artifact.get("audit_kind") != "offline_causal_quality"
            or artifact.get("case_id") != summary.get("case_id")
            or artifact.get("terminal_status") != "calibration_complete"
            or artifact.get("campaign_result_sha256") != sha256_file(calibration / "result.json")
            or artifact.get("core_source_sha256") != current_core
            or artifact.get("trial_count") != 1
            or artifact.get("archive_integrity_valid") is not True
            or artifact.get("guidance_consistent") is not True
            or artifact.get("report_gate_passed") is not True):
        raise ValueError("fixed-core healthy causal audit is missing or failed")
    return {"path": str(calibration / "offline-causal-audit.json"),
            "sha256": sha256_file(calibration / "offline-causal-audit.json"),
            "core_source_sha256": current_core}


def _normalized_receipt_paths(config: dict) -> dict:
    copy = json.loads(json.dumps(config))
    mapping = copy.get("mapping", {})
    if mapping.get("verified_healthy_probe"):
        mapping["verified_healthy_probe"] = str(Path(mapping["verified_healthy_probe"]).resolve())
    audit = copy.get("calibration_attestation", {}).get("healthy_causal_audit", {})
    if audit.get("path"):
        audit["path"] = str(Path(audit["path"]).resolve())
    return copy


def promote(config_path: Path, calibration: Path, output: Path, row: dict,
            reference: dict) -> Path:
    config = _read(config_path)
    case_id = row["case_id"]
    if config.get("case_id") != case_id or config.get("system") != row["system"]:
        raise ValueError("calibration config differs from case inventory")
    original = _read(calibration / "config.json")
    if original != config:
        raise ValueError("calibration used a different configuration")
    summary = _read(calibration / "result.json")
    trial = _read(calibration / "trials/r0000/result.json")
    if (summary.get("case_id") != case_id or summary.get("status") != "calibration_complete"
            or not summary.get("calibration_only") or not summary.get("healthy_seed_valid")
            or summary.get("fault_trials_completed") != 0
            or trial.get("case_id") != case_id or trial.get("trial_id") != 0
            or trial.get("plan") != []):
        raise ValueError("healthy calibration is incomplete or invalid")
    if summary.get("trials", [{}])[0].get("status") != "observed":
        raise ValueError("healthy trial was not observed")
    causal_audit = _calibration_causal_audit(calibration, summary)
    junit_attestation = _test_attestation(row["system"], calibration / "trials/r0000",
                                          trial, case_id)
    feedback = trial.get("feedback", {})
    binding = summary.get("target_binding") or {}
    named_nodes = set(binding.get("nodes") or
                      ([binding["node"]] if binding.get("node") else []))
    named_nodes.difference_update({None, "unknown", "None", "null", ""})
    observed_nodes = {instance.get("node") for instance in
                      feedback.get("target_instances", [])}
    observed_nodes.difference_update({None, "unknown", "None", "null", ""})
    if (feedback.get("status") != "observed" or not feedback.get("target_reached")
            or feedback.get("target_threw") or feedback.get("target_exception_candidate")
            or not named_nodes or not observed_nodes or not named_nodes <= observed_nodes):
        raise ValueError("healthy target was not reached cleanly on named nodes")
    if (not feedback.get("doors") or feedback.get("eligible_doors_before_target", 0) < 1
            or summary.get("healthy_eligible_doors", 0) < 1):
        raise ValueError("healthy target has no eligible upstream fault door")
    catalog = trial.get("site_catalog_validation", {})
    class_hash = catalog.get("observed_target_class_sha256")
    loaders = catalog.get("target_class_loader_ids")
    if (catalog.get("valid") is not True or catalog.get("reason") != "ok"
            or catalog.get("missing_check_sites") or catalog.get("missing_throw_site")
            or catalog.get("duplicate_target_sites")
            or not isinstance(class_hash, str) or len(class_hash) != 64
            or any(char not in "0123456789abcdef" for char in class_hash)
            or not isinstance(loaders, list) or len(loaders) != 1
            or not trial.get("site_catalog_sha256")
            or sha256_file(calibration / "trials/r0000/sites.jsonl")
            != trial["site_catalog_sha256"]):
        raise ValueError("exact target catalog or loaded-class identity is unverified")
    root = Path(row["provenance"]["source_root"])
    source_root = Path(config.get("source_equivalent_root") or root)
    if config.get("source_equivalent_root"):
        local = {"name": "local", "kind": "local"}
        verdict = verify_from_reference(local, Path(), root,
                                        row["provenance"]["source_commit"],
                                        reference, source_root)
        if not verdict["content_match"]:
            raise ValueError("clean equivalent source differs from pinned inventory")
    for path, expected in case_expected_files(row, config):
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"target/test source hash mismatch: {path}")
    promoted = json.loads(json.dumps(config))
    promoted["calibration_only"] = False
    promoted["auto_promote_if_healthy"] = True
    promoted["expected_target_class_sha256"] = class_hash
    mapping = promoted.setdefault("mapping", {})
    mapping.update({"status": "runtime_attested", "healthy_seed_verified": True,
                    "node_identity_binding_verified": True,
                    "verified_healthy_probe": str(calibration / "trials/r0000/result.json")})
    promoted["calibration_attestation"] = {
        "healthy_result_sha256": sha256_file(calibration / "trials/r0000/result.json"),
        "site_catalog_sha256": trial["site_catalog_sha256"],
        "class_loader_id": loaders[0], "target_nodes": sorted(named_nodes),
        "identity_gaps": summary.get("target_identity_gaps", []),
        "source_reference_digest": reference["roots"][str(root)]["digest"],
        "source_overlay_receipt_sha256": config.get("source_overlay_receipt_sha256"),
        "healthy_junit": junit_attestation,
        "healthy_causal_audit": causal_audit,
    }
    if output.is_file() and _normalized_receipt_paths(_read(output)) != _normalized_receipt_paths(promoted):
        raise ValueError("existing promoted config differs; preserve campaign identity")
    if not output.is_file():
        atomic_json(output, promoted)
    return output
