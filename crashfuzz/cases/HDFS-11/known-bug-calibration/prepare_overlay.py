#!/usr/bin/env python3
"""Overlay the original HDFS-11 check recorder with outbound SASL I/O tracing."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import zipfile


HERE = Path(__file__).resolve().parent
BASE = HERE.parent / "independent" / "run_original.py"
spec = importlib.util.spec_from_file_location("hdfs11_runner", BASE)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
BUILD = HERE / "build"
OVERLAY = BUILD / "overlay"
CLIENT_CLASS = (
    "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/"
    "SaslDataTransferClient.class"
)


def main() -> None:
    base_overlay = runner.build_instrumentation()
    source_files = [HERE / name for name in
                    ("Hdfs17967Probe.java", "PatchOutboundSasl.java")]
    marker = BUILD / "build.json"
    if marker.is_file() and marker.stat().st_mtime > max(p.stat().st_mtime for p in source_files):
        print(marker.read_text())
        return
    BUILD.mkdir(parents=True, exist_ok=True)
    if OVERLAY.exists():
        shutil.rmtree(OVERLAY)
    shutil.copytree(base_overlay, OVERLAY)
    cp = ":".join(str(p) for p in
                  [runner.HDFS_CLIENT, runner.HDFS, runner.COMMON, *runner.ASM_JARS])
    subprocess.run([str(runner.JDK / "javac"), "-cp", cp, "-d", str(BUILD),
                    *(str(p) for p in source_files)], check=True)
    shutil.copy2(BUILD / "Hdfs17967Probe.class", OVERLAY / "Hdfs17967Probe.class")
    original = BUILD / "SaslDataTransferClient.original.class"
    with zipfile.ZipFile(runner.HDFS_CLIENT) as jar:
        original.write_bytes(jar.read(CLIENT_CLASS))
    subprocess.run([str(runner.JDK / "java"), "-cp",
                    str(BUILD) + ":" + ":".join(str(p) for p in runner.ASM_JARS),
                    "PatchOutboundSasl", str(original), str(OVERLAY)], check=True)
    result = {"release_client_jar_sha256": hashlib.sha256(
                  runner.HDFS_CLIENT.read_bytes()).hexdigest(),
              "original_class_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
              "patched_class_sha256": hashlib.sha256((OVERLAY / CLIENT_CLASS).read_bytes()).hexdigest(),
              "base_hdfs11_overlay": str(base_overlay),
              "graphchecker_runtime": False,
              "hook": "SaslDataTransferClient.socketSend seven-argument outbound I/O"}
    marker.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
