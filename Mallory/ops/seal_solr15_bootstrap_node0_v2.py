#!/usr/bin/env python3
"""Attest and SHA-seal SOLR-15's path-qualified bounded bootstrap."""

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
PACKAGE = BASE / 'Mallory/adapters/solr/cases/SOLR-15/fault-bootstrap-node0-v2'
RAW = BASE / 'data/mallory/solr15_fault_bootstrap_node0_v2'
RELEASE = BASE / 'Mallory/dispatch/releases/815cba9b-target-absent-v1'
SOURCE = Path('/users/ZhenyuLi/.graphchecker-sources/solr-8.11.4/solr/core/src/java/org/apache/solr/cloud/api/collections/SplitShardCmd.java')
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-15-fault-bootstrap-node0-v2'
ARCHIVE = ARCHIVES / f'{PREFIX}.tar.gz'
MEMBERS = ARCHIVES / f'{PREFIX}.members.json'
RECEIPT = ARCHIVES / f'{PREFIX}.receipt.json'
DEPTH = RAW / 'fault-depth-review.json'
QUALITY = RAW / 'terminal-quality.json'
LOCK = Path('/tmp/mallory-lanes/solr-node0-v1.lock')
FLOOR = 7_650_410_496
sys.path.insert(0, str(PACKAGE))
import seed_selector as seed  # noqa: E402


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
    admission = read(PACKAGE / 'admission-full-node0.json')
    release = read(RELEASE / 'manifest.json')
    source_text = SOURCE.read_text()
    if not (result.get('case_id') == checkpoint.get('case_id') == 'SOLR-15'
            and result.get('status') == checkpoint.get('status') == 'fault_resource_mismatch'
            and checkpoint.get('completed_trials') == [0, 1, 2, 3, 4]
            and checkpoint.get('running') is None
            and result.get('fault_trials_completed') == 4
            and result.get('strict_injected_trials') == 3
            and result.get('target_exception_candidate_trials') == [2, 3]
            and result.get('reproduced_candidates') == [{'first_trial': 2, 'replay_trial': 3}]
            and result.get('target_discovered_trial') == 2
            and result.get('exact_exception_trials') == 2
            and result.get('new_bug') is not True
            and read(RAW / 'config.json') == read(PACKAGE / 'config-full-node0.json')
            and admission.get('go') is True and admission.get('host') == 'node0'
            and admission.get('mode') == 'full' and admission.get('case_id') == 'SOLR-15'
            and admission.get('intended_output') == str(RAW)
            and admission.get('config_sha256') == sha(PACKAGE / 'config-full-node0.json')
            and admission.get('runner_sha256') == sha(PACKAGE / 'run_campaign.py')
            and admission.get('selector_sha256') == sha(PACKAGE / 'seed_selector.py')
            and admission.get('agent_sha256') == sha(PACKAGE / 'agent/release/mallory-agent.jar')
            and release.get('files')
            and all(sha(RELEASE / name) == digest for name, digest in release['files'].items())
            and 'if (leaderZnodeStat == null)  {' in source_text
            and 'the leader is not live anymore, fail the split!' in source_text
            and 'propMap.put(subSlice, Slice.State.RECOVERY_FAILED.toString())' in source_text):
        raise RuntimeError('SOLR-15 v2 terminal, GO, pinned controller, or protective source mismatch')

    trials = []
    depths = Counter()
    for number in range(5):
        root = RAW / 'trials' / f'r{number:04d}'
        trial = read(root / 'result.json')
        pilot = read(root / 'pilot-result.json')
        plan = trial.get('plan')
        feedback = trial.get('feedback', {})
        evidence = trial.get('events_evidence', {})
        junit = trial.get('junit_validation', {})
        if not (trial.get('trial_id') == number and isinstance(plan, list)
                and trial.get('return_code') == 0 and trial.get('timed_out') is False
                and junit.get('status') == 'passed'
                and (junit.get('tests'), junit.get('failures'), junit.get('errors'), junit.get('skipped')) == (1, 0, 0, 0)
                and junit.get('junit_log_sha256') == sha(root / 'junit.log')
                and pilot.get('exit_code') == 0
                and pilot.get('junit') == {'run': 1, 'failures': 0, 'ignored': 0}
                and evidence.get('gzip_sha256') == sha(root / evidence['gzip_path'])):
            raise RuntimeError(f'r{number:04d} trial, JUnit, or trace mismatch')
        if number:
            depths[str(len(plan))] += 1
        trials.append(trial)

    if not (len(trials[0]['plan']) == 0
            and trials[0]['feedback']['status'] == 'healthy_target_missing'
            and [len(trial['plan']) for trial in trials[1:]] == [1, 2, 2, 3]
            and [trial['feedback']['status'] for trial in trials[1:]] ==
            ['target_lost', 'target_exception_candidate',
             'target_exception_candidate', 'fault_resource_mismatch']):
        raise RuntimeError('SOLR-15 v2 trial status/depth changed')
    for number in (1, 2, 3):
        root = RAW / 'trials' / f'r{number:04d}'
        trial = trials[number]
        seed.attest_fault_resources(root, trial['plan'])
        after = seed.attest_target_after_fault(root, trial['plan'])
        if (trial.get('resource_attestation') !=
                {'valid': True, 'role': 'same-run parent-leader live znode',
                 'target_after_fault': after}
                or after != (number in (2, 3))
                or trial['feedback']['all_faults_effective'] is not True):
            raise RuntimeError(f'r{number:04d} strict resource or target mismatch')
    if not (trials[4].get('resource_attestation') ==
            {'valid': False, 'reason': 'target gate requires all planned faults applied'}
            and len(trials[4]['feedback']['applied_fault_ids']) == 2
            and trials[4]['feedback']['all_faults_effective'] is False):
        raise RuntimeError('r0004 invalid third fault was credited')

    proof = []
    for number in (2, 3):
        trial = trials[number]
        rows = seed.events(RAW / 'trials' / f'r{number:04d}')
        fault_ids = {fault['fault_id'] for fault in trial['plan']}
        applied = [row for row in rows if row.get('type') == 'FAULT_APPLIED'
                   and row.get('fault_id') in fault_ids]
        checks = [row for row in rows if row.get('type') == 'TARGET_CHECK'
                  and row.get('site', '').endswith('@536:branch:40')]
        throws = [row for row in rows if row.get('type') == 'TARGET_THROW'
                  and row.get('site', '').endswith('@538:throw:1')]
        if not (len(applied) == 2 and len(checks) == len(throws) == 1
                and len({row.get('resource') for row in applied}) == 1
                and all(seed.same_execution(row, applied[0]) for row in applied + checks + throws)
                and max(row['seq'] for row in applied) < min(row['seq'] for row in checks)
                and max(row['seq'] for row in checks) < min(row['seq'] for row in throws)
                and all(row.get('exception_class') == 'org.apache.solr.common.SolrException'
                        for row in throws)):
            raise RuntimeError(f'r{number:04d} exact throw sequence mismatch')
        proof.append({'trial_id': number,
                      'parent_live_node_resource': applied[0]['resource'],
                      'fault_applied_sequences': [row['seq'] for row in applied],
                      'target_check_sequences': [row['seq'] for row in checks],
                      'target_throw_sequences': [row['seq'] for row in throws],
                      'trace_sha256': sha(RAW / 'trials' / f'r{number:04d}/events.jsonl.gz')})

    depth = {'schema_version': 1, 'case_id': 'SOLR-15',
             'scope': 'fault_plan_depth_and_controller_provenance',
             'status': result['status'], 'fault_trials_completed': 4,
             'campaign_result_sha256': sha(RAW / 'result.json'),
             'campaign_checkpoint_sha256': sha(RAW / 'checkpoint.json'),
             'controller_release_id': RELEASE.name,
             'controller_release_manifest_sha256': sha(RELEASE / 'manifest.json'),
             'scheduler_sha256': sha(RELEASE / 'Mallory/core/scheduler.py'),
             'depth_distribution': dict(depths),
             'trials': [{'trial_id': number, 'depth': len(trials[number]['plan']),
                         'result_sha256': sha(RAW / 'trials' / f'r{number:04d}/result.json')}
                        for number in range(1, 5)]}
    quality = {'schema_version': 1, 'case_id': 'SOLR-15',
               'scope': 'resource_qualified_bootstrap_v2',
               'status': result['status'], 'duration_seconds': result['duration_seconds'],
               'fault_trials_completed': 4, 'strict_resource_valid_trials': [1, 2, 3],
               'strict_target_exception_trials': [2, 3],
               'reproduced_expected_protective_abort': True,
               'expected_source_branch': 'SplitShardCmd.split@536-538',
               'source_sha256': sha(SOURCE), 'strict_sequence_proof': proof,
               'invalid_depth_three_trial': 4,
               'invalid_depth_three_reason': 'third planned fault not applied',
               'plan_depth_distribution': dict(depths),
               'campaign_completion_credited': False, 'new_bug': False}
    return result, depth, quality


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MEMBERS, RECEIPT)):
        raise FileExistsError('SOLR-15 v2 seal already exists')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, depth, quality = attest()
        write(DEPTH, depth)
        write(QUALITY, quality)
        files = sorted(path for path in RAW.rglob('*')
                       if path.is_file() and path.name != '.campaign.lock')
        if not files or any(path.is_symlink() for path in files):
            raise RuntimeError('raw campaign empty or symlinked')
        prefix = 'solr15_fault_bootstrap_node0_v2/'
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
        write(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-15',
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
                   'package_selector_sha256': sha(PACKAGE / 'seed_selector.py'),
                   'package_agent_sha256': sha(PACKAGE / 'agent/release/mallory-agent.jar'),
                   'all_archive_members_verified': True}
        write(RECEIPT, receipt)
        return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
