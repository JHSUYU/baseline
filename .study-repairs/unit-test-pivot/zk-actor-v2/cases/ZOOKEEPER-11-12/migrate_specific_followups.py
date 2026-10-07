#!/usr/bin/env python3
"""One-time migration from first-fault-wide to exact-parent/next-actor scoring."""

import argparse
import copy
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import shutil

from build_adapter import sha
from calibrate_v2 import CASE, calibrate, locked_hashes
from campaign_v2 import LOCK, ROOT, STATE, atomic, choose, recover
from run_v2 import verify_build

OLD_CAMPAIGN_SHA = '51972a16046f9f51a5071a15624ce54cbd72d75a15267d272ea20f38eb722ce4'
OLD_CALIBRATION_SHA = 'ba7f0f291ddfeaa20d70bd91a77b606ed69ae4613c4db1d71504a7c7ae6f6647'
FIRST_FAULT = ('AtomicFileOutputStream#close:87:File.renameTo@@peer:0'
               '@@file:currentEpoch:op:rename@@2')


def migrate():
    verify_build()
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text())
        if state['script_hashes']['campaign_v2.py'] != OLD_CAMPAIGN_SHA or \
                state['calibration_sha256'] != OLD_CALIBRATION_SHA or \
                state['selected_count'] != 27 or len(state['results']) != 26 or \
                state['inflight']['run_id'] != 'trial-027':
            raise RuntimeError('not the reviewed completed trial-027 boundary')
        if not (ROOT / 'trial-027' / 'run.json').is_file():
            raise RuntimeError('trial-027 original JUnit receipt incomplete')
        current = CASE / 'calibration-receipt.json'
        previous = CASE / 'calibration-receipt-before-specific-followups.json'
        if sha(current) != OLD_CALIBRATION_SHA:
            raise RuntimeError('old healthy calibration receipt changed')
        if not previous.exists():
            shutil.copyfile(current, previous)
        if sha(previous) != OLD_CALIBRATION_SHA:
            raise RuntimeError('old healthy calibration backup changed')
        old_healthy = json.loads(current.read_text())['healthy']
        prior_counts = {case: item['effective_count'] for case, item in state['budgets'].items()}
        prior_coverage = set(state['seen_coverage'])
        prior_families = set(state['seen_families'])
        old_hashes = state['script_hashes'].copy()
        recover(state)
        if state['inflight'] is not None or len(state['results']) != 27 or \
                state['results'][-1]['run_id'] != 'trial-027':
            raise RuntimeError('trial-027 not recovered exactly once')
        last = state['results'][-1]
        if any(item['effective'] for item in last['case_results'].values()):
            raise RuntimeError('reviewed trial-027 target-lost classification changed')
        if last['new_coverage_lines'] or last['new_io_families'] or \
                set(state['seen_coverage']) != prior_coverage or \
                set(state['seen_families']) != prior_families or \
                any(item['effective_count'] != prior_counts[case]
                    for case, item in state['budgets'].items()):
            raise RuntimeError('target-lost trial changed feedback or effective budget')
        lost = []
        safe = []
        for result in state['results']:
            if not result['strict_injection'] or len(result['plan']) < 2 or \
                    result['plan'][0] != FIRST_FAULT:
                continue
            (safe if any(item['effective'] for item in result['case_results'].values())
             else lost).append(result['run_id'])
        if not {'trial-003', 'trial-004', 'trial-005', 'trial-006'} <= set(lost) or \
                not {'trial-007', 'trial-008', 'trial-010'} <= set(safe):
            raise RuntimeError('mixed safe/lost extensions of the first fault changed')
        calibrated = calibrate()
        if [seed['trace_sha256'] for seed in calibrated['healthy']] != \
                [seed['trace_sha256'] for seed in old_healthy]:
            raise RuntimeError('healthy raw traces changed during controller migration')
        state['script_hashes'] = locked_hashes()
        state['calibration_sha256'] = sha(current)
        state['status'] = 'paused_at_trial_boundary'
        next_job = choose(copy.deepcopy(state))
        migration = {
            'utc': datetime.now(timezone.utc).isoformat(),
            'reason': 'first-fault-wide loss penalty suppressed known safe extensions; '
                      'use exact tested parent plus next-fault actor',
            'selected_count': state['selected_count'],
            'recovered_trial': 'trial-027',
            'effective_counts': prior_counts,
            'first_fault': FIRST_FAULT,
            'lost_extensions': lost,
            'target_retaining_extensions': safe,
            'trial027_target_lost_feedback_excluded': True,
            'next_normal_selection': None if next_job is None else {
                'case': next_job['case'], 'plan': next_job['plan']},
            'old_script_hashes': old_hashes,
            'new_script_hashes': state['script_hashes'],
            'old_calibration_sha256': OLD_CALIBRATION_SHA,
            'new_calibration_sha256': state['calibration_sha256'],
            'original_agent_sha256': state['agent_sha256'],
            'no_old_trials_replayed': True,
        }
        state.setdefault('migrations', []).append(migration)
        atomic(ROOT / 'migration-specific-followups.json', migration)
        atomic(STATE, state)
        print(json.dumps({'selected': state['selected_count'],
                          'effective': prior_counts,
                          'normal_next': migration['next_normal_selection'],
                          'status': state['status']}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        migrate()
    else:
        print(json.dumps({'status': 'prepared_only', 'checkpoint_changed': False}))
