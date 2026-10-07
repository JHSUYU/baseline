#!/usr/bin/env python3
"""Build unchanged original JUnit plus isolated actor-aware bytecode agent."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
INDEPENDENT = HERE.parent / 'independent'
SOURCE = INDEPENDENT / 'solr-source'
REVISION = 'e27f44e3d78dfcec230c97e0a1240e3751daeff9'
JAVA8 = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm')
ASM_VERSION = '9.10.1'
DIST = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist')
TEST_REL = ('solr/solrj/src/test/org/apache/solr/client/solrj/impl/'
            'CloudHttp2SolrClientTest.java')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classpath() -> str:
    original = (INDEPENDENT / 'original-classpath.txt').read_text().strip().split(':')
    old = str(INDEPENDENT / 'classes-original')
    if original.count(old) != 1:
        raise RuntimeError('original classpath has no unique original test class directory')
    return ':'.join(str(HERE / 'classes') if entry == old else entry
                    for entry in original)


def asm_jars() -> list[Path]:
    return [ASM / module / ASM_VERSION / f'{module}-{ASM_VERSION}.jar'
            for module in ('asm', 'asm-tree', 'asm-commons', 'asm-util')]


def main() -> None:
    revision = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'],
                                       text=True).strip()
    if revision != REVISION:
        raise RuntimeError(f'original Solr revision changed: {revision}')
    classes = HERE / 'classes'
    classes.mkdir(parents=True, exist_ok=True)
    test = SOURCE / TEST_REL
    helper = INDEPENDENT / 'probe/RunSingleJUnit.java'
    cp = classpath()
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', cp, '-d', str(classes), str(helper), str(test)], check=True)
    coverage_cp = cp + ':' + str(INDEPENDENT / 'lib/jacoco-core.jar')
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', coverage_cp, '-d', str(classes),
                    str(INDEPENDENT / 'probe/CoverageProbes.java'),
                    str(INDEPENDENT / 'probe/CoverageSummary.java')], check=True)
    agent_classes = HERE / 'agent-classes'
    agent_classes.mkdir(parents=True, exist_ok=True)
    src = HERE / 'src/research/solraliasv2'
    sources = [src / name for name in ('Agent.java', 'Probe.java', 'Smoke.java')]
    compile_cp = ':'.join([cp, *(str(path) for path in asm_jars())])
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', compile_cp, '-d', str(agent_classes),
                    *(str(source) for source in sources)], check=True)
    manifest = HERE / 'agent.mf'
    manifest.write_text('Manifest-Version: 1.0\n'
                        'Premain-Class: research.solraliasv2.Agent\n\n')
    agent = HERE / 'solr01-actor-v2-agent.jar'
    subprocess.run([str(JAVA8 / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(agent_classes), 'research/solraliasv2'], check=True)
    receipt = {
        'source_revision': revision,
        'test': 'CloudHttp2SolrClientTest#testAliasHandling',
        'test_source_sha256': sha(test), 'helper_source_sha256': sha(helper),
        'test_class_sha256': sha(classes / 'org/apache/solr/client/solrj/impl/CloudHttp2SolrClientTest.class'),
        'helper_class_sha256': sha(classes / 'baseline/solr01/RunSingleJUnit.class'),
        'agent_sha256': sha(agent),
        'agent_sources_sha256': {p.name: sha(p) for p in sources},
        'original_solrj_sha256': sha(DIST / 'solr-solrj-8.11.4.jar'),
        'original_core_sha256': sha(DIST / 'solr-core-8.11.4.jar'),
        'classpath_entries': len(cp.split(':')),
        'classpath_contains_graphchecker': 'graphchecker' in cp.lower(),
    }
    if receipt['classpath_contains_graphchecker']:
        raise RuntimeError('V2 original classpath contains GraphChecker')
    (HERE / 'build-receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
