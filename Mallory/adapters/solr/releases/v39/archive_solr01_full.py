#!/usr/bin/env python3
"""Losslessly archive the terminal SOLR-01 raw campaign without pruning it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile


def digest_stream(stream) -> str:
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(chunk)
    return value.hexdigest()


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return digest_stream(stream)


def archive_members(archive: Path) -> dict[str, dict]:
    members = {}
    with tarfile.open(archive, "r:gz") as packed:
        for member in packed:
            name = Path(member.name)
            if (not member.isfile() or name.is_absolute() or ".." in name.parts
                    or member.name in members):
                raise ValueError("unsafe or duplicate archive member")
            stream = packed.extractfile(member)
            if stream is None:
                raise ValueError("archive member cannot be read")
            members[member.name] = {"sha256": digest_stream(stream), "bytes": member.size}
    return members


def verify(archive: Path, manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("schema_version") != 1 or manifest.get("case_id") != "SOLR-01"
            or manifest.get("source_status") != "budget_exhausted"
            or manifest.get("archive_sha256") != digest(archive)
            or manifest.get("members") != archive_members(archive)
            or manifest.get("source_result_sha256") !=
            manifest["members"].get("result.json", {}).get("sha256")):
        raise ValueError("SOLR-01 archive or manifest does not match its members")
    return manifest


def create(source: Path, archive: Path, manifest_path: Path) -> dict:
    result = json.loads((source / "result.json").read_text())
    if (result.get("case_id") != "SOLR-01" or result.get("status") != "budget_exhausted"
            or result.get("fault_trials_completed") != 80):
        raise ValueError("expected terminal SOLR-01 80-trial result")
    files = [path for path in sorted(source.rglob("*")) if path.is_file()]
    if not files or any(path.is_symlink() for path in source.rglob("*")):
        raise ValueError("source evidence absent or contains a symlink")
    members = {str(path.relative_to(source)): {"sha256": digest(path),
               "bytes": path.stat().st_size} for path in files}
    if archive.exists() or manifest_path.exists():
        if not (archive.is_file() and manifest_path.is_file()):
            raise ValueError("partial archive exists")
        existing = verify(archive, manifest_path)
        if existing["members"] != members:
            raise ValueError("existing archive is bound to different source bytes")
        return existing
    archive.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name("." + archive.name + f".{os.getpid()}.tmp")
    try:
        with tarfile.open(temporary, "w:gz") as packed:
            for path in files:
                packed.add(path, arcname=str(path.relative_to(source)), recursive=False)
        if archive_members(temporary) != members:
            raise ValueError("archive differs from original source bytes")
        manifest = {"schema_version": 1, "case_id": "SOLR-01",
                    "source_status": "budget_exhausted", "fault_trials_completed": 80,
                    "source_result_sha256": members["result.json"]["sha256"],
                    "archive_sha256": digest(temporary), "archive_bytes": temporary.stat().st_size,
                    "members": members}
        os.replace(temporary, archive)
        manifest_temp = manifest_path.with_name("." + manifest_path.name +
                                                f".{os.getpid()}.tmp")
        try:
            manifest_temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            os.replace(manifest_temp, manifest_path)
        finally:
            manifest_temp.unlink(missing_ok=True)
        verify(archive, manifest_path)
        return manifest
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    manifest = (create(args.source, args.archive, args.manifest) if args.source else
                verify(args.archive, args.manifest))
    print(json.dumps({"archive_sha256": manifest["archive_sha256"],
                      "archive_bytes": manifest["archive_bytes"],
                      "manifest_sha256": digest(args.manifest),
                      "member_count": len(manifest["members"]),
                      "source_result_sha256": manifest["source_result_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
