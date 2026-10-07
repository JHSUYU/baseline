#!/usr/bin/env python3
"""Run unchanged AddReplicaTest.testAddMultipleReplicas in isolated scratch."""

import argparse
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


CASE = Path(__file__).resolve().parents[1]
SOURCE = CASE.parent / "solr-source"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--faults", default="", help="Semicolon-delimited actor V2 selectors")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--original", action="store_true")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    if args.original and args.faults:
        parser.error("Original classes cannot inject faults")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # An interrupted inflight trial restarts in this directory. Never accept
    # its previous trace, JaCoCo file or manifest as evidence for the rerun.
    for name in ("events.tsv", "jacoco.exec", "manifest.json", "manifest.json.tmp"):
        (output / name).unlink(missing_ok=True)
    scratch = output / "scratch"
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
        "-Dsolr05.v4.trace=" + str(output / "events.tsv"),
        "-Dsolr05.v4.faults=" + args.faults,
        "-cp", cp, "baseline.solr05v4.RunSingleJUnit",
        "org.apache.solr.cloud.AddReplicaTest", "testAddMultipleReplicas",
    ]
    if args.coverage:
        agent = CASE.parent / "lib/jacoco-agent.jar"
        command.insert(command.index("-cp"),
                       "-javaagent:" + str(agent) + "=destfile=" + str(output / "jacoco.exec")
                       + ",append=false,dumponexit=true,includes=org.apache.solr.*")
    started = time.time()
    with (output / "junit.log").open("w") as log:
        try:
            lock_path = Path("/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/jvm-start.lock")
            with lock_path.open("a+") as gate:
                while True:
                    fcntl.flock(gate, fcntl.LOCK_EX)
                    running = subprocess.run(["pgrep", "-c", "java"],
                                             capture_output=True, text=True, check=False)
                    count = int(running.stdout.strip() or 0)
                    if count < 5 and shutil.disk_usage(CASE).free >= 3 * 1024**3:
                        proc = subprocess.Popen(command, cwd=SOURCE, stdout=log,
                                                stderr=subprocess.STDOUT)
                        fcntl.flock(gate, fcntl.LOCK_UN)
                        break
                    fcntl.flock(gate, fcntl.LOCK_UN)
                    time.sleep(10)
            exit_code = proc.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            exit_code = 124
            log.write("\nSOLR05_V4_JUNIT_TIMEOUT\n")
    result = {
        "case_ids": ["SOLR-05"],
        "test": "AddReplicaTest.testAddMultipleReplicas",
        "identity_version": "receiver-state-read-v4",
        "exit_code": exit_code,
        "elapsed_seconds": time.time() - started,
        "faults": args.faults,
        "coverage_enabled": args.coverage,
        "original_classes": args.original,
        "trace": str(output / "events.tsv"),
        "log": str(output / "junit.log"),
    }
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(json.dumps(result), flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
