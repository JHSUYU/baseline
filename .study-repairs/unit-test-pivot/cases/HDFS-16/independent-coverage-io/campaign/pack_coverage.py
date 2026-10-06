#!/usr/bin/env python3
"""Losslessly pack completed HDFS-16 production coverage TSVs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tarfile


CASE = Path(__file__).resolve().parents[1]
STATE = CASE / "campaign/checkpoint.json"
ARCHIVE = CASE / "coverage-evidence.tar.gz"


def main() -> None:
    rows = json.loads(STATE.read_text())["completed"]
    files = [CASE / "campaign" / row["trial"] / "coverage.tsv" for row in rows]
    if not rows or not all(path.is_file() for path in files):
        raise RuntimeError("every completed trial needs raw coverage before packing")
    temporary = ARCHIVE.with_name(ARCHIVE.name + f".tmp.{os.getpid()}")
    with tarfile.open(temporary, "w:gz") as archive:
        for path in files:
            archive.add(path, arcname=path.relative_to(CASE).as_posix())
    with tarfile.open(temporary, "r:gz") as archive:
        assert set(archive.getnames()) == {
            path.relative_to(CASE).as_posix() for path in files}
        for path in files:
            stream = archive.extractfile(path.relative_to(CASE).as_posix())
            assert stream is not None and stream.read() == path.read_bytes()
    os.replace(temporary, ARCHIVE)
    print(json.dumps({"trials": len(rows), "archive": str(ARCHIVE),
                      "bytes": ARCHIVE.stat().st_size}))


if __name__ == "__main__":
    main()
