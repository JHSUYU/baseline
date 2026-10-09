#!/usr/bin/env python3
"""Build or verify the deterministic, source-only HDFS-12 handoff bundle."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECEIPT = HERE / "source-release-receipt.json"
FILES = (
    "README.md", "HDFS-12.sites.json", "HDFS-12-healthy-only.json",
    "HDFS-12-token-window-proof.json", "HDFS-12-token-window-review.md",
    "check_offline.py", "check_overlay.py", "audit_timeline.py",
    "test_audit_timeline.py", "package_source.py",
    "overlay/HdfsMiniClusterTransformer.java", "overlay/HdfsHooks.java",
    "overlay/Hdfs12KeyHooks.java", "overlay/Probe.java",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def bundle() -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name in FILES:
                content = (HERE / name).read_bytes()
                item = tarfile.TarInfo(name)
                item.size = len(content)
                item.mode = 0o644
                item.mtime = 0
                item.uid = item.gid = 0
                item.uname = item.gname = ""
                archive.addfile(item, io.BytesIO(content))
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    data = bundle()
    sha = digest(data)
    archive = HERE / "source-release" / sha / "hdfs12-source-bundle.tar.gz"
    expected = {
        "schema_version": 1,
        "case_id": "HDFS-12",
        "status": "source_only_unbuilt_unrun_no_healthy_admission",
        "archive_path": str(archive),
        "archive_sha256": sha,
        "files": [{"path": name, "sha256": digest((HERE / name).read_bytes())}
                  for name in FILES],
        "requires_future_release": [
            "isolated instrumentation JAR containing overlay/Probe.java",
            "isolated HDFS adapter JAR containing the three overlay HDFS classes",
            "dispatch HDFS source lane and exact indexed healthy JUnit gate",
        ],
    }
    if args.verify:
        assert archive.is_file() and archive.read_bytes() == data
        assert json.loads(RECEIPT.read_text()) == expected
        print(f"PASS: immutable HDFS-12 source bundle {sha}")
        return
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        assert archive.read_bytes() == data
    else:
        archive.write_bytes(data)
    RECEIPT.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    print(f"FROZEN: {archive} SHA-256 {sha}")


if __name__ == "__main__":
    main()
