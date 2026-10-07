#!/usr/bin/env python3
"""Compile unchanged TestPullReplica and case-local graph-free probes."""

from pathlib import Path
import subprocess
import sys


CASE = Path(__file__).resolve().parents[1]
PROBE = CASE / "probe"
JAVAC = "/usr/lib/jvm/java-8-openjdk-amd64/bin/javac"
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
VERSION = "9.10.1"


def main() -> None:
    classes = CASE / "classes"
    original = CASE / "classes-original"
    classes.mkdir(parents=True, exist_ok=True)
    original.mkdir(parents=True, exist_ok=True)
    cp = (CASE / "classpath.txt").read_text().strip()
    test = CASE / "solr-source/solr/core/src/test/org/apache/solr/cloud/TestPullReplica.java"
    subprocess.run([JAVAC, "-cp", cp, "-d", str(classes),
                    str(PROBE / "RunSingleJUnit.java"), str(test)], check=True)
    original_cp = cp.replace(str(classes), str(original), 1)
    subprocess.run([JAVAC, "-cp", original_cp, "-d", str(original),
                    str(PROBE / "RunSingleJUnit.java"), str(test)], check=True)
    (CASE / "original-classpath.txt").write_text(original_cp + "\n")
    asm = [ASM / module / VERSION / f"{module}-{VERSION}.jar"
           for module in ("asm", "asm-tree", "asm-commons")]
    helpers = ":".join(map(str, [classes, CASE / "lib/jacoco-core.jar", *asm]))
    subprocess.run([JAVAC, "-cp", helpers, "-d", str(classes),
                    str(PROBE / "CoverageProbes.java"),
                    str(PROBE / "CoverageSummary.java")], check=True)
    subprocess.run([sys.executable, str(PROBE / "weave.py")], check=True)


if __name__ == "__main__":
    main()
