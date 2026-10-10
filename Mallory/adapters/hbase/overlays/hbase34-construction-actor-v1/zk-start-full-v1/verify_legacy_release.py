#!/usr/bin/env python3
"""Verify the pinned legacy Mallory core release by exact manifest and file SHA.

The generic release verifier additionally requires a content-derived directory
name. This older release has a source-commit label; its manifest and every
listed byte are still pinned here before a campaign can start.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_ID = "815cba9b-target-absent-v1"
EXPECTED_MANIFEST_SHA256 = "addd46568f8d29029e6b4f68df491c098fa37feb153c1f406f278b7cb35fda8c"
CORE_FILES = ("__init__.py", "audit.py", "campaign.py", "events.py",
              "feedback.py", "graph.py", "junit.py", "scheduler.py")
EXPECTED_FILES = {"Mallory/__init__.py", *
                  (f"Mallory/core/{name}" for name in CORE_FILES)}


def digest(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def verify(release: Path) -> dict:
    release = release.resolve()
    if release.name != EXPECTED_ID:
        raise ValueError("wrong pinned legacy release directory")
    manifest_path = release / "manifest.json"
    if digest(manifest_path) != EXPECTED_MANIFEST_SHA256:
        raise ValueError("legacy release manifest SHA mismatch")
    manifest = json.loads(manifest_path.read_text())
    files = manifest.get("files")
    if (manifest.get("schema_version") != 1 or
            manifest.get("release_id") != EXPECTED_ID or
            manifest.get("source_commit") != "815cba9b" or
            not isinstance(files, dict) or set(files) != EXPECTED_FILES):
        raise ValueError("legacy release manifest schema or file set changed")
    for name, expected_sha in sorted(files.items()):
        if (not isinstance(expected_sha, str) or len(expected_sha) != 64 or
                digest(release / name) != expected_sha):
            raise ValueError(f"legacy release file SHA mismatch: {name}")
    return {"status": "verified", "release_id": EXPECTED_ID,
            "manifest_sha256": EXPECTED_MANIFEST_SHA256,
            "verified_file_count": len(files)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.release), sort_keys=True))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"HBASE-34 legacy release verification failed: {exc}")


if __name__ == "__main__":
    main()
