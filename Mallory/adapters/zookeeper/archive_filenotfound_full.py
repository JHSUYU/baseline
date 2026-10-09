#!/usr/bin/env python3
"""Archive the terminal ZK12 FNF campaign and publish compact metadata."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


BASE = Path("/users/ZhenyuLi/baseline")
RAW = BASE / "data/mallory/campaigns/ZOOKEEPER-12-fnf-v1"
CANONICAL = BASE / "data/mallory/cases/ZOOKEEPER-12"
ARCHIVE = BASE / "data/mallory/evidence_archives/campaign/ZOOKEEPER-12.tar.gz"
MANIFEST = ARCHIVE.with_suffix(".manifest.json")
REVIEW = BASE / "data/mallory/admissions/ZOOKEEPER-12-fa5f-filenotfound-v1-full-review.json"
FLOOR = 5 * 1024 ** 3


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    if ARCHIVE.exists() or MANIFEST.exists() or CANONICAL.exists():
        raise FileExistsError("ZK12 canonical archive or metadata already exists")
    result_path = RAW / "result.json"
    audit_path = RAW / "offline-causal-audit.json"
    config_path = RAW / "config.json"
    result, audit, config, review = map(read, (result_path, audit_path,
                                              config_path, REVIEW))
    if not (result["case_id"] == "ZOOKEEPER-12"
            and result["status"] == "queue_exhausted"
            and result["runtime_attestation"]["valid"] is True
            and result["healthy_junit_validation"]["status"] == "passed"
            and audit["report_gate_passed"] is True
            and audit["campaign_result_sha256"] == sha(result_path)
            and review["campaign_result_sha256"] == sha(result_path)
            and review["offline_audit_sha256"] == sha(audit_path)
            and review["config_sha256"] == sha(config_path)
            and review["strict_fault_chain_trials"] == result["fault_trials_completed"]
            and review["same_actor_same_occurrence_postfault_check_trials"] > 0
            and review["same_actor_same_occurrence_postfault_throw_trials"] == 0
            and config["source_overlay_receipt_sha256"] ==
                sha(Path(config["source_overlay_receipt"]))):
        raise ValueError("terminal ZK12 evidence or strict postfault review failed")
    free = shutil.disk_usage(BASE).free
    if free < FLOOR + 100 * 1024 ** 2:
        raise RuntimeError("disk reserve too low to archive ZK12")
    files = sorted(path for path in RAW.rglob("*")
                   if path.is_file() and path.name != ".campaign.lock")
    if not files or any(path.is_symlink() for path in files):
        raise ValueError("raw campaign is empty or contains a symlink")
    members = {str(path.relative_to(RAW)): {"sha256": sha(path),
                                              "bytes": path.stat().st_size}
               for path in files}
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    temporary = ARCHIVE.with_name(f".{ARCHIVE.name}.{os.getpid()}.tmp")
    try:
        with tarfile.open(temporary, "w:gz") as packed:
            for path in files:
                packed.add(path, arcname=str(path.relative_to(RAW)), recursive=False)
        extracted = {}
        with tarfile.open(temporary, "r:gz") as packed:
            for member in packed:
                if not member.isfile() or member.name not in members:
                    raise ValueError(f"unexpected archive member {member.name}")
                stream = packed.extractfile(member)
                if stream is None:
                    raise ValueError(f"unreadable archive member {member.name}")
                h = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(block)
                extracted[member.name] = {"sha256": h.hexdigest(),
                                          "bytes": member.size}
        if extracted != members or sha(result_path) != review["campaign_result_sha256"]:
            raise ValueError("archive bytes differ from terminal source")
        os.replace(temporary, ARCHIVE)
    finally:
        temporary.unlink(missing_ok=True)
    manifest = {
        "schema_version": 1, "case_id": "ZOOKEEPER-12", "phase": "campaign",
        "source_campaign": str(RAW.resolve()),
        "archive_sha256": sha(ARCHIVE), "archive_bytes": ARCHIVE.stat().st_size,
        "source_result_sha256": sha(result_path),
        "offline_audit_sha256": sha(audit_path),
        "config_sha256": sha(config_path),
        "strict_review_sha256": sha(REVIEW),
        "source_overlay_receipt_sha256": config["source_overlay_receipt_sha256"],
        "trial_count": len(result["trials"]),
        "strict_postfault_target_trials":
            review["same_actor_same_occurrence_postfault_check_trials"],
        "members": members,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    staged = CANONICAL.with_name(".ZOOKEEPER-12.stage")
    if staged.exists():
        raise FileExistsError(staged)
    staged.mkdir(parents=True)
    retained = ("result.json", "offline-causal-audit.json", "config.json",
                "driver-exit.json", "collection-receipt.json",
                "core-release-manifest.json")
    for name in retained:
        shutil.copy2(RAW / name, staged / name)
        if sha(staged / name) != members[name]["sha256"]:
            raise ValueError(f"canonical metadata copy mismatch: {name}")
    sync = {
        "schema_version": 1, "case_id": "ZOOKEEPER-12",
        "source_result_sha256": sha(result_path),
        "source_audit_sha256": sha(audit_path),
        "archive_sha256": sha(ARCHIVE),
        "archive_manifest_sha256": sha(MANIFEST),
        "strict_review_sha256": sha(REVIEW),
        "retained_files": {name: members[name] for name in retained},
        "archive_only_files": {name: meta for name, meta in members.items()
                               if name not in retained},
    }
    (staged / "sync-receipt.json").write_text(
        json.dumps(sync, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(staged, CANONICAL)
    print(json.dumps({"archive_sha256": sha(ARCHIVE),
                      "archive_manifest_sha256": sha(MANIFEST),
                      "sync_receipt_sha256": sha(CANONICAL / "sync-receipt.json"),
                      "canonical_result_sha256": sha(CANONICAL / "result.json"),
                      "members": len(members), "archive_bytes": ARCHIVE.stat().st_size},
                     sort_keys=True))


if __name__ == "__main__":
    main()
