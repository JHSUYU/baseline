#!/usr/bin/env python3
"""Run one isolated original ZK04 JUnit with an ordered actor-aware I/O plan."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from calibrate_healthy import (AGENT, JAVA, ROOT, RUNNER, SOURCE, TEST_CLASS,
                               TEST_CLASS_FILE, TEST_METHOD, classpath, preflight, sha)


def run(run_id, plan, worker_id=15, worker_count=16, timeout=180):
    if not run_id.startswith('trial-') or '/' in run_id or not plan:
        raise ValueError('trial requires trial-* ID and nonempty fault plan')
    if any('|||' in selector or not selector for selector in plan):
        raise ValueError('invalid actor-aware selector')
    if not (AGENT.is_file() and RUNNER.is_file() and TEST_CLASS_FILE.is_file()):
        raise RuntimeError('original JUnit artifacts or case agent missing')
    dest = ROOT / run_id
    if dest.exists():
        raise FileExistsError(dest)
    check = preflight(worker_id, worker_count)
    dest.mkdir(parents=True)
    (dest / 'temp').mkdir()
    cp = classpath()
    cmd = [str(JAVA), '-ea', '-Xmx1g', '-Djava.awt.headless=true',
           '-Dsun.reflect.noInflation=true', '-Djava.io.tmpdir=' + str(dest / 'temp'),
           '-Dbuild.test.dir=' + str(dest / 'test-data'),
           '-Dtest.junit.threads=' + str(worker_count),
           '-Dzookeeper.junit.threadid=' + str(worker_id),
           '-Dzk.actor.plan=' + '|||'.join(plan),
           '-Dzk.actor.events.output=' + str(dest / 'events.tsv'),
           '-Dzk.actor.coverage.output=' + str(dest / 'coverage.tsv'),
           '-javaagent:' + str(AGENT), '-cp', cp,
           'zk04.OriginalJUnitRunner', TEST_CLASS, TEST_METHOD]
    started = time.monotonic()
    with (dest / 'junit.log').open('w') as log:
        try:
            code = subprocess.run(cmd, cwd=SOURCE / 'zookeeper-server',
                                  stdout=log, stderr=subprocess.STDOUT,
                                  timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
    receipt = {'run_id': run_id, 'plan': plan, 'worker_slot': worker_id,
               'worker_count': worker_count, 'preflight': check,
               'elapsed_seconds': round(time.monotonic() - started, 3),
               'exit_code': code, 'agent_sha256': sha(AGENT),
               'original_test_class_sha256': sha(TEST_CLASS_FILE),
               'runner_sha256': sha(RUNNER),
               'classpath_sha256': hashlib.sha256(cp.encode()).hexdigest(),
               'original_source_commit': '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae',
               'original_test': TEST_CLASS + '#' + TEST_METHOD,
               'stdout_log_bytes': (dest / 'junit.log').stat().st_size}
    tmp = dest / 'run.json.tmp'
    tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, dest / 'run.json')
    # Finished JUnit scratch is disposable; raw traces, receipt, and logs stay.
    shutil.rmtree(dest / 'temp', ignore_errors=True)
    shutil.rmtree(dest / 'test-data', ignore_errors=True)
    return receipt
