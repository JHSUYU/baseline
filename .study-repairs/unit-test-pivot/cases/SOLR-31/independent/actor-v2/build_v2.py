#!/usr/bin/env python3
"""Build the isolated SOLR-31 actor-bound ASM adapter against release jars."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LEGACY = HERE.parent
sys.path.insert(0, str(LEGACY))
from build import JAVA8, original_classpath  # noqa: E402


def main() -> None:
    cp = original_classpath()
    assert 'graphchecker' not in cp.lower()
    sources = sorted((HERE / 'src/research/solrforcev2').glob('*.java'))
    classes = HERE / 'classes'
    classes.mkdir(exist_ok=True)
    command = [str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
               '-cp', cp, '-d', str(classes), *(str(path) for path in sources)]
    compiled = subprocess.run(command, capture_output=True, text=True)
    if compiled.returncode:
        raise RuntimeError(compiled.stderr)
    manifest = HERE / 'agent.mf'
    manifest.write_text('Manifest-Version: 1.0\n'
                        'Premain-Class: research.solrforcev2.Agent\n\n')
    agent = HERE / 'solr31-actor-v2-agent.jar'
    subprocess.run([str(JAVA8 / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(classes), 'research/solrforcev2'], check=True)
    receipt = {
        'agent_sha256': hashlib.sha256(agent.read_bytes()).hexdigest(),
        'sources_sha256': {str(path.relative_to(HERE)): hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in sources},
        'classpath_contains_graphchecker': False,
        'java_assertions_required': True,
        'actor_binding': 'target handler CoreContainer ZkController SolrZkClient identity and node name',
    }
    (HERE / 'build-v2.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
