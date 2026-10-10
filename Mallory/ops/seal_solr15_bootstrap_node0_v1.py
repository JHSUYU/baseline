#!/usr/bin/env python3
"""SHA-seal SOLR-15's terminal same-parent bootstrap selection gap."""

from __future__ import annotations

from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
PACKAGE = BASE / 'Mallory/adapters/solr/cases/SOLR-15/fault-bootstrap-node0-v1'
RAW = BASE / 'data/mallory/solr15_fault_bootstrap_node0_v1'
RELEASE = BASE / 'Mallory/dispatch/releases/815cba9b-target-absent-v1'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-15-fault-bootstrap-node0-v1'
ARCHIVE = ARCHIVES / f'{PREFIX}.tar.gz'
MEMBERS = ARCHIVES / f'{PREFIX}.members.json'
RECEIPT = ARCHIVES / f'{PREFIX}.receipt.json'
DEPTH = RAW / 'fault-depth-review.json'
QUALITY = RAW / 'terminal-quality.json'
LOCK = Path('/tmp/mallory-lanes/solr-node0-v1.lock')
FLOOR = 7_650_410_496
sys.path.insert(0, str(PACKAGE))
import seed_selector as seed  # noqa: E402


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
    if path.exists():
        if read(path) != value:
            raise RuntimeError(f'existing sidecar differs: {path}')
        return
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def attest() -> tuple[dict, dict, dict]:
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    config = read(RAW / 'config.json')
    admission = read(PACKAGE / 'admission-full-node0.json')
    release = read(RELEASE / 'manifest.json')
    if (result.get('case_id') != 'SOLR-15'
            or result.get('status') != 'fault_resource_mismatch'
            or checkpoint.get('status') != 'fault_resource_mismatch'
            or checkpoint.get('completed_trials') != [0, 1]
            or checkpoint.get('running') is not None
            or result.get('fault_trials_completed') != 1
            or result.get('strict_injected_trials') != 0
            or result.get('target_reached_trials') != 0
            or result.get('exact_exception_trials') != 0
            or result.get('target_discovered_trial') is not None
            or result.get('new_bug') is True
            or result.get('target_exception_candidate_trials') != []
            or result.get('reproduced_candidates') != []
            or result.get('healthy_junit_validation', {}).get('status') != 'passed'
            or config != read(PACKAGE / 'config-full-node0.json')
            or admission.get('go') is not True
            or admission.get('host') != 'node0'
            or admission.get('mode') != 'full'
            or admission.get('case_id') != 'SOLR-15'
            or admission.get('intended_output') != str(RAW)
            or admission.get('config_sha256') != sha(PACKAGE / 'config-full-node0.json')
            or admission.get('runner_sha256') != sha(PACKAGE / 'run_campaign.py')
            or not release.get('files')
            or any(sha(RELEASE / name) != digest
                   for name, digest in release['files'].items())):
        raise RuntimeError('SOLR-15 terminal result, config, release, or GO mismatch')
    trials = []
    for number in (0, 1):
        root = RAW / 'trials' / f'r{number:04d}'
        trial = read(root / 'result.json')
        pilot = read(root / 'pilot-result.json')
        plan = trial.get('plan')
        evidence = trial.get('events_evidence') or {}
        trace = root / evidence.get('gzip_path', '')
        junit = trial.get('junit_validation') or {}
        if (trial.get('trial_id') != number
                or not isinstance(plan, list) or len(plan) != number
                or trial.get('return_code') != 0 or trial.get('timed_out') is not False
                or junit.get('status') != 'passed'
                or (junit.get('tests'), junit.get('failures'), junit.get('errors')) != (1, 0, 0)
                or junit.get('junit_log_sha256') != sha(root / 'junit.log')
                or pilot.get('exit_code') != 0
                or pilot.get('target_check_count') != 0
                or pilot.get('target_throw_count') != 0
                or evidence.get('gzip_sha256') != sha(trace)
                or trial.get('feedback', {}).get('target_reached') is not False
                or trial['feedback'].get('target_threw') is not False):
            raise RuntimeError(f'trial or evidence mismatch: r{number:04d}')
        trials.append(trial)
    healthy, fault = trials
    fresh_second = seed.second_lookup(RAW / 'trials/r0001')
    plan = fault['plan'][0]
    receipts = [event for event in seed.events(RAW / 'trials/r0001')
                if event.get('fault_id') == plan['fault_id']
                and event.get('type') in ('FAULT_MATCHED', 'FAULT_APPLIED')]
    matched = next((event for event in receipts if event['type'] == 'FAULT_MATCHED'), None)
    applied = next((event for event in receipts if event['type'] == 'FAULT_APPLIED'), None)
    if (healthy['feedback']['status'] != 'healthy_target_missing'
            or fault['feedback']['status'] != 'fault_resource_mismatch'
            or fault['feedback']['all_faults_effective'] is not False
            or fault.get('resource_attestation') != {
                'valid': False,
                'reason': 'fault applied to a different live-node path or actor'}
            or len(receipts) != 2 or matched is None or applied is None
            or matched.get('resource') != '/overseer/queue'
            or applied.get('resource') != '/overseer/queue'
            or matched.get('door_ordinal') != 42
            or applied.get('door_ordinal') != 42
            or applied.get('seq') != matched.get('seq') + 1
            or fresh_second.get('resource') != '/live_nodes/127.0.0.1:42553_'
            or fresh_second.get('door_ordinal') != 47
            or fresh_second.get('id') != 'SOLR-15-r0001:1898'
            or plan.get('expected_resource_role') != 'parent_leader_znode'
            or plan.get('point', {}).get('door_ordinal') != 42):
        raise RuntimeError('SOLR-15 fault path mismatch evidence differs')
    depth = {'schema_version': 1, 'case_id': 'SOLR-15',
             'scope': 'fault_plan_depth_and_controller_provenance',
             'status': result['status'], 'fault_trials_completed': 1,
             'campaign_result_sha256': sha(RAW / 'result.json'),
             'campaign_checkpoint_sha256': sha(RAW / 'checkpoint.json'),
             'controller_release_id': RELEASE.name,
             'controller_release_manifest_sha256': sha(RELEASE / 'manifest.json'),
             'scheduler_sha256': sha(RELEASE / 'Mallory/core/scheduler.py'),
             'depth_distribution': {'1': 1},
             'trials': [{'trial_id': 1, 'depth': 1,
                         'result_sha256': sha(RAW / 'trials/r0001/result.json')}]}
    quality = {'schema_version': 1, 'case_id': 'SOLR-15',
               'scope': 'same_parent_fault_bootstrap_full_v1',
               'status': result['status'], 'duration_seconds': result['duration_seconds'],
               'fault_trials_completed': 1, 'matched_and_applied_trials': 1,
               'strict_resource_valid_trials': 0, 'strict_target_trials': 0,
               'exact_exception_trials': 0, 'target_discovered': False,
               'fresh_second_native_event_id': fresh_second['id'],
               'fresh_second_ordinal': fresh_second['door_ordinal'],
               'fresh_second_resource': fresh_second['resource'],
               'applied_ordinal': applied['door_ordinal'],
               'applied_resource': applied['resource'],
               'resource_attestation_valid': False,
               'selection_gap': 'cross_trial_native_ordinal_drift',
               'plan_depth_distribution': {'1': 1},
               'campaign_completion_credited': False, 'new_bug': False}
    return result, depth, quality


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT)):
        raise FileExistsError('SOLR-15 bootstrap seal already exists')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, depth, quality = attest()
        write(DEPTH, depth)
        write(QUALITY, quality)
        files = sorted(path for path in RAW.rglob('*')
                       if path.is_file() and path.name != '.campaign.lock')
        if not files or any(path.is_symlink() for path in files):
            raise RuntimeError('raw campaign empty or symlinked')
        prefix = 'solr15_fault_bootstrap_node0_v1/'
        members = [{'path': prefix + path.relative_to(RAW).as_posix(),
                    'bytes': path.stat().st_size, 'sha256': sha(path)} for path in files]
        allocated = sum(path.stat().st_blocks * 512 for path in files)
        if shutil.disk_usage(BASE).free < FLOOR + 2 * allocated + 100 * 1024**2:
            raise RuntimeError('archive may breach node0 disk reserve')
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
                    digest = hashlib.sha256()
                    with archive.extractfile(item) as stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(block)
                    if not item.isfile() or item.size != row['bytes'] or digest.hexdigest() != row['sha256']:
                        raise RuntimeError('archive member size or SHA mismatch')
            if sha(RAW / 'result.json') != depth['campaign_result_sha256'] or shutil.disk_usage(BASE).free < FLOOR:
                raise RuntimeError('result changed or disk reserve breached')
            os.replace(temporary, ARCHIVE)
        finally:
            temporary.unlink(missing_ok=True)
        write(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-15',
                        'raw_root': str(RAW), 'member_count': len(members),
                        'members': members, 'archive_sha256': sha(ARCHIVE),
                        'result_sha256': depth['campaign_result_sha256']})
        receipt = {**quality, 'archive_sha256': sha(ARCHIVE),
                   'member_manifest_sha256': sha(MEMBERS), 'member_count': len(members),
                   'result_sha256': sha(RAW / 'result.json'),
                   'checkpoint_sha256': sha(RAW / 'checkpoint.json'),
                   'depth_review_sha256': sha(DEPTH),
                   'quality_sidecar_sha256': sha(QUALITY),
                   'admission_receipt_sha256': sha(PACKAGE / 'admission-full-node0.json'),
                   'package_config_sha256': sha(PACKAGE / 'config-full-node0.json'),
                   'package_runner_sha256': sha(PACKAGE / 'run_campaign.py'),
                   'all_archive_members_verified': True}
        write(RECEIPT, receipt)
        return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
