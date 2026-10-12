#!/usr/bin/env python3
"""Export only terminal SOLR-10 role-campaign evidence, excluding scratch."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

TERMINAL = {"budget_exhausted", "queue_exhausted", "healthy_seed_invalid",
            "healthy_node_identity_missing", "healthy_seed_ambiguous",
            "healthy_no_injectable_door", "healthy_attestation_failed",
            "fault_trials_not_attested"}
SELECTED = ("plan.json", "result.json", "junit-receipt.json", "pilot-result.json",
            "sites.jsonl", "events.jsonl.gz", "events.jsonl")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while data := stream.read(1024 * 1024):
            h.update(data)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--export", type=Path, required=True)
    args = parser.parse_args()
    source = args.campaign.resolve(strict=True)
    result = json.loads((source / "result.json").read_text())
    if result.get("case_id") != "SOLR-10" or result.get("status") not in TERMINAL:
        raise ValueError("SOLR-10 campaign is not terminal")
    rows = result.get("trials", [])
    if not rows or len(rows) > 81 or result.get("fault_trials_completed") != len(rows) - 1:
        raise ValueError("terminal trial count or budget is inconsistent")
    destination = args.export.resolve()
    if destination.exists() or source == destination or source in destination.parents:
        raise ValueError("export must be a fresh path outside campaign scratch")
    destination.mkdir(parents=True)
    files = []
    try:
        def copy(relative: Path) -> None:
            original = source / relative
            if not original.is_file():
                raise FileNotFoundError(original)
            copied = destination / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, copied)
            original_sha = digest(original)
            if digest(copied) != original_sha:
                raise ValueError(f"copy SHA mismatch: {relative}")
            files.append({"path": relative.as_posix(), "sha256": original_sha,
                          "bytes": copied.stat().st_size})

        for name in ("config.json", "checkpoint.json", "result.json"):
            copy(Path(name))
        table = []
        for row in rows:
            trial_id = row["trial_id"]
            trial = Path("trials") / f"r{trial_id:04d}"
            detail = json.loads((source / trial / "result.json").read_text())
            if detail.get("trial_id") != trial_id or detail.get("case_id") != "SOLR-10":
                raise ValueError(f"trial identity mismatch: {trial_id}")
            for name in SELECTED:
                path = source / trial / name
                if path.is_file():
                    copy(trial / name)
            evidence = detail.get("events_evidence", {})
            event_name = evidence.get("gzip_path") or evidence.get("raw_path")
            if not event_name or not (destination / trial / event_name).is_file():
                raise ValueError(f"trial {trial_id} lacks archived event evidence")
            expected = evidence.get("gzip_sha256") or evidence.get("raw_sha256")
            if digest(destination / trial / event_name) != expected:
                raise ValueError(f"trial {trial_id} event receipt mismatch")
            feedback = detail.get("feedback", {})
            table.append({"trial_id": trial_id, "seconds": detail.get("elapsed_seconds"),
                          "status": feedback.get("status"),
                          "faults": len(detail.get("plan", [])),
                          "all_faults_effective": feedback.get("all_faults_effective"),
                          "role_identity_valid": feedback.get("role_identity_valid"),
                          "postfault_event_path_valid": feedback.get("postfault_event_path_valid"),
                          "target_reached": feedback.get("target_reached"),
                          "target_exception_candidate": feedback.get("target_exception_candidate"),
                          "junit_status": detail.get("junit_validation", {}).get("status")})
        table_file = destination / "terminal-table.csv"
        with table_file.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(table[0]))
            writer.writeheader()
            writer.writerows(table)
        manifest = {"schema_version": 1, "case_id": "SOLR-10", "host": "node2",
                    "status": result["status"], "trials": len(rows),
                    "scratch_excluded": ["classes/", "stdout.log", "stderr.log",
                                         "junit.log", "agent.properties", "*.tmp"],
                    "files": files, "table_sha256": digest(table_file)}
        (destination / "evidence-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"export": str(destination), "trial_count": len(rows),
                          "manifest_sha256": digest(destination / "evidence-manifest.json")},
                         sort_keys=True))
    except BaseException:
        shutil.rmtree(destination)
        raise


if __name__ == "__main__":
    main()
