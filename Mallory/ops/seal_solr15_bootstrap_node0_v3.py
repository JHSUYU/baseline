#!/usr/bin/env python3
"""Attest and SHA-seal the terminal SOLR-15 v3 bounded continuation."""

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
PACKAGE = BASE / 'Mallory/adapters/solr/cases/SOLR-15/fault-bootstrap-node0-v3'
RAW = BASE / 'data/mallory/solr15_fault_bootstrap_node0_v3'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-15-fault-bootstrap-node0-v3'
ARCHIVE = ARCHIVES / f'{PREFIX}.tar.gz'
MEMBERS = ARCHIVES / f'{PREFIX}.members.json'
RECEIPT = ARCHIVES / f'{PREFIX}.receipt.json'
QUALITY = RAW / 'terminal-quality.json'
DEPTH = RAW / 'fault-depth-review.json'
LOCK = Path('/tmp/mallory-lanes/solr-node0-v1.lock')
FLOOR = 7_650_410_496
sys.path.insert(0, str(PACKAGE))
import run_campaign as runner  # noqa: E402
import audit_trial  # noqa: E402


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write_once(path: Path, value: dict) -> None:
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
    metadata = runner.preflight()
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    admission = read(PACKAGE / 'admission-full-node0.json')
    if not (result.get('case_id') == checkpoint.get('case_id') == 'SOLR-15'
            and result.get('status') == checkpoint.get('status')
            and result['status'] in {'budget_exhausted', 'queue_exhausted'}
            and checkpoint.get('running') is None
            and read(RAW / 'config.json') == read(PACKAGE / 'config-full-node0.json')
            and admission.get('go') is True and admission.get('host') == 'node0'
            and admission.get('mode') == 'full' and admission.get('case_id') == 'SOLR-15'
            and admission.get('intended_output') == str(RAW)
            and admission.get('config_sha256') == metadata['config_sha256']
            and admission.get('runner_sha256') == metadata['runner_sha256']
            and admission.get('agent_sha256') == metadata['agent_sha256']
            and result.get('new_bug') is not True):
        raise RuntimeError('terminal status, config, or admission mismatch')

    completed = checkpoint['completed_trials']
    if completed != list(range(len(completed))) or completed[:5] != list(range(5)):
        raise RuntimeError('completed trial sequence changed')
    dropped = {row['trial_id']: row for row in checkpoint.get('dropped_trials', [])}
    if 4 not in dropped or 4 in checkpoint.get('target_exception_candidates', []):
        raise RuntimeError('v2 invalid r0004 was credited')
    trials = []
    depths = Counter()
    statuses = Counter()
    valid_new = []
    dropped_new = []
    for number in completed:
        root = RAW / 'trials' / f'r{number:04d}'
        trial = read(root / 'result.json')
        feedback = trial['feedback']
        evidence = trial['events_evidence']
        junit = trial['junit_validation']
        if not (trial.get('trial_id') == number
                and isinstance(trial.get('plan'), list)
                and trial.get('return_code') == 0
                and trial.get('timed_out') is False
                and junit.get('status') == 'passed'
                and (junit.get('tests'), junit.get('failures'),
                     junit.get('errors'), junit.get('skipped')) == (1, 0, 0, 0)
                and junit.get('junit_log_sha256') == sha(root / 'junit.log')
                and evidence.get('gzip_sha256') == sha(root / evidence['gzip_path'])):
            raise RuntimeError(f'r{number:04d} result, JUnit, or trace mismatch')
        if number:
            depths[str(len(trial['plan']))] += 1
            statuses[feedback['status']] += 1
        if number >= 5:
            original = root / 'raw-result.json'
            if not original.is_file():
                raise RuntimeError(f'r{number:04d} original result missing')
            if trial.get('resource_attestation', {}).get('valid') is True:
                expected = audit_trial.attest(root, trial['plan'])
                if trial['resource_attestation'] != expected or feedback.get('all_faults_effective') is not True:
                    raise RuntimeError(f'r{number:04d} resource attestation changed')
                valid_new.append(number)
            else:
                if (not trial.get('dropped_no_credit')
                        or trial['dropped_no_credit'].get('raw_result_sha256') != sha(original)
                        or number not in dropped
                        or feedback.get('status') != 'dropped_invalid_depth_three'
                        or feedback.get('target_exception_candidate') is not False):
                    raise RuntimeError(f'r{number:04d} unqualified trial was credited')
                dropped_new.append(number)
        trials.append({'trial_id': number, 'depth': len(trial['plan']),
                       'feedback_status': feedback['status'],
                       'junit_status': junit['status'],
                       'resource_valid': trial.get('resource_attestation', {}).get('valid'),
                       'result_sha256': sha(root / 'result.json'),
                       'trace_sha256': sha(root / evidence['gzip_path'])})

    candidates = checkpoint.get('target_exception_candidates', [])
    if (sorted(candidates) != sorted(result.get('target_exception_candidate_trials', []))
            or not set(candidates).issubset({2, 3, *valid_new})
            or any(number not in candidates for number in (2, 3))):
        raise RuntimeError('strict candidate accounting mismatch')
    for number in candidates:
        feedback = read(RAW / 'trials' / f'r{number:04d}/result.json')['feedback']
        if not (feedback.get('target_exception_candidate') is True
                and feedback.get('target_threw') is True
                and feedback.get('all_faults_effective') is True):
            raise RuntimeError(f'r{number:04d} candidate is not strict')

    depth = {'schema_version': 1, 'case_id': 'SOLR-15',
             'scope': 'v2_replay_seeded_v3_fault_depth',
             'status': result['status'],
             'controller_release_id': runner.RELEASE.name,
             'controller_release_manifest_sha256': sha(runner.RELEASE / 'manifest.json'),
             'scheduler_sha256': sha(runner.RELEASE / 'Mallory/core/scheduler.py'),
             'campaign_result_sha256': sha(RAW / 'result.json'),
             'campaign_checkpoint_sha256': sha(RAW / 'checkpoint.json'),
             'depth_distribution': dict(depths), 'feedback_status_distribution': dict(statuses),
             'trials': trials}
    quality = {'schema_version': 1, 'case_id': 'SOLR-15',
               'scope': 'resource_qualified_depth_three_continuation_v3',
               'status': result['status'],
               'duration_seconds': result['duration_seconds'],
               'fault_trials_completed': result['fault_trials_completed'],
               'strict_candidate_trials': candidates,
               'new_strict_resource_valid_trials': valid_new,
               'new_dropped_uncredited_trials': dropped_new,
               'prior_uncredited_trial': 4,
               'v2_reconstruction_receipt_sha256': sha(PACKAGE / 'reconstruction-receipt.json'),
               'v2_seal_receipt_sha256': sha(BASE / 'data/mallory/evidence_archives/SOLR-15-fault-bootstrap-node0-v2.receipt.json'),
               'source_review': 'expected protective SplitShardCmd @538 abort after live-node loss',
               'campaign_completion_credited': True,
               'new_bug': False}
    return result, depth, quality


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT)):
        raise FileExistsError('SOLR-15 v3 seal already exists')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _, depth, quality = attest()
        write_once(DEPTH, depth)
        write_once(QUALITY, quality)
        files = sorted(path for path in RAW.rglob('*')
                       if path.is_file() and path.name != '.campaign.lock')
        if not files or any(path.is_symlink() for path in files):
            raise RuntimeError('raw campaign empty or symlinked')
        prefix = 'solr15_fault_bootstrap_node0_v3/'
        members = [{'path': prefix + path.relative_to(RAW).as_posix(),
                    'bytes': path.stat().st_size, 'sha256': sha(path)} for path in files]
        if shutil.disk_usage(BASE).free < FLOOR + sum(row['bytes'] for row in members) + 64 * 1024**2:
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
        write_once(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-15',
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
                   'package_manifest_sha256': sha(PACKAGE / 'sha-manifest.json'),
                   'package_agent_sha256': sha(PACKAGE / 'agent/release/mallory-agent.jar'),
                   'all_archive_members_verified': True}
        write_once(RECEIPT, receipt)
        return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
