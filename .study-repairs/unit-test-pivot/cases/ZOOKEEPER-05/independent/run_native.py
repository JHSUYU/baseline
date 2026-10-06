#!/usr/bin/env python3
"""Run the unchanged embedded-cluster JUnit using only case-local ASM and JaCoCo agents."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


HOME = Path(os.environ.get('ZK05_HOME', '/users/ZhenyuLi/zk05-independent'))
SOURCE = HOME / 'source'
TOOLS = HOME / 'tools'
RUNS = HOME / 'runs'
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin/java')
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar')
JACOCO_AGENT = TOOLS / 'jacoco-agent.jar'
JACOCO_CORE = TOOLS / 'jacoco-core.jar'
REPORT = SOURCE / 'zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml'
SOURCE_FROM = '/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/ZOOKEEPER-05/source'
CLASSES = ','.join('org/apache/zookeeper/server/quorum/' + value for value in
                   ('Follower', 'Learner', 'LearnerHandler', 'Leader', 'QuorumPeer',
                    'QuorumCnxManager'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    run = RUNS / args.run_id
    run.mkdir(exist_ok=False)
    (run / 'temp').mkdir()
    report = ET.parse(REPORT).getroot()
    cp = next(prop.get('value') for prop in report.findall('./properties/property')
              if prop.get('name') == 'java.class.path')
    cp = cp.replace(SOURCE_FROM, str(SOURCE))
    cp = os.pathsep.join((str(ASM), cp, str(TOOLS / 'runner/zk05-runner.jar')))
    if 'graphchecker' in cp.lower() or 'skeleton' in cp.lower():
        raise RuntimeError('forbidden legacy instrumentor in classpath')
    plan = json.loads(args.plan.read_text()) if args.plan else []
    if not isinstance(plan, list) or any(not isinstance(item, str) for item in plan):
        raise ValueError('plan must be a JSON list of exact selector strings')
    cmd = [str(JAVA), '-ea', '-Xmx1g', '-Djava.awt.headless=true',
           '-Dsun.reflect.noInflation=true', '-Djava.io.tmpdir=' + str(run / 'temp'),
           '-Dbuild.test.dir=' + str(run / 'test-data'),
           '-Dtest.junit.threads=24', '-Dzookeeper.junit.threadid=22',
           '-Dzk05.events.output=' + str(run / 'events.tsv'),
           '-Dzk05.lines.output=' + str(run / 'lines.tsv'),
           '-Dzk05.fault.plan=' + '|||'.join(plan),
           '-javaagent:' + str(TOOLS / 'agent/zk05-agent.jar') + '=' + CLASSES,
           '-javaagent:' + str(JACOCO_AGENT) + '=destfile=' + str(run / 'jacoco.exec')
           + ',append=false,output=file,includes=org.apache.zookeeper.*',
           '-cp', cp, 'zk05.OriginalJUnitRunner',
           'org.apache.zookeeper.test.QuorumRestartTest', 'testRollingRestart']
    started = time.monotonic()
    with (run / 'junit.log').open('w') as log:
        process = subprocess.Popen(cmd, cwd=SOURCE / 'zookeeper-server',
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=args.timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            code = 124
            timed_out = True
    elapsed = round(time.monotonic() - started, 3)
    if (run / 'jacoco.exec').exists():
        with (run / 'coverage.tsv').open('w') as output:
            subprocess.run([str(JAVA), '-cp', str(JACOCO_CORE) + os.pathsep
                            + str(TOOLS / 'coverage/zk05-coverage-dump.jar'),
                            'zk05.CoverageDump', str(run / 'jacoco.exec')],
                           stdout=output, stderr=subprocess.PIPE, check=True)
    summary = {'run_id': args.run_id, 'junit_exit_code': code,
               'elapsed_seconds': elapsed, 'timeout': timed_out,
               'fault_plan': plan, 'target_test': 'QuorumRestartTest#testRollingRestart',
               'methodology': 'original_junit_independent_asm_jacoco',
               'agent_sha256': sha(TOOLS / 'agent/zk05-agent.jar'),
               'runner_sha256': sha(TOOLS / 'runner/zk05-runner.jar'),
               'classpath_sha256': hashlib.sha256(cp.encode()).hexdigest()}
    (run / 'run.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'run': str(run), 'exit': code, 'elapsed': elapsed,
                      'timeout': timed_out}, sort_keys=True), flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
