#!/usr/bin/env python3
"""Materialize only the pinned HDFS-18 adapted JUnit source on node2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]
from preflight import ORIGINAL, REFERENCE, source_digest  # noqa: E402
sys.path.insert(0, str(HERE.parent / "hdfs18-provided-heartbeat-v2"))
from prepare_overlay import render  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if socket.gethostname().split(".")[0] != "node2":
        raise RuntimeError("this source materialization is scoped to node2")
    pins = json.loads((HERE / "package-manifest.json").read_text())
    reference = json.loads(REFERENCE.read_text())["roots"][str(ORIGINAL)]
    if source_digest(ORIGINAL, reference["paths"]) != pins["original_full_source_digest"]:
        raise RuntimeError("original full Hadoop source snapshot changed")
    archive = Path(pins["compiled_target_archive_path"])
    if sha(archive) != pins["compiled_target_archive_sha256"]:
        raise RuntimeError("compiled target archive changed")
    root = Path(pins["source_root"])
    if root.exists():
        raise RuntimeError("dedicated HDFS-18 source root already exists")
    root.mkdir(parents=True)
    subprocess.run(["rsync", "-a", "--exclude=.git", "--exclude=target",
                    str(ORIGINAL) + "/", str(root) + "/"], check=True)
    source = root / pins["test_source_relative"]
    receipt = json.loads((HERE.parent / "hdfs18-provided-heartbeat-v2" /
                          "source-overlay-receipt.json").read_text())
    source.write_bytes(render(source.read_bytes(), receipt))
    module = root / "hadoop-hdfs-project/hadoop-hdfs"
    subprocess.run(["tar", "-C", str(module), "-I", "zstd", "-xf", str(archive)], check=True)
    subprocess.run([sys.executable, "-B", str(HERE / "preflight.py")], check=True)


if __name__ == "__main__":
    main()
