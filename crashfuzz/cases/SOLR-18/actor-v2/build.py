#!/usr/bin/env python3
"""Build the unchanged Solr 8.11.4 alias-state JUnit in an isolated case directory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4')
DIST = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4')
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
CLASSES = HERE / 'classes'
CLEAN_CLASSES = HERE / 'clean-classes'
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.6/asm-9.6.jar')
ASM_TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.6/asm-tree-9.6.jar')
ASM_COMMONS = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-commons/9.6/asm-commons-9.6.jar')
JACOCO_CORE = Path('/users/ZhenyuLi/.m2/repository/org/jacoco/org.jacoco.core/0.8.15/org.jacoco.core-0.8.15.jar')
TEST_BASE = SOURCE / 'solr/core/src/test/org/apache/solr/cloud'
TEST_SOURCES = (TEST_BASE / 'AliasIntegrationTest.java',)
TEST_CLASS = 'org.apache.solr.cloud.AliasIntegrationTest'
TEST_METHOD = 'testProperties'


def classpath() -> str:
    entries = (HERE / 'classpath.txt').read_text().strip().split(':')
    assert entries[0] == str(SOURCE / 'solr/core/src/test-files')
    assert entries[1] == str(CLASSES)
    assert not any(any(word in Path(entry).name.lower() for word in
                       ('graphchecker', 'skeleton', 'causynth'))
                   for entry in entries if Path(entry).suffix == '.jar')
    return ':'.join(entries)


def clean_classpath() -> str:
    entries = classpath().split(':')
    entries[1] = str(CLEAN_CLASSES)
    return ':'.join(entries)


def main() -> None:
    CLASSES.mkdir(parents=True, exist_ok=True)
    CLEAN_CLASSES.mkdir(parents=True, exist_ok=True)
    clean = subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
                            '-cp', clean_classpath(), '-d', str(CLEAN_CLASSES),
                            str(HERE / 'src/OriginalJUnit.java'),
                            str(HERE / 'src/Solr18Probe.java'),
                            *map(str, TEST_SOURCES)],
                           text=True, capture_output=True, check=False)
    if clean.returncode:
        raise RuntimeError(clean.stderr)
    cp = classpath()
    sources = [HERE / 'src/OriginalJUnit.java', HERE / 'src/Solr18Probe.java',
               HERE / 'src/PatchSolr18.java', HERE / 'src/CoverageSolr18.java', *TEST_SOURCES]
    run = subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
                          '-cp', cp + ':' + ':'.join(map(str, (ASM, ASM_TREE, ASM_COMMONS, JACOCO_CORE))),
                          '-d', str(CLASSES), *map(str, sources)],
                         text=True, capture_output=True, check=False)
    if run.returncode:
        raise RuntimeError(run.stderr)
    manifest = {
        'test': TEST_CLASS + '#' + TEST_METHOD,
        'source_revision': subprocess.check_output(
            ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
        'source_sha256': {str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in TEST_SOURCES},
        'case_probe_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sources if p not in TEST_SOURCES},
        'graphchecker_runtime_jars': [entry for entry in cp.split(':')
                                      if Path(entry).suffix == '.jar'
                                      and 'graphchecker' in Path(entry).name.lower()],
        'source_resource_path': str(SOURCE / 'solr/core/src/test-files'),
        'classpath_entries': len(cp.split(':')),
        'clean_junit_class_sha256': hashlib.sha256((CLEAN_CLASSES /
            'org/apache/solr/cloud/AliasIntegrationTest.class').read_bytes()).hexdigest(),
        'actor_junit_class_sha256': hashlib.sha256((CLASSES /
            'org/apache/solr/cloud/AliasIntegrationTest.class').read_bytes()).hexdigest(),
        'solr_core_jar_sha256': hashlib.sha256(
            (DIST / 'dist/solr-core-8.11.4.jar').read_bytes()).hexdigest(),
    }
    (HERE / 'build.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    print(json.dumps(manifest, sort_keys=True))


if __name__ == '__main__':
    main()
