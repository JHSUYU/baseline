#!/usr/bin/env python3
"""Verify one exact fault and same-replica target preservation."""

from __future__ import annotations

import json
from pathlib import Path
import re

from build import HERE

FIELDS = ('marker', 'siteId', 'sourceKey', 'resource', 'hitOrdinal')


def main() -> None:
    base = HERE / 'calibration'
    attempt = base / 'attempt-01'
    selected = json.loads((base / 'selection.json').read_text())['selection']
    events = [json.loads(line) for line in (attempt / 'events.jsonl').open()]
    applied = [event for event in events
               if event['event'] == 'IO_OBSERVED' and event['applied']]
    summaries = [event['detail'] for event in events if event['event'] == 'SUMMARY']
    strict = (len(applied) == 1 and all(applied[0][field] == selected[field]
                                        for field in FIELDS)
              and summaries == ['applied=1/1'])
    last_fault = applied[0]['seq'] if strict else -1
    guards = [event for event in events if event['event'] == 'TARGET_CHECK'
              and event['marker'] == 'SOLR38:LEADER_IDENTITY_GUARD']
    same_replica_after = [event for event in guards
                          if strict and event['seq'] > last_fault
                          and event['sourceKey'] == selected['sourceKey']]
    throws = [event for event in events if event['event'] == 'TARGET_THROW'
              and event['marker'] == 'SOLR38:LEADER_IDENTITY_THROW']
    metadata = json.loads((attempt / 'run.json').read_text())
    log = (attempt / 'console.log').read_text(errors='replace')
    gate_match = re.search(r'SOLR38_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)', log)
    gate = tuple(map(int, gate_match.groups())) if gate_match else None
    report = {
        'exact_fault_applied': strict,
        'same_replica_target_after_fault': len(same_replica_after),
        'all_target_guard_count': len(guards),
        'exact_target_throw_after_fault': sum(event['seq'] > last_fault for event in throws),
        'original_junit': {'ran_ignored_failures': gate,
                           'passed': gate == (1, 0, 0) and metadata['exit_code'] == 0},
        'elapsed_seconds': metadata['elapsed_seconds'],
        'selected_fault': selected,
        'methodology': 'coverage_io_no_graph',
    }
    (base / 'audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))
    if not strict or not same_replica_after or not report['original_junit']['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
