#!/usr/bin/env python3
"""Dispatch-owned HBASE-23 campaign with a synchronous fresh-r0000 gate."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from preflight_full import verify as preflight
from verify_fresh_seed import review as review_fresh_seed
from preflight import HERE, ROOT


LOCK = Path('/tmp/mallory-lanes/hbase-lane9-next.lock')
OUTPUT = ROOT / 'data/mallory/HBASE-23/full/existing-minizk-four-member-v1'
CORE = ROOT / ('Mallory/dispatch/releases/'
               'fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def java_busy() -> bool:
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / 'comm').read_text().strip() == 'java':
                return True
        except (FileNotFoundError, PermissionError):
            continue
    return False


def run(attempt: int) -> dict:
    if os.environ.get('MALLORY_NODE1_CAPACITY_GRANTED') != '1':
        raise RuntimeError('dispatch must grant node1 capacity')
    if not os.uname().nodename.startswith('node1'):
        raise RuntimeError('the HBase MiniZK lane is pinned to node1')
    if not 1 <= attempt <= 3:
        raise ValueError('full attempt must be between 1 and 3')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        checked = preflight(strict_runtime=True)
        if java_busy():
            raise RuntimeError('another Java process is active on node1')

        out = OUTPUT / f'attempt-{attempt:02d}'
        if out.exists():
            checkpoint = out / 'checkpoint.json'
            if not checkpoint.is_file():
                raise RuntimeError('existing output has no resumable checkpoint')
            state = json.loads(checkpoint.read_text())
            config = json.loads((HERE / 'full.json').read_text())
            sys.path.insert(0, str(CORE))
            from Mallory.core.feedback import digest
            if state.get('config_digest') != digest(config):
                raise RuntimeError('checkpoint belongs to another full config')
            if 0 in state.get('completed_trials', []):
                gate_path = out / 'fresh-r0000-admission.json'
                if not gate_path.is_file():
                    raise RuntimeError('r0000 completed without a recorded pre-fault gate')
                gate = json.loads(gate_path.read_text())
                if gate.get('status') != 'fresh_r0000_admitted' or gate.get('reasons') or not (
                        out / 'trials/r0000/result.json').is_file() or (
                        gate.get('result_sha256') != sha(out / 'trials/r0000/result.json')):
                    raise RuntimeError('r0000 gate failed or its evidence changed; refuse resume')
            if state.get('status') != 'running':
                return {'case_id': 'HBASE-23', 'status': state['status'],
                        'output': str(out), 'resumed': False,
                        'fault_trials_completed': sum(i > 0 for i in
                                                      state.get('completed_trials', []))}
        else:
            out.mkdir(parents=True)
            (out / 'node1-preflight.json').write_text(json.dumps(checked, indent=2,
                                                                 sort_keys=True) + '\n')

        sys.path.insert(0, str(CORE))
        from Mallory.core import campaign

        original_apply = campaign._apply_result

        def gated_apply(state, config, result, item):
            original_apply(state, config, result, item)
            if result.get('trial_id') != 0:
                return
            try:
                gate = review_fresh_seed(out, state)
            except Exception as exc:
                gate = {
                    'schema_version': 1, 'case_id': 'HBASE-23',
                    'status': 'fresh_r0000_rejected',
                    'fault_trials_started_at_gate': 0,
                    'result_sha256': sha(out / 'trials/r0000/result.json'),
                    'reasons': [f'fresh seed verifier failed: {type(exc).__name__}: {exc}'],
                }
            campaign.atomic_json(out / 'fresh-r0000-admission.json', gate)
            if gate['status'] != 'fresh_r0000_admitted':
                state['queue'].clear()
                if state['status'] == 'running':
                    state['status'] = 'healthy_attestation_failed'

        campaign._apply_result = gated_apply
        try:
            state = campaign.run(HERE / 'full.json', out, calibration_only=False)
        finally:
            campaign._apply_result = original_apply

        gate_path = out / 'fresh-r0000-admission.json'
        gate = json.loads(gate_path.read_text()) if gate_path.is_file() else None
        faults = sum(i > 0 for i in state['completed_trials'])
        if faults and (not gate or gate.get('status') != 'fresh_r0000_admitted'):
            raise AssertionError('fault trial exists without admitted fresh-r0000 gate')
        receipt = {
            'schema_version': 1, 'case_id': 'HBASE-23', 'attempt': attempt,
            'status': state['status'], 'output': str(out),
            'fault_trials_completed': faults,
            'fresh_r0000_admission_status': gate['status'] if gate else 'absent',
            'fresh_r0000_admission_sha256': sha(gate_path) if gate else None,
            'result_sha256': sha(out / 'result.json'),
            'full_config_sha256': checked['full_config_sha256'],
            'completed_at_utc_epoch': time.time(),
        }
        campaign.atomic_json(out / 'full-run-receipt.json', receipt)
        return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=int, required=True)
    args = parser.parse_args()
    result = run(args.attempt)
    print(json.dumps(result, sort_keys=True))
    if result.get('fresh_r0000_admission_status') == 'fresh_r0000_rejected':
        raise SystemExit(2)
