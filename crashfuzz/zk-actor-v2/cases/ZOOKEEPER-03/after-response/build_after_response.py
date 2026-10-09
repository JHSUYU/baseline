#!/usr/bin/env python3
"""Compile ZK03 V2 ASM agent and run only offline adapter smoke tests."""

import hashlib
import json
from pathlib import Path
import os
import subprocess
import xml.etree.ElementTree as ET

AFTER = Path(__file__).resolve().parent
CASE = AFTER.parent
V2 = CASE.parents[1]
REVISION = '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae'
SOURCE = Path(os.environ.get('ZK03_SOURCE', '/users/ZhenyuLi/zk03-independent-unit'))
SERVER = SOURCE / 'zookeeper-server/target/classes'
TEST = SOURCE / 'zookeeper-server/target/test-classes'
BUILD = Path(os.environ.get('ZK03_AFTER_BUILD', '/users/ZhenyuLi/zk03-actor-v2-after-response-build'))
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar')
TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.4/asm-tree-9.4.jar')
ANALYSIS = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-analysis/9.4/asm-analysis-9.4.jar')
REPORT = Path(os.environ.get('ZK03_REPORT', '/tmp/zk387-unit-smoke-20261006/zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml'))
SITE = 'ClientCnxnSocketNIO#doIO:119:SocketChannel.write'
SELECTOR = SITE + '@@client:handle:1:session:movedSession@@peer:2:channel:1:op:write@@1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    actual = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != REVISION:
        raise RuntimeError('original source revision changed')
    BUILD.mkdir(parents=True, exist_ok=True)
    classes = BUILD / 'classes'
    classes.mkdir(exist_ok=True)
    sources = sorted((V2 / 'src').rglob('*.java')) + sorted((CASE / 'src').rglob('*.java')) + sorted((AFTER / 'src').rglob('*.java'))
    subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
                    '-cp', ':'.join(map(str, (ASM, TREE, ANALYSIS))), '-d', str(classes),
                    *map(str, sources)], check=True)
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    original_cp = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    original_cp = original_cp.replace('/tmp/zk387-unit-smoke-20261006', str(SOURCE))
    cp = ':'.join(map(str, (classes, ASM, TREE, ANALYSIS))) + ':' + original_cp
    transformed = BUILD / 'transformed'
    names = [CaseName.TEST, 'org/apache/zookeeper/ClientCnxnSocketNIO',
             'org/apache/zookeeper/server/NIOServerCnxn',
             'org/apache/zookeeper/server/SessionTrackerImpl',
             'org/apache/zookeeper/server/quorum/QuorumPeer']
    transform = subprocess.run([str(JAVA / 'java'), '-cp', cp,
                                'research.zkactor.zk03.AfterResponseTransformSmoke', str(TEST), str(SERVER),
                                str(SERVER), str(SERVER), str(SERVER), str(transformed)],
                               check=True, text=True, capture_output=True)
    verified = subprocess.run([str(JAVA / 'java'), '-Xverify:all', '-cp', str(transformed) + ':' + cp,
                               'research.zkactor.VerifyTransformed', str(transformed), *names],
                              check=True, text=True, capture_output=True)
    smoke = subprocess.run([str(JAVA / 'java'), '-Dzk.actor.plan=' + SELECTOR,
                            '-cp', cp, 'research.zkactor.zk03.OfflineCaseSmoke',
                            str(BUILD), str(BUILD / 'offline-events.tsv')],
                           check=True, text=True, capture_output=True)
    manifest = BUILD / 'manifest.mf'
    manifest.write_text('Premain-Class: research.zkactor.zk03.AfterResponseAgent\n'
                        'Class-Path: ' + str(ASM) + '\n')
    agent = BUILD / 'zk03-after-response-agent.jar'
    subprocess.run([str(JAVA / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(classes), '.'], check=True)
    receipt = {
        'status': 'offline_pass', 'agent': str(agent), 'agent_sha256': digest(agent),
        'source_commit': actual,
        'original_test_class_sha256': digest(TEST / (CaseName.TEST + '.class')),
        'original_classes_sha256': {
            name: digest((TEST if name == CaseName.TEST else SERVER) / (name + '.class'))
            for name in names},
        'original_test_source_sha256': digest(SOURCE / 'zookeeper-server/src/test/java'
                                              / (CaseName.TEST + '.java')),
        'original_target_source_sha256': digest(SOURCE / 'zookeeper-server/src/main/java'
                                                / 'org/apache/zookeeper/server/SessionTrackerImpl.java'),
        'agent_sources_sha256': {str(path): digest(path) for path in sources},
        'transform_smoke': transform.stdout.strip(), 'jvm_verify': verified.stdout.strip(),
        'two_actor_smoke': smoke.stdout.strip(),
        'junit_executed': False, 'experiment': 'post-response-stage-two',
    }
    (BUILD / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, sort_keys=True))


class CaseName:
    TEST = 'org/apache/zookeeper/test/QuorumTest'


if __name__ == '__main__':
    main()
