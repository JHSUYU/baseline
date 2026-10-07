#!/usr/bin/env python3
"""Move a finished 24-plan HTTP pilot to the audited target-aware scheduler.

The original fuzzer process must have exited and its run_stages parent must
remain stopped. This only updates the runner digest in the existing checkpoint;
the completed plans, queue, coverage, and selected budget are retained.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import fuzz_rpc as campaign


OLD_RUNNER_SHA = '235a40b48f3db29308a31e41b03850fadf7ebcdeccc8a68c00261979289e273e'
MIGRATION = campaign.ROOT / 'migrations' / '0002-timeout-stage2'
OLD_RUNNER = MIGRATION / 'fuzz_rpc.pilot24.py'


def main() -> None:
    state_file = campaign.ROOT / 'state.json'
    progress_file = campaign.ROOT / 'progress.json'
    if (MIGRATION / 'migration.json').exists():
        raise RuntimeError('HTTP stage-2 scheduler migration already applied')
    before = state_file.read_bytes()
    state = json.loads(before)
    rows = state['completed']
    if (state['status'] != 'budget_complete'
            or state['budget'] != {'max_trials': 24, 'max_faults': 2}
            or len(rows) != 24 or state['active'] is not None
            or state['locks']['rpc-stage/fuzz_rpc.py'] != OLD_RUNNER_SHA
            or campaign.sha(OLD_RUNNER) != OLD_RUNNER_SHA):
        raise RuntimeError('the exact finished pilot and old runner backup are required')
    if len({row['selected_queue_id'] for row in rows}) != 24:
        raise RuntimeError('pilot selected a plan more than once')
    if not state['queue']:
        raise RuntimeError('no stage-2 queue remains')
    for key, expected in state['locks'].items():
        current = OLD_RUNNER if key == 'rpc-stage/fuzz_rpc.py' else campaign.PARENT / key
        if campaign.sha(current) != expected:
            raise RuntimeError(f'old checkpoint dependency differs: {key}')
    new_locks = campaign.locks()
    if (new_locks['rpc-stage/fuzz_rpc.py'] == OLD_RUNNER_SHA
            or any(new_locks[key] != expected for key, expected in state['locks'].items()
                   if key != 'rpc-stage/fuzz_rpc.py')):
        raise RuntimeError('migration changed more than the scheduler runner')
    preview = copy.deepcopy(state)
    next_plan = campaign.choose(preview)
    if (next_plan['id'] in {row['selected_queue_id'] for row in rows}
            or next_plan['sequence'][-1]['fault_mode'] != 'TIMEOUT'):
        raise RuntimeError('stage-2 preview duplicates a plan or misses TIMEOUT')
    original_rows = copy.deepcopy(rows)
    original_queue = copy.deepcopy(state['queue'])
    original_probes = list(state['covered_probes'])
    original_selectors = list(state['observed_rpc_selectors'])
    MIGRATION.mkdir(parents=True, exist_ok=True)
    (MIGRATION / 'state.pilot24.json').write_bytes(before)
    (MIGRATION / 'progress.pilot24.json').write_bytes(progress_file.read_bytes())
    (MIGRATION / 'stage-status.pilot24.json').write_bytes(
        (campaign.ROOT / 'stage-status.json').read_bytes())
    state['locks'] = new_locks
    campaign.atomic(state_file, state)
    if (state['completed'] != original_rows or state['queue'] != original_queue
            or state['covered_probes'] != original_probes
            or state['observed_rpc_selectors'] != original_selectors):
        raise RuntimeError('migration changed completed trial or queue evidence')
    modes = {}
    for mode in ('TIMEOUT', 'DELAY'):
        selected = [row for row in rows if row['last_fault_mode'] == mode]
        modes[mode] = {
            'selected': len(selected),
            'strict': sum(row['strict_injection'] for row in selected),
            'solr36_postfinal': sum(row['strict_injection'] and
                                    row['postfault_same_child_guards']['SOLR-36'] > 0
                                    for row in selected),
            'solr37_postfinal': sum(row['strict_injection'] and
                                    row['postfault_same_child_guards']['SOLR-37'] > 0
                                    for row in selected),
            'elapsed_seconds': round(sum(row['elapsed_seconds'] for row in selected), 3),
        }
    receipt = {
        'case_ids': ['SOLR-36', 'SOLR-37'],
        'old_state_sha256': campaign.sha(MIGRATION / 'state.pilot24.json'),
        'new_state_sha256': campaign.sha(state_file),
        'old_runner_sha256': OLD_RUNNER_SHA,
        'new_runner_sha256': new_locks['rpc-stage/fuzz_rpc.py'],
        'pilot_selected_plans': len(rows),
        'pilot_modes': modes,
        'retained_queue_length': len(original_queue),
        'next_plan_id': next_plan['id'],
        'next_plan_mode': next_plan['sequence'][-1]['fault_mode'],
        'migration_scope': 'scheduler-only; completed plans/queue/coverage unchanged',
    }
    campaign.atomic(MIGRATION / 'migration.json', receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
