#!/usr/bin/env python3
"""Verify isolated V2 ASM hooks against the original Solr 8.11.4 class bytes."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / "independent"
sys.path.insert(0, str(PARENT))
from build import JAVA8, original_classpath  # noqa: E402


def main() -> None:
    cp = original_classpath() + ":" + str(HERE / "agent-classes")
    source = HERE / "src/research/solrsubshardv2/SmokeTransform.java"
    subprocess.run([str(JAVA8 / "javac"), "-source", "8", "-target", "8",
                    "-cp", cp, "-d", str(HERE / "agent-classes"), str(source)],
                   check=True)
    trace = HERE / "smoke-events.jsonl"
    subprocess.run([str(JAVA8 / "java"), "-Xverify:all",
                    "-Dsolrsubshard.trace.file=" + str(trace),
                    "-cp", cp, "research.solrsubshardv2.SmokeTransform"],
                   check=True)


if __name__ == "__main__":
    main()
