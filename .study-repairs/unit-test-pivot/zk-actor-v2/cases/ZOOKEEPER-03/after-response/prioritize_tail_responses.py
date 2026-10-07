#!/usr/bin/env python3
"""At a pilot boundary, prioritize complete sync responses before next guard.

The original QuorumTest.testSessionMoved sends setData and sync for each new
handle, then starts the next handoff. In healthy traces, the third completed
NIOServerCnxn response on that actor follows the sync write. This changes
pending scores only; it neither creates plans nor reclassifies old trials.
"""

import argparse
import fcntl
import hashlib
import json
import os

from calibrate_healthy import ROOT
from campaign import CHECKPOINT, LEDGER, LOCK

ARCHIVE = ROOT / 'queue-priority-tail-response'
SITE = 'org.apache.zookeeper.server.NIOServerCnxn#handleWrite:299:packetSent()V@@'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if ARCHIVE.exists():
        raise RuntimeError('priority migration archive already exists')
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before, ledger = CHECKPOINT.read_bytes(), LEDGER.read_bytes()
        state = json.loads(before)
        if state['status'] != 'paused_at_trial_boundary' or state['inflight']:
            raise RuntimeError('complete original-JUnit trial boundary required')
        if [json.loads(line) for line in ledger.splitlines()] != state['results']:
            raise RuntimeError('ledger differs from completed checkpoint prefix')
        prior_results = json.dumps(state['results'], sort_keys=True)
        prior_plans = [job['plan'] for job in state['pending']]
        changed = []
        for job in state['pending']:
            if (len(job['plan']) == 1 and job['plan'][0].startswith(SITE)
                    and job['plan'][0].endswith('@@3')):
                changed.append({'selector': job['plan'][0],
                                'old_score': job['score'], 'new_score': 50.0})
                job['score'] = 50.0
        if len(changed) != 9:
            raise RuntimeError('expected nine as-yet-untested third responses')
        if prior_results != json.dumps(state['results'], sort_keys=True) or \
                prior_plans != [job['plan'] for job in state['pending']]:
            raise RuntimeError('migration changed a completed trial or queue plan')
        state['priority_migration'] = 'nine complete third responses after sync'
        after = (json.dumps(state, sort_keys=True, indent=2) + '\n').encode()
        summary = {'status': 'prepared', 'completed_trials': len(state['results']),
                   'effective': state['effective_count'], 'boosted': changed,
                   'checkpoint_before_sha256': sha(before),
                   'checkpoint_after_sha256': sha(after),
                   'ledger_unchanged_sha256': sha(ledger)}
        if not args.run:
            print(json.dumps(summary, sort_keys=True))
            return
        ARCHIVE.mkdir()
        (ARCHIVE / 'checkpoint.before.json').write_bytes(before)
        (ARCHIVE / 'ledger.unchanged.jsonl').write_bytes(ledger)
        temp = CHECKPOINT.with_suffix('.json.priority-tmp')
        with temp.open('wb') as output:
            output.write(after)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, CHECKPOINT)
        if sha(CHECKPOINT.read_bytes()) != sha(after) or \
                sha(LEDGER.read_bytes()) != sha(ledger):
            raise RuntimeError('priority migration SHA check failed')
        summary['status'] = 'applied'
        (ARCHIVE / 'receipt.json').write_text(json.dumps(summary, sort_keys=True, indent=2)
                                               + '\n')
        print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    main()
