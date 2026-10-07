#!/usr/bin/env python3
"""Export production-only JaCoCo feedback for the HDFS-43 actor V2 run."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

from run_original import HADOOP, HERE, JDK

M2 = Path.home() / ".m2/repository"
JARS = [
    M2 / "org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar",
    M2 / "org/ow2/asm/asm/9.6/asm-9.6.jar",
    M2 / "org/ow2/asm/asm-tree/9.6/asm-tree-9.6.jar",
    M2 / "org/ow2/asm/asm-commons/9.6/asm-commons-9.6.jar",
]


def run(execution: Path, output: Path) -> None:
    if any(not path.is_file() for path in JARS):
        raise FileNotFoundError("JaCoCo/ASM dependency missing")
    classes = HERE / "coverage-classes"
    classes.mkdir(exist_ok=True)
    source = HERE / "CoverageDump.java"
    compiled = classes / "CoverageDump.class"
    libs = os.pathsep.join(str(path) for path in JARS)
    if not compiled.is_file() or compiled.stat().st_mtime < source.stat().st_mtime:
        subprocess.run([str(JDK / "javac"), "-cp", libs, "-d", str(classes),
                        str(source)], check=True)
    runtime = os.pathsep.join((str(classes), libs))
    hdfs = HADOOP / "share/hadoop/hdfs"
    common = HADOOP / "share/hadoop/common"
    command = [str(JDK / "java"), "-Xmx2g", "-cp", runtime,
               "CoverageDump", str(execution), str(HERE / "probe-classes"),
               str(hdfs / "hadoop-hdfs-3.4.3.jar"),
               str(hdfs / "hadoop-hdfs-client-3.4.3.jar"),
               str(common / "hadoop-common-3.4.3.jar")]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("w") as stream:
        subprocess.run(command, stdout=stream, check=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exec", dest="execution", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.execution, args.output)
