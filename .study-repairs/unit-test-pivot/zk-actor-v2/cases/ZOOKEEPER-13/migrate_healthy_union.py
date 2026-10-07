#!/usr/bin/env python3
"""At a stopped trial boundary, correct feedback to both healthy seeds' union.

This changes only derived coverage/I/O scores. Original JUnit runs, ordered
fault plans, actor receipts, effectiveness, and trial IDs stay byte-for-byte.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil

from calibrate_healthy import ROOT
from campaign import CHECKPOINT, LEDGER, LOCK, candidates, parse_events

MARKER = ROOT / 'feedback-migration-in-progress'
ARCHIVE = ROOT / 'feedback-migration-healthy-union'


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    temp = path.with_suffix(path.suffix + '.migration-tmp')
    with temp.open('wb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def recompute(state):
    healthy_names = ('healthy-a', 'healthy-b')
    coverage = set().union(*(
        set((ROOT / name / 'coverage.tsv').read_text().splitlines())
        for name in healthy_names))
    families = {point['family'] for name in healthy_names
                for point in candidates(parse_events(ROOT / name / 'events.tsv'))}
    changes = []
    for item in state['results']:
        old_cov, old_io = item['new_coverage_lines'], item['new_io_families']
        if item['effective']:
            run_dir = ROOT / item['run_id']
            observed_cov = set((run_dir / 'coverage.tsv').read_text().splitlines())
            rows = parse_events(run_dir / 'events.tsv')
            last = max((seq for seq, kind, _ in rows if kind == 'FAULT_APPLIED'), default=0)
            observed_families = {point['family'] for point in candidates(rows, last)}
            item['new_coverage_lines'] = len(observed_cov - coverage)
            item['new_io_families'] = len(observed_families - families)
            coverage.update(observed_cov)
            families.update(observed_families)
        else:
            item['new_coverage_lines'] = 0
            item['new_io_families'] = 0
        if (old_cov, old_io) != (item['new_coverage_lines'], item['new_io_families']):
            changes.append({'run_id': item['run_id'],
                            'old': [old_cov, old_io],
                            'new': [item['new_coverage_lines'], item['new_io_families']]})
    by_id = {item['run_id']: item for item in state['results']}
    for job in state['pending']:
        parent = by_id.get(job['parent'])
        if parent is None:
            if job['parent'] != 'healthy-a':
                raise RuntimeError('pending mutation parent missing: ' + job['parent'])
            continue
        new_cov = parent['new_coverage_lines']
        new_io = parent['new_io_families']
        job['score'] = ((8.0 if new_cov else 2.0) + min(new_cov, 20) * 0.3
                        + (5.0 if new_io else 0.0))
    state['seen_coverage'] = sorted(coverage)
    state['seen_families'] = sorted(families)
    state['schema'] = 3
    state['feedback_baseline'] = 'healthy_union_v2'
    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true', help='apply only at a stopped boundary')
    args = parser.parse_args()
    if MARKER.exists() or ARCHIVE.exists():
        raise RuntimeError('migration marker or previous archive exists; inspect before rerun')
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        checkpoint_before = CHECKPOINT.read_bytes()
        ledger_before = LEDGER.read_bytes()
        state = json.loads(checkpoint_before)
        if state['status'] != 'paused_at_trial_boundary' or state['inflight']:
            raise RuntimeError('campaign must be stopped after a complete pilot trial')
        if state.get('feedback_baseline') == 'healthy_union_v2':
            raise RuntimeError('checkpoint already uses two healthy seeds')
        if [json.loads(line) for line in ledger_before.splitlines()] != state['results']:
            raise RuntimeError('append-only ledger differs before migration')
        old_results = json.loads(json.dumps(state['results']))
        old_plans = [item['plan'] for item in old_results]
        changes = recompute(state)
        if [item['plan'] for item in state['results']] != old_plans or \
                any(a['effective'] != b['effective'] or a['run_id'] != b['run_id']
                    for a, b in zip(old_results, state['results'])):
            raise RuntimeError('migration attempted to change original trial verdict or plan')
        new_checkpoint = (json.dumps(state, sort_keys=True, indent=2) + '\n').encode()
        new_ledger = b''.join((json.dumps(item, sort_keys=True) + '\n').encode()
                              for item in state['results'])
        summary = {'status': 'prepared', 'completed_trials': len(state['results']),
                   'effective': state['effective_count'], 'feedback_changes': changes,
                   'checkpoint_before_sha256': sha_bytes(checkpoint_before),
                   'ledger_before_sha256': sha_bytes(ledger_before),
                   'checkpoint_after_sha256': sha_bytes(new_checkpoint),
                   'ledger_after_sha256': sha_bytes(new_ledger)}
        if not args.run:
            print(json.dumps(summary, sort_keys=True))
            return
        MARKER.write_text('migration in progress\n')
        ARCHIVE.mkdir()
        (ARCHIVE / 'checkpoint.before.json').write_bytes(checkpoint_before)
        (ARCHIVE / 'ledger.before.jsonl').write_bytes(ledger_before)
        atomic(CHECKPOINT, new_checkpoint)
        atomic(LEDGER, new_ledger)
        if sha_bytes(CHECKPOINT.read_bytes()) != summary['checkpoint_after_sha256'] or \
                sha_bytes(LEDGER.read_bytes()) != summary['ledger_after_sha256']:
            raise RuntimeError('migration write verification failed; marker retained')
        summary['status'] = 'applied'
        (ARCHIVE / 'receipt.json').write_text(json.dumps(summary, sort_keys=True, indent=2)
                                               + '\n')
        MARKER.unlink()
        print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
