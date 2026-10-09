#!/usr/bin/env python3
"""Migrate ZK13 feedback at a stopped original-JUnit boundary.

The fault selector keeps its exact channel/connection generation. Only the
coverage-guidance I/O family drops that ephemeral generation. A single
interrupted trial with no run.json can be archived and requeued; completed
trials, their plans, actor verdicts, and raw artifacts remain unchanged.
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
ARCHIVE = ROOT / 'feedback-migration-normalized-family'
BEFORE = 'healthy_union_v2'
AFTER = 'healthy_union_normalized_io_v3'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    temp = path.with_suffix(path.suffix + '.migration-tmp')
    with temp.open('wb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temp, path)


def migrate_state(state):
    if state.get('feedback_baseline') != BEFORE:
        raise RuntimeError('expected prior healthy-union checkpoint')
    old_results = json.loads(json.dumps(state['results']))
    interrupted = None
    if state['inflight']:
        if len(state['inflight']) != 1:
            raise RuntimeError('at most one original JUnit may be interrupted')
        interrupted = state['inflight'][0]
        expected_id = 'trial-{:04d}'.format(len(state['results']) + 1)
        if interrupted['run_id'] != expected_id or state['next_trial'] != len(state['results']) + 2:
            raise RuntimeError('interrupted trial is not exactly after completed prefix')
        path = ROOT / expected_id
        if (path / 'run.json').exists():
            raise RuntimeError('interrupted trial has a complete receipt; recover it first')
        if not path.is_dir():
            raise RuntimeError('interrupted raw trial directory missing')
        state['pending'].insert(0, {k: v for k, v in interrupted.items()
                                    if k not in ('run_id', 'worker_slot')})
        state['inflight'] = []
        state['next_trial'] -= 1
    state['status'] = 'paused_at_trial_boundary'
    healthy = ('healthy-a', 'healthy-b')
    coverage = set().union(*(set((ROOT / name / 'coverage.tsv').read_text().splitlines())
                             for name in healthy))
    families = {point['family'] for name in healthy
                for point in candidates(parse_events(ROOT / name / 'events.tsv'))}
    changes = []
    for item in state['results']:
        old = (item['new_coverage_lines'], item['new_io_families'])
        if item['effective']:
            run_dir = ROOT / item['run_id']
            observed_cov = set((run_dir / 'coverage.tsv').read_text().splitlines())
            rows = parse_events(run_dir / 'events.tsv')
            last = max((seq for seq, kind, _ in rows if kind == 'FAULT_APPLIED'), default=0)
            observed = {point['family'] for point in candidates(rows, last)}
            item['new_coverage_lines'] = len(observed_cov - coverage)
            item['new_io_families'] = len(observed - families)
            coverage.update(observed_cov)
            families.update(observed)
        else:
            item['new_coverage_lines'] = 0
            item['new_io_families'] = 0
        new = (item['new_coverage_lines'], item['new_io_families'])
        if old != new:
            changes.append({'run_id': item['run_id'], 'old': old, 'new': new})
    if any(a['plan'] != b['plan'] or a['effective'] != b['effective'] or
           a['run_id'] != b['run_id'] or a['strict_receipt'] != b['strict_receipt']
           for a, b in zip(old_results, state['results'])):
        raise RuntimeError('migration changed a completed plan or actor verdict')
    by_id = {item['run_id']: item for item in state['results']}
    for job in state['pending']:
        parent = by_id.get(job['parent'])
        if parent is None:
            if job['parent'] != 'healthy-a':
                raise RuntimeError('pending parent missing: ' + job['parent'])
            continue
        new_cov, new_io = parent['new_coverage_lines'], parent['new_io_families']
        job['score'] = (8.0 if new_cov else 2.0) + min(new_cov, 20) * 0.3 + \
            (5.0 if new_io else 0.0)
    state['seen_coverage'] = sorted(coverage)
    state['seen_families'] = sorted(families)
    state['schema'] = 4
    state['feedback_baseline'] = AFTER
    return interrupted, changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if MARKER.exists() or ARCHIVE.exists():
        raise RuntimeError('existing migration marker/archive requires manual audit')
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before_cp, before_ledger = CHECKPOINT.read_bytes(), LEDGER.read_bytes()
        state = json.loads(before_cp)
        if [json.loads(line) for line in before_ledger.splitlines()] != state['results']:
            raise RuntimeError('append-only ledger differs before migration')
        interrupted, changes = migrate_state(state)
        after_cp = (json.dumps(state, sort_keys=True, indent=2) + '\n').encode()
        after_ledger = b''.join((json.dumps(item, sort_keys=True) + '\n').encode()
                                for item in state['results'])
        summary = {'status': 'prepared', 'completed_trials': len(state['results']),
                   'effective': state['effective_count'],
                   'interrupted_requeued': interrupted['run_id'] if interrupted else None,
                   'feedback_changes': changes,
                   'checkpoint_before_sha256': sha(before_cp),
                   'ledger_before_sha256': sha(before_ledger),
                   'checkpoint_after_sha256': sha(after_cp),
                   'ledger_after_sha256': sha(after_ledger)}
        if not args.run:
            print(json.dumps(summary, sort_keys=True))
            return
        MARKER.write_text('normalized-family migration in progress\n')
        ARCHIVE.mkdir()
        (ARCHIVE / 'checkpoint.before.json').write_bytes(before_cp)
        (ARCHIVE / 'ledger.before.jsonl').write_bytes(before_ledger)
        if interrupted:
            shutil.move(str(ROOT / interrupted['run_id']),
                        str(ARCHIVE / (interrupted['run_id'] + '-interrupted')))
        atomic(CHECKPOINT, after_cp)
        atomic(LEDGER, after_ledger)
        if sha(CHECKPOINT.read_bytes()) != sha(after_cp) or \
                sha(LEDGER.read_bytes()) != sha(after_ledger):
            raise RuntimeError('post-migration SHA verification failed')
        summary['status'] = 'applied'
        (ARCHIVE / 'receipt.json').write_text(json.dumps(summary, sort_keys=True, indent=2)
                                               + '\n')
        MARKER.unlink()
        print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
