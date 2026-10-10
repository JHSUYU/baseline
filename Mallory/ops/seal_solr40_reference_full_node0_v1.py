#!/usr/bin/env python3
"""Seal a naturally terminal SOLR-40 reference-path campaign without pruning raw data."""

from __future__ import annotations

from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile


BASE = Path('/users/ZhenyuLi/baseline')
RAW = BASE / 'data/mallory/solr40_reference_full_v1_node0/SOLR-40'
CANONICAL = BASE / 'data/mallory/cases/SOLR-40'
PACKAGE = BASE / 'Mallory/adapters/solr/cases/SOLR-40/full-reference-handoff-node0-v1'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-40-reference-full-node0-v1'
ARCHIVE = ARCHIVES / (PREFIX + '.tar.gz')
MANIFEST = ARCHIVES / (PREFIX + '.members.json')
RECEIPT = ARCHIVES / (PREFIX + '.receipt.json')
DEPTH = RAW / 'fault-depth-review.json'
QUALITY = RAW / 'terminal-quality.json'
LOCK = Path('/tmp/mallory-lanes/solr-node0-v1.lock')
TERMINAL = {'budget_exhausted', 'queue_exhausted'}
FLOOR = 7_650_410_496


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def attest() -> tuple[dict, dict, dict, dict]:
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    config = read(RAW / 'config.json')
    audit = read(RAW / 'offline-causal-audit.json')
    gate = read(RAW / 'fresh-r0000-gate.json')
    admission = read(PACKAGE / 'admission-full-node0.json')
    completed = checkpoint.get('completed_trials')
    count = result.get('fault_trials_completed')
    if (result.get('case_id') != 'SOLR-40'
            or result.get('status') not in TERMINAL
            or checkpoint.get('status') != result['status']
            or checkpoint.get('running') is not None
            or checkpoint.get('calibration_only') is not False
            or result.get('calibration_only') is not False
            or result.get('healthy_seed_valid') is not True
            or not isinstance(count, int) or not 0 < count <= 80
            or not isinstance(completed, list) or completed != list(range(count + 1))
            or result.get('new_bug') is True
            or not isinstance(result.get('exact_exception_trials'), int)
            or not isinstance(result.get('target_exception_candidate_trials'), list)
            or not isinstance(result.get('reproduced_candidates'), list)
            or result.get('healthy_junit_validation', {}).get('status') != 'passed'
            or gate.get('status') != 'fresh_r0000_admitted'
            or gate.get('named_exact_target_checks', 0) <= 0
            or gate.get('named_observed_watcher_doors', 0) <= 0
            or not gate.get('exact_reference_witnesses')
            or checkpoint.get('promoted_healthy_gate_sha256') != sha(RAW / 'fresh-r0000-gate.json')
            or config != read(PACKAGE / 'config.json')
            or admission.get('go') is not True
            or admission.get('case_id') != 'SOLR-40'
            or admission.get('mode') != 'full'
            or admission.get('host') != 'node0'
            or admission.get('intended_output') != str(RAW)
            or admission.get('config_sha256') != sha(PACKAGE / 'config.json')
            or admission.get('runner_sha256') != sha(PACKAGE / 'run_full.py')
            or admission.get('agent_jar_sha256') != sha(PACKAGE / 'releases/mallory-agent.jar')
            or audit.get('campaign_result_sha256') != sha(RAW / 'result.json')
            or audit.get('case_id') != 'SOLR-40'
            or audit.get('terminal_status') != result['status']
            or audit.get('trial_count') != count + 1):
        raise RuntimeError('terminal result, fresh gate, audit, or admission mismatch')

    distribution: Counter[str] = Counter()
    trials = []
    for number in range(count + 1):
        trial_id = f'r{number:04d}'
        path = RAW / 'trials' / trial_id / 'result.json'
        trial = read(path)
        evidence = trial.get('events_evidence') or {}
        trace = RAW / 'trials' / trial_id / evidence.get('gzip_path', '')
        plan = trial.get('plan')
        if (trial.get('case_id') != 'SOLR-40'
                or trial.get('trial_id') != number
                or not isinstance(plan, list)
                or (number == 0 and plan != [])
                or (number > 0 and not 1 <= len(plan) <= 3)
                or not trace.is_file()
                or trace.parent != path.parent
                or evidence.get('gzip_sha256') != sha(trace)):
            raise RuntimeError(f'invalid trial, plan, or trace: {trial_id}')
        if number:
            distribution[str(len(plan))] += 1
            trials.append({'trial_id': number, 'depth': len(plan),
                           'result_sha256': sha(path)})
    if sum(distribution.values()) != count:
        raise RuntimeError('fault depth distribution differs from completed trial count')

    pinned = config.get('mapping', {}).get('pinned_core') or {}
    root = Path(pinned.get('root', ''))
    files = pinned.get('files') or {}
    scheduler = root / 'Mallory/core/scheduler.py'
    if (not root.is_dir() or not files
            or files.get('Mallory/core/scheduler.py') != sha(scheduler)
            or any(sha(root / name) != digest for name, digest in files.items())):
        raise RuntimeError('pinned controller files differ from config')
    depth = {'schema_version': 1, 'case_id': 'SOLR-40',
             'scope': 'fault_plan_depth_and_pinned_controller_provenance',
             'status': result['status'], 'fault_trials_completed': count,
             'campaign_result_sha256': sha(RAW / 'result.json'),
             'campaign_checkpoint_sha256': sha(RAW / 'checkpoint.json'),
             'campaign_config_sha256': sha(RAW / 'config.json'),
             'pinned_core_root': str(root), 'pinned_core_files_sha256': files,
             'scheduler_sha256': sha(scheduler),
             'single_fault_breadth_interval': config.get('single_fault_breadth_interval'),
             'multi_fault_exploration_interval': config.get('multi_fault_exploration_interval'),
             'depth_distribution': dict(sorted(distribution.items())), 'trials': trials}
    quality = {'schema_version': 1, 'case_id': 'SOLR-40',
               'status': result['status'], 'duration_seconds': result['duration_seconds'],
               'fault_trials_completed': count,
               'strict_injected_trials': result.get('strict_injected_trials'),
               'strict_target_trials': result.get('strict_target_trials'),
               'exact_exception_trials': result['exact_exception_trials'],
               'target_exception_candidates': len(result['target_exception_candidate_trials']),
               'reproduced_candidates': len(result['reproduced_candidates']),
               'fresh_healthy_gate_sha256': sha(RAW / 'fresh-r0000-gate.json'),
               'offline_audit_sha256': sha(RAW / 'offline-causal-audit.json'),
               'audit_report_gate_passed': audit.get('report_gate_passed'),
               'audit_guidance_consistent': audit.get('guidance_consistent'),
               'audit_archive_integrity_valid': audit.get('archive_integrity_valid'),
               'audit_applied_fault_identity_valid': audit.get('applied_fault_identity_valid'),
               'audit_target_claims_reverified': audit.get('target_claims_reverified'),
               'audit_healthy_closure_proven': audit.get('healthy_closure_proven'),
               'audit_same_actor_target_gate_passed': audit.get('same_actor_target_gate_passed'),
               'plan_depth_distribution': dict(sorted(distribution.items())),
               'new_bug': False}
    return result, checkpoint, depth, quality


def seal() -> dict:
    if any(path.exists() for path in (ARCHIVE, MANIFEST, RECEIPT, CANONICAL, DEPTH, QUALITY)):
        raise FileExistsError('SOLR-40 full seal or canonical import already exists')
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, checkpoint, depth, quality = attest()
        write(DEPTH, depth)
        write(QUALITY, quality)
        files = sorted(path for path in RAW.rglob('*') if path.is_file()
                       and path.name != '.campaign.lock')
        if (not files or any(path.is_symlink() or path.name.endswith('.tmp')
                             for path in files)):
            raise RuntimeError('raw evidence empty, symlinked, or temporary')
        members = [{'path': 'solr40_reference_full_v1_node0/SOLR-40/' +
                    path.relative_to(RAW).as_posix(), 'bytes': path.stat().st_size,
                    'sha256': sha(path)} for path in files]
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
                    if (not item.isfile() or item.size != row['bytes'] or stream is None):
                        raise RuntimeError('archive member absent or size differs')
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
        write(MANIFEST, {'schema_version': 1, 'case_id': 'SOLR-40',
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
                   'main_core_audit_sha256': sha(RAW / 'offline-causal-audit-main-core.json'),
                   'admission_receipt_sha256': sha(PACKAGE / 'admission-full-node0.json'),
                   'package_config_sha256': sha(PACKAGE / 'config.json'),
                   'package_runner_sha256': sha(PACKAGE / 'run_full.py'),
                   'all_archive_members_verified': True}
        write(RECEIPT, receipt)
        staged = CANONICAL.with_name('.SOLR-40.full-import')
        staged.mkdir(parents=True, exist_ok=False)
        names = ('config.json', 'result.json', 'checkpoint.json',
                 'offline-causal-audit.json', 'fresh-r0000-gate.json',
                 'fault-depth-review.json', 'terminal-quality.json')
        for name in names:
            shutil.copy2(RAW / name, staged / name)
        write(staged / 'terminal-seal.json', {
            'schema_version': 1, 'case_id': 'SOLR-40', 'status': result['status'],
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
