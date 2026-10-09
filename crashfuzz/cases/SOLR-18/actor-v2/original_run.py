#!/usr/bin/env python3
"""Run the released Solr JUnit with no production bytecode overlay."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from build import (CLEAN_CLASSES, JAVA, SOURCE, TEST_CLASS, TEST_METHOD,
                   clean_classpath)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "scratch"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    command = [
        str(JAVA / "java"), "-ea", "-Xmx4g", "-Djava.awt.headless=true",
        "-Djava.io.tmpdir=" + str(scratch), "-DtempDir=" + str(scratch),
        "-Dtests.seed=D82A1912E3C1791F",
        "-Dtests.src.home=" + str(SOURCE / "solr/core"),
        "-Dcommon.dir=" + str(SOURCE / "lucene"),
        "-Dtests.asserts=true", "-Dtests.slow=true", "-Dtests.nightly=true",
        "-Dtests.timeoutSuite=86400000", "-Dtests.timeout=86400000",
        "-Djetty.testMode=1", "-Djetty.insecurerandom=1",
        "-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory",
        "-Djdk.map.althashing.threshold=0",
        "-Djava.security.egd=file:/dev/./urandom",
        "-cp", clean_classpath(), "research.solr18.OriginalJUnit",
        TEST_CLASS, TEST_METHOD,
    ]
    start = time.monotonic()
    with (output / "console.log").open("w") as log:
        try:
            result = subprocess.run(command, cwd=SOURCE, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=args.timeout,
                                    check=False)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            log.write("\nSOLR18_ORIGINAL_TIMEOUT\n")
    junit_class = CLEAN_CLASSES / "org/apache/solr/cloud/AliasIntegrationTest.class"
    receipt = {
        "test": TEST_CLASS + "#" + TEST_METHOD,
        "source_kind": "released_solr_8_11_4_no_production_overlay",
        "junit_class_sha256": hashlib.sha256(junit_class.read_bytes()).hexdigest(),
        "exit_code": exit_code,
        "elapsed_seconds": round(time.monotonic() - start, 3),
    }
    (output / "run.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
