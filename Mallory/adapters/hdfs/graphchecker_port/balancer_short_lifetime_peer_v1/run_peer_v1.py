#!/usr/bin/env python3
"""Stage a fresh HDFS peer-ranked campaign from pinned K4V2 inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


OLD = Path('/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-short-lifetime-k4v2-v1/formal-v1')
ROOT = Path('/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-short-lifetime-peer-v1/formal-v1')
CODE = ROOT / 'inputs/frozen-code'
CONFIG = ROOT / 'campaign-config-peer-v1.json'
CAMPAIGN = ROOT / 'campaign-peer-v1'
LOCAL = Path('/dev/shm/mallory-hdfs-balancer-short-lifetime-peer-native-v1')
ENGINE_ROOT = Path('/proj/silentfailure-PG0/ZhenyuLi/mallory-hdfs-balancer-timing-v1/formal-v1/inputs/engine-source/Mallory/static_scope_port/original_engine')
PRIOR_RUNNER = Path('/users/ZhenyuLi/.mallory-local-evidence/hdfs-balancer-short-lifetime-v1')
CASE = 'HDFS-11-TIMING-LIFETIME-PEER-V1'
OLD_CONFIG_SHA = '69607b5b31bd9cf31a3f6bfd12882f534cb8f960c2929c8fd63a4b523a5aa6e7'
CAMPAIGN_SOURCE_SHA = '28b872e77f6913fa5deb5ed919aaae01daffb3ddbd8229ed7336b092c6b1c700'
STATIC_MAY_SOURCE_SHA = '7f36447caf3d8be5cc6d58531960012008737b650b5399764a61ec3c3e5a12ec'
TEST_SOURCE_SHA = 'f30f80b858206926ec95c10f4661465b479a251398a572e597d94b397cb2f1e8'
STATIC_MAY_TEST_SHA = '00b44eaa6cc3d9dfc5de24f7acda0e73d75535f6b55e1efaccf24d21cc4c7b9a'
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
    if sha(OLD / 'campaign-config-k4v2-v1.json') != OLD_CONFIG_SHA:
        raise ValueError('predecessor config pin changed')
    state = json.loads((OLD / 'campaign-k4v2-v1/checkpoint.json').read_text())
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
        result = OLD / 'campaign-k4v2-v1/trials' / f'r{index:04d}/result.json'
        if (receipt['archive_sha256'] != sha(archive) or
                receipt['result_sha256'] != sha(result) or
                receipt['verified_against_source'] is not True):
            raise ValueError(f'predecessor raw trial {index} changed')
    return {'checkpoint_sha256': sha(OLD / 'campaign-k4v2-v1/checkpoint.json'),
            'completed_strict_fault_trials': 16, 'imported_trials': 0}


def common_pins() -> dict:
    values = {
        'test_class': sha(Path('/dev/shm/mallory-hdfs-balancer-short-lifetime-native-v1/adapted-test-classes/org/apache/hadoop/hdfs/server/balancer/TestBalancer.class')),
        'weave_receipt': sha(Path('/dev/shm/mallory-hdfs-balancer-short-lifetime-native-v1/woven/native-original-weave-receipt.json')),
    }
    if values != {'test_class': TEST_CLASS_SHA, 'weave_receipt': WEAVE_SHA}:
        raise ValueError(f'unchanged JUnit/weave pin changed: {values}')
    return values


def stage(campaign_source: Path, static_may_source: Path,
          test_source: Path, static_may_test: Path) -> None:
    predecessor = old_sealed()
    common = common_pins()
    if subprocess.run(['pgrep', '-x', 'java'], capture_output=True).stdout:
        raise RuntimeError('node1 Java slot is occupied')
    if ROOT.exists() or LOCAL.exists():
        raise RuntimeError('fresh PEERV1 root already exists; inspect it')
    if {sha(campaign_source), sha(static_may_source), sha(test_source),
            sha(static_may_test)} != {CAMPAIGN_SOURCE_SHA, STATIC_MAY_SOURCE_SHA,
                                     TEST_SOURCE_SHA, STATIC_MAY_TEST_SHA}:
        raise ValueError('v12 source pin changed')
    ROOT.mkdir(parents=True)
    shutil.copytree(OLD / 'inputs/frozen-code', CODE)
    shutil.copy2(campaign_source, CODE / 'Mallory/native_graphchecker_campaign/campaign.py')
    shutil.copy2(static_may_source, CODE / 'Mallory/native_graphchecker_campaign/static_may.py')
    shutil.copy2(test_source, CODE / 'Mallory/native_graphchecker_campaign/test_multi_anchor_campaign.py')
    shutil.copy2(static_may_test, CODE / 'Mallory/native_graphchecker_campaign/test_static_may.py')
    if (sha(CODE / 'Mallory/native_graphchecker_campaign/campaign.py') != CAMPAIGN_SOURCE_SHA or
            sha(CODE / 'Mallory/native_graphchecker_campaign/static_may.py') != STATIC_MAY_SOURCE_SHA):
        raise ValueError('staged v12 campaign changed')
    config = json.loads((OLD / 'campaign-config-k4v2-v1.json').read_text())
    if (config['case_id'] != 'HDFS-11-TIMING-LIFETIME-K4V2-V1' or
            config['budget'] != {'fault_trials': 64, 'max_faults_per_trial': 6,
                                 'seconds': 7200} or
            config['recording']['multi_target_max_anchors'] != 4 or
            'predecessor_campaign' in config):
        raise ValueError('prior K4V2 config changed')
    config['case_id'] = CASE
    config['recording']['target_name'] = 'HDFS11TIMINGLIFETIMEPEERV1'
    config['recording']['anchor_retention_policy'] = 'smoothed_postfault_3of4'
    config['recording']['control_plane_peer_policy'] = 'same_peer_pretarget_quarter'
    config['runner']['local_artifact_root'] = str(LOCAL / 'raw')
    config['runner']['local_work_root'] = str(LOCAL / 'work')
    write_new(CONFIG, config)
    write_new(ROOT / 'peer-v1-stage-receipt.json', {
        'case_id': CASE, 'config_sha256': sha(CONFIG),
        'campaign_source_sha256': CAMPAIGN_SOURCE_SHA,
        'static_may_source_sha256': STATIC_MAY_SOURCE_SHA,
        'test_source_sha256': TEST_SOURCE_SHA,
        'static_may_test_sha256': STATIC_MAY_TEST_SHA,
        'source_policy_commit': 'c75a9999253cf1549304bc831b524556b1414149',
        'predecessor': predecessor, 'common_pins': common,
        'provenance': 'independent healthy; no prior trial import or credit',
    })


def healthy() -> None:
    common_pins()
    stage_receipt = json.loads((ROOT / 'peer-v1-stage-receipt.json').read_text())
    config = json.loads(CONFIG.read_text())
    if (stage_receipt['case_id'] != CASE or
            stage_receipt['config_sha256'] != sha(CONFIG) or
            sha(CODE / 'Mallory/native_graphchecker_campaign/campaign.py') != CAMPAIGN_SOURCE_SHA or
            sha(CODE / 'Mallory/native_graphchecker_campaign/static_may.py') != STATIC_MAY_SOURCE_SHA or
            sha(CODE / 'Mallory/native_graphchecker_campaign/test_multi_anchor_campaign.py') != TEST_SOURCE_SHA or
            sha(CODE / 'Mallory/native_graphchecker_campaign/test_static_may.py') != STATIC_MAY_TEST_SHA or
            config['case_id'] != CASE or
            config['recording'].get('anchor_retention_policy') != 'smoothed_postfault_3of4' or
            config['recording'].get('control_plane_peer_policy') != 'same_peer_pretarget_quarter' or
            config['recording'].get('multi_target_max_anchors') != 4 or
            CAMPAIGN.exists() or (ROOT / 'peer-v1-healthy-gate.json').exists()):
        raise ValueError('PEERV1 stage identity changed or healthy already started')
    for name in ('local_artifact_root', 'local_work_root'):
        Path(config['runner'][name]).mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(PRIOR_RUNNER))
    from run_variant import run_guarded, require_ok
    env = dict(os.environ, PYTHONPATH=str(CODE),
               MALLORY_NATIVE_ENGINE_ROOT=str(ENGINE_ROOT))
    command = [sys.executable, '-m', 'Mallory.native_graphchecker_campaign',
               '--config', str(CONFIG), '--output', str(CAMPAIGN),
               '--stop-after-fault-trials', '0']
    receipt = run_guarded(command, log=ROOT / 'peer-v1-healthy.log', cwd=ROOT,
                          timeout=1800, env=env)
    write_new(ROOT / 'peer-v1-healthy-process.json', receipt)
    require_ok(receipt)
    state = json.loads((CAMPAIGN / 'checkpoint.json').read_text())
    result = json.loads((CAMPAIGN / 'trials/r0000/result.json').read_text())
    bundle = json.loads((CAMPAIGN / 'trials/r0000/native-summary.json').read_text())
    anchors = bundle.get('anchors')
    peer_receipt = CAMPAIGN / 'trials/r0000/peer-ranking-receipt.json'
    peer = json.loads(peer_receipt.read_text())
    if (state['case_id'] != CASE or state['scheduler_version'] != 12 or
            state['completed_fault_trials'] != 0 or state['active'] is not None or
            state['status'] != 'bounded_checkpoint_stop' or
            result['status'] != 'healthy_seed' or
            result.get('raw_exact_target_throw_count') != 0 or
            bundle.get('status') != 'multi_target_recorded' or
            peer.get('scopeKind') != 'observed_typed_rpc_peer_hint' or
            not isinstance(peer.get('anchors'), list) or len(peer['anchors']) != 4 or
            not any(a['peerAudit'].get('samePeerBeforeTargetCount', 0) > 0
                    for a in peer['anchors']) or
            not isinstance(anchors, list) or len(anchors) != 4 or
            not all(row.get('targetReached') is True for row in anchors)):
        raise RuntimeError('fresh PEERV1 healthy graph did not pass gate')
    write_new(ROOT / 'peer-v1-healthy-gate.json', {
        'case_id': CASE, 'imported_old_trials': 0,
        'raw_exact_target_throw_count': 0,
        'anchor_addresses': [row['occurrenceAddress'] for row in anchors],
        'anchor_graph_sha256': [sha(CAMPAIGN / 'trials/r0000/original-graph' /
                                    f'anchor-{index:02d}/summary.json')
                                for index in range(4)],
        'result_sha256': sha(CAMPAIGN / 'trials/r0000/result.json'),
        'checkpoint_sha256': sha(CAMPAIGN / 'checkpoint.json'),
        'bundle_sha256': sha(CAMPAIGN / 'trials/r0000/native-summary.json'),
        'peer_ranking_receipt_sha256': sha(peer_receipt),
        'peer_same_before_counts': [a['peerAudit']['samePeerBeforeTargetCount']
                                    for a in peer['anchors']],
        'elapsed_seconds': receipt['elapsed_seconds'],
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('stage', 'healthy'), required=True)
    parser.add_argument('--campaign-source', type=Path)
    parser.add_argument('--static-may-source', type=Path)
    parser.add_argument('--test-source', type=Path)
    parser.add_argument('--static-may-test', type=Path)
    args = parser.parse_args()
    if args.phase == 'stage':
        if any(path is None for path in (args.campaign_source,
                args.static_may_source, args.test_source,
                args.static_may_test)):
            parser.error('stage requires four pinned source paths')
        stage(args.campaign_source, args.static_may_source,
              args.test_source, args.static_may_test)
    else:
        healthy()


if __name__ == '__main__':
    main()
