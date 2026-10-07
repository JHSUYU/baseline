#!/usr/bin/env python3
"""Convert one immutable V2 JaCoCo exec into production coverage feedback."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess

from build_offline import BUILD, CASE, HADOOP, HERE, JDK, OVERLAY


def convert(name: str) -> None:
    run = HERE / "evidence" / name
    execution = run / "jacoco.exec"
    if not execution.is_file() or not execution.stat().st_size:
        raise ValueError("raw JaCoCo is absent")
    classes = BUILD / "runner-classes"
    dependencies = sorted((CASE / "deps").glob("*.jar"))
    cp = os.pathsep.join((str(classes), *(str(path) for path in dependencies)))
    output = run / "coverage.tsv"
    temp = output.with_name(output.name + ".tmp")
    command = [str(JDK / "java"), "-Xmx2g", "-cp", cp, "CoverageDump",
        str(execution), str(OVERLAY),
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-3.4.3.jar"),
        str(HADOOP / "share/hadoop/hdfs/hadoop-hdfs-client-3.4.3.jar")]
    with temp.open("w") as stream:
        subprocess.run(command, stdout=stream, check=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    if (not args.name or any(c not in
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for c in args.name)):
        parser.error("unsafe run ID")
    convert(args.name)


if __name__ == "__main__":
    main()
