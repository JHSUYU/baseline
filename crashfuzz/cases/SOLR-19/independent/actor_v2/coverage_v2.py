#!/usr/bin/env python3
"""Summarize JaCoCo on original Solr production plus case-local woven classes."""

import argparse
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
JAVA_HOME = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
ASM_VERSION = "9.10.1"
JACOCO = CASE / "lib/jacoco-core.jar"
DIST = Path("/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("exec_files", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    subprocess.run([str(JAVA_HOME / "javac"), "-cp", str(JACOCO),
                    "-d", str(HERE / "classes"), str(HERE / "CoverageSummary.java")], check=True)
    cp = ":".join(map(str, [HERE / "classes", JACOCO,
        ASM / "asm" / ASM_VERSION / f"asm-{ASM_VERSION}.jar",
        ASM / "asm-tree" / ASM_VERSION / f"asm-tree-{ASM_VERSION}.jar",
        ASM / "asm-commons" / ASM_VERSION / f"asm-commons-{ASM_VERSION}.jar"]))
    command = [str(JAVA_HOME / "java"), "-cp", cp, "baseline.solr19v2.CoverageSummary",
               str(DIST), str(HERE / "classes")] + [str(path) for path in args.exec_files]
    result = json.loads(subprocess.check_output(command, text=True))
    result["exec_files"] = [str(path) for path in args.exec_files]
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
