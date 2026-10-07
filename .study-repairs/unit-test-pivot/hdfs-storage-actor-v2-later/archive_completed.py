#!/usr/bin/env python3
"""Archive only completed storage V2 trials, verify a second host, then prune exports.

The archive contains every regular file of the selected run directories.  Neither
an in-flight directory nor a campaign checkpoint is changed by this program.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".part-{os.getpid()}")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def verify_files(root: Path, files: list[dict]) -> None:
    for item in files:
        path = root / item["path"]
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"missing/unsafe archived file: {path}")
        if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise RuntimeError(f"archived file differs: {path}")


def archive_path(anchor: Path, manifest: dict) -> Path:
    return anchor / "archives" / manifest["archive_name"]


def prepare(anchor: Path, start: int, count: int) -> Path:
    state_path = anchor / "campaign-state.json"
    state = json.loads(state_path.read_text())
    if start < 1 or count < 1:
        raise RuntimeError("archive range must be positive")
    first, last = start, start + count - 1
    ids = state["completion_order"][first - 1:last]
    if len(ids) != count or not ids:
        raise RuntimeError("requested count is not completed")
    if len(ids) != len(set(ids)) or any(i not in state["completed"] for i in ids):
        raise RuntimeError("checkpoint completed IDs are inconsistent")
    if any(i == (state.get("in_flight") or {}).get("id") for i in ids):
        raise RuntimeError("in-flight trial appears in archive selection")
    prefix = f"rollback-{first:04d}-{last:04d}"
    directory = anchor / "archives"
    directory.mkdir(exist_ok=True)
    manifest_path = directory / f"{prefix}.manifest.json"
    tar_path = directory / f"{prefix}.tar.zst"
    if manifest_path.exists() or tar_path.exists():
        raise RuntimeError("immutable archive name already exists")
    files: list[dict] = []
    for sequence_id in ids:
        run = anchor / "runs" / sequence_id
        if not run.is_dir() or run.is_symlink():
            raise RuntimeError(f"missing/unsafe completed run: {sequence_id}")
        for path in sorted(run.rglob("*")):
            if path.is_symlink():
                raise RuntimeError(f"symlink prohibited: {path}")
            if path.is_file():
                files.append({"path": path.relative_to(anchor).as_posix(),
                              "bytes": path.stat().st_size, "sha256": sha(path)})
    if not files:
        raise RuntimeError("selected runs contain no files")
    with tempfile.TemporaryDirectory(dir=directory, prefix="archive-build-") as tmp:
        list_path = Path(tmp) / "files.txt"
        list_path.write_text("".join(item["path"] + "\n" for item in files))
        temporary_tar = Path(tmp) / "archive.tar.zst"
        subprocess.run(["tar", "-C", str(anchor), "--zstd", "-cf",
                        str(temporary_tar), "-T", str(list_path)], check=True)
        subprocess.run(["zstd", "-tq", str(temporary_tar)], check=True)
        extract = Path(tmp) / "extract"
        extract.mkdir()
        subprocess.run(["tar", "--zstd", "-xf", str(temporary_tar),
                        "-C", str(extract)], check=True)
        verify_files(extract, files)
        archive_sha = sha(temporary_tar)
        archive_bytes = temporary_tar.stat().st_size
        os.replace(temporary_tar, tar_path)
    manifest = {"schema": "hdfs-storage-v2-completed-archive-1",
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_host": socket.gethostname(), "completed_count": count,
                "first_index": first, "last_index": last,
                "sequence_ids": ids, "checkpoint_sha256": sha(state_path),
                "archive_name": tar_path.name, "archive_sha256": archive_sha,
                "archive_bytes": archive_bytes, "files": files}
    write_json(manifest_path, manifest)
    return manifest_path


def verify(anchor: Path, manifest_path: Path, restore: bool) -> Path:
    manifest = json.loads(manifest_path.read_text())
    tar_path = archive_path(anchor, manifest)
    if (not tar_path.is_file() or tar_path.stat().st_size != manifest["archive_bytes"]
            or sha(tar_path) != manifest["archive_sha256"]):
        raise RuntimeError("archive SHA/size differs from immutable manifest")
    with tempfile.TemporaryDirectory(dir=anchor / "archives", prefix="archive-verify-") as tmp:
        extract = Path(tmp)
        subprocess.run(["tar", "--zstd", "-xf", str(tar_path),
                        "-C", str(extract)], check=True)
        verify_files(extract, manifest["files"])
        actual = sorted(p.relative_to(extract).as_posix() for p in extract.rglob("*") if p.is_file())
        expected = sorted(item["path"] for item in manifest["files"])
        if actual != expected:
            raise RuntimeError("archive has missing or extra files")
        if restore:
            for item in manifest["files"]:
                destination = anchor / item["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if sha(destination) != item["sha256"]:
                        raise RuntimeError(f"mirror collision: {destination}")
                else:
                    shutil.copy2(extract / item["path"], destination)
            verify_files(anchor, manifest["files"])
    receipt_path = manifest_path.with_name(manifest_path.stem.replace(".manifest", "") +
                                           f".{socket.gethostname()}.verified.json")
    write_json(receipt_path, {
        "schema": "hdfs-storage-v2-mirror-verification-1",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(), "manifest_sha256": sha(manifest_path),
        "archive_sha256": manifest["archive_sha256"],
        "verified_file_count": len(manifest["files"]),
        "restored_raw": restore,
    })
    return receipt_path


def prune(anchor: Path, manifest_path: Path, remote_receipt_path: Path) -> Path:
    manifest = json.loads(manifest_path.read_text())
    receipt = json.loads(remote_receipt_path.read_text())
    if (receipt["host"] == socket.gethostname() or not receipt["restored_raw"]
            or receipt["manifest_sha256"] != sha(manifest_path)
            or receipt["archive_sha256"] != manifest["archive_sha256"]
            or receipt["verified_file_count"] != len(manifest["files"])):
        raise RuntimeError("no independent full mirror verification receipt")
    if sha(archive_path(anchor, manifest)) != manifest["archive_sha256"]:
        raise RuntimeError("local archive SHA changed")
    state = json.loads((anchor / "campaign-state.json").read_text())
    first = manifest.get("first_index", 1)
    last = manifest.get("last_index", manifest["completed_count"])
    if (state["completion_order"][first - 1:last] != manifest["sequence_ids"]
            or any(i not in state["completed"] for i in manifest["sequence_ids"])):
        raise RuntimeError("completed checkpoint prefix changed")
    files = {item["path"]: item for item in manifest["files"]}
    pruned: list[dict] = []
    remove_paths: list[Path] = []
    for sequence_id in manifest["sequence_ids"]:
        result = state["completed"][sequence_id]["result"]
        if any(entry["target_exception_after_fault"] for entry in result["by_case"].values()):
            continue  # retain every locally visible candidate, even an expected throw
        run = anchor / "runs" / sequence_id
        candidates = list(run.rglob("covered_*.txt"))
        for scratch in run.rglob("scratch"):
            if scratch.is_dir():
                candidates.extend(path for path in scratch.rglob("*") if path.is_file())
        for path in candidates:
            if not path.is_file():
                continue
            rel = path.relative_to(anchor).as_posix()
            item = files.get(rel)
            if item is None or sha(path) != item["sha256"]:
                raise RuntimeError(f"unverified cleanup candidate: {path}")
            remove_paths.append(path)
            pruned.append(item)
    index_path = anchor / "archives" / "verified-pruned.json"
    if index_path.exists():
        index = json.loads(index_path.read_text())
    else:
        index = {"schema": "hdfs-storage-v2-verified-pruned-1", "batches": []}
    if any(batch["manifest_sha256"] == sha(manifest_path) for batch in index["batches"]):
        raise RuntimeError("archive batch already indexed")
    index["batches"].append({
        "manifest": manifest_path.name, "manifest_sha256": sha(manifest_path),
        "archive": manifest["archive_name"], "archive_sha256": manifest["archive_sha256"],
        "remote_receipt": remote_receipt_path.name,
        "remote_receipt_sha256": sha(remote_receipt_path),
        "pruned": pruned,
    })
    # Publish the verified missing-file index before removing any file.  If a
    # process dies mid-cleanup, the audit can still prove every absent export.
    write_json(index_path, index)
    for path in remove_paths:
        path.unlink()
    for sequence_id in manifest["sequence_ids"]:
        run = anchor / "runs" / sequence_id
        for scratch in sorted((p for p in run.rglob("scratch") if p.is_dir()),
                              key=lambda p: len(p.parts), reverse=True):
            for child in sorted((p for p in scratch.rglob("*") if p.is_dir()),
                                key=lambda p: len(p.parts), reverse=True):
                if not any(child.iterdir()):
                    child.rmdir()
            if not any(scratch.iterdir()):
                scratch.rmdir()
    return index_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "verify", "prune"))
    parser.add_argument("anchor", type=Path)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--count", type=int)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--remote-receipt", type=Path)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        if args.count is None:
            parser.error("prepare requires --count")
        path = prepare(args.anchor, args.start, args.count)
    elif args.action == "verify":
        if args.manifest is None:
            parser.error("verify requires --manifest")
        path = verify(args.anchor, args.manifest, args.restore)
    else:
        if args.manifest is None or args.remote_receipt is None:
            parser.error("prune requires --manifest and --remote-receipt")
        path = prune(args.anchor, args.manifest, args.remote_receipt)
    print(path)


if __name__ == "__main__":
    main()
