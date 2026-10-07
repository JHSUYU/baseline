#!/usr/bin/env python3
"""Recompute JaCoCo production feedback from an immutable QJM V2 exec."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

from build_offline import BASE, HADOOP, HERE

JDK = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
JACOCO_CORE = Path("/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/"
                   "org.jacoco.core-0.8.15.jar")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_JARS = [ASM / part / "9.6" / (part + "-9.6.jar") for part in
            ("asm", "asm-tree", "asm-commons")]


def convert(case: str, name: str) -> None:
    run = HERE / "evidence" / f"HDFS-{case}" / name
    execution = run / "jacoco.exec"
    if not execution.is_file() or execution.stat().st_size == 0:
        return
    classes = BASE / f"HDFS-{case}" / "independent/build/classes"
    overlay = HERE / "build" / f"HDFS-{case}" / "overlay"
    cp = os.pathsep.join((str(classes), str(JACOCO_CORE),
                         *(str(path) for path in ASM_JARS)))
    with (run / "covered_probes.txt.tmp").open("w") as stream:
        subprocess.run([str(JDK / "java"), "-cp", cp, "CoverageHdfs50",
            str(execution), str(overlay),
            str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"),
            str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar"),
            str(HADOOP / "share/hadoop/common/hadoop-common-3.4.3.jar")],
            stdout=stream, check=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(run / "covered_probes.txt.tmp", run / "covered_probes.txt")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("07", "09", "10"), required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    if (not args.name or any(character not in
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in args.name)):
        parser.error("unsafe run ID")
    convert(args.case, args.name)


if __name__ == "__main__":
    main()
