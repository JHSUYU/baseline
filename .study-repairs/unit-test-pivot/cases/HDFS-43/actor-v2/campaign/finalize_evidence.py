#!/usr/bin/env python3
"""Freeze independently checked HDFS-43 V2 evidence after the tmux campaign."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
sys.path.insert(0, str(HERE))

from audit_v2 import run as audit_run  # noqa: E402
from run_campaign import atomic_json  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def classify_junit_failure(row: dict) -> str:
    if row["junit_exit"] == 0:
        return "passed"
    with gzip.open(row["junit_log_gzip"], "rt", errors="replace") as stream:
        matches = [line.strip() for line in stream
                   if line.startswith("testTruncateTwiceTogether(")]
    expected = (len(matches) == 1 and
                "HDFS-43 injected at RPC_RESPONSE_WAIT\ttruncate\tnn0\tclient\t"
                "/testTruncateTwiceTogether/file\t-1\t398#1" in matches[0])
    return "injected_client_truncate_response" if expected else "unclassified"


def add_artifact(paths: dict, path: Path) -> None:
    require(path.is_file(), f"missing raw artifact: {path}")
    paths[str(path.relative_to(CASE))] = {
        "absolute_path": str(path), "sha256": sha(path),
        "bytes": path.stat().st_size,
    }


def main() -> None:
    state = read(HERE / "checkpoint.json")
    completed = state["completed"]
    effective = [row for row in completed if row["strict_injection"] and
                 row["target_after_fault_same_actor"]]
    require(len(completed) == 125 and len(effective) == 80 and
            state["active"] is None and
            state["stop_reason"] == "effective_budget_reached" and
            state["extended"] is False,
            "campaign is not at its independently reviewed 80-effective terminal")
    report = audit_run()
    require(report["integrity_passed"] and not report["errors"] and
            report["audited_trials"] == 125 and report["strict"] == 84 and
            report["effective"] == 80 and report["expected_guard"] == 80 and
            report["extension_gate_novelty"] is False,
            "independent raw audit failed")
    failure_classes = Counter(classify_junit_failure(row) for row in effective)
    require(failure_classes == {"passed": 25,
                                "injected_client_truncate_response": 55},
            f"unexpected original JUnit outcome: {failure_classes}")
    require(all(row["bug_mark"] == "none" for row in completed),
            "new bug candidate requires separate replay/source review")

    artifacts: dict[str, dict] = {}
    archive_files: list[Path] = []
    for name in ("actor-seed", "actor-repeat"):
        root = CASE / "healthy" / name
        for relative in ("manifest.json", "trace/runtime_trace.jsonl",
                         "coverage.tsv", "jacoco.exec", "junit.log.gz"):
            path = root / relative
            add_artifact(artifacts, path)
            if relative in ("manifest.json", "trace/runtime_trace.jsonl"):
                archive_files.append(path)
    for number in range(1, 126):
        root = HERE / f"trial-{number:03d}"
        for relative in ("manifest.json", "trial-result.json",
                         "trace/runtime_trace.jsonl", "coverage.tsv.gz",
                         "jacoco.exec", "junit.log.gz"):
            path = root / relative
            add_artifact(artifacts, path)
            if relative in ("manifest.json", "trial-result.json",
                            "trace/runtime_trace.jsonl"):
                archive_files.append(path)
        plan = HERE / "plans" / f"trial-{number:03d}.tsv"
        add_artifact(artifacts, plan)
        archive_files.append(plan)
    for path in (HERE / "checkpoint.json", HERE / "trial-ledger.csv",
                 CASE / "system-test/build-probe.json"):
        add_artifact(artifacts, path)
        archive_files.append(path)

    archive_path = HERE / "raw-trace-selector-evidence.tar.gz"
    temporary = archive_path.with_name(archive_path.name + f".tmp.{os.getpid()}")
    with tarfile.open(temporary, "w:gz") as archive:
        for path in sorted(archive_files):
            archive.add(path, arcname=str(path.relative_to(CASE)),
                        recursive=False)
    os.replace(temporary, archive_path)
    manifest = {
        "case_id": "HDFS-43", "artifact_root": str(CASE),
        "trial_count": 125, "healthy_count": 2,
        "files": artifacts,
        "raw_trace_selector_archive": {
            "absolute_path": str(archive_path),
            "sha256": sha(archive_path), "bytes": archive_path.stat().st_size,
            "contents": "healthy/trial raw trace, selector plan, manifest, trial result, checkpoint, ledger, source build receipt",
        },
        "jacoco_regeneration_command": (
            "python3 system-test/run_coverage.py --exec <trial>/jacoco.exec "
            "--output <trial>/coverage.tsv"),
        "coverage_classes": "released Hadoop 3.4.3 HDFS/client/common JARs plus case-local production overrides; Probe/JUnit excluded",
        "sha256_generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    atomic_json(HERE / "final-artifact-manifest.json", manifest)
    atomic_json(HERE / "final-audit.json", report)

    kinds = Counter(identifier.split("\t", 1)[0]
                    for row in effective for identifier in row["new_coverage_ids"])
    summary = {
        "case_id": "HDFS-43", "status": "quality_complete",
        "attempts": 125, "requested_faults": sum(row["requested_faults"] for row in completed),
        "matched_faults": sum(row["matched_faults"] for row in completed),
        "applied_faults": sum(row["applied_faults"] for row in completed),
        "strict_trials": 84, "effective_trials": 80,
        "post_fault_target_exceptions": 80,
        "expected_original_guard_response_trials": 80,
        "bug_mark": "none", "original_junit_effective_outcomes": dict(failure_classes),
        "statuses": dict(Counter(row["status"] for row in completed)),
        "fault_depths": dict(Counter(len(row["sequence"]) for row in completed)),
        "coverage_gain_by_kind": dict(kinds),
        "new_stable_io_families": len({family for row in effective
                                       for family in row["new_io_family_ids"]}),
        "extension_gate_effective_73_to_80": [{
            "effective_number": index + 1, "trial_id": row["id"],
            "production_coverage_gain": row["new_coverage_count"],
            "new_stable_io_families": len(row["new_io_family_ids"]),
        } for index, row in enumerate(effective[72:80], 72)],
        "stop_reason": state["stop_reason"], "extended": False,
        "elapsed_seconds": read(CASE / "result.json")["elapsed_seconds"],
        "audit_sha256": sha(HERE / "final-audit.json"),
        "archive_sha256": sha(archive_path),
        "artifact_manifest_sha256": sha(HERE / "final-artifact-manifest.json"),
    }
    atomic_json(HERE / "final-summary.json", summary)
    result = read(CASE / "result.json")
    result.update({"status": "quality_complete", "final_audit": str(HERE / "final-audit.json"),
                   "final_summary": str(HERE / "final-summary.json"),
                   "artifact_manifest": str(HERE / "final-artifact-manifest.json"),
                   "raw_trace_selector_archive": str(archive_path),
                   "original_junit_effective_outcomes": dict(failure_classes),
                   "extension_gate_novelty": False,
                   "source_review": (
                       "FSDirTruncateOp.java:113-118 throws AlreadyBeingCreatedException "
                       "for a different second truncate length under recovery; "
                       "original TestFileTruncate.java:279-282 intercepts it")})
    atomic_json(CASE / "result.json", result)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
