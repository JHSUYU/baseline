#!/usr/bin/env python3
"""SHA-seal the one-trial SOLR-15 node0 chaos healthy observation."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
CASE = BASE / 'Mallory/adapters/solr/cases/SOLR-15/chaos-healthy-node0-v1'
RAW = BASE / 'data/mallory/solr15_chaos_healthy_node0_v1/healthy'
PREFIX = 'SOLR-15-chaos-healthy-node0-v1'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
ARCHIVE = ARCHIVES / (PREFIX + '.tar.gz')
MEMBERS = ARCHIVES / (PREFIX + '.members.json')
RECEIPT = ARCHIVES / (PREFIX + '.receipt.json')


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
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT)):
        raise FileExistsError('SOLR-15 healthy seal already exists')
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    trial = read(RAW / 'trials/r0000/result.json')
    pilot = read(RAW / 'trials/r0000/pilot-result.json')
    gate = read(RAW / 'chaos-healthy-node0-gate.json')
    admission = read(CASE / 'admission-healthy-node0.json')
    trace = RAW / 'trials/r0000/events.jsonl.gz'
    if not (result.get('case_id') == 'SOLR-15'
            and result.get('status') == checkpoint.get('status') == 'calibration_complete'
            and checkpoint.get('completed_trials') == [0]
            and result.get('calibration_only') is True
            and result.get('healthy_seed_valid') is False
            and result.get('fault_trials_completed') == 0
            and result.get('healthy_junit_validation', {}).get('status') == 'passed'
            and result['healthy_junit_validation'].get('tests') == 1
            and pilot.get('target_check_count') == 0
            and pilot.get('target_throw_count') == 0
            and pilot.get('junit', {}).get('run') == 1
            and pilot['junit'].get('failures') == pilot['junit'].get('ignored') == 0
            and trial.get('feedback', {}).get('status') == 'healthy_target_missing'
            and trial['feedback'].get('target_reached') is False
            and trial['feedback'].get('target_threw') is False
            and trial.get('events_evidence', {}).get('gzip_sha256') == sha(trace)
            and gate.get('status') == 'failed'
            and gate.get('full_campaign_admitted') is False
            and gate.get('resource_path_attested') is False
            and gate.get('observed_first_caller_doors') == 1
            and gate.get('observed_second_caller_doors') == 1
            and gate.get('observed_native_exists_doors') == 170
            and gate.get('same_split_handoff_witness') is None
            and gate.get('original_gate', {}).get('native_door_count') == 0
            and set(gate.get('reasons', [])) == {
                'native_exists_door_lacks_named_physical_actor',
                'same_split_first_second_and_native_exists_handoff_missing'}
            and read(RAW / 'config.json') == read(CASE / 'config-healthy-node0.json')
            and admission.get('go') is True
            and admission.get('config_sha256') == sha(CASE / 'config-healthy-node0.json')
            and admission.get('runner_sha256') == sha(CASE / 'run_campaign.py')
            and admission.get('intended_output') == str(RAW)):
        raise RuntimeError('SOLR-15 healthy result, audit, trace, or admission mismatch')
    files = sorted(path for path in RAW.rglob('*') if path.is_file())
    if not files or any(path.is_symlink() or path.name.endswith('.tmp') for path in files):
        raise RuntimeError('raw evidence is empty, symlinked, or temporary')
    members = [{'path': 'solr15_chaos_healthy_node0_v1/healthy/' +
                path.relative_to(RAW).as_posix(), 'bytes': path.stat().st_size,
                'sha256': sha(path)} for path in files]
    if shutil.disk_usage(BASE).free < 7_650_410_496 + sum(row['bytes'] for row in members):
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
                if not item.isfile() or item.size != row['bytes']:
                    raise RuntimeError('archive member size mismatch')
                digest = hashlib.sha256()
                with archive.extractfile(item) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                if digest.hexdigest() != row['sha256']:
                    raise RuntimeError('archive member SHA mismatch')
        os.replace(temporary, ARCHIVE)
    finally:
        temporary.unlink(missing_ok=True)
    write(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-15',
                    'scope': 'node0_chaos_healthy_only', 'member_count': len(members),
                    'members': members, 'archive_sha256': sha(ARCHIVE)})
    receipt = {'schema_version': 1, 'case_id': 'SOLR-15',
               'scope': 'node0_chaos_healthy_only', 'status': result['status'],
               'junit_passed': True, 'healthy_seed_valid': False,
               'fault_trials_completed': 0, 'exact_target_checks': 0,
               'observed_first_caller_doors': 1,
               'observed_second_caller_doors': 1,
               'observed_native_exists_doors': 170,
               'qualified_named_native_exists_doors': 0,
               'same_split_handoff_proven': False,
               'resource_path_attested': False,
               'full_campaign_admitted': False,
               'archive_sha256': sha(ARCHIVE),
               'member_manifest_sha256': sha(MEMBERS),
               'member_count': len(members),
               'result_sha256': sha(RAW / 'result.json'),
               'trial_result_sha256': sha(RAW / 'trials/r0000/result.json'),
               'trace_sha256': sha(trace),
               'quality_gate_sha256': sha(RAW / 'chaos-healthy-node0-gate.json'),
               'admission_receipt_sha256': sha(CASE / 'admission-healthy-node0.json'),
               'runner_sha256': sha(CASE / 'run_campaign.py'),
               'config_sha256': sha(CASE / 'config-healthy-node0.json'),
               'all_archive_members_verified': True}
    write(RECEIPT, receipt)
    return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
