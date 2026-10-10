#!/usr/bin/env python3
"""Import the sealed SOLR-38 terminal campaign after its offline gate correction."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile


BASE = Path(__file__).resolve().parents[2]
DATA = BASE / "data/mallory"
RAW = DATA / "pilot_observations/SOLR-38-strict-fault-node1-v3"
CANONICAL = DATA / "cases/SOLR-38"
PREFIX = "SOLR-38-strict-fault-node1-v3"
ARCHIVE = DATA / "evidence_archives" / f"{PREFIX}.tar.gz"
MANIFEST = DATA / "evidence_archives" / f"{PREFIX}.members.json"
SEAL = DATA / "evidence_archives" / f"{PREFIX}.receipt.json"
SALVAGE_DIR = BASE / "Mallory/adapters/solr/cases/SOLR-38/election-v3-offline-salvage-v4"
SALVAGE = SALVAGE_DIR / "salvage-receipt.json"
DEPTH = DATA / "quality_reviews/fault_depth/SOLR-38.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    if CANONICAL.exists():
        raise RuntimeError("SOLR-38 canonical result already exists")
    seal, salvage, manifest = read(SEAL), read(SALVAGE), read(MANIFEST)
    result, checkpoint = read(RAW / "result.json"), read(RAW / "checkpoint.json")
    if (not (sha(ARCHIVE) == seal.get("archive_sha256") == salvage.get("archive_sha256"))
            or sha(SEAL) != salvage.get("archive_receipt_sha256")
            or sha(MANIFEST) != seal.get("manifest_sha256")
            or seal.get("member_count") != 280
            or len(manifest.get("files", {})) != 280):
        raise RuntimeError("SOLR-38 sealed archive identity differs")
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        members = {}
        for item in tar:
            if not item.isfile() or not item.name.startswith(PREFIX + "/"):
                raise RuntimeError("unexpected archive member")
            name = item.name.removeprefix(PREFIX + "/")
            members[name] = hashlib.sha256(tar.extractfile(item).read()).hexdigest()
    if members != manifest["files"]:
        raise RuntimeError("SOLR-38 archive member SHA differs")
    if (salvage.get("eligible_for_canonical_completed_row") is not True
            or salvage.get("configured_campaign_complete") is not True
            or not (salvage.get("terminal_status") == result.get("status") == "queue_exhausted")
            or not (salvage.get("fault_trials_run") == result.get("fault_trials_completed") == 2)
            or salvage.get("same_actor_postfault_strict_target_trials") != 2
            or not (salvage.get("exact_target_exception_trials") == result.get("exact_exception_trials") == 0)
            or not (salvage.get("duration_seconds") == result.get("duration_seconds") == 53.985)
            or salvage.get("new_bug_confirmed") is not False
            or checkpoint.get("completed_trials") != [0, 1, 2]
            or seal.get("result_sha256") != sha(RAW / "result.json")
            or seal.get("offline_causal_audit_sha256") != sha(RAW / "offline-causal-audit.json")
            or salvage.get("old_offline_audit_sha256") != seal["offline_causal_audit_sha256"]):
        raise RuntimeError("corrected terminal evidence differs")
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "salvage.json"
        check = subprocess.run(["python3", "-B", str(SALVAGE_DIR / "audit.py"),
                                "--out", str(output)], cwd=BASE,
                               capture_output=True, text=True, timeout=90)
        if check.returncode or output.read_bytes() != SALVAGE.read_bytes():
            raise RuntimeError("independent correction replay differs")
    for name in ("result.json", "config.json", "checkpoint.json", "offline-causal-audit.json"):
        if sha(RAW / name) != manifest["files"][name]:
            raise RuntimeError(f"local raw differs from archive: {name}")
    if (read(DEPTH).get("campaign_result_sha256") != sha(RAW / "result.json")
            or read(DEPTH).get("depth_distribution") != {"1": 2}):
        raise RuntimeError("fault-depth provenance differs")
    CANONICAL.mkdir(parents=True)
    for name in ("result.json", "config.json", "checkpoint.json", "offline-causal-audit.json"):
        shutil.copyfile(RAW / name, CANONICAL / name)
    shutil.copyfile(SALVAGE, CANONICAL / "causal-audit-correction.json")
    campaigns = CANONICAL / "campaigns"
    campaigns.mkdir()
    compact = campaigns / "strict-v3"
    compact.mkdir()
    for name in ("result.json", "config.json", "checkpoint.json"):
        shutil.copyfile(RAW / name, compact / name)
    for number in (1, 2):
        trial = compact / "trials" / f"r{number:04d}"
        trial.mkdir(parents=True)
        shutil.copyfile(RAW / "trials" / f"r{number:04d}" / "result.json",
                        trial / "result.json")
    write(CANONICAL / "canonical-import-receipt.json", {
        "schema_version": 1, "case_id": "SOLR-38",
        "completion_criterion": "natural_queue_exhausted_after_two_eligible_typed_points",
        "status": "queue_exhausted", "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_result_sha256": sha(CANONICAL / "result.json"),
        "canonical_config_sha256": sha(CANONICAL / "config.json"),
        "canonical_checkpoint_sha256": sha(CANONICAL / "checkpoint.json"),
        "canonical_audit_sha256": sha(CANONICAL / "offline-causal-audit.json"),
        "salvage_receipt_sha256": sha(CANONICAL / "causal-audit-correction.json"),
        "salvage_auditor_sha256": sha(SALVAGE_DIR / "audit.py"),
        "archive_sha256": sha(ARCHIVE), "archive_manifest_sha256": sha(MANIFEST),
        "archive_receipt_sha256": sha(SEAL),
        "depth_review_sha256": sha(DEPTH),
        "original_audit_report_gate_passed": False,
        "corrected_same_actor_postfault_strict_target_trials": 2,
        "exact_exception_trials": 0, "new_bug": False,
    })
    print(json.dumps({"case_id": "SOLR-38", "completed_fault_trials": 2,
                      "import_receipt_sha256": sha(CANONICAL / "canonical-import-receipt.json")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
