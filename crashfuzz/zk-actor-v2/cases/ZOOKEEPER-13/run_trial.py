#!/usr/bin/env python3
"""Run one isolated original ZK13 JUnit trial with an actor-aware I/O plan."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from calibrate_healthy import (AGENT, JAVA, ROOT, RUNNER, SOURCE, TEST_CLASS,
                               TEST_CLASS_FILE, TEST_METHOD, classpath, preflight, sha,
                               verify_build)

def run(run_id, plan, worker_id, worker_count=16, timeout=180):
    if not run_id.startswith('trial-') or '/' in run_id or not plan:
        raise ValueError('trial needs a nonempty plan and a trial-* ID')
    if any('|||' in selector or not selector for selector in plan):
        raise ValueError('invalid selector')
    if not (AGENT.is_file() and RUNNER.is_file() and TEST_CLASS_FILE.is_file()):
        raise RuntimeError('original JUnit/agent artifacts absent')
    verify_build()
    dest = ROOT / run_id
    if dest.exists():
        raise FileExistsError(dest)
    check = preflight(worker_id, worker_count)
    dest.mkdir(parents=True)
    (dest / 'temp').mkdir()
    cp = classpath()
    cmd = [str(JAVA), '-Xverify:all', '-ea', '-Xmx1g', '-Djava.awt.headless=true',
           '-Dsun.reflect.noInflation=true',
           '-Djava.io.tmpdir=' + str(dest / 'temp'),
           '-Dbuild.test.dir=' + str(dest / 'test-data'),
           '-Dtest.junit.threads=' + str(worker_count),
           '-Dzookeeper.junit.threadid=' + str(worker_id),
           '-Dzk.actor.plan=' + '|||'.join(plan),
           '-Dzk.actor.events.output=' + str(dest / 'events.tsv'),
           '-Dzk.actor.coverage.output=' + str(dest / 'coverage.tsv'),
           '-javaagent:' + str(AGENT), '-cp', cp,
           'independent.OriginalJUnitRunner', TEST_CLASS, TEST_METHOD]
    started = time.monotonic()
    with (dest / 'junit.log').open('w') as log:
        try:
            result = subprocess.run(cmd, cwd=SOURCE / 'zookeeper-server',
                                    stdout=log, stderr=subprocess.STDOUT,
                                    timeout=timeout)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    receipt = {
        'run_id': run_id, 'plan': plan, 'worker_slot': worker_id,
        'worker_count': worker_count, 'preflight': check,
        'elapsed_seconds': round(time.monotonic() - started, 3),
        'exit_code': exit_code, 'agent_sha256': sha(AGENT),
        'original_test_class_sha256': sha(TEST_CLASS_FILE),
        'runner_sha256': sha(RUNNER),
        'classpath_sha256': hashlib.sha256(cp.encode()).hexdigest(),
        'original_source_commit': '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae',
        'original_test': TEST_CLASS + '#' + TEST_METHOD,
        'stdout_log_bytes': (dest / 'junit.log').stat().st_size,
    }
    temp = dest / 'run.json.tmp'
    temp.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n')
    os.replace(temp, dest / 'run.json')
    # Original JUnit scratch is disposable. Preserve events, coverage, logs,
    # and the full receipt for later source-level review and replay.
    shutil.rmtree(dest / 'temp', ignore_errors=True)
    shutil.rmtree(dest / 'test-data', ignore_errors=True)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id')
    parser.add_argument('plan_json', type=Path)
    parser.add_argument('--worker-id', type=int, required=True)
    parser.add_argument('--worker-count', type=int, default=16)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    plan = json.loads(args.plan_json.read_text())
    print(json.dumps(run(args.run_id, plan, args.worker_id,
                         args.worker_count, args.timeout), sort_keys=True))


if __name__ == '__main__':
    main()
