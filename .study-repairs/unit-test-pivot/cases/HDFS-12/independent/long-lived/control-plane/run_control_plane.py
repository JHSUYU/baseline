#!/usr/bin/env python3
"""Run the original long-lived HDFS JUnit with key-delivery I/O probes."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent.parent
BUILD = HERE / "build"
OVERLAY = HERE / "overlay"
PATCHER = HERE / "PatchHdfs12KeyRpc.java"
CLASSES = (
    "org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class",
    "org/apache/hadoop/hdfs/server/datanode/BPOfferService.class",
)

spec = importlib.util.spec_from_file_location("hdfs12_original", PARENT / "run_original.py")
assert spec is not None and spec.loader is not None
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)
base_instrumentation = original.build_instrumentation


def prepare() -> Path:
    base = base_instrumentation()
    marker = BUILD / "overlay-built"
    base_marker = original.BUILD / "instrumented-built"
    if (marker.is_file() and marker.stat().st_mtime > PATCHER.stat().st_mtime
            and marker.stat().st_mtime > base_marker.stat().st_mtime):
        return OVERLAY
    BUILD.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(OVERLAY, ignore_errors=True)
    shutil.copytree(base, OVERLAY)
    asm = os.pathsep.join(str(path) for path in original.ASM_JARS)
    subprocess.run([str(original.JDK / "javac"), "-cp", asm, "-d", str(BUILD),
                    str(PATCHER)], check=True)
    with zipfile.ZipFile(original.HDFS) as archive:
        for name in CLASSES:
            source = BUILD / "original" / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(archive.read(name))
            subprocess.run([str(original.JDK / "java"), "-cp",
                            os.pathsep.join((str(BUILD), asm)),
                            "PatchHdfs12KeyRpc", str(source), str(OVERLAY)], check=True)
    marker.write_text("released HDFS 3.4.3 classes with key delivery I/O probes\n")
    return OVERLAY


def main() -> None:
    # The parent runner retains the original JUnit launcher, JaCoCo extraction,
    # exact runtime-identity plan and fresh MiniDFSCluster scratch directory.
    original.build_instrumentation = prepare
    sys.argv = [sys.argv[0], "--method", "testLongLivedClient",
                "--parameter", "0", *sys.argv[1:]]
    original.main()


if __name__ == "__main__":
    main()
