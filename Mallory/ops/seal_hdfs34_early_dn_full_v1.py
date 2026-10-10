#!/usr/bin/env python3
"""SHA-seal and import the naturally completed HDFS-34 full campaign."""

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
CASE = "HDFS-34"
NAME = "HDFS-34-early-dn-full-v1"
RAW = DATA / "campaigns" / NAME
ARCHIVES = DATA / "evidence_archives"
CANONICAL = DATA / "cases" / CASE
DEPTH = DATA / "quality_reviews/fault_depth/HDFS-34.json"
REMOTE = ARCHIVES / f"{NAME}.remote-sha.json"
ARCHIVE = ARCHIVES / f"{NAME}.tar.gz"
MEMBERS = ARCHIVES / f"{NAME}.members.json"
RECEIPT = ARCHIVES / f"{NAME}.receipt.json"
CONFIG = ROOT / "Mallory/adapters/hdfs/cases/hdfs34-early-dn-full-v1/HDFS-34-node2-full-v1.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> None:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT, CANONICAL)):
        raise RuntimeError("HDFS-34 seal or canonical import already exists")
    result = json.loads((RAW / "result.json").read_text())
    checkpoint = json.loads((RAW / "checkpoint.json").read_text())
    audit = json.loads((RAW / "offline-causal-audit.json").read_text())
    gate = json.loads((RAW / "healthy-gate.json").read_text())
    depth = json.loads(DEPTH.read_text())
    remote = json.loads(REMOTE.read_text())
    if not (result["case_id"] == checkpoint["case_id"] == audit["case_id"] == CASE
            and result["status"] == checkpoint["status"] == "budget_exhausted"
            and result["fault_trials_completed"] == 80
            and checkpoint["completed_trials"] == list(range(81))
            and checkpoint["running"] is None
            and result["strict_injected_trials"] == 80
            and result["strict_target_trials"] == 78
            and result["exact_exception_trials"] == 0
            and result["duration_seconds"] == 1682.826
            and not checkpoint["target_exception_candidates"]
            and not checkpoint["reproduced_candidates"]
            and gate["passed"] is True
            and depth["depth_distribution"] == {"1": 8, "2": 23, "3": 49}
            and audit["report_gate_passed"] is True
            and all(audit[key] is True for key in
                    ("archive_integrity_valid", "applied_fault_identity_valid",
                     "target_claims_reverified", "guidance_consistent",
                     "healthy_closure_proven", "same_actor_target_gate_passed"))
            and sha(RAW / "config.json") == sha(CONFIG)):
        raise RuntimeError("HDFS-34 terminal, quality, or pinned config changed")
    raw_files = {str(path.relative_to(RAW)): sha(path)
                 for path in RAW.rglob("*") if path.is_file()}
    if (set(raw_files) - set(remote["files"]) != {"offline-causal-audit.json"}
            or any(raw_files.get(name) != digest
                   for name, digest in remote["files"].items())):
        raise RuntimeError("local raw differs from node2 SHA index")
    with tarfile.open(ARCHIVE, "w:gz") as archive:
        for name in sorted(raw_files):
            archive.add(RAW / name, arcname=f"{NAME}/{name}", recursive=False)
    listed = []
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        for member in archive:
            if not member.isfile():
                raise RuntimeError("non-file archive member")
            name = member.name.removeprefix(f"{NAME}/")
            if member.name != f"{NAME}/{name}" or name not in raw_files:
                raise RuntimeError("unexpected archive member")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError("unreadable archive member")
            payload = extracted.read()
            digest = hashlib.sha256(payload).hexdigest()
            if digest != raw_files[name] or len(payload) != member.size:
                raise RuntimeError(f"archive member mismatch: {name}")
            listed.append({"path": member.name, "sha256": digest,
                           "bytes": member.size})
    if len(listed) != len(raw_files):
        raise RuntimeError("archive member count mismatch")
    write_json(MEMBERS, {"schema_version": 1, "case_id": CASE,
                         "archive_sha256": sha(ARCHIVE),
                         "member_count": len(listed), "members": listed})
    receipt = {
        "schema_version": 1, "case_id": CASE, "kind": "full_campaign",
        "status": "budget_exhausted", "completion_criterion": "natural_full_terminal",
        "source_host": "node2", "source_path": remote["source_path"],
        "raw_local_path": str(RAW.relative_to(ROOT)),
        "issued_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "remote_file_count": len(remote["files"]),
        "remote_sha_index_sha256": sha(REMOTE),
        "archive_sha256": sha(ARCHIVE), "manifest_sha256": sha(MEMBERS),
        "file_count": len(listed), "result_sha256": sha(RAW / "result.json"),
        "config_sha256": sha(RAW / "config.json"),
        "checkpoint_sha256": sha(RAW / "checkpoint.json"),
        "audit_sha256": sha(RAW / "offline-causal-audit.json"),
        "healthy_gate_sha256": sha(RAW / "healthy-gate.json"),
        "depth_review_sha256": sha(DEPTH), "audit_report_gate_passed": True,
        "duration_seconds": 1682.826, "fault_trials_completed": 80,
        "strict_injected_trials": 80, "strict_target_trials": 78,
        "exact_exception_trials": 0, "new_bug": False,
    }
    write_json(RECEIPT, receipt)
    CANONICAL.mkdir(parents=True)
    for name in ("result.json", "config.json", "checkpoint.json",
                 "offline-causal-audit.json", "healthy-gate.json"):
        shutil.copyfile(RAW / name, CANONICAL / name)
    campaigns = CANONICAL / "campaigns"
    campaigns.mkdir()
    (campaigns / "full-v1").symlink_to(os.path.relpath(RAW, campaigns))
    write_json(CANONICAL / "canonical-import-receipt.json", {
        "schema_version": 1, "case_id": CASE, "status": "budget_exhausted",
        "completion_criterion": "natural_full_terminal",
        "issued_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "canonical_result_sha256": sha(CANONICAL / "result.json"),
        "canonical_config_sha256": sha(CANONICAL / "config.json"),
        "canonical_checkpoint_sha256": sha(CANONICAL / "checkpoint.json"),
        "canonical_audit_sha256": sha(CANONICAL / "offline-causal-audit.json"),
        "archive_sha256": sha(ARCHIVE),
        "archive_receipt_sha256": sha(RECEIPT),
        "offhost_seal_sha256": sha(REMOTE), "file_count": len(listed),
    })
    print(json.dumps({"case_id": CASE, "status": result["status"],
                      "fault_trials_completed": 80, "audit_report_gate_passed": True,
                      "archive_sha256": sha(ARCHIVE), "receipt_sha256": sha(RECEIPT),
                      "result_sha256": sha(RAW / "result.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
