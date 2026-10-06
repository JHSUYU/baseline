#!/usr/bin/env python3
"""Run the unchanged CollectionReloadTest method in its embedded cluster."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from build import CASE22, HERE, JAVA8, SOURCE, TEST_CLASS, TEST_METHOD, original_classpath


def run(out: Path, test_seed: str = 'D82A1912E3C1791F',
        agent_path: Path | None = None, fault_plan: Path | None = None) -> int:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / 'scratch'
    scratch.mkdir(exist_ok=True)
    cp = original_classpath()
    command = [
        str(JAVA8 / 'java'), '-ea', '-Xmx4g',
        '-javaagent:' + str(CASE22 / 'v5/lib/jacoco-agent.jar')
        + '=destfile=' + str(out / 'jacoco.exec')
        + ',append=false,dumponexit=true,includes=org.apache.solr.*:org.apache.lucene.*',
        '-Djava.awt.headless=true', '-Djava.io.tmpdir=' + str(scratch),
        '-DtempDir=' + str(scratch), '-Dtests.seed=' + test_seed,
        '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
        '-Dcommon.dir=' + str(SOURCE / 'lucene'),
        '-Dtests.asserts=true', '-Dtests.slow=true', '-Dtests.nightly=true',
        '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
        '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
        '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
        '-Djdk.map.althashing.threshold=0',
        '-Djava.security.egd=file:/dev/./urandom',
        '-cp', cp, 'research.solrreload.OriginalJUnit', TEST_CLASS, TEST_METHOD,
    ]
    if agent_path is not None:
        agent_path = agent_path.resolve()
        command.insert(command.index('-cp'),
                       '-Dsolrreload.trace.file=' + str(out / 'events.jsonl'))
        command.insert(command.index('-cp'), '-javaagent:' + str(agent_path))
    if fault_plan is not None:
        if agent_path is None:
            raise ValueError('fault plan requires the case-local ASM recorder')
        command.insert(command.index('-cp'),
                       '-Dsolrreload.fault.plan=' + str(fault_plan.resolve()))
    started = time.monotonic()
    with (out / 'console.log').open('w') as console:
        try:
            result = subprocess.run(command, cwd=SOURCE, stdout=console,
                                    stderr=subprocess.STDOUT, timeout=1200,
                                    env=os.environ.copy(), check=False)
            exit_code = result.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            exit_code = 124
            timed_out = True
    meta = {
        'test': TEST_CLASS + '#' + TEST_METHOD,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'exit_code': exit_code,
        'timed_out': timed_out,
        'test_seed': test_seed,
        'agent_sha256': hashlib.sha256(agent_path.read_bytes()).hexdigest()
                         if agent_path is not None else None,
        'fault_plan': str(fault_plan.resolve()) if fault_plan else None,
        'classpath_contains_graphchecker': 'graphchecker' in cp.lower(),
        'original_source_revision': subprocess.check_output(
            ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
    }
    (out / 'run.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    print(json.dumps(meta, sort_keys=True))
    return exit_code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--test-seed', default='D82A1912E3C1791F')
    parser.add_argument('--agent', type=Path)
    parser.add_argument('--fault-plan', type=Path)
    arguments = parser.parse_args()
    raise SystemExit(run(arguments.output, arguments.test_seed,
                         arguments.agent, arguments.fault_plan))
