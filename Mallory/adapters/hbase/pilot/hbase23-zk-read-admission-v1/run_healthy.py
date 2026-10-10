#!/usr/bin/env python3
"""Dispatch-only, one-attempt HBASE-23 healthy admission runner."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from preflight import CORE, HERE, ROOT, verify
from verify_healthy import review


LOCK = Path('/tmp/mallory-lanes/hbase-lane9-next.lock')
OUTPUT = ROOT / 'data/mallory/HBASE-23/healthy/typed-zk-read-v1'


def java_busy():
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / 'comm').read_text().strip() == 'java':
                return True
        except (FileNotFoundError, PermissionError):
            pass
    return False


def run(attempt):
    if os.environ.get('MALLORY_NODE1_CAPACITY_GRANTED') != '1':
        raise RuntimeError('dispatch must grant node1 capacity')
    if not os.uname().nodename.startswith('node1'):
        raise RuntimeError('healthy MiniCluster runner is pinned to node1')
    if not 1 <= attempt <= 12:
        raise ValueError('attempt must be between 1 and 12')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight = verify(strict_runtime=True)
        if java_busy():
            raise RuntimeError('another JVM is active on node1')
        output = OUTPUT / f'attempt-{attempt:02d}'
        if output.exists():
            raise FileExistsError(f'healthy attempt is immutable: {output}')
        output.mkdir(parents=True)
        (output / 'node1-preflight.json').write_text(json.dumps(preflight, indent=2,
                                                     sort_keys=True) + '\n')
        env = dict(os.environ, PYTHONPATH=f'{CORE}:{ROOT}')
        command = [sys.executable, '-m', 'Mallory.core.campaign', '--config',
                   str(HERE / 'healthy.json'), '--out', str(output), '--calibration-only']
        with (output / 'campaign.log').open('w') as log:
            campaign = subprocess.run(command, cwd=ROOT, env=env, stdout=log,
                                      stderr=subprocess.STDOUT)
        audit_code = None
        audit_file = output / 'offline-causal-audit.json'
        if (output / 'result.json').exists() and (output / 'trials/r0000/result.json').exists():
            command = [sys.executable, '-m', 'Mallory.core.audit', '--campaign',
                       str(output), '--out', str(audit_file)]
            with (output / 'audit.log').open('w') as log:
                audit = subprocess.run(command, cwd=ROOT, env=env, stdout=log,
                                       stderr=subprocess.STDOUT)
            audit_code = audit.returncode
        if audit_file.exists():
            try:
                admission = review(output)
            except (OSError, ValueError, KeyError) as error:
                admission = {'case_id': 'HBASE-23', 'status': 'healthy_not_admitted',
                             'reasons': [f'offline verifier could not read evidence: {error}'],
                             'jvm_workloads_started_by_verifier': 0,
                             'fault_trials_admitted': False}
        else:
            admission = {'case_id': 'HBASE-23', 'status': 'healthy_not_admitted',
                         'reasons': ['offline audit artifact absent'],
                         'jvm_workloads_started_by_verifier': 0,
                         'fault_trials_admitted': False}
        if campaign.returncode or audit_code:
            admission['status'] = 'healthy_not_admitted'
            admission.setdefault('reasons', []).append(
                f'campaign/audit process exit codes: {campaign.returncode}/{audit_code}')
        admission.update({'campaign_exit_code': campaign.returncode,
                          'audit_exit_code': audit_code,
                          'attempt': attempt, 'preflight_status': preflight['status']})
        (output / 'admission-receipt.json').write_text(json.dumps(admission, indent=2,
                                                      sort_keys=True) + '\n')
        return admission


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', type=int, required=True)
    args = parser.parse_args()
    receipt = run(args.attempt)
    print(json.dumps({'attempt': args.attempt, 'status': receipt['status'],
                      'reasons': receipt.get('reasons', [])}, sort_keys=True))
    raise SystemExit(0 if receipt['status'] == 'healthy_admitted' else 2)
