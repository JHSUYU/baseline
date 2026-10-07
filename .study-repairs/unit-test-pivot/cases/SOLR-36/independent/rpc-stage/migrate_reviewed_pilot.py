#!/usr/bin/env python3
"""One-time audited migration of the frozen SOLR-36 role-V2 first trial."""

from __future__ import annotations

import json
from pathlib import Path

import fuzz_rpc as campaign


OLD_RUNNER_SHA = 'acc0cf7d321f9bae20620dea1b2d4b6cbd3186f282bd352408028a1b905e05e7'
FIRST_ID = '82ec14e4a3e1cf168995'
MIGRATION = campaign.ROOT / 'migrations' / '0001-effect-time-reviewed-503'


def main() -> None:
    state_file = campaign.ROOT / 'state.json'
    progress_file = campaign.ROOT / 'progress.json'
    if MIGRATION.exists():
        raise RuntimeError('migration already exists; refusing to repeat')
    old_state_bytes = state_file.read_bytes()
    state = json.loads(old_state_bytes)
    if (state['status'] != 'candidate_target_exception'
            or len(state['completed']) != 1
            or state['active'] is not None
            or state['completed'][0]['selected_queue_id'] != FIRST_ID
            or state['locks']['rpc-stage/fuzz_rpc.py'] != OLD_RUNNER_SHA):
        raise RuntimeError('checkpoint is not the exact frozen first candidate')
    old_runner = MIGRATION.parent / '.fuzz_rpc.before.py'
    if not old_runner.is_file() or campaign.sha(old_runner) != OLD_RUNNER_SHA:
        raise RuntimeError('byte-for-byte old runner backup is missing')
    old_locks = dict(state['locks'])
    for key, expected in old_locks.items():
        path = campaign.PARENT / key
        if key == 'rpc-stage/fuzz_rpc.py':
            path = old_runner
        if campaign.sha(path) != expected:
            raise RuntimeError(f'old lock mismatch: {key}')
    row = state['completed'][0]
    run = campaign.ROOT / 'trials' / f'0001-{FIRST_ID}' / 'attempt-01'
    seed_probes = set().union(*(campaign.production_probes(seed)
                                for seed in campaign.SEEDS))
    seed_selectors = {campaign.point_id(campaign.point(event))
                      for seed in campaign.SEEDS
                      for event in campaign.rpc_events(seed)}
    analysis_state = {'covered_probes': sorted(seed_probes),
                      'observed_rpc_selectors': sorted(seed_selectors)}
    recounted, probes, selectors = campaign.analyze(
        run, row['sequence'], analysis_state)
    if (not recounted['strict_injection']
            or recounted['postfault_same_child_guards'] != {'SOLR-36': 1, 'SOLR-37': 0}
            or recounted['postfault_same_child_throws'] != {'SOLR-36': 1, 'SOLR-37': 0}
            or recounted['fault_effect_boundary_seq'] != 3983
            or not recounted['reviewed_expected_target_rejection']
            or recounted['junit_gate'] != (1, 0, 0)
            or recounted['junit_exit'] != 0
            or recounted['new_production_probes'] != row['new_production_probes']
            or recounted['new_exact_rpc_selectors'] != row['new_exact_rpc_selectors']
            or set(state['covered_probes']) != seed_probes | probes
            or set(state['observed_rpc_selectors']) != seed_selectors | selectors):
        raise RuntimeError('offline recount differs from the frozen pilot')
    old_row = dict(row)
    row.update(recounted)
    state['locks'] = campaign.locks()
    state['status'] = 'budget_complete'
    if (len(state['completed']) != 1 or state['active'] is not None
            or row['selected_queue_id'] != FIRST_ID):
        raise RuntimeError('migration changed plan identity')
    MIGRATION.mkdir(parents=True)
    (MIGRATION / 'state.before.json').write_bytes(old_state_bytes)
    (MIGRATION / 'progress.before.json').write_bytes(progress_file.read_bytes())
    campaign.atomic(run / 'audit.json', row)
    campaign.atomic(state_file, state)
    campaign.publish(state)
    record = {
        'classification': 'expected_target_rejection',
        'new_bug': False,
        'case_ids': ['SOLR-36', 'SOLR-37'],
        'old_state_sha256': campaign.sha(MIGRATION / 'state.before.json'),
        'new_state_sha256': campaign.sha(state_file),
        'old_runner_sha256': OLD_RUNNER_SHA,
        'new_runner_sha256': campaign.sha(campaign.HERE / 'fuzz_rpc.py'),
        'old_locks': old_locks,
        'new_locks': state['locks'],
        'selected_plan_id': FIRST_ID,
        'original_trial_count': 1,
        'retained_queue_length': len(state['queue']),
        'old_row_summary': {key: old_row.get(key) for key in
                            ('strict_injection', 'postfault_same_child_guards',
                             'postfault_same_child_throws', 'new_production_probes',
                             'new_exact_rpc_selectors')},
        'recount_summary': {key: recounted.get(key) for key in
                            ('strict_injection', 'fault_effect_boundary_seq',
                             'postfault_same_child_guards',
                             'postfault_same_child_throws',
                             'reviewed_expected_target_rejection',
                             'new_production_probes', 'new_exact_rpc_selectors')},
        'source_review': str(campaign.ROOT / 'candidates' /
                             '0001-role-v2' / 'source-review.md'),
        'raw_trace_sha256': campaign.sha(run / 'events.jsonl'),
    }
    campaign.atomic(MIGRATION / 'migration.json', record)
    print(json.dumps(record, sort_keys=True))


if __name__ == '__main__':
    main()
