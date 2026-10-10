#!/usr/bin/env python3
"""SHA-seal the SOLR-37 node0 watcher-state healthy observation."""

from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
CASE = BASE / 'Mallory/adapters/solr/cases/SOLR-37/healthy-state-watcher-node0-v1'
RAW = BASE / 'data/mallory/solr37_state_watcher_healthy_v1_node0/SOLR-37/healthy'
PREFIX = 'SOLR-37-watcher-state-node0-healthy-v1'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
ARCHIVE = ARCHIVES / (PREFIX + '.tar.gz')
MEMBERS = ARCHIVES / (PREFIX + '.members.json')
RECEIPT = ARCHIVES / (PREFIX + '.receipt.json')
AUDIT = BASE / 'data/mallory/quality_reviews/healthy/SOLR-37-watcher-node0-v1.json'
DOOR = ('org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState'
        '(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Ljava/lang/String;)'
        'Lorg/apache/solr/common/cloud/DocCollection;@1641:door:1')
REGION = ('org.apache.solr.common.cloud.ZkStateReader$StateWatcher#refreshAndWatch'
          '(Lorg/apache/zookeeper/Watcher$Event$EventType;)V')
EXCEPTION = 'org.apache.zookeeper.KeeperException$ConnectionLossException'


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
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def audit_trace() -> dict:
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    trial = read(RAW / 'trials/r0000/result.json')
    pilot = read(RAW / 'trials/r0000/pilot-result.json')
    admission = read(CASE / 'admission-healthy-node0.json')
    trace = RAW / 'trials/r0000/events.jsonl.gz'
    if not (result.get('case_id') == 'SOLR-37'
            and result.get('status') == checkpoint.get('status') == 'calibration_complete'
            and checkpoint.get('completed_trials') == [0]
            and result.get('calibration_only') is True
            and result.get('healthy_seed_valid') is True
            and result.get('fault_trials_completed') == 0
            and result.get('healthy_junit_validation', {}).get('status') == 'passed'
            and result['healthy_junit_validation'].get('tests') == 1
            and pilot.get('target_check_count') == 180
            and pilot.get('target_throw_count') == 0
            and pilot.get('target_nodes') == ['shard-4']
            and trial.get('feedback', {}).get('target_reached') is True
            and trial['feedback'].get('target_threw') is False
            and trial.get('events_evidence', {}).get('gzip_sha256') == sha(trace)
            and read(RAW / 'config.json') == read(CASE / 'config-healthy-node0.json')
            and admission.get('go') is True
            and admission.get('config_sha256') == sha(CASE / 'config-healthy-node0.json')
            and admission.get('runner_sha256') == sha(CASE / 'run_campaign.py')
            and admission.get('intended_output') == str(RAW)):
        raise RuntimeError('SOLR-37 healthy result, trace, or admission mismatch')
    doors = []
    targets = []
    with gzip.open(trace, 'rt') as stream:
        for line in stream:
            event = json.loads(line)
            if (event.get('type') == 'DOOR_OBSERVED'
                    and event.get('site') == DOOR
                    and event.get('exception_class') == EXCEPTION):
                doors.append(event)
            if (event.get('type') == 'TARGET_CHECK'
                    and event.get('site') in read(CASE / 'config-healthy-node0.json')['target']['check_sites']):
                targets.append(event)
    first_target = min(event['seq'] for event in targets)
    by_node = Counter(event.get('node') for event in doors)
    same_node_watcher = [event for event in doors if event.get('node') == 'shard-4'
                         and event.get('region') == REGION]
    pretarget = [event for event in same_node_watcher if event['seq'] < first_target]
    if not (len(doors) == 636 and len(targets) == 180
            and len(same_node_watcher) == 141 and len(pretarget) == 23
            and all(event.get('node') == 'shard-4' for event in targets)
            and all(event.get('outcome') != 'THROW' for event in targets)):
        raise RuntimeError('exact watcher/target trace counts changed')
    audit = {'schema_version': 1, 'case_id': 'SOLR-37',
             'scope': 'node0_healthy_watcher_qualification',
             'status': result['status'], 'junit_passed': True,
             'result_sha256': sha(RAW / 'result.json'),
             'trial_result_sha256': sha(RAW / 'trials/r0000/result.json'),
             'trace_sha256': sha(trace),
             'exact_typed_watcher_doors': len(doors),
             'exact_typed_watcher_doors_by_node': dict(sorted(by_node.items())),
             'same_target_node_watcher_occurrence_doors': len(same_node_watcher),
             'same_target_node_watcher_pretarget_doors': len(pretarget),
             'first_target_seq': first_target,
             'exact_nonthrowing_target_checks': len(targets),
             'target_node': 'shard-4',
             'watcher_path_field_present': any('path' in event for event in doors),
             'target_reader_id_field_present': any('reader_id' in event for event in targets),
             'target_range_operand_field_present': any(
                 key in event for event in targets for key in ('mySlice', 'parent_range')),
             'watcher_to_target_handoff_admission_proven': False,
             'full_campaign_admitted': False,
             'interpretation': ('A same-node pretarget watcher door and target check are '
                                'observed, but the selected trace lacks reader identity, '
                                'ZooKeeper path, target range operands, and a demonstrated '
                                'watcher-to-request causal handoff.')}
    write(AUDIT, audit)
    return audit


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT, AUDIT)):
        raise FileExistsError('SOLR-37 healthy seal already exists')
    audit = audit_trace()
    files = sorted(path for path in RAW.rglob('*') if path.is_file())
    if not files or any(path.is_symlink() or path.name.endswith('.tmp') for path in files):
        raise RuntimeError('raw evidence is empty, symlinked, or temporary')
    members = [{'path': 'solr37_state_watcher_healthy_v1_node0/SOLR-37/healthy/' +
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
        if sha(RAW / 'result.json') != audit['result_sha256']:
            raise RuntimeError('raw result changed during archive creation')
        os.replace(temporary, ARCHIVE)
    finally:
        temporary.unlink(missing_ok=True)
    write(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-37',
                    'scope': audit['scope'], 'member_count': len(members),
                    'members': members, 'archive_sha256': sha(ARCHIVE)})
    receipt = {'schema_version': 1, 'case_id': 'SOLR-37', 'scope': audit['scope'],
               'status': audit['status'], 'fault_trials_completed': 0,
               'archive_sha256': sha(ARCHIVE),
               'member_manifest_sha256': sha(MEMBERS),
               'member_count': len(members),
               'quality_audit_sha256': sha(AUDIT),
               'result_sha256': audit['result_sha256'],
               'trace_sha256': audit['trace_sha256'],
               'admission_receipt_sha256': sha(CASE / 'admission-healthy-node0.json'),
               'runner_sha256': sha(CASE / 'run_campaign.py'),
               'config_sha256': sha(CASE / 'config-healthy-node0.json'),
               'handoff_admission_proven': False,
               'all_archive_members_verified': True}
    write(RECEIPT, receipt)
    return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
