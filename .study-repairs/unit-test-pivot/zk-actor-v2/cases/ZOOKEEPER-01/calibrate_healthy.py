#!/usr/bin/env python3
"""Prepare or later run two fresh original-cluster JUnit healthy calibrations.

Default is read-only preparation. --run explicitly starts the original JUnit and
requires an assigned ZooKeeper test port slot; never touches the old campaign.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

CASE = Path(__file__).resolve().parent
BUILD = Path('/users/ZhenyuLi/zk01-actor-v2-build')
ROOT = Path('/users/ZhenyuLi/zk01-actor-v2-runs')
SOURCE = Path('/users/ZhenyuLi/zk01-independent-unit')
REPORT = Path('/tmp/zk387-unit-smoke-20261006/zookeeper-server/target/surefire-reports/TEST-org.apache.zookeeper.test.QuorumRestartTest.xml')
JAVA = Path('/usr/lib/jvm/java-8-openjdk-amd64/bin/java')
ASM = Path('/users/ZhenyuLi/.m2/repository/org/ow2/asm/asm/9.4/asm-9.4.jar')
AGENT = BUILD / 'zk01-actor-v2-agent.jar'
RUNNER = Path('/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/ZOOKEEPER-01/evidence/independent/runner/independent-runner.jar')
TEST_CLASS = 'org.apache.zookeeper.server.quorum.SessionUpgradeQuorumTest'
TEST_METHOD = 'testCloseSessionWhileUpgradeOnLeader'
TEST_CLASS_FILE = SOURCE / 'zookeeper-server/target/test-classes/org/apache/zookeeper/server/quorum/SessionUpgradeQuorumTest.class'
MIN_FREE_BYTES = 2 * 1024 ** 3


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classpath():
    props = ET.parse(REPORT).getroot().findall('./properties/property')
    original = next(p.get('value') for p in props if p.get('name') == 'java.class.path')
    original = original.replace('/tmp/zk387-unit-smoke-20261006', str(SOURCE))
    cp = os.pathsep.join([str(ASM), original, str(RUNNER), str(AGENT)])
    if 'graphchecker' in cp.lower() or 'skeleton' in cp.lower():
        raise ValueError('non-original GraphChecker/Skeleton dependency in classpath')
    return cp


def command(run_id, slot, slots):
    dest = ROOT / run_id
    cp = classpath()
    cmd = [str(JAVA), '-ea', '-Xmx1g', '-Djava.awt.headless=true',
           '-Dsun.reflect.noInflation=true', '-Djava.io.tmpdir=' + str(dest / 'temp'),
           '-Dbuild.test.dir=' + str(dest / 'test-data'),
           '-Dtest.junit.threads=' + str(slots), '-Dzookeeper.junit.threadid=' + str(slot),
           '-Dzk.actor.plan=',
           '-Dzk.actor.events.output=' + str(dest / 'events.tsv'),
           '-Dzk.actor.coverage.output=' + str(dest / 'coverage.tsv'),
           '-javaagent:' + str(AGENT), '-cp', cp,
           'independent.OriginalJUnitRunner', TEST_CLASS, TEST_METHOD]
    return cmd, cp


def preflight(slot, slots):
    free = shutil.disk_usage(ROOT.parent).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError('disk under 2 GiB headroom before cluster JVM: ' + str(free))
    span = (32767 - 11221) // slots
    low = 11221 + (slot - 1) * span
    high = low + span - 1
    listeners = subprocess.check_output(['ss', '-H', '-ltn'], text=True)
    occupied = []
    for line in listeners.splitlines():
        address = line.split()[3]
        try:
            port = int(address.rsplit(':', 1)[1])
        except (IndexError, ValueError):
            continue
        if low <= port <= high:
            occupied.append(port)
    if occupied:
        raise RuntimeError('reserved ZooKeeper port slot occupied: '
                           + str((low, high, occupied)))
    return {'free_bytes': free, 'port_range': [low, high]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='start two cluster JUnit runs')
    parser.add_argument('--worker-id', type=int, help='reserved ZooKeeper port slot')
    parser.add_argument('--worker-count', type=int, default=1)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    if args.run and (args.worker_id is None or args.worker_id < 1):
        parser.error('--run requires a reserved --worker-id >= 1')
    if args.worker_count < 1:
        parser.error('--worker-count must be positive')
    if args.run and args.worker_id > args.worker_count:
        parser.error('--worker-id must be within --worker-count')
    if not AGENT.is_file() or not RUNNER.is_file() or not TEST_CLASS_FILE.is_file():
        raise SystemExit('build adapter first and retain the original JUnit classes/runner')
    selected_slot = args.worker_id if args.worker_id is not None else '<reserved-slot>'
    prepared = []
    for run_id in ('healthy-a', 'healthy-b'):
        if args.run:
            check = preflight(args.worker_id, args.worker_count)
            dest = ROOT / run_id
            if dest.exists():
                raise SystemExit(str(dest) + ' already exists; refusing to overwrite evidence')
            dest.mkdir(parents=True)
            (dest / 'temp').mkdir()
        cmd, cp = command(run_id, args.worker_id or 1, args.worker_count)
        prepared.append({'run_id': run_id, 'worker_slot': selected_slot,
                         'agent_sha256': sha(AGENT), 'original_test_class_sha256': sha(TEST_CLASS_FILE),
                         'runner_sha256': sha(RUNNER), 'classpath_sha256': hashlib.sha256(cp.encode()).hexdigest(),
                         'original_test': TEST_CLASS + '#' + TEST_METHOD,
                         'output_directory': str(ROOT / run_id), 'command': cmd})
        if args.run:
            prepared[-1]['preflight'] = check
        if not args.run:
            continue
        started = time.monotonic()
        dest = ROOT / run_id
        with (dest / 'junit.log').open('w') as log:
            try:
                proc = subprocess.run(cmd, cwd=SOURCE / 'zookeeper-server', stdout=log,
                                      stderr=subprocess.STDOUT, timeout=args.timeout)
                code = proc.returncode
            except subprocess.TimeoutExpired:
                code = 124
        receipt = {key: value for key, value in prepared[-1].items() if key != 'command'}
        receipt.update(exit_code=code, elapsed_seconds=round(time.monotonic() - started, 3),
                       plan=[], original_source_commit='9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae')
        temp = dest / 'run.json.tmp'
        temp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        os.replace(temp, dest / 'run.json')
        print(json.dumps(receipt, sort_keys=True), flush=True)
        if code != 0:
            raise SystemExit(code)
        if shutil.disk_usage(ROOT.parent).free < MIN_FREE_BYTES:
            raise SystemExit('disk under 2 GiB after healthy run; stopping calibration')
    if not args.run:
        print(json.dumps({'status': 'prepared_only', 'junit_executed': False,
                          'runs': prepared}, indent=2))


if __name__ == '__main__':
    main()
