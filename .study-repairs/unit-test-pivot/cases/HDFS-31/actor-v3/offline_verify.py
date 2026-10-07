#!/usr/bin/env python3
"""Build V3, verify its five patched classes without starting Hadoop services."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import run_original


def main() -> None:
    run_original.build()
    env = dict(os.environ, JAVA_HOME=str(run_original.JDK.parent))
    hadoop_cp = subprocess.check_output(
        [str(run_original.HADOOP / "bin/hadoop"), "classpath", "--glob"],
        env=env, text=True).strip()
    m2 = Path("/users/ZhenyuLi/.m2/repository")
    extras = [m2 / "org/mockito/mockito-core/4.9.0/mockito-core-4.9.0.jar",
              m2 / "net/bytebuddy/byte-buddy/1.12.16/byte-buddy-1.12.16.jar",
              m2 / "net/bytebuddy/byte-buddy-agent/1.12.16/byte-buddy-agent-1.12.16.jar",
              m2 / "org/objenesis/objenesis/3.3/objenesis-3.3.jar"]
    cp = os.pathsep.join((str(run_original.OVERLAY),
                          str(run_original.BUILD / "classes"),
                          str(run_original.TESTS),
                          str(run_original.HADOOP / "share/hadoop/common/hadoop-common-3.4.3-tests.jar"),
                          hadoop_cp, *(str(p) for p in extras),
                          *(str(p) for p in sorted(
                              (run_original.HADOOP / "share/hadoop/tools/lib").glob("*.jar")))))
    classes = [name.replace("/", ".") for name in run_original.PATCHED]
    cmd = [str(run_original.JDK / "java"), "-Xverify:all", "-cp", cp,
           "VerifyOverlay", *classes]
    completed = subprocess.run(cmd, env=env, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stdout + completed.stderr)
    if completed.stdout.splitlines() != classes:
        raise RuntimeError("overlay class load did not report every expected class")
    print("V3 overlay bytecode verified: " + ", ".join(classes))


if __name__ == "__main__":
    main()
