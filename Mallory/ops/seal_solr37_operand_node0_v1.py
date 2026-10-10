#!/usr/bin/env python3
"""SHA-seal the terminal SOLR-37 node0 healthy diagnostic, including failure."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
CASE = BASE / 'Mallory/adapters/solr/cases/SOLR-37/operand-telemetry-v1'
RAW = BASE / 'data/mallory/solr37_operand_telemetry_healthy_v1_node0/SOLR-37/healthy'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-37-operand-healthy-node0-v1'
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
    admission = read(CASE / 'admission-healthy-node0.json')
    junit = result['healthy_junit_validation']
    log = RAW / 'trials/r0000/junit.log'
    trace = RAW / 'trials/r0000/events.jsonl.gz'
    if not (result['case_id'] == checkpoint['case_id'] == pilot['case_id'] == 'SOLR-37'
            and result['status'] == checkpoint['status'] == 'healthy_seed_invalid'
            and checkpoint['completed_trials'] == [0]
            and checkpoint['running'] is None
            and result['calibration_only'] is True
            and result['fault_trials_completed'] == 0
            and result['new_bug'] is not True
            and result['healthy_seed_valid'] is False
            and result['target_reached_trials'] == result['exact_exception_trials'] == 0
            and trial['plan'] == [] and trial['timed_out'] is False
            and trial['return_code'] == pilot['exit_code'] == 1
            and trial['junit_validation'] == junit
            and junit['status'] == 'report_invalid'
            and junit['reason'] == 'invalid test counts'
            and junit['junit_log_sha256'] == sha(log)
            and 'MALLORY_TEST_RESULT run=1 failures=3 ignored=0' in log.read_text()
            and pilot['junit'] == {'run': 1, 'failures': 3, 'ignored': 0}
            and pilot['target_check_count'] == pilot['target_throw_count'] == 0
            and trial['feedback']['status'] == 'healthy_junit_report_invalid'
            and trial['feedback']['target_reached'] is False
            and trial['feedback']['target_threw'] is False
            and trial['feedback']['trace_truncated'] is False
            and trial['events_evidence']['gzip_sha256'] == sha(trace)
            and read(RAW / 'config.json') == read(CASE / 'config-healthy-node0.json')
            and admission['go'] is True and admission['case_id'] == 'SOLR-37'
            and admission['host'] == 'node0' and admission['mode'] == 'healthy'
            and admission['intended_output'] == str(RAW)
            and admission['config_sha256'] == sha(CASE / 'config-healthy-node0.json')
            and admission['runner_sha256'] == sha(CASE / 'run_campaign.py')):
        raise RuntimeError('SOLR-37 terminal result, JUnit, trace, or admission mismatch')
    return result


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT)):
        raise FileExistsError('SOLR-37 healthy seal already exists')
    result = attest()
    files = sorted(path for path in RAW.rglob('*') if path.is_file())
    if not files or any(path.is_symlink() for path in files):
        raise RuntimeError('raw evidence empty or symlinked')
    prefix = 'solr37_operand_telemetry_healthy_v1_node0/SOLR-37/healthy/'
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
    write(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-37',
                    'scope': 'node0_healthy_diagnostic', 'member_count': len(members),
                    'members': members, 'archive_sha256': sha(ARCHIVE)})
    receipt = {'schema_version': 1, 'case_id': 'SOLR-37',
               'scope': 'node0_healthy_diagnostic', 'status': result['status'],
               'duration_seconds': result['duration_seconds'],
               'junit_marker': 'run=1 failures=3 ignored=0',
               'controller_junit_status': 'report_invalid',
               'controller_junit_reason': 'invalid test counts',
               'pilot_exit_code': 1, 'exact_target_checks': 0,
               'exact_target_throws': 0, 'fault_trials_completed': 0,
               'full_campaign_admitted': False, 'new_bug': False,
               'archive_sha256': sha(ARCHIVE),
               'member_manifest_sha256': sha(MEMBERS),
               'member_count': len(members),
               'result_sha256': sha(RAW / 'result.json'),
               'trial_result_sha256': sha(RAW / 'trials/r0000/result.json'),
               'trace_sha256': sha(RAW / 'trials/r0000/events.jsonl.gz'),
               'junit_log_sha256': sha(RAW / 'trials/r0000/junit.log'),
               'admission_receipt_sha256': sha(CASE / 'admission-healthy-node0.json'),
               'runner_sha256': sha(CASE / 'run_campaign.py'),
               'config_sha256': sha(CASE / 'config-healthy-node0.json'),
               'all_archive_members_verified': True}
    write(RECEIPT, receipt)
    return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
