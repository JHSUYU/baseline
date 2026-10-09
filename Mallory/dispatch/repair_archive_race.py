"""Repair a verified terminal archive receipt conflict while preserving both versions.

This is for a narrow historical race where a collector replaced an archive
after a local finalizer had already added its receipt to result.json.  The
original scientific result must still be present, byte for byte, in the
replacement archive.  The augmented result is saved before its receipt is
updated; a SHA-bound repair record describes the change.
"""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import tarfile

from .verify_sources import sha256_file
from .worker import atomic_json


def repair(root: Path, case_id: str, expected_result_sha256: str,
           expected_archive_sha256: str) -> dict:
    if not case_id or "/" in case_id or ".." in case_id:
        raise ValueError("invalid case ID")
    archive_dir = root / "evidence_archives/campaign"
    with (archive_dir / f".{case_id}.archive.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        result_path = root / "cases" / case_id / "result.json"
        archive = archive_dir / f"{case_id}.tar.gz"
        manifest_path = archive.with_suffix(".manifest.json")
        if sha256_file(result_path) != expected_result_sha256:
            raise RuntimeError("terminal result changed before repair")
        if sha256_file(archive) != expected_archive_sha256:
            raise RuntimeError("archive changed before repair")
        result_bytes = result_path.read_bytes()
        result = json.loads(result_bytes)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        old_receipt = result.get("evidence_archive") or {}
        if (result.get("case_id") != case_id or
                result.get("status") not in ("budget_exhausted", "queue_exhausted") or
                manifest.get("case_id") != case_id or
                manifest.get("phase") != "campaign" or
                manifest.get("archive_sha256") != expected_archive_sha256 or
                not old_receipt.get("sha256") or
                old_receipt["sha256"] == expected_archive_sha256):
            raise RuntimeError("case is not the expected archive receipt conflict")
        with tarfile.open(archive, "r:gz") as packed:
            members = packed.getmembers()
            if (len(members) != len(set(member.name for member in members)) or
                    set(member.name for member in members) != set(manifest["members"]) or
                    any(not member.isfile() for member in members)):
                raise RuntimeError("archive members differ from manifest")
            archived_result_bytes = packed.extractfile("result.json").read()
        if sha256_bytes(archived_result_bytes) != manifest.get("source_result_sha256"):
            raise RuntimeError("archive does not contain its declared original result")
        original = json.loads(archived_result_bytes)
        stripped = {key: value for key, value in result.items()
                    if key not in ("evidence_archive", "dispatch_provenance")}
        if stripped != original:
            raise RuntimeError("archive result and terminal result differ scientifically")
        repair_dir = root / "evidence_archives/archive_repairs" / case_id
        repair_dir.mkdir(parents=True, exist_ok=True)
        backup = repair_dir / f"result.{expected_result_sha256}.json"
        if backup.exists():
            if backup.read_bytes() != result_bytes:
                raise RuntimeError("existing conflict backup differs")
        else:
            backup.write_bytes(result_bytes)
        result["evidence_archive"] = {
            "path": str(archive.relative_to(root)),
            "sha256": expected_archive_sha256,
            "manifest_path": str(manifest_path.relative_to(root)),
            "manifest_sha256": sha256_file(manifest_path),
            "bytes": archive.stat().st_size,
        }
        atomic_json(result_path, result)
        receipt = {
            "schema_version": 1, "case_id": case_id,
            "reason": "concurrent_archive_replacement_after_result_receipt",
            "preserved_result_path": str(backup.relative_to(root)),
            "preserved_result_sha256": expected_result_sha256,
            "archived_original_result_sha256": manifest["source_result_sha256"],
            "replacement_archive_sha256": expected_archive_sha256,
            "replacement_manifest_sha256": sha256_file(manifest_path),
            "repaired_result_sha256": sha256_file(result_path),
            "scientific_fields_identical": True,
        }
        atomic_json(repair_dir / "repair.json", receipt)
        return receipt


def sha256_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--expected-result-sha256", required=True)
    parser.add_argument("--expected-archive-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(repair(args.data_root.resolve(), args.case_id,
                            args.expected_result_sha256,
                            args.expected_archive_sha256), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
