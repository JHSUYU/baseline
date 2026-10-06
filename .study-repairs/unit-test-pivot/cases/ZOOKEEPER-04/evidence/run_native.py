#!/usr/bin/env python3
"""Run the original ZooKeeper JUnit with case-local output and line probes."""

import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


SOURCE_BUILD = Path('/tmp/zk387-unit-smoke-20261006')
REPORT = SOURCE_BUILD / 'zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml'
RUN_ROOT = Path('/users/ZhenyuLi/zk04-runs')
GC_JAR = Path('/users/ZhenyuLi/GraphChecker-unit-zookeeper/target/GraphChecker-1.0-SNAPSHOT-jar-with-dependencies.jar')
PLAIN_RUNNER_JAR = Path(__file__).resolve().parent / 'runner/original-junit-runner.jar'
AGENT = Path(__file__).resolve().parent / 'agent/audit-agent.jar'
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin/java')


def main():
    run_id = sys.argv[1] if len(sys.argv) > 1 else 'healthy-01'
    method = sys.argv[2] if len(sys.argv) > 2 else 'testRevalidateCount'
    fault_site = sys.argv[3] if len(sys.argv) > 3 else None
    fault_ordinal = int(sys.argv[4]) if len(sys.argv) > 4 else None
    test_class = sys.argv[5] if len(sys.argv) > 5 else 'org.apache.zookeeper.server.ConnectionMetricsTest'
    plain_junit = os.environ.get('ZK04_PLAIN_JUNIT') == '1'
    run = RUN_ROOT / run_id
    run.mkdir(parents=True, exist_ok=True)
    (run / 'temp').mkdir(exist_ok=True)
    report = ET.parse(REPORT).getroot()
    props = report.findall('./properties/property')
    cp = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    cp = '/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar' + os.pathsep + cp
    cp += os.pathsep + str(PLAIN_RUNNER_JAR if plain_junit else GC_JAR)
    if plain_junit and any(token in cp.lower() for token in ('graphchecker', 'skeleton')):
        raise RuntimeError('plain JUnit classpath contains a forbidden legacy dependency')
    cmd = [str(JAVA), '-ea', '-Xmx1g', '-Djava.awt.headless=true',
           '-Dsun.reflect.noInflation=true', '-Djava.io.tmpdir=' + str(run / 'temp'),
           '-Dbuild.test.dir=' + str(run / 'test-data'),
           '-Dtest.junit.threads=1', '-Dzookeeper.junit.threadid=1',
           '-Dcoverage.output=' + str(run / 'coverage.tsv'),
           '-Dzk04.events.output=' + str(run / 'events.tsv'),
           '-javaagent:' + str(AGENT) + '=org/apache/zookeeper/server/ZooKeeperServer,org/apache/zookeeper/ClientCnxnSocketNIO,org/apache/zookeeper/ClientCnxn$SendThread,org/apache/zookeeper/server/quorum/QuorumPeer',
           '-cp', cp,
           'zk04.OriginalJUnitRunner' if plain_junit else 'edu.uva.liftlab.graphchecker.runtime.JUnitMethodRunner',
           test_class, method]
    if not plain_junit:
        cmd[1:1] = ['-Dcausynth.trace.start.paused=true',
                    '-Dcausynth.trace.test=' + test_class + '#' + method]
    if fault_site is not None:
        cmd[1:1] = ['-Dzk04.fault.site=' + fault_site,
                    '-Dzk04.fault.ordinal=' + str(fault_ordinal)]
    if os.environ.get('ZK04_FAULT_PLAN'):
        cmd[1:1] = ['-Dzk04.fault.plan=' + os.environ['ZK04_FAULT_PLAN']]
    env = os.environ.copy()
    if not plain_junit:
        env['CAUSYNTH_TRACE_OUTPUT_DIR'] = str(run / 'trace')
    started = time.monotonic()
    with (run / 'junit.log').open('w') as out:
        try:
            result = subprocess.run(cmd, cwd=SOURCE_BUILD / 'zookeeper-server',
                                    env=env, stdout=out, stderr=subprocess.STDOUT,
                                    timeout=150)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
    elapsed = time.monotonic() - started
    (run / 'run.txt').write_text('exit_code={}\nelapsed_seconds={:.3f}\n'.format(code, elapsed))
    print('{} exit={} elapsed={:.3f}s'.format(run, code, elapsed), flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
