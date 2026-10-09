#!/usr/bin/env python3
"""Build the unchanged Solr 8.11.4 alias JUnit in an isolated case directory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
CASES = HERE.parents[1]
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4')
DIST = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4')
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
CLASSES = HERE / 'classes'
TEST_BASE = SOURCE / 'solr/core/src/test/org/apache/solr/update/processor'
TEST_SOURCES = (TEST_BASE / 'RoutedAliasUpdateProcessorTest.java',
                TEST_BASE / 'TimeRoutedAliasUpdateProcessorTest.java',
                TEST_BASE / 'TrackingUpdateProcessorFactory.java')
TEST_CLASS = 'org.apache.solr.update.processor.TimeRoutedAliasUpdateProcessorTest'
TEST_METHOD = 'testPreemptiveCreation'


def classpath() -> str:
    old = CASES / 'SOLR-22'
    entries = (old / 'classpath.txt').read_text().strip().split(':')
    result = []
    for entry in entries:
        if any(word in entry.lower() for word in ('graphchecker', 'unit-test-core', 'causynth')):
            continue
        if entry == str(old / 'classes'):
            result.append(str(CLASSES))
        elif entry == str(old / 'solr-source/solr/core/src/test-files'):
            result.append(str(SOURCE / 'solr/core/src/test-files'))
        else:
            result.append(entry)
    extra = [DIST / 'dist/solr-analysis-extras-8.11.4.jar']
    extra += sorted((DIST / 'contrib/analysis-extras/lib').glob('*.jar'))
    extra += sorted((DIST / 'contrib/analysis-extras/lucene-libs').glob('*.jar'))
    result += [str(path) for path in extra if path.is_file() and str(path) not in result]
    return ':'.join(result)


def main() -> None:
    CLASSES.mkdir(parents=True, exist_ok=True)
    cp = classpath()
    sources = [HERE / 'src/OriginalJUnit.java', *TEST_SOURCES]
    run = subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
                          '-cp', cp, '-d', str(CLASSES), *map(str, sources)],
                         text=True, capture_output=True, check=False)
    if run.returncode:
        raise RuntimeError(run.stderr)
    manifest = {
        'test': TEST_CLASS + '#' + TEST_METHOD,
        'source_revision': subprocess.check_output(
            ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
        'source_sha256': {str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in TEST_SOURCES},
        'graphchecker_runtime_jars': [entry for entry in cp.split(':')
                                      if Path(entry).suffix == '.jar'
                                      and 'graphchecker' in Path(entry).name.lower()],
        'source_resource_path': str(SOURCE / 'solr/core/src/test-files'),
        'classpath_entries': len(cp.split(':')),
        'solr_core_jar_sha256': hashlib.sha256(
            (DIST / 'dist/solr-core-8.11.4.jar').read_bytes()).hexdigest(),
    }
    (HERE / 'build.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps(manifest, sort_keys=True))


if __name__ == '__main__':
    main()
