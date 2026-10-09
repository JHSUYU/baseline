#!/usr/bin/env python3
"""Preserve the node2 SOLR-21 v25f raw campaign, including sparse scratch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tarfile


BASE = Path("/users/ZhenyuLi/baseline")
SOURCE = BASE / "data/mallory/campaign_v25f_lane1/SOLR-21"
SYNC_RECEIPT = BASE / "data/mallory/dispatch/solr21-v25f-archive-source-receipt.json"
ARCHIVE = BASE / "data/mallory/evidence_archives/campaign/SOLR-21.tar.gz"
MANIFEST = ARCHIVE.with_suffix(".manifest.json")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    receipt = json.loads(SYNC_RECEIPT.read_text())
    if (receipt.get("case_id") != "SOLR-21" or
            receipt.get("remote_root") != str(SOURCE) or
            receipt.get("status") != "budget_exhausted"):
        raise ValueError("source manifest does not identify terminal SOLR-21")
    expected = dict(receipt["retained_files"])
    expected.update(receipt["remote_only_scratch_files"])
    actual = {}
    for path in sorted(SOURCE.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink in raw evidence: {path}")
        if path.is_file():
            actual[str(path.relative_to(SOURCE))] = {
                "sha256": sha(path), "bytes": path.stat().st_size}
    if actual != expected or actual["result.json"]["sha256"] != receipt["result_sha256"]:
        raise ValueError("terminal raw differs from watcher SHA manifest")
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    temporary = ARCHIVE.with_name(f".{ARCHIVE.name}.building")
    if ARCHIVE.exists() or temporary.exists() or MANIFEST.exists():
        raise FileExistsError("SOLR-21 full archive already exists")
    subprocess.run(["tar", "--sparse", "--sort=name", "-czf", str(temporary),
                    "-C", str(SOURCE), "."], check=True)
    seen = {}
    with tarfile.open(temporary, "r:gz") as archive:
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile() or member.issym() or member.islnk():
                raise ValueError(f"unexpected archive member: {member.name}")
            name = member.name.removeprefix("./")
            if name in seen:
                raise ValueError(f"duplicate archive member: {name}")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"archive member unreadable: {name}")
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
            seen[name] = {"sha256": digest.hexdigest(), "bytes": size}
    if seen != expected:
        raise ValueError("lossless archive member SHA/size mismatch")
    temporary.replace(ARCHIVE)
    manifest = {
        "schema_version": 1,
        "case_id": "SOLR-21",
        "phase": "campaign",
        "variant": "v25f_lane1_local_timeline_c9ee",
        "source_host": "node2",
        "source_root": str(SOURCE),
        "source_result_sha256": actual["result.json"]["sha256"],
        "config_sha256": actual["config.json"]["sha256"],
        "sync_source_receipt_sha256": sha(SYNC_RECEIPT),
        "archive_sha256": sha(ARCHIVE),
        "archive_bytes": ARCHIVE.stat().st_size,
        "members": expected,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": manifest["archive_sha256"],
                      "manifest_sha256": sha(MANIFEST),
                      "members": len(expected),
                      "archive_bytes": manifest["archive_bytes"]}, sort_keys=True))


if __name__ == "__main__":
    main()
