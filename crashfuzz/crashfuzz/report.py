"""The 102-check table from a results root.

One row per original checklist check: its site and JUnit, the case's state,
trial counts, target reach, coverage gain and candidates, with the
source-review verdicts from ``data/`` applied (a reviewed candidate can be
rejected; an exact target throw alone is not a new bug).
"""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from typing import Any

from . import settings

COLUMNS = ("case_id", "system", "status", "finished", "bug_mark",
           "review_verdict", "review_reason", "review_evidence",
           "target_file", "target_function", "target_line", "target_site_id",
           "check_code", "cluster_test", "total_elapsed_seconds", "active_runtime_seconds",
           "healthy_seconds", "fault_trials", "active_trial", "strict_injections",
           "healthy_target_reached", "post_fault_target_reach_trials",
           "lost_target_trials", "target_outcome_changed_trials",
           "coverage_gain_methods", "coverage_gain_branches",
           "target_exception_candidates",
           "target_exception_triggered", "target_exception_trigger_trials",
           "target_exception_evidence_kind", "healthy_expected_target_exception",
           "first_target_exception_elapsed_seconds", "target_exception_review_evidence",
           "static_io_calls", "static_coverage_methods", "campaign_result", "error")
CANDIDATE_REVIEWS = settings.DATA / "static102-candidate-reviews.json"
TARGET_EXCEPTION_REVIEWS = settings.DATA / "static102-target-exception-reviews.json"


def enrich_live_trials(value: dict[str, Any], state: dict[str, Any]) -> None:
    """Trial counts of a running campaign, from its checkpoint."""
    statuses = [trial.get("status") for trial in state.get("completed", [])]
    value["fault_trials"] = len(statuses)
    value["strict_injections"] = sum(status not in (None, "unmatched") for status in statuses)
    value["post_fault_target_reach_trials"] = sum(
        status not in (None, "unmatched", "lost_target") for status in statuses)
    candidates = statuses.count("target_exception_candidate")
    value["target_exception_candidates"] = candidates
    if candidates:
        value["bug_mark"] = "candidate"


def reconcile_elapsed(value: dict[str, Any]) -> None:
    """A resumed worker's last wall segment cannot undercount earlier trials."""
    active = value.get("active_runtime_seconds")
    if active is None:
        return
    value["active_runtime_seconds"] = round(float(active), 3)
    value["total_elapsed_seconds"] = round(max(float(value.get("total_elapsed_seconds") or 0),
                                               float(active)), 3)


def apply_candidate_review(value: dict[str, Any], reviews: dict[str, dict]) -> None:
    count = int(value.get("target_exception_candidates") or 0)
    if count < 1:
        return
    review = reviews.get(value["case_id"])
    if not review or count > review.get("reviewed_candidate_count", 0):
        value["review_verdict"] = "pending_source_review"
        return
    value["review_verdict"] = review["verdict"]
    value["review_reason"] = review["reason"]
    value["review_evidence"] = review["evidence"]
    if review["verdict"].startswith("rejected_"):
        value["bug_mark"] = "rejected"


def apply_target_exception_review(value: dict[str, Any], reviews: dict[str, dict]) -> None:
    """Keep triggering the target check distinct from classifying a bug."""
    review = reviews.get(value["case_id"])
    if not review:
        return
    value["target_exception_triggered"] = True
    value["target_exception_trigger_trials"] = review["fault_trial_numbers"]
    value["target_exception_evidence_kind"] = review["evidence_kind"]
    value["healthy_expected_target_exception"] = review["healthy_expected"]
    value["first_target_exception_elapsed_seconds"] = review["first_trigger_elapsed_seconds"]
    value["target_exception_review_evidence"] = review["evidence"]


def infer_healthy_target_reach(value: dict[str, Any], base: Path) -> None:
    """Recover an omitted healthy reach flag from an exact CHECK_REACHED."""
    if value.get("healthy_target_reached") is not None:
        return
    target = value.get("target_site_id")
    trace = base / "healthy/runtime_trace.jsonl"
    if not target or not trace.is_file():
        return
    with trace.open() as events:
        for line in events:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") == "CHECK_REACHED" and event.get("siteId") == target:
                value["healthy_target_reached"] = True
                return


def enrich_result_metrics(value: dict[str, Any], record: dict[str, Any]) -> None:
    gain = record.get("coverage_gain_by_kind") or {}
    value["healthy_target_reached"] = record.get("target_reached")
    value["lost_target_trials"] = record.get("lost_target_trials")
    value["target_outcome_changed_trials"] = record.get("target_outcome_changed_trials")
    value["coverage_gain_methods"] = gain.get("methods")
    value["coverage_gain_branches"] = gain.get("branch_outcomes")


def enrich_live_summary(base: Path, value: dict[str, Any]) -> None:
    """A running case's numbers from its newest checkpoint of the current selection."""
    if value.get("status") != "fuzzing" or value.get("finished"):
        return
    artifact = (Path(value["selection_artifact"]) if value.get("selection_artifact") else
                base / ("caller-expanded/soot-selection.json"
                        if value.get("selection_profile") == "caller_expanded"
                        else "soot-selection.json"))
    digest = json.loads(artifact.read_text()).get("input_digest") if artifact.is_file() else None
    for state_path in sorted(base.glob("campaign*/" + value["case_id"] + "/state.json"),
                             key=lambda path: path.stat().st_mtime, reverse=True):
        state = json.loads(state_path.read_text())
        if digest and state.get("static_selection_digest") != digest:
            continue
        enrich_live_trials(value, state)
        active = state.get("active")
        value["active_trial"] = active.get("number") if isinstance(active, dict) else None
        value["active_runtime_seconds"] = state.get("active_runtime_seconds")
        result_path = state_path.with_name("result.json")
        if result_path.is_file():
            enrich_result_metrics(value, json.loads(result_path.read_text()))
        break


def case_summaries(results: Path) -> dict[str, dict[str, Any]]:
    """Every case summary under a results root, enriched from its campaign."""
    summaries = {}
    for path in results.glob("*/case-summary.json"):
        try:
            value = json.loads(path.read_text())
            if value.get("campaign_result"):
                result_path = Path(value["campaign_result"])
                if result_path.is_file():
                    record = json.loads(result_path.read_text())
                    enrich_result_metrics(value, record)
                    if not value.get("active_runtime_seconds"):
                        value["active_runtime_seconds"] = record.get("total_elapsed_seconds")
            enrich_live_summary(path.parent, value)
            reconcile_elapsed(value)
            summaries[value["case_id"]] = value
        except (OSError, ValueError, KeyError):
            continue
    return summaries


def _load_cases(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text()).get("cases", {}) if path.is_file() else {}


def table(results: Path, checklist: Path = settings.CHECKLIST) -> list[dict[str, Any]]:
    original = [row for row in json.loads(checklist.read_text())["rows"]
                if row.get("selection_group") == "original_102"]
    reviews = _load_cases(CANDIDATE_REVIEWS)
    target_exceptions = _load_cases(TARGET_EXCEPTION_REVIEWS)
    summaries = case_summaries(results)
    rows = []
    for row in original:
        location = row["exact_check_location"]
        merged = {"case_id": row["case_id"], "system": row["system"], "status": "pending",
                  "finished": False, "bug_mark": "none", "target_file": location["file"],
                  "target_function": location["enclosing_function"],
                  "target_line": location["selected_line"], "target_site_id": location["site_id"],
                  "check_code": row.get("check_code"), "cluster_test": row.get("cluster_test"),
                  **summaries.get(row["case_id"], {})}
        infer_healthy_target_reach(merged, results / row["case_id"])
        apply_candidate_review(merged, reviews)
        apply_target_exception_review(merged, target_exceptions)
        rows.append(merged)
    return rows


def write_tsv(rows: list[dict[str, Any]], output: Path) -> None:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n",
                            extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: (value.replace("\r", " ").replace("\n", "\\n")
                               if isinstance(value, str) else value)
                         for key, value in row.items()})
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".tmp.{os.getpid()}")
    temporary.write_text(buffer.getvalue())
    os.replace(temporary, output)
