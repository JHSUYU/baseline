#!/usr/bin/env python3
"""Rebuild the case-local runner and observation hooks from the clean Solr source."""

from pathlib import Path
import subprocess
import sys


WORK = Path(__file__).resolve().parents[1]
PROBE = WORK / "probe"
JAVAC = "/usr/lib/jvm/java-8-openjdk-amd64/bin/javac"
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
VERSION = "9.10.1"


def main() -> None:
    for directory in (WORK / "classes", WORK / "classes-probe"):
        directory.mkdir(parents=True, exist_ok=True)
    base_cp = (WORK / "classpath.txt").read_text().strip()
    subprocess.run([JAVAC, "-cp", base_cp, "-d", str(WORK / "classes"),
                    str(PROBE / "RunSingleJUnit.java")], check=True)
    asm = [ASM / module / VERSION / f"{module}-{VERSION}.jar"
           for module in ("asm", "asm-tree", "asm-commons")]
    helper_cp = ":".join(map(str, [WORK / "classes", WORK / "lib/jacoco-core.jar", *asm]))
    subprocess.run([JAVAC, "-cp", helper_cp, "-d", str(WORK / "classes-probe"),
                    str(PROBE / "CoverageProbes.java"),
                    str(PROBE / "CoverageSummary.java")], check=True)
    subprocess.run([sys.executable, str(PROBE / "weave.py")], check=True)


if __name__ == "__main__":
    main()
