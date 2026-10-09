#!/usr/bin/env python3
"""Build a separate retry-internal Solr/ZooKeeper ASM agent without changing v1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from build import HERE, JAVA8, SOURCE, original_classpath


def main() -> None:
    sources = sorted((HERE / 'native-src').rglob('*.java'))
    assert len(sources) == 2, sources
    classes = HERE / 'native/classes'
    classes.mkdir(parents=True, exist_ok=True)
    cp = original_classpath()
    assert 'graphchecker' not in cp.lower() and 'causynth' not in cp.lower()
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', cp, '-d', str(classes), *(str(s) for s in sources)],
                   check=True)
    manifest = HERE / 'native/agent.mf'
    manifest.write_text('Manifest-Version: 1.0\n'
                        'Premain-Class: research.solrsplitnative.Agent\n\n')
    agent = HERE / 'native/solrsplit-native-agent.jar'
    subprocess.run([str(JAVA8 / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(classes), 'research/solrsplitnative'], check=True)
    source_revision = subprocess.check_output(
        ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    meta = {
        'agent_sha256': hashlib.sha256(agent.read_bytes()).hexdigest(),
        'source_revision': source_revision,
        'instrumentation': 'SolrZkClient retry lambda entry; KeeperException.ConnectionLoss inside ZkCmdExecutor.retryOperation',
        'classpath_contains_graphchecker': False,
        'sources': {str(s.relative_to(HERE)): hashlib.sha256(s.read_bytes()).hexdigest()
                    for s in sources},
    }
    (HERE / 'native/build.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    print(json.dumps(meta, sort_keys=True))


if __name__ == '__main__':
    main()
