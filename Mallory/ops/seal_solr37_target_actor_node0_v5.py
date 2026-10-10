#!/usr/bin/env python3
"""Attest and SHA-seal the terminal SOLR-37 dynamic-actor bounded pilot."""

from __future__ import annotations

from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

BASE = Path('/users/ZhenyuLi/baseline')
CASE = BASE / 'Mallory/adapters/solr/cases/SOLR-37/target-actor-fault-pilot-node0-v5'
RAW = BASE / 'data/mallory/solr37_target_actor_fault_pilot_v5_node0/SOLR-37/pilot'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-37-target-actor-pilot-node0-v5'
ARCHIVE = ARCHIVES / f'{PREFIX}.tar.gz'
MEMBERS = ARCHIVES / f'{PREFIX}.members.json'
RECEIPT = ARCHIVES / f'{PREFIX}.receipt.json'
QUALITY = RAW / 'terminal-quality.json'
DEPTH = RAW / 'fault-depth-review.json'
LOCK = Path('/tmp/mallory-lanes/solr-node0-v1.lock')
FLOOR = 7_650_410_496


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
    admission = read(CASE / 'admission-pilot-node0.json')
    if not (result['case_id'] == checkpoint['case_id'] == 'SOLR-37'
            and result['status'] == checkpoint['status'] == 'budget_exhausted'
            and checkpoint['completed_trials'] == list(range(7))
            and checkpoint['running'] is None
            and result['healthy_seed_valid'] is True
            and result['fault_trials_completed'] == 6
            and result['strict_injected_trials'] == 2
            and result['target_reached_trials'] == 2
            and result['exact_exception_trials'] == 0
            and result['target_exception_candidate_trials'] == []
            and result['reproduced_candidates'] == []
            and result['new_bug'] is not True
            and read(RAW / 'config.json') == read(CASE / 'config-pilot-node0.json')
            and admission['go'] is True and admission['case_id'] == 'SOLR-37'
            and admission['host'] == 'node0' and admission['mode'] == 'pilot'
            and admission['intended_output'] == str(RAW)
            and admission['config_sha256'] == sha(CASE / 'config-pilot-node0.json')
            and admission['runner_sha256'] == sha(CASE / 'run_campaign.py')):
        raise RuntimeError('SOLR-37 v5 terminal result, config or GO mismatch')
    depths = Counter()
    rows = []
    for number in range(7):
        trial_root = RAW / 'trials' / f'r{number:04d}'
        trial = read(trial_root / 'result.json')
        audit = read(trial_root / 'strict-audit.json')
        pilot = read(trial_root / 'pilot-result.json')
        feedback = trial['feedback']
        junit = trial['junit_validation']
        trace = trial_root / 'events.jsonl.gz'
        if not (trial['trial_id'] == number
                and trial['return_code'] == 0 and trial['timed_out'] is False
                and junit['status'] == 'passed'
                and (junit['tests'], junit['failures'], junit['errors'], junit['skipped']) == (1, 0, 0, 0)
                and junit['junit_log_sha256'] == sha(trial_root / 'junit.log')
                and pilot['exit_code'] == 0
                and pilot['junit'] == {'run': 1, 'failures': 0, 'ignored': 0}
                and pilot['target_throw_count'] == 0
                and trial['strict_audit'] == audit
                and trial['events_evidence']['gzip_sha256'] == sha(trace)
                and feedback['target_threw'] is False):
            raise RuntimeError(f'r{number:04d} trial/JUnit/trace mismatch')
        depth = len(trial['plan'])
        if number:
            depths[str(depth)] += 1
        if number == 0:
            expected = (0, True, 'strict_healthy_path', True)
            if not (audit['strict_witness_count'] == 44
                    and audit['target_count'] == 168
                    and audit['candidate_state_edges'] == 0):
                raise RuntimeError('fresh healthy exact-reference gate changed')
        elif number in (1, 2):
            expected = (1, True, 'strict_fault_and_postfault_target', True)
            if not (audit['postfault_target_count'] == {1: 100, 2: 116}[number]
                    and feedback['all_faults_matched'] is True
                    and feedback['all_faults_applied'] is True
                    and feedback['all_faults_effective'] is True):
                raise RuntimeError(f'r{number:04d} strict effective fault changed')
        else:
            expected = ({3: 1, 4: 1, 5: 1, 6: 2}[number], False,
                        'fault_receipt_missing_or_duplicated', False)
            if feedback['all_faults_effective'] is not False:
                raise RuntimeError(f'r{number:04d} invalid fault got effectiveness credit')
        if not (depth == expected[0] and audit['valid'] is expected[1]
                and audit['reason'] == expected[2]
                and feedback['target_reached'] is expected[3]):
            raise RuntimeError(f'r{number:04d} strict audit or target status changed')
        rows.append({'trial_id': number, 'depth': depth, 'junit': '1/0/0/0',
                     'strict_audit_valid': audit['valid'], 'strict_audit_reason': audit['reason'],
                     'effective_fault': number in (1, 2),
                     'postfault_target_count': audit.get('postfault_target_count', 0),
                     'target_throw_count': 0,
                     'result_sha256': sha(trial_root / 'result.json'),
                     'strict_audit_sha256': sha(trial_root / 'strict-audit.json'),
                     'trace_sha256': sha(trace)})
    depth = {'schema_version': 1, 'case_id': 'SOLR-37',
             'scope': 'bounded_pilot_fault_depth',
             'status': result['status'], 'fault_trials_completed': 6,
             'depth_distribution': dict(depths),
             'controller_release_manifest_sha256': sha(
                 BASE / 'Mallory/dispatch/releases/4390310699b695ba002ed541508b359204a2d95529df09bb9f702db5dac3cde4/manifest.json'),
             'campaign_result_sha256': sha(RAW / 'result.json'),
             'trials': rows[1:]}
    quality = {'schema_version': 1, 'case_id': 'SOLR-37',
               'scope': 'dynamic_target_actor_strict_pilot_v5',
               'status': result['status'], 'duration_seconds': result['duration_seconds'],
               'healthy_strict_witness_count': 44,
               'fault_trials_completed': 6,
               'strict_effective_target_retaining_trials': [1, 2],
               'strict_missing_receipt_trials': [3, 4, 5, 6],
               'exact_target_exception_trials': [],
               'plan_depth_distribution': dict(depths),
               'bounded_pilot_completed': True,
               'full_campaign_admitted': False, 'new_bug': False,
               'trials': rows}
    return result, depth, quality


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT)):
        raise FileExistsError('SOLR-37 v5 seal already exists')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, depth, quality = attest()
        write(DEPTH, depth)
        write(QUALITY, quality)
        files = sorted(path for path in RAW.rglob('*')
                       if path.is_file() and path.name != '.campaign.lock')
        if not files or any(path.is_symlink() for path in files):
            raise RuntimeError('raw pilot empty or symlinked')
        prefix = 'solr37_target_actor_fault_pilot_v5_node0/SOLR-37/pilot/'
        members = [{'path': prefix + path.relative_to(RAW).as_posix(),
                    'bytes': path.stat().st_size, 'sha256': sha(path)} for path in files]
        if shutil.disk_usage(BASE).free < FLOOR + sum(row['bytes'] for row in members):
            raise RuntimeError('archive would breach node0 disk reserve')
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
            if shutil.disk_usage(BASE).free < FLOOR:
                raise RuntimeError('archive breached disk reserve')
            os.replace(temporary, ARCHIVE)
        finally:
            temporary.unlink(missing_ok=True)
        write(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-37',
                        'raw_root': str(RAW), 'member_count': len(members),
                        'members': members, 'archive_sha256': sha(ARCHIVE),
                        'result_sha256': sha(RAW / 'result.json')})
        receipt = {'schema_version': 1, 'case_id': 'SOLR-37',
                   'scope': quality['scope'], 'status': result['status'],
                   'duration_seconds': result['duration_seconds'],
                   'fault_trials_completed': 6,
                   'strict_effective_target_retaining_trials': [1, 2],
                   'strict_missing_receipt_trials': [3, 4, 5, 6],
                   'exact_target_exception_trials': [],
                   'plan_depth_distribution': depth['depth_distribution'],
                   'bounded_pilot_completed': True,
                   'full_campaign_admitted': False, 'new_bug': False,
                   'archive_sha256': sha(ARCHIVE),
                   'member_manifest_sha256': sha(MEMBERS), 'member_count': len(members),
                   'result_sha256': sha(RAW / 'result.json'),
                   'checkpoint_sha256': sha(RAW / 'checkpoint.json'),
                   'depth_review_sha256': sha(DEPTH),
                   'quality_sidecar_sha256': sha(QUALITY),
                   'admission_receipt_sha256': sha(CASE / 'admission-pilot-node0.json'),
                   'config_sha256': sha(CASE / 'config-pilot-node0.json'),
                   'runner_sha256': sha(CASE / 'run_campaign.py'),
                   'agent_sha256': sha(CASE.parent / 'strict-fault-pilot-node0-v4/agent/release/mallory-agent.jar'),
                   'adapter_sha256': sha(CASE / 'adapter/release/adapter.jar'),
                   'all_archive_members_verified': True}
        write(RECEIPT, receipt)
        return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
