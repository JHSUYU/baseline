#!/usr/bin/env python3
"""Recount actor identity, target outcomes, timing, and extension novelty."""

from __future__ import annotations

import json
from pathlib import Path

import campaign_v2 as c


def main() -> None:
    state = json.loads((c.ROOT / 'state.json').read_text())
    build = json.loads((c.HERE / 'build-v2.json').read_text())
    if state['agent_sha256'] != build['agent_sha256']:
        raise RuntimeError('checkpoint agent mismatch')
    if state['runner_sha256'] != c.runner_hashes():
        raise RuntimeError('checkpoint runner mismatch')
    attempted = state['attempted']
    completed = state['completed']
    if completed != [row for row in attempted if row['target_preserved']]:
        raise RuntimeError('effective-trial accounting mismatch')
    audited = []
    for row in attempted:
        events = c.load_events(Path(row['trace']).parent)
        applied = [event for event in events if event['event'] == 'IO_OBSERVED'
                   and event['applied']]
        guards = c.guard_events(events)
        throws = [event for event in events if event['event'] == 'TARGET_THROW'
                  and event['marker'] == c.THROW
                  and event['sourceKey'] == c.TARGET
                  and 'The shard already has an active leader' in event['detail']]
        strict = len(applied) == len(row['fault_sequence']) and all(
            c.bound_event(event)
            and c.point_id(c.point(event)) == c.point_id(point)
            for event, point in zip(applied, row['fault_sequence']))
        summary = [event for event in events if event['event'] == 'SUMMARY']
        strict = strict and len(summary) == 1 and summary[0]['detail'] == (
            f'applied={len(applied)}/{len(row["fault_sequence"])}')
        last = applied[-1]['seq'] if applied else -1
        retained = strict and any(event['seq'] > last for event in guards)
        if strict != row['strict_injection'] or retained != row['target_preserved']:
            raise RuntimeError(f'trial {row["trial_number"]} raw trace/checkpoint mismatch')
        audited.append({
            'trial_number': row['trial_number'],
            'attempts': row['attempts'],
            'planned_faults': len(row['fault_sequence']),
            'applied_faults': len(applied),
            'strict_actor_bound_injection': strict,
            'target_guard_after_last_fault': sum(event['seq'] > last for event in guards)
                                              if strict else 0,
            'exact_target_throw_after_last_fault': sum(event['seq'] > last for event in throws)
                                                   if strict else 0,
            'junit_exit': row['junit_exit'],
            'junit_gate': row['junit_gate'],
            'status': row['status'],
            'elapsed_seconds': row['elapsed_seconds'],
            'new_production_probes': row['new_production_probes'],
            'new_actor_bound_io_families': row['new_io_families'],
        })
    last8 = completed[-8:]
    extension_novelty = any(row['new_production_probes'] > 0
                            or row['new_io_families'] > 0 for row in last8)
    report = {
        'case_id': 'SOLR-31',
        'status': state['status'],
        'budget': state['budget'],
        'selected_sequences': len(attempted),
        'effective_trials': len(completed),
        'total_junit_attempts': sum(row['attempts'] for row in attempted),
        'strict_injections': sum(row['strict_injection'] for row in attempted),
        'post_fault_target_reach_trials': len(completed),
        'passing_junit_trials': sum(row['junit_gate'] == [1, 0, 0]
                                    and row['junit_exit'] == 0 for row in attempted),
        'nonpassing_effective_trials': [row['trial_number'] for row in completed
                                        if row['junit_gate'] != [1, 0, 0]
                                        or row['junit_exit'] != 0],
        'lost_target_sequences': [row['trial_number'] for row in attempted
                                  if row['status'] == 'lost_target'],
        'exact_target_throw_after_fault_trials': sum(
            row['exact_target_throw_after_last_fault'] > 0 for row in completed),
        'elapsed_junit_seconds': round(sum(row['elapsed_seconds'] for row in attempted), 3),
        'production_probe_gain': len(state['covered_probes']) - state['seed_probe_count'],
        'actor_bound_io_family_gain': len(state['io_families']) - state['seed_io_family_count'],
        'last8_effective_novelty': extension_novelty,
        'extend_to_128_max10': len(completed) >= 80 and extension_novelty,
        'trials': audited,
    }
    path = c.ROOT / 'audit-v2.json'
    c.atomic(path, report)
    print(json.dumps({key: report[key] for key in (
        'status', 'selected_sequences', 'effective_trials', 'total_junit_attempts',
        'exact_target_throw_after_fault_trials', 'last8_effective_novelty')}, sort_keys=True))


if __name__ == '__main__':
    main()
