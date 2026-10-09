#!/usr/bin/env python3
"""Build the isolated ZK03 quorum-response agent; never start a cluster."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get('ZK03_SOURCE', '/users/ZhenyuLi/zk03-independent-unit'))
BUILD = Path(os.environ.get('ZK03_QUORUM_BUILD', '/users/ZhenyuLi/zk03-quorum-response-build'))
REPORT = Path(os.environ.get('ZK03_REPORT', '/tmp/zk387-unit-smoke-20261006/zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml'))
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
M2 = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm')
ASM = M2 / 'asm/9.4/asm-9.4.jar'
TREE = M2 / 'asm-tree/9.4/asm-tree-9.4.jar'
ANALYSIS = M2 / 'asm-analysis/9.4/asm-analysis-9.4.jar'
REVISION = '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae'
NAMES = [
    'org/apache/zookeeper/test/QuorumTest',
    'org/apache/zookeeper/ClientCnxnSocketNIO',
    'org/apache/zookeeper/server/NIOServerCnxn',
    'org/apache/zookeeper/server/SessionTrackerImpl',
    'org/apache/zookeeper/server/quorum/QuorumPeer',
    'org/apache/zookeeper/server/quorum/LearnerHandler',
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    revision = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REVISION:
        raise RuntimeError('original source revision differs from pinned ZooKeeper 3.8.7')
    for item in (ASM, TREE, ANALYSIS, REPORT):
        if not item.is_file():
            raise FileNotFoundError(item)
    root = HERE.parents[2]  # zk-actor-v2
    sources = [root / 'src/research/zkactor/Probe.java',
               root / 'src/research/zkactor/VerifyTransformed.java']
    sources += sorted((HERE / 'src').rglob('*.java'))
    BUILD.mkdir(parents=True, exist_ok=True)
    classes = BUILD / 'classes'
    classes.mkdir(exist_ok=True)
    subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
                    '-cp', ':'.join(map(str, (ASM, TREE, ANALYSIS))),
                    '-d', str(classes), *map(str, sources)], check=True)
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    original_cp = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    original_cp = original_cp.replace('/tmp/zk387-unit-smoke-20261006', str(SOURCE))
    cp = ':'.join(map(str, (classes, ASM, TREE, ANALYSIS))) + ':' + original_cp
    test_classes = SOURCE / 'zookeeper-server/target/test-classes'
    main_classes = SOURCE / 'zookeeper-server/target/classes'
    class_roots = [test_classes] + [main_classes] * 5
    transformed = BUILD / 'transformed'
    transformed.mkdir(exist_ok=True)
    smoke = subprocess.run([str(JAVA / 'java'), '-cp', cp,
                            'research.zkactor.zk03.QuorumResponseTransformSmoke',
                            *map(str, class_roots), str(transformed)],
                           check=True, text=True, capture_output=True)
    verified = subprocess.run([str(JAVA / 'java'), '-Xverify:all', '-cp', str(transformed) + ':' + cp,
                               'research.zkactor.VerifyTransformed', str(transformed), *NAMES],
                              check=True, text=True, capture_output=True)
    manifest = BUILD / 'manifest.mf'
    manifest.write_text('Premain-Class: research.zkactor.zk03.QuorumResponseAgent\n'
                        'Class-Path: ' + str(ASM) + '\n')
    agent = BUILD / 'zk03-quorum-response-agent.jar'
    subprocess.run([str(JAVA / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(classes), '.'], check=True)
    receipt = {
        'status': 'offline_pass', 'junit_executed': False, 'source_commit': revision,
        'agent': str(agent), 'agent_sha256': sha(agent),
        'original_classes_sha256': {name: sha(base / (name + '.class'))
                                    for name, base in zip(NAMES, class_roots)},
        'original_test_source_sha256': sha(SOURCE / 'zookeeper-server/src/test/java/org/apache/zookeeper/test/QuorumTest.java'),
        'original_target_source_sha256': sha(SOURCE / 'zookeeper-server/src/main/java/org/apache/zookeeper/server/SessionTrackerImpl.java'),
        'agent_sources_sha256': {str(path): sha(path) for path in sources},
        'transform_smoke': smoke.stdout.strip(), 'jvm_verify': verified.stdout.strip(),
        'fault_family': 'leader REVALIDATE response after successful bufferedOutput.flush',
    }
    (BUILD / 'build-receipt.json').write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
