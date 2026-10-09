#!/usr/bin/env python3
"""Run unchanged AddReplicaTest on isolated case-local production overlays."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
LOCAL_SOURCE = CASE / "solr-source"
REMOTE_SOURCE = Path("/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4")
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--faults", default="", help="Ordered OP|PATH|CALLER|ACTOR|ORDINAL selectors")
    args = parser.parse_args()
    source = args.source_root or (LOCAL_SOURCE if LOCAL_SOURCE.exists() else REMOTE_SOURCE)
    if not (source / "solr/core/src/test/org/apache/solr/cloud/AddReplicaTest.java").exists():
        raise SystemExit(f"exact original source absent: {source}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    original_cp = (CASE / "original-classpath.txt").read_text().strip()
    cp = original_cp.replace(str(LOCAL_SOURCE), str(source))
    cp = str(HERE / "classes") + ":" + cp
    command = [
        JAVA, "-ea", "-Xmx3g", "-Djava.awt.headless=true",
        "-Djava.io.tmpdir=" + str(scratch), "-DtempDir=" + str(scratch),
        "-Dtests.seed=F0993D5343E20BA4",
        "-Dtests.src.home=" + str(source / "solr/core"),
        "-Dcommon.dir=" + str(source / "lucene"),
        "-Dtests.asserts=true", "-Dtests.slow=true", "-Dtests.nightly=false",
        "-Dtests.timeoutSuite=86400000", "-Dtests.timeout=86400000",
        "-Djetty.testMode=1", "-Djetty.insecurerandom=1",
        "-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory",
        "-Djdk.map.althashing.threshold=0", "-Djava.security.egd=file:/dev/./urandom",
        "-Dsolr19v2.trace=" + str(output / "actor-events.tsv"),
        "-Dsolr19v2.faults=" + args.faults,
    ]
    if args.coverage:
        command.append("-javaagent:" + str(CASE / "lib/jacoco-agent.jar")
                       + "=destfile=" + str(output / "jacoco.exec")
                       + ",append=false,dumponexit=true,includes=org.apache.solr.*")
    command += ["-cp", cp, "baseline.solr19.RunSingleJUnit",
                "org.apache.solr.cloud.AddReplicaTest", "testAddMultipleReplicas"]
    started = time.time()
    with (output / "junit.log").open("w") as log:
        try:
            result = subprocess.run(command, cwd=source, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=args.timeout,
                                    check=False)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            log.write("\nSOLR19_V2_JUNIT_TIMEOUT\n")
    manifest = {
        "case_id": "SOLR-19", "phase": "actor_v2_fault" if args.faults else "actor_v2_healthy",
        "original_junit": "AddReplicaTest.testAddMultipleReplicas",
        "original_source_commit": "e27f44e", "exit_code": exit_code,
        "elapsed_seconds": round(time.time() - started, 3),
        "coverage_enabled": args.coverage, "source_root": str(source),
        "faults": args.faults,
        "trace": str(output / "actor-events.tsv"),
        "junit_log": str(output / "junit.log"),
    }
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(json.dumps(manifest), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
