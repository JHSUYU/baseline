#!/usr/bin/env python3
"""Build the case-local ASM target/I/O recorder from source."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from build import HERE, JAVA8, SOURCE, original_classpath


def main() -> None:
    sources = [HERE / 'src/research/solrsubshard/Agent.java',
               HERE / 'src/research/solrsubshard/Probe.java']
    classes = HERE / 'agent-classes'
    classes.mkdir(exist_ok=True)
    cp = original_classpath()
    compiled = subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                               '-cp', cp, '-d', str(classes),
                               *(str(source) for source in sources)],
                              capture_output=True, text=True, check=False)
    if compiled.returncode:
        raise RuntimeError(f'ASM recorder compilation failed:\n{compiled.stderr}')
    manifest = HERE / 'agent.mf'
    manifest.write_text('Manifest-Version: 1.0\n'
                        'Premain-Class: research.solrsubshard.Agent\n\n')
    agent = HERE / 'solrsubshard-independent-agent.jar'
    subprocess.run([str(JAVA8 / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(classes), 'research/solrsubshard'], check=True)
    meta = {
        'agent_sha256': hashlib.sha256(agent.read_bytes()).hexdigest(),
        'source_revision': subprocess.check_output(
            ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
        'source_sha256': {str(source.relative_to(HERE)): hashlib.sha256(source.read_bytes()).hexdigest()
                          for source in sources},
        'classpath_contains_graphchecker': 'graphchecker' in cp.lower(),
    }
    (HERE / 'agent-build.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')
    print(json.dumps(meta, sort_keys=True))


if __name__ == '__main__':
    main()
