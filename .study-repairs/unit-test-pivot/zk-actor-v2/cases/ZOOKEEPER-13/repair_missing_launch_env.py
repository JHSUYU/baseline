#!/usr/bin/env python3
"""Requeue a trial rejected before JUnit startup by missing launch paths.

Requires exactly one inflight trial with no trial directory or run receipt.
The completed prefix and append-only ledger are preserved byte for byte.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path

from calibrate_healthy import ROOT
from campaign import CHECKPOINT, LEDGER, LOCK

ARCHIVE = ROOT / 'launch-env-repair'


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if ARCHIVE.exists():
        raise RuntimeError('repair archive already exists')
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = CHECKPOINT.read_bytes()
        ledger = LEDGER.read_bytes()
        state = json.loads(before)
        if state.get('feedback_baseline') != 'healthy_union_normalized_io_v3':
            raise RuntimeError('expected normalized feedback checkpoint')
        if [json.loads(line) for line in ledger.splitlines()] != state['results']:
            raise RuntimeError('completed ledger differs from checkpoint')
        if len(state['inflight']) != 1:
            raise RuntimeError('expected exactly one failed pre-JUnit launch')
        job = state['inflight'][0]
        expected = 'trial-{:04d}'.format(len(state['results']) + 1)
        if job['run_id'] != expected or state['next_trial'] != len(state['results']) + 2:
            raise RuntimeError('inflight run is not the immediate uncompleted successor')
        if (ROOT / expected).exists():
            raise RuntimeError('trial directory exists; this is not a pre-JUnit failure')
        state['pending'].insert(0, {k: v for k, v in job.items()
                                    if k not in ('run_id', 'worker_slot')})
        state['inflight'] = []
        state['next_trial'] -= 1
        state['status'] = 'paused_at_trial_boundary'
        after = (json.dumps(state, sort_keys=True, indent=2) + '\n').encode()
        summary = {'status': 'prepared', 'run_id_requeued': expected,
                   'completed_preserved': len(state['results']),
                   'effective_preserved': state['effective_count'],
                   'checkpoint_before_sha256': digest(before),
                   'checkpoint_after_sha256': digest(after),
                   'ledger_sha256': digest(ledger)}
        if not args.run:
            print(json.dumps(summary, sort_keys=True))
            return
        ARCHIVE.mkdir()
        (ARCHIVE / 'checkpoint.before.json').write_bytes(before)
        (ARCHIVE / 'ledger.unchanged.jsonl').write_bytes(ledger)
        temp = CHECKPOINT.with_suffix('.json.repair-tmp')
        with temp.open('wb') as output:
            output.write(after)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, CHECKPOINT)
        if digest(CHECKPOINT.read_bytes()) != digest(after) or \
                digest(LEDGER.read_bytes()) != digest(ledger):
            raise RuntimeError('repair SHA verification failed')
        summary['status'] = 'applied'
        (ARCHIVE / 'receipt.json').write_text(json.dumps(summary, sort_keys=True, indent=2)
                                               + '\n')
        print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
