#!/usr/bin/env python3
"""Run the unchanged ReadOnlyModeTest method with case-local probes only."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent
BUILD = Path('/tmp/zk387-unit-smoke-20261006')
SOURCE = Path('/users/ZhenyuLi/zk13-unit')
REPORT = BUILD / 'zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml'
ROOT = Path('/users/ZhenyuLi/zk13-runs')
JAVA = '/usr/lib/jvm/java-8-openjdk-amd64/bin/java'
AGENT = BASE / 'agent/zk13-agent.jar'
RUNNER = BASE / 'runner/zk13-runner.jar'
ASM = '/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar'
CLASSES = ','.join([
    'org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer',
    'org/apache/zookeeper/server/quorum/QuorumPeer',
    'org/apache/zookeeper/ClientCnxnSocketNIO',
    'org/apache/zookeeper/ClientCnxn$SendThread',
    'org/apache/zookeeper/server/NIOServerCnxn',
    'org/apache/zookeeper/server/NIOServerCnxnFactory',
    'org/apache/zookeeper/server/quorum/ReadOnlyRequestProcessor',
    'org/apache/zookeeper/server/quorum/LearnerSessionTracker',
])


def run(run_id, plan=(), timeout=150, worker_id=1, worker_count=1):
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
           '-Dcoverage.output=' + str(dest / 'coverage.tsv'),
           '-Dzk13.events.output=' + str(dest / 'events.tsv'),
           '-Dzk13.fault.plan=' + '|||'.join(plan),
           '-javaagent:' + str(AGENT) + '=' + CLASSES,
           '-cp', cp, 'zk13.OriginalJUnitRunner',
           'org.apache.zookeeper.test.ReadOnlyModeTest', 'testGlobalSessionInRO']
    started = time.monotonic()
    with (dest / 'junit.log').open('w') as log:
        try:
            proc = subprocess.run(cmd, cwd=SOURCE / 'zookeeper-server',
                                  stdout=log, stderr=subprocess.STDOUT,
                                  timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = 124
    result = {'run_id': run_id, 'plan': list(plan), 'exit_code': code,
              'elapsed_seconds': round(time.monotonic() - started, 3),
              'port_assignment_worker_id': worker_id,
              'port_assignment_worker_count': worker_count,
              'classpath_has_graphchecker': False,
              'source_worktree': '/users/ZhenyuLi/zk13-unit',
              'original_source_commit': '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae'}
    (dest / 'run.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    run(sys.argv[1], sys.argv[2:])
