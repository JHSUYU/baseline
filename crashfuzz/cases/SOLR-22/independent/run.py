#!/usr/bin/env python3
"""Run unmodified TestPullReplica.testAddDocs with independent event probes."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from build import HERE, CASE, JAVA8, original_classpath


TEST_CLASS = 'org.apache.solr.cloud.TestPullReplica'
TEST_METHOD = 'testAddDocs'
SOURCE = HERE / 'solr-pristine'


def run(out: Path, fault_plan: Path | None = None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / 'scratch'
    scratch.mkdir(exist_ok=True)
    cp = ':'.join((str(HERE / 'classes'), original_classpath()))
    command = [
        str(JAVA8 / 'java'), '-ea', '-Xmx3g',
        '-javaagent:' + str(CASE / 'v5/lib/jacoco-agent.jar')
        + '=destfile=' + str(out / 'jacoco.exec')
        + ',append=false,dumponexit=true,includes=org.apache.solr.*:org.apache.lucene.*',
        '-javaagent:' + str(HERE / 'solr22-independent-agent.jar'),
        '-Dsolr22.trace.file=' + str(out / 'events.jsonl'),
        '-Djava.awt.headless=true',
        '-Djava.io.tmpdir=' + str(scratch),
        '-DtempDir=' + str(scratch),
        '-Dtests.seed=F0993D5343E20BA4',
        '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
        '-Dcommon.dir=' + str(SOURCE / 'lucene'),
        '-Dtests.asserts=true', '-Dtests.slow=true', '-Dtests.nightly=false',
        '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
        '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
        '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
        '-Djdk.map.althashing.threshold=0',
        '-Djava.security.egd=file:/dev/./urandom',
        '-cp', cp, 'research.solr22.OriginalJUnit', TEST_CLASS, TEST_METHOD,
    ]
    if fault_plan is not None:
        command.insert(command.index('-cp'), '-Dsolr22.fault.plan=' + str(fault_plan.resolve()))
    started = time.monotonic()
    timed_out = False
    with (out / 'console.log').open('w') as console:
        try:
            result = subprocess.run(command, cwd=SOURCE, stdout=console,
                                    stderr=subprocess.STDOUT, timeout=240,
                                    env=os.environ.copy(), check=False)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
    meta = {'test': TEST_CLASS + '#' + TEST_METHOD,
            'elapsed_seconds': round(time.monotonic() - started, 3),
            'exit_code': exit_code, 'timed_out': timed_out,
            'fault_plan': str(fault_plan) if fault_plan else None,
            'agent': str(HERE / 'solr22-independent-agent.jar'),
            'classpath_contains_graphchecker': 'graphchecker' in cp.lower(),
            'original_source_revision': subprocess.check_output(
                ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()}
    (out / 'run.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--fault-plan', type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.output.resolve(), args.fault_plan))


if __name__ == '__main__':
    main()
