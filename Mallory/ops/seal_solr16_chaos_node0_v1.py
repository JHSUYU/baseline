#!/usr/bin/env python3
"""Verify and SHA-seal the SOLR-16 node0 healthy diagnostic."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
CASE = BASE / 'Mallory/adapters/solr/cases/SOLR-16/chaos-healthy-node0-v1'
RAW = BASE / 'data/mallory/solr16_chaos_healthy_node0_v1/healthy'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-16-chaos-healthy-node0-v1'
ARCHIVE = ARCHIVES / f'{PREFIX}.tar.gz'
MEMBERS = ARCHIVES / f'{PREFIX}.members.json'
RECEIPT = ARCHIVES / f'{PREFIX}.receipt.json'


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


def attest() -> dict:
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    trial = read(RAW / 'trials/r0000/result.json')
    pilot = read(RAW / 'trials/r0000/pilot-result.json')
    gate = read(RAW / 'solr16-chaos-healthy-gate.json')
    admission = read(CASE / 'admission-healthy-node0.json')
    trace = RAW / 'trials/r0000/events.jsonl.gz'
    witness = gate['same_split_identity_witness']
    ids = [witness[key] for key in ('first_caller_event_id',
                                   'first_native_event_id',
                                   'second_caller_event_id',
                                   'second_native_event_id')]
    with gzip.open(trace, 'rt', encoding='utf-8') as stream:
        events = {event['id']: event for line in stream
                  if (event := json.loads(line)).get('id') in ids}
    rows = [events.get(event_id) for event_id in ids]
    junit = result['healthy_junit_validation']
    if not (result['case_id'] == checkpoint['case_id'] == gate['case_id'] == 'SOLR-16'
            and result['status'] == checkpoint['status'] == 'calibration_complete'
            and checkpoint['completed_trials'] == [0]
            and checkpoint['running'] is None
            and result['calibration_only'] is True
            and result['fault_trials_completed'] == 0
            and result['new_bug'] is not True
            and result['healthy_seed_valid'] is False
            and result['target_reached_trials'] == 0
            and result['exact_exception_trials'] == 0
            and junit['status'] == 'passed'
            and (junit['tests'], junit['failures'], junit['errors'], junit['skipped']) == (1, 0, 0, 0)
            and trial['junit_validation'] == junit
            and trial['return_code'] == 0
            and trial['timed_out'] is False
            and trial['plan'] == []
            and trial['feedback']['target_reached'] is False
            and trial['feedback']['target_threw'] is False
            and trial['feedback']['trace_truncated'] is False
            and trial['events_evidence']['gzip_sha256'] == sha(trace)
            and pilot['exit_code'] == 0
            and pilot['junit'] == {'run': 1, 'failures': 0, 'ignored': 0}
            and pilot['target_check_count'] == pilot['target_throw_count'] == 0
            and gate['status'] == 'failed'
            and gate['reasons'] == ['exact_target_check_missing_after_same_split_lookup']
            and gate['identity_status'] == 'bound'
            and gate['resource_path_attested'] is True
            and gate['healthy_exact_check_reached'] is False
            and gate['healthy_exact_throw_reached'] is False
            and gate['same_split_exact_check_event_id'] is None
            and gate['full_campaign_admitted'] is False
            and gate['original_junit'] == junit
            and all(row is not None for row in rows)
            and [row['seq'] for row in rows] == sorted(row['seq'] for row in rows)
            and all(row['type'] == 'DOOR_OBSERVED' for row in rows)
            and all(row['node'] == witness['actor'] == 'control' for row in rows)
            and all(row['context'] == witness['context'] for row in rows)
            and all(row['occurrence'] == witness['split_occurrence'] for row in rows)
            and all(row['thread_id'] == witness['thread_id'] for row in rows)
            and all(row['epoch'] == witness['epoch'] for row in rows)
            and rows[1]['resource'] == rows[3]['resource'] == witness['parent_live_node_resource']
            and rows[1]['site'] == rows[3]['site'] == gate['typed_fault_door']
            and junit['junit_log_sha256'] == sha(RAW / 'trials/r0000/junit.log')
            and read(RAW / 'config.json') == read(CASE / 'config-healthy-node0.json')
            and admission['go'] is True and admission['host'] == 'node0'
            and admission['mode'] == 'healthy'
            and admission['intended_output'] == str(RAW)
            and admission['config_sha256'] == sha(CASE / 'config-healthy-node0.json')
            and admission['runner_sha256'] == sha(CASE / 'run_campaign.py')
            and admission['manifest_sha256'] == sha(CASE / 'sha-manifest.json')):
        raise RuntimeError('SOLR-16 terminal result, witness, or admission mismatch')
    return result, gate


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT)):
        raise FileExistsError('SOLR-16 healthy seal already exists')
    result, gate = attest()
    files = sorted(path for path in RAW.rglob('*') if path.is_file())
    if not files or any(path.is_symlink() or path.name.endswith('.tmp') for path in files):
        raise RuntimeError('raw evidence empty, symlinked, or temporary')
    prefix = 'solr16_chaos_healthy_node0_v1/healthy/'
    members = [{'path': prefix + path.relative_to(RAW).as_posix(),
                'bytes': path.stat().st_size, 'sha256': sha(path)} for path in files]
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
    write(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-16',
                    'scope': 'node0_healthy_diagnostic', 'member_count': len(members),
                    'members': members, 'archive_sha256': sha(ARCHIVE)})
    receipt = {'schema_version': 1, 'case_id': 'SOLR-16',
               'scope': 'node0_healthy_diagnostic', 'status': result['status'],
               'duration_seconds': result['duration_seconds'],
               'junit': '1/0/0/0', 'exact_target_checks': 0,
               'exact_target_throws': 0, 'fault_trials_completed': 0,
               'same_split_path_attested': True,
               'parent_live_node_resource': gate['same_split_identity_witness']['parent_live_node_resource'],
               'healthy_gate_status': gate['status'], 'healthy_gate_reasons': gate['reasons'],
               'full_campaign_admitted': False, 'new_bug': False,
               'archive_sha256': sha(ARCHIVE),
               'member_manifest_sha256': sha(MEMBERS),
               'member_count': len(members),
               'result_sha256': sha(RAW / 'result.json'),
               'trial_result_sha256': sha(RAW / 'trials/r0000/result.json'),
               'trace_sha256': sha(RAW / 'trials/r0000/events.jsonl.gz'),
               'healthy_gate_sha256': sha(RAW / 'solr16-chaos-healthy-gate.json'),
               'admission_receipt_sha256': sha(CASE / 'admission-healthy-node0.json'),
               'runner_sha256': sha(CASE / 'run_campaign.py'),
               'config_sha256': sha(CASE / 'config-healthy-node0.json'),
               'all_archive_members_verified': True}
    write(RECEIPT, receipt)
    return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
