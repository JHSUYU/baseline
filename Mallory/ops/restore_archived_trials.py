#!/usr/bin/env python3
"""Verify or restore a Mallory case's archived trial evidence.

The campaign archive and its manifest are the durable copy. Restoration is
limited to ``cases/<ID>/trials``; it never overwrites an existing directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


CASE_ID = re.compile(r"(?:HBASE|HDFS|SOLR|ZOOKEEPER)-[0-9]{2}\Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(data_root: Path, case_id: str) -> tuple[Path, Path, dict, dict[str, str]]:
    if not CASE_ID.fullmatch(case_id):
        raise ValueError(f"invalid case ID: {case_id}")
    archive_root = data_root / "evidence_archives" / "campaign"
    archive = archive_root / f"{case_id}.tar.gz"
    manifest_path = archive_root / f"{case_id}.tar.manifest.json"
    case = data_root / "cases" / case_id
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("case_id") != case_id or manifest.get("phase") != "campaign":
        raise ValueError("archive manifest identifies a different case or phase")
    if archive.stat().st_size != manifest.get("archive_bytes"):
        raise ValueError("archive size differs from manifest")
    archive_digest = sha256(archive)
    if archive_digest != manifest.get("archive_sha256"):
        raise ValueError("archive SHA-256 differs from manifest")
    # Archiving appends dispatch provenance and an evidence_archive receipt to
    # the live result, so its hash normally differs from the archived result.
    live_result = json.loads((case / "result.json").read_text())
    receipt = live_result.get("evidence_archive", {})
    if live_result.get("status") not in {"budget_exhausted", "queue_exhausted"}:
        raise ValueError("case is not terminal")
    if receipt.get("sha256") != archive_digest or receipt.get("manifest_sha256") != sha256(manifest_path):
        raise ValueError("case result does not identify this archive and manifest")

    expected = manifest.get("members")
    if not isinstance(expected, list) or len(expected) != len(set(expected)):
        raise ValueError("invalid or duplicate manifest members")
    members: dict[str, str] = {}
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle:
            name = member.name
            parts = PurePosixPath(name).parts
            if not parts or name.startswith("/") or any(p in ("", ".", "..") for p in parts):
                raise ValueError(f"unsafe archive path: {name}")
            if not member.isfile():
                if member.isdir():
                    continue
                raise ValueError(f"nonregular archive member: {name}")
            if name in members:
                raise ValueError(f"duplicate archive member: {name}")
            stream = bundle.extractfile(member)
            assert stream is not None
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            members[name] = digest.hexdigest()
    if set(members) != set(expected):
        raise ValueError("archive members differ from manifest")
    if members.get("result.json") != manifest["source_result_sha256"]:
        raise ValueError("archived result.json differs from manifest")
    if not any(name.startswith("trials/") for name in members):
        raise ValueError("archive has no trial files")
    return archive, case, manifest, members


def verify_local(case: Path, members: dict[str, str]) -> str:
    target = case / "trials"
    if not target.exists():
        return "absent"
    expected = {name for name in members if name.startswith("trials/")}
    actual = {p.relative_to(case).as_posix() for p in target.rglob("*") if p.is_file()}
    if actual != expected:
        raise ValueError(f"local trial file set differs: missing={len(expected - actual)}, extra={len(actual - expected)}")
    for name in expected:
        if sha256(case / name) != members[name]:
            raise ValueError(f"local trial file differs from archive: {name}")
    return "byte_identical"


def restore(archive: Path, case: Path, members: dict[str, str]) -> None:
    target = case / "trials"
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite {target}")
    scratch = Path(tempfile.mkdtemp(prefix=".restore-trials-", dir=case))
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle:
                name = member.name
                if not member.isfile() or not name.startswith("trials/"):
                    continue
                destination = scratch.joinpath(*PurePosixPath(name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                stream = bundle.extractfile(member)
                assert stream is not None
                digest = hashlib.sha256()
                with destination.open("wb") as output:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        output.write(chunk)
                        digest.update(chunk)
                if digest.hexdigest() != members[name]:
                    raise ValueError(f"restored bytes differ: {name}")
        os.replace(scratch / "trials", target)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("data/mallory"))
    parser.add_argument("--case", required=True)
    parser.add_argument("--restore", action="store_true", help="restore absent trials after verifying archive")
    args = parser.parse_args()
    archive, case, manifest, members = inspect(args.data_root, args.case)
    local = verify_local(case, members)
    if args.restore:
        if local != "absent":
            raise FileExistsError(f"refusing to overwrite existing trials in {case}")
        restore(archive, case, members)
        local = verify_local(case, members)
    print(json.dumps({"case_id": args.case, "archive_sha256": manifest["archive_sha256"],
                      "trial_files": sum(name.startswith("trials/") for name in members),
                      "local_trials": local}, sort_keys=True))


if __name__ == "__main__":
    main()
