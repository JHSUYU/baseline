#!/usr/bin/env python3
"""Temporary handoff gate; never starts a JUnit when the pause request is active."""
import hashlib
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

CASE = Path(__file__).resolve().parents[1]
CAMPAIGN = CASE / 'evidence/campaign-v4'
STATE = CAMPAIGN / 'state.json'
CALIBRATION = CAMPAIGN / 'node1-handoff-calibration'
MARKER = CALIBRATION / 'pause-request-v8.json'
ORIGINAL = CASE / 'probe/run-original-v8.py'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path, obj):
    temp = path.with_name(path.name + '.pause.tmp')
    temp.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n')
    os.replace(temp, path)


def main():
    if MARKER.exists():
        request = json.loads(MARKER.read_text())
        state = json.loads(STATE.read_text())
        inflight = state['inflight']
        if (len(state['trials']) >= request['after_trial'] and inflight is not None):
            number = inflight['number']
            plan = inflight['plan']
            if number != len(state['trials']) + 1:
                raise RuntimeError('selected plan number is not next uncompleted trial')
            if (CAMPAIGN / f'trial-{number:03d}' / 'manifest.json').exists():
                raise RuntimeError('selected plan already has a JUnit manifest')
            if len(state['seen_plans']) != len(state['trials']):
                raise RuntimeError('seen-plan ledger differs from completed trials')
            before = sha(STATE)
            ledger = {'trials': state['trials'], 'seen_plans': state['seen_plans']}
            ledger_sha = hashlib.sha256(json.dumps(ledger, sort_keys=True,
                                                  separators=(',', ':')).encode()).hexdigest()
            state['queue'].insert(0, plan)
            state['inflight'] = None
            atomic_json(STATE, state)
            receipt = {'intercepted_trial_number': number, 'plan': plan,
                       'completed_trials': len(state['trials']),
                       'state_sha256_before': before,
                       'state_sha256_after': sha(STATE),
                       'ledger_sha256_before_and_after': ledger_sha,
                       'queue_first_restored_plan': state['queue'][0],
                       'request_sha256': sha(MARKER),
                       'original_runner_sha256': sha(ORIGINAL),
                       'wrapper_sha256': sha(Path(__file__)),
                       'junit_started_for_intercepted_plan': False,
                       'stopped_at_utc': datetime.now(timezone.utc).isoformat()}
            atomic_json(CALIBRATION / 'pause-applied-v8.json', receipt)
            print(json.dumps(receipt, sort_keys=True), flush=True)
            return 75
    os.execv(sys.executable, [sys.executable, str(ORIGINAL), *sys.argv[1:]])


if __name__ == '__main__':
    sys.exit(main())
