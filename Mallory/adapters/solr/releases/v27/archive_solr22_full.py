#!/usr/bin/env python3
"""Create and reverify a lossless offhost archive of SOLR-22's terminal run."""

import hashlib
import json
import os
from pathlib import Path
import tarfile
import sys


EXPECTED_RESULT = "e99cbb27f9397f9427d8e4f4677b4bce856e072f8fdc0ec036c294a5c1c14ca9"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    source = Path(sys.argv[1]).resolve()
    archive = Path(sys.argv[2]).resolve()
    manifest_path = Path(sys.argv[3]).resolve()
    receipt_path = Path(sys.argv[4]).resolve()
    result_path = source / "result.json"
    result = json.loads(result_path.read_text())
    if (result.get("case_id") != "SOLR-22" or result.get("status") != "budget_exhausted"
            or result.get("fault_trials_completed") != 80
            or digest(result_path) != EXPECTED_RESULT):
        raise ValueError("SOLR-22 terminal source/result pin differs")
    if archive.exists() or manifest_path.exists() or receipt_path.exists():
        raise FileExistsError("archive output already exists")
    members = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in terminal evidence: " + str(path))
        if not path.is_file():
            continue
        relative = str(path.relative_to(source))
        members[relative] = {"sha256": digest(path), "bytes": path.stat().st_size,
                             "mode": path.stat().st_mode & 0o777}
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(archive.name + f".partial-{os.getpid()}")
    try:
        with tarfile.open(temporary, "w:gz") as stream:
            for relative in members:
                stream.add(source / relative, arcname=relative, recursive=False)
        with tarfile.open(temporary, "r:gz") as stream:
            found = {}
            for member in stream:
                if not member.isfile() or member.name not in members or member.name in found:
                    raise ValueError("unexpected archive member: " + member.name)
                content = stream.extractfile(member)
                if content is None:
                    raise ValueError("missing archive content")
                value = hashlib.sha256()
                count = 0
                for block in iter(lambda: content.read(1024 * 1024), b""):
                    value.update(block)
                    count += len(block)
                if (value.hexdigest() != members[member.name]["sha256"]
                        or count != members[member.name]["bytes"]):
                    raise ValueError("archive member differs: " + member.name)
                found[member.name] = True
            if set(found) != set(members):
                raise ValueError("archive member set differs")
        os.replace(temporary, archive)
    finally:
        if temporary.exists():
            temporary.unlink()
    # Re-read every source member to catch a concurrent change during archiving.
    for relative, record in members.items():
        if digest(source / relative) != record["sha256"]:
            raise ValueError("terminal source changed: " + relative)
    manifest = {"schema_version": 1, "case_id": "SOLR-22",
                "source_root": str(source), "terminal_result_sha256": EXPECTED_RESULT,
                "members": members}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    receipt = {"schema_version": 1, "case_id": "SOLR-22",
               "archive_path": str(archive), "archive_sha256": digest(archive),
               "archive_bytes": archive.stat().st_size,
               "manifest_path": str(manifest_path),
               "manifest_sha256": digest(manifest_path),
               "terminal_result_sha256": EXPECTED_RESULT,
               "member_count": len(members),
               "logical_member_bytes": sum(record["bytes"] for record in members.values()),
               "source_preserved": True, "archive_members_reverified": True}
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"archive_sha256": receipt["archive_sha256"],
                      "archive_bytes": receipt["archive_bytes"],
                      "manifest_sha256": receipt["manifest_sha256"],
                      "member_count": len(members)}, sort_keys=True))


if __name__ == "__main__":
    main()
