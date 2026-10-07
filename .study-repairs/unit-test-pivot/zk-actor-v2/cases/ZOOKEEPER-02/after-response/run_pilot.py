#!/usr/bin/env python3
"""Bounded original-JUnit calibration and one isolated after-write pilot."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
spec = importlib.util.spec_from_file_location('zk02_calibration', CASE / 'calibrate_healthy.py')
calibration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibration)
calibration.ROOT = Path('/users/ZhenyuLi/zk02-actor-v2-after-response-runs')
calibration.AGENT = Path('/users/ZhenyuLi/zk02-actor-v2-after-response-build/zk02-after-response-agent.jar')
ROOT = calibration.ROOT
AGENT = calibration.AGENT
SLOT = 15
SLOTS = 16


def execute(run_id, plan, expected_agent_sha, slot=SLOT):
    if run_id not in ('healthy-a', 'healthy-b', 'pilot-01', 'pilot-02', 'pilot-03') and not (
            run_id.startswith('trial-') and run_id[6:].isdigit()):
        raise ValueError('unexpected isolated run id')
    if calibration.sha(AGENT) != expected_agent_sha:
        raise RuntimeError('after-I/O agent changed between calibration and pilot')
    if not calibration.RUNNER.is_file() or not calibration.TEST_CLASS_FILE.is_file():
        raise RuntimeError('original JUnit artifacts missing')
    check = calibration.preflight(slot, SLOTS)
    dest = ROOT / run_id
    if dest.exists():
        raise FileExistsError(dest)
    dest.mkdir(parents=True)
    (dest / 'temp').mkdir()
    cp = calibration.classpath()
    command = [str(calibration.JAVA), '-ea', '-Xmx1g', '-Djava.awt.headless=true',
               '-Dsun.reflect.noInflation=true',
               '-Djava.io.tmpdir=' + str(dest / 'temp'),
               '-Dbuild.test.dir=' + str(dest / 'test-data'),
               '-Dtest.junit.threads=' + str(SLOTS),
               '-Dzookeeper.junit.threadid=' + str(slot),
               '-Dzk.actor.plan=' + '|||'.join(plan),
               '-Dzk.actor.events.output=' + str(dest / 'events.tsv'),
               '-Dzk.actor.coverage.output=' + str(dest / 'coverage.tsv'),
               '-javaagent:' + str(AGENT), '-cp', cp,
               'independent.OriginalJUnitRunner', calibration.TEST_CLASS,
               calibration.TEST_METHOD]
    start = time.monotonic()
    with (dest / 'junit.log').open('w') as log:
        try:
            result = subprocess.run(command, cwd=calibration.SOURCE / 'zookeeper-server',
                                    stdout=log, stderr=subprocess.STDOUT, timeout=180)
            exit_code = result.returncode
        except subprocess.TimeoutExpired:
            exit_code = 124
    receipt = {
        'run_id': run_id, 'experiment': 'post-response-stage-two',
        'counts_toward_campaign_budget': False, 'plan': plan,
        'worker_slot': slot, 'worker_count': SLOTS, 'preflight': check,
        'elapsed_seconds': round(time.monotonic() - start, 3), 'exit_code': exit_code,
        'agent_sha256': calibration.sha(AGENT),
        'original_test_class_sha256': calibration.sha(calibration.TEST_CLASS_FILE),
        'runner_sha256': calibration.sha(calibration.RUNNER),
        'classpath_sha256': hashlib.sha256(cp.encode()).hexdigest(),
        'original_source_commit': '9085db92dd679e1e90a63bfe6ae6345ab6cbc4ae',
        'original_test': calibration.TEST_CLASS + '#' + calibration.TEST_METHOD,
    }
    (dest / 'run.json.tmp').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    os.replace(dest / 'run.json.tmp', dest / 'run.json')
    shutil.rmtree(dest / 'temp', ignore_errors=True)
    shutil.rmtree(dest / 'test-data', ignore_errors=True)
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('healthy', 'pilot'))
    parser.add_argument('--selector', help='exact selector from the new healthy trace')
    parser.add_argument('--run-id', default='pilot-01',
                        choices=('pilot-01', 'pilot-02', 'pilot-03'))
    args = parser.parse_args()
    if args.stage == 'pilot' and not args.selector:
        parser.error('pilot requires an exact --selector')
    if args.stage == 'healthy' and args.selector:
        parser.error('healthy takes no selector')
    expected = calibration.sha(AGENT)
    ids = ('healthy-a', 'healthy-b') if args.stage == 'healthy' else (args.run_id,)
    for run_id in ids:
        result = execute(run_id, [] if args.stage == 'healthy' else [args.selector], expected)
        print(json.dumps(result, sort_keys=True), flush=True)
        if result['exit_code'] != 0 and args.stage == 'healthy':
            raise SystemExit('original healthy JUnit failed; no pilot permitted')
        if shutil.disk_usage(ROOT.parent).free < calibration.MIN_FREE_BYTES:
            raise SystemExit('disk under 2 GiB after original JUnit; stopping')


if __name__ == '__main__':
    main()
