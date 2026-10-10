#!/usr/bin/env python3
"""SHA-seal the one-trial node0 SOLR-40 healthy admission outcome."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tarfile


ROOT = Path('/users/ZhenyuLi/baseline')
HERE = Path(__file__).resolve().parent
RAW = ROOT / 'data/mallory/calibration_solr40_watcher_handoff_v1_node0/SOLR-40'
ARCHIVES = ROOT / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-40-healthy-watcher-handoff-node0-v1'
ARCHIVE = ARCHIVES / (PREFIX + '.tar.gz')
MANIFEST = ARCHIVES / (PREFIX + '.members.json')
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
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MANIFEST, RECEIPT)):
        raise FileExistsError('SOLR-40 v1 healthy seal already exists')
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    trial = read(RAW / 'trials/r0000/result.json')
    pilot = read(RAW / 'trials/r0000/pilot-result.json')
    junit = read(RAW / 'trials/r0000/junit-receipt.json')
    audit = read(RAW / 'handoff-audit.json')
    admission = read(HERE / 'admission-healthy-node0.json')
    if not (result.get('case_id') == 'SOLR-40'
            and result.get('status') == checkpoint.get('status') == 'healthy_seed_invalid'
            and checkpoint.get('completed_trials') == [0]
            and result.get('fault_trials_completed') == 0
            and result.get('healthy_seed_valid') is False
            and result.get('healthy_eligible_doors') == 0
            and read(RAW / 'config.json') == read(HERE / 'config.json')
            and admission.get('go') is True
            and admission.get('config_sha256') == sha(HERE / 'config.json')
            and admission.get('runner_sha256') == sha(HERE / 'run_healthy.py')
            and admission.get('intended_output') == str(RAW)
            and junit.get('status') == 'passed' and junit.get('tests') == 1
            and pilot.get('target_check_count') == 11
            and pilot.get('target_throw_count') == 0
            and trial.get('feedback', {}).get('status') == 'healthy_exact_watcher_door_missing'
            and trial['feedback'].get('target_reached') is True
            and trial['feedback'].get('target_threw') is False
            and len(trial['feedback'].get('target_instances', [])) == 11
            and audit.get('junit_passed') is True
            and audit.get('target_nonthrowing') is True
            and audit.get('named_exact_door_events') == 36
            and audit.get('named_exact_target_checks') == 11
            and audit.get('committed_gate_same_occurrence_doors') == 0
            and not audit.get('same_occurrence_pretarget_pairs')
            and not audit.get('observed_graph_paths')
            and audit.get('sampled_state_is_admission_proof') is False
            and audit.get('result_sha256') == sha(RAW / 'result.json')
            and audit.get('trial_result_sha256') == sha(RAW / 'trials/r0000/result.json')
            and audit.get('trace_sha256') == sha(RAW / 'trials/r0000/events.jsonl.gz')
            and audit.get('junit_log_sha256') == sha(RAW / 'trials/r0000/junit.log')
            and trial.get('events_evidence', {}).get('gzip_sha256') ==
            sha(RAW / 'trials/r0000/events.jsonl.gz')):
        raise RuntimeError('SOLR-40 healthy raw evidence or admission mismatch')
    files = sorted(path for path in RAW.rglob('*') if path.is_file())
    if not files or any(path.is_symlink() or path.name.endswith('.tmp') for path in files):
        raise RuntimeError('raw evidence is empty, symlinked, or temporary')
    members = [{'path': 'calibration_solr40_watcher_handoff_v1_node0/SOLR-40/' +
                path.relative_to(RAW).as_posix(), 'bytes': path.stat().st_size,
                'sha256': sha(path)} for path in files]
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
        if sha(RAW / 'result.json') != audit['result_sha256']:
            raise RuntimeError('raw result changed while sealing')
        os.replace(temporary, ARCHIVE)
    finally:
        temporary.unlink(missing_ok=True)
    write(MANIFEST, {'schema_version': 1, 'case_id': 'SOLR-40',
                     'scope': 'node0_healthy_only', 'members': members,
                     'member_count': len(members), 'archive_sha256': sha(ARCHIVE)})
    receipt = {'schema_version': 1, 'case_id': 'SOLR-40',
               'scope': 'node0_healthy_only', 'status': result['status'],
               'fault_trials_completed': 0, 'junit_passed': True,
               'named_exact_door_events': 36, 'named_exact_target_checks': 11,
               'committed_gate_same_occurrence_doors': 0,
               'observed_graph_paths': 0,
               'sampled_state_handoffs': len(audit.get('sampled_state_handoffs', [])),
               'sampled_state_is_admission_proof': False,
               'archive_sha256': sha(ARCHIVE),
               'member_manifest_sha256': sha(MANIFEST),
               'member_count': len(members),
               'result_sha256': sha(RAW / 'result.json'),
               'trial_result_sha256': sha(RAW / 'trials/r0000/result.json'),
               'trace_sha256': sha(RAW / 'trials/r0000/events.jsonl.gz'),
               'handoff_audit_sha256': sha(RAW / 'handoff-audit.json'),
               'admission_receipt_sha256': sha(HERE / 'admission-healthy-node0.json'),
               'runner_sha256': sha(HERE / 'run_healthy.py'),
               'config_sha256': sha(HERE / 'config.json'),
               'all_archive_members_verified': True}
    write(RECEIPT, receipt)
    return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
