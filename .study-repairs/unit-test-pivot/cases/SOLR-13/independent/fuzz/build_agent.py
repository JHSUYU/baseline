#!/usr/bin/env python3
"""Build the SOLR-13 case-local ASM recorder without modifying Solr source."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
INDEPENDENT = HERE.parent
sys.path.insert(0, str(INDEPENDENT))
from build import JAVA, SOURCE, classpath  # noqa: E402


def main() -> None:
    sources = [HERE / 'src/research/solr13/Agent.java',
               HERE / 'src/research/solr13/Probe.java']
    classes = HERE / 'agent-classes'
    classes.mkdir(exist_ok=True)
    command = [str(JAVA / 'javac'), '-source', '8', '-target', '8',
               '-cp', classpath(), '-d', str(classes),
               *(str(p) for p in sources)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    manifest = HERE / 'agent.mf'
    manifest.write_text('Manifest-Version: 1.0\n'
                        'Premain-Class: research.solr13.Agent\n\n')
    jar = HERE / 'solr13-agent.jar'
    subprocess.run([str(JAVA / 'jar'), 'cfm', str(jar), str(manifest),
                    '-C', str(classes), 'research/solr13'], check=True)
    report = {'source_revision': subprocess.check_output(
        ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
        'agent_sha256': hashlib.sha256(jar.read_bytes()).hexdigest(),
        'source_sha256': {str(p.relative_to(HERE)):
                          hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sources},
        'graphchecker_runtime_jars': [entry for entry in classpath().split(':')
                                      if Path(entry).suffix == '.jar' and
                                      'graphchecker' in Path(entry).name.lower()]}
    (HERE / 'agent-build.json').write_text(json.dumps(report, indent=2,
                                                     sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
