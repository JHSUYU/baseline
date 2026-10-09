#!/usr/bin/env python3
"""Convert per-run JaCoCo data to stable HDFS probe/method/branch feedback."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

from run_original import CASE, HERE, HADOOP, JDK


def main(execution: Path, output: Path) -> None:
    jars = sorted((CASE / "deps").glob("*.jar"))
    if len(jars) < 5:
        raise RuntimeError("case-local JaCoCo/ASM jars are missing")
    cp = os.pathsep.join(str(jar) for jar in jars)
    classes = HERE / "coverage-classes"
    classes.mkdir(exist_ok=True)
    source = HERE / "CoverageDump.java"
    compiled = classes / "CoverageDump.class"
    if not compiled.is_file() or compiled.stat().st_mtime < source.stat().st_mtime:
        subprocess.run([str(JDK / "javac"), "-cp", cp, "-d", str(classes),
                        str(source)], check=True)
    runtime = os.pathsep.join((str(classes), cp))
    hdfs = HADOOP / "share/hadoop/hdfs"
    command = [str(JDK / "java"), "-Xmx2g", "-cp", runtime,
               "CoverageDump", str(execution), str(HERE / "probe-classes"),
               str(hdfs / "hadoop-hdfs-3.4.3.jar"),
               str(hdfs / "hadoop-hdfs-client-3.4.3.jar")]
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
    main(args.execution, args.output)
