#!/usr/bin/env python3
"""Run only the fresh K4 healthy seed for the isolated HDFS timing variant."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path('/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-short-lifetime-k4-v1/formal-v1')
OLD = Path('/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-short-lifetime-v1/formal-v1')
CODE = ROOT / 'inputs/frozen-code'
CONFIG = ROOT / 'campaign-config-k4-v1.json'
CAMPAIGN = ROOT / 'campaign-k4-v1'
ENGINE_ROOT = Path('/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-timing-v1/formal-v1/inputs/engine-source/Mallory/static_scope_port/original_engine')
PRIOR_RUNNER = Path('/users/ZhenyuLi/.mallory-local-evidence/hdfs-balancer-short-lifetime-v1')
EXPECTED = {
    'config': '50cb92d2b93f86da1a516efeab8f704dc5ce930afcf9ddc4990fee59844434b5',
    'campaign_code': '0be58d1561e13adea688f4039d9fded89b7ebc8327b2e577e5188c39c9819568',
    'multi_target_code': '23a80c72d73436f888551dd5728d52f6860e314ed9443110b7a494991ef596e8',
    'test_class': 'c17878c62a8bc32a5bf47bc6870addc3d52d7b5a9042d799f0d641b4f58fc0cd',
    'weave_receipt': '2fb0def45772cfdbb19b676c7447a6397f52172318113fb48e35e34d544f5ea6',
    'old_healthy_gate': '67d688e844a12987fdce55cec1c4a0835473473dbd3ce0b766bca55fd1d0c13a',
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def check() -> dict:
    paths = {
        'config': CONFIG,
        'campaign_code': CODE / 'Mallory/native_graphchecker_campaign/campaign.py',
        'multi_target_code': CODE / 'Mallory/native_graphchecker_feedback/multi_target.py',
        'test_class': Path('/dev/shm/mallory-hdfs-balancer-short-lifetime-native-v1/adapted-test-classes/org/apache/hadoop/hdfs/server/balancer/TestBalancer.class'),
        'weave_receipt': Path('/dev/shm/mallory-hdfs-balancer-short-lifetime-native-v1/woven/native-original-weave-receipt.json'),
        'old_healthy_gate': OLD / 'healthy-gate.json',
    }
    actual = {name: digest(path) for name, path in paths.items()}
    if actual != EXPECTED:
        raise ValueError(f'K4 source pin changed: {actual}')
    config = json.loads(CONFIG.read_text())
    if (config['case_id'] != 'HDFS-11-TIMING-LIFETIME-K4-V1' or
            config['recording']['multi_target_max_anchors'] != 4 or
            config['budget'] != {'fault_trials': 64,
                                 'max_faults_per_trial': 6, 'seconds': 7200} or
            'predecessor_campaign' in config):
        raise ValueError('K4 independent configuration changed')
    if (CAMPAIGN / 'checkpoint.json').exists() or (ROOT / 'k4-healthy-process.json').exists():
        raise RuntimeError('K4 healthy already started; inspect existing receipt')
    return actual


def main() -> None:
    pins = check()
    sys.path.insert(0, str(PRIOR_RUNNER))
    from run_variant import run_guarded, require_ok, write_new

    env = dict(os.environ, PYTHONPATH=str(CODE),
               MALLORY_NATIVE_ENGINE_ROOT=str(ENGINE_ROOT))
    cmd = [sys.executable, '-m', 'Mallory.native_graphchecker_campaign',
           '--config', str(CONFIG), '--output', str(CAMPAIGN),
           '--stop-after-fault-trials', '0']
    receipt = run_guarded(cmd, log=ROOT / 'k4-healthy-run.log', cwd=ROOT,
                          timeout=1800, env=env)
    receipt['input_pins'] = pins
    write_new(ROOT / 'k4-healthy-process.json', receipt)
    require_ok(receipt)
    state = json.loads((CAMPAIGN / 'checkpoint.json').read_text())
    result = json.loads((CAMPAIGN / 'trials/r0000/result.json').read_text())
    bundle = json.loads((CAMPAIGN / 'trials/r0000/native-summary.json').read_text())
    anchors = bundle.get('anchors')
    if (state['case_id'] != 'HDFS-11-TIMING-LIFETIME-K4-V1' or
            state['completed_fault_trials'] != 0 or state['active'] is not None or
            state['status'] != 'bounded_checkpoint_stop' or
            state['healthy']['status'] != 'healthy_seed' or
            result['status'] != 'healthy_seed' or
            result.get('raw_exact_target_throw_count') != 0 or
            bundle.get('status') != 'multi_target_recorded' or
            not isinstance(anchors, list) or len(anchors) != 4 or
            not all(row.get('targetReached') is True for row in anchors)):
        raise RuntimeError('fresh K4 healthy graph did not pass its exact gate')
    write_new(ROOT / 'k4-healthy-gate.json', {
        'case_id': state['case_id'], 'completed_fault_trials': 0,
        'imported_old_trials': 0, 'raw_exact_target_throw_count': 0,
        'target_anchor_addresses': [row['occurrenceAddress'] for row in anchors],
        'anchor_graph_sha256': [digest(CAMPAIGN / 'trials/r0000/original-graph' /
                                       f'anchor-{index:02d}/summary.json')
                                for index in range(4)],
        'result_sha256': digest(CAMPAIGN / 'trials/r0000/result.json'),
        'checkpoint_sha256': digest(CAMPAIGN / 'checkpoint.json'),
        'bundle_sha256': digest(CAMPAIGN / 'trials/r0000/native-summary.json'),
    })


if __name__ == '__main__':
    main()
