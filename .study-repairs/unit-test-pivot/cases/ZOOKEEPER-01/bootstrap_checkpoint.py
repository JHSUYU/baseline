#!/usr/bin/env python3
"""Start a discovery-only campaign while excluding six prior selectors."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

BASE = Path('/users/ZhenyuLi/zk01-unit')
sys.path.insert(0, str(BASE / 'core-fuzzer'))
import fuzzer  # noqa: E402

CONFIG = BASE / 'campaign/case.json'
ROOT = BASE / 'campaign/results'
NAMES = ('tcp-connect-01', 'tcp-connect-02', 'tcp-xid1-01',
         'tcp-xid1-02', 'tcp-xid2-01', 'tcp-xid2-02')


def main() -> None:
    config = json.loads(CONFIG.read_text())
    fuzzer.validate(config)
    case_dir = ROOT / config['case_id']
    case_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = case_dir / 'state.json'
    if checkpoint.exists():
        raise FileExistsError('Existing campaign checkpoint: ' + str(checkpoint))
    target = config['target']
    state = {
        'schemaVersion': fuzzer.SCHEMA, 'case_id': config['case_id'],
        'system': config['system'], 'test_class': config['test_class'],
        'test_method': config['test_method'],
        'target_method': target['method'],
        'target_throw_method': target.get('throw_method', target['method']),
        'target_throw_site_id': target.get('throw_site_id'),
        'target_source_file': target.get('source_file'),
        'target_source_line': target.get('source_line'),
        'target_code': target.get('code'),
        'coverage_exclude_sites': target.get('coverage_exclude_sites', []),
        'coverage_include_prefixes': target.get('coverage_include_prefixes', []),
        'config_digest': fuzzer.fingerprint({
            key: value for key, value in config.items()
            if key not in {'budget', 'timeout_seconds'}}),
        'seed': None, 'coverage': [], 'queue': [], 'seen_sequences': [],
        'io_families': [], 'active_runtime_seconds': 0.0,
        'seed_runtime_seconds': 0.0, 'fault_runtime_seconds': 0.0,
        'setup_seconds': 0.0, 'build_seconds': 0.0,
        'active': None, 'completed': [], 'started': time.time(),
        'status': 'fuzzing', 'finished': False,
    }
    fuzzer.ensure_seed(config, state, case_dir)
    seed = state['seed']['feedback']
    if not seed['target_reached'] or not seed['points']:
        raise RuntimeError('Discovery seed lacks exact target or I/O points')
    seed_points = {fuzzer.fingerprint(point) for point in seed['points']}
    excluded = []
    for name in NAMES:
        prior_plan = json.loads((BASE / 'plans' / (name + '.json')).read_text())
        fault = prior_plan['faults'][0]
        point = {key: fault[key] for key in
                 ('marker', 'siteId', 'occurrence', 'sourceKey', 'hitOrdinal')}
        if fuzzer.fingerprint(point) not in seed_points:
            raise RuntimeError('Prior selector absent from new seed: ' + name)
        trace = BASE / 'runs' / name / 'trace/runtime_trace.jsonl'
        feedback = fuzzer.trace_feedback(trace, target, config.get('io_scope'))
        exact = (feedback['matched_count'] == 1 and
                 feedback['applied_count'] == 1 and
                 feedback['applied_points'] == [point] and
                 feedback['applied_fault_ids'] == [fault['faultId']])
        if not exact:
            raise RuntimeError('Prior selector was not applied exactly: ' + name)
        old = json.loads((BASE / 'runs' / name / 'feedback.json').read_text())
        identifier = fuzzer.sequence_id([point])
        state['queue'] = [item for item in state['queue'] if item['id'] != identifier]
        # ensure_seed already recorded this ID in seen_sequences. It remains
        # excluded from future mutation, yet it is not a completed new trial.
        excluded.append({
            'name': name, 'sequence_id': identifier,
            'exact_applied': True,
            'post_fault_source_check_reached': feedback['target_reached_after_fault'],
            'post_fault_global_tracker_reached':
                old['global_target_retained_after_fault'],
            'historical_elapsed_seconds': old['total_seconds'],
            'historical_trace_mode': 'region-state',
            'not_counted_in_new_budget_or_coverage': True,
        })
    state['excluded_legacy_sequences'] = [row['sequence_id'] for row in excluded]
    fuzzer.atomic_json(checkpoint, state)
    fuzzer.write_case_result(case_dir, state)
    audit = {
        'schema_version': 1,
        'new_methodology': 'coverage_io_discovery_no_graph',
        'new_seed_trace_mode': 'discovery',
        'old_selection_methodology': 'closure_guided',
        'old_trace_mode': 'region-state',
        'selectors_identical_in_new_seed': len(excluded),
        'exact_applied_old_trials': len(excluded),
        'old_post_fault_site_reach': sum(row['post_fault_source_check_reached']
                                         for row in excluded),
        'old_post_fault_global_tracker_reach': sum(
            row['post_fault_global_tracker_reached'] for row in excluded),
        'excluded_from_new_trial_count': True,
        'excluded_from_new_coverage_feedback': True,
        'trials': excluded,
    }
    fuzzer.atomic_json(case_dir / 'legacy-reassessment.json', audit)
    print(json.dumps({'new_completed': 0, 'excluded_old': len(excluded),
                      'new_queue': len(state['queue'])}))


if __name__ == '__main__':
    main()
