#!/usr/bin/env python3
"""Run unchanged original SOLR-13 JUnit with isolated trace and JaCoCo."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
INDEPENDENT = HERE.parent
sys.path.insert(0, str(INDEPENDENT))
from build import JAVA, SOURCE, TEST_CLASS, TEST_METHOD, classpath  # noqa: E402

JACOCO = Path.home() / '.m2/repository/org/jacoco/org.jacoco.agent/0.8.15/org.jacoco.agent-0.8.15-runtime.jar'
AGENT = HERE / 'solr13stage2-agent.jar'


def run(out: Path, plan: Path | None = None, seed: str = 'D82A1912E3C1791F',
        timeout: int = 1200) -> int:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / 'scratch'
    # An interrupted attempt must not inherit its previous embedded cluster.
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    command = [str(JAVA / 'java'), '-ea', '-Xmx4g',
               '-javaagent:' + str(JACOCO)
               + '=destfile=' + str(out / 'jacoco.exec')
               + ',append=false,dumponexit=true,includes=org.apache.solr.*',
               '-javaagent:' + str(AGENT),
               '-Djava.awt.headless=true', '-Djava.io.tmpdir=' + str(scratch),
               '-DtempDir=' + str(scratch), '-Dtests.seed=' + seed,
               '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
               '-Dcommon.dir=' + str(SOURCE / 'lucene'),
               '-Dtests.asserts=true', '-Dtests.slow=true',
               '-Dtests.nightly=true', '-Dtests.awaitsfix=true',
               '-Dsolr.disableConfigSetsCreateAuthChecks=true',
               '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
               '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
               '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
               '-Djdk.map.althashing.threshold=0',
               '-Djava.security.egd=file:/dev/./urandom',
               '-Dsolr13stage2.trace.file=' + str(out / 'events.jsonl')]
    if plan is not None:
        command.append('-Dsolr13stage2.fault.plan=' + str(plan.resolve()))
    command.extend(['-cp', classpath(), 'research.solr13.OriginalJUnit',
                    TEST_CLASS, TEST_METHOD])
    started = time.monotonic()
    with (out / 'console.log').open('w') as log:
        try:
            result = subprocess.run(command, cwd=SOURCE, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=timeout,
                                    env=os.environ.copy(), check=False)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    meta = {'case_id': 'SOLR-13', 'test': TEST_CLASS + '#' + TEST_METHOD,
            'elapsed_seconds': round(time.monotonic() - started, 3),
            'exit_code': exit_code, 'test_seed': seed,
            'fault_plan': str(plan.resolve()) if plan else None,
            'agent_sha256': hashlib.sha256(AGENT.read_bytes()).hexdigest(),
            'graphchecker_runtime_jars': [entry for entry in classpath().split(':')
                                          if Path(entry).suffix == '.jar' and
                                          'graphchecker' in Path(entry).name.lower()],
            'original_source_revision': subprocess.check_output(
                ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'],
                text=True).strip()}
    temporary = out / 'run.json.tmp'
    temporary.write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    temporary.replace(out / 'run.json')
    print(json.dumps(meta, sort_keys=True), flush=True)
    return exit_code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--seed', default='D82A1912E3C1791F')
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.plan, args.seed, args.timeout))
