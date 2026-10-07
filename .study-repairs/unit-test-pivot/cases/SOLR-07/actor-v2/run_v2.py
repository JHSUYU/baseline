#!/usr/bin/env python3
"""Run the original AddReplicaTest JUnit in isolation."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from build_v2 import DIST, HERE, JAVA8, SOURCE, TEST_REL, classpath, sha

AGENT = HERE / 'solr07-actor-v2-agent.jar'


def verify_build() -> dict:
    receipt = json.loads((HERE / 'build-receipt.json').read_text())
    revision = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'],
                                       text=True).strip()
    if revision != receipt['source_revision'] or not receipt['assertions_required']:
        raise RuntimeError('original Solr revision or assertion gate changed')
    hashes = {
        SOURCE / TEST_REL: receipt['test_source_sha256'],
        HERE / 'classes/org/apache/solr/cloud/AddReplicaTest.class': receipt['test_class_sha256'],
        HERE / 'classes/baseline/solr07/RunSingleJUnit.class': receipt['helper_class_sha256'],
        AGENT: receipt['agent_sha256'],
        DIST / 'solr-core-8.11.4.jar': receipt['original_core_sha256'],
        DIST / 'solr-solrj-8.11.4.jar': receipt['original_solrj_sha256'],
    }
    for path, digest in hashes.items():
        if sha(path) != digest:
            raise RuntimeError(f'V2 build input changed: {path}')
    if len(classpath().split(':')) != receipt['classpath_entries']:
        raise RuntimeError('V2 classpath changed')
    return receipt


def run(output: Path, plan: Path | None = None, timeout: int = 300,
        instrumented: bool = True) -> int:
    if plan is not None and not instrumented:
        raise ValueError('a fault plan requires the actor agent')
    receipt = verify_build()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / 'scratch'
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    command = [
        str(JAVA8 / 'java'), '-ea', '-Xmx3g', '-Djava.awt.headless=true',
        '-Djava.io.tmpdir=' + str(scratch), '-DtempDir=' + str(scratch),
        '-Dtests.seed=F0993D5343E20BA4',
        '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
        '-Dcommon.dir=' + str(SOURCE / 'lucene'),
        '-Dtests.asserts=true', '-Dtests.slow=true', '-Dtests.nightly=false',
        '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
        '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
        '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
        '-Djdk.map.althashing.threshold=0',
        '-Djava.security.egd=file:/dev/./urandom',
        '-cp', classpath(), 'baseline.solr07.RunSingleJUnit',
        'org.apache.solr.cloud.AddReplicaTest', 'testAddMultipleReplicas',
    ]
    if instrumented:
        command[command.index('-cp'):command.index('-cp')] = [
            '-Dsolr07v2.trace=' + str(output / 'events.jsonl'),
            '-javaagent:' + str(AGENT),
            '-javaagent:' + str(HERE.parent / 'independent/lib/jacoco-agent.jar')
            + '=destfile=' + str(output / 'jacoco.exec')
            + ',append=false,dumponexit=true,includes=org.apache.solr.*',
        ]
    if plan is not None:
        command.insert(command.index('-cp'), '-Dsolr07v2.plan=' + str(plan.resolve()))
    started = time.monotonic()
    with (output / 'junit.log').open('w') as log:
        try:
            result = subprocess.run(command, cwd=SOURCE, stdout=log,
                                    stderr=subprocess.STDOUT, env=os.environ.copy(),
                                    timeout=timeout, check=False)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
            log.write('\nSOLR07_V2_JUNIT_TIMEOUT\n')
    metadata = {
        'test': receipt['test'], 'assertions_enabled': True,
        'source_revision': receipt['source_revision'],
        'agent_sha256': receipt['agent_sha256'] if instrumented else None,
        'instrumented': instrumented,
        'exit_code': exit_code, 'elapsed_seconds': round(time.monotonic() - started, 3),
        'plan': str(plan.resolve()) if plan else None,
    }
    temp = output / 'run.json.tmp'
    temp.write_text(json.dumps(metadata, indent=2, sort_keys=True) + '\n')
    temp.replace(output / 'run.json')
    print(json.dumps(metadata, sort_keys=True), flush=True)
    return exit_code


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--clean', action='store_true')
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.plan, args.timeout,
                         instrumented=not args.clean))
