#!/usr/bin/env python3
"""Pinned ZK11 full campaign with a read-only preflight and node0 lane lock."""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


BASE = Path('/users/ZhenyuLi/baseline')
HERE = Path(__file__).resolve().parent
CONFIG = HERE / 'full.json'
PINS = HERE / 'pins.json'
CORE = BASE / 'Mallory/dispatch/releases/224e15f3a987faab681ec46278650cca80ee3bc34b75ea2f68c87b911f9928f1'
OUT = BASE / 'data/mallory/campaigns/ZOOKEEPER-11-epoch-full-v2'
LOCK = Path('/tmp/mallory-lanes/zookeeper-node0-source.lock')
FLOOR = 6_000_000_000
RESERVE = 300 * 1024**2
HEADROOM = 150 * 1024**2
CHECK = 'org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V@1169:branch:2'
THROW = 'org.apache.zookeeper.server.quorum.QuorumPeer#loadDataBase()V@1175:throw:1'


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def free_bytes() -> int:
    stat = os.statvfs(OUT.parent)
    return stat.f_bavail * stat.f_frsize


def preflight() -> dict:
    config = read(CONFIG)
    pins = read(PINS)
    if pins.get('case_id') != 'ZOOKEEPER-11' or pins.get('scope') != 'epoch_full_80_3600_max3_depth4':
        raise ValueError('wrong pin manifest')
    if (config.get('case_id') != 'ZOOKEEPER-11'
            or config.get('cluster_test') != 'org.apache.zookeeper.server.quorum.CurrentEpochWriteFailureTest#testReadCurrentEpochFromAcceptedEpochTmpFile'
            or config.get('calibration_only') is not False
            or config.get('auto_promote_if_healthy') is not True
            or config.get('budget', {}).get('trials') != 80
            or config.get('budget', {}).get('seconds') != 3600
            or config.get('budget', {}).get('max_faults_per_trial') != 3
            or config.get('target', {}).get('check_sites') != [CHECK]
            or config.get('target', {}).get('throw_site') != THROW
            or config.get('expected_target_class_sha256') !=
            '446279eb1dfdb4837aaf5e65f943b54a1138a068b1b83f69b5008d6b18cca717'
            or config.get('core_release') != str(CORE)
            or config.get('multi_fault_exploration_interval') != 4
            or config.get('single_fault_breadth_interval') is not None
            or config.get('reject_coarse_roots') is not True
            or config.get('require_event_time_paths') is not True
            or config.get('allow_local_timeline_doors') is not True):
        raise ValueError('full campaign policy changed')
    for row in pins['files']:
        path = Path(row['path'])
        if not path.is_file() or sha(path) != row['sha256']:
            raise ValueError(f'pinned file missing or changed: {path}')
    controller = read(HERE / 'controller-release.json')
    manifest = read(CORE / 'manifest.json')
    if (controller.get('controller_commit') !=
            '1201848817be643685d9db82e6afe38d97cfa8dd'
            or controller.get('release_id') != CORE.name
            or controller.get('release_files') != manifest.get('files')
            or controller.get('release_manifest_sha256') != sha(CORE / 'manifest.json')
            or controller.get('scheduler_policy', {}).get('multi_fault_exploration_interval') != 4):
        raise ValueError('controller release or depth policy changed')
    prior = read(BASE / 'data/mallory/admissions/ZOOKEEPER-11-fa5f-fault-model-target-lost.json')
    audit = read(BASE / 'data/mallory/calibration_fa5f_lane2/ZOOKEEPER-11/offline-causal-audit.json')
    if (prior.get('status') != 'fault_model_target_lost'
            or prior.get('healthy', {}).get('junit_status') != 'passed'
            or prior.get('healthy', {}).get('local_timeline_doors') != 1
            or prior.get('healthy', {}).get('observed_path_doors') != 0
            or prior.get('healthy', {}).get('local_timeline_evidence', {}).get('node') != 'zk0'
            or prior.get('pilot', {}).get('strict_target_trials') != 0
            or prior.get('target', {}).get('check_site') != CHECK
            or audit.get('healthy_closure_proven') is not True
            or audit.get('healthy_closure_included_named_doors') != 1
            or audit.get('healthy_observed_path_doors') != 0
            or audit.get('healthy_closure_evidence_types') != ['observed_local_timeline']):
        raise ValueError('prior healthy or target-lost evidence changed')
    env = os.environ.copy()
    env['PYTHONPATH'] = f'{CORE}:{BASE}'
    subprocess.run([sys.executable, str(BASE / 'Mallory/adapters/zookeeper/verify_lane2_campaign.py'),
                    str(CONFIG)], cwd=BASE, env=env, check=True)
    subprocess.run([sys.executable, str(BASE / 'Mallory/dispatch/core_release.py'),
                    '--verify', str(CORE / 'manifest.json')], cwd=BASE, env=env,
                   check=True, stdout=subprocess.DEVNULL)
    return {'schema_version': 1, 'case_id': 'ZOOKEEPER-11', 'status': 'passed_no_jvm',
            'config_sha256': sha(CONFIG), 'pins_sha256': sha(PINS),
            'controller_commit': controller['controller_commit'],
            'core_release_id': CORE.name,
            'core_manifest_sha256': sha(CORE / 'manifest.json'),
            'prior_target_lost_receipt_sha256': sha(BASE / 'data/mallory/admissions/ZOOKEEPER-11-fa5f-fault-model-target-lost.json'),
            'free_bytes': free_bytes(), 'required_free_bytes': FLOOR + RESERVE,
            'fault_budget': config['budget']}


def trace_receipt(result_path: Path) -> tuple[dict, Path]:
    result = read(result_path)
    evidence = result.get('events_evidence') or {}
    name = evidence.get('gzip_path')
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError(f'compressed trace missing: {result_path}')
    trace = result_path.parent / name
    if sha(trace) != evidence.get('gzip_sha256'):
        raise ValueError(f'trace hash mismatch: {trace}')
    return result, trace


def collect(exit_code: int, audit_sha256: str | None) -> dict:
    result_path = OUT / 'result.json'
    result = read(result_path) if result_path.is_file() else {}
    audit_path = OUT / 'offline-causal-audit.json'
    audit = read(audit_path) if audit_sha256 is not None else {}
    trials = []
    for path in sorted((OUT / 'trials').glob('r[0-9][0-9][0-9][0-9]/result.json')):
        _, trace = trace_receipt(path)
        trials.append({'trial': path.parent.name, 'result_sha256': sha(path),
                       'trace_sha256': sha(trace)})
    healthy = {}
    healthy_path = OUT / 'trials/r0000/result.json'
    if healthy_path.is_file():
        row, trace = trace_receipt(healthy_path)
        checks = []
        throws = []
        with gzip.open(trace, 'rt', encoding='utf-8') as stream:
            for line in stream:
                event = json.loads(line)
                if event.get('type') == 'TARGET_CHECK' and event.get('site') == CHECK:
                    checks.append(event)
                if event.get('type') == 'TARGET_THROW' and event.get('site') == THROW:
                    throws.append(event)
        catalog = row.get('site_catalog_validation') or {}
        junit = row.get('junit_validation') or {}
        valid = (junit.get('status') == 'passed' and junit.get('tests') == 1
                 and catalog.get('valid') is True
                 and catalog.get('observed_target_class_sha256') ==
                 '446279eb1dfdb4837aaf5e65f943b54a1138a068b1b83f69b5008d6b18cca717'
                 and row.get('feedback', {}).get('status') == 'observed'
                 and len(checks) > 0 and not throws
                 and all(isinstance(event.get('node'), str)
                         and event['node'] == 'zk0'
                         and event.get('outcome') == 'FALLTHROUGH' for event in checks)
                 and result.get('healthy_seed_valid') is True
                 and (result.get('runtime_attestation') or {}).get('valid') is True)
        healthy = {'valid': valid, 'junit_status': junit.get('status'),
                   'junit_tests': junit.get('tests'), 'exact_check_count': len(checks),
                   'exact_throw_count': len(throws),
                   'target_nodes': sorted({event['node'] for event in checks
                                           if isinstance(event.get('node'), str)}),
                   'trace_sha256': sha(trace), 'result_sha256': sha(healthy_path)}
    receipt = {'schema_version': 1, 'case_id': 'ZOOKEEPER-11',
               'scope': 'epoch_full_80_3600_max3_depth4', 'driver_exit_code': exit_code,
               'campaign_status': result.get('status'),
               'fault_trials_completed': result.get('fault_trials_completed'),
               'trial_count_matches_result': (len(trials) == 1 + result['fault_trials_completed'])
               if isinstance(result.get('fault_trials_completed'), int) else False,
               'strict_injected_trials': result.get('strict_injected_trials'),
               'strict_target_trials': result.get('strict_target_trials'),
               'exact_exception_trials': result.get('exact_exception_trials'),
               'healthy': healthy, 'audit_sha256': audit_sha256,
               'graph_path_quality': {
                   'healthy_closure_proven': audit.get('healthy_closure_proven'),
                   'healthy_observed_path_doors': audit.get('healthy_observed_path_doors'),
                   'healthy_local_timeline_doors': audit.get('healthy_local_timeline_doors'),
                   'named_applied_faults': audit.get('named_applied_faults'),
                   'target_retained_fault_trials': audit.get('target_retained_fault_trials'),
                   'same_actor_target_trials': audit.get('same_actor_target_trials'),
                   'report_gate_passed': audit.get('report_gate_passed'),
               },
               'result_sha256': sha(result_path) if result_path.is_file() else None,
               'checkpoint_sha256': sha(OUT / 'checkpoint.json') if (OUT / 'checkpoint.json').is_file() else None,
               'trials': trials, 'free_bytes': free_bytes(),
               'interpretation': 'Graph-path and target-retention quality require the offline audit; no automatic bug claim.'}
    write(OUT / 'collection-receipt.json', receipt)
    return receipt


def stop(process: subprocess.Popen) -> None:
    checkpoint = OUT / 'checkpoint.json'
    child = (read(checkpoint).get('running') or {}).get('pid') if checkpoint.is_file() else None
    if process.poll() is None and os.getpgid(process.pid) == process.pid:
        os.killpg(process.pid, signal.SIGTERM)
    if isinstance(child, int) and child > 0:
        try:
            if os.getpgid(child) == child:
                os.killpg(child, signal.SIGTERM)
        except ProcessLookupError:
            pass


def run() -> int:
    if os.environ.get('MALLORY_ZK11_NODE0_V2_GO') != '1':
        raise RuntimeError('dispatch GO gate absent: MALLORY_ZK11_NODE0_V2_GO=1')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight_receipt = preflight()
        if free_bytes() < FLOOR + RESERVE:
            raise RuntimeError('disk admission below 6 GB floor plus 300 MiB reserve')
        checkpoint = OUT / 'checkpoint.json'
        if checkpoint.is_file():
            if read(checkpoint).get('status') != 'running' or sha(OUT / 'config.json') != sha(CONFIG):
                raise RuntimeError('existing campaign is terminal or config changed')
        elif OUT.exists() and any(OUT.iterdir()):
            raise RuntimeError('output directory exists without a resumable checkpoint')
        OUT.mkdir(parents=True, exist_ok=True)
        write(OUT / 'preflight.json', preflight_receipt)
        env = os.environ.copy()
        env['PYTHONPATH'] = f'{CORE}:{BASE}'
        env['MALLORY_CORE_RELEASE_ID'] = CORE.name
        env['MALLORY_ATTEMPT_ID'] = 'zk11-node0-full-v2-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        low_disk = False
        with (OUT / 'driver.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-m', 'Mallory.core.campaign',
                                        '--config', str(CONFIG), '--out', str(OUT)],
                                       cwd=CORE, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            while process.poll() is None:
                if free_bytes() < FLOOR + HEADROOM:
                    low_disk = True
                    stop(process)
                    break
                time.sleep(5)
            code = process.wait()
        write(OUT / 'driver-exit.json', {'started_utc': started,
              'finished_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'attempt_id': env['MALLORY_ATTEMPT_ID'], 'exit_code': code,
              'low_disk_stop': low_disk, 'free_bytes': free_bytes()})
        audit_sha = None
        if (OUT / 'result.json').is_file():
            audit_path = OUT / 'offline-causal-audit.json'
            audit_env = env.copy()
            with (OUT / 'offline-audit.log').open('ab') as log:
                audit_code = subprocess.run([sys.executable, '-m', 'Mallory.core.audit',
                    '--campaign', str(OUT), '--out', str(audit_path)],
                    cwd=CORE, env=audit_env, stdout=log, stderr=subprocess.STDOUT).returncode
            if audit_code == 0 and audit_path.is_file():
                audit_sha = sha(audit_path)
        receipt = collect(code, audit_sha)
        if (code == 0 and receipt['campaign_status'] in {'budget_exhausted', 'queue_exhausted'}
                and receipt['healthy'].get('valid') is True and audit_sha is not None
                and receipt['trial_count_matches_result'] is True):
            return 0
        return code or 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--preflight', action='store_true')
    choice.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.preflight:
        print(json.dumps(preflight(), sort_keys=True))
    else:
        raise SystemExit(run())
