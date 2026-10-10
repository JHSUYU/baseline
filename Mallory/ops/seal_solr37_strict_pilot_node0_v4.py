#!/usr/bin/env python3
"""SHA-seal SOLR-37 v4's terminal strict healthy-gate outcome."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
CASE = BASE / 'Mallory/adapters/solr/cases/SOLR-37/strict-fault-pilot-node0-v4'
RAW = BASE / 'data/mallory/solr37_strict_fault_pilot_v4_node0/SOLR-37/pilot'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-37-strict-pilot-node0-v4'
ARCHIVE = ARCHIVES / f'{PREFIX}.tar.gz'
MEMBERS = ARCHIVES / f'{PREFIX}.members.json'
RECEIPT = ARCHIVES / f'{PREFIX}.receipt.json'
QUALITY = RAW / 'terminal-quality.json'
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


def attest() -> tuple[dict, dict]:
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    trial = read(RAW / 'trials/r0000/result.json')
    audit = read(RAW / 'trials/r0000/strict-audit.json')
    pilot = read(RAW / 'trials/r0000/pilot-result.json')
    admission = read(CASE / 'admission-pilot-node0.json')
    junit = result['healthy_junit_validation']
    trace = RAW / 'trials/r0000/events.jsonl.gz'
    if not (result['case_id'] == checkpoint['case_id'] == pilot['case_id'] == 'SOLR-37'
            and result['status'] == checkpoint['status'] == 'healthy_seed_invalid'
            and checkpoint['completed_trials'] == [0]
            and checkpoint['running'] is None
            and result['healthy_seed_valid'] is False
            and result['fault_trials_completed'] == 0
            and result['exact_exception_trials'] == 0
            and result['new_bug'] is not True
            and junit['status'] == 'passed'
            and (junit['tests'], junit['failures'], junit['errors'], junit['skipped']) == (1, 0, 0, 0)
            and trial['junit_validation'] == junit
            and trial['return_code'] == 0 and trial['timed_out'] is False
            and trial['plan'] == []
            and trial['feedback']['status'] == 'strict_missing_strict_healthy_path'
            and trial['feedback']['target_threw'] is False
            and trial['strict_audit'] == audit
            and audit == {'candidate_state_edges': 0, 'door_count': 18,
                          'eligible_for_fault_pilot': False,
                          'observed_state_edges': 26715,
                          'reason': 'missing_strict_healthy_path',
                          'strict_witness_count': 0,
                          'strict_witness_sample': [],
                          'target_count': 160, 'valid': False}
            and trial['events_evidence']['gzip_sha256'] == sha(trace)
            and pilot['exit_code'] == 0
            and pilot['junit'] == {'run': 1, 'failures': 0, 'ignored': 0}
            and pilot['target_check_count'] == 160
            and pilot['target_throw_count'] == 0
            and junit['junit_log_sha256'] == sha(RAW / 'trials/r0000/junit.log')
            and read(RAW / 'config.json') == read(CASE / 'config-pilot-node0.json')
            and admission['go'] is True and admission['case_id'] == 'SOLR-37'
            and admission['host'] == 'node0' and admission['mode'] == 'pilot'
            and admission['intended_output'] == str(RAW)
            and admission['config_sha256'] == sha(CASE / 'config-pilot-node0.json')
            and admission['runner_sha256'] == sha(CASE / 'run_campaign.py')):
        raise RuntimeError('SOLR-37 v4 terminal healthy gate, JUnit, trace, or GO mismatch')
    return result, audit


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT)):
        raise FileExistsError('SOLR-37 v4 seal already exists')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, audit = attest()
        quality = {'schema_version': 1, 'case_id': 'SOLR-37',
                   'scope': 'strict_pilot_v4_healthy_gate',
                   'status': result['status'], 'duration_seconds': result['duration_seconds'],
                   'junit': '1/0/0/0', 'exact_target_checks': 160,
                   'exact_target_throws': 0, 'qualified_watcher_doors': 18,
                   'strict_witness_count': 0,
                   'observed_state_edges': 26715, 'candidate_state_edges': 0,
                   'fault_trials_completed': 0, 'full_campaign_admitted': False,
                   'campaign_completion_credited': False, 'new_bug': False,
                   'strict_audit_sha256': sha(RAW / 'trials/r0000/strict-audit.json')}
        write(QUALITY, quality)
        files = sorted(path for path in RAW.rglob('*')
                       if path.is_file() and path.name != '.campaign.lock')
        if not files or any(path.is_symlink() for path in files):
            raise RuntimeError('raw evidence empty or symlinked')
        prefix = 'solr37_strict_fault_pilot_v4_node0/SOLR-37/pilot/'
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
        receipt = {**quality, 'archive_sha256': sha(ARCHIVE),
                   'member_manifest_sha256': sha(MEMBERS), 'member_count': len(members),
                   'result_sha256': sha(RAW / 'result.json'),
                   'checkpoint_sha256': sha(RAW / 'checkpoint.json'),
                   'quality_sidecar_sha256': sha(QUALITY),
                   'trace_sha256': sha(RAW / 'trials/r0000/events.jsonl.gz'),
                   'admission_receipt_sha256': sha(CASE / 'admission-pilot-node0.json'),
                   'config_sha256': sha(CASE / 'config-pilot-node0.json'),
                   'runner_sha256': sha(CASE / 'run_campaign.py'),
                   'agent_sha256': sha(CASE / 'agent/release/mallory-agent.jar'),
                   'adapter_sha256': sha(CASE / 'adapter/release/adapter.jar'),
                   'all_archive_members_verified': True}
        write(RECEIPT, receipt)
        return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
