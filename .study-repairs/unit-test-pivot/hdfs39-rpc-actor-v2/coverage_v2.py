#!/usr/bin/env python3
"""Convert a V2 run's JaCoCo exec to stable production feedback IDs."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

from build_offline import CASE, HADOOP, HERE, JDK, OVERLAY


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
           for char in args.name) or not args.name:
        parser.error("unsafe run ID")
    run = HERE / "evidence" / args.name
    execution = run / "jacoco.exec"
    if not execution.is_file():
        parser.error("run lacks JaCoCo exec")
    classes = HERE / "build/coverage-classes"
    if not (classes / "CoverageDumpV2.class").is_file():
        parser.error("run build_offline.py to compile V2-aware coverage converter")
    jars = sorted((CASE / "deps").glob("*.jar"))
    cp = os.pathsep.join(str(path) for path in jars)
    runtime = os.pathsep.join((str(classes), cp))
    hdfs = HADOOP / "share/hadoop/hdfs"
    output = run / "coverage.tsv"
    if output.exists():
        parser.error("coverage.tsv exists; retain immutable feedback")
    temporary = run / "coverage.tsv.tmp"
    with temporary.open("w") as stream:
        subprocess.run([str(JDK / "java"), "-Xmx2g", "-cp", runtime,
            "CoverageDumpV2", str(execution), str(OVERLAY),
            str(hdfs / "hadoop-hdfs-3.4.3.jar"),
            str(hdfs / "hadoop-hdfs-client-3.4.3.jar")],
            stdout=stream, check=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output)
    print(output)


if __name__ == "__main__":
    main()
