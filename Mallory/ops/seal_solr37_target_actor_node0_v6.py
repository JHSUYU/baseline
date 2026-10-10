#!/usr/bin/env python3
"""Attest and SHA-seal the terminal SOLR-37 actor-aware continuation."""

from __future__ import annotations

from collections import Counter
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile

BASE = Path('/users/ZhenyuLi/baseline')
PACKAGE = BASE / 'Mallory/adapters/solr/cases/SOLR-37/target-actor-full-node0-v6'
RAW = BASE / 'data/mallory/solr37_target_actor_full_v6_node0/SOLR-37/full'
ARCHIVES = BASE / 'data/mallory/evidence_archives'
PREFIX = 'SOLR-37-target-actor-full-node0-v6'
ARCHIVE = ARCHIVES / f'{PREFIX}.tar.gz'
MEMBERS = ARCHIVES / f'{PREFIX}.members.json'
RECEIPT = ARCHIVES / f'{PREFIX}.receipt.json'
QUALITY = RAW / 'terminal-quality.json'
DEPTH = RAW / 'fault-depth-review.json'
LOCK = Path('/tmp/mallory-lanes/solr-node0-v1.lock')
FLOOR = 7_650_410_496
EXACT_THROW_SITE = (
    'org.apache.solr.update.processor.DistributedZkUpdateProcessor'
    '#doDefensiveChecks(Lorg/apache/solr/update/processor/'
    'DistributedUpdateProcessor$DistribPhase;)V@995:throw:1')
sys.path.insert(0, str(PACKAGE))
import run_campaign as runner  # noqa: E402


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def write_once(path: Path, value: dict) -> None:
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
    metadata = runner.preflight()
    result = read(RAW / 'result.json')
    checkpoint = read(RAW / 'checkpoint.json')
    admission = read(PACKAGE / 'admission-full-node0.json')
    imported = read(RAW / 'parent-import.json')
    parent_manifest = read(BASE / 'data/mallory/evidence_archives/SOLR-37-target-actor-pilot-node0-v5.members.json')
    parent_members = {row['path']: row for row in parent_manifest['members']}
    if not (result.get('case_id') == checkpoint.get('case_id') == 'SOLR-37'
            and result.get('status') == checkpoint.get('status')
            and result['status'] in {'budget_exhausted', 'queue_exhausted'}
            and checkpoint.get('running') is None
            and read(RAW / 'config.json') == read(PACKAGE / 'config-full-node0.json')
            and admission.get('go') is True and admission.get('host') == 'node0'
            and admission.get('mode') == 'full' and admission.get('case_id') == 'SOLR-37'
            and admission.get('intended_output') == str(RAW)
            and admission.get('config_sha256') == metadata['config_sha256']
            and admission.get('runner_sha256') == metadata['runner_sha256']
            and imported.get('imported_trials') == [0, 1, 2]
            and imported.get('excluded_unmatched_parent_trials') == [3, 4, 5, 6]
            and imported.get('parent_archive_sha256') == metadata['parent_archive_sha256']
            and result.get('new_bug') is not True):
        raise RuntimeError('terminal status, parent import, config, or GO mismatch')

    completed = checkpoint['completed_trials']
    if completed[:3] != [0, 1, 2] or completed[3:] != list(range(7, 7 + len(completed[3:]))):
        raise RuntimeError('continuation trial sequence changed')
    valid = []
    invalid = []
    junit_qualified = []
    path_valid_junit_invalid = []
    junit_invalid_novelty = []
    depths = Counter()
    reasons = Counter()
    rows = []
    raw_exact_throws = []
    junit_nonpassing = []
    missing_audit = []
    parent_prefix = 'solr37_target_actor_fault_pilot_v5_node0/SOLR-37/pilot/'
    for number in completed:
        root = RAW / 'trials' / f'r{number:04d}'
        trial = read(root / 'result.json')
        audit_path = root / 'strict-audit.json'
        audit = read(audit_path) if audit_path.is_file() else {
            'valid': False, 'reason': 'audit_missing'}
        trace = root / 'events.jsonl.gz'
        feedback = trial['feedback']
        trial_raw_throws = []
        with gzip.open(trace, 'rt') as stream:
            for line in stream:
                event = json.loads(line)
                if event.get('type') == 'TARGET_THROW' and event.get('site') == EXACT_THROW_SITE:
                    trial_raw_throws.append({
                        'trial_id': number, 'event_id': event.get('id'),
                        'seq': event.get('seq'), 'node': event.get('node'),
                        'epoch': event.get('epoch'),
                        'exception_class': event.get('exception_class')})
        raw_exact_throws.extend(trial_raw_throws)
        if not (trial.get('trial_id') == number
                and isinstance(trial.get('plan'), list)
                and trial['events_evidence']['gzip_sha256'] == sha(trace)):
            raise RuntimeError(f'r{number:04d} trial/audit/trace mismatch')
        if audit_path.is_file():
            if trial.get('strict_audit') != audit:
                raise RuntimeError(f'r{number:04d} strict audit sidecar differs')
        elif number < 3 or trial.get('strict_audit') not in (None, {}):
            raise RuntimeError(f'r{number:04d} strict audit absence differs')
        if number >= 7 and not audit_path.is_file():
            missing_audit.append(number)
        if number < 3:
            for name in ('result.json', 'plan.json', 'strict-audit.json',
                         'events.jsonl.gz', 'junit-receipt.json', 'sites.jsonl',
                         'stdout.log', 'stderr.log'):
                path = root / name
                member = parent_members.get(parent_prefix + f'trials/r{number:04d}/' + name)
                if not member or path.stat().st_size != member['bytes'] or sha(path) != member['sha256']:
                    raise RuntimeError(f'imported r{number:04d}/{name} differs from sealed parent')
            if not audit.get('valid') or number and not feedback.get('all_faults_effective'):
                raise RuntimeError(f'imported r{number:04d} was not valid in parent')
        else:
            junit = trial.get('junit_validation', {})
            junit_passed = (trial.get('return_code') == 0 and trial.get('timed_out') is False
                            and junit.get('status') == 'passed'
                            and (junit.get('tests'), junit.get('failures'),
                                 junit.get('errors'), junit.get('skipped')) == (1, 0, 0, 0))
            if (root / 'junit.log').is_file() and junit.get('junit_log_sha256') and \
                    junit['junit_log_sha256'] != sha(root / 'junit.log'):
                raise RuntimeError(f'r{number:04d} JUnit log SHA changed')
            if not junit_passed:
                junit_nonpassing.append(number)
                novelty = trial.get('novelty', {})
                if any(novelty.get(key, 0) for key in ('coverage', 'closure_coverage', 'closure_edges')):
                    junit_invalid_novelty.append({'trial_id': number, **novelty})
            if audit.get('valid'):
                if not (feedback.get('all_faults_matched') is True
                        and feedback.get('all_faults_applied') is True
                        and feedback.get('all_faults_effective') is True
                        and feedback.get('target_reached') is True
                        and audit.get('reason') == 'strict_fault_and_postfault_target'
                        and audit.get('postfault_target_count', 0) > 0
                        and audit.get('strict_witness_count', 0) > 0):
                    raise RuntimeError(f'r{number:04d} strict fault or target changed')
                valid.append(number)
                if junit_passed:
                    junit_qualified.append(number)
                else:
                    path_valid_junit_invalid.append(number)
            else:
                if audit_path.is_file() and (feedback.get('all_faults_effective') is not False
                                             or feedback.get('target_exception_candidate') is not False):
                    raise RuntimeError(f'r{number:04d} invalid trial got candidate credit')
                if not audit_path.is_file() and number in checkpoint.get('target_exception_candidates', []):
                    raise RuntimeError(f'r{number:04d} unaudited trial got candidate credit')
                invalid.append(number)
        if number:
            depths[str(len(trial['plan']))] += 1
        reasons[audit['reason']] += 1
        rows.append({'trial_id': number, 'origin': 'sealed_v5' if number < 3 else 'v6',
                     'depth': len(trial['plan']), 'strict_audit_valid': audit['valid'],
                     'strict_audit_reason': audit['reason'],
                     'all_faults_effective': feedback.get('all_faults_effective'),
                     'target_reached': feedback.get('target_reached'),
                     'target_threw': feedback.get('target_threw'),
                     'postfault_target_count': audit.get('postfault_target_count', 0),
                     'junit_status': trial.get('junit_validation', {}).get('status'),
                     'novelty': trial.get('novelty'),
                     'raw_exact_target_throw_count': len(trial_raw_throws),
                     'result_sha256': sha(root / 'result.json'),
                     'strict_audit_sha256': sha(audit_path) if audit_path.is_file() else None,
                     'trace_sha256': sha(trace)})

    candidates = result.get('target_exception_candidate_trials', [])
    if sorted(candidates) != sorted(checkpoint.get('target_exception_candidates', [])):
        raise RuntimeError('candidate counts differ between result and checkpoint')
    for number in candidates:
        if number not in valid:
            raise RuntimeError('candidate lacks valid v6 strict audit')
        trial = read(RAW / 'trials' / f'r{number:04d}/result.json')
        if not (trial['feedback'].get('target_exception_candidate') is True
                and trial['feedback'].get('target_threw') is True
                and trial['strict_audit'].get('exact_postfault_target_throws')):
            raise RuntimeError(f'r{number:04d} exact target throw lacks strict proof')
    depth = {'schema_version': 1, 'case_id': 'SOLR-37',
             'scope': 'actor_aware_full_v6_fault_depth',
             'status': result['status'],
             'controller_release_manifest_sha256': sha(runner.RELEASE / 'manifest.json'),
             'scheduler_sha256': sha(runner.RELEASE / 'Mallory/core/scheduler.py'),
             'campaign_result_sha256': sha(RAW / 'result.json'),
             'campaign_checkpoint_sha256': sha(RAW / 'checkpoint.json'),
             'depth_distribution': dict(depths),
             'strict_reason_distribution': dict(reasons),
             'trials': rows}
    quality = {'schema_version': 1, 'case_id': 'SOLR-37',
               'scope': 'actor_aware_full_continuation_v6',
               'status': result['status'],
               'duration_seconds': result['duration_seconds'],
               'fault_trials_completed': result['fault_trials_completed'],
               'strict_injected_trials': result['strict_injected_trials'],
               'strict_target_trials': result['strict_target_trials'],
               'strict_new_valid_trials': valid,
               'strict_new_junit_qualified_trials': junit_qualified,
               'strict_new_path_valid_junit_invalid_trials': path_valid_junit_invalid,
               'junit_qualified_strict_trials_including_imported': [1, 2, *junit_qualified],
               'junit_invalid_novelty_credit': junit_invalid_novelty,
               'guidance_consistent_with_junit_gate': not junit_invalid_novelty,
               'strict_new_invalid_trials': invalid,
               'new_missing_audit_trials': missing_audit,
               'exact_target_exception_trials': candidates,
               'raw_exact_target_throw_site': EXACT_THROW_SITE,
               'raw_exact_target_throw_events': raw_exact_throws,
               'raw_exact_target_throw_trials': sorted({row['trial_id'] for row in raw_exact_throws}),
               'raw_throw_without_strict_candidate_trials': sorted(
                   {row['trial_id'] for row in raw_exact_throws} - set(candidates)),
               'new_junit_nonpassing_trials': junit_nonpassing,
               'excluded_unmatched_parent_trials': [3, 4, 5, 6],
               'imported_valid_parent_trials': [0, 1, 2],
               'parent_archive_sha256': imported['parent_archive_sha256'],
               'plan_depth_distribution': dict(depths),
               'campaign_completion_credited': True,
               'source_review_status': ('pending' if candidates or raw_exact_throws
                                        else 'not_needed_no_exact_exception'),
               'new_bug': None if candidates or raw_exact_throws else False}
    return result, depth, quality


def verify_archive(path: Path, members: list[dict]) -> None:
    with tarfile.open(path, 'r:gz') as archive:
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


def seal() -> dict:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result, depth, quality = attest()
        write_once(DEPTH, depth)
        write_once(QUALITY, quality)
        files = sorted(path for path in RAW.rglob('*')
                       if path.is_file() and path.name != '.campaign.lock')
        if not files or any(path.is_symlink() for path in files):
            raise RuntimeError('raw campaign empty or symlinked')
        prefix = 'solr37_target_actor_full_v6_node0/SOLR-37/full/'
        members = [{'path': prefix + path.relative_to(RAW).as_posix(),
                    'bytes': path.stat().st_size, 'sha256': sha(path)} for path in files]
        reserve = FLOOR + 64 * 1024**2
        ARCHIVES.mkdir(parents=True, exist_ok=True)
        temporary = ARCHIVE.with_name(ARCHIVE.name + '.tmp')
        # The archive may already be sealed if a previous process stopped
        # after its atomic rename but before writing the two JSON receipts.
        # Reverify it against fresh raw SHAs and finish those receipts.
        if ARCHIVE.exists():
            verify_archive(ARCHIVE, members)
            temporary.unlink(missing_ok=True)
        else:
            temporary.unlink(missing_ok=True)
            if shutil.disk_usage(BASE).free < reserve:
                raise RuntimeError('archive start lacks node0 disk reserve')
            try:
                with tarfile.open(temporary, 'w:gz') as archive:
                    for path, row in zip(files, members):
                        # Preserve the reserve at every write without requiring
                        # free space for an uncompressed duplicate of all raw.
                        if shutil.disk_usage(BASE).free < reserve + row['bytes'] + 2 * 1024**2:
                            raise RuntimeError('next archive member may breach node0 disk reserve')
                        info = tarfile.TarInfo(row['path'])
                        info.size = row['bytes']
                        info.mode = 0o600
                        info.mtime = 0
                        with path.open('rb') as stream:
                            archive.addfile(info, stream)
                        archive.fileobj.flush()
                        if shutil.disk_usage(BASE).free < reserve:
                            raise RuntimeError('archive write approached node0 disk reserve')
                verify_archive(temporary, members)
                if sha(RAW / 'result.json') != depth['campaign_result_sha256'] or shutil.disk_usage(BASE).free < reserve:
                    raise RuntimeError('result changed or disk reserve breached')
                os.replace(temporary, ARCHIVE)
            finally:
                temporary.unlink(missing_ok=True)
        write_once(MEMBERS, {'schema_version': 1, 'case_id': 'SOLR-37',
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
                   'config_sha256': sha(PACKAGE / 'config-full-node0.json'),
                   'runner_sha256': sha(PACKAGE / 'run_campaign.py'),
                   'manifest_sha256': sha(PACKAGE / 'sha-manifest.json'),
                   'sealer_sha256': sha(Path(__file__)),
                   'all_archive_members_verified': True}
        write_once(RECEIPT, receipt)
        return receipt


if __name__ == '__main__':
    print(json.dumps(seal(), sort_keys=True))
