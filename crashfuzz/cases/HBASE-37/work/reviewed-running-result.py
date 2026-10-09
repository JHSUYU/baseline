#!/usr/bin/env python3
"""Publish source-reviewed target-exception status for the live case table."""
import json
import os
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
CASE = HERE.parent
CHECKPOINT = HERE / 'checkpoint.json'
RESULT = CASE / 'result.json'


def reviewed_direct_nonode(trial):
    return trial['exact_exception'] and any(
        'MasterAddressTracker.getMasterInfoPort:' in item and item.endswith('~NONODE')
        for item in trial['plan'])


def main():
    result_stat = RESULT.stat()
    if time.time() - result_stat.st_mtime < 0.5:
        return
    state = json.loads(CHECKPOINT.read_text())
    result = json.loads(RESULT.read_text())
    trials = state['trials']
    if result.get('fault_trials') != len(trials):
        return
    exact = [t for t in trials if t['exact_exception']]
    direct = [t for t in exact if reviewed_direct_nonode(t)]
    unseen = [t for t in exact if not reviewed_direct_nonode(t)]
    reviewed = ([{
        'signature': 'direct_master_znode_getData_NONODE_to_selected_null_guard_IOException',
        'trial_ids': [t['id'] for t in direct],
        'source_review': 'ZKUtil.getData catches NoNodeException and returns null; '
                         'MasterAddressTracker.getMasterInfoPort then throws the specified '
                         'IOException; ActiveMasterManager catches it and returns port 0.',
        'independent_replay': 'work/logs/replay-r002.log',
        'classification': 'expected_protective_guard_path_not_new_bug'
    }] if direct else [])
    mark = 'candidate_review' if unseen else 'none'
    if (result.get('bug_mark') == mark
            and result.get('reviewed_candidate_signatures') == reviewed
            and result.get('unreviewed_target_exception_trial_ids') ==
            [t['id'] for t in unseen]):
        return
    if RESULT.stat().st_mtime_ns != result_stat.st_mtime_ns:
        return
    result['bug_mark'] = mark
    result['reviewed_candidate_signatures'] = reviewed
    result['candidate_signature_count'] = len(reviewed) + len(unseen)
    result['unreviewed_target_exception_trial_ids'] = [t['id'] for t in unseen]
    tmp = RESULT.with_name('result.json.reviewed.tmp')
    tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, RESULT)


if __name__ == '__main__':
    main()
