#!/usr/bin/env python3
"""Run ZK13 with separately preserved, bounded healthy admissions."""

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
CORE = BASE / 'Mallory/dispatch/releases/29ab038f754e3df6f38f94f38cee052b82b9601f255f347322fa422b45350fbc'
OUT = BASE / 'data/mallory/campaigns/ZOOKEEPER-13-connectpath-retry-full-v1'
LOCK = Path('/tmp/mallory-lanes/zookeeper-node0-source.lock')
MAX_HEALTHY_STARTS = 3
DISK_FLOOR = 6_000_000_000
DISK_RESERVE = 300 * 1024**2
DISK_HEADROOM = 150 * 1024**2


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(row, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def free_bytes() -> int:
    stat = os.statvfs(OUT.parent)
    return stat.f_bavail * stat.f_frsize


def preflight() -> dict:
    pins = read(PINS)
    config = read(CONFIG)
    if pins['case_id'] != config['case_id'] or pins['case_id'] != 'ZOOKEEPER-13':
        raise ValueError('case identity changed')
    if (config['cluster_test'] != 'org.apache.zookeeper.test.ReadOnlyModeTest#testConnectionEvents'
            or config['budget']['trials'] != 80
            or config['budget']['seconds'] != 3600
            or config['budget']['max_faults_per_trial'] != 3
            or config['calibration_only'] is not False
            or config['auto_promote_if_healthy'] is not True
            or config['core_release'] != str(CORE)):
        raise ValueError('full admission policy changed')
    for row in pins['files']:
        path = Path(row['path'])
        if not path.is_file() or sha(path) != row['sha256']:
            raise ValueError(f'pinned file missing or changed: {path}')
    env = os.environ.copy()
    env['PYTHONPATH'] = f'{CORE}:{BASE}'
    subprocess.run([sys.executable, str(BASE / 'Mallory/adapters/zookeeper/verify_lane2_campaign.py'),
                    str(CONFIG)], cwd=BASE, env=env, check=True)
    subprocess.run([sys.executable, str(BASE / 'Mallory/dispatch/core_release.py'),
                    '--verify', str(CORE / 'manifest.json')], cwd=BASE, env=env,
                   check=True, stdout=subprocess.DEVNULL)
    return {'case_id': 'ZOOKEEPER-13', 'status': 'passed_no_jvm',
            'config_sha256': sha(CONFIG), 'pins_sha256': sha(PINS),
            'max_healthy_starts': MAX_HEALTHY_STARTS,
            'fault_budget': config['budget'], 'free_bytes': free_bytes()}


def evidence_row(attempt: Path) -> dict:
    result_path = attempt / 'result.json'
    result = read(result_path)
    healthy_path = attempt / 'trials/r0000/result.json'
    if not healthy_path.is_file():
        raise ValueError(f'missing healthy result: {attempt}')
    healthy = read(healthy_path)
    trace_info = healthy.get('events_evidence') or {}
    trace_name = trace_info.get('gzip_path')
    if not isinstance(trace_name, str) or Path(trace_name).name != trace_name:
        raise ValueError(f'healthy compressed trace missing: {attempt}')
    trace = healthy_path.parent / trace_name
    if sha(trace) != trace_info.get('gzip_sha256'):
        raise ValueError(f'healthy trace hash mismatch: {attempt}')
    checks = 0
    throws = 0
    outcomes: set[str] = set()
    check_nodes: set[str] = set()
    with gzip.open(trace, 'rt', encoding='utf-8') as stream:
        for line in stream:
            event = json.loads(line)
            if event.get('type') == 'TARGET_CHECK' and event.get('site') in CONFIG_TARGET_CHECKS:
                checks += 1
                if not isinstance(event.get('outcome'), str) or not isinstance(event.get('node'), str):
                    raise ValueError(f'unnamed exact target check: {attempt}')
                outcomes.add(event['outcome'])
                check_nodes.add(event['node'])
            throws += event.get('type') == 'TARGET_THROW' and event.get('site') == CONFIG_TARGET_THROW
    if result.get('status') == 'healthy_seed_invalid':
        if (result.get('fault_trials_completed') != 0 or checks != 0 or throws != 0
                or healthy.get('junit_validation', {}).get('status') != 'passed'
                or healthy.get('feedback', {}).get('status') != 'healthy_target_missing'
                or result.get('healthy_seed_valid') is not False):
            raise ValueError(f'invalid seed is not a passing target miss: {attempt}')
    trial_receipts = []
    for path in sorted((attempt / 'trials').glob('r[0-9][0-9][0-9][0-9]/result.json')):
        trial = read(path)
        trace_info = trial.get('events_evidence') or {}
        trace_name = trace_info.get('gzip_path')
        if not isinstance(trace_name, str) or Path(trace_name).name != trace_name:
            raise ValueError(f'trial compressed trace missing: {path}')
        trace = path.parent / trace_name
        if sha(trace) != trace_info.get('gzip_sha256'):
            raise ValueError(f'trial trace hash mismatch: {path}')
        trial_receipts.append({'trial': path.parent.name, 'result_sha256': sha(path),
                               'trace_sha256': sha(trace)})
    if len(trial_receipts) != 1 + result.get('fault_trials_completed', -2):
        raise ValueError(f'trial count differs from result: {attempt}')
    return {'attempt': attempt.name, 'campaign_status': result.get('status'),
            'healthy_junit_status': healthy.get('junit_validation', {}).get('status'),
            'healthy_feedback_status': healthy.get('feedback', {}).get('status'),
            'healthy_target_checks': checks, 'healthy_target_throws': throws,
            'healthy_target_outcomes': sorted(outcomes),
            'healthy_target_nodes': sorted(check_nodes),
            'healthy_seed_valid': result.get('healthy_seed_valid'),
            'healthy_attestation_valid': (result.get('runtime_attestation') or {}).get('valid'),
            'fault_trials_completed': result.get('fault_trials_completed'),
            'result_sha256': sha(result_path), 'healthy_result_sha256': sha(healthy_path),
            'healthy_trace_sha256': sha(trace), 'trials': trial_receipts,
            'driver_exit_code': read(attempt / 'driver-exit.json')['exit_code']}


def ledger(rows: list[dict], status: str) -> None:
    atomic_json(OUT / 'admission-ledger.json', {
        'schema_version': 1, 'case_id': 'ZOOKEEPER-13', 'status': status,
        'policy': 'up to three independent, preserved healthy starts; only passing exact target misses retry',
        'config_sha256': sha(CONFIG), 'pins_sha256': sha(PINS), 'attempts': rows})


def stop(process: subprocess.Popen, attempt: Path) -> None:
    checkpoint = attempt / 'checkpoint.json'
    running = (read(checkpoint).get('running') or {}).get('pid') if checkpoint.is_file() else None
    if process.poll() is None and os.getpgid(process.pid) == process.pid:
        os.killpg(process.pid, signal.SIGTERM)
    if isinstance(running, int) and running > 0:
        try:
            if os.getpgid(running) == running:
                os.killpg(running, signal.SIGTERM)
        except ProcessLookupError:
            pass


def launch(attempt: Path) -> None:
    attempt.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['PYTHONPATH'] = f'{CORE}:{BASE}'
    env['MALLORY_CORE_RELEASE_ID'] = CORE.name
    env['MALLORY_ATTEMPT_ID'] = 'zk13-node0-' + attempt.name + '-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    low_disk = False
    with (attempt / 'driver.log').open('ab') as log:
        process = subprocess.Popen([sys.executable, '-m', 'Mallory.core.campaign',
                                    '--config', str(CONFIG), '--out', str(attempt)],
                                   cwd=CORE, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        while process.poll() is None:
            if free_bytes() < DISK_FLOOR + DISK_HEADROOM:
                low_disk = True
                stop(process, attempt)
                break
            time.sleep(5)
        code = process.wait()
    atomic_json(attempt / 'driver-exit.json', {
        'started_utc': started,
        'finished_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'attempt_id': env['MALLORY_ATTEMPT_ID'], 'exit_code': code,
        'low_disk_stop': low_disk, 'free_bytes': free_bytes()})
    if low_disk:
        raise RuntimeError(f'disk emergency stop in {attempt}')


def audit(attempt: Path) -> str:
    output = attempt / 'offline-causal-audit.json'
    if not output.is_file():
        env = os.environ.copy()
        env['PYTHONPATH'] = f'{CORE}:{BASE}'
        with (attempt / 'offline-audit.log').open('ab') as log:
            subprocess.run([sys.executable, '-m', 'Mallory.core.audit',
                            '--campaign', str(attempt), '--out', str(output)],
                           cwd=CORE, env=env, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
    return sha(output)


def run() -> int:
    if os.environ.get('MALLORY_ZK13_NODE0_GO') != '1':
        raise RuntimeError('dispatch GO gate absent: MALLORY_ZK13_NODE0_GO=1')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        receipt = preflight()
        if free_bytes() < DISK_FLOOR + DISK_RESERVE:
            raise RuntimeError('disk admission below floor plus reserve')
        OUT.mkdir(parents=True, exist_ok=True)
        atomic_json(OUT / 'preflight.json', receipt)
        rows = []
        for index in range(1, MAX_HEALTHY_STARTS + 1):
            attempt = OUT / 'attempts' / f'a{index:02d}'
            exit_path = attempt / 'driver-exit.json'
            checkpoint_path = attempt / 'checkpoint.json'
            checkpoint = read(checkpoint_path) if checkpoint_path.is_file() else {}
            if checkpoint_path.is_file() and not exit_path.is_file() and checkpoint.get('status') != 'running':
                raise RuntimeError(f'terminal attempt lacks driver exit: {attempt}')
            if not exit_path.is_file() or checkpoint.get('status') == 'running':
                launch(attempt)
            try:
                row = evidence_row(attempt)
            except Exception as exc:
                rows.append({'attempt': attempt.name, 'classification_error': str(exc),
                             'result_sha256': sha(attempt / 'result.json')
                             if (attempt / 'result.json').is_file() else None})
                ledger(rows, 'admission_or_campaign_error')
                raise
            rows.append(row)
            if row['campaign_status'] == 'healthy_seed_invalid' and row['driver_exit_code'] == 2:
                ledger(rows, 'healthy_retry_pending' if index < MAX_HEALTHY_STARTS else 'healthy_retry_exhausted')
                continue
            if (row['driver_exit_code'] == 0 and row['healthy_seed_valid'] is True
                    and row['healthy_attestation_valid'] is True
                    and row['healthy_junit_status'] == 'passed'
                    and row['healthy_feedback_status'] == 'observed'
                    and row['healthy_target_checks'] > 0 and row['healthy_target_throws'] == 0
                    and row['healthy_target_outcomes'] == ['TAKEN']
                    and all(node and node != 'unknown' for node in row['healthy_target_nodes'])
                    and row['campaign_status'] in {'budget_exhausted', 'queue_exhausted'}):
                row['offline_audit_sha256'] = audit(attempt)
                ledger(rows, 'full_terminal')
                return 0
            ledger(rows, 'admission_or_campaign_error')
            return row['driver_exit_code'] or 1
        return 2


CONFIG_DATA = read(CONFIG)
CONFIG_TARGET_CHECKS = set(CONFIG_DATA['target']['check_sites'])
CONFIG_TARGET_THROW = CONFIG_DATA['target']['throw_site']

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
