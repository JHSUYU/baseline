#!/usr/bin/env python3
"""Merge original HDFS-11 probes with released-class key delivery I/O hooks."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import zipfile


HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
BUILD = HERE / "build"
OVERLAY = HERE / "overlay"
HDFS = Path("/users/ZhenyuLi/.baseline-deps/hadoop-3.4.3/share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar")
CLASSES = (
    "org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class",
    "org/apache/hadoop/hdfs/server/datanode/BPOfferService.class",
)


def prepare() -> Path:
    source = HERE / "PatchHdfs11KeyRpc.java"
    marker = BUILD / "merged-built"
    if marker.exists() and marker.stat().st_mtime > source.stat().st_mtime:
        return OVERLAY
    spec = importlib.util.spec_from_file_location("hdfs11_original", PARENT / "run_original.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    base_overlay = module.build_instrumentation()
    BUILD.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(OVERLAY, ignore_errors=True)
    shutil.copytree(base_overlay, OVERLAY)
    asm = os.pathsep.join(str(path) for path in module.ASM_JARS)
    subprocess.run([str(module.JDK / "javac"), "-cp", asm, "-d", str(BUILD),
                    str(source)], check=True)
    with zipfile.ZipFile(HDFS) as archive:
        for name in CLASSES:
            original = BUILD / "original" / name
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(archive.read(name))
            subprocess.run([str(module.JDK / "java"), "-cp",
                            os.pathsep.join((str(BUILD), asm)), "PatchHdfs11KeyRpc",
                            str(original), str(OVERLAY)], check=True)
    marker.write_text("HDFS-11 key expiry overlay; released 3.4.3 classes\n")
    return OVERLAY


if __name__ == "__main__":
    print(prepare())
