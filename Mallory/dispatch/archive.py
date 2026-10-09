"""Create a lossless terminal-case evidence archive on its owner host."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import tarfile

try:
    from .verify_sources import sha256_file
    from .worker import atomic_json
except ImportError:
    from verify_sources import sha256_file
    from worker import atomic_json


TERMINAL = {"calibration": {"calibration_complete", "healthy_seed_invalid",
                             "healthy_node_identity_missing", "healthy_seed_ambiguous",
                             "healthy_no_injectable_door", "healthy_attestation_failed"},
            "campaign": {"budget_exhausted", "queue_exhausted", "healthy_seed_invalid",
                         "healthy_node_identity_missing", "healthy_seed_ambiguous",
                         "healthy_no_injectable_door", "healthy_attestation_failed",
                         "fault_trials_not_attested"}}


def ensure(root: Path, phase: str, case_id: str, reserve_bytes: int = 3 * 1024**3,
           cohort: str = "") -> dict:
    if (phase not in TERMINAL or not case_id or "/" in case_id or ".." in case_id
            or (cohort and (not cohort.isascii() or not cohort.isalnum()))):
        raise ValueError("invalid phase or case ID")
    archive_dir = root / "evidence_archives" / (phase + (f"_{cohort}" if cohort else ""))
    archive_dir.mkdir(parents=True, exist_ok=True)
    lock_path = archive_dir / f".{case_id}.archive.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        return _ensure_locked(root, phase, case_id, reserve_bytes, cohort)


def _ensure_locked(root: Path, phase: str, case_id: str, reserve_bytes: int,
                   cohort: str) -> dict:
    collection = f"calibration_{cohort}" if phase == "calibration" and cohort else (
        "calibration" if phase == "calibration" else "cases")
    case = root / collection / case_id
    result_path = case / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("case_id") != case_id or result.get("status") not in TERMINAL[phase]:
        raise ValueError("case has no terminal scientific result")
    digest = sha256_file(result_path)
    receipt = result.get("evidence_archive") or {}
    archive = root / "evidence_archives" / (phase + (f"_{cohort}" if cohort else "")) / f"{case_id}.tar.gz"
    manifest_path = archive.with_suffix(".manifest.json")
    if archive.is_file() and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest.get("case_id") != case_id or manifest.get("phase") != phase
                or manifest.get("cohort", "") != cohort):
            raise RuntimeError("existing archive manifest belongs to a different case")
        if ((manifest.get("source_result_sha256") == digest or
             receipt.get("sha256") == manifest.get("archive_sha256")) and
                manifest.get("archive_sha256") == sha256_file(archive)):
            return _response(root, archive, manifest_path, manifest)
        if receipt:
            raise RuntimeError("archived case result is bound to different evidence; refusing rebuild")
    if receipt:
        raise RuntimeError("archived case result is bound to missing evidence; refusing rebuild")
    if shutil.disk_usage(root).free < reserve_bytes:
        raise RuntimeError("insufficient disk reserve for evidence archive")
    files = [path for path in sorted(case.rglob("*")) if path.is_file()]
    files = [path for path in files if path.name != ".campaign.lock"]
    if not files or any(path.is_symlink() for path in files):
        raise ValueError("case evidence missing or contains symlink")
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(f".{archive.name}.{os.getpid()}.tmp")
    try:
        with tarfile.open(temporary, "w:gz") as output:
            for path in files:
                output.add(path, arcname=str(path.relative_to(case)), recursive=False)
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        if sha256_file(result_path) != digest:
            raise RuntimeError("case result changed during archive creation; retry after finalization")
        archive_digest = sha256_file(temporary)
        os.replace(temporary, archive)
        manifest = {"schema_version": 1, "case_id": case_id, "phase": phase,
                    "cohort": cohort,
                    "source_result_sha256": digest, "archive_sha256": archive_digest,
                    "archive_bytes": archive.stat().st_size,
                    "members": [str(path.relative_to(case)) for path in files]}
        atomic_json(manifest_path, manifest)
        return _response(root, archive, manifest_path, manifest)
    finally:
        temporary.unlink(missing_ok=True)


def _response(root: Path, archive: Path, manifest_path: Path, manifest: dict) -> dict:
    return {"archive_relative": str(archive.relative_to(root)),
            "archive_sha256": manifest["archive_sha256"],
            "archive_bytes": manifest["archive_bytes"],
            "manifest_relative": str(manifest_path.relative_to(root)),
            "manifest_sha256": sha256_file(manifest_path),
            "source_result_sha256": manifest["source_result_sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--phase", choices=tuple(TERMINAL), required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--cohort", default="")
    args = parser.parse_args()
    print(json.dumps(ensure(args.data_root.resolve(), args.phase, args.case_id,
                            cohort=args.cohort), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
