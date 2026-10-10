#!/usr/bin/env python3
"""SHA-seal a naturally terminal SOLR-13 exploratory full campaign."""

from __future__ import annotations

from collections import Counter
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

from seal_solr40_reference_full_node0_v1 import read, sha, write


BASE = Path('/users/ZhenyuLi/baseline')
RAW = BASE / 'data/mallory/campaigns/SOLR-13-source-exploratory-full-node0-v1'
CANONICAL = BASE / 'data/mallory/cases/SOLR-13'
PACKAGE = BASE / 'Mallory/adapters/solr/cases/SOLR-13/source-exploratory-full-node0-v1'
RELEASE = BASE / 'Mallory/dispatch/releases/fa5f3bde5aef54c0253ff8d783ce107112c196d6c82ae5cd0284a2876f053d3f'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-13-source-exploratory-full-node0-v1'
ARCHIVE = ARCHIVES / (PREFIX + '.tar.gz')
MANIFEST = ARCHIVES / (PREFIX + '.members.json')
RECEIPT = ARCHIVES / (PREFIX + '.receipt.json')
DEPTH = RAW / 'fault-depth-review.json'
QUALITY = RAW / 'terminal-quality.json'
LOCK = Path('/tmp/mallory-lanes/solr-node0-v1.lock')
TERMINAL = {'budget_exhausted', 'queue_exhausted'}
FLOOR = 7_650_410_496


def attest() -> tuple[dict, dict, dict]:
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    config = read(RAW / 'config.json')
    audit = read(RAW / 'offline-causal-audit.json')
    admission = read(PACKAGE / 'admission-full-node0.json')
    count = result.get('fault_trials_completed')
    if (result.get('case_id') != 'SOLR-13'
            or result.get('status') not in TERMINAL
            or checkpoint.get('status') != result['status']
            or checkpoint.get('running') is not None
            or result.get('healthy_seed_valid') is not True
            or not isinstance(count, int) or not 0 < count <= 80
            or checkpoint.get('completed_trials') != list(range(count + 1))
            or result.get('new_bug') is True
            or not isinstance(result.get('exact_exception_trials'), int)
            or not isinstance(result.get('target_exception_candidate_trials'), list)
            or not isinstance(result.get('reproduced_candidates'), list)
            or result.get('healthy_junit_validation', {}).get('status') != 'passed'
            or config != read(PACKAGE / 'config-full-node0.json')
            or admission.get('go') is not True
            or admission.get('case_id') != 'SOLR-13'
            or admission.get('mode') != 'full'
            or admission.get('host') != 'node0'
            or admission.get('intended_output') != str(RAW)
            or admission.get('config_sha256') != sha(PACKAGE / 'config-full-node0.json')
            or admission.get('runner_sha256') != sha(PACKAGE / 'run_campaign.py')
            or audit.get('campaign_result_sha256') != sha(RAW / 'result.json')
            or audit.get('case_id') != 'SOLR-13'
            or audit.get('terminal_status') != result['status']
            or audit.get('trial_count') != count + 1):
        raise RuntimeError('terminal SOLR-13 result, audit, config, or GO mismatch')

    release_manifest_path = RELEASE / 'manifest.json'
    release = read(release_manifest_path)
    if (release.get('release_id') != RELEASE.name
            or any(sha(RELEASE / name) != digest
                   for name, digest in release.get('files', {}).items())
            or not release.get('files')):
        raise RuntimeError('controller release differs from pinned manifest')
    distribution: Counter[str] = Counter()
    feedback_status: Counter[str] = Counter()
    unmatched_actor_drift: Counter[str] = Counter()
    trials = []
    for number in range(count + 1):
        trial_id = f'r{number:04d}'
        path = RAW / 'trials' / trial_id / 'result.json'
        trial = read(path)
        evidence = trial.get('events_evidence') or {}
        trace = path.parent / evidence.get('gzip_path', '')
        plan = trial.get('plan')
        if (trial.get('case_id') != 'SOLR-13'
                or trial.get('trial_id') != number
                or not isinstance(plan, list)
                or (number == 0 and plan != [])
                or (number > 0 and not 1 <= len(plan) <= 3)
                or not trace.is_file() or trace.parent != path.parent
                or evidence.get('gzip_sha256') != sha(trace)):
            raise RuntimeError(f'trial, plan, or trace mismatch: {trial_id}')
        if number:
            distribution[str(len(plan))] += 1
            status = str(trial.get('feedback', {}).get('status'))
            feedback_status[status] += 1
            if status == 'fault_unmatched' and len(plan) == 1:
                point = plan[0].get('point') or {}
                selected_site = point.get('site')
                selected_node = point.get('node')
                with gzip.open(trace, 'rt', encoding='utf-8') as stream:
                    observed = sorted({row.get('node') for line in stream
                                       if (row := json.loads(line)).get('type') == 'DOOR_OBSERVED'
                                       and row.get('site') == selected_site
                                       and isinstance(row.get('node'), str)})
                if selected_node not in observed and observed:
                    unmatched_actor_drift[f'{selected_node}->{",".join(observed)}'] += 1
            trials.append({'trial_id': number, 'depth': len(plan),
                           'result_sha256': sha(path)})
    depth = {'schema_version': 1, 'case_id': 'SOLR-13',
             'scope': 'fault_plan_depth_and_controller_provenance',
             'status': result['status'], 'fault_trials_completed': count,
             'campaign_result_sha256': sha(RAW / 'result.json'),
             'campaign_checkpoint_sha256': sha(RAW / 'checkpoint.json'),
             'campaign_config_sha256': sha(RAW / 'config.json'),
             'controller_release_id': RELEASE.name,
             'controller_release_manifest_sha256': sha(release_manifest_path),
             'scheduler_sha256': sha(RELEASE / 'Mallory/core/scheduler.py'),
             'single_fault_breadth_interval': config.get('single_fault_breadth_interval'),
             'multi_fault_exploration_interval': config.get('multi_fault_exploration_interval'),
             'depth_distribution': dict(sorted(distribution.items())), 'trials': trials}
    quality = {'schema_version': 1, 'case_id': 'SOLR-13',
               'scope': 'exploratory_full_path_unverified_at_admission',
               'status': result['status'], 'duration_seconds': result['duration_seconds'],
               'fault_trials_completed': count,
               'strict_injected_trials': result.get('strict_injected_trials'),
               'strict_target_trials': result.get('strict_target_trials'),
               'exact_exception_trials': result['exact_exception_trials'],
               'target_exception_candidates': len(result['target_exception_candidate_trials']),
               'reproduced_candidates': len(result['reproduced_candidates']),
               'offline_audit_sha256': sha(RAW / 'offline-causal-audit.json'),
               'audit_report_gate_passed': audit.get('report_gate_passed'),
               'audit_guidance_consistent': audit.get('guidance_consistent'),
               'audit_archive_integrity_valid': audit.get('archive_integrity_valid'),
               'audit_applied_fault_identity_valid': audit.get('applied_fault_identity_valid'),
               'audit_target_claims_reverified': audit.get('target_claims_reverified'),
               'audit_healthy_observed_path_doors': audit.get('healthy_observed_path_doors'),
               'audit_same_actor_target_gate_passed': audit.get('same_actor_target_gate_passed'),
               'plan_depth_distribution': dict(sorted(distribution.items())),
               'fault_feedback_status_distribution': dict(sorted(feedback_status.items())),
               'unmatched_single_fault_actor_drift': dict(sorted(unmatched_actor_drift.items())),
               'new_bug': False}
    return result, depth, quality


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MANIFEST, RECEIPT, CANONICAL, DEPTH, QUALITY)):
        raise FileExistsError('SOLR-13 exploratory full seal or import already exists')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, depth, quality = attest()
        write(DEPTH, depth)
        write(QUALITY, quality)
        files = sorted(path for path in RAW.rglob('*') if path.is_file()
                       and path.name != '.campaign.lock')
        if not files or any(path.is_symlink() or path.name.endswith('.tmp')
                            for path in files):
            raise RuntimeError('raw campaign empty, symlinked, or temporary')
        members = [{'path': 'campaigns/' + PREFIX + '/' + path.relative_to(RAW).as_posix(),
                    'bytes': path.stat().st_size, 'sha256': sha(path)} for path in files]
        free = shutil.disk_usage(BASE).free
        actual_bytes = sum(path.stat().st_blocks * 512 for path in files)
        if free < FLOOR + 2 * actual_bytes + 100 * 1024**2:
            raise RuntimeError('archive may breach node0 disk reserve')
        ARCHIVES.mkdir(parents=True, exist_ok=True)
        temporary = ARCHIVE.with_name(ARCHIVE.name + '.tmp')
        try:
            with tarfile.open(temporary, 'w:gz') as packed:
                for path, row in zip(files, members):
                    item = tarfile.TarInfo(row['path'])
                    item.size = row['bytes']
                    item.mode = 0o600
                    item.mtime = 0
                    with path.open('rb') as stream:
                        packed.addfile(item, stream)
            with tarfile.open(temporary, 'r:gz') as packed:
                entries = packed.getmembers()
                if [item.name for item in entries] != [row['path'] for row in members]:
                    raise RuntimeError('archive member list differs')
                for item, row in zip(entries, members):
                    stream = packed.extractfile(item)
                    if not item.isfile() or item.size != row['bytes'] or stream is None:
                        raise RuntimeError('archive member missing or size differs')
                    digest = hashlib.sha256()
                    with stream:
                        for block in iter(lambda: stream.read(1024 * 1024), b''):
                            digest.update(block)
                    if digest.hexdigest() != row['sha256']:
                        raise RuntimeError('archive member SHA differs')
            if (sha(RAW / 'result.json') != depth['campaign_result_sha256']
                    or shutil.disk_usage(BASE).free < FLOOR):
                raise RuntimeError('raw result changed or archive breached disk reserve')
            os.replace(temporary, ARCHIVE)
        finally:
            temporary.unlink(missing_ok=True)
        write(MANIFEST, {'schema_version': 1, 'case_id': 'SOLR-13',
                         'raw_root': str(RAW), 'member_count': len(members),
                         'members': members, 'archive_sha256': sha(ARCHIVE),
                         'result_sha256': depth['campaign_result_sha256']})
        receipt = {**quality, 'archive_path': str(ARCHIVE),
                   'archive_sha256': sha(ARCHIVE), 'archive_size': ARCHIVE.stat().st_size,
                   'member_manifest_sha256': sha(MANIFEST), 'member_count': len(members),
                   'result_sha256': sha(RAW / 'result.json'),
                   'checkpoint_sha256': sha(RAW / 'checkpoint.json'),
                   'depth_review_sha256': sha(DEPTH),
                   'quality_sidecar_sha256': sha(QUALITY),
                   'admission_receipt_sha256': sha(PACKAGE / 'admission-full-node0.json'),
                   'package_config_sha256': sha(PACKAGE / 'config-full-node0.json'),
                   'package_runner_sha256': sha(PACKAGE / 'run_campaign.py'),
                   'all_archive_members_verified': True}
        write(RECEIPT, receipt)
        staged = CANONICAL.with_name('.SOLR-13.exploratory-full-import')
        staged.mkdir(parents=True, exist_ok=False)
        names = ('config.json', 'result.json', 'checkpoint.json',
                 'offline-causal-audit.json', 'fault-depth-review.json',
                 'terminal-quality.json')
        for name in names:
            shutil.copy2(RAW / name, staged / name)
        write(staged / 'terminal-seal.json', {
            'schema_version': 1, 'case_id': 'SOLR-13', 'status': result['status'],
            'fault_trials_completed': result['fault_trials_completed'],
            'source_campaign': str(RAW.relative_to(BASE)),
            'compact_files_sha256': {name: sha(staged / name) for name in names},
            'archive_sha256': sha(ARCHIVE),
            'member_manifest_sha256': sha(MANIFEST),
            'archive_receipt_sha256': sha(RECEIPT),
            'plan_depth_distribution': depth['depth_distribution'],
            'audit_report_gate_passed': quality['audit_report_gate_passed']})
        os.replace(staged, CANONICAL)
        return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
