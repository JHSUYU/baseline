#!/usr/bin/env python3
"""Build unchanged ZooKeeper 3.8.7 class hooks and run offline identity/ASM tests."""

import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

CASE = Path(__file__).resolve().parent
V2 = CASE.parents[1]
SOURCE = Path('/users/ZhenyuLi/zk01-independent-unit')
SERVER = SOURCE / 'zookeeper-server/target/classes'
TEST = SOURCE / 'zookeeper-server/target/test-classes'
BUILD = Path('/users/ZhenyuLi/zk1112-actor-v2-build')
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
ASM_ROOT = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm')
ASM = [ASM_ROOT / module / '9.4' / f'{module}-9.4.jar'
       for module in ('asm', 'asm-tree', 'asm-analysis')]
REPORT = Path('/tmp/zk387-unit-smoke-20261006/zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml')
TEST_NAME = 'org/apache/zookeeper/server/quorum/CurrentEpochWriteFailureTest'
PEER_NAME = 'org/apache/zookeeper/server/quorum/QuorumPeer'
ATOMIC_NAME = 'org/apache/zookeeper/common/AtomicFileOutputStream'
REVISION = '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae'
AGENT = BUILD / 'zk1112-actor-v2-agent.jar'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def original_classpath():
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    cp = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    cp = cp.replace('/tmp/zk387-unit-smoke-20261006', str(SOURCE))
    if 'graphchecker' in cp.lower() or 'skeleton' in cp.lower():
        raise RuntimeError('non-original classpath')
    return cp


def main():
    revision = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'],
                                       text=True).strip()
    if revision != REVISION:
        raise RuntimeError(f'wrong original ZooKeeper revision {revision}')
    if any(not jar.is_file() for jar in ASM):
        raise RuntimeError('ASM 9.4 dependency missing')
    BUILD.mkdir(parents=True, exist_ok=True)
    classes = BUILD / 'classes'
    classes.mkdir(exist_ok=True)
    sources = sorted((V2 / 'src').rglob('*.java')) + sorted((CASE / 'src').rglob('*.java'))
    subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
                    '-cp', ':'.join(map(str, ASM)), '-d', str(classes),
                    *map(str, sources)], check=True)
    cp = ':'.join(map(str, (classes, *ASM))) + ':' + original_classpath()
    transformed = BUILD / 'transformed'
    transform = subprocess.run([str(JAVA / 'java'), '-cp', cp,
                                'research.zkactor.zk1112.TransformSmoke', str(TEST),
                                str(SERVER), str(SERVER), str(transformed)],
                               check=True, text=True, capture_output=True)
    names = [TEST_NAME, PEER_NAME, ATOMIC_NAME]
    verified = subprocess.run([str(JAVA / 'java'), '-Xverify:all', '-cp',
                               str(transformed) + ':' + cp,
                               'research.zkactor.VerifyTransformed', str(transformed), *names],
                              check=True, text=True, capture_output=True)
    site = 'QuorumPeer#readLongFromFile:2186:FileReader'
    selector = site + '@@peer:0@@file:currentEpoch:op:read@@1'
    identity = subprocess.run([str(JAVA / 'java'), '-Dzk.actor.plan=' + selector,
                               '-cp', cp, 'research.zkactor.zk1112.OfflineCaseSmoke',
                               str(BUILD), str(BUILD / 'offline-events.tsv')],
                              check=True, text=True, capture_output=True)
    manifest = BUILD / 'manifest.mf'
    manifest.write_text('Premain-Class: research.zkactor.zk1112.CaseAgent\n'
                        'Class-Path: ' + str(ASM[0]) + '\n')
    subprocess.run([str(JAVA / 'jar'), 'cfm', str(AGENT), str(manifest),
                    '-C', str(classes), '.'], check=True)
    receipt = {
        'status': 'offline_pass', 'junit_executed': False, 'source_commit': revision,
        'agent': str(AGENT), 'agent_sha256': sha(AGENT),
        'agent_sources_sha256': {str(path): sha(path) for path in sources},
        'original_test_class_sha256': sha(TEST / (TEST_NAME + '.class')),
        'original_peer_class_sha256': sha(SERVER / (PEER_NAME + '.class')),
        'original_atomic_class_sha256': sha(SERVER / (ATOMIC_NAME + '.class')),
        'original_test_source_sha256': sha(SOURCE / 'zookeeper-server/src/test/java' / (TEST_NAME + '.java')),
        'original_peer_source_sha256': sha(SOURCE / 'zookeeper-server/src/main/java' / (PEER_NAME + '.java')),
        'original_atomic_source_sha256': sha(SOURCE / 'zookeeper-server/src/main/java' / (ATOMIC_NAME + '.java')),
        'transform_smoke': transform.stdout.strip(), 'jvm_verify': verified.stdout.strip(),
        'wrong_peer_file_smoke': identity.stdout.strip(),
    }
    (BUILD / 'build-receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
