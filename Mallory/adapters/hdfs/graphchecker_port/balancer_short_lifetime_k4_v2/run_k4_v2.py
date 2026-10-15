#!/usr/bin/env python3
"""Stage and run a fresh, independent HDFS K4 retention-policy healthy seed."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


OLD = Path('/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-short-lifetime-k4-v1/formal-v1')
ROOT = Path('/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-short-lifetime-k4v2-v1/formal-v1')
CODE = ROOT / 'inputs/frozen-code'
CONFIG = ROOT / 'campaign-config-k4v2-v1.json'
CAMPAIGN = ROOT / 'campaign-k4v2-v1'
LOCAL = Path('/dev/shm/mallory-hdfs-balancer-short-lifetime-k4v2-native-v1')
ENGINE_ROOT = Path('/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-timing-v1/formal-v1/inputs/engine-source/Mallory/static_scope_port/original_engine')
PRIOR_RUNNER = Path('/users/ZhenyuLi/.mallory-local-evidence/hdfs-balancer-short-lifetime-v1')
CASE = 'HDFS-11-TIMING-LIFETIME-K4V2-V1'
OLD_CONFIG_SHA = '50cb92d2b93f86da1a516efeab8f704dc5ce930afcf9ddc4990fee59844434b5'
CAMPAIGN_SOURCE_SHA = '4813f402e35bbee1713cef8b5a153fe3d6cffeb636df9da28d2a1f8ac978e67b'
TEST_SOURCE_SHA = '872fd69b304e718300f2a8a735fa0471ee0ce3ad88110d568a7d971a8902a586'
TEST_CLASS_SHA = 'c17878c62a8bc32a5bf47bc6870addc3d52d7b5a9042d799f0d641b4f58fc0cd'
WEAVE_SHA = '2fb0def45772cfdbb19b676c7447a6397f52172318113fb48e35e34d544f5ea6'


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')


def old_sealed() -> dict:
    if sha(OLD / 'campaign-config-k4-v1.json') != OLD_CONFIG_SHA:
        raise ValueError('predecessor config pin changed')
    state = json.loads((OLD / 'campaign-k4-v1/checkpoint.json').read_text())
    if (state['completed_fault_trials'] != 16 or state['active'] is not None or
            state['status'] != 'bounded_checkpoint_stop' or
            state.get('terminal') is not False or
            len(state['trials']) != 16 or
            not all(row.get('strict_injection') is True and
                    row.get('raw_exact_target_throw_count', 0) == 0
                    for row in state['trials'])):
        raise ValueError('predecessor 16-trial checkpoint is not sealed')
    for index in range(1, 17):
        archive = OLD / f'raw-r{index:04d}.tar.gz'
        receipt = json.loads((OLD / f'raw-r{index:04d}-receipt.json').read_text())
        result = OLD / 'campaign-k4-v1/trials' / f'r{index:04d}/result.json'
        if (receipt['archive_sha256'] != sha(archive) or
                receipt['result_sha256'] != sha(result) or
                receipt['verified_against_source'] is not True):
            raise ValueError(f'predecessor raw trial {index} changed')
    return {'checkpoint_sha256': sha(OLD / 'campaign-k4-v1/checkpoint.json'),
            'completed_strict_fault_trials': 16, 'imported_trials': 0}


def common_pins() -> dict:
    values = {
        'test_class': sha(Path('/dev/shm/mallory-hdfs-balancer-short-lifetime-native-v1/adapted-test-classes/org/apache/hadoop/hdfs/server/balancer/TestBalancer.class')),
        'weave_receipt': sha(Path('/dev/shm/mallory-hdfs-balancer-short-lifetime-native-v1/woven/native-original-weave-receipt.json')),
    }
    if values != {'test_class': TEST_CLASS_SHA, 'weave_receipt': WEAVE_SHA}:
        raise ValueError(f'unchanged JUnit/weave pin changed: {values}')
    return values


def stage(campaign_source: Path, test_source: Path) -> None:
    predecessor = old_sealed()
    common = common_pins()
    if subprocess.run(['pgrep', '-x', 'java'], capture_output=True).stdout:
        raise RuntimeError('node1 Java slot is occupied')
    if ROOT.exists() or LOCAL.exists():
        raise RuntimeError('fresh K4V2 root already exists; inspect it')
    if sha(campaign_source) != CAMPAIGN_SOURCE_SHA or sha(test_source) != TEST_SOURCE_SHA:
        raise ValueError('v11 source pin changed')
    ROOT.mkdir(parents=True)
    shutil.copytree(OLD / 'inputs/frozen-code', CODE)
    shutil.copy2(campaign_source, CODE / 'Mallory/native_graphchecker_campaign/campaign.py')
    shutil.copy2(test_source, CODE / 'Mallory/native_graphchecker_campaign/test_multi_anchor_campaign.py')
    if sha(CODE / 'Mallory/native_graphchecker_campaign/campaign.py') != CAMPAIGN_SOURCE_SHA:
        raise ValueError('staged v11 campaign changed')
    config = json.loads((OLD / 'campaign-config-k4-v1.json').read_text())
    if (config['case_id'] != 'HDFS-11-TIMING-LIFETIME-K4-V1' or
            config['budget'] != {'fault_trials': 64, 'max_faults_per_trial': 6,
                                 'seconds': 7200} or
            config['recording']['multi_target_max_anchors'] != 4 or
            'predecessor_campaign' in config):
        raise ValueError('prior K4 config changed')
    config['case_id'] = CASE
    config['recording']['target_name'] = 'HDFS11TIMINGLIFETIMEK4V2V1'
    config['recording']['anchor_retention_policy'] = 'smoothed_postfault_3of4'
    config['runner']['local_artifact_root'] = str(LOCAL / 'raw')
    config['runner']['local_work_root'] = str(LOCAL / 'work')
    write_new(CONFIG, config)
    write_new(ROOT / 'k4v2-stage-receipt.json', {
        'case_id': CASE, 'config_sha256': sha(CONFIG),
        'campaign_source_sha256': CAMPAIGN_SOURCE_SHA,
        'test_source_sha256': TEST_SOURCE_SHA,
        'source_policy_commit': 'f00aa20943f43a4111a436ac8746148ec3efc79a',
        'predecessor': predecessor, 'common_pins': common,
        'provenance': 'independent healthy; no prior trial import or credit',
    })


def healthy() -> None:
    common_pins()
    stage_receipt = json.loads((ROOT / 'k4v2-stage-receipt.json').read_text())
    config = json.loads(CONFIG.read_text())
    if (stage_receipt['case_id'] != CASE or
            stage_receipt['config_sha256'] != sha(CONFIG) or
            sha(CODE / 'Mallory/native_graphchecker_campaign/campaign.py') != CAMPAIGN_SOURCE_SHA or
            sha(CODE / 'Mallory/native_graphchecker_campaign/test_multi_anchor_campaign.py') != TEST_SOURCE_SHA or
            config['case_id'] != CASE or
            config['recording'].get('anchor_retention_policy') != 'smoothed_postfault_3of4' or
            config['recording'].get('multi_target_max_anchors') != 4 or
            CAMPAIGN.exists() or (ROOT / 'k4v2-healthy-gate.json').exists()):
        raise ValueError('K4V2 stage identity changed or healthy already started')
    for name in ('local_artifact_root', 'local_work_root'):
        Path(config['runner'][name]).mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(PRIOR_RUNNER))
    from run_variant import run_guarded, require_ok
    env = dict(os.environ, PYTHONPATH=str(CODE),
               MALLORY_NATIVE_ENGINE_ROOT=str(ENGINE_ROOT))
    command = [sys.executable, '-m', 'Mallory.native_graphchecker_campaign',
               '--config', str(CONFIG), '--output', str(CAMPAIGN),
               '--stop-after-fault-trials', '0']
    receipt = run_guarded(command, log=ROOT / 'k4v2-healthy.log', cwd=ROOT,
                          timeout=1800, env=env)
    write_new(ROOT / 'k4v2-healthy-process.json', receipt)
    require_ok(receipt)
    state = json.loads((CAMPAIGN / 'checkpoint.json').read_text())
    result = json.loads((CAMPAIGN / 'trials/r0000/result.json').read_text())
    bundle = json.loads((CAMPAIGN / 'trials/r0000/native-summary.json').read_text())
    anchors = bundle.get('anchors')
    if (state['case_id'] != CASE or state['scheduler_version'] != 11 or
            state['completed_fault_trials'] != 0 or state['active'] is not None or
            state['status'] != 'bounded_checkpoint_stop' or
            result['status'] != 'healthy_seed' or
            result.get('raw_exact_target_throw_count') != 0 or
            bundle.get('status') != 'multi_target_recorded' or
            not isinstance(anchors, list) or len(anchors) != 4 or
            not all(row.get('targetReached') is True for row in anchors)):
        raise RuntimeError('fresh K4V2 healthy graph did not pass gate')
    write_new(ROOT / 'k4v2-healthy-gate.json', {
        'case_id': CASE, 'imported_old_trials': 0,
        'raw_exact_target_throw_count': 0,
        'anchor_addresses': [row['occurrenceAddress'] for row in anchors],
        'anchor_graph_sha256': [sha(CAMPAIGN / 'trials/r0000/original-graph' /
                                    f'anchor-{index:02d}/summary.json')
                                for index in range(4)],
        'result_sha256': sha(CAMPAIGN / 'trials/r0000/result.json'),
        'checkpoint_sha256': sha(CAMPAIGN / 'checkpoint.json'),
        'bundle_sha256': sha(CAMPAIGN / 'trials/r0000/native-summary.json'),
        'elapsed_seconds': receipt['elapsed_seconds'],
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('stage', 'healthy'), required=True)
    parser.add_argument('--campaign-source', type=Path)
    parser.add_argument('--test-source', type=Path)
    args = parser.parse_args()
    if args.phase == 'stage':
        if args.campaign_source is None or args.test_source is None:
            parser.error('stage requires both pinned source paths')
        stage(args.campaign_source, args.test_source)
    else:
        healthy()


if __name__ == '__main__':
    main()
