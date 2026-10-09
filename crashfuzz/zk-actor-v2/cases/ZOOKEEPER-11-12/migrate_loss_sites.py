#!/usr/bin/env python3
"""One-time checkpoint migration for exact actor/file/callsite fault-site feedback."""

import argparse
import copy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import shutil

from build_adapter import sha
from calibrate_v2 import CASE, calibrate, locked_hashes
from campaign_v2 import FAULT_KIND, LOCK, ROOT, STATE, atomic, choose, recover
from run_v2 import verify_build

OLD_CAMPAIGN_SHA = 'bc328b0a4114c906acc69aca3f942f132deda6212aef5f0a9ec262dd6c30bd70'
OLD_CALIBRATION_SHA = '3c589bce1558a1be45c3d6ff844e6c9876c2194d739992f62f3761b31725ce02'
REPEATED_SITE = ('QuorumPeer#loadDataBase:1169:File.exists@@peer:0'
                 '@@file:currentEpoch.tmp:op:exists@@1')


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def migrate():
    verify_build()
    with LOCK.open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text())
        if state['script_hashes']['campaign_v2.py'] != OLD_CAMPAIGN_SHA or \
                state['calibration_sha256'] != OLD_CALIBRATION_SHA or \
                state['selected_count'] != 38 or len(state['results']) != 37 or \
                state['inflight']['run_id'] != 'trial-038':
            raise RuntimeError('not the reviewed completed trial-038 boundary')
        if not (ROOT / 'trial-038' / 'run.json').is_file():
            raise RuntimeError('trial-038 original JUnit receipt incomplete')
        current = CASE / 'calibration-receipt.json'
        previous = CASE / 'calibration-receipt-before-loss-sites.json'
        if sha(current) != OLD_CALIBRATION_SHA:
            raise RuntimeError('old healthy calibration receipt changed')
        if not previous.exists():
            shutil.copyfile(current, previous)
        if sha(previous) != OLD_CALIBRATION_SHA:
            raise RuntimeError('old calibration backup changed')
        old_healthy = json.loads(current.read_text())['healthy']
        old_results = copy.deepcopy(state['results'])
        old_queue = copy.deepcopy(state['queue'])
        old_counts = {case: item['effective_count'] for case, item in state['budgets'].items()}
        old_coverage = set(state['seen_coverage'])
        old_families = set(state['seen_families'])
        old_hashes = state['script_hashes'].copy()
        recover(state)
        if state['inflight'] is not None or state['selected_count'] != 38 or \
                len(state['results']) != 38 or state['results'][:-1] != old_results or \
                state['queue'] != old_queue or state['results'][-1]['run_id'] != 'trial-038':
            raise RuntimeError('completed results or queue changed during recovery')
        last = state['results'][-1]
        if not last['strict_injection'] or last['plan'][-1] != REPEATED_SITE or \
                any(item['postfault_guards'] or item['effective']
                    for item in last['case_results'].values()) or \
                last['new_coverage_lines'] or last['new_io_families'] or \
                set(state['seen_coverage']) != old_coverage or \
                set(state['seen_families']) != old_families or \
                any(item['effective_count'] != old_counts[case]
                    for case, item in state['budgets'].items()):
            raise RuntimeError('target-lost trial-038 affected target or feedback counts')
        losing = [r['run_id'] for r in state['results']
                  if r['strict_injection'] and r['plan'][-1] == REPEATED_SITE
                  and not any(item['postfault_guards'] for item in r['case_results'].values())]
        retaining = [r['run_id'] for r in state['results']
                     if r['strict_injection'] and r['plan'][-1] == REPEATED_SITE
                     and any(item['postfault_guards'] for item in r['case_results'].values())]
        if not {'trial-011', 'trial-016', 'trial-029', 'trial-034', 'trial-038'} \
                <= set(losing) or retaining:
            raise RuntimeError('exact site loss/retention evidence changed')
        calibrated = calibrate()
        if [seed['trace_sha256'] for seed in calibrated['healthy']] != \
                [seed['trace_sha256'] for seed in old_healthy]:
            raise RuntimeError('healthy raw traces changed during migration')
        state['script_hashes'] = locked_hashes()
        state['calibration_sha256'] = sha(current)
        state['status'] = 'paused_at_trial_boundary'
        next_job = choose(copy.deepcopy(state))
        if next_job is not None and next_job['plan'][-1] == REPEATED_SITE:
            raise RuntimeError('ordinary turn still chose repeatedly losing exact I/O site')
        migration = {
            'utc': datetime.now(timezone.utc).isoformat(),
            'reason': 'downweight exact IOException callsite/actor/file/ordinal after '
                      'three target-losing trials and zero target-retaining trials',
            'selected_count': 38,
            'recovered_trial': 'trial-038',
            'effective_counts': old_counts,
            'completed_results_prefix_sha256': digest(old_results),
            'queue_before_recovery_sha256': digest(old_queue),
            'queue_after_recovery_sha256': digest(state['queue']),
            'fault_kind': FAULT_KIND,
            'selector': REPEATED_SITE,
            'target_losing_trials': losing,
            'target_retaining_trials': retaining,
            'trial038_target_lost_feedback_excluded': True,
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
        atomic(ROOT / 'migration-loss-sites.json', migration)
        atomic(STATE, state)
        print(json.dumps({'selected': 38, 'effective': old_counts,
                          'loss_site_trials': losing,
                          'next': migration['next_normal_selection']}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        migrate()
    else:
        print(json.dumps({'status': 'prepared_only', 'checkpoint_changed': False}))
