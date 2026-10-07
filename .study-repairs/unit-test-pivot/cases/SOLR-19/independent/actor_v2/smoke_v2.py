#!/usr/bin/env python3
"""Offline proof that I/O faults match role, path, callsite and ordinal."""

from pathlib import Path
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
JAVA = Path("/usr/lib/jvm/java-8-openjdk-amd64/bin")
CORE = "testAddMultipleReplicas_shard1_replica_n1"
PATH = "/collections/testAddMultipleReplicas/state.json"


def main() -> None:
    cp = str(HERE / "classes") + ":" + (CASE / "original-classpath.txt").read_text().strip()
    subprocess.run([str(JAVA / "javac"), "-cp", cp, "-d", str(HERE / "classes"),
                    str(HERE / "SmokeV2.java")], check=True)
    actors = {
        "JETTY": "JETTY_1",
        "OWNER": "OWNER_OF_CORE:" + CORE,
        "PRODUCER": "PRODUCER_OF_CORE:" + CORE,
    }
    with tempfile.TemporaryDirectory(prefix="solr19-v2-smoke-") as directory:
        for mode, actor in actors.items():
            trace = Path(directory) / (mode + ".tsv")
            selector = "|".join(("GET_DATA", PATH, "<external>", actor, "1"))
            command = [str(JAVA / "java"), "-Xmx256m", "-ea",
                       "-Dsolr19v2.trace=" + str(trace),
                       "-Dsolr19v2.faults=" + selector,
                       "-cp", cp, "baseline.solr19v2.SmokeV2", mode]
            result = subprocess.run(command, text=True, capture_output=True, check=True)
            lines = trace.read_text().splitlines()
            if ("SMOKE_OK " + mode) not in result.stdout or \
                    sum("\tFAULT_MATCHED\t" in line for line in lines) != 1 or \
                    sum("\tFAULT_APPLIED_CONNECTION_LOSS\t" in line for line in lines) != 1:
                raise AssertionError((mode, result.stdout, result.stderr, lines))
            print("SMOKE_OK", mode, len(lines), "events")


if __name__ == "__main__":
    main()
