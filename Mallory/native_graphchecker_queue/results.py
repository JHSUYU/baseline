"""Deterministic 102-row native-only result table from verified queue receipts."""

from __future__ import annotations

import csv
import fcntl
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from Mallory.native_graphchecker_dispatch.checklist import (
    _native_case_files, load_inventory, load_ownership,
)
from .queue import _terminal_fingerprint, obj, sha

FIELDS = (
    "case_id", "system", "system_version", "owner", "native_state",
    "target_source_path", "target_class", "target_method", "target_line",
    "target_check_code", "target_exception", "original_junit",
    "executed_original_junit", "terminal_disposition", "checkpoint_status",
    "checkpoint_observed_fault_trials", "checkpoint_observed_elapsed_seconds",
    "native_tested_complete", "fault_trials", "strict_fault_trials",
    "target_retained_fault_trials", "target_throw_trials", "candidate_trials",
    "elapsed_seconds", "elapsed_basis", "target_throw_observed",
    "new_bug_candidate", "native_config_path", "native_config_sha256",
    "checkpoint_path", "checkpoint_sha256", "summary_path", "summary_sha256",
    "completion_receipt_path", "completion_receipt_sha256", "evidence_paths",
)
RESULT_STATES = {"tested_candidate", "tested_no_target_throw",
                 "tested_inconclusive", "native_blocked"}


def _method_parts(function: str) -> tuple[str, str]:
    head = function.split("(", 1)[0]
    class_name, _ = head.rsplit(".", 1)
    return class_name, function[len(class_name) + 1:]


def native_rows(inventory: Path, ownership_file: Path, config_root: Path,
                state_root: Path) -> list[dict[str, Any]]:
    cases, by_id = load_inventory(inventory)
    owners = load_ownership(ownership_file, set(by_id))
    if len(cases) != 102:
        raise ValueError("native result export requires the 102-case inventory")
    rows = []
    for item in sorted(cases, key=lambda item: item["case_id"]):
        case_id = item["case_id"]
        target = item["target"]
        source_class, source_method = _method_parts(target["function"])
        config_file, native_root = _native_case_files(item, config_root,
                                                       state_root)
        checkpoint_path = native_root / "checkpoint.json"
        summary_path = native_root / "summary.json"
        receipt_path = (state_root / ".native-queue" / "completions" /
                        f"{case_id}.json")
        row: dict[str, Any] = {
            "case_id": case_id, "system": item["system"],
            "system_version": item["system_version"],
            "owner": owners[case_id], "native_state": "not_completed",
            "target_source_path": target["source_path"],
            "target_class": source_class, "target_method": source_method,
            "target_line": target["source_line"],
            "target_check_code": target["check_code"],
            "target_exception": target.get("target_exception"),
            "original_junit": item["workload"].get("selected_selector"),
            "executed_original_junit": None,
            "terminal_disposition": None, "checkpoint_status": None,
            "checkpoint_observed_fault_trials": None,
            "checkpoint_observed_elapsed_seconds": None,
            "native_tested_complete": False, "fault_trials": None,
            "strict_fault_trials": None,
            "target_retained_fault_trials": None, "target_throw_trials": None,
            "candidate_trials": None, "elapsed_seconds": None,
            "elapsed_basis": None, "target_throw_observed": False,
            "new_bug_candidate": False, "native_config_path": None,
            "native_config_sha256": None,
            "checkpoint_path": None, "checkpoint_sha256": None,
            "summary_path": None, "summary_sha256": None,
            "completion_receipt_path": None,
            "completion_receipt_sha256": None, "evidence_paths": [],
        }
        if config_file.is_file():
            row["native_config_path"] = str(config_file.resolve())
            row["native_config_sha256"] = sha(config_file)
            row["evidence_paths"].append(str(config_file.resolve()))
        if checkpoint_path.is_file():
            checkpoint = obj(checkpoint_path)
            row["checkpoint_status"] = checkpoint.get("status")
            row["checkpoint_observed_fault_trials"] = checkpoint.get(
                "completed_fault_trials")
            row["checkpoint_observed_elapsed_seconds"] = checkpoint.get(
                "elapsed_seconds")
            row["checkpoint_path"] = str(checkpoint_path.resolve())
            row["checkpoint_sha256"] = sha(checkpoint_path)
            row["evidence_paths"].append(str(checkpoint_path.resolve()))
        if receipt_path.is_file():
            receipt = obj(receipt_path)
            fingerprint = _terminal_fingerprint(item, config_root, state_root)
            if (fingerprint is None or
                    receipt.get("method") != "original_native_graphchecker_campaign" or
                    receipt.get("case_id") != case_id or
                    receipt.get("system") != item["system"] or
                    receipt.get("source_path") != target["source_path"] or
                    receipt.get("source_line") != target["source_line"] or
                    receipt.get("target_site") != target["site_id"] or
                    receipt.get("target_exception") != target.get("target_exception") or
                    receipt.get("original_junit") != row["original_junit"] or
                    receipt.get("terminal_disposition") not in RESULT_STATES or
                    not isinstance(receipt.get("native_tested_complete"), bool) or
                    (receipt.get("terminal_disposition") == "native_blocked" and
                     receipt.get("native_tested_complete") is not False) or
                    (receipt.get("terminal_disposition") != "native_blocked" and
                     receipt.get("native_tested_complete") is not True) or
                    receipt.get("config_sha256") != fingerprint["config_sha256"] or
                    receipt.get("summary_sha256") != fingerprint["summary_sha256"] or
                    receipt.get("config_path") != str(config_file.resolve()) or
                    receipt.get("summary_path") != str(summary_path.resolve()) or
                    receipt.get("binding_sha256") != fingerprint["binding_sha256"]):
                raise ValueError(f"native completion receipt changed: {case_id}")
            if receipt.get("bug_candidate") is not (
                    receipt["terminal_disposition"] == "tested_candidate"):
                raise ValueError(f"native bug mark disagrees with disposition: {case_id}")
            row.update({
                "native_state": ("verified_terminal" if receipt[
                    "native_tested_complete"] else "native_blocked"),
                "executed_original_junit": receipt["executed_original_junit"],
                "terminal_disposition": receipt["terminal_disposition"],
                "native_tested_complete": receipt["native_tested_complete"],
                "fault_trials": receipt["fault_trials"],
                "strict_fault_trials": receipt["strict_fault_trials"],
                "target_retained_fault_trials": receipt[
                    "target_retained_fault_trials"],
                "target_throw_trials": receipt["target_throw_trials"],
                "candidate_trials": receipt["candidate_trials"],
                "elapsed_seconds": receipt["elapsed_seconds"],
                "elapsed_basis": "sum_original_native_junit_trial_seconds",
                "target_throw_observed": receipt["target_throw_trials"] > 0,
                "new_bug_candidate": receipt["bug_candidate"],
                "checkpoint_sha256": fingerprint["checkpoint_sha256"],
                "summary_path": str(summary_path.resolve()),
                "summary_sha256": fingerprint["summary_sha256"],
                "completion_receipt_path": str(receipt_path.resolve()),
                "completion_receipt_sha256": sha(receipt_path),
                "evidence_paths": [str(config_file.resolve()),
                                   str(checkpoint_path.resolve()),
                                   str(summary_path.resolve()),
                                   str(receipt_path.resolve())],
            })
        elif row["checkpoint_status"] == "running":
            row["native_state"] = "running_no_terminal_receipt"
        elif checkpoint_path.is_file() and obj(checkpoint_path).get("terminal") is True:
            row["native_state"] = "terminal_awaiting_adoption"
        rows.append(row)
    return rows


def _replace_text(path: Path, contents: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=".native-results-", delete=False) as out:
        temporary = Path(out.name)
        out.write(contents)
        out.flush()
        os.fsync(out.fileno())
        os.fchmod(out.fileno(), 0o644)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def export_native_results(inventory: Path, ownership_file: Path,
                          config_root: Path, state_root: Path,
                          results_dir: Path) -> tuple[Path, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    with (results_dir / ".native-results.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = native_rows(inventory, ownership_file, config_root, state_root)
        document = {"schema_version": 1,
                    "method": "original_native_graphchecker_campaign",
                    "inventory_sha256": sha(inventory),
                    "ownership_sha256": sha(ownership_file),
                    "case_count": 102,
                    "verified_terminal_count": sum(
                        row["native_state"] == "verified_terminal" for row in rows),
                    "rows": rows}
        tsv_stream = io.StringIO()
        writer = csv.DictWriter(tsv_stream, fieldnames=FIELDS, delimiter="\t",
                                lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(row[key], sort_keys=True)
                             if isinstance(row[key], (dict, list)) else
                             "" if row[key] is None else row[key]
                             for key in FIELDS})
        json_path = results_dir / "native-102-results.json"
        tsv_path = results_dir / "native-102-results.tsv"
        _replace_text(json_path, json.dumps(document, sort_keys=True,
                                            indent=2) + "\n")
        _replace_text(tsv_path, tsv_stream.getvalue())
        return json_path, tsv_path
