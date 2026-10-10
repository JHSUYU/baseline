#!/usr/bin/env python3
"""Seal a naturally terminal ZK13 attempt and publish a compact case result."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
OUT = BASE / 'data/mallory/campaigns/ZOOKEEPER-13-connectpath-retry-full-v1'
CASE = BASE / 'data/mallory/cases/ZOOKEEPER-13'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
ARCHIVE = ARCHIVES / 'ZOOKEEPER-13-connectpath-retry-full-v1.tar.gz'
MANIFEST = ARCHIVES / 'ZOOKEEPER-13-connectpath-retry-full-v1.manifest.json'
LOCK = Path('/tmp/mallory-lanes/zookeeper-node0-source.lock')
RELEASE = BASE / 'Mallory/dispatch/releases/29ab038f754e3df6f38f94f38cee052b82b9601f255f347322fa422b45350fbc'
CONFIG = BASE / 'Mallory/adapters/zookeeper/cases/ZOOKEEPER-13-connectpath-retry-full-v1/full.json'
PINS = CONFIG.with_name('pins.json')
TERMINAL = {'budget_exhausted', 'queue_exhausted'}
FLOOR = 6_000_000_000
HEADROOM = 300 * 1024**2


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def terminal_attempt() -> tuple[Path, dict]:
    candidates = []
    for attempt in sorted((OUT / 'attempts').glob('a[0-9][0-9]')):
        result_path = attempt / 'result.json'
        if result_path.is_file():
            result = read(result_path)
            if result.get('status') in TERMINAL:
                candidates.append((attempt, result))
    if len(candidates) != 1:
        raise RuntimeError(f'expected one natural full terminal, found {len(candidates)}')
    attempt, result = candidates[0]
    checkpoint = read(attempt / 'checkpoint.json')
    healthy = read(attempt / 'trials/r0000/result.json')
    if (result.get('case_id') != 'ZOOKEEPER-13' or
            result.get('calibration_only') is not False or
            result.get('healthy_seed_valid') is not True or
            result.get('healthy_junit_validation', {}).get('status') != 'passed' or
            checkpoint.get('status') != result['status'] or
            checkpoint.get('running') is not None or
            len(checkpoint.get('completed_trials', [])) !=
            1 + result.get('fault_trials_completed', -2) or
            healthy.get('junit_validation', {}).get('status') != 'passed' or
            read(attempt / 'config.json') != read(CONFIG)):
        raise RuntimeError('ZK13 result, checkpoint, healthy seed, or config mismatch')
    return attempt, result


def ensure_audit(attempt: Path) -> tuple[str, int]:
    audit_path = attempt / 'offline-causal-audit.json'
    if not audit_path.is_file():
        env = dict(os.environ)
        env['PYTHONPATH'] = f'{RELEASE}:{BASE}'
        audit = subprocess.run(
            [sys.executable, '-m', 'Mallory.core.audit', '--campaign', str(attempt),
             '--out', str(audit_path)], cwd=BASE, env=env,
            capture_output=True, text=True)
        write(attempt / 'terminal-audit-execution.json', {
            'exit_code': audit.returncode, 'stdout': audit.stdout,
            'stderr': audit.stderr, 'result_sha256': sha(attempt / 'result.json')})
        if audit.returncode not in (0, 2):
            raise RuntimeError(f'frozen audit failed: {audit.stderr[-500:]}')
        exit_code = audit.returncode
    else:
        exit_code = read(attempt / 'terminal-audit-execution.json').get('exit_code', 0) \
            if (attempt / 'terminal-audit-execution.json').is_file() else 0
    if read(audit_path).get('campaign_result_sha256') != sha(attempt / 'result.json'):
        raise RuntimeError('ZK13 audit is not bound to terminal result')
    return sha(audit_path), exit_code


def source_members() -> list[dict]:
    members = []
    for path in sorted(OUT.rglob('*')):
        if path.is_symlink():
            raise RuntimeError(f'symlink in ZK13 evidence tree: {path}')
        if path.is_file():
            members.append({'path': path.relative_to(BASE / 'data/mallory').as_posix(),
                            'bytes': path.stat().st_size, 'sha256': sha(path)})
    if not members:
        raise RuntimeError('ZK13 raw evidence tree is empty')
    return members


def seal() -> dict:
    if CASE.exists():
        receipt = read(CASE / 'terminal-seal.json')
        if (receipt.get('case_id') == 'ZOOKEEPER-13' and
                receipt.get('archive_sha256') == sha(ARCHIVE) and
                receipt.get('archive_manifest_sha256') == sha(MANIFEST) and
                receipt.get('result_sha256') == sha(CASE / 'result.json')):
            return receipt
        raise RuntimeError('existing ZK13 canonical evidence fails SHA seal')
    with LOCK.open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        attempt, result = terminal_attempt()
        audit_sha, audit_exit = ensure_audit(attempt)
        members = source_members()
        raw_bytes = sum(item['bytes'] for item in members)
        if shutil.disk_usage(BASE).free < FLOOR + raw_bytes + HEADROOM:
            raise RuntimeError('ZK13 archive would breach node0 disk reserve')
        ARCHIVES.mkdir(parents=True, exist_ok=True)
        if ARCHIVE.exists() != MANIFEST.exists():
            raise RuntimeError('partial ZK13 archive publication needs review')
        if not ARCHIVE.exists():
            temporary = ARCHIVE.with_name(ARCHIVE.name + '.tmp')
            with tarfile.open(temporary, 'w:gz') as archive:
                for item in members:
                    archive.add(BASE / 'data/mallory' / item['path'],
                                arcname=item['path'], recursive=False)
            os.replace(temporary, ARCHIVE)
        with tarfile.open(ARCHIVE, 'r:gz') as archive:
            packed = archive.getmembers()
            if [item.name for item in packed] != [item['path'] for item in members]:
                raise RuntimeError('ZK13 archive member list differs from raw')
            for item, expected in zip(packed, members):
                if not item.isfile() or item.size != expected['bytes']:
                    raise RuntimeError('ZK13 archive member size differs from raw')
                stream = archive.extractfile(item)
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
                if digest.hexdigest() != expected['sha256']:
                    raise RuntimeError('ZK13 archive member hash differs from raw')
        manifest = {'schema_version': 1, 'case_id': 'ZOOKEEPER-13',
                    'raw_root': str(OUT), 'member_count': len(members),
                    'logical_bytes': raw_bytes, 'members': members,
                    'archive_sha256': sha(ARCHIVE)}
        if MANIFEST.exists() and read(MANIFEST) != manifest:
            raise RuntimeError('existing ZK13 manifest differs from terminal raw')
        if not MANIFEST.exists():
            write(MANIFEST, manifest)
        staged = CASE.with_name('.ZOOKEEPER-13.import')
        staged.mkdir(parents=True, exist_ok=False)
        for name in ('config.json', 'result.json', 'checkpoint.json',
                     'offline-causal-audit.json'):
            shutil.copy2(attempt / name, staged / name)
        ledger = OUT / 'admission-ledger.json'
        if ledger.is_file():
            shutil.copy2(ledger, staged / ledger.name)
        receipt = {
            'schema_version': 1, 'case_id': 'ZOOKEEPER-13',
            'status': result['status'], 'fault_trials_completed': result['fault_trials_completed'],
            'duration_seconds': result.get('duration_seconds'),
            'exact_exception_trials': result.get('exact_exception_trials'),
            'attempt': attempt.name, 'config_sha256': sha(staged / 'config.json'),
            'result_sha256': sha(staged / 'result.json'),
            'checkpoint_sha256': sha(staged / 'checkpoint.json'),
            'audit_sha256': audit_sha, 'audit_exit_code': audit_exit,
            'archive_path': str(ARCHIVE), 'archive_sha256': sha(ARCHIVE),
            'archive_manifest_path': str(MANIFEST), 'archive_manifest_sha256': sha(MANIFEST),
            'archive_members': len(members), 'runner_config_sha256': sha(CONFIG),
            'runner_pins_sha256': sha(PINS), 'raw_root': str(OUT)}
        write(staged / 'terminal-seal.json', receipt)
        os.replace(staged, CASE)
        return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seal', action='store_true', required=True)
    parser.parse_args()
    print(json.dumps(seal(), sort_keys=True))
