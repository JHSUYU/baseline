#!/usr/bin/env python3
"""Pin the node2 original JUnit and release provenance before V2 execution."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LEGACY = HERE.parent
sys.path.insert(0, str(LEGACY))
from build import SOURCE, TEST_BASE, original_classpath  # noqa: E402
from run_v2 import AGENT, RELEASE_CORE  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    hostname = socket.gethostname()
    if not hostname.startswith('node2'):
        raise RuntimeError(f'V2 JUnit requires node2; found {hostname}')
    cp = original_classpath()
    if 'graphchecker' in cp.lower():
        raise RuntimeError('GraphChecker in JUnit classpath')
    missing = [entry for entry in cp.split(':') if not Path(entry).exists()]
    if missing:
        raise RuntimeError(f'missing classpath entries: {missing}')
    original_build = json.loads((LEGACY / 'build.json').read_text())
    agent_build = json.loads((HERE / 'build-v2.json').read_text())
    source = TEST_BASE / 'ForceLeaderTest.java'
    source_key = 'solr/core/src/test/org/apache/solr/cloud/ForceLeaderTest.java'
    if sha(source) != original_build['source_sha256'][source_key]:
        raise RuntimeError('original test source hash mismatch')
    if sha(RELEASE_CORE) != original_build['original_solr_core_jar_sha256']:
        raise RuntimeError('Solr release JAR hash mismatch')
    if sha(AGENT) != agent_build['agent_sha256']:
        raise RuntimeError('V2 agent hash mismatch')
    runner = LEGACY / 'run.py'
    if "'-ea'" not in runner.read_text():
        raise RuntimeError('original JUnit runner lacks -ea')
    revision = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != original_build['source_revision']:
        raise RuntimeError('original Solr source revision mismatch')
    receipt = {
        'hostname': hostname,
        'source_revision': revision,
        'original_test_source_sha256': sha(source),
        'original_test_class_sha256': sha(LEGACY / 'classes/org/apache/solr/cloud/ForceLeaderTest.class'),
        'original_junit_runner_source_sha256': sha(LEGACY / 'src/research/solrforce/OriginalJUnit.java'),
        'original_junit_runner_class_sha256': sha(LEGACY / 'classes/research/solrforce/OriginalJUnit.class'),
        'release_solr_core_jar_sha256': sha(RELEASE_CORE),
        'v2_agent_sha256': sha(AGENT),
        'assertions_enabled_by_runner': True,
        'classpath_contains_graphchecker': False,
        'classpath_entries': len(cp.split(':')),
        'pid': os.getpid(),
    }
    (HERE / 'preflight-v2.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
