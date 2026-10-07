#!/usr/bin/env python3
"""Original JUnit runner; no cluster starts without explicit --run and a port slot."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from build_adapter import (AGENT, ATOMIC_NAME, BUILD, JAVA, PEER_NAME, REVISION,
                           SERVER, SOURCE, TEST, TEST_NAME, original_classpath, sha)

CASE = Path(__file__).resolve().parent
ROOT = Path('/users/ZhenyuLi/zk1112-actor-v2-runs')
RUNNER = Path('/users/ZhenyuLi/baseline/.study-repairs/unit-test-pivot/cases/ZOOKEEPER-11/evidence/independent/runner/independent-runner.jar')
TEST_CLASS = TEST_NAME.replace('/', '.')
TEST_METHOD = 'testReadCurrentEpochFromAcceptedEpochTmpFile'
MIN_FREE_BYTES = 2 * 1024 ** 3


def classpath():
    cp = os.pathsep.join((str(AGENT), str(RUNNER), original_classpath()))
    if 'graphchecker' in cp.lower() or 'skeleton' in cp.lower():
        raise RuntimeError('non-original classpath')
    return cp


def verify_build():
    receipt = json.loads((BUILD / 'build-receipt.json').read_text())
    revision = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'],
                                       text=True).strip()
    if revision != REVISION or receipt['source_commit'] != REVISION:
        raise RuntimeError('original ZooKeeper revision changed')
    if sha(AGENT) != receipt['agent_sha256']:
        raise RuntimeError('V2 agent changed since offline smoke')
    if any(sha(path) != digest for path, digest in
           receipt['agent_sources_sha256'].items()):
        raise RuntimeError('V2 agent source differs from verified JAR')
    if sha(TEST / (TEST_NAME + '.class')) != receipt['original_test_class_sha256']:
        raise RuntimeError('original JUnit class changed')
    if sha(SERVER / (PEER_NAME + '.class')) != receipt['original_peer_class_sha256'] or \
            sha(SERVER / (ATOMIC_NAME + '.class')) != receipt['original_atomic_class_sha256']:
        raise RuntimeError('original epoch production class changed')
    source_root = SOURCE / 'zookeeper-server/src'
    if sha(source_root / 'test/java' / (TEST_NAME + '.java')) != \
            receipt['original_test_source_sha256'] or \
            sha(source_root / 'main/java' / (PEER_NAME + '.java')) != \
            receipt['original_peer_source_sha256'] or \
            sha(source_root / 'main/java' / (ATOMIC_NAME + '.java')) != \
            receipt['original_atomic_source_sha256']:
        raise RuntimeError('original epoch source changed')
    if not RUNNER.is_file():
        raise RuntimeError('original JUnit launcher absent')
    return receipt


def preflight(slot, slots):
    if not (1 <= slot <= slots):
        raise ValueError('assigned worker slot must be within worker count')
    ROOT.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(ROOT).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError('under 2 GiB free before cluster JVM: ' + str(free))
    span = (32767 - 11221) // slots
    low = 11221 + (slot - 1) * span
    high = low + span - 1
    listeners = subprocess.check_output(['ss', '-H', '-ltn'], text=True)
    occupied = []
    for line in listeners.splitlines():
        try:
            port = int(line.split()[3].rsplit(':', 1)[1])
        except (IndexError, ValueError):
            continue
        if low <= port <= high:
            occupied.append(port)
    if occupied:
        raise RuntimeError(f'ZooKeeper slot {slot}/{slots} occupied: {occupied}')
    return {'free_bytes': free, 'port_range': [low, high]}


def command(dest, plan, slot, slots):
    cp = classpath()
    return [str(JAVA / 'java'), '-Xverify:all', '-ea', '-Xmx1g',
            '-Djava.awt.headless=true', '-Dsun.reflect.noInflation=true',
            '-Djava.io.tmpdir=' + str(dest / 'temp'),
            '-Dbuild.test.dir=' + str(dest / 'test-data'),
            '-Dtest.junit.threads=' + str(slots),
            '-Dzookeeper.junit.threadid=' + str(slot),
            '-Dzk.actor.plan=' + '|||'.join(plan),
            '-Dzk.actor.events.output=' + str(dest / 'events.tsv'),
            '-Dzk.actor.coverage.output=' + str(dest / 'coverage.tsv'),
            '-javaagent:' + str(AGENT), '-cp', cp,
            'independent.OriginalJUnitRunner', TEST_CLASS, TEST_METHOD]


def run(run_id, plan, slot, slots, timeout=240):
    if not run_id or '/' in run_id or any('|||' in x for x in plan):
        raise ValueError('invalid run ID or selector plan')
    build = verify_build()
    check = preflight(slot, slots)
    dest = ROOT / run_id
    if dest.exists():
        raise FileExistsError(dest)
    dest.mkdir(parents=True)
    (dest / 'temp').mkdir()
    cmd = command(dest, plan, slot, slots)
    started = time.monotonic()
    with (dest / 'junit.log').open('w') as log:
        try:
            proc = subprocess.run(cmd, cwd=SOURCE / 'zookeeper-server',
                                  stdout=log, stderr=subprocess.STDOUT,
                                  timeout=timeout, check=False)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = 124
            log.write('\nZK1112_V2_JUNIT_TIMEOUT\n')
    receipt = {
        'run_id': run_id, 'plan': plan, 'worker_slot': slot, 'worker_count': slots,
        'preflight': check, 'exit_code': code,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'agent_sha256': build['agent_sha256'],
        'original_test_class_sha256': build['original_test_class_sha256'],
        'original_source_commit': REVISION,
        'runner_sha256': sha(RUNNER),
        'classpath_sha256': hashlib.sha256(classpath().encode()).hexdigest(),
        'original_test': TEST_CLASS + '#' + TEST_METHOD,
    }
    temp = dest / 'run.json.tmp'
    temp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    os.replace(temp, dest / 'run.json')
    shutil.rmtree(dest / 'temp', ignore_errors=True)
    shutil.rmtree(dest / 'test-data', ignore_errors=True)
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='explicitly start original JUnit')
    parser.add_argument('--run-id', default='healthy-a')
    parser.add_argument('--worker-id', type=int)
    parser.add_argument('--worker-count', type=int, default=16)
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--plan-json', type=Path)
    args = parser.parse_args()
    verify_build()
    plan = json.loads(args.plan_json.read_text()) if args.plan_json else []
    if not args.run:
        print(json.dumps({'prepared_only': True, 'junit_executed': False,
                          'run_id': args.run_id, 'plan': plan,
                          'needs_worker_slot': True}, sort_keys=True))
        return
    if args.worker_id is None:
        parser.error('--run requires an assigned --worker-id')
    run(args.run_id, plan, args.worker_id, args.worker_count, args.timeout)


if __name__ == '__main__':
    main()
