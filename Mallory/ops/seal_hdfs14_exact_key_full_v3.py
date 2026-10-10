#!/usr/bin/env python3
"""SHA-seal the naturally completed HDFS-14 exact-key campaign."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/mallory"
NAME = "HDFS-14-early-dn-exact-key-full-v3"
RAW = DATA / "campaigns" / NAME
ARCHIVES = DATA / "evidence_archives"
CANONICAL = DATA / "cases/HDFS-14"
DEPTH = DATA / "quality_reviews/fault_depth/HDFS-14.json"
REMOTE = ARCHIVES / f"{NAME}.remote-sha.json"
ARCHIVE = ARCHIVES / f"{NAME}.tar.gz"
MEMBERS = ARCHIVES / f"{NAME}.members.json"
RECEIPT = ARCHIVES / f"{NAME}.receipt.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def main() -> None:
    assert not ARCHIVE.exists() and not MEMBERS.exists() and not RECEIPT.exists()
    assert not CANONICAL.exists()
    result = json.loads((RAW / "result.json").read_text())
    checkpoint = json.loads((RAW / "checkpoint.json").read_text())
    audit = json.loads((RAW / "offline-causal-audit.json").read_text())
    review = json.loads(DEPTH.read_text())
    remote = json.loads(REMOTE.read_text())
    assert result["case_id"] == checkpoint["case_id"] == audit["case_id"] == "HDFS-14"
    assert result["status"] == checkpoint["status"] == "queue_exhausted"
    assert result["fault_trials_completed"] == 9
    assert checkpoint["completed_trials"] == list(range(10))
    assert result["strict_injected_trials"] == result["strict_target_trials"] == 9
    assert result["exact_exception_trials"] == 0
    assert not checkpoint["target_exception_candidates"] and not checkpoint["reproduced_candidates"]
    assert audit["report_gate_passed"] is True
    assert review["depth_distribution"] == {"1": 2, "2": 3, "3": 4}
    raw_files = {str(p.relative_to(RAW)): sha(p) for p in RAW.rglob("*") if p.is_file()}
    for name, digest in remote["files"].items():
        assert raw_files[name] == digest, name
    assert len(raw_files) == len(remote["files"]) + 1
    assert set(raw_files) - set(remote["files"]) == {"offline-causal-audit.json"}

    with tarfile.open(ARCHIVE, "w:gz") as out:
        for name in sorted(raw_files):
            out.add(RAW / name, arcname=f"{NAME}/{name}", recursive=False)
    listed = []
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        for member in archive.getmembers():
            assert member.isfile()
            relative = member.name.removeprefix(f"{NAME}/")
            assert member.name == f"{NAME}/{relative}" and relative in raw_files
            extracted = archive.extractfile(member)
            assert extracted is not None
            data = extracted.read()
            digest = hashlib.sha256(data).hexdigest()
            assert digest == raw_files[relative] and len(data) == member.size
            listed.append({"path": member.name, "sha256": digest, "bytes": member.size})
    assert len(listed) == len(raw_files)
    write_json(MEMBERS, {"schema_version": 1, "case_id": "HDFS-14", "archive_sha256": sha(ARCHIVE),
                         "member_count": len(listed), "members": listed})
    receipt = {
        "schema_version": 1,
        "case_id": "HDFS-14",
        "kind": "full_campaign",
        "status": "queue_exhausted",
        "completion_criterion": "natural_full_terminal",
        "source_host": "node2",
        "source_path": "/tmp/mallory-hdfs14-early-dn-exact-key-v3-node2-full",
        "raw_local_path": str(RAW.relative_to(ROOT)),
        "issued_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "remote_file_count": len(remote["files"]),
        "remote_sha_index_sha256": sha(REMOTE),
        "archive_sha256": sha(ARCHIVE),
        "manifest_sha256": sha(MEMBERS),
        "file_count": len(listed),
        "result_sha256": sha(RAW / "result.json"),
        "config_sha256": sha(RAW / "config.json"),
        "checkpoint_sha256": sha(RAW / "checkpoint.json"),
        "audit_sha256": sha(RAW / "offline-causal-audit.json"),
        "depth_review_sha256": sha(DEPTH),
        "audit_report_gate_passed": True,
        "duration_seconds": result["duration_seconds"],
        "fault_trials_completed": 9,
        "strict_injected_trials": 9,
        "strict_target_trials": 9,
        "exact_exception_trials": 0,
        "new_bug": False,
    }
    write_json(RECEIPT, receipt)
    CANONICAL.mkdir(parents=True)
    for name in ("result.json", "config.json", "checkpoint.json", "offline-causal-audit.json"):
        shutil.copyfile(RAW / name, CANONICAL / name)
    campaigns = CANONICAL / "campaigns"
    campaigns.mkdir()
    (campaigns / "full-v3").symlink_to(os.path.relpath(RAW, campaigns))
    write_json(CANONICAL / "canonical-import-receipt.json", {
        "schema_version": 1,
        "case_id": "HDFS-14",
        "status": "queue_exhausted",
        "completion_criterion": "natural_full_terminal",
        "issued_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "canonical_result_sha256": sha(CANONICAL / "result.json"),
        "canonical_config_sha256": sha(CANONICAL / "config.json"),
        "canonical_checkpoint_sha256": sha(CANONICAL / "checkpoint.json"),
        "canonical_audit_sha256": sha(CANONICAL / "offline-causal-audit.json"),
        "archive_sha256": sha(ARCHIVE),
        "archive_receipt_sha256": sha(RECEIPT),
        "offhost_seal_sha256": sha(REMOTE),
        "file_count": len(listed),
    })
    print(json.dumps({"case_id": "HDFS-14", "status": result["status"],
                      "fault_trials_completed": 9, "audit_report_gate_passed": True,
                      "archive_sha256": sha(ARCHIVE), "receipt_sha256": sha(RECEIPT),
                      "result_sha256": sha(RAW / "result.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
