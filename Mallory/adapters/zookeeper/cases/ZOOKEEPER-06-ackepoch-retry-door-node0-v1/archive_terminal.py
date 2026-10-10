#!/usr/bin/env python3
"""Create and verify a complete SHA-bound archive of the terminal case."""

import hashlib
import json
import tarfile
from pathlib import Path


BASE = Path("/users/ZhenyuLi/baseline")
CASE = BASE / "data/mallory/cases/ZOOKEEPER-06"
ARCHIVES = BASE / "data/mallory/evidence_archives"
PREFIX = "ZOOKEEPER-06-node0-full-v1"


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stream_sha(stream):
    h = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        h.update(chunk)
    return h.hexdigest()


def main():
    archive = ARCHIVES / f"{PREFIX}.tar.gz"
    manifest_path = ARCHIVES / f"{PREFIX}.members.json"
    receipt_path = ARCHIVES / f"{PREFIX}.receipt.json"
    if any(path.exists() for path in (archive, manifest_path, receipt_path)):
        raise FileExistsError("terminal archive output already exists")
    result = json.loads((CASE / "result.json").read_text())
    assert result["status"] == "budget_exhausted"
    assert result["fault_trials_completed"] == 80
    collection = json.loads((CASE / "collection-receipt.json").read_text())
    assert collection["result_sha256"] == sha(CASE / "result.json")
    files = sorted(path for path in CASE.rglob("*") if path.is_file())
    assert all(not path.is_symlink() for path in files)
    members = [{"name": "ZOOKEEPER-06/" + str(path.relative_to(CASE)),
                "sha256": sha(path), "size": path.stat().st_size} for path in files]
    manifest = {"schema_version": 1, "case_id": "ZOOKEEPER-06", "members": members}
    ARCHIVES.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
        for path, row in zip(files, members):
            info = tarfile.TarInfo(row["name"])
            info.size = row["size"]
            info.mode = 0o600
            info.mtime = 0
            with path.open("rb") as stream:
                tar.addfile(info, stream)
    with tarfile.open(archive, "r:gz") as tar:
        actual = [member for member in tar if member.isfile()]
        assert [member.name for member in actual] == [row["name"] for row in members]
        for item, row in zip(actual, members):
            assert item.size == row["size"]
            with tar.extractfile(item) as stream:
                assert stream_sha(stream) == row["sha256"], item.name
    receipt = {
        "schema_version": 1,
        "case_id": "ZOOKEEPER-06",
        "terminal_status": result["status"],
        "archive_path": str(archive),
        "archive_sha256": sha(archive),
        "archive_size": archive.stat().st_size,
        "member_manifest_path": str(manifest_path),
        "member_manifest_sha256": sha(manifest_path),
        "member_count": len(members),
        "collection_receipt_sha256": sha(CASE / "collection-receipt.json"),
        "result_sha256": sha(CASE / "result.json"),
        "offline_audit_sha256": sha(CASE / "offline-causal-audit.json"),
        "all_archive_members_verified": True,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print("archive_sha256", receipt["archive_sha256"], "member_count", len(members),
          "receipt_sha256", sha(receipt_path))


if __name__ == "__main__":
    main()
