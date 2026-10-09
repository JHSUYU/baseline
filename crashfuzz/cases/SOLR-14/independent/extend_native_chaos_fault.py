#!/usr/bin/env python3
"""Append one observed retry at the selected second leader read."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build import HERE
from fuzz import load_events, point, point_id, write_plan


ROOT = HERE / 'supplemental/shardsplit'
SOURCE = 'SOLR/SPLIT/collection1/shard1/PARENT_LEADER'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous_run')
    parser.add_argument('child_number', type=int)
    args = parser.parse_args()
    if not 2 <= args.child_number <= 8:
        raise SystemExit('child fault count must be 2..8')
    directory = ROOT / args.previous_run
    audit = json.loads((directory / 'audit.json').read_text())
    if not audit['strict_injection'] or not audit['post_fault_outer_guard']:
        raise RuntimeError('previous exact sequence did not preserve target outer guard')
    if len(audit['applied_events']) != args.child_number - 1:
        raise RuntimeError('new sequence must add exactly one fault')
    if any(row['post_fault_exact_throw'] for row in audit['target_outcomes'].values()):
        raise RuntimeError('candidate exact target exception requires replay/review, not mutation')
    events = load_events(directory)
    prior = [point(event) for event in audit['applied_events']]
    last = audit['applied_events'][-1]
    outer = next(event['seq'] for event in events
                 if event['event'] == 'TARGET_CHECK'
                 and event['marker'] == 'TARGET:SOLR15_16:OUTER'
                 and event['sourceKey'] == SOURCE and event['seq'] > last['seq'])
    subsequent = [event for event in events
                  if event['event'] == 'IO_OBSERVED'
                  and last['seq'] < event['seq'] < outer
                  and all(event[key] == last[key] for key in
                          ('marker', 'siteId', 'sourceKey', 'resource', 'threadId', 'physicalNode'))
                  and event['hitOrdinal'] == last['hitOrdinal'] + 1]
    if not subsequent:
        raise RuntimeError('no observed same-thread retry before target outer guard')
    selected = subsequent[0]
    child = prior + [point(selected)]
    assert all(point_id(child[i]) != point_id(child[i+1])
               for i in range(len(child) - 1))
    plan = ROOT / f'native-chaos-plan-{args.child_number:02d}.properties'
    write_plan(plan, child)
    record = {
        'parent_run': args.previous_run,
        'parent_audit': str(directory / 'audit.json'),
        'child_plan': str(plan),
        'fault_sequence': child,
        'new_observed_retry': selected,
        'parent_post_fault_outer_seq': outer,
    }
    selection = ROOT / f'native-chaos-plan-{args.child_number:02d}-selection.json'
    selection.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print(selection)


if __name__ == '__main__':
    main()
