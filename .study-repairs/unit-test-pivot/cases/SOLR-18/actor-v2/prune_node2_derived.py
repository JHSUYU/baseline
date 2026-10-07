#!/usr/bin/env python3
"""Reclaim old mirrored JaCoCo text after independent raw SHA audits."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re

from build import HERE
from mirror import NODE2_LOCAL, RECEIPT as MIRROR
from run_native import RUN_ROOT

STATE = HERE / 'campaign-state.json'
AUDIT = HERE / 'final-audit.json'
RECEIPT = HERE / 'derived-prune-receipt.json'
DERIVED = ('covered_probes.txt', 'covered_methods.txt', 'covered_lines.txt')


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--node0-pre-audit-sha', required=True)
    args = parser.parse_args()
    assert NODE2_LOCAL, 'run only on node2'
    assert re.fullmatch(r'[0-9a-f]{64}', args.node0_pre_audit_sha)
    assert not RECEIPT.exists(), 'derived prune receipt already exists'
    state = json.loads(STATE.read_text())
    audit = json.loads(AUDIT.read_text())
    mirror = json.loads(MIRROR.read_text())
    assert state['inflight'] is None
    assert audit['checkpoint_complete'] and not audit['unreviewed_outcomes']
    assert audit['attempts'] == state['attempts']
    assert audit['effective_fault_trials'] == state['effective']
    assert audit['raw_archive_pending_node0_pull_runs'] == []
    assert audit['node0_archive_verified_runs'] == state['attempts'] - 189
    runs: dict[str, dict] = {}
    for trial in state['trials']:
        run_id = trial['run_id']
        if int(run_id.split('-')[1]) > 189:
            continue
        source = mirror['runs'][run_id]
        assert source.get('archive_status') is None
        assert source['rsync_checksum_dry_run_exit'] == 0
        assert source['rsync_checksum_dry_run_output'] == ''
        files = {}
        for name in DERIVED:
            if name not in source['sha256']:
                continue
            path = RUN_ROOT / run_id / name
            assert path.is_file(), path
            actual = sha(path)
            assert actual == source['sha256'][name], path
            files[name] = {'sha256': actual, 'size_bytes': path.stat().st_size}
        if files:
            runs[run_id] = {'files': files}
    assert runs, 'nothing to prune'
    receipt = {
        'schema_version': 1, 'case_id': 'SOLR-18',
        'node': 'node2',
        'prepared_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'checkpoint_attempts': state['attempts'],
        'checkpoint_effective': state['effective'],
        'node0_pre_prune_independent_audit_sha256': args.node0_pre_audit_sha,
        'node2_pre_prune_independent_audit_sha256': sha(AUDIT),
        'mirror_receipt_sha256': sha(MIRROR),
        'source_raw_and_jacoco_retained_on_node2': True,
        'original_raw_mirror_verified_from_node0': True,
        'regenerable_from_jacoco': True,
        'runs': runs,
        'file_count': sum(len(entry['files']) for entry in runs.values()),
        'file_bytes': sum(file['size_bytes'] for entry in runs.values()
                          for file in entry['files'].values()),
    }
    temp = RECEIPT.with_suffix('.json.tmp')
    temp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    os.replace(temp, RECEIPT)
    for run_id, entry in runs.items():
        for name, file in entry['files'].items():
            path = RUN_ROOT / run_id / name
            assert sha(path) == file['sha256']
            path.unlink()
    print(json.dumps({'checkpoint_attempts': state['attempts'],
                      'checkpoint_effective': state['effective'],
                      'runs': len(runs),
                      'files_pruned': receipt['file_count'],
                      'bytes_pruned': receipt['file_bytes']}, sort_keys=True))


if __name__ == '__main__':
    main()
