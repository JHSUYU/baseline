#!/usr/bin/env python3
"""Run the original AddReplicaTest method in an isolated scratch directory."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


CASE = Path(__file__).resolve().parents[1]
SOURCE = CASE / "solr-source"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--faults", default="", help="Semicolon-delimited OP|path-part|ordinal selectors")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--original", action="store_true", help="Use unchanged production classes")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if args.original and args.faults:
        parser.error("--original cannot inject faults")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    # A resumed, interrupted trial may already have a partial embedded cluster.
    # Recreate only this trial's scratch so a retry starts from a clean state.
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    cp = (CASE / ("original-classpath.txt" if args.original else "classpath.txt")).read_text().strip()
    command = [
        JAVA, "-ea", "-Xmx3g", "-Djava.awt.headless=true",
        "-Djava.io.tmpdir=" + str(scratch), "-DtempDir=" + str(scratch),
        "-Dtests.seed=F0993D5343E20BA4",
        "-Dtests.src.home=" + str(SOURCE / "solr/core"),
        "-Dcommon.dir=" + str(SOURCE / "lucene"),
        "-Dtests.asserts=true", "-Dtests.slow=true", "-Dtests.nightly=false",
        "-Dtests.timeoutSuite=86400000", "-Dtests.timeout=86400000",
        "-Djetty.testMode=1", "-Djetty.insecurerandom=1",
        "-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory",
        "-Djdk.map.althashing.threshold=0",
        "-Djava.security.egd=file:/dev/./urandom",
        "-Dsolr07.trace=" + str(output / "events.tsv"),
        "-Dsolr07.faults=" + args.faults,
        "-cp", cp, "baseline.solr07.RunSingleJUnit",
        "org.apache.solr.cloud.AddReplicaTest", "testAddMultipleReplicas",
    ]
    if args.coverage:
        agent = CASE / "lib/jacoco-agent.jar"
        command.insert(command.index("-cp"),
            "-javaagent:" + str(agent) + "=destfile=" + str(output / "jacoco.exec")
            + ",append=false,dumponexit=true,includes=org.apache.solr.*")
    started = time.time()
    with (output / "junit.log").open("w") as log:
        try:
            proc = subprocess.run(command, cwd=SOURCE, stdout=log,
                                  stderr=subprocess.STDOUT, check=False,
                                  timeout=args.timeout)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            log.write("\nSOLR07_JUNIT_TIMEOUT\n")
    result = {"case_id": "SOLR-07", "test": "AddReplicaTest.testAddMultipleReplicas",
              "exit_code": exit_code, "elapsed_seconds": time.time() - started,
              "faults": args.faults, "coverage_enabled": args.coverage,
              "original_classes": args.original,
              "log": str(output / "junit.log"), "trace": str(output / "events.tsv")}
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(json.dumps(result), flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
