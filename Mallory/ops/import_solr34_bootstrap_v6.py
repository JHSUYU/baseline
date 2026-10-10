#!/usr/bin/env python3
"""Import SOLR-34's exhausted bootstrap with its target-absent limitation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile


BASE = Path(__file__).resolve().parents[2]
DATA = BASE / "data/mallory"
NAME = "SOLR-34-fault-bootstrap-node1-v6"
RAW = DATA / "pilot_observations" / NAME
CANONICAL = DATA / "cases/SOLR-34"
ARCHIVE = DATA / "evidence_archives" / f"{NAME}.tar.gz"
MEMBERS = DATA / "evidence_archives" / f"{NAME}.members.json"
SEAL = DATA / "evidence_archives" / f"{NAME}.receipt.json"
DEPTH = DATA / "quality_reviews/fault_depth/SOLR-34.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def main() -> None:
    if CANONICAL.exists():
        raise RuntimeError("SOLR-34 canonical case already exists")
    seal, manifest = read(SEAL), read(MEMBERS)
    result, checkpoint = read(RAW / "result.json"), read(RAW / "checkpoint.json")
    audit, depth = read(RAW / "bootstrap-outcome-audit.json"), read(DEPTH)
    if (sha(ARCHIVE) != seal.get("archive_sha256")
            or sha(MEMBERS) != seal.get("manifest_sha256")
            or seal.get("member_count") != 1202
            or len(manifest.get("files", {})) != 1202):
        raise RuntimeError("sealed SOLR-34 archive identity differs")
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        found = {item.name.removeprefix(NAME + "/"):
                 hashlib.sha256(tar.extractfile(item).read()).hexdigest()
                 for item in tar if item.isfile() and item.name.startswith(NAME + "/")}
    if found != manifest["files"]:
        raise RuntimeError("archive member hash mismatch")
    if (not (result.get("status") == checkpoint.get("status") == "budget_exhausted")
            or result.get("healthy_seed_valid") is not False
            or result.get("fault_trials_completed") != 12
            or result.get("strict_injected_trials") != 11
            or result.get("strict_target_trials") != 0
            or result.get("target_reached_trials") != 0
            or result.get("exact_exception_trials") != 0
            or checkpoint.get("completed_trials") != list(range(13))
            or audit.get("check_completed") is not False
            or audit.get("fully_attributed_fault_trials") != 11
            or audit.get("partially_applied_fault_trials") != 1
            or audit.get("exact_target_check_events") != 0
            or audit.get("exact_target_throw_events") != 0
            or audit.get("junit_passed_trials") != 13
            or audit.get("new_bug_confirmed") is not False
            or seal.get("bootstrap_outcome_audit_sha256") != sha(RAW / "bootstrap-outcome-audit.json")
            or seal.get("result_sha256") != sha(RAW / "result.json")
            or depth.get("campaign_result_sha256") != sha(RAW / "result.json")
            or depth.get("depth_distribution") != {"1": 6, "2": 6}):
        raise RuntimeError("terminal budget or target-absent quality differs")
    for name in ("result.json", "config.json", "checkpoint.json", "bootstrap-outcome-audit.json"):
        if sha(RAW / name) != manifest["files"][name]:
            raise RuntimeError(f"local SOLR-34 raw differs: {name}")
    CANONICAL.mkdir(parents=True)
    for name in ("result.json", "config.json", "checkpoint.json"):
        shutil.copyfile(RAW / name, CANONICAL / name)
    shutil.copyfile(RAW / "bootstrap-outcome-audit.json",
                    CANONICAL / "case-local-quality-audit.json")
    compact = CANONICAL / "campaigns/bootstrap-v6"
    compact.mkdir(parents=True)
    for name in ("result.json", "config.json", "checkpoint.json"):
        shutil.copyfile(RAW / name, compact / name)
    for number in range(1, 13):
        trial = compact / "trials" / f"r{number:04d}"
        trial.mkdir(parents=True)
        shutil.copyfile(RAW / "trials" / f"r{number:04d}" / "result.json",
                        trial / "result.json")
    write(CANONICAL / "canonical-import-receipt.json", {
        "schema_version": 1, "case_id": "SOLR-34", "status": "budget_exhausted",
        "completion_criterion": "natural_bounded_bootstrap_budget_terminal",
        "quality_classification": "target_not_activated_under_faults",
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_result_sha256": sha(CANONICAL / "result.json"),
        "canonical_config_sha256": sha(CANONICAL / "config.json"),
        "canonical_checkpoint_sha256": sha(CANONICAL / "checkpoint.json"),
        "case_local_audit_sha256": sha(CANONICAL / "case-local-quality-audit.json"),
        "archive_sha256": sha(ARCHIVE),
        "archive_manifest_sha256": sha(MEMBERS),
        "archive_receipt_sha256": sha(SEAL),
        "depth_review_sha256": sha(DEPTH),
        "fault_trials_completed": 12, "fully_attributed_fault_trials": 11,
        "partially_applied_fault_trials": 1,
        "exact_target_check_events": 0, "exact_target_throw_events": 0,
        "original_audit_check_completed": False,
        "new_bug": False,
    })
    print(json.dumps({"case_id": "SOLR-34", "archive_sha256": sha(ARCHIVE),
                      "canonical_import_sha256": sha(CANONICAL / "canonical-import-receipt.json")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
