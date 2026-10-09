#!/usr/bin/env python3
"""Normalize saved V2 review flags to the selected target exception oracle.

The first live campaign process was launched before the oracle bookkeeping
was narrowed. Run this only after that tmux process exits; the campaign lock
prevents changing a live checkpoint. It does not change effective counts,
fault receipts, coverage, or raw traces.
"""

import fcntl
import json
import os
from pathlib import Path
import shutil

ROOT = Path('/users/ZhenyuLi/zk01-actor-v2-runs')
CHECKPOINT = ROOT / 'v2-campaign.json'
LEDGER = ROOT / 'v2-trials.jsonl'
LOCK = ROOT / 'v2-campaign.lock'
BACKUP = ROOT / 'v2-campaign.pre-oracle-reconcile.json'


def atomic_write(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(data)
    os.replace(temp, path)


def main():
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not CHECKPOINT.is_file():
            raise RuntimeError('campaign checkpoint absent')
        if not BACKUP.exists():
            shutil.copy2(CHECKPOINT, BACKUP)
        state = json.loads(CHECKPOINT.read_text())
        changed = 0
        for item in state['results']:
            observed = bool(item['selected_target_throw_count'])
            desired_mark = 'candidate_needs_source_review' if observed else 'none'
            if item['needs_source_review'] != observed or item['bug_mark'] != desired_mark:
                changed += 1
                item['needs_source_review'] = observed
                item['bug_mark'] = desired_mark
        atomic_write(CHECKPOINT, json.dumps(state, sort_keys=True, indent=2) + '\n')
        atomic_write(LEDGER, ''.join(json.dumps(x, sort_keys=True) + '\n'
                                     for x in state['results']))
        print(json.dumps({'status': state['status'], 'results': len(state['results']),
                          'effective_count': state['effective_count'],
                          'oracle_flags_corrected': changed,
                          'selected_target_throw_trials': sum(
                              bool(x['selected_target_throw_count'])
                              for x in state['results'])}, sort_keys=True))


if __name__ == '__main__':
    main()
