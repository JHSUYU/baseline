#!/usr/bin/env python3
"""Compile original AddReplicaTest and isolated Solr-07 ASM agent."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent / 'independent'
SOURCE = PARENT / 'solr-source'
DIST = Path('/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist')
JAVA8 = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm')
REVISION = 'e27f44e3d78dfcec230c97e0a1240e3751daeff9'
TEST_REL = 'solr/core/src/test/org/apache/solr/cloud/AddReplicaTest.java'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def asm_jars() -> list[Path]:
    return [ASM / module / '9.10.1' / f'{module}-9.10.1.jar'
            for module in ('asm', 'asm-tree', 'asm-commons', 'asm-util')]


def classpath() -> str:
    entries = (PARENT / 'original-classpath.txt').read_text().strip().split(':')
    old = str(PARENT / 'classes-original')
    if entries.count(old) != 1:
        raise RuntimeError('original classpath lacks one test class directory')
    return ':'.join(str(HERE / 'classes') if entry == old else entry for entry in entries)


def main() -> None:
    revision = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'],
                                       text=True).strip()
    if revision != REVISION:
        raise RuntimeError(f'wrong Solr revision {revision}')
    classes = HERE / 'classes'
    classes.mkdir(parents=True, exist_ok=True)
    test = SOURCE / TEST_REL
    helper = PARENT / 'probe/RunSingleJUnit.java'
    cp = classpath()
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8', '-cp', cp,
                    '-d', str(classes), str(helper), str(test)], check=True)
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', cp + ':' + str(PARENT / 'lib/jacoco-core.jar'),
                    '-d', str(classes), str(PARENT / 'probe/CoverageProbes.java'),
                    str(PARENT / 'probe/CoverageSummary.java')], check=True)
    src = HERE / 'src/research/solraddv2'
    sources = [src / name for name in ('Agent.java', 'Probe.java', 'Smoke.java')]
    agent_classes = HERE / 'agent-classes'
    agent_classes.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(JAVA8 / 'javac'), '-source', '8', '-target', '8',
                    '-cp', ':'.join((cp, *(str(p) for p in asm_jars()))),
                    '-d', str(agent_classes), *(str(p) for p in sources)], check=True)
    manifest = HERE / 'agent.mf'
    manifest.write_text('Manifest-Version: 1.0\n'
                        'Premain-Class: research.solraddv2.Agent\n\n')
    agent = HERE / 'solr07-actor-v2-agent.jar'
    subprocess.run([str(JAVA8 / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(agent_classes), 'research/solraddv2'], check=True)
    receipt = {
        'test': 'AddReplicaTest#testAddMultipleReplicas', 'source_revision': revision,
        'test_source_sha256': sha(test), 'helper_source_sha256': sha(helper),
        'test_class_sha256': sha(classes / 'org/apache/solr/cloud/AddReplicaTest.class'),
        'helper_class_sha256': sha(classes / 'baseline/solr07/RunSingleJUnit.class'),
        'agent_sha256': sha(agent),
        'agent_sources_sha256': {p.name: sha(p) for p in sources},
        'original_core_sha256': sha(DIST / 'solr-core-8.11.4.jar'),
        'original_solrj_sha256': sha(DIST / 'solr-solrj-8.11.4.jar'),
        'classpath_entries': len(cp.split(':')),
        'classpath_contains_graphchecker': 'graphchecker' in cp.lower(),
        'assertions_required': True,
    }
    if receipt['classpath_contains_graphchecker']:
        raise RuntimeError('V2 classpath contains GraphChecker')
    (HERE / 'build-receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
