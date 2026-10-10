#!/usr/bin/env python3
"""SHA-seal the SOLR-40 v2 healthy result and its JUnit recognition gap."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
CASE = BASE / 'Mallory/adapters/solr/cases/SOLR-40/healthy-watcher-handoff-node0-v2'
RAW = BASE / 'data/mallory/calibration_solr40_reference_handoff_v2_node0/SOLR-40'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-40-reference-healthy-node0-v2'
ARCHIVE = ARCHIVES / (PREFIX + '.tar.gz')
MEMBERS = ARCHIVES / (PREFIX + '.members.json')
RECEIPT = ARCHIVES / (PREFIX + '.receipt.json')
QUALITY = RAW / 'reference-healthy-node0-quality.json'
WITNESS_IDS = ('SOLR-40-r0000:5022', 'SOLR-40-r0000:5061',
               'SOLR-40-r0000:5896', 'SOLR-40-r0000:5898')


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
    audit = read(RAW / 'handoff-audit.json')
    admission = read(CASE / 'admission-healthy-node0.json')
    trial_root = RAW / 'trials/r0000'
    trace = trial_root / 'events.jsonl.gz'
    log = trial_root / 'junit.log'
    marker = 'MALLORY_TEST_RESULT run=1 failures=0 ignored=0'
    marker_lines = [line for line in log.read_text().splitlines()
                    if re.fullmatch(r'MALLORY_TEST_RESULT run=\d+ failures=\d+ ignored=\d+',
                                    line)]
    with gzip.open(trace, 'rt', encoding='utf-8') as stream:
        events = {row['id']: row for line in stream
                  if (row := json.loads(line)).get('id') in WITNESS_IDS}
    door, write_event, read_event, check = (events.get(key) for key in WITNESS_IDS)
    witness = audit.get('exact_reference_witnesses', {}).get(WITNESS_IDS[0], {})
    if not (result.get('case_id') == 'SOLR-40'
            and result.get('status') == checkpoint.get('status') == 'healthy_seed_invalid'
            and checkpoint.get('completed_trials') == [0]
            and checkpoint.get('running') is None
            and result.get('calibration_only') is True
            and result.get('healthy_seed_valid') is False
            and result.get('fault_trials_completed') == 0
            and result.get('new_bug') is not True
            and result.get('healthy_junit_validation', {}).get('status') == 'not_applicable'
            and trial.get('junit_validation', {}).get('status') == 'not_applicable'
            and trial.get('feedback', {}).get('status') ==
                'healthy_junit_runner_unrecognized'
            and trial['feedback'].get('target_reached') is True
            and trial['feedback'].get('target_threw') is False
            and trial['feedback'].get('trace_truncated') is False
            and trial.get('return_code') == 0
            and trial.get('timed_out') is False
            and trial.get('plan') == []
            and pilot.get('exit_code') == 0
            and pilot.get('junit') == {'run': 1, 'failures': 0, 'ignored': 0}
            and pilot.get('target_check_count') == 11
            and pilot.get('target_throw_count') == 0
            and marker_lines == [marker]
            and audit.get('status') == 'fresh_handoff_not_proven'
            and audit.get('eligible_for_full_review') is False
            and audit.get('full_campaign_go') is False
            and audit.get('junit_status') == 'not_applicable'
            and audit.get('named_exact_target_checks') == 11
            and audit.get('named_observed_watcher_doors') == 1
            and witness.get('reference_write_event') == WITNESS_IDS[1]
            and witness.get('reference_read_event') == WITNESS_IDS[2]
            and witness.get('target_event') == WITNESS_IDS[3]
            and witness.get('edge_kinds') == ['program_order', 'state_ref', 'return']
            and all(row is not None for row in (door, write_event, read_event, check))
            and [row.get('type') for row in (door, write_event, read_event, check)] ==
                ['DOOR_OBSERVED', 'STATE_WRITE', 'STATE_READ', 'TARGET_CHECK']
            and all(row.get('node') == 'node1' for row in
                    (door, write_event, read_event, check))
            and write_event.get('key') == read_event.get('key')
            and write_event.get('value_object') == read_event.get('value_object') == 'o394'
            and [row.get('seq') for row in (door, write_event, read_event, check)] ==
                [5022, 5061, 5896, 5898]
            and trial.get('events_evidence', {}).get('gzip_sha256') == sha(trace)
            and audit.get('trace_sha256') == sha(trace)
            and audit.get('junit_log_sha256') == sha(log)
            and audit.get('result_sha256') == sha(RAW / 'result.json')
            and audit.get('trial_result_sha256') == sha(trial_root / 'result.json')
            and read(RAW / 'config.json') == read(CASE / 'config.json')
            and admission.get('go') is True
            and admission.get('config_sha256') == sha(CASE / 'config.json')
            and admission.get('runner_sha256') == sha(CASE / 'run_healthy_v2.py')
            and admission.get('agent_jar_sha256') == sha(CASE / 'releases/mallory-agent.jar')
            and admission.get('intended_output') == str(RAW)):
        raise RuntimeError('SOLR-40 v2 result, exact reference trace, or GO mismatch')
    return {'schema_version': 1, 'case_id': 'SOLR-40',
            'scope': 'node0_exact_reference_healthy_only',
            'status': 'core_healthy_seed_invalid',
            'core_junit_validation': 'not_applicable',
            'core_feedback_status': 'healthy_junit_runner_unrecognized',
            'pilot_exit_code': 0, 'pilot_junit': pilot['junit'],
            'independent_junit_marker': marker,
            'named_exact_target_checks': 11, 'named_watcher_doors': 1,
            'exact_reference_witness_event_ids': list(WITNESS_IDS),
            'exact_reference_value_object': 'o394',
            'exact_reference_edge_kinds': witness['edge_kinds'],
            'fault_trials_completed': 0,
            'eligible_for_full_review_in_pinned_audit': False,
            'full_campaign_go': False, 'new_bug': False,
            'note': ('The independent JUnit marker and healthy exact-reference path '
                     'do not override the pinned core validator or prove '
                     'postfault target retention.')}


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT, QUALITY)):
        raise FileExistsError('SOLR-40 v2 healthy seal already exists')
    quality = attest()
    write(QUALITY, quality)
    files = sorted(path for path in RAW.rglob('*') if path.is_file())
    if not files or any(path.is_symlink() or path.name.endswith('.tmp') for path in files):
        raise RuntimeError('raw evidence is empty, symlinked, or temporary')
    members = [{'path': 'calibration_solr40_reference_handoff_v2_node0/SOLR-40/' +
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
    write(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-40',
                    'scope': 'node0_exact_reference_healthy_only',
                    'member_count': len(members), 'members': members,
                    'archive_sha256': sha(ARCHIVE)})
    receipt = {**quality, 'archive_sha256': sha(ARCHIVE),
               'member_manifest_sha256': sha(MEMBERS),
               'member_count': len(members),
               'result_sha256': sha(RAW / 'result.json'),
               'trial_result_sha256': sha(RAW / 'trials/r0000/result.json'),
               'trace_sha256': sha(RAW / 'trials/r0000/events.jsonl.gz'),
               'handoff_audit_sha256': sha(RAW / 'handoff-audit.json'),
               'quality_sidecar_sha256': sha(QUALITY),
               'admission_receipt_sha256': sha(CASE / 'admission-healthy-node0.json'),
               'runner_sha256': sha(CASE / 'run_healthy_v2.py'),
               'agent_jar_sha256': sha(CASE / 'releases/mallory-agent.jar'),
               'config_sha256': sha(CASE / 'config.json'),
               'all_archive_members_verified': True}
    write(RECEIPT, receipt)
    return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
