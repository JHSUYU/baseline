#!/usr/bin/env python3
"""One-time, case-local checkpoint migration after a completed trial boundary."""

import argparse
import fcntl
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone

from build_adapter import sha
from calibrate_v2 import CASE, calibrate, locked_hashes
from campaign_v2 import LOCK, ROOT, STATE, atomic, recover
from run_v2 import verify_build

OLD_CAMPAIGN_SHA = '905fdd27b25dbcad03d9ad3a615cd39b639e0970b7c3093d701d77410e039a46'
OLD_CALIBRATION_SHA = 'addc8481996649263e631398777c9e22b36208f18e6b9d4b4132755789a24764'


def migrate():
    verify_build()
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text())
        if state['script_hashes']['campaign_v2.py'] != OLD_CAMPAIGN_SHA or \
                state['calibration_sha256'] != OLD_CALIBRATION_SHA or \
                state['selected_count'] != 9:
            raise RuntimeError('not the reviewed post-trial-009 checkpoint')
        prior = CASE / 'calibration-receipt-before-loss-penalty.json'
        current = CASE / 'calibration-receipt.json'
        if not prior.is_file():
            if sha(current) != OLD_CALIBRATION_SHA:
                raise RuntimeError('original healthy calibration receipt changed')
            shutil.copyfile(current, prior)
        if sha(prior) != OLD_CALIBRATION_SHA:
            raise RuntimeError('original calibration backup changed')
        recovered = state['inflight']['run_id'] if state['inflight'] else None
        if recovered is not None and not (ROOT / recovered / 'run.json').is_file():
            raise RuntimeError('inflight trial lacks complete original JUnit receipt')
        recover(state)
        if state['inflight'] is not None or len(state['results']) != state['selected_count']:
            raise RuntimeError('trial recovery did not reach a completed boundary')
        losing = {}
        for result in state['results']:
            if len(result['plan']) < 2 or not result['strict_injection'] or any(
                    item['postfault_guards'] for item in result['case_results'].values()):
                continue
            prefix = result['plan'][0]
            losing[prefix] = losing.get(prefix, 0) + 1
        prefix = ('AtomicFileOutputStream#close:87:File.renameTo@@peer:0'
                  '@@file:currentEpoch:op:rename@@2')
        if losing.get(prefix, 0) < 3:
            raise RuntimeError('reviewed target-losing prefix threshold not met')
        previous_hashes = state['script_hashes'].copy()
        calibrated = calibrate()
        if calibrated['first_server_sid'] != '0':
            raise RuntimeError('selected firstServer identity changed')
        state['script_hashes'] = locked_hashes()
        state['calibration_sha256'] = sha(current)
        state['status'] = 'paused_at_trial_boundary'
        migration = {
            'utc': datetime.now(timezone.utc).isoformat(),
            'reason': 'downweight exact multi-fault prefix after >=3 target-losing trials',
            'recovered_trial': recovered,
            'selected_count': state['selected_count'],
            'effective_counts': {case: item['effective_count']
                                 for case, item in state['budgets'].items()},
            'losing_prefix': prefix,
            'losing_prefix_trials': losing[prefix],
            'old_script_hashes': previous_hashes,
            'new_script_hashes': state['script_hashes'],
            'old_calibration_sha256': OLD_CALIBRATION_SHA,
            'new_calibration_sha256': state['calibration_sha256'],
            'original_agent_sha256': state['agent_sha256'],
            'no_old_trials_replayed': True,
        }
        state.setdefault('migrations', []).append(migration)
        atomic(ROOT / 'migration-loss-penalty.json', migration)
        atomic(STATE, state)
        print(json.dumps({'status': state['status'], 'selected': state['selected_count'],
                          'effective': migration['effective_counts'],
                          'losing_prefix_trials': losing[prefix]}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({'status': 'prepared_only', 'checkpoint_changed': False}))
    else:
        migrate()
