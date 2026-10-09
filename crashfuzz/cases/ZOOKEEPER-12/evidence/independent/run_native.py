#!/usr/bin/env python3
"""Run the original cluster JUnit with only this case's independent ASM recorder."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
BUILD = Path('/tmp/zk387-unit-smoke-20261006')
SOURCE = Path('/users/ZhenyuLi/zk12-independent-unit')
REPORT = BUILD / 'zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml'
ROOT = Path('/users/ZhenyuLi/zk12-independent-runs')
JAVA = '/usr/lib/jvm/java-8-openjdk-amd64/bin/java'
AGENT = BASE / 'agent/independent-agent.jar'
RUNNER = BASE / 'runner/independent-runner.jar'
ASM = '/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar'
TEST_CLASS = 'org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest'
TEST_METHOD = 'testReadCurrentEpochFromAcceptedEpochTmpFile'
TARGET_METHOD = 'loadDataBase'
GUARD_LINE = 1193
THROW_LINE = 1197
CLASSES = ','.join([
    'org/apache/zookeeper/ClientCnxnSocketNIO',
    'org/apache/zookeeper/ClientCnxn$SendThread',
    'org/apache/zookeeper/server/NIOServerCnxn',
    'org/apache/zookeeper/server/quorum/QuorumPeer',
    'org/apache/zookeeper/common/AtomicFileWritingIdiom',
    'org/apache/zookeeper/common/AtomicFileOutputStream',
])


def run(run_id, plan=(), test_class=TEST_CLASS, method=TEST_METHOD,
        worker_id=1, worker_count=1, timeout=150):
    dest = ROOT / run_id
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'temp').mkdir(exist_ok=True)
    for name in ('coverage.tsv', 'events.tsv'):
        (dest / name).unlink(missing_ok=True)
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    cp = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    cp = cp.replace(str(BUILD), str(SOURCE))
    cp = os.pathsep.join([ASM, cp, str(RUNNER)])
    assert 'graphchecker' not in cp.lower() and 'skeleton' not in cp.lower()
    cmd = [JAVA, '-ea', '-Xmx1g', '-Djava.awt.headless=true',
           '-Dsun.reflect.noInflation=true',
           '-Djava.io.tmpdir=' + str(dest / 'temp'),
           '-Dbuild.test.dir=' + str(dest / 'test-data'),
           '-Dtest.junit.threads=' + str(worker_count),
           '-Dzookeeper.junit.threadid=' + str(worker_id),
           '-Dresearch.coverage.output=' + str(dest / 'coverage.tsv'),
           '-Dresearch.events.output=' + str(dest / 'events.tsv'),
           '-Dresearch.fault.plan=' + '|||'.join(plan),
           '-Dresearch.target.method=' + TARGET_METHOD,
           '-Dresearch.target.guard.line=' + str(GUARD_LINE),
           '-Dresearch.target.throw.line=' + str(THROW_LINE),
           '-javaagent:' + str(AGENT) + '=' + CLASSES,
           '-cp', cp, 'independent.OriginalJUnitRunner', test_class, method]
    started = time.monotonic()
    with (dest / 'junit.log').open('w') as log:
        try:
            proc = subprocess.run(cmd, cwd=SOURCE / 'zookeeper-server',
                                  stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = 124
    result = {
        'run_id': run_id, 'plan': list(plan), 'exit_code': code,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'test_class': test_class, 'method': method,
        'target_method': TARGET_METHOD, 'target_guard_line': GUARD_LINE,
        'target_throw_line': THROW_LINE,
        'port_assignment_worker_id': worker_id,
        'port_assignment_worker_count': worker_count,
        'classpath_sha256': hashlib.sha256(cp.encode()).hexdigest(),
        'classpath_has_graphchecker': False, 'classpath_has_skeleton': False,
        'agent_sha256': hashlib.sha256(AGENT.read_bytes()).hexdigest(),
        'runner_sha256': hashlib.sha256(RUNNER.read_bytes()).hexdigest(),
        'source_worktree': str(SOURCE),
        'original_source_commit': '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae',
    }
    temp = dest / 'run.json.tmp'
    temp.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    os.replace(temp, dest / 'run.json')
    print(json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2:])
