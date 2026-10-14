"""Deterministic 102-row native-only result table from verified queue receipts."""

from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from Mallory.native_graphchecker_dispatch.checklist import (
    _native_case_files, load_ownership,
)
from Mallory.native_graphchecker_dispatch.region_state_target import (
    healthy_reached_nonfatal,
)
from Mallory.native_graphchecker_feedback.artifacts import region_plan_path
from .queue import _terminal_fingerprint, obj, sha
from .coverage import coverage_path, read_coverage
from .inventory_epoch import (_row_sha, load_queue_inventory,
                              require_epoch_results_dir)

FIELDS = (
    "case_id", "system", "system_version", "owner", "native_state",
    "preparation_status", "preparation_junit_trials",
    "preparation_fault_trials", "preparation_review_path",
    "preparation_review_sha256", "preparation_note_pin_path",
    "preparation_note_pin_sha256", "preparation_note",
    "target_source_path", "target_class", "target_method", "target_line",
    "target_check_code", "target_exception", "original_junit",
    "executed_original_junit", "terminal_disposition", "checkpoint_status",
    "checkpoint_observed_fault_trials", "checkpoint_observed_elapsed_seconds",
    "native_tested_complete", "fault_trials", "strict_fault_trials",
    "target_retained_fault_trials", "strict_target_retained_fault_trials",
    "strict_in_target_closure_trials", "closure_attribution_basis",
    "closure_audit_path", "closure_audit_sha256",
    "target_throw_trials", "candidate_trials",
    "elapsed_seconds", "elapsed_basis", "target_throw_observed",
    "reviewed_campaign_wall_seconds", "reviewed_static_to_terminal_wall_seconds",
    "target_exception_candidate", "confirmed_new_bug",
    "native_config_path", "native_config_sha256",
    "checkpoint_path", "checkpoint_sha256", "summary_path", "summary_sha256",
    "terminal_review_path", "terminal_review_sha256",
    "terminal_quality_note",
    "completion_receipt_path", "completion_receipt_sha256", "evidence_paths",
)
RESULT_STATES = {"tested_candidate", "tested_no_target_throw",
                 "tested_inconclusive", "native_blocked"}


def _method_parts(function: str) -> tuple[str, str]:
    head = function.split("(", 1)[0]
    class_name, _ = head.rsplit(".", 1)
    return class_name, function[len(class_name) + 1:]


def _preparation_note(item: dict, state_root: Path) -> dict[str, Any] | None:
    """Read a pinned pre-JUnit failure without granting terminal status."""
    case_id = item["case_id"]
    pin_path = (state_root / ".native-queue" / "preparation-notes" /
                f"{case_id}.json")
    if not pin_path.is_file():
        return None
    pin = obj(pin_path)
    paths = {}
    for name in ("review", "source_preflight", "request"):
        entry = pin.get(name)
        path = Path(entry.get("path", "")) if isinstance(entry, dict) else Path("")
        if (not path.is_absolute() or path.is_symlink() or not path.is_file() or
                sha(path) != entry.get("sha256")):
            raise ValueError(f"native preparation {name} pin changed: {case_id}")
        paths[name] = path
    if (pin.get("schema_version") != 1 or pin.get("case_id") != case_id or
            pin.get("status") != "static_timeout" or
            pin.get("junit_trials") != 0 or
            pin.get("fault_trials") != 0):
        raise ValueError(f"native preparation note changed: {case_id}")
    review = obj(paths["review"])
    source = obj(paths["source_preflight"])
    request = obj(paths["request"])
    timeout = review.get("configured_static_timeout_seconds")
    if (review.get("schema_version") != 1 or
            review.get("case_id") != case_id or
            review.get("status") != "static_timeout" or
            review.get("no_weave_manifest") is not True or
            review.get("no_junit_run") is not True or
            review.get("no_fault_trial") is not True or
            str(review.get("exit_code")) != "1" or
            not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or
            timeout <= 0 or
            review.get("request_sha256") != sha(paths["request"]) or
            source.get("schema_version") != 1 or
            source.get("case_id") != case_id or
            source.get("target_source_sha256") != item["target"]["source_sha256"] or
            source.get("target_throw_source_line") != item["target"]["source_line"] or
            source.get("target_exception") != item["target"].get(
                "target_exception") or
            source.get("original_junit") != item["workload"].get(
                "selected_selector") or
            request.get("case_id") != case_id or
            request.get("inventory_row_sha256") != hashlib.sha256(
                json.dumps(item, sort_keys=True, separators=(",", ":")
                           ).encode()).hexdigest() or
            request.get("original_junit", {}).get("selector") != item[
                "workload"].get("selected_selector") or
            request.get("target", {}).get("site_id") != item["target"][
                "site_id"]):
        raise ValueError(f"native preparation evidence changed: {case_id}")
    stage = review.get("last_observed_stage")
    if not isinstance(stage, str) or not stage:
        raise ValueError(f"native preparation stage is missing: {case_id}")
    return {
        "preparation_status": "static_timeout",
        "preparation_junit_trials": 0,
        "preparation_fault_trials": 0,
        "preparation_review_path": str(paths["review"].resolve()),
        "preparation_review_sha256": sha(paths["review"]),
        "preparation_note_pin_path": str(pin_path.resolve()),
        "preparation_note_pin_sha256": sha(pin_path),
        "preparation_note": (f"Original static ScopePlanner stopped after "
                             f"{timeout:g}s at {stage}; no JUnit or fault trial ran."),
        "evidence_paths": [str(path.resolve()) for path in paths.values()] +
                          [str(pin_path.resolve())],
    }


def _admission_note(item: dict, state_root: Path) -> dict[str, Any] | None:
    """Record a pinned healthy JUnit whose native graph admission did not finish."""
    case_id = item["case_id"]
    pin_path = (state_root / ".native-queue" / "admission-notes" /
                f"{case_id}.json")
    if not pin_path.is_file():
        return None
    pin = obj(pin_path)
    if (pin.get("schema_version") != 1 or pin.get("case_id") != case_id or
            pin.get("status") != "blocked_healthy_native_session" or
            pin.get("junit_trials") != 1 or pin.get("fault_trials") != 0 or
            pin.get("inventory_row_sha256") != hashlib.sha256(json.dumps(
                item, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()):
        raise ValueError(f"native admission note changed: {case_id}")
    paths = {}
    for name in ("review", "config", "healthy_result", "target_occurrence"):
        entry = pin.get(name)
        path = Path(entry.get("path", "")) if isinstance(entry, dict) else Path("")
        if (not path.is_absolute() or path.is_symlink() or not path.is_file() or
                sha(path) != entry.get("sha256")):
            raise ValueError(f"native admission {name} pin changed: {case_id}")
        paths[name] = path
    review, config, healthy, occurrence = (obj(paths[name]) for name in
                                           ("review", "config", "healthy_result",
                                            "target_occurrence"))
    selector = item["workload"].get("selected_selector")
    executed = config.get("junit", {}).get("class", "") + "#" + config.get(
        "junit", {}).get("method", "")
    if (review.get("caseId") != case_id or
            review.get("kind") != "HBASE07_V4_NO_PLAN_HEALTHY_GRAPH_TERMINAL_REVIEW" or
            review.get("status") != "blocked_healthy_native_session" or
            review.get("failureClass") != "original_recorder_timeout_1800s" or
            review.get("formalStarted") is not False or
            review.get("appliedFaultCount") != 0 or
            review.get("bugClaim") is not False or
            review.get("junitPassed") is not True or
            review.get("rawTargetCheckCount", 0) < 1 or
            review.get("rawTargetThrowCount") != 0 or
            review.get("configPath") != str(paths["config"]) or
            review.get("configSha256") != sha(paths["config"]) or
            review.get("healthyResultSha256") != sha(paths["healthy_result"]) or
            executed != selector or
            config.get("target_throw", {}).get("siteId") != item[
                "target"]["site_id"] or
            config.get("target_throw", {}).get("exceptionClass") != item[
                "target"].get("target_exception") or
            config.get("target_site") != occurrence.get("checkSiteId") or
            occurrence.get("test") != selector or
            not healthy_reached_nonfatal(occurrence) or
            healthy.get("status") != "blocked_healthy_native_session" or
            healthy.get("junit_passed") is not True or
            healthy.get("target_exception_triggered") is not False or
            healthy.get("target_throw_rows", []) != [] or
            healthy.get("faults") != [] or
            healthy.get("strict_injection") is not False):
        raise ValueError(f"native admission evidence changed: {case_id}")
    return {
        "preparation_status": "blocked_healthy_native_session",
        "preparation_junit_trials": 1,
        "preparation_fault_trials": 0,
        "preparation_review_path": str(paths["review"].resolve()),
        "preparation_review_sha256": sha(paths["review"]),
        "preparation_note_pin_path": str(pin_path.resolve()),
        "preparation_note_pin_sha256": sha(pin_path),
        "preparation_note": (
            f"Original JUnit passed and reached the exact target guard "
            f"{review['rawTargetCheckCount']} times in "
            f"{review['junitElapsedSeconds']:g}s; original analysis stage "
            f"took {review['analysisElapsedSeconds']:g}s, including the "
            "Recorder timeout configured at 1800s. "
            "No formal fault trial ran; no target throw or bug claim."),
        "evidence_paths": [str(path.resolve()) for path in paths.values()] +
                          [str(pin_path.resolve())],
    }


def _selected_test_candidate(item: dict) -> dict:
    workload = item["workload"]
    selected = [candidate for candidate in workload.get("candidates", [])
                if candidate.get("selector") == workload.get("selected_selector")]
    if len(selected) != 1:
        raise ValueError(f"selected original JUnit candidate ambiguous: {item['case_id']}")
    return selected[0]


def _eligibility_note(item: dict, inventory: Path,
                      state_root: Path) -> dict[str, Any] | None:
    """Verify a source-only skip without granting a native trial verdict."""
    case_id = item["case_id"]
    pin_path = (state_root / ".native-queue" / "eligibility-notes" /
                f"{case_id}.json")
    if not pin_path.is_file():
        return None
    pin = obj(pin_path)
    entry = pin.get("review", {})
    review_path = Path(entry.get("path", ""))
    status = "no_eligible_original_cluster_test_current_checkout"
    if (pin.get("schema_version") != 1 or pin.get("case_id") != case_id or
            pin.get("status") != status or
            pin.get("native_queue_junit_trials") != 0 or
            pin.get("native_queue_fault_trials") != 0 or
            not review_path.is_absolute() or review_path.is_symlink() or
            not review_path.is_file() or sha(review_path) != entry.get("sha256")):
        raise ValueError(f"native eligibility review pin changed: {case_id}")
    review = obj(review_path)
    inventory_pin = review.get("inventory", {})
    row_sha = hashlib.sha256(json.dumps(item, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    if (review.get("schema_version") != 1 or
            review.get("case_id") != case_id or
            review.get("status") != status or
            review.get("selected_original_junit") != item["workload"].get(
                "selected_selector") or
            review.get("native_queue_junit_trials") != 0 or
            review.get("native_queue_fault_trials") != 0 or
            item.get("eligibility", {}).get("may_dispatch_healthy_seed") is not False or
            item["eligibility"].get("state") != "original_junit_skipped" or
            inventory_pin.get("sha256") != sha(inventory) or
            inventory_pin.get("row_sha256") != row_sha or
            review.get("target", {}).get("source_path") != item["target"][
                "source_path"] or
            review["target"].get("source_sha256") != item["target"][
                "source_sha256"] or
            review["target"].get("method") != item["target"]["function"] or
            review["target"].get("throw_line") != item["target"][
                "source_line"] or
            review["target"].get("exception") != item["target"].get(
                "target_exception") or
            review.get("prior_opt_in_junit") != {
                "tests": 1, "failures": 1, "target_checks": 0,
                "target_throws": 0}):
        raise ValueError(f"native eligibility review identity changed: {case_id}")
    pinned_inventory = Path(inventory_pin.get("path", ""))
    if (not pinned_inventory.is_absolute() or pinned_inventory.is_symlink() or
            not pinned_inventory.is_file() or
            sha(pinned_inventory) != inventory_pin["sha256"]):
        raise ValueError(f"native eligibility inventory pin changed: {case_id}")
    paths = {}
    for name in ("prior_source_review", "prior_opt_in_junit_log"):
        entry = review.get(name, {})
        path = Path(entry.get("path", ""))
        if (not path.is_absolute() or path.is_symlink() or
                not path.is_file() or sha(path) != entry.get("sha256")):
            raise ValueError(f"native eligibility {name} changed: {case_id}")
        paths[name] = path
    prior = obj(paths["prior_source_review"])
    log = paths["prior_opt_in_junit_log"].read_text()
    source_files = review.get("source_files", {})
    expected_sources = prior.get("source_hashes", {})
    required = {"processor", "time_test", "base_test", "lucene_annotation",
                "category_test", "dimensional_test", "create_test",
                "concurrent_test", "api_test", "alias_test"}
    if (prior.get("case_id") != case_id or
            prior.get("source_review_status") !=
            "source_review_no_suitable_test_current_environment" or
            prior.get("receipt_tier_assessment", {}).get(
                "source_only_no_executable_test_justified_for_unmodified_checkout")
            is not True or
            prior.get("receipt_tier_assessment", {}).get(
                "permanent_no_test_claim_justified") is not False or
            prior.get("target", {}).get("source_sha256") != item["target"][
                "source_sha256"] or
            prior.get("target", {}).get("source_line") != item["target"][
                "source_line"] or
            prior.get("prior_attempt", {}).get("pilot_target_check_count") != 0 or
            prior["prior_attempt"].get("junit_failures") != 1 or
            not isinstance(source_files, dict) or
            set(source_files) != set(expected_sources) or
            not required.issubset(source_files) or
            source_files["processor"].get("sha256") != item["target"][
                "source_sha256"] or
            source_files["time_test"].get("sha256") != _selected_test_candidate(
                item)["source_sha256"] or
            "@AwaitsFix" not in log or
            "Can't create a configset with an unauthenticated request" not in log):
        raise ValueError(f"native eligibility source review changed: {case_id}")
    source_paths = []
    for name, source in source_files.items():
        path = Path(source.get("path", ""))
        expected = expected_sources[name]
        if (not path.is_absolute() or path.is_symlink() or
                not path.is_file() or
                not str(path).endswith(expected["path"]) or
                source.get("sha256") != expected["sha256"] or
                sha(path) != expected["sha256"]):
            raise ValueError(f"native eligibility source {name} changed: {case_id}")
        source_paths.append(str(path.resolve()))
    return {
        "preparation_status": status,
        "preparation_junit_trials": 0,
        "preparation_fault_trials": 0,
        "preparation_review_path": str(review_path.resolve()),
        "preparation_review_sha256": sha(review_path),
        "preparation_note_pin_path": str(pin_path.resolve()),
        "preparation_note_pin_sha256": sha(pin_path),
        "preparation_note": (
            "No target-reaching original cluster JUnit is eligible under the "
            "pinned checkout and current harness: normal selection inherits "
            "@AwaitsFix; one prior opt-in JUnit failed in configset setup "
            "before routed ADD (zero target checks). No native queue JUnit "
            "or fault trial ran; fixture repair may change eligibility."),
        "evidence_paths": [str(review_path.resolve()), str(pin_path.resolve())] +
                          [str(path.resolve()) for path in paths.values()] +
                          source_paths,
    }


def _eligibility_supersession(item: dict, state_root: Path,
                             old_note: dict[str, Any] | None
                             ) -> dict[str, Any] | None:
    """Reopen a source-only skip after an independently pinned healthy JUnit.

    The old review stays on disk and is validated by ``_eligibility_note``.
    This receipt only changes scheduling eligibility; it never counts a native
    fault trial or claims a target exception.
    """
    case_id = item["case_id"]
    path = (state_root / ".native-queue" / "eligibility-supersessions" /
            f"{case_id}.json")
    if not path.is_file():
        return None
    if old_note is None:
        raise ValueError(f"native eligibility supersession lacks old review: {case_id}")
    receipt = obj(path)
    if (receipt.get("schema_version") != 1 or
            receipt.get("case_id") != case_id or
            receipt.get("status") != "healthy_original_junit_reopens_case" or
            receipt.get("superseded_pin_sha256") !=
            old_note["preparation_note_pin_sha256"]):
        raise ValueError(f"native eligibility supersession identity changed: {case_id}")
    files: dict[str, Path] = {}
    for name in ("healthy_result", "healthy_trial", "junit_receipt",
                 "test_source", "target_source"):
        entry = receipt.get(name, {})
        source = Path(entry.get("path", ""))
        if (not source.is_absolute() or source.is_symlink() or
                not source.is_file() or sha(source) != entry.get("sha256")):
            raise ValueError(f"native eligibility supersession {name} changed: {case_id}")
        files[name] = source
    healthy = obj(files["healthy_result"])
    trial = obj(files["healthy_trial"])
    junit = obj(files["junit_receipt"])
    target = healthy.get("target", {})
    expected_junit = item["workload"].get("selected_selector")
    if (healthy.get("case_id") != case_id or
            healthy.get("cluster_test") != expected_junit or
            healthy.get("calibration_only") is not True or
            healthy.get("healthy_seed_valid") is not True or
            healthy.get("fault_trials_completed") != 0 or
            healthy.get("target_node_named") is not True or
            healthy.get("healthy_eligible_doors", 0) < 1 or
            healthy.get("runtime_attestation", {}).get("valid") is not True or
            target.get("source_path") != item["target"]["source_path"] or
            target.get("source_line") != item["target"]["source_line"] or
            target.get("exception_class") != item["target"].get(
                "target_exception") or
            trial.get("case_id") != case_id or
            trial.get("trial_id") != 0 or
            trial.get("junit_receipt_sha256") != sha(files["junit_receipt"]) or
            trial.get("plan") != [] or
            junit.get("status") != "passed" or
            junit.get("tests") != 1 or
            any(junit.get(key) != 0 for key in
                ("failures", "errors", "skipped", "assumption_failures")) or
            sha(files["test_source"]) != _selected_test_candidate(item)[
                "source_sha256"] or
            sha(files["target_source"]) != item["target"]["source_sha256"]):
        raise ValueError(f"native eligibility supersession healthy evidence changed: {case_id}")
    checks = [row for row in healthy.get("trials", []) if
              row.get("trial_id") == 0 and row.get("target_reached") is True]
    if len(checks) != 1 or checks[0].get("eligible_doors_before_target", 0) < 1:
        raise ValueError(f"native eligibility supersession has no target path: {case_id}")
    return {
        "preparation_status": "healthy_original_junit_reopens_case",
        "preparation_junit_trials": 0,
        "preparation_fault_trials": 0,
        "preparation_review_path": str(path.resolve()),
        "preparation_review_sha256": sha(path),
        "preparation_note": (
            "Later unchanged original cluster JUnit passed, reached the exact "
            "target and observed pre-target doors. The old source-only skip "
            "is superseded; native queue preparation and fault trials remain."),
        "evidence_paths": [str(path.resolve()), *old_note["evidence_paths"],
                           *(str(source.resolve()) for source in files.values())],
    }


def _elapsed_basis(native_root: Path, fault_trials: int,
                   elapsed_seconds: float) -> str:
    """Attribute reported time to the native trial receipts' actual schema."""
    files = sorted((native_root / "trials").glob("r*/result.json"))
    if len(files) != fault_trials + 1:
        raise ValueError("native elapsed basis lacks healthy/fault trial receipts")
    rows = [obj(path) for path in files]
    if round(sum(float(row["elapsed_seconds"]) for row in rows), 3) != round(
            elapsed_seconds, 3):
        raise ValueError("native elapsed seconds differ from original trial receipts")
    breakdown = ["junit_elapsed_seconds" in row and
                 "analysis_elapsed_seconds" in row for row in rows]
    if all(breakdown):
        for row in rows:
            if abs(row["elapsed_seconds"] - row["junit_elapsed_seconds"] -
                   row["analysis_elapsed_seconds"]) > 0.002:
                raise ValueError("native JUnit/analysis time breakdown changed")
        return "sum_native_trial_elapsed_seconds_including_graph_analysis"
    if not any(breakdown) and all(
            "junit_elapsed_seconds" not in row and
            "analysis_elapsed_seconds" not in row for row in rows):
        return "sum_native_junit_execution_seconds_legacy"
    raise ValueError("native trial elapsed accounting changed within campaign")


def _reviewed_wall_timing(review: dict, trial_elapsed: float) -> tuple[float | None,
                                                                      float | None]:
    timing = review.get("timing")
    if timing is None and "campaign_wall_seconds" in review:
        timing = {"campaign_wall_seconds": review["campaign_wall_seconds"],
                  "cumulative_trial_seconds": review.get(
                      "cumulative_healthy_and_trial_seconds"),
                  "static_to_terminal_wall_seconds": review.get(
                      "static_to_terminal_wall_seconds")}
    if not isinstance(timing, dict) or "campaign_wall_seconds" not in timing:
        return None, None
    cumulative = timing.get("cumulative_trial_seconds",
                            timing.get("cumulative_healthy_plus_fault_trial_seconds"))
    campaign_wall = timing["campaign_wall_seconds"]
    static_wall = timing.get("static_to_terminal_wall_seconds")
    if (not isinstance(cumulative, (int, float)) or
            not isinstance(campaign_wall, (int, float)) or
            isinstance(cumulative, bool) or isinstance(campaign_wall, bool) or
            round(float(cumulative), 3) != round(float(trial_elapsed), 3) or
            campaign_wall < 0 or
            (static_wall is not None and
             (not isinstance(static_wall, (int, float)) or
              isinstance(static_wall, bool) or static_wall < 0))):
        raise ValueError("reviewed wall timing differs from native trial receipts")
    return float(campaign_wall), (float(static_wall) if static_wall is not None
                                  else None)


def _reviewed_exact_closure(case_id: str, native_root: Path, state_root: Path,
                            strict: int, proxy: int,
                            completion_sha: str) -> tuple[int, Path, str, Path] | None:
    """Accept an exact Finalizer-plan ID audit only with frozen trial inputs."""
    pin_path = (state_root / ".native-queue" / "closure-reviews" /
                f"{case_id}.json")
    if not pin_path.is_file():
        return None
    pin = obj(pin_path)
    selected_instance = pin.get("audit_basis") == "selected_target_occurrence"
    if pin.get("audit_basis") not in (None, "selected_target_occurrence"):
        raise ValueError(f"native exact closure audit basis changed: {case_id}")
    report_path = Path(pin.get("report_path", ""))
    method_path = Path(pin.get("method_path", ""))
    id_source_path = Path(pin.get("id_source_path", ""))
    engine_path = Path(pin.get("engine_jar_path", ""))
    index_path = Path(pin.get("index_path", ""))
    checked = ((report_path, "report_sha256"),
               (method_path, "method_sha256"),
               (id_source_path, "id_source_sha256"),
               (engine_path, "engine_jar_sha256"),
               (index_path, "index_sha256"))
    if (pin.get("schema_version") != 1 or pin.get("case_id") != case_id or
            pin.get("completion_receipt_sha256") != completion_sha or
            any(not path.is_absolute() or path.is_symlink() or
                not path.is_file() or sha(path) != pin.get(key)
                for path, key in checked)):
        raise ValueError(f"native exact closure audit pin changed: {case_id}")
    report = obj(report_path)
    index = obj(index_path)
    index_rows = [row for row in index.get("rows", []) if isinstance(row, dict)
                  and row.get("auditPath") == str(report_path)]
    rows = report.get("trials")
    if (report.get("kind") != "READ_ONLY_REGION_STATE_CLOSURE_AUDIT" or
            index.get("kind") != "READ_ONLY_REGION_STATE_CLOSURE_AUDIT_INDEX" or
            len(index_rows) != 1 or
            index_rows[0].get("auditSha256") != pin["report_sha256"] or
            index_rows[0].get("campaign") != str(native_root.resolve()) or
            index_rows[0].get("engineJarSha256") != pin["engine_jar_sha256"] or
            any(index_rows[0].get(key) != report.get(key) for key in (
                "strictTargetRetainedTrials", "reportedLastFaultInClosure",
                "correctedLastFaultInClosure")) or
            report.get("campaign") != str(native_root.resolve()) or
            report.get("engineJarSha256") != pin["engine_jar_sha256"] or
            report.get("strictTargetRetainedTrials") != strict or
            report.get("reportedLastFaultInClosure") != proxy or
            not isinstance(rows, list) or len(rows) != strict or
            any(not isinstance(row, dict) or
                not isinstance(row.get("correctedLastFaultInClosure"), bool) or
                not isinstance(row.get("reportedLastFaultInClosure"), bool)
                for row in rows) or
            report.get("correctedLastFaultInClosure") != sum(
                row.get("correctedLastFaultInClosure") is True for row in rows)):
        raise ValueError(f"native exact closure report differs from receipts: {case_id}")
    observed = set()
    for trial in rows:
        name = trial.get("trial", "")
        if (not isinstance(name, str) or not name.startswith("r") or
                not name[1:].isdigit() or name in observed):
            raise ValueError(f"native exact closure trial is invalid: {case_id}")
        observed.add(name)
        directory = native_root / "trials" / name
        result = obj(directory / "result.json")
        plan = region_plan_path(directory / "original-graph/recorded")
        events = directory / "iteration-native/fault-events.jsonl"
        if (result.get("strict_injection") is not True or
                result.get("native_target_retained") is not True or
                result.get("fault_in_target_closure") is not trial.get(
                    "reportedLastFaultInClosure") or
                result.get("target_exception_triggered") is not trial.get(
                    "targetExceptionTriggered") or
                result.get("target_temporal_admitted") is not trial.get(
                    "targetTemporalAdmitted") or
                sha(plan) != trial.get("originalPlanSha256") or
                sha(events) != trial.get("faultEventsSha256")):
            raise ValueError(f"native exact closure trial changed: {case_id}/{name}")
        if selected_instance:
            summary = obj(directory / "native-summary.json")
            selected = trial.get("selectedTargetOccurrenceId")
            target = summary.get("targetEvidence", {})
            rows = [json.loads(line) for line in events.read_text().splitlines()
                    if line.strip()]
            applied = [row for row in rows if row.get("kind") == "FAULT_APPLIED"]
            if (not isinstance(selected, str) or not selected or
                    summary.get("provenance", {}).get("engineJarSha256") !=
                        pin["engine_jar_sha256"] or
                    summary.get("provenance", {}).get("regionPlanSha256") !=
                        trial["originalPlanSha256"] or
                    summary.get("provenance", {}).get("faultEventsSha256") !=
                        trial["faultEventsSha256"] or
                    selected not in summary.get("closureOccurrenceIds", []) or
                    selected not in target.get("targetCheckOccurrenceIds", []) or
                    not any(row.get("kind") == "TARGET_CHECK" and
                            row.get("occurrenceId") == selected and
                            row.get("siteId") == summary.get("targetSiteId") and
                            row.get("node") == target.get("physicalActor") and
                            row.get("actorEpochOrdinal") == target.get(
                                "actorEpochOrdinal") for row in rows) or
                    not applied or
                    applied[-1].get("occurrenceId") != trial.get(
                        "lastFaultOccurrenceId") or
                    (applied[-1]["occurrenceId"] in summary[
                        "closureOccurrenceIds"]) is not trial[
                            "correctedLastFaultInClosure"] or
                    sorted(set(target.get("targetCheckOccurrenceIds", [])) -
                           set(summary["closureOccurrenceIds"])) != trial.get(
                               "observedTargetIdsOutsideClosure")):
                raise ValueError(f"native selected target closure changed: {case_id}/{name}")
    expected = {path.parent.name for path in (native_root / "trials").glob(
        "r*/result.json") if obj(path).get("strict_injection") is True and
        obj(path).get("native_target_retained") is True}
    if observed != expected:
        raise ValueError(f"native exact closure trial set changed: {case_id}")
    return (report["correctedLastFaultInClosure"], report_path,
            sha(report_path), index_path)


def native_rows(inventory: Path, ownership_file: Path, config_root: Path,
                state_root: Path, epoch_receipt: Path | None = None,
                epoch_receipt_sha256: str | None = None) -> list[dict[str, Any]]:
    cases, by_id, epoch = load_queue_inventory(inventory, state_root,
                                               epoch_receipt,
                                               epoch_receipt_sha256)
    owners = load_ownership(ownership_file, set(by_id))
    if len(cases) != 102:
        raise ValueError("native result export requires the 102-case inventory")
    rows = []
    source_archive_root = state_root / ".native-queue" / "source-archive"
    for item in sorted(cases, key=lambda item: item["case_id"]):
        case_id = item["case_id"]
        target = item["target"]
        source_class, source_method = _method_parts(target["function"])
        config_file, native_root = _native_case_files(item, config_root,
                                                       state_root,
                                                       source_archive_root)
        checkpoint_path = native_root / "checkpoint.json"
        summary_path = native_root / "summary.json"
        receipt_path = (state_root / ".native-queue" / "completions" /
                        f"{case_id}.json")
        row: dict[str, Any] = {
            "case_id": case_id, "system": item["system"],
            "system_version": item["system_version"],
            "owner": owners[case_id], "native_state": "not_completed",
            "preparation_status": None, "preparation_junit_trials": None,
            "preparation_fault_trials": None,
            "preparation_review_path": None,
            "preparation_review_sha256": None,
            "preparation_note_pin_path": None,
            "preparation_note_pin_sha256": None,
            "preparation_note": None,
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
            "target_retained_fault_trials": None,
            "strict_target_retained_fault_trials": None,
            "strict_in_target_closure_trials": None,
            "closure_attribution_basis": None,
            "closure_audit_path": None, "closure_audit_sha256": None,
            "target_throw_trials": None,
            "candidate_trials": None, "elapsed_seconds": None,
            "elapsed_basis": None, "target_throw_observed": False,
            "reviewed_campaign_wall_seconds": None,
            "reviewed_static_to_terminal_wall_seconds": None,
            "target_exception_candidate": False,
            "confirmed_new_bug": None, "native_config_path": None,
            "native_config_sha256": None,
            "checkpoint_path": None, "checkpoint_sha256": None,
            "summary_path": None, "summary_sha256": None,
            "terminal_review_path": None, "terminal_review_sha256": None,
            "terminal_quality_note": None,
            "completion_receipt_path": None,
            "completion_receipt_sha256": None, "evidence_paths": [],
        }
        if epoch is not None:
            row["inventory_row_sha256"] = _row_sha(item)
            row["inventory_epoch"] = ("v15-corrected" if case_id ==
                                      epoch["amended_case_id"] else "v14-unchanged")
        preparation = _preparation_note(item, state_root)
        if preparation is not None:
            evidence = preparation.pop("evidence_paths")
            row.update(preparation)
            row["evidence_paths"].extend(evidence)
            row["native_state"] = "preparation_static_timeout"
        admission = _admission_note(item, state_root)
        if admission is not None:
            if preparation is not None:
                raise ValueError(f"native admission conflicts with preparation: {case_id}")
            evidence = admission.pop("evidence_paths")
            row.update(admission)
            row["evidence_paths"].extend(evidence)
            row["native_state"] = "preparation_healthy_graph_blocked"
        eligibility = _eligibility_note(item, inventory, state_root)
        if eligibility is not None:
            supersession = _eligibility_supersession(item, state_root,
                                                    eligibility)
            if preparation is not None or admission is not None or \
                    (supersession is None and
                     (config_file.is_file() or checkpoint_path.is_file() or
                      receipt_path.is_file())):
                raise ValueError(f"native eligibility note conflicts with case: {case_id}")
            evidence = eligibility.pop("evidence_paths")
            row.update(eligibility)
            row["evidence_paths"].extend(evidence)
            if supersession is None:
                row["native_state"] = "skipped_no_eligible_original_cluster_test"
            else:
                evidence = supersession.pop("evidence_paths")
                row.update(supersession)
                row["evidence_paths"].extend(evidence)
                row["native_state"] = "not_completed"
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
            fingerprint = _terminal_fingerprint(item, config_root, state_root,
                                                source_archive_root)
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
                "elapsed_basis": _elapsed_basis(
                    native_root, receipt["fault_trials"],
                    receipt["elapsed_seconds"]),
                "target_throw_observed": receipt["target_throw_trials"] > 0,
                "target_exception_candidate": receipt["bug_candidate"],
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
            metric = read_coverage(item, config_root, state_root,
                                   source_archive_root)
            if metric is not None:
                row["strict_target_retained_fault_trials"] = metric[
                    "strict_target_retained_fault_trials"]
                row["strict_in_target_closure_trials"] = metric[
                    "strict_in_target_closure_trials"]
                row["closure_attribution_basis"] = (
                    "region_state_v1_same_occurrence_proxy; causal_target_"
                    "reachability_unverified")
                row["evidence_paths"].append(str(coverage_path(
                    state_root, case_id).resolve()))
                exact = _reviewed_exact_closure(
                    case_id, native_root, state_root,
                    metric["strict_target_retained_fault_trials"],
                    metric["strict_in_target_closure_trials"],
                    row["completion_receipt_sha256"])
                if exact is not None:
                    count, exact_path, exact_sha, index_path = exact
                    row["strict_in_target_closure_trials"] = count
                    exact_pin = obj(state_root / ".native-queue" /
                                    "closure-reviews" / f"{case_id}.json")
                    row["closure_attribution_basis"] = (
                        "original_finalizer_plan_exact_selected_occurrence_id_join; "
                        "temporal_causality_unverified" if exact_pin.get(
                            "audit_basis") == "selected_target_occurrence" else
                        "original_finalizer_plan_exact_occurrence_id_join; "
                        "temporal_causality_unverified")
                    row["closure_audit_path"] = str(exact_path)
                    row["closure_audit_sha256"] = exact_sha
                    row["evidence_paths"].extend((str(exact_path),
                                                   str((state_root / ".native-queue" /
                                                        "closure-reviews" /
                                                        f"{case_id}.json").resolve()),
                                                   str(index_path)))
            review_pin = (state_root / ".native-queue" / "reviews" /
                          f"{case_id}.json")
            if review_pin.is_file():
                pin = obj(review_pin)
                review_path = Path(pin.get("review_path", ""))
                if (pin.get("schema_version") != 1 or
                        pin.get("case_id") != case_id or
                        not review_path.is_absolute() or review_path.is_symlink() or
                        not review_path.is_file() or
                        sha(review_path) != pin.get("review_sha256") or
                        pin.get("checkpoint_sha256") != row["checkpoint_sha256"] or
                        pin.get("completion_receipt_sha256") != row[
                            "completion_receipt_sha256"]):
                    raise ValueError(f"native terminal review pin changed: {case_id}")
                row["terminal_review_path"] = str(review_path)
                row["terminal_review_sha256"] = pin["review_sha256"]
                identity = pin.get("identity_review")
                if identity is not None:
                    identity_path = Path(identity.get("path", ""))
                    if (not identity_path.is_absolute() or
                            identity_path.is_symlink() or
                            not identity_path.is_file() or
                            sha(identity_path) != identity.get("sha256")):
                        raise ValueError(f"native target identity review changed: {case_id}")
                    row["evidence_paths"].append(str(identity_path))
                note = pin.get("quality_note")
                if note is not None and (not isinstance(note, str) or not note):
                    raise ValueError(f"native terminal quality note is invalid: {case_id}")
                row["terminal_quality_note"] = note
                wall, static_wall = _reviewed_wall_timing(
                    obj(review_path), row["elapsed_seconds"])
                row["reviewed_campaign_wall_seconds"] = wall
                row["reviewed_static_to_terminal_wall_seconds"] = static_wall
                row["evidence_paths"].extend((str(review_path),
                                               str(review_pin.resolve())))
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
                          results_dir: Path, epoch_receipt: Path | None = None,
                          epoch_receipt_sha256: str | None = None
                          ) -> tuple[Path, Path]:
    _, _, epoch = load_queue_inventory(inventory, state_root,
                                       epoch_receipt, epoch_receipt_sha256)
    require_epoch_results_dir(results_dir, state_root, epoch)
    results_dir.mkdir(parents=True, exist_ok=True)
    with (results_dir / ".native-results.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = native_rows(inventory, ownership_file, config_root, state_root,
                           epoch_receipt, epoch_receipt_sha256)
        document = {"schema_version": 2 if epoch is not None else 1,
                    "method": "original_native_graphchecker_campaign",
                    "inventory_sha256": sha(inventory),
                    "ownership_sha256": sha(ownership_file),
                    "case_count": 102,
                    "verified_terminal_count": sum(
                        row["native_state"] == "verified_terminal" for row in rows),
                    "rows": rows}
        if epoch is not None:
            document["inventory_epoch"] = epoch
        tsv_stream = io.StringIO()
        fieldnames = (FIELDS + ("inventory_row_sha256", "inventory_epoch")
                      if epoch is not None else FIELDS)
        writer = csv.DictWriter(tsv_stream, fieldnames=fieldnames, delimiter="\t",
                                lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(row[key], sort_keys=True)
                             if isinstance(row[key], (dict, list)) else
                             "" if row[key] is None else row[key]
                             for key in fieldnames})
        json_path = results_dir / "native-102-results.json"
        tsv_path = results_dir / "native-102-results.tsv"
        _replace_text(json_path, json.dumps(document, sort_keys=True,
                                            indent=2) + "\n")
        _replace_text(tsv_path, tsv_stream.getvalue())
        return json_path, tsv_path
