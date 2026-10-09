#!/usr/bin/env python3
"""Preserve HDFS31 V4 terminal raw files and verify a mirror without extraction."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tarfile
import tempfile


NAME = "hdfs31-v4-0022-0094"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def save(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f".part-{os.getpid()}")
    with temporary.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def verify_stream(archive: Path, files: list[dict]) -> None:
    expected = {row["path"]: row for row in files}
    if len(expected) != len(files):
        raise RuntimeError("duplicate manifest path")
    seen: set[str] = set()
    process = subprocess.Popen(["zstd", "-dc", str(archive)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as tar:
            for member in tar:
                if member.isdir():
                    continue
                name = member.name.removeprefix("./")
                if not member.isfile() or name not in expected or name in seen:
                    raise RuntimeError(f"unexpected archive member: {name}")
                if member.size != expected[name]["bytes"]:
                    raise RuntimeError(f"archive member size changed: {name}")
                stream = tar.extractfile(member)
                if stream is None:
                    raise RuntimeError(f"unreadable archive member: {name}")
                value = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    value.update(chunk)
                if value.hexdigest() != expected[name]["sha256"]:
                    raise RuntimeError(f"archive member SHA changed: {name}")
                seen.add(name)
        if process.wait() != 0:
            raise RuntimeError("zstd stream decompression failed")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait()
        process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
    if seen != set(expected):
        raise RuntimeError(f"archive misses {len(set(expected) - seen)} manifest files")


def prepare(anchor: Path) -> None:
    state_path = anchor / "campaign-state.json"
    state = json.loads(state_path.read_text())
    frozen = json.loads((anchor / "legacy21-freeze.manifest.json").read_text())
    if (len(state["completion_order"]) != 94 or state["effective"] != 80
            or state["in_flight"] is not None or state["budget"]["goal"] != 80
            or state["completion_order"][:21] != frozen["completed_ids"]
            or state["identity_rule_migration"]["boundary_completed"] != 21):
        raise RuntimeError("not the exact V4 base-80 terminal checkpoint")
    destination = anchor / "archives"
    destination.mkdir(exist_ok=True)
    archive = destination / f"{NAME}.tar.zst"
    manifest_path = destination / f"{NAME}.manifest.json"
    if archive.exists() or manifest_path.exists():
        raise RuntimeError("immutable terminal archive already exists")
    names = state["completion_order"][21:94]
    paths = [state_path, anchor / "audit-base80.json",
             anchor / "audit-base80-novelty.json",
             anchor / "actor-continuity-v4-migration.json"]
    for identity in names:
        run = anchor / "runs" / identity / "attempt-1"
        if not run.is_dir() or run.is_symlink():
            raise RuntimeError(f"missing completed run: {identity}")
        paths.extend(sorted(path for path in run.rglob("*") if path.is_file()))
    files = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"unsafe source file: {path}")
        files.append({"path": path.relative_to(anchor).as_posix(),
                      "bytes": path.stat().st_size, "sha256": digest(path)})
    if len({row["path"] for row in files}) != len(files):
        raise RuntimeError("duplicate archive source")
    with tempfile.TemporaryDirectory(dir=destination, prefix="hdfs31-archive-build-") as temp:
        listing = Path(temp) / "names.txt"
        listing.write_text("".join(row["path"] + "\n" for row in files))
        candidate = Path(temp) / "raw.tar.zst"
        subprocess.run(["tar", "-C", str(anchor), "--zstd", "-cf",
                        str(candidate), "-T", str(listing)], check=True)
        verify_stream(candidate, files)
        archive_sha = digest(candidate)
        archive_bytes = candidate.stat().st_size
        os.replace(candidate, archive)
    manifest = {"schema": "hdfs31-v4-terminal-raw-archive-1",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_host": socket.gethostname(),
                "terminal_checkpoint_sha256": digest(state_path),
                "legacy_boundary_completed": 21,
                "completed_ids": names,
                "archive_name": archive.name,
                "archive_sha256": archive_sha,
                "archive_bytes": archive_bytes,
                "files": files}
    save(manifest_path, manifest)
    print(json.dumps({"manifest": str(manifest_path), "files": len(files),
                      "raw_bytes": sum(row["bytes"] for row in files),
                      "archive_bytes": archive_bytes, "archive_sha256": archive_sha},
                     sort_keys=True))


def verify(anchor: Path) -> None:
    directory = anchor / "archives"
    manifest_path = directory / f"{NAME}.manifest.json"
    manifest = json.loads(manifest_path.read_text())
    archive = directory / manifest["archive_name"]
    if (manifest["schema"] != "hdfs31-v4-terminal-raw-archive-1"
            or not archive.is_file() or archive.stat().st_size != manifest["archive_bytes"]
            or digest(archive) != manifest["archive_sha256"]):
        raise RuntimeError("archive or manifest changed")
    verify_stream(archive, manifest["files"])
    receipt = {"schema": "hdfs31-v4-terminal-stream-mirror-1",
               "verified_at_utc": datetime.now(timezone.utc).isoformat(),
               "host": socket.gethostname(),
               "manifest_sha256": digest(manifest_path),
               "archive_sha256": manifest["archive_sha256"],
               "terminal_checkpoint_sha256": manifest["terminal_checkpoint_sha256"],
               "verified_files": len(manifest["files"]),
               "verified_raw_bytes": sum(x["bytes"] for x in manifest["files"]),
               "stream_verified_without_disk_extraction": True,
               "restored_raw": False}
    destination = directory / f"{NAME}.{socket.gethostname()}.stream-verified.json"
    if destination.exists():
        raise RuntimeError("immutable mirror receipt already exists")
    save(destination, receipt)
    print(json.dumps({"receipt": str(destination), **receipt}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("anchor", type=Path)
    args = parser.parse_args()
    anchor = args.anchor.resolve()
    if args.action == "prepare":
        prepare(anchor)
    else:
        verify(anchor)


if __name__ == "__main__":
    main()
