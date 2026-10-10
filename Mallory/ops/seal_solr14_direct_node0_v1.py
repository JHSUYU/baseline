#!/usr/bin/env python3
"""Audit and SHA-seal the one-trial SOLR-14 node0 direct-door observation."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
CASE = BASE / 'Mallory/adapters/solr/cases/SOLR-14/healthy-direct-node0-v1'
RAW = BASE / 'data/mallory/solr14_direct_healthy_v1_node0/SOLR-14/healthy'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-14-direct-healthy-node0-v1'
ARCHIVE = ARCHIVES / (PREFIX + '.tar.gz')
MEMBERS = ARCHIVES / (PREFIX + '.members.json')
RECEIPT = ARCHIVES / (PREFIX + '.receipt.json')
GATE = RAW / 'direct-healthy-node0-gate.json'
SITE_PREFIX = ('org.apache.solr.cloud.api.collections.SplitShardCmd'
               '#split(Lorg/apache/solr/common/cloud/ClusterState;'
               'Lorg/apache/solr/common/cloud/ZkNodeProps;'
               'Lorg/apache/solr/common/util/NamedList;)Z')
CHECK = SITE_PREFIX + '@165:branch:5'
DOOR_130 = SITE_PREFIX + '@130:door:1'
DOOR_164 = SITE_PREFIX + '@164:door:2'
TYPED_EXCEPTION = 'org.apache.zookeeper.KeeperException$ConnectionLossException'


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
    trace = RAW / 'trials/r0000/events.jsonl.gz'
    with gzip.open(trace, 'rt', encoding='utf-8') as stream:
        events = [json.loads(line) for line in stream]
    checks = [e for e in events if e.get('type') == 'TARGET_CHECK'
              and e.get('site') == CHECK]
    doors130 = [e for e in events if e.get('type') == 'DOOR_OBSERVED'
                and e.get('site') == DOOR_130]
    doors164 = [e for e in events if e.get('type') == 'DOOR_OBSERVED'
                and e.get('site') == DOOR_164]
    throws = [e for e in events if e.get('type') == 'TARGET_THROW']
    pairs = [(door, check) for door in doors164 for check in checks
             if (door.get('node'), door.get('occurrence')) ==
                (check.get('node'), check.get('occurrence'))
             and door.get('seq', -1) < check.get('seq', -1)]
    junit = trial.get('junit_validation', {})
    feedback = trial.get('feedback', {})
    valid = (result.get('case_id') == 'SOLR-14'
             and result.get('status') == checkpoint.get('status') == 'calibration_complete'
             and checkpoint.get('completed_trials') == [0]
             and checkpoint.get('running') is None
             and result.get('calibration_only') is True
             and result.get('healthy_seed_valid') is True
             and result.get('fault_trials_completed') == 0
             and result.get('new_bug') is not True
             and junit.get('status') == 'passed'
             and (junit.get('tests'), junit.get('failures'), junit.get('errors'),
                  junit.get('skipped')) == (1, 0, 0, 0)
             and trial.get('plan') == [] and trial.get('timed_out') is False
             and trial.get('return_code') == 0
             and trial.get('site_catalog_validation', {}).get('valid') is True
             and trial['site_catalog_validation'].get('class_hash_match') is True
             and feedback.get('status') == 'observed'
             and feedback.get('target_reached') is True
             and feedback.get('target_threw') is False
             and feedback.get('trace_truncated') is False
             and feedback.get('target_identity_complete') is True
             and pilot.get('target_check_count') == len(checks) == 3
             and pilot.get('target_throw_count') == len(throws) == 0
             and len(doors130) == len(doors164) == len(pairs) == 3
             and all(e.get('node') == 'node1' and e.get('outcome') == 'TAKEN'
                     for e in checks)
             and all(e.get('node') == 'node1' and
                     e.get('exception_class') == TYPED_EXCEPTION
                     for e in doors130 + doors164)
             and trial.get('events_evidence', {}).get('gzip_sha256') == sha(trace)
             and trial.get('events_sha256') ==
                 hashlib.sha256(gzip.decompress(trace.read_bytes())).hexdigest()
             and trial.get('site_catalog_sha256') ==
                 sha(RAW / 'trials/r0000/sites.jsonl')
             and read(RAW / 'config.json') == read(CASE / 'config-healthy-node0.json')
             and admission.get('go') is True
             and admission.get('config_sha256') == sha(CASE / 'config-healthy-node0.json')
             and admission.get('runner_sha256') == sha(CASE / 'run_campaign.py')
             and admission.get('intended_output') == str(RAW))
    if not valid:
        raise RuntimeError('SOLR-14 healthy result, trace, site catalog, or GO mismatch')
    return {'schema_version': 1, 'case_id': 'SOLR-14',
            'scope': 'node0_direct_healthy_only', 'status': 'observation_passed',
            'junit': '1/0/0', 'target_site': CHECK,
            'target_check_count': len(checks), 'target_throw_count': len(throws),
            'typed_door_130_count': len(doors130),
            'typed_door_164_count': len(doors164),
            'same_occurrence_164_to_165_pairs': len(pairs),
            'same_occurrence_pair_event_ids': [
                {'door': door['id'], 'target': check['id']}
                for door, check in pairs],
            'source_path': 'solr/core/src/java/org/apache/solr/cloud/api/collections/SplitShardCmd.java',
            'source_limit': ('ConnectionLossException at either selected direct call '
                             'propagates before the line-165 target check; the '
                             'fault-retaining path is unproved.'),
            'fault_trials_completed': 0, 'full_campaign_admitted': False,
            'new_bug': False}


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT, GATE)):
        raise FileExistsError('SOLR-14 healthy seal already exists')
    gate = attest()
    write(GATE, gate)
    files = sorted(path for path in RAW.rglob('*') if path.is_file())
    if not files or any(path.is_symlink() or path.name.endswith('.tmp') for path in files):
        raise RuntimeError('raw evidence is empty, symlinked, or temporary')
    members = [{'path': 'solr14_direct_healthy_v1_node0/SOLR-14/healthy/' +
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
    write(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-14',
                    'scope': 'node0_direct_healthy_only', 'member_count': len(members),
                    'members': members, 'archive_sha256': sha(ARCHIVE)})
    receipt = {**gate, 'status': 'calibration_complete',
               'duration_seconds': read(RAW / 'result.json')['duration_seconds'],
               'archive_sha256': sha(ARCHIVE),
               'member_manifest_sha256': sha(MEMBERS),
               'member_count': len(members),
               'result_sha256': sha(RAW / 'result.json'),
               'trial_result_sha256': sha(RAW / 'trials/r0000/result.json'),
               'trace_sha256': sha(RAW / 'trials/r0000/events.jsonl.gz'),
               'quality_gate_sha256': sha(GATE),
               'admission_receipt_sha256': sha(CASE / 'admission-healthy-node0.json'),
               'runner_sha256': sha(CASE / 'run_campaign.py'),
               'config_sha256': sha(CASE / 'config-healthy-node0.json'),
               'all_archive_members_verified': True}
    write(RECEIPT, receipt)
    return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
