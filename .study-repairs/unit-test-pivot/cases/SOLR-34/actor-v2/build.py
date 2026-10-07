#!/usr/bin/env python3
"""Compile the unchanged original TestCoordinatorRole JUnit and a narrow runner."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parent
CASE22 = HERE.parents[1] / 'SOLR-22'
JAVA8 = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4')
EXPECTED_REVISION = 'e27f44e3d78dfcec230c97e0a1240e3751daeff9'
EXPECTED_TEST_SHA256 = '2e2c6a24b8f2ea37bb1dc4b95842e7974b166e000acf8393ba7d1342bddb59b3'
SOLR_DIST = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4')
TEST_BASE = SOURCE / 'solr/core/src/test/org/apache/solr/search'
TEST_SOURCES = (
    TEST_BASE / 'TestCoordinatorRole.java',
    SOURCE / 'solr/core/src/test/org/apache/solr/common/cloud/ZkStateReaderAccessor.java',
    SOURCE / 'solr/core/src/test/org/apache/solr/schema/MockExchangeRateProvider.java',
    SOURCE / 'solr/core/src/test/org/apache/solr/search/similarities/CustomSimilarityFactory.java',
    SOURCE / 'solr/core/src/test/org/apache/solr/search/similarities/MockConfigurableSimilarity.java',
    SOURCE / 'solr/core/src/test/org/apache/solr/search/function/NvlValueSourceParser.java',
    SOURCE / 'solr/core/src/test/org/apache/solr/search/facet/DebugAgg.java',
)
TEST_CLASS = 'org.apache.solr.search.TestCoordinatorRole'
TEST_METHOD = 'testSimple'


def original_classpath() -> str:
    entries = (CASE22 / 'classpath.txt').read_text().strip().split(':')
    old_classes = str(CASE22 / 'classes')
    old_resources = str(CASE22 / 'solr-source/solr/core/src/test-files')
    result = []
    for entry in entries:
        if any(x in entry.lower() for x in ('graphchecker', 'unit-test-core', 'causynth')):
            continue
        if entry == old_classes:
            result.append(str(HERE / 'classes'))
        elif entry == old_resources:
            result.append(str(SOURCE / 'solr/core/src/test-files'))
        else:
            result.append(entry)
    extras = [SOLR_DIST / 'dist/solr-analysis-extras-8.11.4.jar']
    extras += sorted((SOLR_DIST / 'contrib/analysis-extras/lib').glob('*.jar'))
    extras += sorted((SOLR_DIST / 'contrib/analysis-extras/lucene-libs').glob('*.jar'))
    result += [str(path) for path in extras if path.is_file() and str(path) not in result]
    return ':'.join(result)


def main() -> None:
    revision = subprocess.check_output(
        ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != EXPECTED_REVISION:
        raise RuntimeError(f'wrong Solr checkout: {revision}')
    test_hash = hashlib.sha256(TEST_SOURCES[0].read_bytes()).hexdigest()
    if test_hash != EXPECTED_TEST_SHA256:
        raise RuntimeError(f'original test source changed: {test_hash}')
    classes = HERE / 'classes'
    classes.mkdir(parents=True, exist_ok=True)
    helper = HERE / 'src/research/solrcoordv2/OriginalJUnit.java'
    cp = original_classpath()
    compiled = subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                               '-cp', cp, '-d', str(classes), str(helper),
                               *(str(source) for source in TEST_SOURCES)],
                              capture_output=True, text=True, check=False)
    if compiled.returncode:
        raise RuntimeError(f'original JUnit compilation failed:\n{compiled.stderr}')
    original_jar = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist/solr-core-8.11.4.jar')
    report = {
        'test': TEST_CLASS + '#' + TEST_METHOD,
        'source_revision': revision,
        'source_sha256': {str(source.relative_to(SOURCE)): hashlib.sha256(source.read_bytes()).hexdigest()
                          for source in TEST_SOURCES},
        'original_solr_core_jar_sha256': hashlib.sha256(original_jar.read_bytes()).hexdigest(),
        'classpath_contains_graphchecker': any(
            token in Path(entry).name.lower()
            for entry in cp.split(':')
            for token in ('graphchecker', 'unit-test-core', 'causynth')),
        'classpath_entries': len(cp.split(':')),
    }
    if report['classpath_contains_graphchecker']:
        raise RuntimeError('GraphChecker in V2 classpath')
    (HERE / 'build.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
