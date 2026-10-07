#!/usr/bin/env python3
"""Prioritize a second complete sync response after a successful first fault.

At a stopped boundary this preserves all completed original-JUnit receipts and
fault plans. It archives one interrupted unreceipted trial, if present, and
reweights only pending descendants whose next exact selector is a third
server response on its actor. Every tenth future selection explores a healthy
root as defined by campaign.py.
"""

import argparse
import fcntl
import hashlib
import json
import os
import shutil

from calibrate_healthy import ROOT
from campaign import CHECKPOINT, LEDGER, LOCK, complete_sync_response

ARCHIVE = ROOT / 'scheduler-migration-tail-sync'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if ARCHIVE.exists():
        raise RuntimeError('tail-sync migration archive already exists')
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before, ledger = CHECKPOINT.read_bytes(), LEDGER.read_bytes()
        state = json.loads(before)
        if state.get('scheduler_revision') != 'target_retaining_v2' or \
                state.get('feedback_baseline') != 'healthy_union_v2':
            raise RuntimeError('expected prior target-retaining scheduler')
        if [json.loads(line) for line in ledger.splitlines()] != state['results']:
            raise RuntimeError('completed ledger differs from checkpoint')
        prior_results = json.dumps(state['results'], sort_keys=True)
        prior_queued = json.dumps(state['queued'], sort_keys=True)
        prior_pending = [job['plan'] for job in state['pending']]
        interrupted = None
        if state['inflight']:
            if len(state['inflight']) != 1:
                raise RuntimeError('only one worker may be interrupted')
            interrupted = state['inflight'][0]
            expected = 'trial-{:04d}'.format(len(state['results']) + 1)
            if interrupted['run_id'] != expected or \
                    state['next_trial'] != len(state['results']) + 2:
                raise RuntimeError('interrupted trial is not after completed prefix')
            source = ROOT / expected
            if not source.is_dir() or (source / 'run.json').exists():
                raise RuntimeError('interrupted trial has a complete receipt or no raw folder')
            state['pending'].insert(0, {k: v for k, v in interrupted.items()
                                        if k not in ('run_id', 'worker_slot')})
            state['inflight'] = []
            state['next_trial'] -= 1
        elif state['status'] != 'paused_at_trial_boundary':
            raise RuntimeError('complete boundary or one interrupted trial required')
        parents = {item['run_id']: item for item in state['results']}
        changed = []
        for job in state['pending']:
            if job['parent'] == 'healthy-a' or not complete_sync_response(job['plan'][-1]):
                continue
            parent = parents.get(job['parent'])
            if parent is None or not parent['effective'] or not parent['strict_receipt']:
                raise RuntimeError('tail mutation lacks target-retaining parent')
            score = 24.0 + min(parent['new_coverage_lines'], 20) * 0.3 + \
                (5.0 if parent['new_io_families'] else 0.0)
            if job['score'] != score:
                changed.append({'parent': job['parent'], 'old': job['score'], 'new': score})
                job['score'] = score
        if not changed:
            raise RuntimeError('no complete-sync descendant to reprioritize')
        if json.dumps(state['results'], sort_keys=True) != prior_results or \
                json.dumps(state['queued'], sort_keys=True) != prior_queued or \
                sorted(job['plan'] for job in state['pending']) != \
                sorted(prior_pending + ([interrupted['plan']] if interrupted else [])):
            raise RuntimeError('migration changed completed trial or queue plans')
        state['status'] = 'paused_at_trial_boundary'
        state['scheduler_revision'] = 'tail_sync_v3'
        after = (json.dumps(state, sort_keys=True, indent=2) + '\n').encode()
        summary = {'status': 'prepared', 'completed': len(state['results']),
                   'effective': state['effective_count'], 'reweighted': len(changed),
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
        temp = CHECKPOINT.with_suffix('.json.tail-tmp')
        with temp.open('wb') as output:
            output.write(after)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, CHECKPOINT)
        if sha(CHECKPOINT.read_bytes()) != sha(after) or \
                sha(LEDGER.read_bytes()) != sha(ledger):
            raise RuntimeError('tail scheduler migration SHA check failed')
        summary['status'] = 'applied'
        (ARCHIVE / 'receipt.json').write_text(json.dumps(summary, sort_keys=True, indent=2)
                                               + '\n')
        print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
