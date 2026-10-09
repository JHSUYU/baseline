#!/usr/bin/env python3
"""Check exact fault application, Solr's retry, and target preservation."""

from __future__ import annotations

import json
from pathlib import Path
import re

from build import HERE


ROOT = HERE / 'calibration'
TRIAL = ROOT / 'watch-exists'


def main() -> None:
    selected = json.loads((ROOT / 'selection.json').read_text())
    identity = selected['logical_identity']
    run = json.loads((TRIAL / 'run.json').read_text())
    events = [json.loads(line) for line in (TRIAL / 'events.jsonl').read_text().splitlines()]
    log = (TRIAL / 'console.log').read_text()
    match = re.search(r'SOLR_FORCE_ORIGINAL_JUNIT ran=(\d+) ignored=(\d+) failures=(\d+)', log)
    junit = tuple(map(int, match.groups())) if match else None
    applied = [event for event in events if event['event'] == 'IO_OBSERVED'
               and event['applied']]
    summaries = [event for event in events if event['event'] == 'SUMMARY']
    assert len(applied) == 1 and len(summaries) == 1
    assert summaries[0]['detail'] == 'applied=1/1'
    fault = applied[0]
    assert all(fault[field] == value for field, value in identity.items())
    assert run['agent_sha256'] == selected['agent_sha256']
    retries = [event for event in events if event['event'] == 'IO_OBSERVED'
               and event['seq'] > fault['seq']
               and all(event[field] == identity[field]
                       for field in ('marker', 'siteId', 'sourceKey', 'resource'))
               and event['hitOrdinal'] == fault['hitOrdinal'] + 1
               and event['threadId'] == fault['threadId']]
    guards = [event for event in events if event['event'] == 'TARGET_CHECK'
              and event['sourceKey'] == identity['sourceKey']
              and event['seq'] > fault['seq']]
    leaders = [event for event in events if event['event'] == 'LEADER_OBSERVED'
               and event['sourceKey'] == identity['sourceKey']
               and event['seq'] > fault['seq']]
    throws = [event for event in events if event['event'] == 'TARGET_THROW'
              and event['sourceKey'] == identity['sourceKey']
              and event['seq'] > fault['seq']]
    report = {
        'exact_fault_applied': True,
        'fault_event': fault,
        'same_operation_retry': bool(retries),
        'retry_event': retries[0] if retries else None,
        'target_guard_after_fault': len(guards),
        'leader_after_fault': [event['detail'] for event in leaders],
        'exact_target_throw_after_fault': len(throws),
        'original_junit': {'ran': junit[0], 'ignored': junit[1], 'failures': junit[2]}
                         if junit else None,
        'original_junit_passed': junit == (1, 0, 0) and run['exit_code'] == 0,
        'elapsed_seconds': run['elapsed_seconds'],
        'test_seed': run['test_seed'],
        'agent_sha256': run['agent_sha256'],
        'classpath_contains_graphchecker': run['classpath_contains_graphchecker'],
    }
    (ROOT / 'audit.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({key: report[key] for key in
                      ('exact_fault_applied', 'same_operation_retry',
                       'target_guard_after_fault', 'exact_target_throw_after_fault',
                       'original_junit_passed', 'elapsed_seconds')}, sort_keys=True))


if __name__ == '__main__':
    main()
