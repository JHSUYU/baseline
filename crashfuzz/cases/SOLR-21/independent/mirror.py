#!/usr/bin/env python3
"""Mirror this case's node2 checkpoint into the 102-check ledger atomically."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time


HERE = Path(__file__).resolve().parent
CASE = HERE.parent
RESULT = CASE / 'result.json'
REMOTE = str(HERE / 'campaign/progress.json')
LOCAL = HERE / 'campaign/progress.json'
SSH = ('ssh', '-i', '/users/ZhenyuLi/.ssh/id_ed25519_nodes',
       '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', 'ZhenyuLi@node2')


def atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent,
                                     prefix='.' + path.name + '.',
                                     suffix='.tmp', delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write('\n')
        temporary = Path(handle.name)
    temporary.replace(path)


def mirror_once() -> dict:
    content = subprocess.check_output((*SSH, 'cat', REMOTE), text=True)
    progress = json.loads(content)
    if progress['case_id'] != 'SOLR-21':
        raise RuntimeError('wrong remote case')
    result = json.loads(RESULT.read_text())
    previous = result.get('campaign', {}).get('fault_trials', 0)
    if progress['fault_trials'] < previous:
        raise RuntimeError('remote checkpoint moved backwards')
    baseline_seconds = result.get('baseline_seconds', result['elapsed_seconds'])
    fault_trials = 1 + progress['fault_trials']  # audited exact file-read calibration
    post_target = result['calibration']['target_guard_after_fault'] + progress['post_fault_target_reach_trials']
    status = progress['status']
    if status == 'candidate_target_exception':
        public_status = 'target_exception_candidate_source_review'
    elif status == 'budget_complete' and progress['budget']['max_trials'] >= 80:
        public_status = 'campaign_budget_complete_audit_pending'
    elif status == 'queue_exhausted':
        public_status = 'campaign_queue_exhausted_audit_pending'
    elif status == 'budget_complete':
        public_status = 'campaign_checkpoint'
    else:
        public_status = 'fuzz_running'
    result.update(
        baseline_seconds=baseline_seconds,
        status=public_status,
        fault_trials=fault_trials,
        strict_injections=1 + progress['strict_injections'],
        target_after_fault=post_target,
        post_fault_target_reach_trials=post_target,
        target_exception_after_fault_trials=progress['target_exception_after_fault_trials'],
        elapsed_seconds=round(baseline_seconds + progress['elapsed_seconds'], 3),
        coverage_gain=progress['production_probe_gain'],
        campaign=progress,
        reason=('Original CollectionReload JUnit with independent ASM exact ZooKeeper '
                'and core.properties selectors plus JaCoCo production probe feedback. '
                'Calibration is counted once; '
                'campaign trials exclude the calibration. Exact target exception '
                'candidates require source review and replay.'),
        evidence='crashfuzz/cases/SOLR-21/independent/campaign/progress.json',
        updated_at=time.time())
    atomic(LOCAL, progress)
    atomic(RESULT, result)
    subprocess.run(('python3', str(HERE.parents[2] / 'checklist.py'), 'render'),
                   stdout=subprocess.DEVNULL, check=True)
    return progress


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--follow', action='store_true')
    parser.add_argument('--interval', type=int, default=15)
    args = parser.parse_args()
    while True:
        try:
            latest = mirror_once()
            print(json.dumps({'status': latest['status'],
                              'fault_trials': latest['fault_trials']}), flush=True)
            if latest['status'] == 'candidate_target_exception' or (
                    latest['status'] in ('budget_complete', 'queue_exhausted')
                    and latest['budget']['max_trials'] >= 80):
                break
        except Exception as error:
            print(f'mirror retry: {error}', flush=True)
        if not args.follow:
            break
        time.sleep(args.interval)
