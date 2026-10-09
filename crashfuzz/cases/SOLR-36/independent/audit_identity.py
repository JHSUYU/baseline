#!/usr/bin/env python3
"""Recount postfault guards with the faulted logical child core preserved."""

from __future__ import annotations

import json
from pathlib import Path

from build import HERE
from fuzz import GUARDS, load_events


ROOT = HERE / 'campaign'
REPLICA = 'SOLR/REPLICA/'
SUBSHARD = 'SOLR/SUBSHARD/'


def affected_child(source: str) -> str | None:
    if source.startswith(REPLICA):
        return SUBSHARD + source[len(REPLICA):]
    return None


def main() -> None:
    state = json.loads((ROOT / 'state.json').read_text())
    reports = {case_id: [] for case_id in GUARDS}
    for row in state['completed']:
        events = load_events(Path(row['trace']).parent)
        applied = [event for event in events if event['event'] == 'IO_OBSERVED'
                   and event['applied']]
        last_fault = applied[-1] if applied else None
        for case_id, marker in GUARDS.items():
            guards = [event for event in events if event['event'] == 'TARGET_CHECK'
                      and event['marker'] == marker
                      and last_fault is not None and event['seq'] > last_fault['seq']
                      and event['sourceKey'].startswith(SUBSHARD + 'collection1/shard1_')]
            child = affected_child(last_fault['sourceKey']) if last_fault else None
            same = (any(event['sourceKey'] == child for event in guards)
                    if child else bool(guards))
            affected = {affected_child(event['sourceKey']) for event in applied}
            affected.discard(None)
            guard_sources = {event['sourceKey'] for event in guards}
            reports[case_id].append({
                'trial_number': row['trial_number'],
                'strict_injection': row['strict_injection'],
                'last_fault_source': last_fault['sourceKey'] if last_fault else None,
                'expected_child_for_last_fault': child,
                'postfault_any_child': bool(guards),
                'postfault_same_last_fault_child_or_collection_scope': bool(
                    row['strict_injection'] and same),
                'postfault_all_faulted_children': bool(
                    row['strict_injection'] and guards
                    and affected.issubset(guard_sources)),
                'postfault_guard_sources': sorted(guard_sources),
            })
    for case_id, trials in reports.items():
        report = {
            'case_id': case_id,
            'methodology': ('exact logical replica matching for the last fault; '
                            'collection-scoped faults may reach either child'),
            'fault_trials': len(trials),
            'strict_postfault_any_child': sum(
                item['strict_injection'] and item['postfault_any_child']
                for item in trials),
            'strict_postfault_same_last_fault_child_or_collection_scope': sum(
                item['postfault_same_last_fault_child_or_collection_scope']
                for item in trials),
            'strict_postfault_all_faulted_children': sum(
                item['postfault_all_faulted_children'] for item in trials),
            'trials': trials,
        }
        path = ROOT / f'identity-audit-{case_id}.json'
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(json.dumps({key: report[key] for key in report if key != 'trials'},
                         sort_keys=True))


if __name__ == '__main__':
    main()
