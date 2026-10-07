#!/usr/bin/env python3
"""Compile ZK02 V2 ASM agent and run only offline adapter smoke tests."""

import hashlib
import json
from pathlib import Path
import subprocess

CASE = Path(__file__).resolve().parent
V2 = CASE.parents[1]
SOURCE = Path('/users/ZhenyuLi/zk02-independent-unit')
SERVER = SOURCE / 'zookeeper-server/target/classes'
TEST = SOURCE / 'zookeeper-server/target/test-classes'
BUILD = Path('/users/ZhenyuLi/zk02-actor-v2-build')
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin')
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar')
TREE = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-tree/9.4/asm-tree-9.4.jar')
ANALYSIS = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm-analysis/9.4/asm-analysis-9.4.jar')
SITE = 'ClientCnxnSocketNIO#doIO:119:SocketChannel.write'
SELECTOR = SITE + '@@client:handle:1:session:movedSession@@peer:2:channel:1:op:write@@1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    classes = BUILD / 'classes'
    classes.mkdir(exist_ok=True)
    sources = sorted((V2 / 'src').rglob('*.java')) + sorted((CASE / 'src').rglob('*.java'))
    subprocess.run([str(JAVA / 'javac'), '-source', '8', '-target', '8',
                    '-cp', ':'.join(map(str, (ASM, TREE, ANALYSIS))), '-d', str(classes),
                    *map(str, sources)], check=True)
    cp = ':'.join(map(str, (classes, ASM, TREE, ANALYSIS)))
    transform = subprocess.run([str(JAVA / 'java'), '-cp', cp,
                                'research.zkactor.zk02.TransformSmoke', str(TEST), str(SERVER),
                                str(SERVER), str(SERVER), str(SERVER)],
                               check=True, text=True, capture_output=True)
    smoke = subprocess.run([str(JAVA / 'java'), '-Dzk.actor.plan=' + SELECTOR,
                            '-cp', cp, 'research.zkactor.zk02.OfflineCaseSmoke',
                            str(BUILD), str(BUILD / 'offline-events.tsv')],
                           check=True, text=True, capture_output=True)
    manifest = BUILD / 'manifest.mf'
    manifest.write_text('Premain-Class: research.zkactor.zk02.CaseAgent\n'
                        'Class-Path: ' + str(ASM) + '\n')
    agent = BUILD / 'zk02-actor-v2-agent.jar'
    subprocess.run([str(JAVA / 'jar'), 'cfm', str(agent), str(manifest),
                    '-C', str(classes), '.'], check=True)
    receipt = {
        'status': 'offline_pass', 'agent': str(agent), 'agent_sha256': digest(agent),
        'source_commit': '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae',
        'original_test_class_sha256': digest(TEST / (CaseName.TEST + '.class')),
        'transform_smoke': transform.stdout.strip(), 'two_actor_smoke': smoke.stdout.strip(),
        'junit_executed': False,
    }
    (BUILD / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, sort_keys=True))


class CaseName:
    TEST = 'org/apache/zookeeper/test/QuorumTest'


if __name__ == '__main__':
    main()
