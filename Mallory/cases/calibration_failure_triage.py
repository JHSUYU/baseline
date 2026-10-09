#!/usr/bin/env python3
"""Summarize terminal healthy calibrations without promoting them to fuzz results."""

from __future__ import annotations

import json
import re
import tarfile
from collections import Counter
from pathlib import Path


BASE = Path(__file__).resolve().parents[2]
DATA = BASE / "data" / "mallory"
HERE = Path(__file__).resolve().parent
RECOVERY_RECEIPTS = {
    "HDFS-48": DATA / "calibration" / "HDFS-48" / "callthrow-healthy-v2" / "calibration.json",
}


def trial_file(root: Path, name: str) -> bytes | None:
    path = root / "trials" / "r0000" / name
    if path.is_file():
        return path.read_bytes()
    archive = DATA / "evidence_archives" / root.parent.name / (root.name + ".tar.gz")
    if archive.is_file():
        with tarfile.open(archive, "r:gz") as handle:
            try:
                member = handle.extractfile("trials/r0000/" + name)
                return member.read() if member is not None else None
            except KeyError:
                pass
    return None


def category(case_id: str, campaign: dict, feedback: dict, stdout: str,
             junit_log: str) -> str:
    status = campaign["status"]
    detail = feedback.get("status")
    if status == "calibration_complete":
        return "healthy_seed_valid_only"
    if case_id == "HDFS-48" and ("initializationError" in stdout
                                 or "initializationError" in junit_log):
        return "instrumentation_runner_error"
    if status == "healthy_node_identity_missing":
        return "target_node_identity_missing"
    if status == "healthy_no_injectable_door":
        return "no_injectable_door_in_closure"
    if detail == "healthy_target_exception":
        return "selected_target_exception_in_healthy_run"
    if detail == "trace_truncated":
        return "trace_truncated_before_valid_seed"
    if "MALLORY_TEST_ASSUMPTION" in junit_log:
        return "junit_assumption_disabled_workload"
    if re.search(r"Tests run:\s*0\b", stdout):
        return "junit_zero_tests"
    if detail == "target_site_not_woven":
        return "target_site_not_woven_or_class_unloaded"
    if detail == "healthy_target_missing":
        return "selected_target_not_reached"
    if detail and detail.startswith("workload_failed"):
        return "workload_failed_before_valid_seed"
    return "other_invalid_healthy_seed"


def main() -> None:
    latest: dict[str, tuple[int, Path]] = {}
    for root in DATA.glob("calibration*"):
        if not root.is_dir():
            continue
        suffix = root.name.removeprefix("calibration")
        rank = int(suffix[2:]) if suffix.startswith("_v") and suffix[2:].isdigit() else 1
        for path in root.glob("*/result.json"):
            if json.loads(path.read_text()).get("status") == "running":
                continue
            current = latest.get(path.parent.name)
            if current is None or rank > current[0]:
                latest[path.parent.name] = rank, path.parent
    rows = []
    for case_id, (_, root) in sorted(latest.items()):
        campaign = json.loads((root / "result.json").read_text())
        raw = trial_file(root, "result.json")
        trial = json.loads(raw) if raw else {}
        feedback = trial.get("feedback", {})
        stdout = (trial_file(root, "stdout.log") or b"").decode(errors="replace")
        junit_log = (trial_file(root, "junit.log") or b"").decode(errors="replace")
        junit_summaries = re.findall(
            r"Tests run:\s*\d+,\s*Failures:\s*\d+,\s*Errors:\s*\d+,\s*Skipped:\s*\d+",
            stdout)
        row = {
            "case_id": case_id,
            "system": campaign["system"],
            "calibration_root": str(root.relative_to(BASE)),
            "campaign_status": campaign["status"],
            "root_cause_group": category(case_id, campaign, feedback, stdout, junit_log),
            "feedback_status": feedback.get("status"),
            "junit_summary": junit_summaries[-1] if junit_summaries else None,
            "target_reached": feedback.get("target_reached"),
            "target_threw": feedback.get("target_threw"),
            "target_identity_complete": feedback.get("target_identity_complete"),
            "eligible_doors_before_target": feedback.get("eligible_doors_before_target"),
            "healthy_seed_valid": campaign.get("healthy_seed_valid"),
            "fault_trials_completed": campaign.get("fault_trials_completed", 0),
        }
        receipt_path = RECOVERY_RECEIPTS.get(case_id)
        if receipt_path and receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text())
            if (receipt.get("campaign_status") == "calibration_complete"
                    and receipt.get("junit_status") == "passed"
                    and receipt.get("junit_tests", 0) > 0
                    and receipt.get("target_reached") is True
                    and receipt.get("target_identity_gap_count") == 0
                    and receipt.get("site_catalog_valid") is True
                    and receipt.get("class_hash_match") is True):
                row["superseded_first_pass_root_cause"] = row["root_cause_group"]
                row["root_cause_group"] = "healthy_seed_valid_only"
                row["calibration_root"] = str(receipt_path.parent.relative_to(BASE))
                row["recovery_receipt"] = str(receipt_path.relative_to(BASE))
                row["campaign_status"] = receipt["campaign_status"]
                row["target_reached"] = True
                row["target_threw"] = receipt.get("target_exception_candidate")
                row["target_identity_complete"] = True
                row["eligible_doors_before_target"] = receipt.get("eligible_doors_before_target")
                row["healthy_seed_valid"] = True
                row["fault_trials_completed"] = 0
        rows.append(row)
    result = {
        "schema_version": 1,
        "scope": "Latest terminal healthy calibration per case in data/mallory/calibration*",
        "interpretation": "A valid healthy seed is not a completed fault campaign or a bug result.",
        "case_count": len(rows),
        "root_cause_counts": dict(sorted(Counter(r["root_cause_group"] for r in rows).items())),
        "cases": rows,
    }
    (HERE / "calibration_failure_triage.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(result["case_count"], result["root_cause_counts"])


if __name__ == "__main__":
    main()
