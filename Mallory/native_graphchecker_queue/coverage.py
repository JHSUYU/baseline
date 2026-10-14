"""Pinned trial evidence for audited fault-in-target-closure counts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Mallory.native_graphchecker_dispatch.checklist import _native_case_files
from .queue import (_same_or_write, _terminal_fingerprint, obj, sha)


def coverage_path(state_root: Path, case_id: str) -> Path:
    return (state_root / ".native-queue" / "coverage" /
            f"{case_id}.json")


def _trial_evidence(native_root: Path, fault_trials: int) -> tuple[int, int, dict[str, str]]:
    trial_results = sorted((native_root / "trials").glob("r*/result.json"))
    if len(trial_results) != fault_trials + 1:
        raise ValueError("target-closure count lacks exact native trial receipts")
    files: dict[str, str] = {}
    strict_retained = inside_closure = 0
    for index, path in enumerate(trial_results):
        result = obj(path)
        if path.parent.name != f"r{index:04d}":
            raise ValueError("target-closure trials are out of order")
        files[str(path.resolve())] = sha(path)
        for evidence in (path.parent / "native-summary.json",
                         path.parent / "iteration-native/fault-events.jsonl"):
            if evidence.is_file():
                files[str(evidence.resolve())] = sha(evidence)
        if index and result.get("strict_injection") is True and result.get(
                "native_target_retained") is True:
            strict_retained += 1
            if result.get("fault_in_target_closure") is True:
                inside_closure += 1
            elif result.get("fault_in_target_closure") is not False:
                raise ValueError("audited target-closure membership is missing")
    return strict_retained, inside_closure, files


def publish_coverage(item: dict, row: dict[str, Any], config_root: Path,
                     state_root: Path) -> dict[str, Any]:
    """Publish only after full inspect_case has checked every native graph."""
    case_id = item["case_id"]
    count = row.get("strict_in_target_closure_trials")
    strict = row.get("strict_target_retained_fault_trials")
    if (row.get("native_tested_complete") is not True or
            not isinstance(count, int) or isinstance(count, bool) or
            not isinstance(strict, int) or isinstance(strict, bool) or
            count < 0 or count > strict):
        raise ValueError("full native closure audit is required")
    config, native_root = _native_case_files(item, config_root, state_root)
    fingerprint = _terminal_fingerprint(item, config_root, state_root)
    completion = (state_root / ".native-queue" / "completions" /
                  f"{case_id}.json")
    if fingerprint is None or not completion.is_file():
        raise ValueError("native completion fingerprint is missing")
    receipt = obj(completion)
    if (receipt.get("native_tested_complete") is not True or
            receipt.get("config_sha256") != sha(config) or
            receipt.get("summary_sha256") != fingerprint["summary_sha256"] or
            receipt.get("fault_trials") != row.get("fault_trials")):
        raise ValueError("native completion differs from closure audit")
    observed_strict, observed_inside, evidence = _trial_evidence(
        native_root, receipt["fault_trials"])
    if observed_strict != strict or observed_inside != count:
        raise ValueError("native trial membership differs from full graph audit")
    metric = {"schema_version": 1,
              "method": "full_native_inspect_case_original_graph_audit",
              "case_id": case_id, "fingerprint": fingerprint,
              "completion_receipt_path": str(completion.resolve()),
              "completion_receipt_sha256": sha(completion),
              "strict_target_retained_fault_trials": strict,
              "strict_in_target_closure_trials": count,
              "evidence_sha256": evidence}
    _same_or_write(coverage_path(state_root, case_id), metric)
    return metric


def read_coverage(item: dict, config_root: Path,
                  state_root: Path) -> dict[str, Any] | None:
    path = coverage_path(state_root, item["case_id"])
    if not path.is_file():
        return None
    metric = obj(path)
    fingerprint = _terminal_fingerprint(item, config_root, state_root)
    completion = (state_root / ".native-queue" / "completions" /
                  f"{item['case_id']}.json")
    evidence = metric.get("evidence_sha256")
    if (metric.get("schema_version") != 1 or
            metric.get("method") != "full_native_inspect_case_original_graph_audit" or
            metric.get("case_id") != item["case_id"] or
            fingerprint is None or metric.get("fingerprint") != fingerprint or
            metric.get("completion_receipt_path") != str(completion.resolve()) or
            metric.get("completion_receipt_sha256") != sha(completion) or
            not isinstance(evidence, dict) or not evidence or
            any(sha(Path(name)) != digest for name, digest in evidence.items())):
        raise ValueError("audited target-closure evidence changed")
    strict, inside, current = _trial_evidence(
        Path(fingerprint["native_root"]), obj(completion)["fault_trials"])
    if (current != evidence or
            metric.get("strict_target_retained_fault_trials") != strict or
            metric.get("strict_in_target_closure_trials") != inside):
        raise ValueError("audited target-closure count changed")
    return metric
