#!/usr/bin/env python3
"""Classify exact target outcomes in an unchanged original chaos JUnit run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from build import HERE
from fuzz import load_events, point


SOURCE = 'SOLR/SPLIT/collection1/shard1/PARENT_LEADER'
FINAL = {'SOLR-14': 'TARGET:SOLR14:CHECK',
         'SOLR-15': 'TARGET:SOLR15:FINAL',
         'SOLR-16': 'TARGET:SOLR16:FINAL'}
THROW = {'SOLR-14': 'TARGET:SOLR14:THROW',
         'SOLR-15': 'TARGET:SOLR15:THROW',
         'SOLR-16': 'TARGET:SOLR16:THROW'}


def plan_rows(path: Path) -> list[dict]:
    pairs = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            pairs[key] = value
    count = int(pairs['count'])
    return [{key: (int(pairs[f'step.{index}.{key}']) if key == 'hitOrdinal'
                   else pairs[f'step.{index}.{key}'])
             for key in ('marker', 'siteId', 'sourceKey', 'resource', 'hitOrdinal')
             if f'step.{index}.{key}' in pairs}
            for index in range(1, count + 1)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_name')
    args = parser.parse_args()
    directory = HERE / 'supplemental/shardsplit' / args.run_name
    run = json.loads((directory / 'run.json').read_text())
    assert run['test'].endswith('ShardSplitTest#testSplitWithChaosMonkey')
    events = load_events(directory)
    plan = plan_rows(Path(run['fault_plan']))
    applied = [event for event in events if event['event'] == 'IO_OBSERVED'
               and event['applied']]
    strict = len(applied) == len(plan) and all(
        all(point(event)[name] == value for name, value in item.items())
        for event, item in zip(applied, plan))
    last = applied[-1]['seq'] if applied else -1
    target = [event for event in events if event['sourceKey'] == SOURCE
              and event['event'] in ('TARGET_CHECK', 'TARGET_THROW')]
    counts = {case: {
        'post_fault_final_check': sum(event['event'] == 'TARGET_CHECK'
                                      and event['marker'] == marker
                                      and event['seq'] > last for event in target)
                                if strict else 0,
        'post_fault_exact_throw': sum(event['event'] == 'TARGET_THROW'
                                      and event['marker'] == THROW[case]
                                      and event['seq'] > last for event in target)
                                if strict else 0,
    } for case, marker in FINAL.items()}
    outer = sum(event['event'] == 'TARGET_CHECK'
                and event['marker'] == 'TARGET:SOLR15_16:OUTER'
                and event['seq'] > last for event in target) if strict else 0
    junit = re.search(r'SOLR_SPLIT_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)',
                      (directory / 'console.log').read_text())
    report = {
        'test': run['test'], 'seed': run['test_seed'],
        'agent_sha256': run['agent_sha256'],
        'elapsed_seconds': run['elapsed_seconds'],
        'junit_exit': run['exit_code'],
        'junit': tuple(map(int, junit.groups())) if junit else None,
        'planned_faults': len(plan), 'applied_faults': len(applied),
        'strict_injection': strict,
        'applied_events': applied,
        'target_outcomes': counts,
        'post_fault_outer_guard': outer,
        'classification': ('candidate_target_exception' if strict and any(
            row['post_fault_exact_throw'] for row in counts.values()) else
            'target_path_preserved' if strict and outer else
            'lost_target' if strict else 'unmatched'),
    }
    out = directory / 'audit.json'
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: report[key] for key in
                      ('elapsed_seconds', 'junit_exit', 'planned_faults',
                       'applied_faults', 'strict_injection',
                       'post_fault_outer_guard', 'target_outcomes',
                       'classification')}, sort_keys=True))


if __name__ == '__main__':
    main()
