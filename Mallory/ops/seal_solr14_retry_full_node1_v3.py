#!/usr/bin/env python3
"""SHA-seal the naturally completed SOLR-14 retrying full campaign."""

import datetime as dt
import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/mallory"
NAME = "SOLR-14-retry-junit-full-node1-v3"
RAW = DATA / "campaigns" / NAME
ARCHIVES = DATA / "evidence_archives"
REMOTE = ARCHIVES / f"{NAME}.remote-sha.json"
ARCHIVE = ARCHIVES / f"{NAME}.tar.gz"
MEMBERS = ARCHIVES / f"{NAME}.members.json"
RECEIPT = ARCHIVES / f"{NAME}.receipt.json"
CANONICAL = DATA / "cases/SOLR-14"
DEPTH = DATA / "quality_reviews/fault_depth/SOLR-14.json"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def main():
    if any(p.exists() for p in (ARCHIVE, MEMBERS, RECEIPT, CANONICAL)):
        raise RuntimeError("SOLR-14 full seal already exists")
    result = json.loads((RAW / "result.json").read_text())
    checkpoint = json.loads((RAW / "checkpoint.json").read_text())
    audit = json.loads((RAW / "offline-causal-audit.json").read_text())
    depth = json.loads(DEPTH.read_text())
    remote = json.loads(REMOTE.read_text())
    if not (result["case_id"] == checkpoint["case_id"] == audit["case_id"] == "SOLR-14"
            and result["status"] == checkpoint["status"] == "queue_exhausted"
            and result["duration_seconds"] == 246.277
            and result["fault_trials_completed"] == 8
            and result["strict_injected_trials"] == 8
            and result["strict_target_trials"] == 2
            and result["exact_exception_trials"] == 0
            and not checkpoint["target_exception_candidates"]
            and not checkpoint["reproduced_candidates"]
            and audit["archive_integrity_valid"] and audit["applied_fault_identity_valid"]
            and audit["target_claims_reverified"] and audit["guidance_consistent"]
            and audit["healthy_closure_proven"]
            and not audit["same_actor_target_gate_passed"]
            and not audit["report_gate_passed"]
            and depth["depth_distribution"] == {"1": 4, "2": 4}):
        raise RuntimeError("SOLR-14 terminal or quality evidence changed")
    raw_files = {}
    for p in sorted(RAW.rglob("*")):
        if p.is_file() and p.name != ".campaign.lock":
            raw_files[str(p.relative_to(RAW))] = sha(p)
    for name, digest in remote["files"].items():
        if raw_files.get(name) != digest:
            raise RuntimeError(f"remote evidence changed: {name}")
    if set(raw_files) - set(remote["files"]) != {"offline-causal-audit.json"}:
        raise RuntimeError("unexpected local campaign files")
    with tarfile.open(ARCHIVE, "w:gz") as out:
        for name in sorted(raw_files):
            out.add(RAW / name, arcname=f"{NAME}/{name}", recursive=False)
    listed = []
    with tarfile.open(ARCHIVE, "r:gz") as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith(f"{NAME}/"):
                raise RuntimeError("unexpected archive member")
            name = member.name.removeprefix(f"{NAME}/")
            extracted = archive.extractfile(member)
            if name not in raw_files or extracted is None:
                raise RuntimeError("archive member absent from index")
            digest = hashlib.sha256(extracted.read()).hexdigest()
            if digest != raw_files[name]:
                raise RuntimeError(f"archive member changed: {name}")
            listed.append({"path": member.name, "sha256": digest, "bytes": member.size})
    if len(listed) != len(raw_files):
        raise RuntimeError("archive member count differs")
    write_json(MEMBERS, {"schema_version": 1, "case_id": "SOLR-14",
                         "archive_sha256": sha(ARCHIVE), "member_count": len(listed),
                         "members": listed})
    write_json(RECEIPT, {
        "schema_version": 1, "case_id": "SOLR-14", "kind": "full_campaign",
        "status": "queue_exhausted", "completion_criterion": "natural_full_terminal",
        "source_host": "node1", "source_path": remote["source"],
        "raw_local_path": str(RAW.relative_to(ROOT)),
        "issued_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "remote_file_count": len(remote["files"]),
        "remote_sha_index_sha256": sha(REMOTE),
        "archive_sha256": sha(ARCHIVE), "manifest_sha256": sha(MEMBERS),
        "file_count": len(listed), "result_sha256": sha(RAW / "result.json"),
        "config_sha256": sha(RAW / "config.json"),
        "checkpoint_sha256": sha(RAW / "checkpoint.json"),
        "audit_sha256": sha(RAW / "offline-causal-audit.json"),
        "depth_review_sha256": sha(DEPTH),
        "duration_seconds": result["duration_seconds"],
        "fault_trials_completed": 8, "strict_injected_trials": 8,
        "strict_target_trials": 2, "exact_exception_trials": 0,
        "audit_report_gate_passed": False,
        "quality_caveat": "same_actor_target_gate_failed_after_fault",
        "new_bug": False,
    })
    CANONICAL.mkdir(parents=True)
    for name in ("result.json", "config.json", "checkpoint.json", "offline-causal-audit.json"):
        shutil.copyfile(RAW / name, CANONICAL / name)
    campaigns = CANONICAL / "campaigns"
    campaigns.mkdir()
    (campaigns / "full-v3").symlink_to(os.path.relpath(RAW, campaigns))
    write_json(CANONICAL / "canonical-import-receipt.json", {
        "schema_version": 1, "case_id": "SOLR-14", "status": "queue_exhausted",
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
    print(json.dumps({"case_id": "SOLR-14", "archive_sha256": sha(ARCHIVE),
                      "receipt_sha256": sha(RECEIPT), "result_sha256": sha(RAW / "result.json"),
                      "file_count": len(listed)}, sort_keys=True))


if __name__ == "__main__":
    main()
