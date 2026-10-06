#!/usr/bin/env python3
"""Losslessly archive completed ZOOKEEPER-12 runtime event streams."""

import gzip
import hashlib
import json
from pathlib import Path
import shutil


HERE = Path(__file__).resolve().parent
STREAM_NAMES = ("runtime_trace.jsonl", "schedule.jsonl")
RUNTIME_DIRS = [HERE / "run" / "runtime", *(HERE / "trials").glob("*/runtime")]


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def archive(path: Path) -> dict:
    archive_path = path.with_name(path.name + ".gz")
    if path.exists():
        if archive_path.exists():
            raise RuntimeError(f"Both raw and compressed streams exist: {path}")
        raw_bytes = path.stat().st_size
        raw_sha256 = digest(path)
        temporary = archive_path.with_name(archive_path.name + ".partial")
        with path.open("rb") as source, gzip.open(temporary, "wb", compresslevel=1) as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        with gzip.open(temporary, "rb") as recovered:
            hasher = hashlib.sha256()
            while block := recovered.read(1024 * 1024):
                hasher.update(block)
        if hasher.hexdigest() != raw_sha256:
            temporary.unlink()
            raise RuntimeError(f"Archive verification failed: {path}")
        temporary.replace(archive_path)
        path.unlink()
    else:
        if not archive_path.exists():
            raise FileNotFoundError(path)
        with gzip.open(archive_path, "rb") as recovered:
            hasher = hashlib.sha256()
            raw_bytes = 0
            while block := recovered.read(1024 * 1024):
                hasher.update(block)
                raw_bytes += len(block)
        raw_sha256 = hasher.hexdigest()
    return {
        "path": str(path.relative_to(HERE)),
        "archive": str(archive_path.relative_to(HERE)),
        "raw_bytes": raw_bytes,
        "raw_sha256": raw_sha256,
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": digest(archive_path),
    }


def main() -> None:
    streams = [directory / name for directory in RUNTIME_DIRS for name in STREAM_NAMES]
    entries = [archive(path) for path in streams]
    manifest = {
        "format": "gzip-1",
        "streams": sorted(entries, key=lambda entry: entry["path"]),
    }
    (HERE / "artifact-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Archived {len(entries)} streams; raw {sum(x['raw_bytes'] for x in entries)} bytes, compressed {sum(x['archive_bytes'] for x in entries)} bytes")


if __name__ == "__main__":
    main()
