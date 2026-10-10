#!/usr/bin/env python3
"""SHA-seal a naturally terminal ZK11 campaign and import compact evidence."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
RAW = BASE / 'data/mallory/campaigns/ZOOKEEPER-11-epoch-full-v2'
CASE = BASE / 'data/mallory/cases/ZOOKEEPER-11'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'ZOOKEEPER-11-epoch-full-v2'
ARCHIVE = ARCHIVES / (PREFIX + '.tar.gz')
MANIFEST = ARCHIVES / (PREFIX + '.members.json')
RECEIPT = ARCHIVES / (PREFIX + '.receipt.json')
CONFIG = BASE / 'Mallory/adapters/zookeeper/cases/ZOOKEEPER-11-epoch-full-v2/full.json'
PINS = CONFIG.with_name('pins.json')
CONTROLLER = CONFIG.with_name('controller-release.json')
LAUNCH = BASE / 'data/mallory/dispatch/node0-zk11-v2-launch.json'
LOCK = Path('/tmp/mallory-lanes/zookeeper-node0-source.lock')
TERMINAL = {'budget_exhausted', 'queue_exhausted'}
FLOOR = 6_000_000_000
HEADROOM = 300 * 1024**2


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def verify_raw() -> tuple[dict, dict, dict[str, int]]:
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    collection = read(RAW / 'collection-receipt.json')
    audit = read(RAW / 'offline-causal-audit.json')
    driver = read(RAW / 'driver-exit.json')
    audit_sha = sha(RAW / 'offline-causal-audit.json')
    audit_quality_failure = (
        audit.get('report_gate_passed') is False
        and audit.get('same_actor_target_required') is True
        and audit.get('same_actor_target_gate_passed') is False
        and audit.get('same_actor_target_trials') == 0
        and all(audit.get(name) is True for name in (
            'archive_integrity_valid', 'applied_fault_identity_valid',
            'target_claims_reverified', 'guidance_consistent',
            'healthy_closure_proven'))
    )
    if (result.get('case_id') != 'ZOOKEEPER-11'
            or result.get('status') not in TERMINAL
            or checkpoint.get('status') != result['status']
            or checkpoint.get('running') is not None
            or read(RAW / 'config.json') != read(CONFIG)
            or read(CONFIG).get('multi_fault_exploration_interval') != 4
            or collection.get('case_id') != 'ZOOKEEPER-11'
            or collection.get('scope') != 'epoch_full_80_3600_max3_depth4'
            or collection.get('campaign_status') != result['status']
            or collection.get('driver_exit_code') != 0
            or driver.get('exit_code') != 0 or driver.get('low_disk_stop') is not False
            or collection.get('healthy', {}).get('valid') is not True
            or collection.get('trial_count_matches_result') is not True
            or collection.get('result_sha256') != sha(RAW / 'result.json')
            or collection.get('checkpoint_sha256') != sha(RAW / 'checkpoint.json')
            or not (collection.get('audit_sha256') == audit_sha or
                    (collection.get('audit_sha256') is None and audit_quality_failure))
            or audit.get('campaign_result_sha256') != sha(RAW / 'result.json')
            or len(checkpoint.get('completed_trials', [])) !=
            1 + result.get('fault_trials_completed', -2)
            or len(collection.get('trials', [])) !=
            1 + result.get('fault_trials_completed', -2)):
        raise RuntimeError('terminal ZK11 result, collection, audit, or runner mismatch')
    depth_distribution: dict[str, int] = {}
    for row in collection['trials']:
        directory = RAW / 'trials' / row['trial']
        trial = read(directory / 'result.json')
        evidence = trial.get('events_evidence') or {}
        trace = directory / evidence.get('gzip_path', '')
        if (not (directory / 'result.json').is_file() or
                row.get('result_sha256') != sha(directory / 'result.json') or
                not trace.is_file() or trace.parent != directory or
                row.get('trace_sha256') != sha(trace) or
                evidence.get('gzip_sha256') != row['trace_sha256']):
            raise RuntimeError(f'trial evidence SHA mismatch: {directory}')
        if row['trial'] != 'r0000':
            depth = len(read(directory / 'plan.json').get('faults', []))
            if depth < 1 or depth > read(CONFIG)['budget']['max_faults_per_trial']:
                raise RuntimeError(f'fault plan depth out of bounds: {directory}')
            key = str(depth)
            depth_distribution[key] = depth_distribution.get(key, 0) + 1
    if sum(depth_distribution.values()) != result['fault_trials_completed']:
        raise RuntimeError('fault plan depth count differs from terminal result')
    return result, collection, depth_distribution


def seal() -> dict:
    if any(path.exists() for path in (CASE, ARCHIVE, MANIFEST, RECEIPT)):
        raise FileExistsError('ZK11 terminal output already exists; verify before reusing')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, collection, depth_distribution = verify_raw()
        audit = read(RAW / 'offline-causal-audit.json')
        audit_sha = sha(RAW / 'offline-causal-audit.json')
        files = sorted(path for path in RAW.rglob('*') if path.is_file())
        if not files or any(path.is_symlink() or path.name.endswith('.tmp') for path in files):
            raise RuntimeError('raw evidence empty, temporary, or symlinked')
        members = [{'path': 'campaigns/' + PREFIX + '/' + path.relative_to(RAW).as_posix(),
                    'bytes': path.stat().st_size, 'sha256': sha(path)} for path in files]
        logical_bytes = sum(row['bytes'] for row in members)
        free = shutil.disk_usage(BASE).free
        if free < FLOOR + HEADROOM + logical_bytes:
            raise RuntimeError('ZK11 archive would breach node0 disk reserve')
        ARCHIVES.mkdir(parents=True, exist_ok=True)
        temporary = ARCHIVE.with_name(ARCHIVE.name + '.tmp')
        try:
            with tarfile.open(temporary, 'w:gz') as archive:
                for path, row in zip(files, members):
                    info = tarfile.TarInfo(row['path'])
                    info.size = row['bytes']
                    info.mode = 0o600
                    info.mtime = 0
                    with path.open('rb') as stream:
                        archive.addfile(info, stream)
            with tarfile.open(temporary, 'r:gz') as archive:
                packed = archive.getmembers()
                if [item.name for item in packed] != [row['path'] for row in members]:
                    raise RuntimeError('archive member list mismatch')
                for item, row in zip(packed, members):
                    if not item.isfile() or item.size != row['bytes']:
                        raise RuntimeError(f'archive member size mismatch: {item.name}')
                    digest = hashlib.sha256()
                    with archive.extractfile(item) as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(block)
                    if digest.hexdigest() != row['sha256']:
                        raise RuntimeError(f'archive member SHA mismatch: {item.name}')
            if sha(RAW / 'result.json') != collection['result_sha256']:
                raise RuntimeError('raw result changed during archive creation')
            os.replace(temporary, ARCHIVE)
        finally:
            temporary.unlink(missing_ok=True)
        manifest = {'schema_version': 1, 'case_id': 'ZOOKEEPER-11',
                    'raw_root': str(RAW), 'member_count': len(members),
                    'logical_bytes': logical_bytes, 'members': members,
                    'archive_sha256': sha(ARCHIVE),
                    'result_sha256': collection['result_sha256']}
        write(MANIFEST, manifest)
        receipt = {'schema_version': 1, 'case_id': 'ZOOKEEPER-11',
                   'terminal_status': result['status'], 'archive_path': str(ARCHIVE),
                   'archive_sha256': sha(ARCHIVE), 'archive_size': ARCHIVE.stat().st_size,
                   'member_manifest_path': str(MANIFEST),
                   'member_manifest_sha256': sha(MANIFEST), 'member_count': len(members),
                   'collection_receipt_sha256': sha(RAW / 'collection-receipt.json'),
                   'result_sha256': sha(RAW / 'result.json'),
                   'checkpoint_sha256': sha(RAW / 'checkpoint.json'),
                   'offline_audit_sha256': sha(RAW / 'offline-causal-audit.json'),
                   'audit_collection_sha_bound': collection.get('audit_sha256') == audit_sha,
                   'audit_report_gate_passed': audit.get('report_gate_passed'),
                   'same_actor_target_gate_passed': audit.get('same_actor_target_gate_passed'),
                   'audit_cli_exit_code_expected': 0 if audit.get('report_gate_passed') else 2,
                   'plan_depth_distribution': depth_distribution,
                   'all_archive_members_verified': True}
        write(RECEIPT, receipt)
        staged = CASE.with_name('.ZOOKEEPER-11.import')
        staged.mkdir(parents=True, exist_ok=False)
        names = ('config.json', 'result.json', 'checkpoint.json',
                 'offline-causal-audit.json', 'collection-receipt.json',
                 'driver-exit.json', 'preflight.json')
        for name in names:
            shutil.copy2(RAW / name, staged / name)
        seal_receipt = {'schema_version': 1, 'case_id': 'ZOOKEEPER-11',
                        'status': result['status'],
                        'fault_trials_completed': result['fault_trials_completed'],
                        'exact_exception_trials': result.get('exact_exception_trials'),
                        'plan_depth_distribution': depth_distribution,
                        'source_campaign': str(RAW.relative_to(BASE)),
                        'compact_files_sha256': {name: sha(staged / name) for name in names},
                        'archive_sha256': sha(ARCHIVE),
                        'member_manifest_sha256': sha(MANIFEST),
                        'archive_receipt_sha256': sha(RECEIPT),
                        'offline_audit_sha256': sha(RAW / 'offline-causal-audit.json'),
                        'audit_collection_sha_bound': collection.get('audit_sha256') ==
                        sha(RAW / 'offline-causal-audit.json'),
                        'audit_report_gate_passed': read(RAW / 'offline-causal-audit.json').get('report_gate_passed'),
                        'same_actor_target_gate_passed':
                        read(RAW / 'offline-causal-audit.json').get('same_actor_target_gate_passed'),
                        'audit_cli_exit_code_expected': 0 if
                        read(RAW / 'offline-causal-audit.json').get('report_gate_passed') else 2,
                        'runner_config_sha256': sha(CONFIG),
                        'runner_pins_sha256': sha(PINS),
                        'controller_release_receipt_sha256': sha(CONTROLLER),
                        'launch_receipt_sha256': sha(LAUNCH),
                        'core_manifest_sha256':
                        sha(Path(read(CONFIG)['core_release']) / 'manifest.json'),
                        'multi_fault_exploration_interval': 4}
        write(staged / 'terminal-seal.json', seal_receipt)
        os.replace(staged, CASE)
        return seal_receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
