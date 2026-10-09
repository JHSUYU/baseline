#!/usr/bin/env python3
"""Run unchanged TimeRoutedAliasUpdateProcessorTest.test in an isolated directory."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


CASE = Path(__file__).resolve().parents[1]
SOURCE = CASE.parent / "work/solr-source"
JAVA = "/usr/lib/jvm/java-8-openjdk-amd64/bin/java"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--faults", default="", help="Semicolon-delimited actor V2 selectors")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--original", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if args.original and args.faults:
        parser.error("Original classes cannot inject faults")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
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
        "-Dtests.awaitsfix=true", "-Dtests.badapples=true",
        "-Dsolr.disableConfigSetsCreateAuthChecks=true",
        "-Dtests.timeoutSuite=86400000", "-Dtests.timeout=86400000",
        "-Djetty.testMode=1", "-Djetty.insecurerandom=1",
        "-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory",
        "-Djdk.map.althashing.threshold=0",
        "-Djava.security.egd=file:/dev/./urandom",
        "-Dsolr103940.v2.trace=" + str(output / "events.tsv"),
        "-Dsolr103940.v2.faults=" + args.faults,
        "-cp", cp, "baseline.solr103940.RunSingleJUnit",
        "org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest", "test",
    ]
    if args.coverage:
        agent = CASE.parent / "work/lib/jacoco-agent.jar"
        command.insert(command.index("-cp"),
                       "-javaagent:" + str(agent) + "=destfile=" + str(output / "jacoco.exec")
                       + ",append=false,dumponexit=true,includes=org.apache.solr.*")
    started = time.time()
    with (output / "junit.log").open("w") as log:
        try:
            proc = subprocess.run(command, cwd=SOURCE, stdout=log,
                                  stderr=subprocess.STDOUT, timeout=args.timeout,
                                  check=False)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            log.write("\nSOLR103940_V2_JUNIT_TIMEOUT\n")
    result = {
        "case_ids": ["SOLR-10", "SOLR-39", "SOLR-40"],
        "test": "TimeRoutedAliasUpdateProcessorTest.test",
        "identity_version": "actor-v2",
        "exit_code": exit_code,
        "elapsed_seconds": time.time() - started,
        "faults": args.faults,
        "coverage_enabled": args.coverage,
        "original_classes": args.original,
        "trace": str(output / "events.tsv"),
        "log": str(output / "junit.log"),
    }
    build_receipt = CASE / "build-receipt.json"
    if build_receipt.exists():
        build = json.loads(build_receipt.read_text())
        result.update({
            "build_receipt_sha256": hashlib.sha256(build_receipt.read_bytes()).hexdigest(),
            "source_commit": build.get("source_commit"),
            "original_test_class_sha256": build.get("test_class_sha256"),
            "actor_probe_class_sha256": build.get("actor_probe_class_sha256"),
        })
    temporary = output / "manifest.json.tmp"
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    temporary.replace(output / "manifest.json")
    print(json.dumps(result), flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
