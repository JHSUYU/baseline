#!/usr/bin/env python3
"""Import the exhausted SOLR-15 continuation with exact resource attribution."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from Mallory.report.fault_depth_review import review as depth_review


BASE = Path(__file__).resolve().parents[2]
DATA = BASE / "data/mallory"
NAME = "SOLR-15-fault-bootstrap-node0-v3"
RAW = DATA / "solr15_fault_bootstrap_node0_v3"
CANONICAL = DATA / "cases/SOLR-15"
ARCHIVE = DATA / "evidence_archives" / f"{NAME}.tar.gz"
MEMBERS = DATA / "evidence_archives" / f"{NAME}.members.json"
SEAL = DATA / "evidence_archives" / f"{NAME}.receipt.json"
DEPTH = DATA / "quality_reviews/fault_depth/SOLR-15.json"
SOURCE = BASE / ".graphchecker-sources/solr-8.11.4"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    if CANONICAL.exists() or DEPTH.exists():
        raise RuntimeError("SOLR-15 canonical result or depth review already exists")
    seal, manifest = read(SEAL), read(MEMBERS)
    result, checkpoint = read(RAW / "result.json"), read(RAW / "checkpoint.json")
    quality = read(RAW / "terminal-quality.json")
    expected = {item["path"]: item["sha256"] for item in manifest["members"]}
    if (sha(ARCHIVE) != seal["archive_sha256"]
            or sha(MEMBERS) != seal["member_manifest_sha256"]
            or seal.get("all_archive_members_verified") is not True
            or seal.get("member_count") != len(expected)
            or len(expected) != 1249):
        raise RuntimeError("archive seal mismatch")
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        found = {item.name: hashlib.sha256(tar.extractfile(item).read()).hexdigest()
                 for item in tar if item.isfile()}
    if found != expected:
        raise RuntimeError("archive member hash mismatch")
    for name, key in (("result.json", "result_sha256"),
                      ("checkpoint.json", "checkpoint_sha256"),
                      ("terminal-quality.json", "quality_sidecar_sha256"),
                      ("fault-depth-review.json", "depth_review_sha256")):
        if sha(RAW / name) != seal[key]:
            raise RuntimeError(f"raw {name} differs from seal")
    if (result.get("case_id") != "SOLR-15"
            or not (result.get("status") == checkpoint.get("status") ==
                    quality.get("status") == "budget_exhausted")
            or result.get("duration_seconds") != 1251.752
            or result.get("fault_trials_completed") != 12
            or result.get("strict_injected_trials") != 5
            or result.get("strict_target_trials") != 4
            or result.get("exact_exception_trials") != 4
            or checkpoint.get("completed_trials") != list(range(13))
            or quality.get("campaign_completion_credited") is not True
            or quality.get("strict_candidate_trials") != [2, 3, 5, 6]
            or quality.get("prior_uncredited_trial") != 4
            or quality.get("new_dropped_uncredited_trials") != list(range(7, 13))
            or quality.get("new_strict_resource_valid_trials") != [5, 6]
            or quality.get("new_bug") is not False
            or seal.get("source_review") !=
            "expected protective SplitShardCmd @538 abort after live-node loss"):
        raise RuntimeError("bounded terminal or guard disposition differs")
    for number in range(1, 13):
        trial = read(RAW / "trials" / f"r{number:04d}" / "result.json")
        feedback = trial["feedback"]
        resource = trial["resource_attestation"]
        if trial.get("case_id") != "SOLR-15" or trial.get("trial_id") != number:
            raise RuntimeError(f"trial {number} identity differs")
        if number in (2, 3, 5, 6):
            if (resource.get("valid") is not True or
                    feedback.get("target_threw") is not True or
                    feedback.get("target_check_reached") is not True or
                    trial["junit_validation"].get("status") != "passed"):
                raise RuntimeError(f"trial {number} lacks valid guard proof")
        elif number in (4, 7, 8, 9, 10, 11, 12):
            if resource.get("valid") is not False:
                raise RuntimeError(f"trial {number} received unexpected credit")
    source_root = Path(read(RAW / "config.json")["mapping"]["source_root"])
    source_rel = "solr/core/src/java/org/apache/solr/cloud/api/collections/SplitShardCmd.java"
    test_rel = "solr/core/src/test/org/apache/solr/cloud/api/collections/ShardSplitTest.java"
    config = read(RAW / "config.json")
    if (sha(source_root / source_rel) != config["mapping"]["target_source_sha256"]
            or sha(source_root / test_rel) != config["mapping"]["test_source_sha256"]):
        raise RuntimeError("pinned Solr source differs")
    CANONICAL.mkdir(parents=True)
    for name in ("result.json", "config.json", "checkpoint.json"):
        shutil.copyfile(RAW / name, CANONICAL / name)
    shutil.copyfile(RAW / "terminal-quality.json", CANONICAL / "case-local-quality-audit.json")
    write(CANONICAL / "source-review.json", {
        "schema_version": 1,
        "case_id": "SOLR-15",
        "source_review_status": "expected_guard",
        "classification": "protective_leader_live_znode_guard",
        "new_bug": False,
        "source_root": str(source_root),
        "source_revision": config["mapping"]["source_git_revision"],
        "source_file": source_rel,
        "source_sha256": sha(source_root / source_rel),
        "test_file": test_rel,
        "test_sha256": sha(source_root / test_rel),
        "selected_check_line": 536,
        "selected_throw_line": 538,
        "same_resource_guard_trials": [2, 3, 5, 6],
        "uncredited_trials": [4, 7, 8, 9, 10, 11, 12],
        "source_reason": "SplitShardCmd marks subshards RECOVERY_FAILED and throws when the parent leader live znode is missing; the unchanged chaos JUnit permits split failure after stopping the leader.",
    })
    compact = CANONICAL / "campaigns/continuation-v3"
    compact.mkdir(parents=True)
    for name in ("result.json", "config.json", "checkpoint.json"):
        shutil.copyfile(RAW / name, compact / name)
    for number in range(1, 13):
        trial = compact / "trials" / f"r{number:04d}"
        trial.mkdir(parents=True)
        shutil.copyfile(RAW / "trials" / f"r{number:04d}" / "result.json",
                        trial / "result.json")
    write(DEPTH, depth_review(RAW))
    if (read(DEPTH)["depth_distribution"] != {"1": 1, "2": 2, "3": 9}
            or read(DEPTH)["fault_trials_completed"] != 12):
        raise RuntimeError("depth distribution differs")
    write(CANONICAL / "canonical-import-receipt.json", {
        "schema_version": 1,
        "case_id": "SOLR-15",
        "status": "budget_exhausted",
        "completion_criterion": "natural_bounded_continuation_budget_terminal",
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_result_sha256": sha(CANONICAL / "result.json"),
        "canonical_config_sha256": sha(CANONICAL / "config.json"),
        "canonical_checkpoint_sha256": sha(CANONICAL / "checkpoint.json"),
        "case_local_audit_sha256": sha(CANONICAL / "case-local-quality-audit.json"),
        "source_review_sha256": sha(CANONICAL / "source-review.json"),
        "depth_review_sha256": sha(DEPTH),
        "archive_sha256": sha(ARCHIVE),
        "archive_manifest_sha256": sha(MEMBERS),
        "archive_receipt_sha256": sha(SEAL),
        "strict_resource_guard_trials": [2, 3, 5, 6],
        "uncredited_trials": [4, 7, 8, 9, 10, 11, 12],
        "new_bug": False,
    })
    print(json.dumps({"case_id": "SOLR-15", "status": "budget_exhausted",
                      "canonical_import_sha256": sha(CANONICAL / "canonical-import-receipt.json")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
