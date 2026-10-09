#!/usr/bin/env python3
"""Verify exact original-JUnit target reach and list stable fault-point identities."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re


TARGET = 'SOLR/FORCE_LEADER/forceleader_lower_terms_collection/shard1'


def audit(directory: Path) -> dict:
    run = json.loads((directory / 'run.json').read_text())
    log = (directory / 'console.log').read_text()
    match = re.search(r'SOLR_FORCE_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)', log)
    if not match:
        raise RuntimeError(f'original JUnit gate missing in {directory}')
    gate = tuple(map(int, match.groups()))
    events = [json.loads(line) for line in (directory / 'events.jsonl').read_text().splitlines()]
    enters = [event for event in events if event['event'] == 'TARGET_ENTER'
              and event['sourceKey'] == TARGET]
    leaders = [event for event in events if event['event'] == 'LEADER_OBSERVED'
               and event['sourceKey'] == TARGET]
    guards = [event for event in events if event['event'] == 'TARGET_CHECK'
              and event['sourceKey'] == TARGET]
    throws = [event for event in events if event['event'] == 'TARGET_THROW'
              and event['sourceKey'] == TARGET]
    if gate == (1, 0, 0) and run['exit_code'] == 0:
        assert len(enters) == len(leaders) == len(guards) == 1
        assert leaders[0]['seq'] < guards[0]['seq']
    guard_seq = guards[0]['seq'] if guards else None
    entry_seq = enters[0]['seq'] if enters else None
    before = [event for event in events if event['event'] == 'IO_OBSERVED'
              and guard_seq is not None and event['seq'] < guard_seq]
    eligible = [event for event in before
                if not event['sourceKey'].startswith('UNRESOLVED:')
                and not event['siteId'].startswith('UNRESOLVED:')
                and 'UNRESOLVED' not in event['resource']
                and event['resource'].startswith('/collections/forceleader_lower_terms_collection')]
    target_window = [event for event in eligible if entry_seq is not None
                     and event['seq'] > entry_seq and event['threadId'] == guards[0]['threadId']]
    families = Counter((event['marker'], event['siteId'], event['sourceKey'], event['resource'])
                       for event in eligible)
    report = {
        'original_junit': {'ran': gate[0], 'ignored': gate[1], 'failures': gate[2]},
        'original_test_passed': gate == (1, 0, 0) and run['exit_code'] == 0,
        'agent_sha256': run.get('agent_sha256'),
        'classpath_contains_graphchecker': run['classpath_contains_graphchecker'],
        'elapsed_seconds': run['elapsed_seconds'],
        'target_source': TARGET,
        'target_enter_count': len(enters),
        'target_guard_count': len(guards),
        'target_throw_count': len(throws),
        'leader_observations': [{'detail': event['detail'],
                                 'physical_node': event['physicalNode']}
                                for event in leaders],
        'observed_io_before_target': len(before),
        'eligible_exact_collection_io_before_target': len(eligible),
        'eligible_target_thread_io_before_guard': len(target_window),
        'eligible_io_families': len(families),
        'target_window_points': [{k: event[k] for k in
                                  ('seq', 'marker', 'siteId', 'sourceKey', 'resource',
                                   'hitOrdinal', 'physicalNode', 'threadId')}
                                 for event in target_window],
        'eligible_family_counts': [
            {'marker': key[0], 'siteId': key[1], 'sourceKey': key[2],
             'resource': key[3], 'count': count}
            for key, count in sorted(families.items())],
    }
    (directory / 'seed-audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = audit(args.directory)
    print(json.dumps({key: result[key] for key in
                      ('original_test_passed', 'target_guard_count', 'target_throw_count',
                       'leader_observations', 'eligible_exact_collection_io_before_target',
                       'eligible_target_thread_io_before_guard', 'eligible_io_families')},
                     sort_keys=True))
