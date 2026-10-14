#!/usr/bin/env python3
"""Run the pinned HDFS11 original-seed and Soot static planner together."""

import json
import os
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: run_scope.py <scope-input.json> <fresh-output-dir>")
    source = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    if output.exists():
        raise FileExistsError(output)
    data = json.loads(source.read_text())
    dependency_cp = data["analysis"]["classpath"][0]
    planner = "/dev/shm/mallory-static-scope-1.0-SNAPSHOT.jar"
    java = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"
    for path in [planner, java, *dependency_cp.split(":")]:
        if not Path(path).exists():
            raise FileNotFoundError(path)
    os.execv(java, [java, "-Xmx16g", "-cp", planner + ":" + dependency_cp,
                    "edu.uva.liftlab.mallory.scope.ScopePlanner",
                    str(source), str(output)])


if __name__ == "__main__":
    main()
