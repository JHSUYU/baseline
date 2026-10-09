#!/usr/bin/env python3
"""Read-only raw-trace recount of the two original sub-shard guard operands."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE / 'campaign'
MARKERS = {
    'SOLR-36': ('SOLR36:ACTIVE_SUBSHARD_GUARD',
                'SOLR36:ACTIVE_SUBSHARD_THROW'),
    'SOLR-37': ('SOLR37:CHILD_RANGE_SUBSET_GUARD',
                'SOLR37:CHILD_RANGE_THROW'),
}


def point(event: dict) -> dict:
    return {key: event[key] for key in
            ('marker', 'siteId', 'sourceKey', 'resource', 'hitOrdinal')}


def source_for_last_fault(source: str) -> str | None:
    if source.startswith('SOLR/REPLICA/'):
        return source.replace('SOLR/REPLICA/', 'SOLR/SUBSHARD/', 1)
    return None


def main() -> None:
    state_file = ROOT / 'state.json'
    state_bytes = state_file.read_bytes()
    state = json.loads(state_bytes)
    rows = state['completed']
    counters = {case_id: {
        'all_guard_operands': Counter(),
        'post_same_child_guard_operands': Counter(),
        'strict_post_same_child_trials': 0,
        'exact_target_throw_after_fault_trials': 0,
        'selected_condition_true_events': 0,
        'trial_checks': [],
    } for case_id in MARKERS}
    junit_passed = 0
    strict_trials = 0
    for row in rows:
        events = [json.loads(line) for line in Path(row['trace']).open()
                  if line.strip()]
        applied = [event for event in events
                   if event['event'] == 'IO_OBSERVED' and event['applied']]
        sequence = row['fault_sequence']
        exact = (len(applied) == len(sequence)
                 and all(point(event) == selected for event, selected
                         in zip(applied, sequence)))
        if exact != row['strict_injection']:
            raise RuntimeError(f'trial {row["trial_number"]} strict mismatch')
        strict_trials += exact
        junit_passed += row['junit_gate'] == [1, 0, 0] and row['junit_exit'] == 0
        if not applied:
            raise RuntimeError(f'trial {row["trial_number"]} has no applied fault')
        last = applied[-1]
        expected_child = source_for_last_fault(last['sourceKey'])
        for case_id, (guard_marker, throw_marker) in MARKERS.items():
            found = [event for event in events
                     if event['event'] == 'TARGET_CHECK'
                     and event['marker'] == guard_marker
                     and event['sourceKey'].startswith(
                         'SOLR/SUBSHARD/collection1/shard1_')]
            post = [event for event in found if event['seq'] > last['seq']
                    and (expected_child is None
                         or event['sourceKey'] == expected_child)]
            throws = [event for event in events
                      if event['event'] == 'TARGET_THROW'
                      and event['marker'] == throw_marker
                      and event['seq'] > last['seq']
                      and (expected_child is None
                           or event['sourceKey'] == expected_child)]
            data = counters[case_id]
            data['all_guard_operands'].update(event['detail'] for event in found)
            data['post_same_child_guard_operands'].update(
                event['detail'] for event in post)
            data['strict_post_same_child_trials'] += exact and bool(post)
            data['exact_target_throw_after_fault_trials'] += exact and bool(throws)
            data['selected_condition_true_events'] += sum(
                ('state=active;' in event['detail'].lower()
                 if case_id == 'SOLR-36'
                 else 'subset=false;' in event['detail'].lower())
                for event in found)
            data['trial_checks'].append({
                'trial_number': row['trial_number'],
                'strict': exact,
                'junit_passed': row['junit_gate'] == [1, 0, 0]
                                and row['junit_exit'] == 0,
                'planned_faults': row['planned_faults'],
                'post_same_child_guard_count': len(post),
                'exact_throw_after_fault_count': len(throws),
            })
    report = {
        'source_state_sha256': hashlib.sha256(state_bytes).hexdigest(),
        'campaign_status': state['status'],
        'fault_trials': len(rows),
        'strict_trials': strict_trials,
        'junit_passed_trials': junit_passed,
        'cases': counters,
    }
    destination = ROOT / 'source-review-recount.json'
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({case_id: {key: value for key, value in data.items()
                                if key != 'trial_checks'}
                      for case_id, data in counters.items()}, sort_keys=True))


if __name__ == '__main__':
    main()
