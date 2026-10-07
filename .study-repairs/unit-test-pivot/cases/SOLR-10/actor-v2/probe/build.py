#!/usr/bin/env python3
"""Offline actor V2 build; compiles the unchanged original test into both classpaths."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys


CASE = Path(__file__).resolve().parents[1]
OLD = CASE.parent / "work"
SOURCE = OLD / "solr-source"
JAVAC = "/usr/lib/jvm/java-8-openjdk-amd64/bin/javac"
ASM = Path("/users/ZhenyuLi/.m2/repository/org/ow2/asm")
VERSION = "9.10.1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    for name in ("classes", "classes-original"):
        (CASE / name).mkdir(parents=True, exist_ok=True)
    old = (OLD / "classpath.txt").read_text().strip().split(":")
    assert old[0] == str(OLD / "classes"), old[0]
    source_cp = old[1:]
    instrumented = ":".join([str(CASE / "classes"), *source_cp])
    original = ":".join([str(CASE / "classes-original"), *source_cp])
    (CASE / "classpath.txt").write_text(instrumented + "\n")
    (CASE / "original-classpath.txt").write_text(original + "\n")
    tests = [SOURCE / "solr/core/src/test/org/apache/solr/update/processor" / name
             for name in ("TrackingUpdateProcessorFactory.java",
                          "RoutedAliasUpdateProcessorTest.java",
                          "TimeRoutedAliasUpdateProcessorTest.java")]
    for classpath, directory in ((instrumented, CASE / "classes"),
                                 (original, CASE / "classes-original")):
        subprocess.run([JAVAC, "-cp", classpath, "-d", str(directory),
                        str(CASE / "probe/RunSingleJUnit.java"),
                        *map(str, tests)], check=True)
    asm = [ASM / module / VERSION / f"{module}-{VERSION}.jar"
           for module in ("asm", "asm-tree", "asm-commons")]
    helpers = ":".join(map(str, [CASE / "classes", OLD / "lib/jacoco-core.jar", *asm]))
    subprocess.run([JAVAC, "-cp", helpers, "-d", str(CASE / "classes"),
                    str(CASE / "probe/CoverageProbes.java"),
                    str(CASE / "probe/CoverageSummary.java"),
                    str(CASE / "probe/CoverageFeedback.java")], check=True)
    subprocess.run([sys.executable, str(CASE / "probe/weave.py")], check=True)
    target = Path("org/apache/solr/update/processor/TimeRoutedAliasUpdateProcessorTest.class")
    original_hash = digest(CASE / "classes-original" / target)
    instrumented_hash = digest(CASE / "classes" / target)
    if original_hash != instrumented_hash:
        raise RuntimeError("Original JUnit bytecode differs between classpaths")
    (CASE / "build-receipt.json").write_text(json.dumps({
        "test_class_sha256": original_hash,
        "unchanged_junit_class": True,
        "source": str(SOURCE),
        "instrumented_classpath": str(CASE / "classpath.txt"),
        "original_classpath": str(CASE / "original-classpath.txt"),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
