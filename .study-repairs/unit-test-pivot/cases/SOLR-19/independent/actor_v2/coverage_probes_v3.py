#!/usr/bin/env python3
"""Return exact production JaCoCo probe IDs for mutation feedback."""

from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
JAVA = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
DIST = Path("/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist")
JACOCO = CASE / "lib/jacoco-core.jar"


def covered(exec_file: Path) -> set[str]:
    if not exec_file.exists():
        return set()
    compiled = HERE / "classes/baseline/solr19v2/CoverageProbes.class"
    if not compiled.exists() or compiled.stat().st_mtime < (HERE / "CoverageProbes.java").stat().st_mtime:
        subprocess.run([str(JAVA / "javac"), "-cp", str(JACOCO),
                        "-d", str(HERE / "classes"), str(HERE / "CoverageProbes.java")], check=True)
    output = subprocess.check_output([str(JAVA / "java"), "-cp",
                                     str(HERE / "classes") + ":" + str(JACOCO),
                                     "baseline.solr19v2.CoverageProbes", str(DIST),
                                     str(exec_file)], text=True)
    return set(output.splitlines())


if __name__ == "__main__":
    import sys
    for item in sorted(covered(Path(sys.argv[1]))):
        print(item)
