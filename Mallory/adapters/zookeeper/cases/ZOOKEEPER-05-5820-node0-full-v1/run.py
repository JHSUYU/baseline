#!/usr/bin/env python3
"""Pinned, guarded ZOOKEEPER-05 full campaign; preflight never starts a JVM."""

from __future__ import annotations

import argparse
import fcntl
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
PINS = HERE / 'pins.json'
CONFIG = HERE / 'full.json'
CORE = BASE / 'Mallory/dispatch/releases/5820a32d4af4216ee42da4c3c2e402fc52fd6746a1bd9188f3cfaaefa7cc37bf'
OUT = BASE / 'data/mallory/campaigns/ZOOKEEPER-05-5820-node0-full-v1'
ZK06 = BASE / 'data/mallory/cases/ZOOKEEPER-06'
LOCK = Path('/tmp/mallory-lanes/zookeeper-node0-source.lock')
FLOOR = 6_000_000_000
RESERVE = 300 * 1024**2
HEADROOM = 150 * 1024**2


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def write_atomic(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(row, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def free_bytes() -> int:
    stat = os.statvfs(OUT.parent)
    return stat.f_bavail * stat.f_frsize


def journal(event: str, **fields: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    row = {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'event': event, **fields}
    with (OUT / 'resource-journal.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def preflight() -> dict:
    pins = read(PINS)
    if pins['case_id'] != 'ZOOKEEPER-05' or pins['scope'] != 'node0_fresh_full_after_zk06':
        raise ValueError('wrong pin manifest')
    for row in pins['files']:
        path = Path(row['path'])
        if not path.is_file() or sha(path) != row['sha256']:
            raise ValueError(f'pinned file missing or changed: {path}')
    config = read(CONFIG)
    assert config['case_id'] == 'ZOOKEEPER-05'
    assert config['calibration_only'] is False
    assert config['auto_promote_if_healthy'] is True
    assert config['budget']['trials'] == 80
    assert config['budget']['seconds'] == 3600
    assert config['budget']['max_faults_per_trial'] == 6
    assert config['target']['check_sites'] == ['org.apache.zookeeper.server.quorum.Follower#followLeader()V@99:branch:2']
    assert config['target']['throw_site'] == 'org.apache.zookeeper.server.quorum.Follower#followLeader()V@104:throw:1'
    assert config['target']['exception_class'] == 'java.io.IOException'
    assert config['core_release'] == str(CORE)
    env = os.environ.copy()
    env['PYTHONPATH'] = f'{CORE}:{BASE}'
    subprocess.run([sys.executable, str(BASE / 'Mallory/adapters/zookeeper/verify_lane2_campaign.py'),
                    str(CONFIG)], cwd=BASE, env=env, check=True)
    subprocess.run([sys.executable, str(BASE / 'Mallory/dispatch/core_release.py'),
                    '--verify', str(CORE / 'manifest.json')], cwd=BASE, env=env,
                   check=True, stdout=subprocess.DEVNULL)
    return {'schema_version': 1, 'case_id': 'ZOOKEEPER-05',
            'status': 'passed_no_jvm', 'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'pins_sha256': sha(PINS), 'config_sha256': sha(CONFIG),
            'core_manifest_sha256': sha(CORE / 'manifest.json'),
            'free_bytes': free_bytes(), 'required_free_bytes': FLOOR + RESERVE,
            'output': str(OUT)}


def source_preflight() -> dict:
    """Check the recorded overlay and identify exact compiled artifacts still needed."""
    config = read(CONFIG)
    receipt = read(Path(config['source_overlay_receipt']))
    root = Path(receipt['patched_root'])
    if root != Path(config['cwd']):
        raise ValueError('restored source path differs from pilot overlay')
    if sha(Path(receipt['patch_file'])) != receipt['patch_sha256']:
        raise ValueError('overlay patch SHA mismatch')
    for group in ('modified_files', 'test_sources'):
        for relative, expected in receipt[group].items():
            path = root / relative
            if not path.is_file() or sha(path) != expected:
                raise ValueError(f'overlay {group} SHA mismatch: {path}')
    pending = []
    for row in receipt['compiled_artifacts']:
        path = Path(row['path'])
        if not path.is_file() or sha(path) != row['sha256']:
            pending.append(str(path))
    return {'schema_version': 1, 'case_id': 'ZOOKEEPER-05',
            'status': 'source_verified_compiled_pending' if pending else 'source_and_classes_verified',
            'modified_source_files_verified': len(receipt['modified_files']),
            'test_source_files_verified': len(receipt['test_sources']),
            'compiled_artifacts_verified': len(receipt['compiled_artifacts']) - len(pending),
            'compiled_artifacts_pending': pending,
            'pins_sha256': sha(PINS), 'config_sha256': sha(CONFIG),
            'free_bytes': free_bytes()}


def build_missing() -> None:
    stage = source_preflight()
    if not stage['compiled_artifacts_pending']:
        return
    if free_bytes() < FLOOR + RESERVE:
        raise RuntimeError('disk admission failed before pinned artifact restoration')
    journal('pinned_artifact_build_start', pending=stage['compiled_artifacts_pending'],
            free_bytes=free_bytes())
    with (OUT / 'pinned-artifact-build.log').open('ab') as log:
        build = subprocess.Popen(['mvn', '-o', '-pl', 'zookeeper-server', '-am',
                                  '-DskipTests', 'compile'], cwd=Path(read(CONFIG)['cwd']),
                                 stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        while build.poll() is None:
            if free_bytes() < FLOOR + HEADROOM:
                journal('pinned_artifact_build_disk_stop', free_bytes=free_bytes(),
                        floor_bytes=FLOOR)
                if os.getpgid(build.pid) == build.pid:
                    os.killpg(build.pid, signal.SIGTERM)
                break
            time.sleep(5)
        build_code = build.wait()
    journal('pinned_artifact_build_exit', exit_code=build_code,
            free_bytes=free_bytes())
    if build_code:
        raise RuntimeError(f'pinned artifact build failed: {build_code}')
    after = source_preflight()
    if after['compiled_artifacts_pending']:
        raise RuntimeError('rebuilt artifact SHA differs from pilot pins: ' +
                           ', '.join(after['compiled_artifacts_pending']))


def build_only() -> None:
    if os.environ.get('MALLORY_ZK05_BUILD_GO') != '1':
        raise RuntimeError('build GO gate absent: MALLORY_ZK05_BUILD_GO=1')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        terminal_zk06()
        if (OUT / 'checkpoint.json').exists():
            raise RuntimeError('campaign checkpoint already exists; build-only is closed')
        OUT.mkdir(parents=True, exist_ok=True)
        build_missing()
        receipt = preflight()
        write_atomic(OUT / 'preflight.json', receipt)
        journal('build_only_preflight_passed', free_bytes=free_bytes(),
                pins_sha256=receipt['pins_sha256'])
        print(json.dumps(receipt, sort_keys=True))


def terminal_zk06() -> None:
    result_path = ZK06 / 'result.json'
    exit_path = ZK06 / 'attempts'
    if not result_path.is_file():
        raise RuntimeError('ZOOKEEPER-06 has no campaign result')
    result = read(result_path)
    if result.get('status') not in {'budget_exhausted', 'queue_exhausted'}:
        raise RuntimeError(f"ZOOKEEPER-06 is not terminal: {result.get('status')}")
    exit_rows = sorted(exit_path.glob('*.exit.json'))
    if not exit_rows or read(exit_rows[-1]).get('exit_code') != 0:
        raise RuntimeError('ZOOKEEPER-06 has no successful terminal driver exit')


def terminate(process: subprocess.Popen) -> None:
    checkpoint = OUT / 'checkpoint.json'
    state = read(checkpoint) if checkpoint.is_file() else {}
    child = (state.get('running') or {}).get('pid')
    journal('emergency_disk_stop', free_bytes=free_bytes(), floor_bytes=FLOOR,
            checkpoint_sha256=sha(checkpoint) if checkpoint.is_file() else None,
            trial_process_group=child)
    if process.poll() is None and os.getpgid(process.pid) == process.pid:
        os.killpg(process.pid, signal.SIGTERM)
    if isinstance(child, int) and child > 0:
        try:
            if os.getpgid(child) == child:
                os.killpg(child, signal.SIGTERM)
        except ProcessLookupError:
            pass


def collect(exit_code: int) -> None:
    result_path = OUT / 'result.json'
    result = read(result_path) if result_path.is_file() else {}
    names = {'pins': PINS, 'config': CONFIG, 'pilot_result': BASE / 'data/mallory/pilot_core5820/ZOOKEEPER-05/result.json',
             'checkpoint': OUT / 'checkpoint.json', 'result': result_path,
             'offline_audit': OUT / 'offline-causal-audit.json',
             'journal': OUT / 'resource-journal.jsonl', 'driver_exit': OUT / 'driver-exit.json'}
    trials = []
    for path in sorted((OUT / 'trials').glob('r[0-9][0-9][0-9][0-9]/result.json')):
        row = read(path)
        evidence = row.get('events_evidence') or {}
        name = evidence.get('gzip_path') or evidence.get('raw_path')
        expected = evidence.get('gzip_sha256') or evidence.get('raw_sha256')
        if not isinstance(name, str) or Path(name).name != name or not expected:
            raise ValueError(f'invalid trace evidence: {path}')
        trace = path.parent / name
        if sha(trace) != expected:
            raise ValueError(f'trace SHA mismatch: {trace}')
        trials.append({'trial': path.parent.name, 'result_sha256': sha(path),
                       'trace': name, 'trace_sha256': expected})
    write_atomic(OUT / 'collection-receipt.json', {
        'schema_version': 1, 'case_id': 'ZOOKEEPER-05', 'scope': 'fresh_full_80_fault_trials',
        'exit_code': exit_code, 'campaign_status': result.get('status'),
        'fault_trials_completed': result.get('fault_trials_completed'),
        'free_bytes': free_bytes(), 'files': {
            key: {'path': str(path), 'sha256': sha(path)} for key, path in names.items()
            if path.is_file()}, 'trials': trials})


def run(resume: bool) -> int:
    if os.environ.get('MALLORY_ZK05_NODE0_GO') != '1':
        raise RuntimeError('dispatch GO gate absent: MALLORY_ZK05_NODE0_GO=1')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as locked:
        fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
        terminal_zk06()
        if not resume:
            if (OUT / 'checkpoint.json').exists():
                raise FileExistsError(f'fresh campaign checkpoint already exists: {OUT}')
            OUT.mkdir(parents=True, exist_ok=True)
            build_missing()
        receipt = preflight()
        if free_bytes() < FLOOR + RESERVE:
            raise RuntimeError('disk admission failed: below 6.0 GB floor + 300 MiB reserve')
        if resume:
            if not (OUT / 'checkpoint.json').is_file():
                raise RuntimeError('resume needs prior checkpoint')
            if sha(OUT / 'config.json') != sha(CONFIG):
                raise RuntimeError('resume config differs from pinned config')
            if read(OUT / 'checkpoint.json').get('status') != 'running':
                raise RuntimeError('resume requires running checkpoint')
        OUT.mkdir(parents=True, exist_ok=True)
        write_atomic(OUT / 'preflight.json', receipt)
        journal('admission', free_bytes=free_bytes(), required_free_bytes=FLOOR + RESERVE,
                pins_sha256=receipt['pins_sha256'], resume=resume)
        env = os.environ.copy()
        env['PYTHONPATH'] = f'{CORE}:{BASE}'
        env['MALLORY_CORE_RELEASE_ID'] = CORE.name
        env['MALLORY_ATTEMPT_ID'] = 'zk05-node0-full-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        with (OUT / 'driver.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-m', 'Mallory.core.campaign',
                                        '--config', str(CONFIG), '--out', str(OUT)],
                                       cwd=CORE, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            journal('campaign_start', pid=process.pid, attempt_id=env['MALLORY_ATTEMPT_ID'])
            last_sample = 0.0
            while process.poll() is None:
                now = time.monotonic()
                free = free_bytes()
                if now - last_sample >= 30:
                    journal('disk_sample', free_bytes=free,
                            checkpoint_sha256=sha(OUT / 'checkpoint.json')
                            if (OUT / 'checkpoint.json').is_file() else None)
                    last_sample = now
                if free < FLOOR + HEADROOM:
                    terminate(process)
                    break
                time.sleep(5)
            code = process.wait()
        write_atomic(OUT / 'driver-exit.json', {'started_utc': started,
                     'finished_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                     'exit_code': code, 'attempt_id': env['MALLORY_ATTEMPT_ID']})
        journal('campaign_exit', exit_code=code, free_bytes=free_bytes())
        if (OUT / 'result.json').is_file():
            with (OUT / 'offline-audit.log').open('wb') as log:
                audit = subprocess.run([sys.executable, '-m', 'Mallory.core.audit',
                                        '--campaign', str(OUT), '--out',
                                        str(OUT / 'offline-causal-audit.json')],
                                       cwd=CORE, env=env, stdout=log, stderr=subprocess.STDOUT)
            journal('offline_audit', exit_code=audit.returncode)
        collect(code)
        result = read(OUT / 'result.json') if (OUT / 'result.json').is_file() else {}
        if code == 0 and result.get('status') in {'budget_exhausted', 'queue_exhausted'}:
            print(json.dumps({'status': result['status'],
                              'fault_trials_completed': result['fault_trials_completed'],
                              'output': str(OUT)}, sort_keys=True))
            return 0
        return code or 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--source-preflight', action='store_true')
    parser.add_argument('--build-only', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.preflight and not args.run and not args.resume:
        print(json.dumps(preflight(), sort_keys=True))
    elif args.source_preflight and not args.preflight and not args.run and not args.resume:
        print(json.dumps(source_preflight(), sort_keys=True))
    elif args.build_only and not args.preflight and not args.source_preflight and not args.run and not args.resume:
        build_only()
    elif args.run != args.resume:
        raise SystemExit(run(resume=args.resume))
    else:
        parser.error('choose exactly one of --preflight, --run, --resume')
