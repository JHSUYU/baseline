#!/usr/bin/env python3
"""Switch the HTTP scheduler only after its current selected cap finishes.

The run_stages parent must be stopped while its fuzzer child exits normally at
budget_complete. This migration changes only the pinned runner digest; it
keeps every completed plan, pending selector, and coverage bit unchanged.
"""

from __future__ import annotations

import copy
from collections import Counter
import json

import fuzz_rpc as campaign


OLD_RUNNER_SHA = '777428d0560f4ce3145dc9cd8c59dc8e57bb192975d57ffee6eb73c2586dda01'
MIGRATION = campaign.ROOT / 'migrations' / '0003-child-source-balance'
OLD_RUNNER = MIGRATION / 'fuzz_rpc.before_child_balance.py'


def validated_update(state: dict, new_locks: dict) -> dict:
    rows = state['completed']
    if (state['status'] != 'budget_complete'
            or state['budget']['max_trials'] < 80
            or state['budget']['max_faults'] != 8
            or len(rows) != state['budget']['max_trials']
            or state['active'] is not None
            or state['locks']['rpc-stage/fuzz_rpc.py'] != OLD_RUNNER_SHA
            or not state['queue']):
        raise RuntimeError('a fully completed selected-cap-80 checkpoint is required')
    if len({row['selected_queue_id'] for row in rows}) != len(rows):
        raise RuntimeError('checkpoint repeated a selected plan')
    if (new_locks['rpc-stage/fuzz_rpc.py'] == OLD_RUNNER_SHA
            or any(new_locks[key] != digest for key, digest in state['locks'].items()
                   if key != 'rpc-stage/fuzz_rpc.py')):
        raise RuntimeError('migration changed a dependency other than the scheduler')
    updated = copy.deepcopy(state)
    updated['locks'] = new_locks
    if any(updated[key] != state[key] for key in
           ('completed', 'queue', 'seen_sequences', 'covered_probes',
            'observed_rpc_selectors', 'budget', 'active', 'status')):
        raise RuntimeError('migration changed campaign evidence')
    return updated


def main() -> None:
    state_file = campaign.ROOT / 'state.json'
    progress_file = campaign.ROOT / 'progress.json'
    stage_file = campaign.ROOT / 'stage-status.json'
    if (MIGRATION / 'migration.json').exists():
        raise RuntimeError('child-source balancing migration already applied')
    before = state_file.read_bytes()
    state = json.loads(before)
    if campaign.sha(OLD_RUNNER) != OLD_RUNNER_SHA:
        raise RuntimeError('byte-for-byte old runner backup is missing')
    for key, digest in state['locks'].items():
        current = OLD_RUNNER if key == 'rpc-stage/fuzz_rpc.py' else campaign.PARENT / key
        if campaign.sha(current) != digest:
            raise RuntimeError(f'old checkpoint dependency differs: {key}')
    new_locks = campaign.locks()
    updated = validated_update(state, new_locks)
    preview = copy.deepcopy(updated)
    next_plan = campaign.choose(preview)
    selected_ids = {row['selected_queue_id'] for row in state['completed']}
    if next_plan['id'] in selected_ids:
        raise RuntimeError('migration preview repeats a completed plan')
    sources = Counter(row['last_fault_source'] for row in state['completed'])
    MIGRATION.mkdir(parents=True, exist_ok=True)
    (MIGRATION / 'state.before_child_balance.json').write_bytes(before)
    (MIGRATION / 'progress.before_child_balance.json').write_bytes(
        progress_file.read_bytes())
    (MIGRATION / 'stage-status.before_child_balance.json').write_bytes(
        stage_file.read_bytes())
    campaign.atomic(state_file, updated)
    receipt = {
        'old_state_sha256': campaign.sha(MIGRATION / 'state.before_child_balance.json'),
        'new_state_sha256': campaign.sha(state_file),
        'old_runner_sha256': OLD_RUNNER_SHA,
        'new_runner_sha256': new_locks['rpc-stage/fuzz_rpc.py'],
        'completed_plans': len(state['completed']),
        'retained_queue_length': len(state['queue']),
        'source_counts_before': dict(sources),
        'next_plan_id': next_plan['id'],
        'next_plan_source': next_plan['sequence'][-1]['point']['sourceKey'],
        'next_plan_mode': next_plan['sequence'][-1]['fault_mode'],
        'migration_scope': 'scheduler-only; completed/queue/coverage unchanged',
    }
    campaign.atomic(MIGRATION / 'migration.json', receipt)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
