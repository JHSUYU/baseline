#!/usr/bin/env python3
"""Mirror the node2 shared campaign into three independent checklist rows."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent
CASES = HERE.parents[1]
PIVOT = HERE.parents[2]
REMOTE = ('ZhenyuLi@node2:/users/ZhenyuLi/baseline/.study-repairs/'
          'unit-test-pivot/cases/SOLR-14/independent/campaign/progress.json')
SSH = 'ssh -i /users/ZhenyuLi/.ssh/id_ed25519_nodes -o IdentitiesOnly=yes -o BatchMode=yes'
BASE_SECONDS = 84.365 + 31.377  # four valid healthy seeds + two strict direct-read calibrations
BASE_FAULT_TRIALS = 2


def atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f'.tmp.{os.getpid()}')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temporary, path)


def sync() -> dict | None:
    target = HERE / 'campaign/live-progress.json'
    target.parent.mkdir(exist_ok=True)
    temporary = target.with_name('live-progress.json.rsynctmp')
    result = subprocess.run(['rsync', '-q', '-e', SSH, REMOTE, str(temporary)],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    data = json.loads(temporary.read_text())
    os.replace(temporary, target)
    return data


def publish(progress: dict) -> None:
    new_trials = progress['fault_trials']
    for number in (14, 15, 16):
        case = f'SOLR-{number:02d}'
        path = CASES / case / 'result.json'
        row = json.loads(path.read_text())
        post = progress['post_fault_target_reach_trials'][case]
        throws = progress['target_exception_after_fault_trials'][case]
        row.update({
            'fault_trials': BASE_FAULT_TRIALS + new_trials,
            'strict_injections': BASE_FAULT_TRIALS + progress['strict_injections'],
            'target_after_fault': post,
            'target_exception_after_fault_trials': throws,
            'coverage_gain': progress['production_probe_gain'],
            'elapsed_seconds': round(BASE_SECONDS + progress['elapsed_seconds'], 3),
            'independent_campaign': progress,
            'post_fault_outer_guard_trials': progress['post_fault_outer_guard_trials'],
            'methodology': 'coverage_io_independent_asm_jacoco',
            'bug_mark': 'none',
            'updated_at': time.time(),
        })
        if throws:
            row['status'] = 'candidate_target_exception_review'
            row['reason'] = 'An exact target throw after a strict applied fault needs source review and replay; the split guards may protect against leader loss.'
        elif progress['status'] == 'running':
            row['status'] = ('fuzz_running' if number == 14 else
                             'fuzz_running_final_guard_not_observed')
        elif progress['status'] in ('budget_complete', 'queue_exhausted'):
            row['status'] = ('campaign_budget_done_review_pending' if number == 14 else
                             'target_final_guard_not_observed_review_pending')
        elif progress['status'] == 'candidate_target_exception':
            row['status'] = 'paused_shared_candidate_review'
        atomic(path, row)
    subprocess.run(['python3', str(PIVOT / 'checklist.py'), 'render'],
                   cwd=PIVOT.parents[1], check=True, stdout=subprocess.DEVNULL)


def main() -> None:
    last = None
    while True:
        if (HERE / 'campaign/mirror.stop').exists():
            break
        data = sync()
        if data is not None:
            digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
            if digest != last:
                publish(data)
                print(f"{time.strftime('%F %T')} trials={data['fault_trials']} "
                      f"strict={data['strict_injections']} status={data['status']}", flush=True)
                last = digest
            if data['status'] == 'candidate_target_exception' or (
                    data['fault_trials'] >= 80 and data['status'] != 'running'):
                break
        time.sleep(10)


if __name__ == '__main__':
    main()
