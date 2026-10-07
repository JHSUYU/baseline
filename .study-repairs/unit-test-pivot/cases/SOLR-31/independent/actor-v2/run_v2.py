#!/usr/bin/env python3
"""Run the original ForceLeader JUnit with the isolated actor-bound V2 agent."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
LEGACY = HERE.parent
sys.path.insert(0, str(LEGACY))
from build import TEST_BASE, original_classpath  # noqa: E402
from run import run as original_run  # noqa: E402

AGENT = HERE / 'solr31-actor-v2-agent.jar'
RELEASE_CORE = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist/solr-core-8.11.4.jar')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(out: Path, test_seed: str = 'F0993D5343E20BA4',
        fault_plan: Path | None = None) -> int:
    if 'graphchecker' in original_classpath().lower():
        raise RuntimeError('GraphChecker found in original JUnit classpath')
    if "'-ea'" not in (LEGACY / 'run.py').read_text():
        raise RuntimeError('original JUnit runner no longer enables assertions')
    build = json.loads((HERE / 'build-v2.json').read_text())
    if digest(AGENT) != build['agent_sha256']:
        raise RuntimeError('V2 agent changed after build')
    source = TEST_BASE / 'ForceLeaderTest.java'
    test_class = LEGACY / 'classes/org/apache/solr/cloud/ForceLeaderTest.class'
    junit_class = LEGACY / 'classes/research/solrforce/OriginalJUnit.class'
    if not all(path.is_file() for path in (source, test_class, junit_class, RELEASE_CORE)):
        raise RuntimeError('original JUnit source/classes/release JAR absent; run legacy build.py on node2')
    original_build = json.loads((LEGACY / 'build.json').read_text())
    source_key = 'solr/core/src/test/org/apache/solr/cloud/ForceLeaderTest.java'
    if digest(source) != original_build['source_sha256'][source_key]:
        raise RuntimeError('original ForceLeaderTest source changed since released build receipt')
    if digest(RELEASE_CORE) != original_build['original_solr_core_jar_sha256']:
        raise RuntimeError('Solr release core JAR changed since original build receipt')
    exit_code = original_run(out, test_seed=test_seed, agent_path=AGENT,
                             fault_plan=fault_plan)
    receipt = {
        'agent_sha256': digest(AGENT),
        'original_test_source_sha256': digest(source),
        'original_test_class_sha256': digest(test_class),
        'original_junit_runner_class_sha256': digest(junit_class),
        'release_solr_core_jar_sha256': digest(RELEASE_CORE),
        'assertions_enabled': True,
        'classpath_contains_graphchecker': False,
        'test_seed': test_seed,
        'fault_plan': str(fault_plan.resolve()) if fault_plan else None,
        'exit_code': exit_code,
    }
    (out / 'v2-provenance.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    return exit_code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--test-seed', default='F0993D5343E20BA4')
    parser.add_argument('--fault-plan', type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.test_seed, args.fault_plan))
