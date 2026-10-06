#!/usr/bin/env python3
"""Atomically publish HDFS-09 checkpoint progress for the node0 checklist."""
from __future__ import annotations

from datetime import datetime, timezone
import json

from campaign import HERE, parse
from expand_campaign import OUT, ORIGINAL_COUNT, atomic, prod


def split(ids):
    return {
        'method_entry_ids': sum(x.startswith('METHOD:') for x in ids),
        'branch_outcome_ids': sum(x.startswith('BRANCH:') for x in ids),
        'total_ids': len(ids),
    }


def publish() -> dict:
    checkpoint = json.loads((OUT / 'checkpoint.json').read_text())
    result = json.loads((HERE / 'result.json').read_text())
    original = result['trials'][:ORIGINAL_COUNT]
    if len(original) != ORIGINAL_COUNT:
        raise RuntimeError('the 16 original trial rows must remain intact')
    coverage = result['coverage']
    original_union = coverage.setdefault('pre_expansion_fault_union',
                                         dict(coverage['fault_union']))
    original_gain = coverage.setdefault('pre_expansion_gain', dict(coverage['gain']))
    rows = []
    new_ids = set()
    for trial in checkpoint['results']:
        trial_path = HERE / trial['trace']
        if 'coverage_method_ids' not in trial:
            production = prod(parse(trial_path)['coverage'])
            trial['coverage_method_ids'] = sum(x.startswith('METHOD:') for x in production)
            trial['coverage_branch_outcome_ids'] = sum(x.startswith('BRANCH:') for x in production)
        new_ids.update(trial['production_gain_id_list'])
        row = dict(trial)
        row['selector'] = trial['sequence']
        row['selector_json'] = json.dumps(trial['sequence'], sort_keys=True,
                                          separators=(',', ':'))
        row['new_production_id_list'] = trial['production_gain_id_list']
        row['new_production_ids_vs_prior_trials'] = trial['production_gain_ids']
        rows.append(row)
    atomic(OUT / 'checkpoint.json', checkpoint)
    all_rows = original + rows
    started = datetime.fromisoformat(result['started_at_utc'].replace('Z', '+00:00'))
    current = datetime.now(timezone.utc)
    lost = sum(row['status'] == 'lost_target' for row in all_rows)
    result.update({
        'status': 'pending_budget_expansion' if not checkpoint.get('stop_reason') else
                  'bounded_assessment_complete',
        'campaign_finished': bool(checkpoint.get('stop_reason')),
        'fault_trials': len(all_rows),
        'sequence_expansion_trials': len(rows),
        'planned_trial_budget': checkpoint['trial_budget'],
        'planned_max_faults_per_trial': checkpoint['max_faults_per_trial'],
        'max_faults_per_trial': max((len(row['sequence']) for row in rows), default=1),
        'requested_fault_events': ORIGINAL_COUNT + sum(len(row['sequence']) for row in rows),
        'strict_injection_trials': sum(bool(row['strict_injection']) for row in all_rows),
        'matched_fault_events': sum(row['matched_count'] for row in all_rows),
        'applied_fault_events': sum(row['applied_count'] for row in all_rows),
        'target_after_fault_trials': sum(bool(row['target_reached_after_fault']) for row in all_rows),
        'target_lost_trials': lost,
        'valid_target_trials': sum(bool(row['strict_injection'] and
                                        row['target_reached_after_fault']) for row in all_rows),
        'target_fatal_trials': sum(row['target_fatal_exception_count'] > 0 for row in all_rows),
        'junit_pass_trials': sum(row['junit_exit'] == 0 for row in all_rows),
        'trial_wall_seconds': round(sum(row['trial_wall_seconds'] for row in all_rows), 3),
        'junit_trial_seconds': round(sum(row['junit_seconds'] for row in all_rows), 3),
        'elapsed_seconds': round((current - started).total_seconds(), 3),
        'updated_at_utc': current.isoformat(),
        'trials': all_rows,
        'stop_reason': checkpoint.get('stop_reason') or
                       f'expansion in progress: {len(all_rows)}/{checkpoint["trial_budget"]} attempted; '
                       f'{lost} lost the selected target and are not valid target trials',
    })
    result['phase_trial_wall_seconds']['sequence_expansion'] = round(
        sum(row['trial_wall_seconds'] for row in rows), 3)
    coverage['fault_union'] = {
        'method_entry_ids': original_union['method_entry_ids'] +
                            sum(x.startswith('METHOD:') for x in new_ids),
        'branch_outcome_ids': original_union['branch_outcome_ids'] +
                              sum(x.startswith('BRANCH:') for x in new_ids),
        'total_ids': original_union['total_ids'] + len(new_ids),
    }
    coverage['gain'] = {
        'method_entry_ids': original_gain['method_entry_ids'] +
                            sum(x.startswith('METHOD:') for x in new_ids),
        'branch_outcome_ids': original_gain['branch_outcome_ids'] +
                              sum(x.startswith('BRANCH:') for x in new_ids),
        'total_ids': original_gain['total_ids'] + len(new_ids),
    }
    coverage['excluded_probe_branch_ids'] = (
        'Client.getRpcResponse #u44/#u49/#u54 and direct file probe '
        'BestEffortLongFile.set #u100000 and #u100100-#u100499')
    result['evidence']['expansion_checkpoint'] = 'expansion/checkpoint.json'
    result['evidence']['expansion_ledger'] = 'expansion/trial-ledger.csv'
    result['evidence']['discovery_healthy_trace'] = 'discovery-healthy/trace/runtime_trace.jsonl'
    result['runtime_probe_dependency']['trace_mode'] = 'discovery'
    result['runtime_probe_dependency']['region_skeletons_required'] = False
    if checkpoint.get('stop_reason'):
        result['completed_at_utc'] = current.isoformat()
    else:
        result.pop('completed_at_utc', None)
    if any(row['target_fatal_exception_count'] > 0 for row in rows):
        result['bug_mark'] = 'target_exception_candidate_requires_replay'
    atomic(HERE / 'result.json', result)
    return result


if __name__ == '__main__':
    result = publish()
    print(json.dumps({key: result[key] for key in
                      ('status', 'fault_trials', 'valid_target_trials',
                       'target_lost_trials', 'elapsed_seconds')}))
