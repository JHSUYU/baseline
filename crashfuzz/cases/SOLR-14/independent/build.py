#!/usr/bin/env python3
"""Build a case-local ASM recorder and the unchanged SplitShardTest.java."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
CASE22 = HERE.parents[1] / 'SOLR-22'
JAVA8 = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
SOURCE = HERE / 'solr-pristine'
TEST_JAVA = SOURCE / 'solr/core/src/test/org/apache/solr/cloud/SplitShardTest.java'


def original_classpath() -> str:
    entries = (CASE22 / 'classpath.txt').read_text().strip().split(':')
    case22_classes = str(CASE22 / 'classes')
    case22_resources = str(CASE22 / 'solr-source/solr/core/src/test-files')
    result = []
    for entry in entries:
        if any(x in entry.lower() for x in ('graphchecker', 'unit-test-core', 'causynth')):
            continue
        if entry == case22_classes:
            result.append(str(HERE / 'classes'))
        elif entry == case22_resources:
            result.append(str(SOURCE / 'solr/core/src/test-files'))
        else:
            result.append(entry)
    return ':'.join(result)


def main() -> None:
    classes = HERE / 'classes'
    classes.mkdir(parents=True, exist_ok=True)
    sources = sorted((HERE / 'src').rglob('*.java'))
    cp = original_classpath() + ':' + str(CASE22 / 'v5/lib/jacoco-core.jar')
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', cp, '-d', str(classes),
                    *(str(s) for s in sources), str(TEST_JAVA)], check=True)
    manifest = HERE / 'agent.mf'
    manifest.write_text('Manifest-Version: 1.0\n'
                        'Premain-Class: research.solrsplit.Agent\n\n')
    agent = HERE / 'solrsplit-independent-agent.jar'
    subprocess.run([str(JAVA8 / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(classes), 'research/solrsplit'], check=True)
    target_jar = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist/solr-core-8.11.4.jar')
    meta = {
        'agent_sha256': hashlib.sha256(agent.read_bytes()).hexdigest(),
        'original_test_source_sha256': hashlib.sha256(TEST_JAVA.read_bytes()).hexdigest(),
        'original_test_class_sha256': hashlib.sha256((classes / 'org/apache/solr/cloud/SplitShardTest.class').read_bytes()).hexdigest(),
        'original_solr_core_jar_sha256': hashlib.sha256(target_jar.read_bytes()).hexdigest(),
        'source_revision': subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
        'classpath_contains_graphchecker': 'graphchecker' in original_classpath().lower(),
        'classpath_entries': len(original_classpath().split(':')),
        'sources': {str(s.relative_to(HERE)): hashlib.sha256(s.read_bytes()).hexdigest() for s in sources},
    }
    (HERE / 'build.json').write_text(json.dumps(meta, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
