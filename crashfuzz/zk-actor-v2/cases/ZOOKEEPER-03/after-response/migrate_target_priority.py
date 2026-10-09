#!/usr/bin/env python3
"""Preserve the pilot prefix and prioritize target-retaining descendants.

This one-time migration runs only with the original JUnit controller stopped.
It archives at most one interrupted, unreceipted trial and returns its plan to
the queue. All completed verdicts, exact plans, feedback, and ledger lines are
unchanged; only pending scores and the scheduler revision change.
"""

import argparse
import fcntl
import hashlib
import json
import os
import shutil

from calibrate_healthy import ROOT
from campaign import CHECKPOINT, LEDGER, LOCK

ARCHIVE = ROOT / 'scheduler-migration-target-retaining'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if ARCHIVE.exists():
        raise RuntimeError('scheduler migration archive already exists')
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before, ledger = CHECKPOINT.read_bytes(), LEDGER.read_bytes()
        state = json.loads(before)
        if state.get('scheduler_revision') == 'target_retaining_v2' or \
                state.get('feedback_baseline') != 'healthy_union_v2':
            raise RuntimeError('checkpoint is not the prior calibrated scheduler')
        if [json.loads(line) for line in ledger.splitlines()] != state['results']:
            raise RuntimeError('append-only ledger differs from checkpoint')
        old_results = json.dumps(state['results'], sort_keys=True)
        old_queued = json.dumps(state['queued'], sort_keys=True)
        prior_pending = [job['plan'] for job in state['pending']]
        interrupted = None
        if state['inflight']:
            if len(state['inflight']) != 1:
                raise RuntimeError('only one worker may be interrupted')
            interrupted = state['inflight'][0]
            expected = 'trial-{:04d}'.format(len(state['results']) + 1)
            if interrupted['run_id'] != expected or \
                    state['next_trial'] != len(state['results']) + 2:
                raise RuntimeError('interrupted trial is not next after completed prefix')
            source = ROOT / expected
            if (source / 'run.json').exists() or not source.is_dir():
                raise RuntimeError('interrupted trial has complete receipt or no raw folder')
            state['pending'].insert(0, {k: v for k, v in interrupted.items()
                                        if k not in ('run_id', 'worker_slot')})
            state['inflight'] = []
            state['next_trial'] -= 1
        elif state['status'] != 'paused_at_trial_boundary':
            raise RuntimeError('campaign has neither stopped boundary nor one interrupted trial')
        by_id = {item['run_id']: item for item in state['results']}
        changes = []
        for job in state['pending']:
            parent = by_id.get(job['parent'])
            if parent is None:
                if job['parent'] != 'healthy-a':
                    raise RuntimeError('pending parent is not a completed trial')
                continue
            if not parent['effective'] or not parent['strict_receipt']:
                raise RuntimeError('target-losing parent has mutation in pending queue')
            score = 15.0 + min(parent['new_coverage_lines'], 20) * 0.3 + \
                (5.0 if parent['new_io_families'] else 0.0)
            if job['score'] != score:
                changes.append({'parent': job['parent'], 'old': job['score'], 'new': score})
                job['score'] = score
        if not changes:
            raise RuntimeError('no demonstrated target-retaining descendants to prioritize')
        if json.dumps(state['results'], sort_keys=True) != old_results or \
                json.dumps(state['queued'], sort_keys=True) != old_queued or \
                sorted(job['plan'] for job in state['pending']) != \
                sorted(prior_pending + ([interrupted['plan']] if interrupted else [])):
            raise RuntimeError('migration changed a completed trial or queued plan')
        state['status'] = 'paused_at_trial_boundary'
        state['schema'] = 4
        state['scheduler_revision'] = 'target_retaining_v2'
        after = (json.dumps(state, sort_keys=True, indent=2) + '\n').encode()
        summary = {'status': 'prepared', 'completed': len(state['results']),
                   'effective': state['effective_count'], 'reweighted': len(changes),
                   'interrupted_requeued': interrupted['run_id'] if interrupted else None,
                   'checkpoint_before_sha256': sha(before),
                   'checkpoint_after_sha256': sha(after),
                   'ledger_unchanged_sha256': sha(ledger)}
        if not args.run:
            print(json.dumps(summary, sort_keys=True))
            return
        ARCHIVE.mkdir()
        (ARCHIVE / 'checkpoint.before.json').write_bytes(before)
        (ARCHIVE / 'ledger.unchanged.jsonl').write_bytes(ledger)
        if interrupted:
            shutil.move(str(ROOT / interrupted['run_id']),
                        str(ARCHIVE / (interrupted['run_id'] + '-interrupted')))
        temporary = CHECKPOINT.with_suffix('.json.scheduler-tmp')
        with temporary.open('wb') as output:
            output.write(after)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, CHECKPOINT)
        if sha(CHECKPOINT.read_bytes()) != sha(after) or \
                sha(LEDGER.read_bytes()) != sha(ledger):
            raise RuntimeError('scheduler migration SHA check failed')
        summary['status'] = 'applied'
        (ARCHIVE / 'receipt.json').write_text(json.dumps(summary, sort_keys=True, indent=2)
                                               + '\n')
        print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
