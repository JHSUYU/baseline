#!/usr/bin/env python3
"""Run the original Solr 8.11.4 embedded cluster JUnit without fault hooks."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from build import HERE, JAVA, SOURCE, TEST_CLASS, TEST_METHOD, classpath


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', default='D82A1912E3C1791F')
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    scratch = out / 'scratch'
    scratch.mkdir(exist_ok=True)
    cmd = [str(JAVA / 'java'), '-ea', '-Xmx4g',
           '-Djava.awt.headless=true', '-Djava.io.tmpdir=' + str(scratch),
           '-DtempDir=' + str(scratch), '-Dtests.seed=' + args.seed,
           '-Dtests.src.home=' + str(SOURCE / 'solr/core'),
           '-Dcommon.dir=' + str(SOURCE / 'lucene'),
           '-Dtests.asserts=true', '-Dtests.slow=true', '-Dtests.nightly=true',
           '-Dtests.timeoutSuite=86400000', '-Dtests.timeout=86400000',
           '-Djetty.testMode=1', '-Djetty.insecurerandom=1',
           '-Dsolr.directoryFactory=org.apache.solr.core.MockDirectoryFactory',
           '-Djdk.map.althashing.threshold=0',
           '-Djava.security.egd=file:/dev/./urandom',
           '-cp', classpath(), 'research.solr18.OriginalJUnit',
           TEST_CLASS, TEST_METHOD]
    start = time.monotonic()
    with (out / 'console.log').open('w') as log:
        try:
            result = subprocess.run(cmd, cwd=SOURCE, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=args.timeout,
                                    env=os.environ.copy(), check=False)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    manifest = {'test': TEST_CLASS + '#' + TEST_METHOD,
                'elapsed_seconds': round(time.monotonic() - start, 3),
                'exit_code': exit_code, 'seed': args.seed,
                'instrumentation': 'none',
                'original_junit': True}
    (out / 'run.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps(manifest, sort_keys=True))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
