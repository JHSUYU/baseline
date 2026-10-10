#!/usr/bin/env python3
"""Seal and import HDFS-48's naturally exhausted checkpoint continuation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile


BASE = Path(__file__).resolve().parents[2]
DATA = BASE / "data/mallory"
RAW = DATA / "campaigns/HDFS-48-rename-presend-full-v6"
INDEX = Path(str(RAW) + ".remote-sha-index.json")
CANONICAL = DATA / "cases/HDFS-48"
PREFIX = "HDFS-48-rename-presend-full-v6"
ARCHIVE = DATA / "evidence_archives" / f"{PREFIX}.tar.gz"
MANIFEST = DATA / "evidence_archives" / f"{PREFIX}.members.json"
RECEIPT = DATA / "evidence_archives" / f"{PREFIX}.receipt.json"
GO = BASE / "Mallory/adapters/hdfs/cases/hdfs48-rename-presend-node2-v6/admission-full-node2.json"
AUDITOR = BASE / "Mallory/adapters/hdfs/cases/hdfs48-rename-presend-node2-v6/audit_terminal.py"
DEPTH = DATA / "quality_reviews/fault_depth/HDFS-48.json"
V5 = DATA / "evidence_archives/HDFS-48-rename-presend-full-v5.receipt.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    if any(p.exists() for p in (ARCHIVE, MANIFEST, RECEIPT, CANONICAL)):
        raise RuntimeError("HDFS-48 v6 seal or canonical import already exists")
    index, result, checkpoint = read(INDEX), read(RAW / "result.json"), read(RAW / "checkpoint.json")
    audit, go, depth = read(RAW / "v6-strict-terminal-audit.json"), read(GO), read(DEPTH)
    if (index.get("source_host") != "node2"
            or index.get("source") != "/tmp/mallory-hdfs48-rename-presend-node2-full-v6"
            or len(index.get("files", {})) != 48):
        raise RuntimeError("unexpected node2 SHA index")
    for name, digest in index["files"].items():
        path = RAW / name
        if not path.is_file() or sha(path) != digest:
            raise RuntimeError(f"node2 raw changed: {name}")
    if (result.get("case_id") != "HDFS-48"
            or not (result.get("status") == checkpoint.get("status") == "queue_exhausted")
            or result.get("healthy_seed_valid") is not True
            or result.get("fault_trials_completed") != 3
            or result.get("strict_injected_trials") != 3
            or result.get("strict_target_trials") != 2
            or result.get("exact_exception_trials") != 0
            or checkpoint.get("completed_trials") != [0, 1, 2, 3]
            or checkpoint.get("queue") != []
            or audit.get("strict_gate_passed") is not True
            or audit.get("errors")
            or audit.get("campaign_result_sha256") != sha(RAW / "result.json")
            or audit.get("valid_fault_trials") != 2
            or audit.get("invalid_fault_trials") != 1
            or [row.get("classification") for row in audit.get("rows", [])] != [
                "healthy_seed", "strict_multifault_retry_rpc_target",
                "strict_multifault_retry_rpc_target", "postfault_retry_door_missing"]
            or audit.get("new_bug") is not False
            or go.get("go") is not True or go.get("host") != "node2"
            or go.get("config_sha256") != sha(RAW / "config.json")
            or go.get("v5_receipt_sha256") != sha(V5)
            or depth.get("campaign_result_sha256") != sha(RAW / "result.json")
            or depth.get("depth_distribution") != {"1": 1, "2": 1, "3": 1}):
        raise RuntimeError("v6 terminal or case-local quality claim changed")
    for number in range(4):
        trial = read(RAW / "trials" / f"r{number:04d}" / "result.json")
        if number < 3 and trial.get("junit_validation", {}).get("status") != "passed":
            raise RuntimeError("admitted HDFS-48 JUnit did not pass")
        if number == 3 and trial.get("junit_validation", {}).get("status") != "failed":
            raise RuntimeError("invalid depth-three JUnit status changed")

    shutil.copyfile(INDEX, RAW / "remote-sha-index.json")
    members = {str(p.relative_to(RAW)): sha(p) for p in sorted(RAW.rglob("*"))
               if p.is_file() and p.name != ".campaign.lock"}
    with tarfile.open(ARCHIVE, "w:gz") as tar:
        for name in sorted(members):
            tar.add(RAW / name, arcname=f"{PREFIX}/{name}", recursive=False)
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        found = {item.name.removeprefix(f"{PREFIX}/"):
                 hashlib.sha256(tar.extractfile(item).read()).hexdigest()
                 for item in tar if item.isfile()}
    if found != members:
        raise RuntimeError("archive member SHA mismatch")
    write(MANIFEST, {"schema_version": 1, "files": members})
    write(RECEIPT, {
        "schema_version": 1, "case_id": "HDFS-48", "kind": "full_continuation",
        "completion_criterion": "natural_queue_exhausted_with_sealed_v5_seed",
        "status": "queue_exhausted", "source_host": "node2", "source_path": index["source"],
        "raw_local_path": str(RAW.relative_to(BASE)),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "remote_file_count": len(index["files"]), "remote_sha_index_sha256": sha(INDEX),
        "archive_sha256": sha(ARCHIVE), "manifest_sha256": sha(MANIFEST),
        "member_count": len(members), "result_sha256": sha(RAW / "result.json"),
        "config_sha256": sha(RAW / "config.json"),
        "checkpoint_sha256": sha(RAW / "checkpoint.json"),
        "strict_audit_sha256": sha(RAW / "v6-strict-terminal-audit.json"),
        "strict_auditor_sha256": sha(AUDITOR),
        "admission_go_sha256": sha(GO), "v5_receipt_sha256": sha(V5),
        "depth_review_sha256": sha(DEPTH),
        "duration_seconds": result["duration_seconds"],
        "fault_trials_completed": 3, "strict_injected_trials": 3,
        "strict_target_trials": 2, "exact_exception_trials": 0,
        "valid_fault_trials": 2, "invalid_fault_trials": 1,
        "invalid_classification": "postfault_retry_door_missing",
        "new_bug": False,
    })
    CANONICAL.mkdir(parents=True)
    for name in ("result.json", "config.json", "checkpoint.json"):
        shutil.copyfile(RAW / name, CANONICAL / name)
    shutil.copyfile(RAW / "v6-strict-terminal-audit.json", CANONICAL / "case-local-causal-audit.json")
    compact = CANONICAL / "campaigns/continuation-v6"
    compact.mkdir(parents=True)
    for name in ("result.json", "config.json", "checkpoint.json"):
        shutil.copyfile(RAW / name, compact / name)
    for number in range(1, 4):
        trial = compact / "trials" / f"r{number:04d}"
        trial.mkdir(parents=True)
        shutil.copyfile(RAW / "trials" / f"r{number:04d}" / "result.json",
                        trial / "result.json")
    write(CANONICAL / "canonical-import-receipt.json", {
        "schema_version": 1, "case_id": "HDFS-48", "status": "queue_exhausted",
        "completion_criterion": "natural_queue_exhausted_with_sealed_v5_seed",
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "canonical_result_sha256": sha(CANONICAL / "result.json"),
        "canonical_config_sha256": sha(CANONICAL / "config.json"),
        "canonical_checkpoint_sha256": sha(CANONICAL / "checkpoint.json"),
        "case_local_audit_sha256": sha(CANONICAL / "case-local-causal-audit.json"),
        "archive_sha256": sha(ARCHIVE), "archive_manifest_sha256": sha(MANIFEST),
        "archive_receipt_sha256": sha(RECEIPT), "depth_review_sha256": sha(DEPTH),
        "strict_auditor_sha256": sha(AUDITOR),
        "valid_fault_trials": 2, "invalid_fault_trials": 1,
        "new_bug": False,
    })
    print(json.dumps({"archive_sha256": sha(ARCHIVE), "receipt_sha256": sha(RECEIPT),
                      "canonical_import_sha256": sha(CANONICAL / "canonical-import-receipt.json"),
                      "member_count": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
