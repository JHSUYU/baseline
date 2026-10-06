#!/usr/bin/env python3
"""Run the original SplitShardTest.doTest under independent probes and JaCoCo."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from build import CASE22, HERE, JAVA8, SOURCE, original_classpath


TEST_CLASS = 'org.apache.solr.cloud.SplitShardTest'
TEST_METHOD = 'doTest'


def run(out: Path, fault_plan: Path | None = None, nightly: bool = False,
        test_seed: str = 'F0993D5343E20BA4',
        agent_path: Path | None = None) -> int:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / 'scratch'
    scratch.mkdir(exist_ok=True)
    cp = original_classpath()
    agent = (agent_path or HERE / 'solrsplit-independent-agent.jar').resolve()
    command = [
        str(JAVA8 / 'java'), '-ea', '-Xmx3g',
        '-javaagent:' + str(CASE22 / 'v5/lib/jacoco-agent.jar')
        + '=destfile=' + str(out / 'jacoco.exec')
        + ',append=false,dumponexit=true,includes=org.apache.solr.*:org.apache.lucene.*',
        '-javaagent:' + str(agent),
        '-Dsolrsplit.trace.file=' + str(out / 'events.jsonl'),
        '-Djava.awt.headless=true',
        '-Djava.io.tmpdir=' + str(scratch),
        '-DtempDir=' + str(scratch),
        '-Dtests.seed=' + test_seed,
        '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
        '-Dcommon.dir=' + str(SOURCE / 'lucene'),
        '-Dtests.asserts=true', '-Dtests.slow=true',
        '-Dtests.nightly=' + str(nightly).lower(),
        '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
        '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
        '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
        '-Djdk.map.althashing.threshold=0',
        '-Djava.security.egd=file:/dev/./urandom',
        '-cp', cp, 'research.solrsplit.OriginalJUnit', TEST_CLASS, TEST_METHOD,
    ]
    if fault_plan is not None:
        command.insert(command.index('-cp'), '-Dsolrsplit.fault.plan=' + str(fault_plan.resolve()))
    started = time.monotonic()
    timed_out = False
    with (out / 'console.log').open('w') as console:
        try:
            result = subprocess.run(command, cwd=SOURCE, stdout=console,
                                    stderr=subprocess.STDOUT, timeout=720,
                                    env=os.environ.copy(), check=False)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
    meta = {
        'test': TEST_CLASS + '#' + TEST_METHOD,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'exit_code': exit_code,
        'timed_out': timed_out,
        'fault_plan': str(fault_plan.resolve()) if fault_plan else None,
        'nightly': nightly,
        'test_seed': test_seed,
        'agent': str(agent),
        'agent_sha256': hashlib.sha256(agent.read_bytes()).hexdigest(),
        'classpath_contains_graphchecker': 'graphchecker' in cp.lower(),
        'original_source_revision': subprocess.check_output(
            ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
    }
    (out / 'run.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--fault-plan', type=Path)
    parser.add_argument('--agent', type=Path)
    parser.add_argument('--test-seed', default='F0993D5343E20BA4')
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.fault_plan, test_seed=args.test_seed,
                         agent_path=args.agent))


if __name__ == '__main__':
    main()
