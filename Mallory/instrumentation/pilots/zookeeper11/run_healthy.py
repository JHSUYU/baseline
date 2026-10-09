#!/usr/bin/env python3
"""Run an unchanged ZooKeeper 3.8.7 three-peer JUnit with the Mallory agent.

This is an instrumentation pilot, not a completed Mallory fuzz result.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

BASELINE = Path(__file__).resolve().parents[4]
MODULE = Path(__file__).resolve().parents[2]
TEST = 'org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest'
METHOD = 'testReadCurrentEpochFromAcceptedEpochTmpFile'
PEER = 'org.apache.zookeeper.server.quorum.QuorumPeer'


def classpath_from_report(report, source):
    properties = ET.parse(report).getroot().findall('./properties/property')
    raw = next(p.get('value') for p in properties if p.get('name') == 'java.class.path')
    original = '/tmp/zk387-unit-smoke-20261006'
    cp = raw.replace(original, str(source))
    missing = [entry for entry in cp.split(os.pathsep) if not Path(entry).exists()]
    if missing:
        raise RuntimeError('JUnit classpath has missing entries: ' + repr(missing[:4]))
    return cp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path,
                        default=Path('/users/ZhenyuLi/zk11-independent-unit'))
    parser.add_argument('--report', type=Path,
                        default=Path('/tmp/zk387-unit-smoke-20261006/zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml'))
    parser.add_argument('--runner', type=Path,
                        default=BASELINE / 'crashfuzz/vendor/0e00f21aa9596261-independent-runner.jar')
    parser.add_argument('--output', type=Path, default=MODULE / 'target/pilots/zk11-healthy')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--slot', type=int, default=16)
    args = parser.parse_args()
    args.source = args.source.resolve()
    args.report = args.report.resolve()
    args.runner = args.runner.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'temp').mkdir()
    (args.output / 'test-data').mkdir()
    sites = {
        'targets': [{'class': PEER, 'method': 'loadDataBase'}],
        'regions': [{'class': PEER, 'method': 'loadDataBase'}],
        'nodeBindings': [{'class': PEER, 'method': 'loadDataBase',
                          'field': 'myid', 'prefix': 'zk'}]
    }
    (args.output / 'sites.json').write_text(json.dumps(sites, indent=2) + '\n')
    agent = MODULE / 'target/mallory-agent.jar'
    if not agent.is_file():
        raise FileNotFoundError('Build instrumentation with mvn package first')
    config = '\n'.join((
        'run.id=zk11-healthy-pilot',
        'events=' + str(args.output / 'events.jsonl'),
        'site.catalog=' + str(args.output / 'catalog.jsonl'),
        'include=' + PEER,
        'site.file=' + str(args.output / 'sites.json'),
        'auto.io.doors=true',
        'coverage.methods=true',
        'coverage.branches=true',
        'state.fields=false',
        'state.maps=false',
        ''))
    (args.output / 'agent.properties').write_text(config)
    cp = os.pathsep.join((str(args.runner), classpath_from_report(args.report, args.source)))
    command = [
        '/usr/lib/jvm/java-8-openjdk-amd64/bin/java', '-Xverify:all', '-ea', '-Xmx1g',
        '-Djava.awt.headless=true', '-Dsun.reflect.noInflation=true',
        '-Djava.io.tmpdir=' + str(args.output / 'temp'),
        '-Dbuild.test.dir=' + str(args.output / 'test-data'),
        '-Dtest.junit.threads=16', '-Dzookeeper.junit.threadid=' + str(args.slot),
        '-javaagent:' + str(agent) + '=config=' + str(args.output / 'agent.properties'),
        '-cp', cp, 'independent.OriginalJUnitRunner', TEST, METHOD,
    ]
    started = time.monotonic()
    with (args.output / 'junit.log').open('w') as log:
        try:
            process = subprocess.run(command, cwd=args.source / 'zookeeper-server',
                                     stdout=log, stderr=subprocess.STDOUT,
                                     timeout=args.timeout, check=False)
            code = process.returncode
        except subprocess.TimeoutExpired:
            code = 124
    receipt = {
        'case_id': 'ZOOKEEPER-11',
        'kind': 'healthy_agent_pilot',
        'original_test': TEST + '#' + METHOD,
        'source_commit': subprocess.check_output(
            ['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip(),
        'agent_sha256': hashlib.sha256(agent.read_bytes()).hexdigest(),
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'exit_code': code,
        'output': str(args.output),
    }
    (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
