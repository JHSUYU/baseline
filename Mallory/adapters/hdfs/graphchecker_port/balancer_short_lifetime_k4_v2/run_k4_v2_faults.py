#!/usr/bin/env python3
"""Resume independent K4V2 policy one tool-selected fault at a time."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from run_k4_v2 import ROOT, CODE, CONFIG, CAMPAIGN, ENGINE_ROOT, PRIOR_RUNNER, sha as digest, CASE, LOCAL



def accepted_state() -> dict:
    stage = json.loads((ROOT / 'k4v2-stage-receipt.json').read_text())
    expected_config_sha = stage['config_sha256']
    if digest(CONFIG) != expected_config_sha:
        raise ValueError('K4V2 config SHA changed')
    gate = json.loads((ROOT / 'k4v2-healthy-gate.json').read_text())
    state = json.loads((CAMPAIGN / 'checkpoint.json').read_text())
    healthy_result = CAMPAIGN / 'trials/r0000/result.json'
    healthy_bundle = CAMPAIGN / 'trials/r0000/native-summary.json'
    anchors = json.loads(healthy_bundle.read_text()).get('anchors')
    if (gate['case_id'] != CASE or gate['imported_old_trials'] != 0 or
            gate['result_sha256'] != digest(healthy_result) or
            gate['bundle_sha256'] != digest(healthy_bundle) or
            not isinstance(anchors, list) or len(anchors) != 4 or
            gate['anchor_addresses'] != [row.get('occurrenceAddress')
                                         for row in anchors] or
            gate['anchor_graph_sha256'] != [digest(
                CAMPAIGN / 'trials/r0000/original-graph' /
                f'anchor-{index:02d}/summary.json') for index in range(4)] or
            gate['raw_exact_target_throw_count'] != 0 or
            state['case_id'] != CASE or state['scheduler_version'] != 11 or
            state['config_sha256'] != expected_config_sha or
            state['healthy']['status'] != 'healthy_seed' or
            state.get('predecessor_import') is not None or
            state['budget'] != {'fault_trials': 64,
                                'max_faults_per_trial': 6, 'seconds': 7200}):
        raise ValueError('K4V2 checkpoint/healthy provenance changed')
    return state


def archive_accepted(index: int) -> dict:
    """Verify each raw file against a tar member before removing its source."""
    result_dir = CAMPAIGN / 'trials' / f'r{index:04d}'
    result = json.loads((result_dir / 'result.json').read_text())
    if result['case_id'] != CASE or not result['faults']:
        raise ValueError('not an accepted fault result')
    archive = ROOT / f'raw-r{index:04d}.tar.gz'
    receipt_path = ROOT / f'raw-r{index:04d}-receipt.json'
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if (receipt['trial_index'] != index or receipt['archive_sha256'] !=
                digest(archive) or not receipt['verified_against_source']):
            raise ValueError('accepted raw archive changed')
        return receipt
    state = accepted_state()
    if state['completed_fault_trials'] < index or state['active'] is not None:
        raise ValueError('raw archive requires a complete checkpoint')
    if subprocess.run(['pgrep', '-x', 'java'], capture_output=True).stdout:
        raise RuntimeError('cannot archive with live Java')
    manifest = json.loads((result_dir / 'local-artifacts.json').read_text())
    raw = (LOCAL / 'raw').resolve(strict=True)
    attempt = Path(manifest['local_attempt_dir']).resolve(strict=True)
    if not attempt.is_relative_to(raw):
        raise ValueError('raw attempt escaped isolated destination')
    members = {}
    for path in [attempt, *attempt.rglob('*')]:
        name = str(path.relative_to(raw))
        if path.is_symlink():
            members[name] = ('symlink', os.readlink(path))
        elif path.is_file():
            members[name] = ('file', path.stat().st_size, digest(path))
        elif path.is_dir():
            members[name] = ('dir',)
        else:
            raise ValueError(f'unsupported raw member: {path}')
    partial = archive.with_suffix(archive.suffix + '.partial')
    if archive.exists() or partial.exists():
        raise RuntimeError('raw archive exists without verified receipt')
    with tarfile.open(partial, 'w:gz', dereference=False) as bundle:
        bundle.add(attempt, arcname=str(attempt.relative_to(raw)), recursive=True)
    seen = {}
    with tarfile.open(partial, 'r:gz') as bundle:
        for item in bundle:
            name = item.name.rstrip('/')
            if item.isfile():
                stream = bundle.extractfile(item)
                if stream is None:
                    raise ValueError('unreadable raw archive member')
                h = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1 << 20), b''):
                    h.update(chunk)
                seen[name] = ('file', item.size, h.hexdigest())
            elif item.issym():
                seen[name] = ('symlink', item.linkname)
            elif item.isdir():
                seen[name] = ('dir',)
            else:
                raise ValueError(f'unsupported archive member: {name}')
    if members != seen:
        raise ValueError('raw archive member mismatch; source retained')
    partial.rename(archive)
    receipt = {'case_id': CASE, 'trial_index': index,
               'result_sha256': digest(result_dir / 'result.json'),
               'checkpoint_sha256_at_archive': digest(CAMPAIGN / 'checkpoint.json'),
               'archive_sha256': digest(archive),
               'archive_size_bytes': archive.stat().st_size,
               'member_count': len(members), 'verified_against_source': True,
               'restore_command': f'tar -xzf {archive} -C {raw}'}
    with receipt_path.open('x') as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
        stream.write('\n')
    shutil.rmtree(attempt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--through', type=int, required=True)
    args = parser.parse_args()
    if not 1 <= args.through <= 64:
        raise ValueError('absolute stop must be within 1..64')
    sys.path.insert(0, str(PRIOR_RUNNER))
    from run_variant import run_guarded, require_ok

    state = accepted_state()
    for index in range(1, state['completed_fault_trials'] + 1):
        result = json.loads((CAMPAIGN / 'trials' / f'r{index:04d}' /
                             'result.json').read_text())
        if result.get('raw_exact_target_throw_count', 0):
            raise RuntimeError(f'existing exact throw at r{index:04d}; triage first')
        archive_accepted(index)
    for index in range(state['completed_fault_trials'] + 1, args.through + 1):
        state = accepted_state()
        if state['active'] is not None and state['active'].get('index') != index:
            raise ValueError('active trial index is not the next result')
        if state['completed_fault_trials'] != index - 1:
            raise ValueError('noncontiguous K4V2 checkpoint')
        attempt = 1
        while (ROOT / f'fault-r{index:04d}-attempt{attempt}.log').exists():
            attempt += 1
        env = dict(os.environ, PYTHONPATH=str(CODE),
                   MALLORY_NATIVE_ENGINE_ROOT=str(ENGINE_ROOT))
        cmd = [sys.executable, '-m', 'Mallory.native_graphchecker_campaign',
               '--config', str(CONFIG), '--output', str(CAMPAIGN),
               '--stop-after-fault-trials', str(index)]
        receipt = run_guarded(cmd, log=ROOT / f'fault-r{index:04d}-attempt{attempt}.log',
                              cwd=ROOT, timeout=1800, env=env)
        receipt_path = ROOT / f'fault-r{index:04d}-attempt{attempt}.json'
        with receipt_path.open('x') as stream:
            json.dump(receipt, stream, sort_keys=True, indent=2)
            stream.write('\n')
        require_ok(receipt)
        state = accepted_state()
        if state['completed_fault_trials'] != index or state['active'] is not None:
            raise RuntimeError('native bounded run did not accept one result')
        result_file = CAMPAIGN / 'trials' / f'r{index:04d}/result.json'
        result = json.loads(result_file.read_text())
        if result.get('raw_exact_target_throw_count', 0):
            with (ROOT / 'k4v2-stop-new-exact-throw.json').open('x') as stream:
                json.dump({'case_id': CASE, 'trial_index': index,
                           'result_sha256': digest(result_file),
                           'strict_injection': result.get('strict_injection'),
                           'post_fault_target_check_observed': result.get(
                               'post_fault_target_check_observed'),
                           'raw_exact_target_throw_count': result[
                               'raw_exact_target_throw_count'],
                           'campaign_elapsed_seconds_at_detection': state[
                               'elapsed_seconds'],
                           'result_file_mtime_ns': result_file.stat().st_mtime_ns,
                           'detected_in_bounded_process_elapsed_seconds': receipt[
                               'elapsed_seconds']}, stream,
                          sort_keys=True, indent=2)
                stream.write('\n')
            return
        archive_accepted(index)
    final = accepted_state()
    if final['completed_fault_trials'] != args.through:
        raise RuntimeError('K4V2 bounded continuation lost trials')


if __name__ == '__main__':
    main()
