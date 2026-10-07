#!/usr/bin/env python3
"""Build the case-local ASM recorder from the original Solr/Lucene classpath."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
JAVA8 = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')


def original_classpath() -> str:
    entries = (CASE / 'classpath.txt').read_text().strip().split(':')
    entries = [entry for entry in entries
               if 'graphchecker' not in entry.lower()
               and 'unit-test-core' not in entry.lower()
               and 'causynth' not in entry.lower()]
    original_resources = str(CASE / 'solr-source/solr/core/src/test-files')
    pristine_resources = str(HERE / 'solr-pristine/solr/core/src/test-files')
    return ':'.join(pristine_resources if entry == original_resources else entry
                    for entry in entries)


def build_classpath() -> str:
    return original_classpath() + ':' + str(CASE / 'v5/lib/jacoco-core.jar')


def main() -> None:
    classes = HERE / 'classes'
    classes.mkdir(exist_ok=True)
    sources = sorted(str(path) for path in (HERE / 'src').rglob('*.java'))
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', build_classpath(), '-d', str(classes), *sources], check=True)
    manifest = HERE / 'agent.mf'
    manifest.write_text('Manifest-Version: 1.0\n'
                        'Premain-Class: research.solr22.Agent\n\n')
    agent = HERE / 'solr22-independent-agent.jar'
    subprocess.run([str(JAVA8 / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(classes), '.'], check=True)
    meta = {
        'agent_sha256': hashlib.sha256(agent.read_bytes()).hexdigest(),
        'source_files': {str(Path(path).relative_to(HERE)): hashlib.sha256(Path(path).read_bytes()).hexdigest()
                         for path in sources},
        'classpath_contains_graphchecker': 'graphchecker' in original_classpath().lower(),
        'classpath_entries': len(original_classpath().split(':')),
        'methodology': 'case_local_asm_direct_directory_plus_jacoco',
    }
    (HERE / 'build.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
